import streamlit as st
import yaml
import datetime
import os

AGENDAMENTOS_FILE = 'config/massai_agendamentos.yaml'
HISTORICO_EXECUCOES_FILE = 'config/massai_historico_execucoes.yaml'

def carregar_agendamentos():
    if os.path.exists(AGENDAMENTOS_FILE):
        with open(AGENDAMENTOS_FILE, 'r') as f:
            return yaml.safe_load(f) or []
    return []

def carregar_historico_execucoes():
    if os.path.exists(HISTORICO_EXECUCOES_FILE):
        with open(HISTORICO_EXECUCOES_FILE, 'r') as f:
            return yaml.safe_load(f) or []
    return []

def traduzir_dia(dia_ingles):
    dias = {
        "Monday": "Segunda",
        "Tuesday": "Terça",
        "Wednesday": "Quarta",
        "Thursday": "Quinta",
        "Friday": "Sexta",
        "Saturday": "Sábado",
        "Sunday": "Domingo"
    }
    return dias.get(dia_ingles, dia_ingles)

def pagina_dashboard_status():
    st.title("📅 Status de Agendamentos - MassAI")

    agendamentos = carregar_agendamentos()
    historico = carregar_historico_execucoes()

    now = datetime.datetime.now()
    horario_atual = now.strftime("%H:%M")
    dia_semana = traduzir_dia(now.strftime("%A"))

    if not agendamentos:
        st.warning("Nenhum agendamento configurado.")
        return

    st.subheader("✅ Agendamentos do Dia")
    for agendamento in agendamentos:
        fluxo = agendamento.get('fluxo_name')
        horario = agendamento.get('horario')
        dias_semana = agendamento.get('dias_semana', ["Todos"])

        if "Todos" not in dias_semana and dia_semana not in dias_semana:
            continue

        st.info(f"📝 **Fluxo:** {fluxo} | 🕑 **Horário Agendado:** {horario}")

    st.divider()

    st.subheader("📈 Histórico de Execuções")
    if not historico:
        st.info("Nenhuma execução realizada ainda.")
        return

    historico_hoje = [h for h in historico if h["data"] == now.strftime("%d/%m/%Y")]

    if not historico_hoje:
        st.info("Nenhuma execução para hoje ainda.")
        return

    for execucao in historico_hoje:
        status_emoji = "🟢" if execucao["status"] == "Sucesso" else "🔴"
        st.markdown(f"""
        **Fluxo:** {execucao['fluxo_name']}  
        **Horário Executado:** {execucao['horario']}  
        **Status:** {status_emoji} {execucao['status']}
        ---
        """)

    if st.button("🔄 Atualizar Página"):
        st.rerun()
