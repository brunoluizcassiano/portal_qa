import streamlit as st
import pandas as pd
import json
import os
import matplotlib.pyplot as plt

HISTORICO_FILE = 'config/massai_historico.json'

def carregar_historico():
    if os.path.exists(HISTORICO_FILE):
        with open(HISTORICO_FILE, 'r') as f:
            return json.load(f)
    else:
        return []

def pagina_dashboard_analytical():
    st.title("📊 Dashboard de Histórico - MassAI")

    historico = carregar_historico()

    if not historico:
        st.warning("Nenhum histórico encontrado ainda. Execute alguns fluxos primeiro!")
        return

    df = pd.DataFrame(historico)

        # Converter coluna de data para datetime
    df["data_hora_dt"] = pd.to_datetime(df["data_hora"], format="%d/%m/%Y %H:%M:%S")

    # Filtro por data
    st.subheader("📅 Filtro por Período")

    col1, col2 = st.columns(2)

    with col1:
        data_inicio = st.date_input("Data Início", value=df["data_hora_dt"].min().date())

    with col2:
        data_fim = st.date_input("Data Fim", value=df["data_hora_dt"].max().date())

    # Aplicar filtro
    df = df[(df["data_hora_dt"].dt.date >= data_inicio) & (df["data_hora_dt"].dt.date <= data_fim)]


    df["percentual_sucesso"] = df["percentual_sucesso"].str.replace("%", "").astype(float)

    # 🌟 COLORIR A TABELA AQUI DENTRO DA FUNÇÃO!
    with st.expander("📋 Ver Tabela Completa"):
        def highlight_status(s):
            if s == 'PASSOU':
                return 'background-color: #d4edda; color: #155724;'  # verde claro
            elif s == 'FALHOU':
                return 'background-color: #f8d7da; color: #721c24;'  # vermelho claro
            else:
                return ''

        styled_df = df.style.applymap(highlight_status, subset=["zephyr_status"])
        st.dataframe(styled_df, use_container_width=True)

    # 📈 Plotar gráfico de evolução da taxa de sucesso
    st.subheader("📈 Evolução da Taxa de Sucesso (%)")
    fig, ax = plt.subplots()
    ax.plot(df["data_hora"], df["percentual_sucesso"], marker='o')
    ax.set_xlabel("Data/Hora")
    ax.set_ylabel("Taxa de Sucesso (%)")
    ax.set_title("Evolução das Execuções E2E")
    plt.xticks(rotation=45)
    st.pyplot(fig)

    # 📊 Plotar gráfico de distribuição Passaram vs Falharam
    st.subheader("📊 Distribuição de Status dos Testes")

    status_counts = df["zephyr_status"].value_counts()

    fig2, ax2 = plt.subplots()
    ax2.bar(status_counts.index, status_counts.values, color=['#28a745', '#dc3545'])
    ax2.set_xlabel("Status do Teste")
    ax2.set_ylabel("Quantidade")
    ax2.set_title("Distribuição de Testes PASSOU vs FALHOU")
    st.pyplot(fig2)
