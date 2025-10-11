# -*- coding: utf-8 -*-
import os
import io
import re
import json
import time
import zipfile
import yaml
import pandas as pd
import requests
import streamlit as st

# arquivos de configuração / saída
FLUXOS_FILE = "config/fluxos.yaml"
MASSAS_FILE = "config/massai_massa_gerada.yaml"
SETTINGS_FILE = "config/settings.yaml"

# ----------------- settings -----------------

def _load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    return cfg

def _get_api_url():
    cfg = _load_settings()
    return cfg.get("api_url", "http://127.0.0.1:8000")

def _get_envs():
    cfg = _load_settings()
    envs = cfg.get("environments")
    if isinstance(envs, list) and envs:
        return [str(e).upper() for e in envs]
    return ["DEV", "UAT", "PROD"]

def _carregar_fluxos_yaml():
    try:
        with open(FLUXOS_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

def _carregar_fluxos():
    fx = _carregar_fluxos_yaml()
    return list(fx.keys()) if isinstance(fx, dict) else []

def salvar_massa_gerada_local(fluxo_name: str, dados):
    """Acrescenta um registro simples no arquivo de massas geradas."""
    try:
        if os.path.exists(MASSAS_FILE):
            with open(MASSAS_FILE, "r", encoding="utf-8") as f:
                massas = yaml.safe_load(f) or []
        else:
            massas = []
    except Exception:
        massas = []

    novo_registro = {
        "fluxo_name": fluxo_name,
        "status": "valida",
        "dados": dados,
        "data_criacao": time.strftime("%d/%m/%Y %H:%M:%S")
    }
    massas.append(novo_registro)
    try:
        os.makedirs(os.path.dirname(MASSAS_FILE), exist_ok=True)
        with open(MASSAS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(massas, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        st.warning(f"Não foi possível gravar arquivo de massas: {e}")

# ----------------- helpers para tabela -----------------

_SPLIT_RE = re.compile(r"[.\[\]]+")

def _get_value_from_path(data, path: str):
    """Extrai valor de um dicionário/lista usando caminho tipo 'a.b[0].c'."""
    try:
        if data is None or path is None:
            return None
        parts = [p for p in _SPLIT_RE.split(str(path).strip()) if p != ""]
        cur = data
        for p in parts:
            if isinstance(cur, list):
                idx = int(p)
                if idx < 0 or idx >= len(cur):
                    return None
                cur = cur[idx]
            elif isinstance(cur, dict):
                cur = cur.get(p)
            else:
                return None
        return cur
    except Exception:
        return None

def _coletar_variaveis_por_etapa(fluxos_yaml: dict, fluxo_nome: str):
    """
    Retorna dict: { step_nome: [ {nome, origem}, ... ] }
    """
    por_etapa = {}
    etapas = fluxos_yaml.get(fluxo_nome, [])
    for step in etapas:
        step_nome = (step.get("nome") or step.get("api_name") or "(sem-nome)").strip() or "(sem-nome)"
        variaveis = step.get("variaveis") or []
        validas = []
        for var in variaveis:
            n = (var.get("nome") or "").strip()
            o = (var.get("origem") or "").strip()
            if n and o:
                validas.append({"nome": n, "origem": o})
        if validas:
            por_etapa[step_nome] = validas
    return por_etapa

def _normalizar_execucoes(resultado):
    """
    Aceita:
      - lista de execuções: [ { <etapa>: {...}, "_context": {...} }, ... ]
      - dict com 'contexto': { status: "...", contexto: [ ... ] }
      - um único dict de execução: { <etapa>: {...}, "_context": {...} }
    Retorna sempre: (lista_de_execucoes, aviso_formato)
    """
    aviso = None
    if isinstance(resultado, list):
        return resultado, None
    if isinstance(resultado, dict):
        if "contexto" in resultado and isinstance(resultado["contexto"], list):
            return resultado["contexto"], None
        return [resultado], None
    aviso = "Formato de retorno inesperado para montar a tabela."
    return [], aviso

def _encontrar_bloco_da_etapa(exec_dict: dict, step_name: str):
    """1) exata; 2) strip; 3) se só tem uma chave, usa ela."""
    if step_name in exec_dict:
        return exec_dict[step_name]
    trimmed = step_name.strip()
    for k in exec_dict.keys():
        if str(k).strip() == trimmed:
            return exec_dict[k]
    if len(exec_dict) == 1:
        return next(iter(exec_dict.values()))
    return None

def _get_from_context(context: dict, origem: str):
    """
    Resolve valores do contexto para:
      - '{{var}}'
      - 'ctx:foo.bar' ou 'ctx.foo.bar'
    """
    s = (origem or "").strip()
    if not s:
        return None
    if s.startswith("{{") and s.endswith("}}"):
        key = s[2:-2].strip()
        return context.get(key)
    if s.lower().startswith("ctx:") or s.lower().startswith("ctx."):
        key = s[4:].lstrip(".:")
        parts = [p for p in _SPLIT_RE.split(key) if p]
        cur = context
        for p in parts:
            if isinstance(cur, dict):
                cur = cur.get(p)
            else:
                return None
        return cur
    return None

def _montar_df_por_etapa(exec_list: list, step_name: str, vars_def: list) -> pd.DataFrame:
    """
    Linha por execução; colunas = nomes das variáveis.
    """
    rows = []
    for item in exec_list:
        row = {}
        exec_dict = item if isinstance(item, dict) else {}
        bloco = _encontrar_bloco_da_etapa(exec_dict, step_name)
        resp = bloco.get("response") if isinstance(bloco, dict) else None
        context = exec_dict.get("_context", {}) if isinstance(exec_dict, dict) else {}

        for v in vars_def:
            nome = v["nome"]
            origem = v["origem"]
            if origem.startswith("{{") or origem.lower().startswith("ctx:") or origem.lower().startswith("ctx."):
                row[nome] = _get_from_context(context, origem)
            elif origem.startswith("="):
                row[nome] = origem[1:]
            else:
                row[nome] = _get_value_from_path(resp, origem)
        rows.append(row)
    return pd.DataFrame(rows)

def _gerar_excel_multiplas_abas(dfs_por_etapa: dict):
    """
    Tenta gerar XLSX com openpyxl; se indisponível, gera ZIP com CSVs.
    Retorna (bytes, mime, ext)
    """
    try:
        import openpyxl  # noqa: F401
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for step_name, df in dfs_por_etapa.items():
                sheet = (step_name or "Etapa")[:31] or "Etapa"
                base = sheet
                idx = 2
                while sheet in writer.sheets:
                    sheet = (base[:27] + f"_{idx}")[:31]
                    idx += 1
                df.to_excel(writer, index=False, sheet_name=sheet)
        buf.seek(0)
        return buf.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    except Exception:
        pass

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for step_name, df in dfs_por_etapa.items():
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            csv_name = (step_name or "Etapa").replace("/", "_") + ".csv"
            z.writestr(csv_name, csv_bytes)
    zbuf.seek(0)
    return zbuf.read(), "application/zip", "zip"

# ----------------- Página -----------------

def pagina_gerar_massas():
    st.title("🚀 Geração de Massas")
    st.subheader("Selecione o fluxo e execute:")

    api_url = _get_api_url()
    ambientes = _get_envs()

    fluxos_yaml = _carregar_fluxos_yaml()
    fluxos = list(fluxos_yaml.keys()) if isinstance(fluxos_yaml, dict) else []

    if not fluxos:
        st.warning("⚠️ Nenhum fluxo encontrado. Cadastre um novo fluxo para começar.")
        return

    c1, c2 = st.columns([0.6, 0.4])
    with c1:
        fluxo_escolhido = st.selectbox("🧩 Escolha o fluxo:", fluxos)
    with c2:
        ambiente = st.selectbox("🌎 Ambiente:", ambientes, index=0)

    quantidade = st.slider("🔢 Quantidade de massas:", 1, 100, 10)

    if st.button("🚀 Executar Fluxo"):
        params = {"fluxo_name": fluxo_escolhido, "quantidade": quantidade, "env": ambiente}
        headers = {"X-MassAI-Env": ambiente}  # ajuda a manter compatibilidade
        with st.spinner(f"⏳ Executando fluxo em **{ambiente}**..."):
            try:
                response = requests.post(f"{api_url.rstrip('/')}/run_fluxo/", json=params, headers=headers)
            except Exception as e:
                st.error(f"❌ Erro de conexão ao endpoint: {e}")
                return

            raw_text = response.text
            try:
                resultado = response.json()
            except Exception:
                resultado = raw_text

            if response.status_code == 200:
                st.success(f"✅ Fluxo executado com sucesso em **{ambiente}**!")

                # ======= TABELAS PRIMEIRO =======
                exec_list, aviso = _normalizar_execucoes(resultado)
                if aviso:
                    st.info(aviso)

                if exec_list:
                    variaveis_por_etapa = _coletar_variaveis_por_etapa(fluxos_yaml, fluxo_escolhido)
                    dfs_por_etapa = {}
                    if variaveis_por_etapa:
                        st.markdown("### 📄 Variáveis por execução (tabelas por etapa)")
                        for step_name, vars_def in variaveis_por_etapa.items():
                            df = _montar_df_por_etapa(exec_list, step_name, vars_def)
                            dfs_por_etapa[step_name] = df
                            st.markdown(f"**Etapa:** `{step_name}`")
                            st.dataframe(df, use_container_width=True)

                        file_bytes, mime, ext = _gerar_excel_multiplas_abas(dfs_por_etapa)
                        st.download_button(
                            label="📥 Exportar tabelas",
                            data=file_bytes,
                            file_name=f"variaveis_{fluxo_escolhido.replace(' ','_')}_{ambiente}.{ext}",
                            mime=mime,
                        )
                    else:
                        st.info("Nenhuma variável cadastrada no fluxo para montar as tabelas.")
                else:
                    st.info("Não foi possível identificar a lista de execuções no retorno.")

                # ======= JSON BRUTO DEPOIS =======
                st.markdown("### 🔎 Retorno bruto")
                try:
                    st.json(resultado)
                except Exception:
                    st.text(str(resultado))

                # salvar massa localmente
                salvar_massa_gerada_local(fluxo_escolhido, resultado)

                # permitir download do JSON
                try:
                    json_bytes = json.dumps(resultado, indent=2, ensure_ascii=False).encode("utf-8")
                    st.download_button(
                        label="⬇️ Baixar retorno (JSON)",
                        data=json_bytes,
                        file_name=f"massa_{fluxo_escolhido.replace(' ', '_')}_{ambiente}.json",
                        mime="application/json"
                    )
                except Exception as e:
                    st.warning(f"Não foi possível preparar o download JSON: {e}")

            else:
                try:
                    obj = response.json()
                    raw_text = json.dumps(obj, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                st.error(f"❌ Erro na execução (HTTP {response.status_code}) em {ambiente}:\n\n{raw_text}")
