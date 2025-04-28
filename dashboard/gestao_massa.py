import streamlit as st
import yaml
import os

MASSAS_FILE = 'config/massai_massa_gerada.yaml'

def carregar_massas():
    if os.path.exists(MASSAS_FILE):
        with open(MASSAS_FILE, 'r') as f:
            return yaml.safe_load(f) or []
    return []

def salvar_massas(massas):
    with open(MASSAS_FILE, 'w') as f:
        yaml.dump(massas, f, allow_unicode=True)

def pagina_gestao_massa():
    st.title("📦 Gestão de Massas Geradas - MassAI")

    massas = carregar_massas()

    if not massas:
        st.warning("Nenhuma massa gerada ainda!")
        return

    # Exibe todas as massas
    for idx, massa in enumerate(massas):
        with st.expander(f"🧩 Massa {idx + 1} - Fluxo: {massa.get('fluxo_name', 'Desconhecido')}"):
            st.json(massa.get("dados", {}))

            # Se já tiver status, usa, senão assume 'valida' como padrão
            status_atual = massa.get("status", "valida")

            novo_status = st.selectbox(
                "🔖 Status da Massa:",
                ["valida", "invalida", "ja_utilizada"],
                index=["valida", "invalida", "ja_utilizada"].index(status_atual),
                key=f"status_{idx}"
            )

            if novo_status != status_atual:
                massa["status"] = novo_status
                salvar_massas(massas)
                st.success(f"Status da Massa {idx + 1} atualizado para: **{novo_status}**")
