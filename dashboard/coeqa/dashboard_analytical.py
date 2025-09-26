# coeqa/dashboard_analytical.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from pathlib import Path
from datetime import datetime, date, timedelta

DATA = Path("config/data")

ISSUE_COLS = ["key","summary","status","type","priority","created","resolutiondate","assignee","reporter"]
PROJ_COLS  = ["id","key","name","projectTypeKey","lead"]

# Zephyr (opcionais)
Z_CASES_COLS = ["key","name","status","automated","testType","labels","created","projectKey"]
Z_EXEC_COLS  = ["executionKey","testKey","status","automated","testType","labels","executedOn","projectKey","issueKey"]

# ----------------- utils -----------------
def safe_read_csv(name: str, columns=None) -> pd.DataFrame:
    p = DATA / name
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame(columns=columns or [])
    try:
        df = pd.read_csv(p)
        if columns:
            # garante colunas esperadas
            for c in columns:
                if c not in df.columns:
                    df[c] = pd.NA
            # ordena se possível
            keep = [c for c in columns if c in df.columns]
            df = df[keep]
        return df
    except Exception:
        return pd.DataFrame(columns=columns or [])

def key_project_prefix(key: str) -> str:
    if isinstance(key, str) and "-" in key:
        return key.split("-")[0]
    return ""

def pct(a, b):
    return float(a) / float(b) * 100 if b not in (0, None, np.nan) else 0.0

def _normalize_dates(df: pd.DataFrame, col: str, out_prefix: str):
    if col in df.columns:
        dt = pd.to_datetime(df[col], errors="coerce")
        df[f"{out_prefix}_dt"] = dt
        df[f"{out_prefix}_date"] = dt.dt.date
        df["month"] = dt.dt.strftime("%Y-%m")

def _as_range(v, fallback):
    # garante (start, end)
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return (v[0], v[1])
    if isinstance(v, date):
        return (v, v)
    return fallback

# ----------------- página -----------------
def pagina_dashboard_analytical():
    try:
        st.set_page_config(page_title="Analytical", layout="wide")
    except Exception:
        pass

    # ====== ESTILO (mesmo das outras telas) ======
    st.markdown("""
    <style>
      .stButton > button {
        height: 78px; width: 100%;
        border-radius: 10px; border: 1px solid rgba(255,255,255,.12);
        background: rgba(255,255,255,.04);
        white-space: pre-line; line-height: 1.05; padding: 8px 8px;
        text-align: center; font-size: 12px; font-weight: 700; min-width: 0;
      }
      .stButton > button:hover { border-color: rgba(186,85,211,.6); background: rgba(186,85,211,.10); }
      .score-selected > button { outline: 2px solid #ba55d3 !important; background: rgba(186,85,211,.16) !important; border-color: transparent !important; }
      .block-container { padding-left: 1rem; padding-right: 1rem; }

      /* Métricas */
      [data-testid="stMetric"] { padding: .4rem .6rem; border-radius: 10px; background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08); }
      [data-testid="stMetricLabel"] { font-size: 12px; opacity: .85; letter-spacing: .2px; }
      [data-testid="stMetricValue"] { font-weight: 800; font-size: 28px; line-height: 1.05; }
      .small-caption { font-size: 12px; opacity:.75; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### Analytical")

    # ====== Carrega bases ======
    df_story  = safe_read_csv("jira_issues_story_latest.csv",  ISSUE_COLS)
    df_epic   = safe_read_csv("jira_issues_epic_latest.csv",   ISSUE_COLS)
    df_bug    = safe_read_csv("jira_issues_bug_latest.csv",    ISSUE_COLS)
    df_subbug = safe_read_csv("jira_issues_subbug_latest.csv", ISSUE_COLS)
    df_proj   = safe_read_csv("jira_projetos_latest.csv",      PROJ_COLS)
    df_zc     = safe_read_csv("zephyr_testcases_latest.csv",   Z_CASES_COLS)
    df_ze     = safe_read_csv("zephyr_executions_latest.csv",  Z_EXEC_COLS)

    # ====== Normalize/aux ======
    for d in (df_story, df_epic, df_bug, df_subbug):
        if not d.empty:
            if "projectKey" not in d.columns:
                d["projectKey"] = d["key"].apply(key_project_prefix)
            _normalize_dates(d, "created", "created")

    if not df_ze.empty:
        if "projectKey" not in df_ze.columns:
            df_ze["projectKey"] = df_ze["issueKey"].apply(key_project_prefix)
        _normalize_dates(df_ze, "executedOn", "executed")

    if not df_zc.empty:
        if "projectKey" not in df_zc.columns:
            df_zc["projectKey"] = df_zc.get("key","").apply(key_project_prefix)
        _normalize_dates(df_zc, "created", "created")

    # ====== Filtros (Data + Domain) ======
    # limite de datas baseado em execuções; se vazio, usa created das issues
    all_exec_dates = df_ze["executed_date"].dropna().tolist() if "executed_date" in df_ze.columns else []
    if all_exec_dates:
        min_d, max_d = min(all_exec_dates), max(all_exec_dates)
    else:
        pool = []
        for d in (df_story, df_epic, df_bug, df_subbug):
            if "created_date" in d.columns:
                pool += d["created_date"].dropna().tolist()
        if pool:
            min_d, max_d = min(pool), max(pool)
        else:
            min_d, max_d = date.today() - timedelta(days=180), date.today()

    # Fonte única do intervalo
    if "analit_periodo_master" not in st.session_state:
        st.session_state["analit_periodo_master"] = (min_d, max_d)

    # Garante que os keys dos widgets existam como range
    def _ensure_range_key(key: str, fallback: tuple[date, date]):
        v = st.session_state.get(key, None)
        st.session_state[key] = _as_range(v, fallback)

    _ensure_range_key("analit_intervalo_data",   st.session_state["analit_periodo_master"])
    _ensure_range_key("analit_intervalo_slider", st.session_state["analit_periodo_master"])

    # Callbacks de sync
    def _on_calendar_change():
        st.session_state["analit_periodo_master"] = st.session_state["analit_intervalo_data"]
        st.session_state["analit_intervalo_slider"] = st.session_state["analit_intervalo_data"]

    def _on_slider_change():
        st.session_state["analit_periodo_master"] = st.session_state["analit_intervalo_slider"]
        st.session_state["analit_intervalo_data"] = st.session_state["analit_intervalo_slider"]

    # linha de filtros
    c0, c1, c2 = st.columns([0.50, 0.30, 0.20])
    with c0:
        if not df_proj.empty:
            projects = ["Todos"] + sorted(df_proj["key"].dropna().unique().tolist())
        else:
            pref = []
            for d in (df_story, df_epic, df_bug, df_subbug, df_ze):
                if not d.empty and "projectKey" in d.columns:
                    pref += d["projectKey"].dropna().tolist()
            projects = ["Todos"] + sorted(list(set(pref)))
        sel_project = st.selectbox("Domain (Projeto)", options=projects, index=0)
    with c1:
        st.caption("")
    with c2:
        st.caption(datetime.now().strftime("Atualizado: %d/%m/%Y %H:%M"))

    c0, c1, c2 = st.columns([0.50, 0.30, 0.20])
    with c0:
        ca, cb = st.columns(2)
        with ca:
            st.date_input(
                "Date (calendário)",
                key="analit_intervalo_data",
                min_value=min_d,
                max_value=max_d,
                format="DD/MM/YYYY",
                on_change=_on_calendar_change,
            )
        with cb:
            st.slider(
                "Date (slider)",
                key="analit_intervalo_slider",
                min_value=min_d,
                max_value=max_d,
                format="DD/MM/YYYY",
                on_change=_on_slider_change,
            )
    with c1:
        st.caption("")
    with c2:
        st.caption("")

    # período aplicado
    d_start, d_end = st.session_state["analit_periodo_master"]

    # ====== Filtro por período e projeto ======
    def f_proj(df, col="projectKey"):
        if df.empty: return df
        return df if sel_project == "Todos" else df[df[col] == sel_project]

    def f_period_created(df):
        if df.empty or "created_date" not in df.columns: return df
        return df[(df["created_date"] >= d_start) & (df["created_date"] <= d_end)].copy()

    def f_period_exec(df):
        if df.empty or "executed_date" not in df.columns: return df
        return df[(df["executed_date"] >= d_start) & (df["executed_date"] <= d_end)].copy()

    f_story  = f_proj(f_period_created(df_story))
    f_epic   = f_proj(f_period_created(df_epic))
    f_bug    = f_proj(f_period_created(df_bug))
    f_subbug = f_proj(f_period_created(df_subbug))
    f_ze     = f_proj(f_period_exec(df_ze))
    f_zc     = f_proj(f_period_created(df_zc))
    f_proj_all = df_proj if sel_project == "Todos" else df_proj[df_proj["key"] == sel_project]

    # ====== KPIs ======
    # Linha 1
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        domains = len(f_proj_all) if not f_proj_all.empty else len({*f_story["projectKey"], *f_epic["projectKey"], *f_bug["projectKey"], *f_subbug["projectKey"]})
        st.metric("Domain", int(domains or 0))
    with k2:
        st.metric("QTD Story", int(f_story.shape[0]))
    with k3:
        st.metric("QTD Epic", int(f_epic.shape[0]))
    with k4:
        den = int(f_story.shape[0]) + int(f_epic.shape[0])
        st.metric("% Story Coverage", f"{pct(int(f_story.shape[0]), den):.2f}%")

    # Linha 2
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        if not f_ze.empty and "automated" in f_ze.columns:
            manual = (~f_ze["automated"].astype(str).str.lower().isin(["1","true","yes"])).sum()
        else:
            manual = 0
        st.metric("# Manual Test Run", int(manual))
    with m2:
        if not f_ze.empty and "automated" in f_ze.columns:
            auto = f_ze["automated"].astype(str).str.lower().isin(["1","true","yes"]).sum()
        else:
            auto = 0
        st.metric("# Automated Test Run", int(auto))
    with m3:
        cycles = f_ze.groupby(["month","issueKey"]).ngroups if not f_ze.empty and "issueKey" in f_ze.columns else 0
        st.metric("# Test Cycle", int(cycles))
    with m4:
        if not f_ze.empty and "issueKey" in f_ze.columns:
            by_issue = f_ze.dropna(subset=["issueKey"]).groupby("issueKey").size()
            avg_issue = by_issue.mean() if not by_issue.empty else 0.0
        else:
            avg_issue = 0.0
        st.metric("Test average per issue", f"{avg_issue:.2f}")

    st.markdown("---")

    # ====== Tabela principal (issues) ======
    # monta df unificado
    def _prep_issues(df: pd.DataFrame, tipo: str) -> pd.DataFrame:
        if df.empty: 
            return pd.DataFrame(columns=["Jira Key","Domain","Sub-domain","Issue","Coverage Tests","Issue Type","Status","Priority","Created","Assignee","Reporter"])
        out = pd.DataFrame()
        out["Jira Key"]       = df["projectKey"]
        # Domain: nome do projeto (join)
        if "projectKey" in df.columns and not df_proj.empty:
            mp = dict(zip(df_proj["key"], df_proj["name"]))
            out["Domain"] = df["projectKey"].map(mp).fillna(df["projectKey"])
        else:
            out["Domain"] = df["projectKey"]
        # Sub-domain: como não temos hierarquia completa, use type para um agrupamento simples
        out["Sub-domain"]     = tipo
        out["Issue"]          = df["key"]
        # Coverage Tests: proxy — número de execuções no Zephyr para a issue
        if "key" in df.columns and not f_ze.empty and "issueKey" in f_ze.columns:
            runs_by_issue = f_ze.groupby("issueKey").size()
            out["Coverage Tests"] = out["Issue"].map(runs_by_issue).fillna(0).astype(int)
        else:
            out["Coverage Tests"] = 0
        out["Issue Type"]     = tipo
        out["Status"]         = df.get("status")
        out["Priority"]       = df.get("priority")
        out["Created"]        = df.get("created")
        out["Assignee"]       = df.get("assignee")
        out["Reporter"]       = df.get("reporter")
        return out

    tbl = pd.concat([
        _prep_issues(f_story,  "Story"),
        _prep_issues(f_epic,   "Epic"),
        _prep_issues(f_bug,    "Bug"),
        _prep_issues(f_subbug, "Sub-bug"),
    ], ignore_index=True)

    st.markdown("#### Issues (Story / Epic / Bug / Sub-bug)")
    if tbl.empty:
        st.info("Sem issues para o período/projeto selecionados.")
    else:
        # ordena por Domain, Sub-domain e Issue
        tbl_sorted = tbl.sort_values(["Domain","Sub-domain","Issue"], kind="stable")
        st.dataframe(
            tbl_sorted,
            use_container_width=True,
            hide_index=True
        )

    st.markdown("---")

    # ====== Complementos analíticos (exemplos) ======
    cA, cB, cC = st.columns(3)

    with cA:
        st.markdown("#### Execuções por tipo (Regressive × Others)")
        if f_ze.empty or "testType" not in f_ze.columns:
            st.info("Sem dados suficientes.")
        else:
            z = f_ze.copy()
            z["grp"] = np.where(
                z["testType"].astype(str).str.lower().str.contains("regress"), "Regressive", "Others"
            )
            df_grp = z.groupby("grp").size().reset_index(name="runs")
            ch = alt.Chart(df_grp).mark_bar().encode(
                x=alt.X("grp:N", title=None),
                y=alt.Y("runs:Q", title="Runs"),
                color=alt.Color("grp:N", legend=None)
            ).properties(height=220)
            st.altair_chart(ch, use_container_width=True)

    with cB:
        st.markdown("#### Positive × Negative (labels/testType)")
        if f_ze.empty:
            st.info("Sem execuções no período.")
        else:
            z = f_ze.copy()
            neg = pd.Series(False, index=z.index)
            if "testType" in z.columns:
                neg |= z["testType"].astype(str).str.lower().str.contains("negative|negativo")
            if "labels" in z.columns:
                neg |= z["labels"].astype(str).str.lower().str.contains("negative|negativo")
            df_pn = pd.DataFrame({
                "class": ["Positive","Negative"],
                "runs":  [int((~neg).sum()), int(neg.sum())]
            })
            ch = alt.Chart(df_pn).mark_bar().encode(
                x=alt.X("class:N", title=None),
                y=alt.Y("runs:Q", title="Runs"),
                color=alt.Color("class:N", legend=None)
            ).properties(height=220)
            st.altair_chart(ch, use_container_width=True)

    with cC:
        st.markdown("#### Automated × Manual")
        if f_ze.empty or "automated" not in f_ze.columns:
            st.info("Sem dados suficientes.")
        else:
            is_auto = f_ze["automated"].astype(str).str.lower().isin(["1","true","yes"])
            df_am = pd.DataFrame({
                "tipo": ["Automated","Manual"],
                "runs": [int(is_auto.sum()), int((~is_auto).sum())]
            })
            ch = alt.Chart(df_am).mark_bar().encode(
                x=alt.X("tipo:N", title=None),
                y=alt.Y("runs:Q", title="Runs"),
                color=alt.Color("tipo:N", legend=None)
            ).properties(height=220)
            st.altair_chart(ch, use_container_width=True)

# debug isolado
if __name__ == "__main__":
    pagina_dashboard_analytical()
