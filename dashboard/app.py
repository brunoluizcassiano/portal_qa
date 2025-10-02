import streamlit as st
import requests
import yaml
import json
import os
import time
from streamlit_option_menu import option_menu
from visualizar_fluxos import pagina_visualizar_fluxos
from visualizar_fluxo_bonito import pagina_fluxo_bonito
from dashboard_historico import pagina_dashboard_historico
from coeqa.dashboard_home import pagina_dashboard_home
from coeqa.dashboard_kpi import pagina_dashboard_kpi
from coeqa.dashboard_score import pagina_dashboard_score
from coeqa.dashboard_covaregeAndRun import pagina_dashboard_coverage_and_run
from coeqa.dashboard_analytical import pagina_dashboard_analytical
from coeqa.dashboard_bugs import pagina_dashboard_bugs
from coeqa.dashboard_waves import pagina_dashboard_waves
from coeqa.dashboard_regression import pagina_dashboard_regression
from coeqa.dashboard_automation import pagina_dashboard_automation
from coeqa.dashboard_roi import pagina_dashboard_roi
from admin_fluxos import pagina_admin_fluxos
from admin_agendamentos import pagina_admin_agendamentos
from dashboard_status_agendamentos import pagina_dashboard_status
from gestao_massa import pagina_gestao_massa
from home import pagina_home
from home_massa import pagina_home_massa
# === CONFIGURAÇÕES ===
MASSAS_FILE = 'config/massai_massa_gerada.yaml'
with open('config/settings.yaml') as f:
    settings = yaml.safe_load(f)
API_URL = settings.get('api_url', 'http://massai-api:8000')
# === FUNÇÕES ===
def salvar_massa_gerada(fluxo_name, dados):
    if os.path.exists(MASSAS_FILE):
        with open(MASSAS_FILE, 'r') as f:
            massas = yaml.safe_load(f) or []
    else:
        massas = []
    novo_registro = {
        "fluxo_name": fluxo_name,
        "status": "valida",   # Quando gerada assume como 'valida'
        "dados": dados,
        "data_criacao": time.strftime("%d/%m/%Y %H:%M:%S")
    }
    massas.append(novo_registro)
    with open(MASSAS_FILE, 'w') as f:
        yaml.dump(massas, f, allow_unicode=True)
# === SIDEBAR ===
from streamlit_option_menu import option_menu
import streamlit as st
with st.sidebar:
    pagina_principal = option_menu(
        menu_title="CIQ - PLARD",
        options=["Home", "Massa de Dados", "KPI's de Qualidade"],
        icons=["house", "database", "bar-chart-line"],
        menu_icon="cast",
        default_index=0,
        # --- Adicione o parâmetro 'styles' ---
        styles={
            "menu-title": {"font-size": "16px"} # Altere o tamanho da fonte aqui
        }
        # --------------------------------------
    )
# === PÁGINAS ===
if pagina_principal == "Home":
    pagina_home()
# Mostrar submenu apenas se "Massa de Dados" estiver selecionado
elif pagina_principal == "Massa de Dados":
    submenu = option_menu(
        menu_title="Massa de Dados",  # Título do submenu (opcional)
        options=["Home", "Gerar Massas", "Dashboards de Massa", "Administração de Sistema"],  # Subitens
        icons=["house", "rocket", "bar-chart-line", "gear"],
        menu_icon="database",
        default_index=0,
        orientation="horizontal"  # Pode ser "horizontal" ou "vertical"
    )
    # Use o submenu para mostrar páginas ou funcionalidades específicas
    if submenu == "Home":
        pagina_home_massa()
    
    elif submenu == "Gerar Massas":
        subsubmenu = option_menu(
            menu_title=None,
            options=["Gerar Massas", "Fluxos", "Gestão de Massa"],
            icons=["play", "shuffle", "database"],
            default_index=0,
            orientation="horizontal",
        )
        if subsubmenu == "Gerar Massas":
            st.title("🚀 Geração de Massas")
            st.subheader("Selecione o fluxo e execute:")
            try:
                with open('config/fluxos.yaml') as f:
                    fluxos_yaml = yaml.safe_load(f)
                fluxos = list(fluxos_yaml.keys())
            except Exception:
                fluxos = []
            if fluxos:
                fluxo_escolhido = st.selectbox("🧩 Escolha o fluxo:", fluxos)
                quantidade = st.slider("🔢 Quantidade de massas:", 1, 100, 10)
                if st.button("🚀 Executar Fluxo"):
                    params = {"fluxo_name": fluxo_escolhido, "quantidade": quantidade}
                    with st.spinner("⏳ Executando fluxo, aguarde..."):
                        try:
                            response = requests.post(f"{API_URL}/run_fluxo/", json=params)
                            if response.status_code == 200:
                                resultado = response.json()
                                st.success("✅ Fluxo executado com sucesso!")
                                st.json(resultado)
                                # Salvar massa
                                salvar_massa_gerada(fluxo_escolhido, resultado)
                                # Permitir download
                                json_bytes = json.dumps(resultado, indent=2).encode('utf-8')
                                st.download_button(
                                    label="📥 Baixar Resultado",
                                    data=json_bytes,
                                    file_name=f"massa_{fluxo_escolhido.replace(' ', '_')}.json",
                                    mime='application/json'
                                )
                            else:
                                st.error(f"❌ Erro na execução:\n\n{response.text}")
                        except Exception as e:
                            st.error(f"❌ Erro de conexão:\n\n{e}")
            else:
                st.warning("⚠️ Nenhum fluxo encontrado. Cadastre um novo fluxo para começar.")
        elif subsubmenu == "Fluxos":
            pagina_fluxo_bonito()
        elif subsubmenu == "Gestão de Massa":
            pagina_gestao_massa()
    
    elif submenu == "Dashboards de Massa":
        subsubmenu = option_menu(
            menu_title=None,
            options=["Dashboard Histórico", "Status dos Agendamentos"],
            icons=["clipboard-data", "clock-history"],
            default_index=0,
            orientation="horizontal",
        )
        if subsubmenu == "Dashboard Histórico":
            pagina_dashboard_historico()
        elif subsubmenu == "Status dos Agendamentos":
            pagina_dashboard_status()
    elif submenu == "Administração de Sistema":
        subsubmenu = option_menu(
            menu_title=None,
            options=["Administração de Fluxos", "Administração de Agendamentos"],
            icons=["tools", "calendar-check"],
            default_index=0,
            orientation="horizontal",
        )
        if subsubmenu == "Administração de Fluxos":
            pagina_admin_fluxos()
        elif subsubmenu == "Administração de Agendamentos":
            pagina_admin_agendamentos()
elif pagina_principal == "KPI's de Qualidade":
    submenu = option_menu(
        menu_title=None,
        options=["Home", "KPI's", "Score", "Coverage and Run", "Analytical", "Bugs", "Waves", "Regressivo", "Automation", "ROI"],
        icons=["clipboard-data", "clock-history", "graph-up", "check2-circle", "bar-chart", "bug", "rocket", "arrow-clockwise", "robot", "currency-dollar"],
        default_index=0,
        orientation="horizontal",
        # --- Estilos Customizados ---
        styles={
            # Estilo para cada item do menu
            "nav-link": {
                "font-size": "12px",  # Reduz o tamanho da fonte (ajuste conforme a necessidade)
                "padding": "5px 10px", # Reduz o padding para diminuir o espaço
                "white-space": "nowrap", # Garante que o texto fique em uma única linha (impede quebras)
                "overflow": "hidden", # Esconde qualquer texto que transborde
                "text-overflow": "ellipsis" # Adiciona '...' se o texto for cortado
            },
            # Estilo para o item selecionado
            "nav-link-selected": {
                "font-size": "12px",
                "padding": "5px 10px",
                # Você pode adicionar um 'background-color' ou 'color' diferente para o item selecionado aqui, se quiser
            },
            # Estilo para o contêiner geral do menu (opcional, mas útil)
            "container": {
                "width": "100%", # Ocupa toda a largura disponível
            }
        }
        # ----------------------------
    )
    # Lista de opções desabilitadas
    desabilitadas = ["Score", "Coverage and Run", "Analytical", "Bugs", "Waves", "Regressivo", "Automation", "ROI"]
    
    if submenu in desabilitadas:
        st.warning(f"A opção '{submenu}' está desabilitada no momento.")
    elif submenu == "Home":
        pagina_dashboard_home()
    elif submenu == "KPI's":
        pagina_dashboard_kpi()
    elif submenu == "Score":
        pagina_dashboard_score()
    
    elif submenu == "Coverage and Run":
        pagina_dashboard_coverage_and_run()
    elif submenu == "Analytical":
        pagina_dashboard_analytical()
    
    elif submenu == "Bugs":
        pagina_dashboard_bugs()
        
    elif submenu == "Waves":
        pagina_dashboard_waves()
    elif submenu == "Regressivo":
        pagina_dashboard_regression()
    
    elif submenu == "Automation":
        pagina_dashboard_automation()
    elif submenu == "ROI":
        pagina_dashboard_roi()
