import streamlit as st
import requests
import yaml
import json
import os
import time
from streamlit_option_menu import option_menu

# === CONFIGURAÇÕES ===
MASSAS_FILE = 'config/massai_massa_gerada.yaml'
with open('config/settings.yaml') as f:
    settings = yaml.safe_load(f)
API_URL = settings.get('api_url', 'http://127.0.0.1:8000')

# =============================================================
# Utils
# =============================================================
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

# =============================================================
# Página principal
# =============================================================
def pagina_gerar_massas():
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