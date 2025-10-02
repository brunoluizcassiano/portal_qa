import streamlit as st
def pagina_home_massa():
    st.title("🏡 Bem-vindo - Geração Inteligente de Massas de Dados")
    st.markdown("""
    <p style='font-size:18px;'>
        O <b>MassAI</b> é uma plataforma inteligente para <b>gerar, gerenciar e monitorar</b> massas de dados para testes, desenvolvimento e automação.
        <br><br>
        Tudo foi pensado para ser rápido, flexível e controlado de forma fácil, visual e segura.
    </p>
    """, unsafe_allow_html=True)
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.header("⚙️ Geração de Massa")
        st.markdown("""
        - Escolha fluxos de dados já configurados.
        - Gere rapidamente massas para testes.
        - Integre com APIs, Mensagerias (Kafka) e mais.
        """)
    with col2:
        st.header("📊 Dashboards")
        st.markdown("""
        - Acompanhe o histórico de execuções.
        - Veja status de agendamentos em tempo real.
        - Analise sucesso e falhas automaticamente.
        """)
    st.divider()
    st.subheader("🚀 Como Funciona?")
    st.markdown("""
    1. **Configure seus fluxos**: Crie sequências de chamadas (APIs, Kafka, etc.).
    2. **Gere massas sob demanda**: Execute fluxos sempre que quiser.
    3. **Agende execuções automáticas**: Defina dias e horários para execuções recorrentes.
    4. **Monitore e gerencie**: Veja resultados, taxas de sucesso e histórico.
    Tudo isso sem precisar alterar código manualmente! 💻✨
    """)
    st.divider()
    st.success("Pronto para transformar sua gestão de dados de testes? Vá até o menu lateral e explore o MassAI 🚀")
