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
                    if nome_lista not in DESTINATARIOS: DESTINATARIOS[nome_lista] = []
                    DESTINATARIOS[nome_lista].append({'id': destinatario_id, 'nome': nome_destinatario})
            
            return DESTINATARIOS
        else:
            st.error(f"ERRO DE COLUNAS na aba '{worksheet_name}'. Obrigatórias: 'lista', 'nome', e 'ids'.")
            return {"Erro de Colunas": "0"}

    except Exception as e:
        st.error(f"ERRO NA LEITURA DA PLANILHA '{worksheet_name}': {e}") 
        logger.critical(f"Falha ao carregar a lista de destinatários ({worksheet_name}): {e}")
        return {"Erro de Conexão": "0"}

def substituir_variaveis(mensagem_original, nome_destinatario):
    """Substitui as variáveis {nome} ou @nome na mensagem."""
    nome = nome_destinatario if nome_destinatario else "Cliente"
    mensagem_processada = mensagem_original.replace("{nome}", nome)
    mensagem_processada = mensagem_original.replace("@nome", nome)
    return mensagem_processada

def coletar_ids_telegram():
    """Busca novos IDs de chat que interagiram com o bot e salva na planilha."""
    
    TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    
    try:
        response = requests.get(TELEGRAM_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'result' not in data or not data['result']:
            st.warning("Nenhuma interação encontrada. Peça aos usuários que enviem uma mensagem para o bot.")
            return

        sh = get_gspread_client()
        if sh is None: return
        
        # 1. Tenta obter a aba. Se não existir, cria com cabeçalho
        try:
            ws = sh.worksheet(WORKSHEET_NAME_AUTORIZACAO)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=WORKSHEET_NAME_AUTORIZACAO, rows="100", cols="3")
            ws.update('A1:C1', [['ID_CHAT', 'NOME_USUARIO', 'DATA_AUTORIZACAO']])
            # Força o cache a limpar para a próxima leitura
            st.cache_data.clear() 
            
        # 2. Verifica se o cabeçalho está correto antes de ler (segurança extra)
        header = ws.row_values(1)
        if header != ['ID_CHAT', 'NOME_USUARIO', 'DATA_AUTORIZACAO']:
             # 🔴 Se o cabeçalho estiver errado (com caracteres invisíveis), avisa
             st.error("ERRO: O cabeçalho da aba 'autorizacao' está incorreto. Exclua a Linha 1 e digite novamente: ID_CHAT, NOME_USUARIO, DATA_AUTORIZACAO.")
             return
            
        # 3. Obtém IDs já existentes e salva novos
        existing_ids = set(ws.col_values(1)[1:]) 
        new_rows = []
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        last_update_id = 0
        
        for update in data['result']:
            if 'message' in update and 'chat' in update['message']:
                chat = update['message']['chat']
                chat_id = str(chat['id'])
                last_update_id = max(last_update_id, update['update_id'])
                
                if chat_id not in existing_ids:
                    user_name = chat.get('username') or chat.get('first_name', 'N/A')
                    new_rows.append([chat_id, user_name, now_str])
                    existing_ids.add(chat_id)
                    
        if new_rows:
            # 🟢 ESCREVE OS DADOS
            ws.append_rows(new_rows)
            st.success(f"✅ {len(new_rows)} novos usuários de Telegram autorizados e salvos na planilha!")
        else:
            st.info("Nenhuma nova interação (ID) encontrada desde a última verificação.")
            
        # Limpa o offset para que o botão funcione corretamente no próximo clique.
        if last_update_id > 0:
            requests.get(TELEGRAM_API_URL + f"?offset={last_update_id + 1}", timeout=5)
        
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com a API do Telegram: {e}")
    except Exception as e:
        # 🔴 Captura qualquer erro de escrita na planilha e exibe
        st.error(f"Erro ao salvar IDs na planilha (Verifique as permissões de ESCRITA!): {e}")

# --- Funções de Envio de API (Telegram) ---
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
    """Função central que executa o envio para o Telegram."""
    
    file_bytes = None
    if uploaded_file is not None:
        if hasattr(uploaded_file, 'seek'): file_bytes = uploaded_file.read() 
    
    destinatarios_raw = []
    for nome_lista in listas_selecionadas: destinatarios_raw.extend(listas_dados.get(nome_lista, []))
    destinatarios = pd.DataFrame(destinatarios_raw).drop_duplicates(subset=['id']).to_dict('records')
    if not destinatarios: st.error("Nenhum destinatário encontrado."); return

    total_enviados = 0; erros = []

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

            percentual = (i + 1) / len(destinatarios); progress_bar.progress(percentual, text=f"Enviando... {i + 1} de {len(destinatarios)}")

    progress_bar.empty(); st.success(f"✅ Disparo Telegram concluído! **{total_enviados}** mensagens enviadas com sucesso.")
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
    
    # LOGO E TÍTULO NA TELA DE LOGIN
    st.markdown(
        f'<div style="text-align: center;">'
        f'<img src="https://upload.wikimedia.org/wikipedia/commons/thumb/8/82/Telegram_logo.svg/100px-Telegram_logo.svg.png" width="40" style="vertical-align:middle; margin-right: 10px;">'
        f'<h3>GRUPO CR</h3>'
        f'</div>',
        unsafe_allow_html=True
    ) 
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
    
    # 🆕 1. LOGO E TÍTULO DA EMPRESA NO CANTO ESQUERDO DA SIDEBAR
    st.sidebar.markdown(
        f'<div style="text-align: center; margin-bottom: 20px; border-bottom: 1px solid #303030; padding-bottom: 15px;">'
        f'<img src="https://raw.githubusercontent.com/charlevaz/telegram-broadcaster/main/cr.png" width="80" style="border-radius: 10px; box-shadow: 0 0 5px rgba(0,0,0,0.2);">'
        f'<h4 style="margin: 0; padding-top: 10px; color: white;">GRUPO CR</h4>'
        f'</div>',
        unsafe_allow_html=True
    )
    
    st.title("📢 Sistema de Disparo Telegram")
    st.sidebar.markdown(f"Usuário: **{st.session_state['username']}**")
    logout_button()
    st.sidebar.header("Configuração de Destinatários")

    # 🔴 NOVO: Botões renderizados na ordem correta
    
    # Botão 1: Coletar IDs
    if st.sidebar.button("🤖 Coletar Novos IDs de Autorização", type="primary", use_container_width=True):
        coletar_ids_telegram()
        st.cache_data.clear() # Limpa cache de listas após coleta
        st.rerun()
        
    # Botão 2: Recarregar a Lista de Disparo
    recarregar_lista = st.sidebar.button("🔄 Recarregar Lista de Disparo", type="secondary", use_container_width=True)
    if recarregar_lista: st.cache_data.clear(); st.rerun()
    st.sidebar.markdown('---')


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
    
    imediato_ids_para_disparo = set()
    for nome_lista in imediato_listas_selecionadas: 
        destinatarios_da_lista = listas_telegram_data.get(nome_lista, [])
        imediato_ids_para_disparo.update([d['id'] for d in destinatarios_da_lista])
        
    st.info(f"Telegram: Serão alcançados **{len(imediato_ids_para_disparo)}** CHAT IDs únicos.")

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