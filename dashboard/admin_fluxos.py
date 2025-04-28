import streamlit as st
import yaml
import os

FLUXOS_FILE = 'config/fluxos.yaml'

def carregar_fluxos():
    if os.path.exists(FLUXOS_FILE):
        with open(FLUXOS_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    else:
        return {}

def salvar_fluxos(fluxos):
    with open(FLUXOS_FILE, 'w') as f:
        yaml.dump(fluxos, f, allow_unicode=True)

def pagina_admin_fluxos():
    st.title("⚙️ Administração de Fluxos - MassAI")

    fluxos = carregar_fluxos()

    # ---------------------- Listagem de fluxos ----------------------
    st.subheader("📋 Fluxos Existentes")
    if not fluxos:
        st.warning("Nenhum fluxo encontrado.")
    else:
        for fluxo_nome, etapas in fluxos.items():
            with st.expander(f"📄 Fluxo: {fluxo_nome}"):
                for idx, etapa in enumerate(etapas):
                    col1, col2, col3 = st.columns([0.7, 0.15, 0.15])

                    with col1:
                        st.markdown(f"**{idx+1}. Tipo:** `{etapa.get('tipo', '-')}` | **Nome:** `{etapa.get('nome', '-')}`")

                    with col2:
                        if st.button("✏️ Editar", key=f"editar_{fluxo_nome}_{idx}"):
                            st.session_state["fluxo_edicao"] = fluxo_nome
                            st.session_state["etapa_edicao_idx"] = idx
                            st.rerun()

                    with col3:
                        if st.button("🗑️ Excluir", key=f"excluir_{fluxo_nome}_{idx}"):
                            fluxos[fluxo_nome].pop(idx)
                            salvar_fluxos(fluxos)
                            st.success(f"Etapa {idx+1} excluída com sucesso do fluxo '{fluxo_nome}'!")
                            st.rerun()

                if st.button(f"➕ Adicionar Etapa ao Fluxo '{fluxo_nome}'", key=f"add_etapa_{fluxo_nome}"):
                    st.session_state["fluxo_para_adicionar_etapa"] = fluxo_nome
                    st.rerun()

    st.divider()

    # ---------------------- Criar novo fluxo ----------------------
    st.subheader("➕ Criar Novo Fluxo")

    novo_fluxo_nome = st.text_input("Nome do Novo Fluxo", key="novo_fluxo_nome")

    if st.button("Criar Fluxo", key="botao_criar_fluxo"):
        if novo_fluxo_nome:
            if novo_fluxo_nome not in fluxos:
                fluxos[novo_fluxo_nome] = []
                salvar_fluxos(fluxos)
                st.success(f"Fluxo '{novo_fluxo_nome}' criado com sucesso!")
                st.session_state["fluxo_para_adicionar_etapa"] = novo_fluxo_nome
                st.rerun()
            else:
                st.error("Já existe um fluxo com esse nome.")
        else:
            st.error("Por favor, informe um nome válido para o fluxo.")

    # ---------------------- Cadastro de nova etapa ----------------------
    fluxo_para_adicionar = st.session_state.get("fluxo_para_adicionar_etapa")
    if fluxo_para_adicionar:
        st.divider()
        st.subheader(f"🛠️ Adicionar Etapa ao Fluxo: {fluxo_para_adicionar}")

        tipo_etapa = st.selectbox("Tipo de Ação", ["api", "kafka"], key="tipo_etapa")

        nome_etapa = st.text_input("Nome da Etapa", key="nome_etapa")

        if tipo_etapa == "api":
            metodo = st.selectbox("Método HTTP", ["GET", "POST", "PUT", "DELETE"], key="metodo_http")
            url = st.text_input("URL da API", key="url_api")
            payload = st.text_area("Payload (YAML opcional)", key="payload_api")
        else:
            topico_envio = st.text_input("Tópico de Envio Kafka", key="topico_envio")
            topico_resposta = st.text_input("Tópico de Resposta Kafka (opcional)", key="topico_resposta")
            mensagem = st.text_area("Mensagem (YAML opcional)", key="mensagem_kafka")

        if st.button("Salvar Etapa", key="botao_salvar_etapa"):
            try:
                nova_etapa = {
                    "tipo": tipo_etapa,
                    "nome": nome_etapa
                }

                if tipo_etapa == "api":
                    try:
                        payload_json = yaml.safe_load(payload) if payload else {}
                    except Exception as e:
                        st.error(f"Payload inválido! Corrija o YAML.\n\nErro: {e}")
                        st.stop()

                    nova_etapa.update({
                        "metodo": metodo,
                        "url": url,
                        "payload": payload_json,
                    })
                else:
                    try:
                        mensagem_json = yaml.safe_load(mensagem) if mensagem else {}
                    except Exception as e:
                        st.error(f"Mensagem inválida! Corrija o YAML.\n\nErro: {e}")
                        st.stop()

                    nova_etapa.update({
                        "topico_envio": topico_envio,
                        "mensagem": mensagem_json,
                    })
                    if topico_resposta:
                        nova_etapa["topico_resposta"] = topico_resposta

                fluxos = carregar_fluxos()
                fluxos[fluxo_para_adicionar].append(nova_etapa)
                salvar_fluxos(fluxos)

                st.success("Etapa adicionada com sucesso!")
                del st.session_state["fluxo_para_adicionar_etapa"]
                st.rerun()

            except Exception as e:
                st.error(f"Erro ao salvar etapa: {e}")

    # ---------------------- Edição de etapa existente ----------------------
    fluxo_edicao = st.session_state.get("fluxo_edicao")
    etapa_edicao_idx = st.session_state.get("etapa_edicao_idx")

    if fluxo_edicao is not None and etapa_edicao_idx is not None:
        st.divider()
        st.subheader(f"📝 Editar Etapa no Fluxo: {fluxo_edicao}")

        fluxos = carregar_fluxos()
        etapa = fluxos[fluxo_edicao][etapa_edicao_idx]

        tipo_etapa = etapa.get("tipo", "api")  # Tipo não pode ser alterado aqui
        nome_etapa = st.text_input("Nome da Etapa", value=etapa.get("nome", ""), key="editar_nome")

        if tipo_etapa == "api":
            metodo = st.selectbox("Método HTTP", ["GET", "POST", "PUT", "DELETE"], index=["GET", "POST", "PUT", "DELETE"].index(etapa.get("metodo", "GET")), key="editar_metodo")
            url = st.text_input("URL da API", value=etapa.get("url", ""), key="editar_url")
            payload = st.text_area("Payload (YAML opcional)", value=yaml.dump(etapa.get("payload", {})), key="editar_payload")
        else:
            topico_envio = st.text_input("Tópico de Envio Kafka", value=etapa.get("topico_envio", ""), key="editar_topico_envio")
            topico_resposta = st.text_input("Tópico de Resposta Kafka (opcional)", value=etapa.get("topico_resposta", ""), key="editar_topico_resposta")
            mensagem = st.text_area("Mensagem (YAML opcional)", value=yaml.dump(etapa.get("mensagem", {})), key="editar_mensagem")

        if st.button("Salvar Alterações", key="botao_salvar_edicao"):
            etapa_editada = {
                "tipo": tipo_etapa,
                "nome": nome_etapa
            }

            try:
                if tipo_etapa == "api":
                    etapa_editada.update({
                        "metodo": metodo,
                        "url": url,
                        "payload": yaml.safe_load(payload) if payload else {},
                    })
                else:
                    etapa_editada.update({
                        "topico_envio": topico_envio,
                        "mensagem": yaml.safe_load(mensagem) if mensagem else {},
                    })
                    if topico_resposta:
                        etapa_editada["topico_resposta"] = topico_resposta

                fluxos[fluxo_edicao][etapa_edicao_idx] = etapa_editada
                salvar_fluxos(fluxos)

                st.success("Etapa editada com sucesso!")
                del st.session_state["fluxo_edicao"]
                del st.session_state["etapa_edicao_idx"]
                st.rerun()

            except Exception as e:
                st.error(f"Erro ao salvar edição: {e}")
