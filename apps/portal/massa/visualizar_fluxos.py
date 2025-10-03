import streamlit as st
import yaml
import random

def pagina_visualizar_fluxos():
    st.title("🔎 Visualizador de Fluxo E2E - MassAI")

    # Carregar os fluxos
    with open('config/fluxos.yaml') as f:
        fluxos = yaml.safe_load(f)

    fluxo_escolhido = st.selectbox("Escolha o fluxo para visualizar:", list(fluxos.keys()), key="fluxo_simples")

    if fluxo_escolhido:
        etapas = fluxos.get(fluxo_escolhido, [])
        
        st.subheader(f"Fluxo: {fluxo_escolhido}")
        
        if not etapas:
            st.warning("Nenhuma etapa encontrada para esse fluxo.")
            return

        fluxo_diagrama = "digraph FluxoE2E {\n"
        ultimo_no = None
        
        for etapa in etapas:
            api_name = etapa.get("api_name", "desconhecido")
            status = random.choice(["executado", "nao_executado"])
            
            cor = "green" if status == "executado" else "red"
            
            fluxo_diagrama += f'"{api_name}" [style=filled, fillcolor={cor}];\n'
            
            if ultimo_no:
                fluxo_diagrama += f'"{ultimo_no}" -> "{api_name}";\n'
            
            ultimo_no = api_name
        
        fluxo_diagrama += "}"
        
        st.graphviz_chart(fluxo_diagrama)
