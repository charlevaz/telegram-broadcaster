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
WORKSHEET_NAME_AUTORIZACAO = 'autorizacao' # ⬅️ Nova aba para logs do fetcher

USER_CREDENTIALS = {
    "operação": "820628", 
    "charle": "966365"    
}

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'PERMANENT_LOGIN' not in st.session_state:
    st.session_state['logged_in'] = st.session_state.get('PERMANENT_LOGIN', False)

# ====================================================================
# 🌐 3. FUNÇÕES DE CONEXÃO E ENVIO
# ====================================================================

def get_gspread_client():
    """Retorna o cliente gspread autenticado."""
    
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        if 'google_service_account' in st.secrets:
            # Autenticação via Streamlit Secrets (Cloud)
            creds_info = dict(st.secrets["google_service_account"]) 
            if isinstance(creds_info, dict):
                 creds_info['private_key'] = creds_info['private_key'].replace('\\n', '\n')
                 creds = Credentials.from_service_account_info(creds_info, scopes=DEFAULT_SCOPES)
            else:
                 creds = Credentials.from_service_account_info(json.loads(creds_info), scopes=DEFAULT_SCOPES)
        else:
            # Autenticação via arquivo local (Ubuntu Server)
            creds = Credentials.from_json_keyfile_name(CREDENTIALS_FILE, scopes=DEFAULT_SCOPES)
            
        return gspread.authorize(creds)
        
    except Exception as e:
        logger.critical(f"Falha na Autenticação GSpread: {e}")
        st.error(f"ERRO DE AUTENTICAÇÃO CRÍTICA: {e}") 
        return None

@st.cache_data(ttl=300, show_spinner="Buscando listas...")
def carregar_listas_db(worksheet_name):
    """Carrega listas do Telegram."""
    
    DESTINATARIOS = {} 
    
    try:
        client = get_gspread_client()
        if client is None: return {"Erro de Conexão": "0"} 

        sheet = client.open_by_key(SHEET_ID)
        worksheet = sheet.worksheet(worksheet_name)
        
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        if 'lista' in df.columns and 'nome' in df.columns and 'ids' in df.columns:
            
            for index, row in df.iterrows():
                nome_lista = str(row['lista']).strip()
                destinatario_id = str(row['ids']).strip()
                nome_destinatario = str(row['nome']).strip()
                
                if nome_lista and destinatario_id:
                    if nome_lista not in DESTINATARIOS:
                        DESTINATARIOS[nome_lista] = []
                    DESTINATARIOS[nome_lista].append({'id': destinatario_id, 'nome': nome_destinatario})
            
            return DESTINATARIOS
        else:
            st.error(f"ERRO DE COLUNAS na aba '{worksheet_name}'. Obrigatórias: 'lista', 'nome', e 'ids'.")
            return {"Erro de Colunas": "0"}

    except Exception as e:
        st.error(f"ERRO NA LEITURA DA PLANILHA '{worksheet_name}': {e}") 
        logger.critical(f"Falha ao carregar a lista de destinatários ({worksheet_name}): {e}")
        return {"Erro de Conexão": "0"}

@st.cache_data(ttl=600, show_spinner="Verificando autorizações...")
def carregar_ids_autorizados():
    """Carrega todos os IDs únicos da aba 'autorizacao'."""
    try:
        client = get_gspread_client()
        if client is None: return set()
        
        sheet = client.open_by_key(SHEET_ID)
        ws_autorizacao = sheet.worksheet(WORKSHEET_NAME_AUTORIZACAO)
        
        # Pega todos os valores da primeira coluna (ID_CHAT), pulando o cabeçalho
        ids = ws_autorizacao.col_values(1)[1:] 
        
        # Retorna um set para consulta rápida
        return set(str(i).strip() for i in ids if str(i).strip())
        
    except gspread.WorksheetNotFound:
        st.warning(f"A aba de autorização '{WORKSHEET_NAME_AUTORIZACAO}' não foi encontrada. Nenhum filtro será aplicado.")
        return set()
    except Exception as e:
        logger.error(f"Erro ao carregar IDs de autorização: {e}")
        return set()


def substituir_variaveis(mensagem_original, nome_destinatario):
    """Substitui as variáveis {nome} ou @nome na mensagem."""
    nome = nome_destinatario if nome_destinatario else "Cliente"
    mensagem_processada = mensagem_original.replace("{nome}", nome)
    mensagem_processada = mensagem_original.replace("@nome", nome)
    return mensagem_processada

# --- Funções de Envio de API ---

def enviar_mensagem_telegram_api(chat_id, mensagem_processada):
    """Envia mensagem de texto via API Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = { 'chat_id': chat_id, 'text': mensagem_processada, 'parse_mode': 'Markdown' }
    try:
        response = requests.post(url, data=payload); response.raise_for_status()
        return True, response.json()
    except requests.exceptions.RequestException as e: return False, str(e)

def enviar_foto_telegram_api(chat_id, foto_bytes, legenda_processada):
    """Envia uma foto com legenda via API Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {'photo': ('imagem.jpg', foto_bytes, 'image/jpeg')} 
    data = {'chat_id': chat_id}
    if legenda_processada: data['caption'] = legenda_processada; data['parse_mode'] = 'Markdown'
    try:
        response = requests.post(url, files=files, data=data); response.raise_for_status()
        return True, response.json()
    except requests.exceptions.RequestException as e: return False, str(e)


# --- Funções de Disparo (Central) ---

def processar_disparo(listas_selecionadas, mensagem_original, uploaded_file, listas_dados):
    """Função central que executa o envio para o Telegram com filtro de autorização."""
    
    file_bytes = None
    if uploaded_file is not None:
        if hasattr(uploaded_file, 'seek'): uploaded_file.seek(0)
        file_bytes = uploaded_file.read() 
    
    # 1. Compila lista de todos os destinatários (bruta)
    destinatarios_raw = []
    for nome_lista in listas_selecionadas: destinatarios_raw.extend(listas_dados.get(nome_lista, []))
    
    # 2. Obtém os IDs autorizados (filtro)
    ids_autorizados = carregar_ids_autorizados()
    
    # 3. FILTRA e remove duplicatas
    destinatarios = []
    for dest in destinatarios_raw:
        if dest['id'] in ids_autorizados:
            destinatarios.append(dest)
    
    destinatarios = pd.DataFrame(destinatarios).drop_duplicates(subset=['id']).to_dict('records')
    
    if not destinatarios: st.error("Nenhum destinatário autorizado encontrado para o envio."); return

    total_enviados = 0; erros = [];
    
    with st.spinner(f'Iniciando envio Telegram para {len(destinatarios)} destinatários...'):
        
        progress_bar = st.progress(0, text="Preparando envio...")
        
        for i, dest in enumerate(destinatarios):
            chat_id = dest['id']; nome_destinatario = dest['nome']
            mensagem_processada = substituir_variaveis(mensagem_original, nome_destinatario)
            
            if file_bytes is not None: sucesso, resultado = enviar_foto_telegram_api(chat_id, file_bytes, mensagem_processada)
            else: sucesso, resultado = enviar_mensagem_telegram_api(chat_id, mensagem_processada)
            
            if sucesso: total_enviados += 1
            else: erros.append(f"ID {chat_id} ({nome_destinatario}): Falha -> {resultado}"); 
            
            logger.info(f"FIM: Telegram para {chat_id}. Status: {'SUCESSO' if sucesso else 'FALHA'}")

            percentual = (i + 1) / len(destinatarios)
            progress_bar.progress(percentual, text=f"Enviando... {i + 1} de {len(destinatarios)}")

    progress_bar.empty()
    st.success(f"✅ Disparo Telegram concluído! **{total_enviados}** mensagens enviadas com sucesso.")
    logger.info(f"FIM DO DISPARO TELEGRAM: Enviados: {total_enviados}, Falhas: {len(erros)}")
    
    if erros:
        st.warning(f"⚠️ {len(erros)} falhas de envio. Detalhes no Log.")
        for erro in erros[:3]: st.code(erro)
            
    return total_enviados


# --- Funções Main e Inicialização ---
def login_form():
    """Exibe o formulário de login e processa a autenticação."""
    
    hide_streamlit_style_login = """
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;} 
    [data-testid="stDecoration"] {visibility: hidden;} 
    </style>
    """
    st.markdown(hide_streamlit_style_login, unsafe_allow_html=True)
    
    st.set_page_config(page_title="Login - Broadcaster Telegram", layout="centered")
    
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/8/82/Telegram_logo.svg/100px-Telegram_logo.svg.png", width=100) 
    st.title("🛡️ Acesso Restrito")
    st.markdown("---")

    with st.form("login_form"):
        username = st.text_input("Usuário:"); password = st.text_input("Senha:", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
        if submitted:
            if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password: 
                st.session_state['logged_in'] = True; st.session_state['username'] = username
                st.session_state['PERMANENT_LOGIN'] = True; st.rerun()
            else: st.error("Usuário ou senha inválidos.")

def logout_button():
    """Botão de Logout simples."""
    if st.sidebar.button("Sair", type="secondary"):
        st.session_state['logged_in'] = False; st.session_state['PERMANENT_LOGIN'] = False
        st.session_state.pop('username', None); st.rerun()

def app_ui():
    
    # 🪄 CSS GERAL: Oculta todos os elementos visuais indesejados
    hide_streamlit_style_app = """
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;} 
    [data-testid="stDecoration"] {visibility: hidden;} 
    </style>
    """
    st.markdown(hide_streamlit_style_app, unsafe_allow_html=True)
    
    st.set_page_config(page_title="Broadcaster Telegram | Equipe", layout="wide") 
    
    # 🆕 LOGO NO CANTO ESQUERDO DA SIDEBAR (usando HTML/Markdown)
    st.sidebar.markdown(
        f'<img src="https://raw.githubusercontent.com/charlevaz/telegram-broadcaster/main/cr.png" width="100">', 
        unsafe_allow_html=True
    )
    
    st.title("📢 Sistema de Disparo Telegram")
    st.sidebar.markdown(f"Usuário: **{st.session_state['username']}**")
    logout_button()
    st.sidebar.header("Configuração de Destinatários")

    recarregar_lista = st.sidebar.button("🔄 Recarregar Dados da Planilha", type="secondary")
    if recarregar_lista: st.cache_data.clear()

    # 1. CARREGA A LISTA DE DESTINATÁRIOS (Telegram)
    listas_telegram_data = carregar_listas_db(WORKSHEET_NAME_TELEGRAM)
    
    # 2. TRATAMENTO DE ERRO NA CONEXÃO
    if "Erro de Conexão" in listas_telegram_data:
        st.error("Falha ao carregar a lista do Telegram. Verifique as credenciais.")
        return 
    
    if "Erro de Colunas" in listas_telegram_data:
        st.error("Erro fatal: Colunas da lista TELEGRAM estão incorretas. Verifique 'lista', 'nome', 'ids'.")
        return 
    
    
    # --- FLUXO DE NOME DE LISTAS ---
    nomes_listas_telegram = list(listas_telegram_data.keys()) if isinstance(listas_telegram_data, dict) else []
    
    
    # --- INTERFACE PRINCIPAL ---
    
    st.markdown('### <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/8/82/Telegram_logo.svg/24px-Telegram_logo.svg.png" style="width:24px; vertical-align:middle;"> Disparo Telegram', unsafe_allow_html=True)

    imediato_listas_selecionadas = st.multiselect("Selecione as Listas para Disparo:", nomes_listas_telegram, key="telegram_lists")
    imediato_uploaded_file = st.file_uploader("🖼️ Anexar Imagem (Opcional)", type=["png", "jpg", "jpeg"], key="telegram_img")
    imediato_mensagem = st.text_area("📝 Mensagem para Disparo (Use {nome} ou @nome para personalizar)", height=150, key="telegram_msg")
    
    # Exibe aviso de filtro de autorização
    ids_autorizados = carregar_ids_autorizados()
    st.info(f"Filtro: Apenas **{len(ids_autorizados)}** CHAT IDs que iniciaram conversa com o bot serão alcançados.")

    if st.button("🚀 Disparar Telegram Agora", key="btn_telegram", type="primary"):
        if not imediato_listas_selecionadas: st.error("Selecione pelo menos uma Lista."); return
        if not imediato_mensagem.strip() and imediato_uploaded_file is None: st.error("Conteúdo vazio."); return

        processar_disparo(imediato_listas_selecionadas, imediato_mensagem, imediato_uploaded_file, listas_telegram_data)
        
# --- Funções Main e Inicialização ---
def main():
    """Controla se exibe a tela de login ou a aplicação principal."""
    if st.session_state['logged_in']:
        app_ui()
    else:
        login_form()

if __name__ == "__main__":
    main()