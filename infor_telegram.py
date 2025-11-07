import streamlit as st
import requests
import gspread 
from google.oauth2.service_account import Credentials
import pandas as pd
import logging
import json 
from gspread.auth import DEFAULT_SCOPES 

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
WORKSHEET_NAME = 'lista_telegram' 

USER_CREDENTIALS = {
    "charle": "equipe123",  
    "admin": "admin456"    
}

# 🟢 NOVO: Inicializa o estado de login com chave de sessão permanente
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = st.session_state.get('PERMANENT_LOGIN', False)

# ====================================================================
# 🌐 3. FUNÇÕES DE CONEXÃO E ENVIO (Mantidas)
# ...
# ====================================================================
def get_gspread_client():
    """Retorna o cliente gspread autenticado."""
    
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        if 'google_service_account' in st.secrets:
            creds_info = dict(st.secrets["google_service_account"]) 
            if isinstance(creds_info, dict):
                 creds_info['private_key'] = creds_info['private_key'].replace('\\n', '\n')
                 creds = Credentials.from_service_account_info(creds_info, scopes=DEFAULT_SCOPES)
            else:
                 creds = Credentials.from_service_account_info(json.loads(creds_info), scopes=DEFAULT_SCOPES)
        else:
            creds = Credentials.from_json_keyfile_name(CREDENTIALS_FILE, scopes=DEFAULT_SCOPES)
            
        return gspread.authorize(creds)
        
    except Exception as e:
        logger.critical(f"Falha na Autenticação GSpread: {e}")
        st.error(f"ERRO DE AUTENTICAÇÃO CRÍTICA: {e}") 
        return None

@st.cache_data(ttl=300, show_spinner="Buscando lista de destinatários...")
def carregar_destinatarios_db():
    DESTINATARIOS = {} 
    try:
        client = get_gspread_client()
        if client is None: return {"Erro de Conexão": "0"} 
        sheet = client.open_by_key(SHEET_ID); worksheet = sheet.worksheet(WORKSHEET_NAME)
        data = worksheet.get_all_records(); df = pd.DataFrame(data)
        if 'lista' in df.columns and 'ids' in df.columns:
            for index, row in df.iterrows():
                nome_lista = str(row['lista']).strip(); chat_id = str(row['ids']).strip()
                if nome_lista and chat_id:
                    if nome_lista not in DESTINATARIOS: DESTINATARIOS[nome_lista] = []
                    DESTINATARIOS[nome_lista].append(chat_id)
            return DESTINATARIOS
        else: return {"Erro de Colunas": "0"}
    except Exception as e:
        st.error(f"ERRO NA LEITURA DA PLANILHA: {e}"); logger.critical(f"Falha ao carregar a lista de destinatários: {e}")
        return {"Erro de Conexão": "0"}

def enviar_mensagem(chat_id, texto):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = { 'chat_id': chat_id, 'text': texto, 'parse_mode': 'Markdown' }
    try:
        response = requests.post(url, data=payload); response.raise_for_status()
        return True, response.json()
    except requests.exceptions.RequestException as e: return False, str(e)

def enviar_foto(chat_id, foto_bytes, legenda=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {'photo': ('imagem.jpg', foto_bytes, 'image/jpeg')} 
    data = {'chat_id': chat_id}
    if legenda: data['caption'] = legenda; data['parse_mode'] = 'Markdown'
    try:
        response = requests.post(url, files=files, data=data); response.raise_for_status()
        return True, response.json()
    except requests.exceptions.RequestException as e: return False, str(e)

def processar_disparo(ids_para_disparo, mensagem, uploaded_file):
    file_bytes = None
    if uploaded_file is not None:
        if hasattr(uploaded_file, 'seek'): uploaded_file.seek(0)
        file_bytes = uploaded_file.read() 
    total_enviados = 0; erros = []
    with st.spinner(f'Iniciando envio para {len(ids_para_disparo)} destinatários...'):
        progress_bar = st.progress(0, text="Preparando envio...")
        for i, chat_id_unico in enumerate(ids_para_disparo):
            if file_bytes is not None: sucesso, resultado = enviar_foto(chat_id_unico, file_bytes, mensagem)
            else: sucesso, resultado = enviar_mensagem(chat_id_unico, mensagem)
            if sucesso: total_enviados += 1; logger.info(f"SUCESSO: Mensagem enviada para o ID: {chat_id_unico}")
            else: erros.append(f"ID {chat_id_unico}: Falha -> {resultado}"); logger.error(f"FALHA: Erro ao enviar para o ID {chat_id_unico}. Detalhes: {resultado}")
            percentual = (i + 1) / len(ids_para_disparo); progress_bar.progress(percentual, text=f"Enviando... {i + 1} de {len(ids_unicos)}")
    progress_bar.empty()
    st.success(f"✅ Disparo concluído! **{total_enviados}** mensagens enviadas com sucesso.")
    logger.info(f"FIM DO DISPARO: Enviados: {total_enviados}, Falhas: {len(erros)}")
    if erros:
        st.warning(f"⚠️ Atenção! Ocorreram {len(erros)} falhas de envio. Verifique o arquivo '{LOG_FILE}' para detalhes.")
        for erro in erros: st.code(erro.split(': Falha -> ')[0])
    return total_enviados

# ====================================================================
# 🔒 FUNÇÕES DE LOGIN/LOGOUT (Modificado para Persistência)
# ====================================================================

def login_form():
    """Exibe o formulário de login e processa a autenticação."""
    
    # 🔴 NOVO CSS: APLICA ESTILO TAMBÉM NA TELA DE LOGIN
    hide_streamlit_style_login = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    /* Remove a barra de ferramentas superior (Fork/GitHub) */
    [data-testid="stToolbar"] {visibility: hidden !important;} 
    /* Remove a miniatura/coroa do Streamlit Cloud */
    [data-testid="stDecoration"] {visibility: hidden;} 
    </style>
    """
    st.markdown(hide_streamlit_style_login, unsafe_allow_html=True)
    
    st.set_page_config(page_title="Login - Broadcaster Telegram", layout="centered")
    st.title("🛡️ Acesso Restrito")
    st.markdown("---")

    with st.form("login_form"):
        username = st.text_input("Usuário:")
        password = st.text_input("Senha:", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")

        if submitted:
            if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password: 
                st.session_state['logged_in'] = True
                st.session_state['username'] = username
                # 🟢 NOVO: Variável de sessão persistente para evitar logout no refresh
                st.session_state['PERMANENT_LOGIN'] = True 
                st.rerun()
            else: st.error("Usuário ou senha inválidos.")

def logout_button():
    """Botão de Logout simples."""
    if st.sidebar.button("Sair", type="secondary"):
        st.session_state['logged_in'] = False
        st.session_state['PERMANENT_LOGIN'] = False # Limpa a sessão
        st.session_state.pop('username', None)
        st.rerun()

# ====================================================================
# 🖼️ 5. INTERFACE GRÁFICA PRINCIPAL (APP_UI)
# ====================================================================

def app_ui():
    
    # 🪄 NOVO CSS: Oculta todos os elementos visuais indesejados
    hide_streamlit_style_app = """
    <style>
    /* Oculta o menu de três pontos e o rodapé */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    /* Remove a barra de ferramentas superior (GitHub/Share/Fork) */
    [data-testid="stToolbar"] {visibility: hidden !important;} 
    /* Remove a miniatura/coroa do Streamlit Cloud (Decoração) */
    [data-testid="stDecoration"] {visibility: hidden;} 
    </style>
    """
    st.markdown(hide_streamlit_style_app, unsafe_allow_html=True)
    
    st.set_page_config(page_title="Broadcaster Telegram | Equipe", layout="wide") 
    st.title("📢 Sistema de Disparo Telegram")
    st.sidebar.markdown(f"Usuário: **{st.session_state['username']}**")
    logout_button()
    st.sidebar.header("Configuração de Destinatários")

    recarregar_lista = st.sidebar.button("🔄 Recarregar Lista da Planilha", type="secondary")
    if recarregar_lista:
        st.cache_data.clear()

    # 1. CARREGA A LISTA DE DESTINATÁRIOS
    lista_destinatarios = carregar_destinatarios_db()
    
    # 2. TRATAMENTO DE ERRO NA CONEXÃO
    if "Erro de Conexão" in lista_destinatarios or "Erro de Colunas" in lista_destinatarios:
        return 
    
    nomes_listas = list(lista_destinatarios.keys())
    
    # --- Disparo Imediato (Corpo Principal) ---
    
    st.header("Disparo Imediato"); st.markdown("---")
    
    imediato_listas_selecionadas = st.multiselect("Selecione as Listas para Disparo:", nomes_listas, key="imediato_lists")
    imediato_uploaded_file = st.file_uploader("🖼️ Anexar Imagem (Opcional)", type=["png", "jpg", "jpeg"], key="imediato_img")
    imediato_mensagem = st.text_area("📝 Mensagem para Disparo", height=150, key="imediato_msg")
    
    imediato_ids_para_disparo = set()
    for nome_lista in imediato_listas_selecionadas: imediato_ids_para_disparo.update(lista_destinatarios.get(nome_lista, []))
        
    st.info(f"Serão alcançados **{len(imediato_ids_para_disparo)}** CHAT IDs únicos.")

    if st.button("🚀 Disparar Mensagem Agora", type="primary"):
        if not imediato_listas_selecionadas: st.error("Selecione pelo menos uma Lista para Disparo."); return
        if not imediato_mensagem.strip() and imediato_uploaded_file is None: st.error("Conteúdo vazio."); return

        logger.info(f"INÍCIO DO DISPARO IMEDIATO: Alvo: {imediato_listas_selecionadas}")
        processar_disparo(imediato_ids_para_disparo, imediato_mensagem, imediato_uploaded_file)
        
# ====================================================================
# 🚀 FUNÇÃO DE INICIALIZAÇÃO
# ====================================================================

def main():
    """Controla se exibe a tela de login ou a aplicação principal."""
    if st.session_state['logged_in']:
        app_ui()
    else:
        login_form()

if __name__ == "__main__":
    main()