# -*- coding: utf-8 -*-
import streamlit as st
import requests
import yaml
import json
import os
import time
import pandas as pd

# === CONFIGURAÇÕES ===
MASSAS_FILE = 'config/massai_massa_gerada.yaml'
SETTINGS_FILE = 'config/settings.yaml'
FLUXOS_FILE = 'config/fluxos.yaml'

def _load_settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

settings = _load_settings()
API_URL = settings.get('api_url', 'http://127.0.0.1:8000')

# =============================================================
# Utils
# =============================================================

def salvar_massa_gerada(fluxo_name, dados):
    try:
        if os.path.exists(MASSAS_FILE):
            with open(MASSAS_FILE, 'r', encoding='utf-8') as f:
                massas = yaml.safe_load(f) or []
        else:
            massas = []
    except Exception:
        massas = []

    novo_registro = {
        "fluxo_name": fluxo_name,
        "status": "valida",   # Quando gerada assume como 'valida'
        "dados": dados,
        "data_criacao": time.strftime("%d/%m/%Y %H:%M:%S")
    }
    massas.append(novo_registro)

    try:
        os.makedirs(os.path.dirname(MASSAS_FILE), exist_ok=True)
        with open(MASSAS_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(massas, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        st.warning(f"Não foi possível gravar o arquivo de massas: {e}")

def _carregar_fluxos_yaml():
    try:
        with open(FLUXOS_FILE, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

def _get_value_from_path(data, path: str):
    """Extrai valor de um dicionário/lista usando caminho tipo 'a.b[0].c'."""
    try:
        if data is None:
            return None
        parts = [p for p in __import__('re').split(r"[.\[\]]+", str(path).strip()) if p != ""]
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

def _coletar_variaveis_do_fluxo(fluxos_yaml: dict, fluxo_nome: str):
    """
    Retorna lista de dicts: [{"nome": "...", "origem": "...", "step_nome": "..."}]
    Percorre as etapas do fluxo e coleta 'variaveis'.
    """
    variaveis = []
    etapas = fluxos_yaml.get(fluxo_nome, [])
    for step in etapas:
        step_nome = step.get("nome") or step.get("api_name") or "(sem-nome)"
        for var in (step.get("variaveis") or []):
            n = (var.get("nome") or "").strip()
            o = (var.get("origem") or "").strip()
            if n and o:
                variaveis.append({"nome": n, "origem": o, "step_nome": step_nome})
    return variaveis

def _montar_tabela_variaveis(resultado_execucao: dict, variaveis: list):
    """
    resultado_execucao: dict com chaves = nome da etapa (ou url) e valor = dict com 'response'
    variaveis: lista de {"nome","origem","step_nome"}
    Retorna dict {nome_var: valor_extraido}
    """
    row = {}
    for v in variaveis:
        nome = v["nome"]
        origem = v["origem"]
        step_nome = v["step_nome"]
        # procura o bloco da etapa correspondente
        bloco = resultado_execucao.get(step_nome)
        if not bloco:
            # se a chave for diferente, tenta qualquer chave que contenha o nome
            # (algumas execuções podem renomear a chave para URL)
            # fallback: pega o primeiro bloco
            bloco = next(iter(resultado_execucao.values()), {})
        resp = bloco.get("response") if isinstance(bloco, dict) else None

        # tipos de origem suportados na UI (path é o mais comum)
        if origem.startswith("={{") or origem.startswith("ctx:") or origem.startswith("ctx."):
            # valores de contexto/literal não estão no response -> sem backend, não temos fonte aqui
            row[nome] = ""
        elif origem.startswith("{{") and origem.endswith("}}"):
            # variável do contexto (pré-request ou de etapa anterior) – idem acima
            row[nome] = ""
        elif origem.startswith("="):
            row[nome] = origem[1:]
        else:
            row[nome] = _get_value_from_path(resp, origem)
    return row

# =============================================================
# Página principal
# =============================================================

def pagina_gerar_massas():
    st.title("🚀 Geração de Massas")
    st.subheader("Selecione o fluxo e execute:")

    fluxos_yaml = _carregar_fluxos_yaml()
    fluxos = list(fluxos_yaml.keys()) if isinstance(fluxos_yaml, dict) else []

    if not fluxos:
        st.warning("⚠️ Nenhum fluxo encontrado. Cadastre um novo fluxo para começar.")
        return

    fluxo_escolhido = st.selectbox("🧩 Escolha o fluxo:", fluxos)
    quantidade = st.slider("🔢 Quantidade de massas:", 1, 100, 10)

    if st.button("🚀 Executar Fluxo"):
        params = {"fluxo_name": fluxo_escolhido, "quantidade": quantidade}
        with st.spinner("⏳ Executando fluxo, aguarde..."):
            try:
                response = requests.post(f"{API_URL.rstrip('/')}/run_fluxo/", json=params)
            except Exception as e:
                st.error(f"❌ Erro de conexão ao chamar o endpoint: {e}")
                return

            if response.status_code == 200:
                try:
                    resultado = response.json()
                except Exception:
                    resultado = response.text

                st.success("✅ Fluxo executado com sucesso!")
                # Mostra bruto (útil para debug)
                try:
                    st.json(resultado)
                except Exception:
                    st.text(str(resultado))

                # Salva massa localmente
                salvar_massa_gerada(fluxo_escolhido, resultado)

                # Download
                try:
                    json_bytes = json.dumps(resultado, indent=2, ensure_ascii=False).encode('utf-8')
                    st.download_button(
                        label="📥 Baixar Resultado",
                        data=json_bytes,
                        file_name=f"massa_{fluxo_escolhido.replace(' ', '_')}.json",
                        mime='application/json'
                    )
                except Exception as e:
                    st.warning(f"Não foi possível preparar o download: {e}")

                # ======= TABELA DE VARIÁVEIS (1 linha por execução) =======
                if isinstance(resultado, list):
                    variaveis = _coletar_variaveis_do_fluxo(fluxos_yaml, fluxo_escolhido)
                    if variaveis:
                        linhas = []
                        for exec_item in resultado:  # cada execução
                            if isinstance(exec_item, dict):
                                linhas.append(_montar_tabela_variaveis(exec_item, variaveis))
                            else:
                                linhas.append({})
                        df = pd.DataFrame(linhas)
                        st.markdown("### 📄 Variáveis por execução")
                        st.caption("As colunas são as variáveis cadastradas no fluxo. Valores vazios indicam que a origem não está presente no response (ex.: variáveis de pré-request).")
                        st.dataframe(df, use_container_width=True)
                    else:
                        st.info("Nenhuma variável cadastrada no fluxo para montar a tabela.")
                else:
                    st.info("O retorno não está no formato de lista de execuções; tabela não gerada.")

            else:
                # tenta mostrar json de erro quando possível
                texto = response.text
                try:
                    obj = response.json()
                    texto = json.dumps(obj, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                st.error(f"❌ Erro na execução (HTTP {response.status_code}):\n\n{texto}")
