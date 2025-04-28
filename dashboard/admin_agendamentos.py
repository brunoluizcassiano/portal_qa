import streamlit as st
import yaml
import os

AGENDAMENTOS_FILE = 'config/massai_agendamentos.yaml'
FLUXOS_FILE = 'config/fluxos.yaml'

def carregar_agendamentos():
    if os.path.exists(AGENDAMENTOS_FILE):
        with open(AGENDAMENTOS_FILE, 'r') as f:
            return yaml.safe_load(f) or []
    else:
        return []

def salvar_agendamentos(agendamentos):
    with open(AGENDAMENTOS_FILE, 'w') as f:
        yaml.dump(agendamentos, f, allow_unicode=True)

def pagina_admin_agendamentos():
    st.title("🗓️ Administração de Agendamentos - MassAI")

    agendamentos = carregar_agendamentos()

    st.subheader("📋 Agendamentos Existentes")
    if not agendamentos:
        st.warning("Nenhum agendamento encontrado.")
    else:
        for idx, agendamento in enumerate(agendamentos):
            with st.expander(f"Agendamento {idx+1}: {agendamento['fluxo_name']}"):
                st.markdown(f"➡️ Fluxo: `{agendamento['fluxo_name']}`")
                st.markdown(f"➡️ Quantidade: `{agendamento['quantidade']}`")
                st.markdown(f"➡️ Horário: `{agendamento['horario']}`")
                st.markdown(f"➡️ Dias da Semana: `{', '.join(agendamento['dias_semana'])}`")

                if st.button(f"❌ Excluir Agendamento {idx+1}"):
                    agendamentos.pop(idx)
                    salvar_agendamentos(agendamentos)
                    st.success("Agendamento excluído com sucesso!")
                    st.rerun()

    st.divider()

    st.subheader("➕ Criar Novo Agendamento")

    # Carregar fluxos disponíveis do YAML
    if os.path.exists(FLUXOS_FILE):
        with open(FLUXOS_FILE, 'r') as f:
            fluxos_cadastrados = yaml.safe_load(f) or {}
        fluxos_disponiveis = list(fluxos_cadastrados.keys())
    else:
        fluxos_disponiveis = []

    if not fluxos_disponiveis:
        st.error("Nenhum fluxo cadastrado. Crie fluxos primeiro na Administração de Fluxos!")
        return

    fluxo_selecionado = st.selectbox("Nome do Fluxo", fluxos_disponiveis)

    quantidade = st.number_input("Quantidade de Massas", min_value=1, step=1)

    horario = st.text_input("Horário (HH:MM)")

    dias_opcoes = ["Todos", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    dias_semana = st.multiselect("Dias da Semana", dias_opcoes, default=["Todos"])

    if st.button("Salvar Novo Agendamento"):
        novo_agendamento = {
            "fluxo_name": fluxo_selecionado,
            "quantidade": quantidade,
            "horario": horario,
            "dias_semana": dias_semana
        }
        agendamentos.append(novo_agendamento)
        salvar_agendamentos(agendamentos)
        st.success("Novo agendamento salvo com sucesso!")
        st.rerun()
