import streamlit as st
import requests
import gspread 
from google.oauth2.service_account import Credentials
import pandas as pd
import logging
import json 
from gspread.auth import DEFAULT_SCOPES 

# ====================================================================
# 🚨 1. CONFIGURAÇÃO E LOGGING (Mantida)
# ...
# ====================================================================

LOG_FILE = 'disparo_telegram.log'
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

# ====================================================================
# 🚨 2. CONFIGURAÇÃO DO APP E ESTADO DE SESSÃO (Mantida)
# ...
# (BOT_TOKEN, SHEET_ID, USER_CREDENTIALS, etc.)
# ====================================================================

BOT_TOKEN = "8586446411:AAH_jXK0Yv6h64gRLhoK3kv2kJo4mG5x3LE" 
CREDENTIALS_FILE = '/home/charle/scripts/chaveBigQuery.json' 
SHEET_ID = '1HSIwFfIr67i9K318DX1qTwzNtrJmaavLKUlDpW5C6xU' 
WORKSHEET_NAME_TELEGRAM = 'lista_telegram' 
WORKSHEET_NAME_WHATSAPP = 'lista_whatsapp'

USER_CREDENTIALS = {"charle": "equipe123", "admin": "admin456"}

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'PERMANENT_LOGIN' not in st.session_state: st.session_state['logged_in'] = st.session_state.get('PERMANENT_LOGIN', False)

# ====================================================================
# 🌐 3. FUNÇÕES DE CONEXÃO E ENVIO (Mantidas)
# ... (get_gspread_client, carregar_listas_db, substituir_variaveis, etc.)
# ====================================================================

# (Funções: get_gspread_client, carregar_listas_db, substituir_variaveis, enviar_mensagem_telegram_api, enviar_foto_telegram_api, enviar_mensagem_whatsapp_api e processar_disparo devem ser mantidas conforme a última versão enviada).

# --- Funções de Login e Inicialização (Mantidas) ---

def login_form():
    # ... (Conteúdo da função mantido)
    hide_streamlit_style_login = """
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;} [data-testid="stDecoration"] {visibility: hidden;} 
    </style>
    """
    st.markdown(hide_streamlit_style_login, unsafe_allow_html=True)
    st.set_page_config(page_title="Login - Broadcaster Telegram", layout="centered")
    st.title("🛡️ Acesso Restrito"); st.markdown("---")
    with st.form("login_form"):
        username = st.text_input("Usuário:"); password = st.text_input("Senha:", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
        if submitted:
            if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password: 
                st.session_state['logged_in'] = True; st.session_state['username'] = username
                st.session_state['PERMANENT_LOGIN'] = True; st.rerun()
            else: st.error("Usuário ou senha inválidos.")

def logout_button():
    if st.sidebar.button("Sair", type="secondary"):
        st.session_state['logged_in'] = False; st.session_state['PERMANENT_LOGIN'] = False
        st.session_state.pop('username', None); st.rerun()

# ====================================================================
# 🖼️ 5. INTERFACE GRÁFICA PRINCIPAL (APP_UI)
# ====================================================================

def app_ui():
    
    # 🪄 CSS GERAL: Oculta todos os elementos visuais indesejados
    hide_streamlit_style_app = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;} 
    [data-testid="stDecoration"] {visibility: hidden;} 
    </style>
    """
    st.markdown(hide_streamlit_style_app, unsafe_allow_html=True)
    
    st.set_page_config(page_title="Broadcaster Multi-Canal | Equipe", layout="wide") 
    st.title("📢 Sistema de Disparo Multi-Canal")
    st.sidebar.markdown(f"Usuário: **{st.session_state['username']}**")
    logout_button()
    st.sidebar.header("Configuração de Destinatários")

    recarregar_lista = st.sidebar.button("🔄 Recarregar Dados da Planilha", type="secondary")
    if recarregar_lista:
        st.cache_data.clear()

    # 1. CARREGA AS LISTAS DE AMBOS OS CANAIS
    listas_telegram_data = carregar_listas_db(WORKSHEET_NAME_TELEGRAM)
    listas_whatsapp_data = carregar_listas_db(WORKSHEET_NAME_WHATSAPP)
    
    # 2. TRATAMENTO DE ERRO NA CONEXÃO
    
    # Verifica se a lista do Telegram falhou criticamente (Conexão GSheets)
    if "Erro de Conexão" in listas_telegram_data:
        st.error("Falha ao carregar a lista do Telegram. Verifique as credenciais da Planilha.")
        return 
    
    # 🟢 CORREÇÃO DO FLUXO: Define a lista de nomes apenas se for um dicionário de listas válido
    if isinstance(listas_telegram_data, dict):
        nomes_listas_telegram = list(listas_telegram_data.keys())
    else:
        # Se for o erro de colunas, a função retornou {}, então a lista está vazia
        nomes_listas_telegram = []

    # Aviso se a lista do WhatsApp falhou criticamente (apenas aviso, não bloqueia o app)
    if "Erro de Conexão" in listas_whatsapp_data or not listas_whatsapp_data:
        st.warning("⚠️ Falha na conexão/colunas para WhatsApp. A funcionalidade WhatsApp será limitada.")
    
    if isinstance(listas_whatsapp_data, dict):
        nomes_listas_whatsapp = list(listas_whatsapp_data.keys())
    else:
        nomes_listas_whatsapp = []
    
    
    # --- SEPARAÇÃO POR ABAS (Telegram e WhatsApp) ---
    tab_telegram, tab_whatsapp = st.tabs(["🟦 Telegram", "🟢 WhatsApp"])

    # --- ABA 1: TELEGRAM ---
    with tab_telegram:
        st.markdown('### <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/8/82/Telegram_logo.svg/24px-Telegram_logo.svg.png" style="width:24px; vertical-align:middle;"> Disparo Telegram', unsafe_allow_html=True)

        imediato_listas_selecionadas = st.multiselect("Selecione as Listas para Disparo:", nomes_listas_telegram, key="telegram_lists")
        imediato_uploaded_file = st.file_uploader("🖼️ Anexar Imagem (Opcional)", type=["png", "jpg", "jpeg"], key="telegram_img")
        imediato_mensagem = st.text_area("📝 Mensagem para Disparo (Use {nome} ou @nome para personalizar)", height=150, key="telegram_msg")
        
        imediato_ids_para_disparo = set()
        for nome_lista in imediato_listas_selecionadas: imediato_ids_para_disparo.update(listas_telegram_data.get(nome_lista, []))
            
        st.info(f"Telegram: Serão alcançados **{len(imediato_ids_para_disparo)}** CHAT IDs únicos.")

        if st.button("🚀 Disparar Telegram Agora", key="btn_telegram", type="primary"):
            if not imediato_listas_selecionadas: st.error("Selecione pelo menos uma Lista."); return
            if not imediato_mensagem.strip() and imediato_uploaded_file is None: st.error("Conteúdo vazio."); return

            processar_disparo('Telegram', imediato_listas_selecionadas, imediato_mensagem, imediato_uploaded_file, listas_telegram_data)
            
            
    # --- ABA 2: WHATSAPP ---
    with tab_whatsapp:
        st.markdown('### <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/WhatsApp.svg/24px-WhatsApp_logo.svg.png" style="width:24px; vertical-align:middle;"> Disparo WhatsApp (Não Oficial)', unsafe_allow_html=True)
        st.warning("⚠️ RISCO DE BLOQUEIO: Este método não usa a API oficial. O envio deve ser moderado, e o número precisa estar logado no WhatsApp Web.")

        whatsapp_listas_selecionadas = st.multiselect("Selecione as Listas para Disparo:", nomes_listas_whatsapp, key="whatsapp_lists")
        whatsapp_uploaded_file = st.file_uploader("🖼️ Anexar Imagem (Opcional)", type=["png", "jpg", "jpeg"], key="whatsapp_img")
        whatsapp_mensagem = st.text_area("Mensagem para Disparo (Use {nome} ou @nome para personalizar)", height=150, key="whatsapp_msg")

        whatsapp_ids_para_disparo = set()
        for nome_lista in whatsapp_listas_selecionadas: whatsapp_ids_para_disparo.update(listas_whatsapp_data.get(nome_lista, []))

        st.info(f"WhatsApp: Serão alcançados **{len(whatsapp_ids_para_disparo)}** NÚMEROS únicos.")

        if st.button("🚀 Disparar WhatsApp Agora", key="btn_whatsapp", type="primary"):
            if not whatsapp_listas_selecionadas: st.error("Selecione pelo menos uma Lista."); return
            if not whatsapp_mensagem.strip(): st.error("Conteúdo vazio."); return
            
            # ⚠️ CHAMA A FUNÇÃO DE ENVIO DO WHATSAPP (PLACEHOLDER)
            processar_disparo('WhatsApp', whatsapp_listas_selecionadas, whatsapp_mensagem, whatsapp_uploaded_file, listas_whatsapp_data)


# --- Funções Main e Inicialização ---
def main():
    if st.session_state['logged_in']:
        app_ui()
    else:
        login_form()

if __name__ == "__main__":
    main()