import streamlit as st
import requests
import gspread 
from gspread.auth import ServiceAccountCredentials
import pandas as pd
import logging
from datetime import datetime, timedelta
import uuid 
import hashlib 
import json 

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

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'agendamentos_ativos' not in st.session_state:
    st.session_state['agendamentos_ativos'] = [] 

# ====================================================================
# 🌐 3. FUNÇÕES DE CONEXÃO E ENVIO
# ====================================================================

def get_gspread_client():
    """Retorna o cliente gspread autenticado via Streamlit Secrets ou arquivo local."""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    try:
        if 'google_service_account' in st.secrets:
            # 🟢 Autenticação via Streamlit Secrets (Cloud)
            creds_info = st.secrets["google_service_account"]
            
            if isinstance(creds_info, dict):
                 creds = ServiceAccountCredentials.from_service_account_info(creds_info, scope)
            else:
                 creds = ServiceAccountCredentials.from_service_account_info(json.loads(creds_info), scope)
        else:
            # 🟡 Autenticação via arquivo local (Ubuntu Server)
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            
        return gspread.authorize(creds)
        
    except Exception as e:
        logger.critical(f"Falha na Autenticação GSpread: {e}")
        # 🚨 NOVO: Exibimos o erro crítico na interface para diagnóstico
        st.error(f"ERRO DE AUTENTICAÇÃO CRÍTICA: {e}") 
        return None

@st.cache_data(ttl=300, show_spinner="Buscando lista de destinatários...")
def carregar_destinatarios_db():
    """Conecta ao Google Sheets e busca a lista de IDs, agrupando-os por nome da lista."""
    
    DESTINATARIOS = {} 
    
    try:
        client = get_gspread_client()
        # Se a autenticação falhou, client será None, e retornamos o erro
        if client is None:
            # A mensagem de erro já foi exibida em get_gspread_client()
            return {"Erro de Conexão": "0"} 

        sheet = client.open_by_key(SHEET_ID)
        worksheet = sheet.worksheet(WORKSHEET_NAME)
        
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        if 'lista' in df.columns and 'ids' in df.columns:
            
            for index, row in df.iterrows():
                nome_lista = str(row['lista']).strip()
                chat_id = str(row['ids']).strip()
                
                if nome_lista and chat_id:
                    if nome_lista not in DESTINATARIOS:
                        DESTINATARIOS[nome_lista] = []
                    DESTINATARIOS[nome_lista].append(chat_id)
            
            return DESTINATARIOS
        else:
            return {"Erro de Colunas": "0"}

    except Exception as e:
        # 🚨 NOVO: Exibimos o erro de leitura na interface
        st.error(f"ERRO NA LEITURA DA PLANILHA: {e}") 
        logger.critical(f"Falha ao carregar a lista de destinatários: {e}")
        return {"Erro de Conexão": "0"}

def enviar_mensagem(chat_id, texto):
    """Envia apenas texto (Markdown) para um CHAT_ID específico."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = { 'chat_id': chat_id, 'text': texto, 'parse_mode': 'Markdown' }
    
    try:
        response = requests.post(url, data=payload); response.raise_for_status()
        return True, response.json()
    except requests.exceptions.RequestException as e: return False, str(e)

def enviar_foto(chat_id, foto_bytes, legenda=None):
    """Envia uma foto (com legenda opcional) para um CHAT_ID específico."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {'photo': ('imagem.jpg', foto_bytes, 'image/jpeg')} 
    data = {'chat_id': chat_id}
    
    if legenda: data['caption'] = legenda; data['parse_mode'] = 'Markdown'
    
    try:
        response = requests.post(url, files=files, data=data); response.raise_for_status()
        return True, response.json()
    except requests.exceptions.RequestException as e: return False, str(e)

def processar_disparo(ids_para_disparo, mensagem, uploaded_file):
    """Função central que executa o envio para todos os IDs, com logging e feedback."""
    
    file_bytes = None
    if uploaded_file is not None:
        if hasattr(uploaded_file, 'seek'): uploaded_file.seek(0)
        file_bytes = uploaded_file.read() 
    
    total_enviados = 0
    erros = []

    with st.spinner(f'Iniciando envio para {len(ids_para_disparo)} destinatários...'):
        
        progress_bar = st.progress(0, text="Preparando envio...")
        
        for i, chat_id_unico in enumerate(ids_para_disparo):
            
            if file_bytes is not None:
                sucesso, resultado = enviar_foto(chat_id_unico, file_bytes, mensagem)
            else:
                sucesso, resultado = enviar_mensagem(chat_id_unico, mensagem)

            if sucesso: total_enviados += 1; logger.info(f"SUCESSO: Mensagem enviada para o ID: {chat_id_unico}")
            else: erros.append(f"ID {chat_id_unico}: Falha -> {resultado}"); logger.error(f"FALHA: Erro ao enviar para o ID {chat_id_unico}. Detalhes: {resultado}")

            percentual = (i + 1) / len(ids_para_disparo)
            progress_bar.progress(percentual, text=f"Enviando... {i + 1} de {len(ids_para_disparo)}")

    progress_bar.empty()
    st.success(f"✅ Disparo concluído! **{total_enviados}** mensagens enviadas com sucesso.")
    
    logger.info(f"FIM DO DISPARO: Enviados: {total_enviados}, Falhas: {len(erros)}")
    
    if erros:
        st.warning(f"⚠️ Atenção! Ocorreram {len(erros)} falhas de envio. Verifique o arquivo '{LOG_FILE}' para detalhes.")
        for erro in erros: st.code(erro.split(': Falha -> ')[0])
            
    return total_enviados

def checar_gatilhos_e_executar(lista_destinatarios):
    """Simula a execução de tarefas agendadas quando a página é recarregada."""
    
    agendamentos_para_remover = []
    
    for agendamento in st.session_state['agendamentos_ativos']:
        
        data_execucao = datetime.strptime(agendamento['data_execucao'], '%Y-%m-%d %H:%M:%S')

        if data_execucao <= datetime.now():
            
            st.warning(f"⏰ EXECUTANDO TAREFA AGENDADA: {agendamento['titulo']}...")
            
            ids_para_disparo = set()
            for nome_lista in agendamento['listas_selecionadas']: ids_para_disparo.update(lista_destinatarios.get(nome_lista, []))
            
            if agendamento['tem_imagem']: st.error("❌ FALHA DE AGENDAMENTO DE IMAGEM: Imagens não são persistidas no agendamento em memória.")
            else: processar_disparo(ids_para_disparo, agendamento['mensagem'], None) 
            
            agendamento['recorrencia_restante'] -= 1
            
            if agendamento['recorrencia_restante'] > 0:
                proximo_agendamento = data_execucao + timedelta(days=1) 
                agendamento['data_execucao'] = proximo_agendamento.strftime('%Y-%m-%d %H:%M:%S')
                st.success(f"Recorrência de '{agendamento['titulo']}' agendada para: {proximo_agendamento}")
            else: agendamentos_para_remover.append(agendamento['id'])
                
    st.session_state['agendamentos_ativos'] = [ag for ag in st.session_state['agendamentos_ativos'] if ag['id'] not in agendamentos_para_remover]
    if agendamentos_para_remover: st.rerun()

# ====================================================================
# 🔒 FUNÇÕES DE LOGIN/LOGOUT (MANTIDAS)
# ====================================================================

def login_form():
    """Exibe o formulário de login e processa a autenticação."""
    st.set_page_config(page_title="Login - Broadcaster Telegram", layout="centered")
    st.title("🛡️ Acesso Restrito")
    st.markdown("---")

    with st.form("login_form"):
        username = st.text_input("Usuário:"); password = st.text_input("Senha:", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
        if submitted:
            if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password: 
                st.session_state['logged_in'] = True; st.session_state['username'] = username; st.rerun()
            else: st.error("Usuário ou senha inválidos.")

def logout_button():
    """Botão de Logout simples."""
    if st.sidebar.button("Sair", type="secondary"):
        st.session_state['logged_in'] = False; st.session_state.pop('username', None); st.rerun()

# ====================================================================
# 🖼️ 5. INTERFACE GRÁFICA PRINCIPAL (APP_UI)
# ====================================================================

def app_ui():
    
    # 🪄 NOVO: Oculta o menu de três pontos e a marca d'água
    hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """
    st.markdown(hide_streamlit_style, unsafe_allow_html=True)
    
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
    # Se a lista não carregar devido a erro, o retorno antecipado evita o travamento
    if "Erro de Conexão" in lista_destinatarios or "Erro de Colunas" in lista_destinatarios:
        return 
    
    nomes_listas = list(lista_destinatarios.keys())
    
    # 3. CHECA GATILHOS (SIMULAÇÃO)
    checar_gatilhos_e_executar(lista_destinatarios)

    # --- SEPARAÇÃO POR ABAS ---
    tab_imediato, tab_programar = st.tabs(["🚀 Disparo Imediato", "🗓️ Programar Envio"])

    # --- LÓGICA DE DISPARO IMEDIATO ---
    with tab_imediato:
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
            
            
    # --- LÓGICA DE PROGRAMAR ENVIO ---
    with tab_programar:
        st.header("Agendamento de Mensagens")
        
        with st.form("form_agendamento"):
            st.subheader("Novo Agendamento")

            titulo_agendamento = st.text_input("📝 Título do Agendamento (ex: Lembrete Mensal)", key="prog_titulo")
            
            col1, col2, col3 = st.columns([1, 1, 0.5])
            with col1: data_agendamento = st.date_input("🗓️ Data do Envio:", min_value=datetime.today().date(), key="prog_data")
            with col2: hora_agendamento = st.time_input("⏰ Hora do Envio:", key="prog_hora", value=datetime.now().time().replace(second=0, microsecond=0))
            with col3: recorrencia = st.number_input("🔁 Recorrência (vezes):", min_value=1, value=1, step=1, key="prog_recor")
            
            programar_listas_selecionadas = st.multiselect("Selecione as Listas para Agendamento:", nomes_listas, key="prog_lists")
            programar_uploaded_file = st.file_uploader("🖼️ Anexar Imagem (Opcional)", type=["png", "jpg", "jpeg"], key="prog_img")
            programar_mensagem = st.text_area("📝 Mensagem para Agendamento", height=150, key="prog_msg")
            
            submitted = st.form_submit_button("💾 Programar Envio", type="primary")

            if submitted:
                # 1. Validações
                if not programar_listas_selecionadas: st.error("Selecione pelo menos uma Lista."); return
                if not programar_mensagem.strip() and programar_uploaded_file is None: st.error("Conteúdo vazio."); return
                if not titulo_agendamento.strip(): st.error("O título do agendamento é obrigatório."); return
                
                agendamento_dt = datetime.combine(data_agendamento, hora_agendamento)
                if agendamento_dt <= datetime.now(): st.error("A data e hora de agendamento devem estar no futuro."); return

                # 2. Cria Objeto de Agendamento
                novo_agendamento = {
                    'id': str(uuid.uuid4()),
                    'titulo': titulo_agendamento,
                    'data_execucao': agendamento_dt.strftime('%Y-%m-%d %H:%M:%S'),
                    'recorrencia_total': recorrencia,
                    'recorrencia_restante': recorrencia,
                    'listas_selecionadas': programar_listas_selecionadas,
                    'mensagem': programar_mensagem,
                    'tem_imagem': programar_uploaded_file is not None,
                    'criacao': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # 3. Adiciona ao estado (memória)
                st.session_state['agendamentos_ativos'].append(novo_agendamento)
                st.success(f"✅ Agendamento '{titulo_agendamento}' criado com sucesso para {agendamento_dt.strftime('%d/%m/%Y às %H:%M')}.")
                logger.info(f"AGENDAMENTO CRIADO: Título: {titulo_agendamento}, Data: {novo_agendamento['data_execucao']}")
                st.rerun()

        # --- Lista de Agendamentos Ativos ---
        st.markdown("---"); st.subheader("Agendamentos Ativos (Em Memória)")
        
        if st.session_state['agendamentos_ativos']:
            
            df_agendamentos = pd.DataFrame(st.session_state['agendamentos_ativos'])
            df_agendamentos['próximo_envio'] = df_agendamentos['data_execucao'].apply(lambda x: datetime.strptime(x, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M'))
            
            cols_exibicao = ['próximo_envio', 'titulo', 'recorrencia_restante', 'listas_selecionadas', 'tem_imagem', 'id']
            df_display = df_agendamentos[cols_exibicao]
            df_display.columns = ['Próximo Envio', 'Título', 'Recorrências', 'Listas Alvo', 'Com Imagem', 'ID']

            st.dataframe(df_display, hide_index=True, use_container_width=True)
            
            # --- Opção de Cancelamento ---
            st.markdown("##### Cancelar Envio:")
            cancel_id = st.text_input("ID do Agendamento para Cancelar (Copie da tabela acima):", key="cancel_id")
            
            if st.button("❌ Cancelar Agendamento", type="secondary"):
                agendamento_cancelado = [ag for ag in st.session_state['agendamentos_ativos'] if ag['id'] == cancel_id]
                
                if agendamento_cancelado:
                    st.session_state['agendamentos_ativos'] = [ag for ag in st.session_state['agendamentos_ativos'] if ag['id'] != cancel_id]
                    st.success(f"✅ Agendamento '{agendamento_cancelado[0]['titulo']}' ({cancel_id}) cancelado com sucesso.")
                    logger.info(f"AGENDAMENTO CANCELADO: ID: {cancel_id}, Título: {agendamento_cancelado[0]['titulo']}")
                    st.rerun()
                else: st.error("ID de agendamento não encontrado.")

        else: st.info("Nenhum agendamento ativo.")

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