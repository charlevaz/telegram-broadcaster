import streamlit as st
import requests
import gspread 
from google.oauth2.service_account import Credentials
import pandas as pd
import logging
import json 
from gspread.auth import DEFAULT_SCOPES 
import uuid 
from datetime import datetime, timedelta
import hashlib 

# ====================================================================
# 🚨 1. CONFIGURAÇÃO E LOGGING
# ====================================================================

LOG_FILE = 'disparo_telegram.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ====================================================================
# 🚨 2. CONFIGURAÇÃO DO APP E ESTADO DE SESSÃO
# ====================================================================

# ⚠️ A configuração de página DEVE ser a primeira linha do Streamlit
st.set_page_config(page_title="Broadcaster Telegram | Grupo CR", layout="wide")

BOT_TOKEN = "8586446411:AAH_jXK0Yv6h64gRLhoK3kv2kJo4mG5x3LE" 
CREDENTIALS_FILE = '/home/charle/scripts/chaveBigQuery.json' 
SHEET_ID = '1HSIwFfIr67i9K318DX1qTwzNtrJmaavLKUlDpW5C6xU' 
WORKSHEET_NAME_TELEGRAM = 'lista_telegram' 
WORKSHEET_NAME_AUTORIZACAO = 'autorizacao' 
WORKSHEET_NAME_ERROS = 'erro' 

USER_CREDENTIALS = {
    "operação": "820628", 
    "charle": "966365"    
}
ADMIN_USERS = ["charle"] 

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'PERMANENT_LOGIN' not in st.session_state:
    st.session_state['logged_in'] = st.session_state.get('PERMANENT_LOGIN', False)

# ====================================================================
# 🌐 3. FUNÇÕES DE CONEXÃO E BANCO DE DADOS
# ====================================================================

def get_gspread_client():
    """Retorna o cliente gspread autenticado (Cloud ou Local)."""
    try:
        if 'google_service_account' in st.secrets:
            creds_info = dict(st.secrets["google_service_account"]) 
            creds_info['private_key'] = creds_info['private_key'].replace('\\n', '\n')
            creds = Credentials.from_service_account_info(creds_info, scopes=DEFAULT_SCOPES)
        else:
            creds = Credentials.from_json_keyfile_name(CREDENTIALS_FILE, scopes=DEFAULT_SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        logger.critical(f"Falha na Autenticação GSpread: {e}")
        return None

def registrar_erro_planilha(chat_id, nome, motivo):
    """Grava o log de erro diretamente na aba 'erro'."""
    try:
        client = get_gspread_client()
        if not client: return
        sheet = client.open_by_key(SHEET_ID)
        try:
            ws_erro = sheet.worksheet(WORKSHEET_NAME_ERROS)
        except gspread.WorksheetNotFound:
            ws_erro = sheet.add_worksheet(title=WORKSHEET_NAME_ERROS, rows="100", cols="4")
            ws_erro.update('A1:D1', [['DATA', 'ID_CHAT', 'NOME', 'MOTIVO_ERRO']])
        
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        ws_erro.append_row([agora, str(chat_id), nome, str(motivo)])
    except Exception as e:
        logger.error(f"Erro ao registrar log de erro na planilha: {e}")

@st.cache_data(ttl=300, show_spinner="Buscando listas...")
def carregar_listas_db(worksheet_name):
    DESTINATARIOS = {} 
    try:
        client = get_gspread_client()
        if client is None: return {"Erro de Conexão": "0"} 
        sheet = client.open_by_key(SHEET_ID).worksheet(worksheet_name)
        df = pd.DataFrame(sheet.get_all_records())
        
        # Garante colunas de variáveis extras
        for col in ['lista', 'nome', 'ids', 'var1', 'var2']:
            if col not in df.columns: df[col] = ""

        for _, row in df.iterrows():
            nome_lista = str(row['lista']).strip()
            if nome_lista:
                if nome_lista not in DESTINATARIOS: DESTINATARIOS[nome_lista] = []
                DESTINATARIOS[nome_lista].append({
                    'id': str(row['ids']).strip(), 
                    'nome': str(row['nome']).strip(),
                    'var1': str(row['var1']).strip(),
                    'var2': str(row['var2']).strip()
                })
        return DESTINATARIOS
    except Exception as e:
        st.error(f"Erro na leitura da planilha: {e}")
        return {}

@st.cache_data(ttl=600, show_spinner="Verificando autorizações...")
def carregar_ids_autorizados():
    try:
        client = get_gspread_client()
        if client is None: return set()
        sheet = client.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME_AUTORIZACAO)
        ids = sheet.col_values(1)[1:] 
        return set(str(i).strip() for i in ids if str(i).strip())
    except:
        return set()

def coletar_ids_telegram():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        res = requests.get(url, timeout=10).json()
        client = get_gspread_client()
        sh = client.open_by_key(SHEET_ID)
        ws = sh.worksheet(WORKSHEET_NAME_AUTORIZACAO)
        existing_ids = set(ws.col_values(1)[1:]) 
        new_rows = []
        for update in res.get('result', []):
            if 'message' in update:
                chat_id = str(update['message']['chat']['id'])
                if chat_id not in existing_ids:
                    user = update['message']['chat'].get('username', 'N/A')
                    new_rows.append([chat_id, user, datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
                    existing_ids.add(chat_id)
        if new_rows: ws.append_rows(new_rows); st.success(f"✅ {len(new_rows)} novos IDs coletados!")
        else: st.info("Nenhum novo ID.")
    except Exception as e: st.error(f"Erro na coleta: {e}")

# ====================================================================
# 📤 4. FUNÇÕES DE ENVIO E PROCESSAMENTO
# ====================================================================

def substituir_variaveis(msg, d):
    """Substitui as tags personalizadas na mensagem."""
    # Tratamento para {nome} ou @nome
    nome = d['nome'] if d['nome'] else "Cliente"
    msg = msg.replace("{nome}", nome).replace("@nome", nome)
    # Novas variáveis
    msg = msg.replace("@var1", d['var1'])
    msg = msg.replace("@var2", d['var2'])
    return msg

def enviar_telegram_api(chat_id, texto, foto_bytes=None):
    """Função unificada de envio (Texto ou Foto)."""
    try:
        if foto_bytes:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            res = requests.post(url, files={'photo': ('img.jpg', foto_bytes)}, data={'chat_id': chat_id, 'caption': texto}, timeout=15)
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            res = requests.post(url, data={'chat_id': chat_id, 'text': texto}, timeout=15)
        return res.status_code == 200, res.text
    except Exception as e:
        return False, str(e)

# ====================================================================
# 🖼️ 5. INTERFACE (UI)
# ====================================================================

def logout_button():
    if st.sidebar.button("Sair", type="secondary", use_container_width=True):
        st.session_state['logged_in'] = False
        st.session_state['PERMANENT_LOGIN'] = False
        st.rerun()

def app_ui():
    user_is_admin = st.session_state.get('username') in ADMIN_USERS
    
    # CSS: Oculta botões e remove seta de recolher sidebar
    st.markdown("""
        <style>
        #MainMenu {visibility: hidden;} footer {visibility: hidden;}
        [data-testid="stToolbar"] {display: none !important;}
        [data-testid="stSidebarToggleButton"] {display: none !important;}
        </style>
    """, unsafe_allow_html=True)
    
    st.sidebar.markdown(f'<div style="text-align: center;"><img src="https://raw.githubusercontent.com/charlevaz/telegram-broadcaster/main/cr.png" width="80"><h4 style="color:black;">GRUPO CR</h4></div>', unsafe_allow_html=True)
    st.sidebar.write(f"Usuário: **{st.session_state['username']}**")
    logout_button()

    if user_is_admin:
        st.sidebar.markdown("---")
        if st.sidebar.button("🤖 Coletar IDs", type="primary", use_container_width=True):
            coletar_ids_telegram()
            st.cache_data.clear()

    st.title("📢 Broadcaster Telegram")
    
    listas_dados = carregar_listas_db(WORKSHEET_NAME_TELEGRAM)
    nomes_listas = list(listas_dados.keys())

    selecionadas = st.multiselect("Selecione as Listas:", nomes_listas)
    arquivo = st.file_uploader("🖼️ Imagem (Opcional)", type=["png", "jpg", "jpeg"])
    
    st.info("💡 Use `{nome}`, `@var1` ou `@var2` para personalizar.")
    mensagem = st.text_area("📝 Mensagem:", height=150)

    if st.button("🚀 Iniciar Disparo", type="primary", use_container_width=True):
        if not selecionadas or not mensagem:
            st.error("Campos obrigatórios vazios."); return

        file_bytes = arquivo.read() if arquivo else None
        ids_autorizados = carregar_ids_autorizados()
        
        # Filtra e remove duplicatas
        todos_dest = []
        for l in selecionadas: todos_dest.extend(listas_dados.get(l, []))
        
        # Filtro de autorização
        final_dest = [d for d in todos_dest if d['id'] in ids_autorizados]
        df_final = pd.DataFrame(final_dest).drop_duplicates(subset=['id'])
        destinatarios = df_final.to_dict('records')

        if not destinatarios:
            st.warning("Nenhum destinatário autorizado encontrado."); return

        progresso = st.progress(0)
        status = st.empty()
        sucesso, falha = 0, 0

        for idx, d in enumerate(destinatarios):
            msg_final = substituir_variaveis(mensagem, d)
            ok, response = enviar_telegram_api(d['id'], msg_final, file_bytes)
            
            if ok: sucesso += 1
            else:
                falha += 1
                registrar_erro_planilha(d['id'], d['nome'], response)
            
            progresso.progress((idx + 1) / len(destinatarios))
            status.text(f"Enviando: {idx+1}/{len(destinatarios)}")

        status.empty()
        st.success(f"✅ Fim do disparo! Sucesso: {sucesso} | Falha: {falha}")

def login_form():
    st.markdown('<div style="text-align: center;"><h3>Acesso Restrito</h3></div>', unsafe_allow_html=True)
    with st.form("login"):
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            if u in USER_CREDENTIALS and USER_CREDENTIALS[u] == p:
                st.session_state['logged_in'] = True
                st.session_state['username'] = u
                st.rerun()
            else: st.error("Incorreto.")

if st.session_state['logged_in']: app_ui()
else: login_form()