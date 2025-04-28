import streamlit as st
import streamlit.components.v1 as components
import yaml
import random
import datetime
import json
import os
import time

HISTORICO_FILE = 'config/massai_historico.json'

def carregar_historico():
    if os.path.exists(HISTORICO_FILE):
        with open(HISTORICO_FILE, 'r') as f:
            return json.load(f)
    else:
        return []

def salvar_historico(historico):
    with open(HISTORICO_FILE, 'w') as f:
        json.dump(historico, f, indent=4)

def pagina_fluxo_bonito():
    st.title("🌟 Visualizador Bonito de Fluxo E2E - MassAI")

    verbose_mode = st.checkbox("🔍 Exibir detalhes da execução (modo verbose)")
    exportar_log = st.checkbox("💾 Exportar log após execução")

    # Carregar histórico do arquivo
    if "historico_fluxos" not in st.session_state:
        st.session_state["historico_fluxos"] = carregar_historico()

    # Carregar fluxos
    with open('config/fluxos.yaml') as f:
        fluxos = yaml.safe_load(f)

    fluxo_escolhido = st.selectbox("Escolha o fluxo:", list(fluxos.keys()), key="fluxo_bonito")

    if fluxo_escolhido:
        etapas = fluxos.get(fluxo_escolhido, [])

        if not etapas:
            st.warning("Nenhuma etapa encontrada.")
            return

        mermaid_code = "flowchart TD\n"
        ultimo_no = None
        total_etapas = len(etapas)
        etapas_sucesso = 0

        # Iniciar log
        log_execucao = []

        for etapa in etapas:
            api_name = etapa.get("api_name", "desconhecido")

            if verbose_mode:
                with st.expander(f"➡️ Etapa: {api_name}", expanded=True):
                    inicio_etapa = time.time()
                    st.write(f"▶️ Iniciando execução da etapa: **{api_name}**")

                    # Simular execução (70% de chance de sucesso)
                    status = "executado" if random.random() < 0.7 else "nao_executado"
                    resposta_simulada = {
                        "status_code": 200 if status == "executado" else 400,
                        "mensagem": f"{api_name} {'executado' if status == 'executado' else 'com erro'}!"
                    }

                    st.code(resposta_simulada, language="json")

                    fim_etapa = time.time()
                    tempo_execucao = fim_etapa - inicio_etapa

                    if status == "executado":
                        st.success(f"✅ Etapa concluída com sucesso em {tempo_execucao:.2f} segundos.")
                        etapas_sucesso += 1
                    else:
                        st.error(f"❌ Etapa falhou em {tempo_execucao:.2f} segundos.")

                    # Registrar log
                    log_execucao.append(f"Etapa: {api_name}\nStatus: {status}\nTempo: {tempo_execucao:.2f} segundos\nResposta: {resposta_simulada}\n---")

            else:
                # Executa sem verbose
                status = "executado" if random.random() < 0.7 else "nao_executado"
                if status == "executado":
                    etapas_sucesso += 1

            if status == "executado":
                mermaid_code += f'{api_name}(["✅ {api_name}"]):::executado\n'
            else:
                mermaid_code += f'{api_name}(["❌ {api_name}"]):::erro\n'

            if ultimo_no:
                mermaid_code += f"{ultimo_no} --> {api_name}\n"

            ultimo_no = api_name

        percentual_sucesso = (etapas_sucesso / total_etapas) * 100

        # Mostrar gráfico bonito usando Mermaid.js
        components.html(f'''
        <div class="mermaid">
        {mermaid_code}
        </div>
        <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
        <script>
            mermaid.initialize({{
                startOnLoad:true,
                theme: "base",
                themeVariables: {{
                    'primaryColor': '#e0f7fa',
                    'edgeLabelBackground':'#ffffff',
                    'nodeTextColor': '#333333',
                    'mainBkg': '#ffffff',
                    'nodeBorder': '#90caf9'
                }}
            }});
        </script>
        ''', height=600)

        st.success(f"✅ Taxa de sucesso: **{percentual_sucesso:.2f}%** das etapas!")

        # Guardar no histórico
        registro = {
            "fluxo": fluxo_escolhido,
            "data_hora": datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "percentual_sucesso": f"{percentual_sucesso:.2f}%",
            "zephyr_test_case_id": f"TEST-{random.randint(1000,9999)}",
            "zephyr_status": random.choices(["PASSOU", "FALHOU"], weights=[80, 20], k=1)[0]
        }

        st.session_state["historico_fluxos"].append(registro)
        salvar_historico(st.session_state["historico_fluxos"])

        # Exibir histórico recente
        with st.expander("Histórico de Execuções"):
            for item in reversed(st.session_state["historico_fluxos"][-5:]):
                st.write(f"🕒 {item['data_hora']} | Fluxo: {item['fluxo']} | Sucesso: {item['percentual_sucesso']}")

        # 💾 Exportar LOG
        if exportar_log and log_execucao:
            log_content = "\n".join(log_execucao)
            st.download_button(
                label="📥 Baixar log da execução",
                data=log_content,
                file_name=f"massai_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain"
            )
