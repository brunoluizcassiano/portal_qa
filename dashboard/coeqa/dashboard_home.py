# coeqa/dashboard_home.py
import streamlit as st
import pandas as pd
from pathlib import Path

# =================== Config de dados ===================
DATA = Path("config/data")

ISSUE_COLS = ["key","summary","status","type","priority","created","resolutiondate","assignee","reporter"]
PROJ_COLS  = ["id","key","name","projectTypeKey","lead"]

def safe_read_csv(name: str, columns=None) -> pd.DataFrame:
    """
    Lê CSV com segurança:
    - se não existir ou tiver 0 bytes, retorna DF vazio com colunas esperadas
    - se existir mas faltar alguma coluna, cria a coluna vazia
    - se der erro de parsing, retorna DF vazio com colunas esperadas
    """
    p = DATA / name
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame(columns=columns or [])
    try:
        df = pd.read_csv(p)
        if columns:
            for c in columns:
                if c not in df.columns:
                    df[c] = pd.NA
            df = df[[c for c in columns if c in df.columns]]
        return df
    except Exception:
        return pd.DataFrame(columns=columns or [])

def map_tier(score: float) -> str:
    if score >= 3.5: return "Diamond 💎"
    if score >= 3.0: return "Gold 🥇"
    if score >= 2.0: return "Silver 🥈"
    return "Bronze 🥉"

def _make_summary(df_proj, df_func, df_story, df_epic, df_bug, df_subbug) -> pd.DataFrame:
    """
    Exemplo de resumo por 'Domain' (usa Project Key como domínio).
    Substitua pelas suas fórmulas reais assim que fechar as métricas.
    """
    if df_proj.empty:
        return pd.DataFrame(columns=[
            "Domain","Category","Score","Covering Test","Test AVG",
            "Created Automation","Automated Runs","Test Regression",
            "Negative Test","Resolution Bug"
        ])

    proj = df_proj.rename(columns={"key":"Domain"})[["Domain","name","projectTypeKey"]].copy()
    proj["Category"] = proj["projectTypeKey"].astype(str).str.title()

    # ======= MÉTRICAS DE EXEMPLO (troque pelas suas regras reais) =======
    counts = {
        "Func": len(df_func),
        "Epic": len(df_epic),
        "Story": len(df_story),
        "Bug": len(df_bug) + len(df_subbug),
    }
    total_tests = max(1, counts["Func"] + counts["Story"])
    coverage = (total_tests / (total_tests + counts["Epic"])) * 100 if total_tests else 0

    proj["Score"] = round((coverage/100)*3.5, 2)
    proj["Covering Test"] = round(coverage, 2)
    proj["Test AVG"] = 3.0                 # coloque sua média real
    proj["Created Automation"] = "85.7%"   # % automatizado criado (Zephyr)
    proj["Automated Runs"] = "88.7%"       # % execuções automatizadas (Zephyr)
    proj["Test Regression"] = "47.4%"      # % regressão (Zephyr)
    proj["Negative Test"] = "19.3%"        # % testes negativos (Zephyr)
    proj["Resolution Bug"] = "10.4d"       # lead time bugs (Jira)

    cols = [
        "Domain","Category","Score","Covering Test","Test AVG",
        "Created Automation","Automated Runs","Test Regression",
        "Negative Test","Resolution Bug"
    ]
    proj = proj[cols].sort_values("Score", ascending=False).reset_index(drop=True)
    return proj

def pagina_dashboard_home():
    """Renderiza a página 'Visão Geral de Qualidade' no Streamlit."""
    st.set_page_config(page_title="Visão Geral de Qualidade", layout="wide")

    # ====== Estilo ======
    st.markdown("""
    <style>
    .big-title {font-size: 28px; font-weight: 700; letter-spacing: .3px;}
    .subtle {opacity:.9}
    .badge-card{
      background: rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08);
      border-radius:12px; padding:16px; text-align:center
    }
    .tbl thead tr th { background: rgba(255,255,255,.04); }
    .block-container { padding-left: 1rem; padding-right: 1rem; }
    </style>
    """, unsafe_allow_html=True)

    # ====== Carregamento das bases (tolerante a vazio) ======
    df_func   = safe_read_csv("jira_issues_func_latest.csv",   ISSUE_COLS)
    df_epic   = safe_read_csv("jira_issues_epic_latest.csv",   ISSUE_COLS)
    df_story  = safe_read_csv("jira_issues_story_latest.csv",  ISSUE_COLS)
    df_bug    = safe_read_csv("jira_issues_bug_latest.csv",    ISSUE_COLS)
    df_subbug = safe_read_csv("jira_issues_subbug_latest.csv", ISSUE_COLS)
    df_proj   = safe_read_csv("jira_projetos_latest.csv",      PROJ_COLS)

    # ====== Header ======
    col1, col2 = st.columns([0.65, 0.35])
    with col1:
        st.markdown('<div class="big-title">CoE de Qualidade</div>', unsafe_allow_html=True)
        st.markdown('<div class="subtle">Visão Geral de Qualidade • visão executiva do portfólio</div>', unsafe_allow_html=True)
    with col2:
        pass  # filtros (período, tribo, squad etc)

    st.markdown("---")

    # ====== Selos / Faixas ======
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        st.markdown('<div class="badge-card">Diamond 💎<br/>Score ≥ 3.5</div>', unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="badge-card">Gold 🥇<br/>3.0 ≤ Score &lt; 3.5</div>', unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="badge-card">Silver 🥈<br/>2.0 ≤ Score &lt; 3.0</div>', unsafe_allow_html=True)
    with c4:
        st.markdown('<div class="badge-card">Bronze 🥉<br/>Score &lt; 2.0</div>', unsafe_allow_html=True)

    st.markdown("")

    # ====== Tabela principal ======
    st.markdown("##### Visão por Domínio / Tribo")
    summary = _make_summary(df_proj, df_func, df_story, df_epic, df_bug, df_subbug)

    if summary.empty:
        st.info("Sem dados ainda. Execute os extratores (Jira/Zephyr) para popular as bases em config/data/*.csv.")
    else:
        df_show = summary.copy()
        df_show["Tier"] = df_show["Score"].apply(map_tier)
        df_show = df_show[[
            "Domain","Category","Tier","Score","Covering Test","Test AVG",
            "Created Automation","Automated Runs","Test Regression","Negative Test","Resolution Bug"
        ]]
        st.dataframe(df_show, use_container_width=True, height=480)


# Permite rodar este arquivo sozinho (útil para debug local):
if __name__ == "__main__":
    pagina_dashboard_home()
