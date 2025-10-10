# -*- coding: utf-8 -*-
import os
import yaml
import streamlit as st
from copy import deepcopy

FLUXOS_FILE = "config/fluxos.yaml"
SETTINGS_FILE = "config/settings.yaml"

# =============================================================
# Utils
# =============================================================

def _safe_load_yaml(text: str, default):
    if not text or not str(text).strip():
        return deepcopy(default)
    try:
        data = yaml.safe_load(text)
        return deepcopy(data if data is not None else default)
    except Exception as e:
        st.error(f"YAML inválido. Corrija o conteúdo.\n\n{e}")
        st.stop()

def _safe_dump_yaml(data) -> str:
    try:
        return yaml.dump(data or {}, allow_unicode=True, sort_keys=False)
    except Exception:
        return ""

def _ensure_dict(d):
    return d if isinstance(d, dict) else {}

def _ensure_list(x):
    return x if isinstance(x, list) else []

def carregar_fluxos():
    if os.path.exists(FLUXOS_FILE):
        with open(FLUXOS_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def salvar_fluxos(fluxos: dict):
    os.makedirs(os.path.dirname(FLUXOS_FILE), exist_ok=True)
    with open(FLUXOS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(fluxos, f, allow_unicode=True, sort_keys=False)

def carregar_ambientes():
    ambientes = ["DEV", "UAT", "PROD"]
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            envs = cfg.get("environments")
            if isinstance(envs, list) and envs:
                ambientes = [str(e) for e in envs]
        except Exception:
            pass
    return ambientes


# =============================================================
# Autorização
# =============================================================

def _render_auth_fields(prefix: str, auth_cfg: dict, ambientes: list):
    tipo = st.selectbox(
        "Authorization",
        options=["none", "bearer", "basic"],
        index=["none", "bearer", "basic"].index(str(auth_cfg.get("type", "none")).lower()),
        key=f"{prefix}_auth_type"
    )
    per_env_default = bool(auth_cfg.get("per_env", False))
    per_env = st.checkbox("Parametrizar por ambiente", value=per_env_default, key=f"{prefix}_auth_per_env")

    bearer_map = _ensure_dict(auth_cfg.get("bearer", {}))
    basic_map = _ensure_dict(auth_cfg.get("basic", {}))

    if tipo == "bearer":
        if per_env:
            tabs = st.tabs(ambientes)
            for i, env in enumerate(ambientes):
                with tabs[i]:
                    val = bearer_map.get(env, "")
                    bearer_map[env] = st.text_input(f"Bearer Token ({env})", value=val, key=f"{prefix}_bearer_{env}")
        else:
            val = bearer_map.get("DEFAULT", "")
            bearer_map["DEFAULT"] = st.text_input("Bearer Token (todos os ambientes)", value=val, key=f"{prefix}_bearer_default")
        basic_map = {}
    elif tipo == "basic":
        if per_env:
            tabs = st.tabs(ambientes)
            for i, env in enumerate(ambientes):
                with tabs[i]:
                    env_cfg = _ensure_dict(basic_map.get(env, {}))
                    user = st.text_input(f"Usuário ({env})", value=env_cfg.get("user", ""), key=f"{prefix}_basic_user_{env}")
                    pwd = st.text_input(f"Senha/Token ({env})", value=env_cfg.get("password", ""), type="password", key=f"{prefix}_basic_pwd_{env}")
                    basic_map[env] = {"user": user, "password": pwd}
        else:
            env_cfg = _ensure_dict(basic_map.get("DEFAULT", {}))
            user = st.text_input("Usuário (todos os ambientes)", value=env_cfg.get("user", ""), key=f"{prefix}_basic_user_default")
            pwd = st.text_input("Senha/Token (todos os ambientes)", value=env_cfg.get("password", ""), type="password", key=f"{prefix}_basic_pwd_default")
            basic_map["DEFAULT"] = {"user": user, "password": pwd}
        bearer_map = {}
    else:
        bearer_map, basic_map = {}, {}

    return tipo, per_env, bearer_map, basic_map


# =============================================================
# Painéis: Variáveis & Pré-request
# =============================================================

def _render_variaveis_panel(key_prefix: str, variaveis_iniciais):
    st.markdown("### 🔁 Variáveis Reutilizáveis")
    st.caption("Mapeie campos do response para variáveis. Depois, use-as em URL, params, headers e payload com {{nome}}.")
    list_key = f"{key_prefix}_vars_list"
    if list_key not in st.session_state:
        st.session_state[list_key] = deepcopy(_ensure_list(variaveis_iniciais) or [])
    items = st.session_state[list_key]

    for i in range(len(items)):
        cols = st.columns([0.4, 0.5, 0.1])
        with cols[0]:
            nome = st.text_input(f"Nome da variável #{i+1}", value=items[i].get("nome",""), key=f"{key_prefix}_var_nome_{i}")
        with cols[1]:
            origem = st.text_input(f"Origem (ex: client.nome, data[0].id)", value=items[i].get("origem",""), key=f"{key_prefix}_var_origem_{i}")
        with cols[2]:
            if st.button("🗑️", key=f"{key_prefix}_var_del_{i}"):
                items.pop(i); st.rerun()
        items[i] = {"nome": nome.strip(), "origem": origem.strip()}

    if st.button("➕ Adicionar variável", key=f"{key_prefix}_add_var"):
        items.append({"nome":"", "origem":""}); st.rerun()

    return deepcopy(items)

def _render_prereq_panel(key_prefix: str, iniciais):
    st.markdown("### ⚡ Pré-request (variáveis geradas antes da chamada)")
    st.caption("Crie variáveis dinâmicas antes da requisição. Ex: digits(11), uuid4(), randint(1000,9999), now(\"%Y%m%d\"), seq(\"doc\",start=1,step=1,pad=11)")
    list_key = f"{key_prefix}_prereq_list"
    if list_key not in st.session_state:
        st.session_state[list_key] = deepcopy(_ensure_list(iniciais) or [])
    items = st.session_state[list_key]

    for i in range(len(items)):
        c = st.columns([0.4, 0.5, 0.1])
        with c[0]:
            nome = st.text_input(f"Nome #{i+1}", value=items[i].get("nome",""), key=f"{key_prefix}_prename_{i}")
        with c[1]:
            expr = st.text_input("Expressão", value=items[i].get("expr",""), key=f"{key_prefix}_preexpr_{i}")
        with c[2]:
            if st.button("🗑️", key=f"{key_prefix}_predel_{i}"):
                items.pop(i); st.rerun()
        items[i] = {"nome": nome.strip(), "expr": expr.strip()}

    if st.button("➕ Adicionar pré-request", key=f"{key_prefix}_preadd"):
        items.append({"nome":"","expr":""}); st.rerun()

    return deepcopy(items)


# =============================================================
# Merge helpers
# =============================================================

def _merge_step_api(
    tipo_etapa, nome_etapa, metodo, url_mode, url_value, urls_by_env,
    params_yaml, headers_yaml, body_mode, body_yaml, bodies_by_env,
    auth_tipo, auth_per_env, bearer_map, basic_map, variaveis, pre_vars
):
    etapa = {"tipo": tipo_etapa, "nome": nome_etapa, "metodo": metodo}

    if url_mode == "Única":
        etapa["url"] = (url_value or "").strip()
    else:
        etapa["url_por_ambiente"] = {env: (url or "").strip() for env, url in urls_by_env.items() if str(url).strip()}

    etapa["params"] = _safe_load_yaml(params_yaml, {})
    etapa["headers"] = {k: str(v) for k, v in _safe_load_yaml(headers_yaml, {}).items()}

    if body_mode == "Único":
        etapa["payload"] = _safe_load_yaml(body_yaml, {})
    else:
        etapa["payload_por_ambiente"] = {env: _safe_load_yaml(val, {}) for env, val in bodies_by_env.items()}

    etapa["auth"] = {"type": auth_tipo, "per_env": bool(auth_per_env)}
    if auth_tipo == "bearer":
        etapa["auth"]["bearer"] = deepcopy(bearer_map)
    elif auth_tipo == "basic":
        etapa["auth"]["basic"] = deepcopy(basic_map)

    etapa["variaveis"] = deepcopy(variaveis or [])
    if pre_vars:
        etapa["pre_request"] = {"vars": deepcopy(pre_vars)}

    # compat: remove "retorno" antigo, se existir
    etapa.pop("retorno", None)
    return etapa


def _read_step_defaults(etapa: dict, ambientes: list):
    metodo = etapa.get("metodo", "GET")
    if "url_por_ambiente" in etapa:
        url_mode = "Por Ambiente"
        url_value = ""
        urls_by_env = {env: etapa["url_por_ambiente"].get(env, "") for env in ambientes}
    else:
        url_mode = "Única"
        url_value = etapa.get("url", "")
        urls_by_env = {env: "" for env in ambientes}

    params_yaml = _safe_dump_yaml(_ensure_dict(etapa.get("params", {})))
    headers_yaml = _safe_dump_yaml(_ensure_dict(etapa.get("headers", {})))

    if "payload_por_ambiente" in etapa:
        body_mode = "Por Ambiente"
        body_yaml = ""
        bodies_by_env = {env: _safe_dump_yaml(etapa["payload_por_ambiente"].get(env, {})) for env in ambientes}
    else:
        body_mode = "Único"
        body_yaml = _safe_dump_yaml(_ensure_dict(etapa.get("payload", {})))
        bodies_by_env = {env: "" for env in ambientes}

    variaveis = _ensure_list(etapa.get("variaveis", []))
    prereq = _ensure_dict(etapa.get("pre_request", {})).get("vars", [])

    auth_cfg = _ensure_dict(etapa.get("auth", {}))
    auth_tipo = auth_cfg.get("type", "none")
    auth_per_env = bool(auth_cfg.get("per_env", False))
    bearer_map = _ensure_dict(auth_cfg.get("bearer", {}))
    basic_map = _ensure_dict(auth_cfg.get("basic", {}))

    return (metodo, url_mode, url_value, urls_by_env,
            params_yaml, headers_yaml, body_mode, body_yaml, bodies_by_env,
            auth_tipo, auth_per_env, bearer_map, basic_map,
            variaveis, prereq)


# =============================================================
# Página principal
# =============================================================

def pagina_admin_fluxos():
    st.title("⚙️ Administração de Fluxos - MassAI")

    ambientes = carregar_ambientes()
    fluxos = carregar_fluxos()

    # -------- Listagem --------
    st.subheader("📋 Fluxos Existentes")
    if not fluxos:
        st.warning("Nenhum fluxo encontrado.")
    else:
        for fluxo_nome, etapas in fluxos.items():
            with st.expander(f"📄 Fluxo: {fluxo_nome}", expanded=False):
                for idx, etapa in enumerate(_ensure_list(etapas)):
                    c1, c2, c3 = st.columns([0.7, 0.15, 0.15])
                    with c1:
                        url_label = etapa.get("url", "(url por ambiente)" if etapa.get("url_por_ambiente") else "-")
                        st.markdown(f"**{idx+1}.** `{etapa.get('tipo','-')}` | **{etapa.get('metodo','-')}** | `{etapa.get('nome','-')}` — {url_label}")
                    with c2:
                        if st.button("✏️ Editar", key=f"editar_{fluxo_nome}_{idx}"):
                            st.session_state["fluxo_edicao"] = fluxo_nome
                            st.session_state["etapa_edicao_idx"] = idx
                            st.rerun()
                    with c3:
                        if st.button("🗑️ Excluir", key=f"excluir_{fluxo_nome}_{idx}"):
                            fluxos[fluxo_nome].pop(idx)
                            salvar_fluxos(fluxos)
                            st.success(f"Etapa {idx+1} excluída de '{fluxo_nome}'.")
                            st.rerun()
                if st.button(f"➕ Adicionar Etapa a '{fluxo_nome}'", key=f"add_etapa_{fluxo_nome}"):
                    st.session_state["fluxo_para_adicionar_etapa"] = fluxo_nome
                    st.rerun()

    st.divider()

    # -------- Criar novo fluxo --------
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

    # -------- Adicionar etapa --------
    fluxo_para_adicionar = st.session_state.get("fluxo_para_adicionar_etapa")
    if fluxo_para_adicionar:
        st.divider()
        st.subheader(f"🛠️ Adicionar Etapa ao Fluxo: {fluxo_para_adicionar}")

        tipo_etapa = st.selectbox("Tipo de Ação", ["api", "kafka"], key="tipo_etapa")
        nome_etapa = st.text_input("Nome da Etapa", key="nome_etapa")

        if tipo_etapa == "api":
            st.caption("Dica: use {{variavel}} em URL, params, headers e payload.")
            metodo = st.selectbox("Método HTTP", ["GET", "POST", "PUT", "PATCH", "DELETE"], key="metodo_http")
            url_mode = st.radio("URL", ["Única", "Por Ambiente"], horizontal=True, key="url_mode")
            urls_by_env = {env: "" for env in ambientes}
            url_value = st.text_input("URL da API", key="url_api") if url_mode == "Única" else None
            if url_mode == "Por Ambiente":
                tabs = st.tabs(ambientes)
                for i, env in enumerate(ambientes):
                    with tabs[i]:
                        urls_by_env[env] = st.text_input(f"URL ({env})", key=f"url_api_{env}")

            params_yaml = st.text_area("Query Params (YAML)", height=100)
            headers_yaml = st.text_area("Headers (YAML)", height=120)
            body_mode = st.radio("Payload", ["Único", "Por Ambiente"], horizontal=True, key="body_mode")
            body_yaml, bodies_by_env = "", {env: "" for env in ambientes}
            if body_mode == "Único":
                body_yaml = st.text_area("Payload (YAML)", height=180)
            else:
                tabs = st.tabs(ambientes)
                for i, env in enumerate(ambientes):
                    with tabs[i]:
                        bodies_by_env[env] = st.text_area(f"Payload ({env})", height=180, key=f"payload_{env}")

            auth_tipo, auth_per_env, bearer_map, basic_map = _render_auth_fields("new", {}, ambientes)

            variaveis = _render_variaveis_panel("new", [])
            prereq_vars = _render_prereq_panel("new", [])

        else:
            topico_envio = st.text_input("Tópico Kafka")
            mensagem = st.text_area("Mensagem (YAML)", height=180)
            variaveis, prereq_vars = [], []

        if st.button("Salvar Etapa", key="botao_salvar_etapa"):
            try:
                if tipo_etapa == "api":
                    etapa = _merge_step_api(tipo_etapa, nome_etapa, metodo, url_mode, url_value, urls_by_env,
                                            params_yaml, headers_yaml, body_mode, body_yaml, bodies_by_env,
                                            auth_tipo, auth_per_env, bearer_map, basic_map,
                                            variaveis, prereq_vars)
                else:
                    etapa = {"tipo": "kafka", "nome": nome_etapa,
                             "topico_envio": topico_envio,
                             "mensagem": _safe_load_yaml(mensagem, {})}
                fluxos = carregar_fluxos()
                fluxos[fluxo_para_adicionar].append(etapa)
                salvar_fluxos(fluxos)
                st.success("Etapa salva com sucesso!")
                del st.session_state["fluxo_para_adicionar_etapa"]
                # limpa estado local dos painéis
                for k in list(st.session_state.keys()):
                    if k.endswith("_vars_list") or k.endswith("_prereq_list"):
                        st.session_state.pop(k, None)
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")

    # -------- Editar etapa --------
    fluxo_edicao = st.session_state.get("fluxo_edicao")
    etapa_edicao_idx = st.session_state.get("etapa_edicao_idx")
    if fluxo_edicao and etapa_edicao_idx is not None:
        st.divider()
        st.subheader(f"📝 Editar Etapa no Fluxo: {fluxo_edicao}")

        fluxos = carregar_fluxos()
        etapas = _ensure_list(fluxos.get(fluxo_edicao, []))
        if etapa_edicao_idx >= len(etapas):
            st.error("Índice inválido.")
            return

        etapa = etapas[etapa_edicao_idx]
        tipo_etapa = etapa.get("tipo", "api")
        nome_etapa = st.text_input("Nome da Etapa", value=etapa.get("nome", ""), key="editar_nome")

        if tipo_etapa == "api":
            (metodo, url_mode, url_value, urls_by_env,
             params_yaml, headers_yaml, body_mode, body_yaml, bodies_by_env,
             auth_tipo, auth_per_env, bearer_map, basic_map,
             variaveis_iniciais, prereq_iniciais) = _read_step_defaults(etapa, ambientes)

            st.caption("Dica: use {{variavel}} em URL, params, headers e payload.")
            metodo = st.selectbox("Método HTTP", ["GET", "POST", "PUT", "PATCH", "DELETE"],
                                  index=["GET","POST","PUT","PATCH","DELETE"].index(metodo), key="editar_metodo")

            url_mode = st.radio("URL", ["Única", "Por Ambiente"], horizontal=True,
                                index=(0 if url_mode=="Única" else 1), key="editar_url_mode")
            if url_mode == "Única":
                url_value = st.text_input("URL da API", value=url_value, key="editar_url")
            else:
                tabs = st.tabs(ambientes)
                for i, env in enumerate(ambientes):
                    with tabs[i]:
                        urls_by_env[env] = st.text_input(f"URL ({env})", value=urls_by_env.get(env, ""), key=f"editar_url_{env}")

            params_yaml = st.text_area("Query Params (YAML)", value=params_yaml, key="editar_params", height=100)
            headers_yaml = st.text_area("Headers (YAML)", value=headers_yaml, key="editar_headers", height=120)

            body_mode = st.radio("Payload", ["Único", "Por Ambiente"], horizontal=True,
                                 index=(0 if body_mode=="Único" else 1), key="editar_body_mode")
            if body_mode == "Único":
                body_yaml = st.text_area("Payload (YAML)", value=body_yaml, key="editar_payload", height=180)
            else:
                tabs = st.tabs(ambientes)
                for i, env in enumerate(ambientes):
                    with tabs[i]:
                        bodies_by_env[env] = st.text_area(f"Payload ({env})", value=bodies_by_env.get(env, ""), key=f"editar_payload_{env}", height=180)

            auth_tipo, auth_per_env, bearer_map, basic_map = _render_auth_fields(
                "edit",
                {"type": auth_tipo, "per_env": auth_per_env, "bearer": bearer_map, "basic": basic_map},
                ambientes
            )

            variaveis = _render_variaveis_panel("edit", variaveis_iniciais)
            prereq_vars = _render_prereq_panel("edit", prereq_iniciais)

        else:
            topico_envio = st.text_input("Tópico Kafka", value=etapa.get("topico_envio", ""))
            mensagem = st.text_area("Mensagem (YAML)", value=_safe_dump_yaml(etapa.get("mensagem", {})), height=180)
            variaveis, prereq_vars = [], []

        if st.button("Salvar Alterações", key="botao_salvar_edicao"):
            try:
                if tipo_etapa == "api":
                    etapa_editada = _merge_step_api(
                        tipo_etapa, nome_etapa, metodo, url_mode, url_value, urls_by_env,
                        params_yaml, headers_yaml, body_mode, body_yaml, bodies_by_env,
                        auth_tipo, auth_per_env, bearer_map, basic_map,
                        variaveis, prereq_vars
                    )
                else:
                    etapa_editada = {"tipo": "kafka", "nome": nome_etapa,
                                     "topico_envio": topico_envio,
                                     "mensagem": _safe_load_yaml(mensagem, {})}

                fluxos[fluxo_edicao][etapa_edicao_idx] = etapa_editada
                salvar_fluxos(fluxos)
                st.success("Etapa editada com sucesso!")
                del st.session_state["fluxo_edicao"]
                del st.session_state["etapa_edicao_idx"]
                # limpa estados locais
                for k in list(st.session_state.keys()):
                    if k.endswith("_vars_list") or k.endswith("_prereq_list"):
                        st.session_state.pop(k, None)
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao salvar edição: {e}")
