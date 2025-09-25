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
from admin_fluxos import pagina_admin_fluxos
from admin_agendamentos import pagina_admin_agendamentos
from dashboard_status_agendamentos import pagina_dashboard_status
from gestao_massa import pagina_gestao_massa
from home import pagina_home

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
with st.sidebar:
    pagina_principal = option_menu(
        menu_title="Menu Principal\nMassAI",
        options=["Home", "Geração de Massa", "Dashboards de Massa", "KPI's de Qualidade", "Administração de Sistema"],
        icons=["house", "rocket", "bar-chart-line", "bar-chart-line", "gear"],
        menu_icon="cast",
        default_index=0,
    )

# === PÁGINAS ===
if pagina_principal == "Home":
    pagina_home()

elif pagina_principal == "Geração de Massa":
    submenu = option_menu(
        menu_title=None,
        options=["Gerar Massas", "Fluxos", "Gestão de Massa"],
        icons=["play", "shuffle", "database"],
        default_index=0,
        orientation="horizontal",
    )

    if submenu == "Gerar Massas":
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

    elif submenu == "Fluxos":
        pagina_fluxo_bonito()

    elif submenu == "Gestão de Massa":
        pagina_gestao_massa()

elif pagina_principal == "Dashboards de Massa":
    submenu = option_menu(
        menu_title=None,
        options=["Dashboard Histórico", "Status dos Agendamentos"],
        icons=["clipboard-data", "clock-history"],
        default_index=0,
        orientation="horizontal",
    )

    if submenu == "Dashboard Histórico":
        pagina_dashboard_historico()

    elif submenu == "Status dos Agendamentos":
        pagina_dashboard_status()

elif pagina_principal == "KPI's de Qualidade":
    submenu = option_menu(
        menu_title=None,
        options=["Dashboard Histórico", "Status dos Agendamentos"],
        icons=["clipboard-data", "clock-history"],
        default_index=0,
        orientation="horizontal",
    )

    if submenu == "Dashboard Histórico":
        pagina_dashboard_historico()

    elif submenu == "Status dos Agendamentos":
        pagina_dashboard_status()

elif pagina_principal == "Administração de Sistema":
    submenu = option_menu(
        menu_title=None,
        options=["Administração de Fluxos", "Administração de Agendamentos"],
        icons=["tools", "calendar-check"],
        default_index=0,
        orientation="horizontal",
    )

    if submenu == "Administração de Fluxos":
        pagina_admin_fluxos()

    elif submenu == "Administração de Agendamentos":
        pagina_admin_agendamentos()
