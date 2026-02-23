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

BOT_TOKEN = "8586446411:AAH_jXK0Yv6h64gRLhoK3kv2kJo4mG5x3LE" 
CREDENTIALS_FILE = '/home/charle/scripts/chaveBigQuery.json' 
SHEET_ID = '1HSIwFfIr67i9K318DX1qTwzNtrJmaavLKUlDpW5C6xU' 
WORKSHEET_NAME_TELEGRAM = 'lista_telegram' 
WORKSHEET_NAME_AUTORIZACAO = 'autorizacao' 
WORKSHEET_NAME_ERROS = 'erro' # ⬅️ Aba para logs de falha

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
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        if 'google_service_account' in st.secrets:
            creds_info = dict(st.secrets["google_service_account"]) 
            creds_info['private_key'] = creds_info['private_key'].replace('\\n', '\n')
            creds = Credentials.from_service_account_info(creds_info, scopes=DEFAULT_SCOPES)
        else:
            creds = Credentials.from_json_keyfile_name(CREDENTIALS_FILE, scopes=DEFAULT_SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        logger.critical(f"Falha na Autenticação GSpread: {e}")
        st.error(f"ERRO DE AUTENTICAÇÃO CRÍTICA: {e}") 
        return None

def registrar_erro_planilha(chat_id, nome, motivo):
    """Grava o log de erro diretamente na aba 'erro' da planilha."""
    try:
        client = get_gspread_client()
        if not client: return
        sheet = client.open_by_key(SHEET_ID)
        
        try:
            ws_erro = sheet.worksheet(WORKSHEET_NAME_ERROS)
        except gspread.WorksheetNotFound:
            # Cria a aba se ela não existir
            ws_erro = sheet.add_worksheet(title=WORKSHEET_NAME_ERROS, rows="100", cols="4")
            ws_erro.update('A1:D1', [['DATA', 'ID_CHAT', 'NOME', 'MOTIVO_ERRO']])
        
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        ws_erro.append_row([agora, str(chat_id), nome, str(motivo)])
    except Exception as e:
        logger.error(f"Erro ao registrar log de erro na planilha: {e}")

@st.cache_data(ttl=300, show_spinner="Buscando listas...")
def carregar_listas_db(worksheet_name):
    """Carrega listas e garante as novas colunas @var1 e @var2."""
    DESTINATARIOS = {} 
    try:
        client = get_gspread_client()
        if client is None: return {"Erro de Conexão": "0"} 
        sheet = client.open_by_key(SHEET_ID).worksheet(worksheet_name)
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # Garante que as colunas existam para não quebrar o código
        for col in ['lista', 'nome', 'ids', 'var1', 'var2']:
            if col not in df.columns: df[col] = ""

        if 'lista' in df.columns and 'nome' in df.columns and 'ids' in df.columns:
            for _, row in df.iterrows():
                nome_lista = str(row['lista']).strip()
                if nome_lista:
                    if nome_lista not in DESTINATARIOS: DESTINATARIOS[nome_lista] = []
                    DESTINATARIOS[nome_lista].append({
                        'id': str(row['ids']).strip(), 
                        'nome': str(row['nome']).strip(),
                        'var1': str(row['var1']).strip(), # 🆕 Variável extra 1
                        'var2': str(row['var2']).strip()  # 🆕 Variável extra 2
                    })
            return DESTINATARIOS
        else:
            st.error(f"ERRO DE COLUNAS na aba '{worksheet_name}'. Obrigatórias: 'lista', 'nome', 'ids'.")
            return {"Erro de Colunas": "0"}
    except Exception as e:
        st.error(f"ERRO NA LEITURA DA PLANILHA '{worksheet_name}': {e}") 
        return {}

def coletar_ids_telegram():
    """Busca novos IDs que interagiram com o bot e salva na planilha de autorização."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        client = get_gspread_client()
        sh = client.open_by_key(SHEET_ID)
        try:
            ws = sh.worksheet(WORKSHEET_NAME_AUTORIZACAO)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=WORKSHEET_NAME_AUTORIZACAO, rows="100", cols="3")
            ws.update('A1:C1', [['ID_CHAT', 'NOME_USUARIO', 'DATA']])
        
        existing_ids = set(ws.col_values(1)[1:]) 
        new_rows = []
        agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for update in data.get('result', []):
            if 'message' in update:
                chat = update['message']['chat']
                chat_id = str(chat['id'])
                if chat_id not in existing_ids:
                    user = chat.get('username') or chat.get('first_name', 'N/A')
                    new_rows.append([chat_id, user, agora])
                    existing_ids.add(chat_id)
        if new_rows:
            ws.append_rows(new_rows)
            st.success(f"✅ {len(new_rows)} novos usuários coletados!")
    except Exception as e:
        st.error(f"Erro na coleta: {e}")

# ====================================================================
# 📤 4. FUNÇÕES DE ENVIO E PROCESSAMENTO
# ====================================================================

def substituir_variaveis(msg, d):
    """Substitui {nome}, @var1 e @var2 no texto."""
    msg = msg.replace("{nome}", d['nome']).replace("@nome", d['nome'])
    msg = msg.replace("@var1", d['var1'])
    msg = msg.replace("@var2", d['var2'])
    return msg

def enviar_telegram(chat_id, texto, foto_bytes=None):
    """Envia texto ou foto (sem Markdown para evitar Erro 400)."""
    try:
        # 🚨 Nota: Usar parse_mode='Markdown' causa erro 400 se houver caracteres como '_' ou '*' soltos.
        # Por segurança, enviamos como texto puro.
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

def app_ui():
    user_is_admin = st.session_state.get('username') in ADMIN_USERS
    
    # CSS completo para segurança visual e remoção do botão de recolher menu
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} 
    footer {visibility: hidden;}
    [data-testid="stToolbar"] {display: none !important;}
    [data-testid="stDecoration"] {visibility: hidden;} 
    
    /* 🛑 REMOVE O BOTÃO DE RECOLHER A SIDEBAR (SETINHAS <<) */
    [data-testid="stSidebarToggleButton"] {
        display: none !important;
    }
    
    div[data-testid="stSidebar"] h4 { color: black !important; }
    </style>
    """, unsafe_allow_html=True)
    
    # Configuração da Página (Título na aba do navegador)
    st.set_page_config(page_title="Broadcaster Telegram | Grupo CR", layout="wide") 

    # Sidebar
    st.sidebar.markdown(f'<div style="text-align: center;"><img src="https://raw.githubusercontent.com/charlevaz/telegram-broadcaster/main/cr.png" width="80"><h4 style="margin-top:10px;">GRUPO CR</h4></div>', unsafe_allow_html=True)
    st.sidebar.write(f"Usuário: **{st.session_state['username']}**")
    
    if st.sidebar.button("Sair", type="secondary", use_container_width=True):
        st.session_state['logged_in'] = False
        st.session_state['PERMANENT_LOGIN'] = False
        st.rerun()

    if user_is_admin:
        st.sidebar.markdown("---")
        if st.sidebar.button("🤖 Coletar Novos IDs", type="primary", use_container_width=True):
            coletar_ids_telegram()
            st.cache_data.clear()

    st.title("📢 Sistema de Disparo Telegram")
    
    listas_dados = carregar_listas_db(WORKSHEET_NAME_TELEGRAM)
    
    if "Erro" in listas_dados:
        st.error("Erro ao carregar dados da planilha.")
        return

    sel_listas = st.multiselect("Selecione as Listas para Disparo:", list(listas_dados.keys()))
    uploaded_file = st.file_uploader("🖼️ Anexar Imagem (Opcional)", type=["jpg", "png", "jpeg"])
    
    st.info("💡 **Tags disponíveis:** `{nome}`, `@var1`, `@var2`")
    mensagem = st.text_area("📝 Mensagem para Disparo:", height=150, placeholder="Olá {nome}, sua variável 1 é @var1.")

    if st.button("🚀 Iniciar Disparo Agora", type="primary", use_container_width=True):
        if not sel_listas or not mensagem:
            st.error("Por favor, selecione ao menos uma lista e escreva a mensagem."); return

        img_content = uploaded_file.read() if uploaded_file else None
        
        # Consolida destinatários únicos
        dest_list = []
        for l in sel_listas: dest_list.extend(listas_dados.get(l, []))
        df_final = pd.DataFrame(dest_list).drop_duplicates(subset=['id'])
        destinatarios = df_final.to_dict('records')

        progresso = st.progress(0)
        status_bar = st.empty()
        sucesso, falha = 0, 0

        for idx, d in enumerate(destinatarios):
            msg_final = substituir_variaveis(mensagem, d)
            ok, resposta = enviar_telegram(d['id'], msg_final, img_content)
            
            if ok: sucesso += 1
            else:
                falha += 1
                registrar_erro_planilha(d['id'], d['nome'], resposta)
            
            progresso.progress((idx + 1) / len(destinatarios))
            status_bar.text(f"Processando: {idx + 1} de {len(destinatarios)}")
        
        status_bar.empty()
        st.success(f"✅ Disparo Concluído! Sucessos: {sucesso} | Falhas: {falha}")
        if falha > 0:
            st.warning("⚠️ Algumas mensagens falharam. Verifique os detalhes na aba 'erro' da planilha.")

# --- LOGIN E MAIN ---
def login_form():
    st.set_page_config(page_title="Login - Grupo CR", layout="centered")
    st.markdown("""<style>[data-testid="stToolbar"] {display: none !important;}</style>""", unsafe_allow_html=True)
    
    st.markdown(f'<div style="text-align: center;"><img src="https://upload.wikimedia.org/wikipedia/commons/thumb/8/82/Telegram_logo.svg/100px-Telegram_logo.svg.png" width="60"><h3>GRUPO CR</h3></div>', unsafe_allow_html=True)
    st.title("🛡️ Acesso Restrito")
    
    with st.form("login"):
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            if u in USER_CREDENTIALS and USER_CREDENTIALS[u] == p:
                st.session_state['logged_in'] = True
                st.session_state['username'] = u
                st.rerun()
            else: st.error("Usuário ou senha inválidos.")

def main():
    if st.session_state['logged_in']:
        app_ui()
    else:
        login_form()

if __name__ == "__main__":
    main()