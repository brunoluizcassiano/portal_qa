import streamlit as st
def pagina_home():
    st.set_page_config(page_title="CIQ - PLARD", layout="wide")
    st.title("🏡 Bem-vindo a Central de inovação em Qualidade de Software - PLARD")
    st.markdown("""
    <p style='font-size:18px;'>
        A <b>Central de inovação em Qualidade de Software</b> é uma plataforma inteligente para <b>gerar, gerenciar e monitorar</b> massas de dados para testes, desenvolvimento e automação.
        <br>
        A plataforma disponibiliza *KPIs (Indicadores-chave de Desempenho) de Qualidade* essenciais para sua tribo ou equipe. Esses KPIs fornecem uma visão clara e objetiva sobre a qualidade dos processos de software.
        <br>
    </p>
    """, unsafe_allow_html=True)
    st.divider()
    st.subheader("⚙️ Geração de Massa")
    
    st.markdown("""
        - Escolha fluxos de dados já configurados.
        - Gere rapidamente massas para testes.
        - Integre com APIs, Mensagerias (Kafka) e mais.
        """)
    st.divider()
    st.subheader("📊 Dashboards")
    st.markdown("""
    - **Identificação de gargalos e oportunidades de melhoria** no ciclo de desenvolvimento
    - **Acompanhamento contínuo do progresso e da evolução** dos projetos
    - **Tomada de decisão mais assertiva**, baseada em dados reais e confiáveis
    - **Promoção da colaboração entre times**, aumentando a transparência e a eficiência
    Os KPIs são fundamentais para **integrar qualidade e performance** ao processo de desenvolvimento, facilitando a comunicação entre áreas e impulsionando a entrega de soluções cada vez melhores.
    """)
    st.divider()
    st.success("Tudo foi pensado para ser rápido, flexível e controlado de forma fácil, visual e segura. Pronto para transformar sua gestão de dados de testes? 🚀🚀🚀")
