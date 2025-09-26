# coeqa/dashboard_covaregeAndRun.py
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

# ---------- utils ----------
def safe_read_csv(name: str, columns=None) -> pd.DataFrame:
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

def key_project_prefix(key: str) -> str:
    if isinstance(key, str) and "-" in key:
        return key.split("-")[0]
    return ""

def to_month(dt_str):
    if pd.isna(dt_str): return None
    try:
        return pd.to_datetime(dt_str).strftime("%Y-%m")
    except Exception:
        return None

def pct(a, b):
    return float(a) / float(b) * 100 if b not in (0, None, np.nan) else 0.0

# ---------- página ----------
def pagina_dashboard_coverage_and_run():
    try:
        st.set_page_config(page_title="Coverage and Run", layout="wide")
    except Exception:
        pass

    # ---- ESTILO (cards/métricas como suas telas anteriores)
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
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### Coverage and Run")

    # ----- Carrega bases
    df_story  = safe_read_csv("jira_issues_story_latest.csv",  ISSUE_COLS)
    df_epic   = safe_read_csv("jira_issues_epic_latest.csv",   ISSUE_COLS)
    df_bug    = safe_read_csv("jira_issues_bug_latest.csv",    ISSUE_COLS)
    df_subbug = safe_read_csv("jira_issues_subbug_latest.csv", ISSUE_COLS)
    df_proj   = safe_read_csv("jira_projetos_latest.csv",      PROJ_COLS)
    df_zc     = safe_read_csv("zephyr_testcases_latest.csv",   Z_CASES_COLS)
    df_ze     = safe_read_csv("zephyr_executions_latest.csv",  Z_EXEC_COLS)

    # ----- Colunas auxiliares
    for d in (df_story, df_epic, df_bug, df_subbug):
        if "projectKey" not in d.columns:
            d["projectKey"] = d["key"].apply(key_project_prefix)
        if "created" in d.columns:
            d["created_dt"] = pd.to_datetime(d["created"], errors="coerce")
            d["created_date"] = d["created_dt"].dt.date
        d["month"] = d["created"].apply(to_month)

    if not df_ze.empty:
        if "projectKey" not in df_ze.columns:
            df_ze["projectKey"] = df_ze["issueKey"].apply(key_project_prefix)
        df_ze["executed_dt"] = pd.to_datetime(df_ze["executedOn"], errors="coerce")
        df_ze["executed_date"] = df_ze["executed_dt"].dt.date
        df_ze["month"] = df_ze["executed_dt"].dt.strftime("%Y-%m")

    if not df_zc.empty:
        if "projectKey" not in df_zc.columns:
            df_zc["projectKey"] = df_zc.get("key","").apply(key_project_prefix)
        if "created" in df_zc.columns:
            df_zc["created_dt"] = pd.to_datetime(df_zc["created"], errors="coerce")
            df_zc["created_date"] = df_zc["created_dt"].dt.date

    # ----- Filtros: intervalo (calendário + slider) e Domain
    all_exec_dates = df_ze["executed_date"].dropna().tolist() if "executed_date" in df_ze.columns else []
    if all_exec_dates:
        min_d, max_d = min(all_exec_dates), max(all_exec_dates)
    else:
        min_d, max_d = date.today() - timedelta(days=180), date.today()

    # 1) Fonte única do intervalo
    if "periodo_master" not in st.session_state:
        st.session_state["periodo_master"] = (min_d, max_d)

    # 2) Garantia: os dois widget-keys existem e SEMPRE são tuplas (início, fim)
    def _ensure_range_key(key: str, fallback: tuple[date, date]):
        v = st.session_state.get(key, None)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            st.session_state[key] = (v[0], v[1])
        elif isinstance(v, date):
            st.session_state[key] = (v, v)
        else:
            st.session_state[key] = fallback

    _ensure_range_key("intervalo_data",   st.session_state["periodo_master"])
    _ensure_range_key("intervalo_slider", st.session_state["periodo_master"])

    # 3) Callbacks de sincronização (bidirecional), SEM st.rerun()
    def _on_calendar_change():
        # calendário venceu → atualiza master e o slider
        st.session_state["periodo_master"] = st.session_state["intervalo_data"]
        st.session_state["intervalo_slider"] = st.session_state["intervalo_data"]

    def _on_slider_change():
        # slider venceu → atualiza master e o calendário
        st.session_state["periodo_master"] = st.session_state["intervalo_slider"]
        st.session_state["intervalo_data"] = st.session_state["intervalo_slider"]

    # 4) Linha de filtros (Domain + intervalo)
    c0, c1, c2 = st.columns([0.50, 0.30, 0.20])
    with c0:
        if not df_proj.empty:
            projects = ["Todos"] + sorted(df_proj["key"].dropna().unique().tolist())
        else:
            pref = []
            for d in (df_story, df_epic, df_ze):
                if not d.empty and "projectKey" in d.columns:
                    pref += d["projectKey"].dropna().tolist()
            projects = ["Todos"] + sorted(list(set(pref)))
        sel_project = st.selectbox("Domain", options=projects, index=0)
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
                key="intervalo_data",
                min_value=min_d,
                max_value=max_d,
                format="DD/MM/YYYY",
                on_change=_on_calendar_change,
            )
        with cb:
            st.slider(
                "Date (slider)",
                key="intervalo_slider",
                min_value=min_d,
                max_value=max_d,
                format="DD/MM/YYYY",
                on_change=_on_slider_change,
            )
    with c1:
        st.caption("")
    with c2:
        st.caption("")

    # 5) Usa a fonte única como período final aplicado
    d_start, d_end = st.session_state["periodo_master"]

    # ----- aplica filtros
    def f_proj(df, col="projectKey"):
        if df.empty: return df
        return df if sel_project == "Todos" else df[df[col] == sel_project]

    def f_period_exec(df):
        if df.empty or "executed_date" not in df.columns: return df
        return df[(df["executed_date"] >= d_start) & (df["executed_date"] <= d_end)].copy()

    def f_period_created(df):
        if df.empty or "created_date" not in df.columns: return df
        return df[(df["created_date"] >= d_start) & (df["created_date"] <= d_end)].copy()

    f_story  = f_proj(f_period_created(df_story))
    f_epic   = f_proj(f_period_created(df_epic))
    f_zc     = f_proj(f_period_created(df_zc))
    f_ze     = f_proj(f_period_exec(df_ze))

    # ----- Cards
    col1 = st.columns(4)
    with col1[0]:
        if not df_proj.empty:
            domains = len(df_proj if sel_project=="Todos" else df_proj[df_proj["key"]==sel_project])
        else:
            domains = len(set([*f_story["projectKey"].dropna().unique(), *f_epic["projectKey"].dropna().unique()]))
        st.metric("Domain", domains or 0)
    with col1[1]:
        st.metric("QTD Story", int(f_story.shape[0]))
    with col1[2]:
        st.metric("QTD Epic", int(f_epic.shape[0]))
    with col1[3]:
        num = int(f_story.shape[0]); den = num + int(f_epic.shape[0])
        st.metric("% Story Coverage", f"{pct(num,den):.2f}%")

    col2 = st.columns(4)
    with col2[0]:
        if not f_ze.empty and "automated" in f_ze.columns:
            man = (~f_ze["automated"].astype(str).str.lower().isin(["1","true","yes"])).sum()
        else:
            man = 0
        st.metric("Manual Test Run", int(man))
    with col2[1]:
        if not f_ze.empty and "automated" in f_ze.columns:
            aut = f_ze["automated"].astype(str).str.lower().isin(["1","true","yes"]).sum()
        else:
            aut = 0
        st.metric("Automated Test Run", int(aut))
    with col2[2]:
        if not f_ze.empty:
            cycles = f_ze.groupby(["month","issueKey"]).ngroups
        else:
            cycles = 0
        st.metric("Test Cycle", int(cycles))
    with col2[3]:
        if not f_ze.empty and "issueKey" in f_ze.columns:
            by_issue = f_ze.dropna(subset=["issueKey"]).groupby("issueKey").size()
            avg_issue = by_issue.mean() if not by_issue.empty else 0.0
        else:
            avg_issue = 0.0
        st.metric("Test average per issue", f"{avg_issue:.2f}")

    st.markdown("---")

    # ---------- Automated backlog
    st.markdown("#### Automated Backlog")
    if f_zc.empty:
        st.info("Sem dados de casos de teste (Zephyr Test Cases).")
    else:
        auto_mask = f_zc["automated"].astype(str).str.lower().isin(["1","true","yes"])
        n_auto = int(auto_mask.sum())
        n_total = int(len(f_zc))
        n_not_app = int((f_zc.get("status","").astype(str).str.contains("not applic", case=False)).sum()) if "status" in f_zc.columns else 0
        n_backlog = max(0, n_total - n_auto - n_not_app)

        df_auto_stack = pd.DataFrame({
            "Categoria": ["Automated","Backlog automated","Not applicable"],
            "Quantidade": [n_auto, n_backlog, n_not_app]
        })
        chart_auto = alt.Chart(df_auto_stack).mark_bar().encode(
            x=alt.X("Quantidade:Q", title="Quantidade"),
            y=alt.Y("Categoria:N", sort=None, title=None),
            color=alt.Color("Categoria:N", legend=None)
        ).properties(height=120)
        st.altair_chart(chart_auto, use_container_width=True)

    cA, cB, cC = st.columns(3)

    # ---------- Regressive × Others
    with cA:
        st.markdown("#### Regressive × Others (Test type)")
        if f_ze.empty or "testType" not in f_ze.columns:
            st.info("Sem dados suficientes para agrupar por 'testType'.")
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

    # ---------- Positive × Negative
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

    # ---------- Automated run × Manual run
    with cC:
        st.markdown("#### Automated run × Manual run")
        if f_ze.empty or "automated" not in f_ze.columns:
            st.info("Sem dados suficientes para identificar execução automatizada.")
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

    st.markdown("---")

    # ---------- Test evolution (linha mensal)
    st.markdown("#### Test evolution (mensal)")
    if f_ze.empty:
        st.info("Sem execuções no período selecionado.")
    else:
        z = f_ze.copy()
        z["is_auto"] = z["automated"].astype(str).str.lower().isin(["1","true","yes"]) if "automated" in z.columns else False
        df_month = z.groupby(["month","is_auto"]).size().reset_index(name="runs")
        df_month["tipo"] = df_month["is_auto"].map({True:"Automated Run", False:"Manual Run"})
        try:
            df_month["month_dt"] = pd.to_datetime(df_month["month"] + "-01")
            df_month = df_month.sort_values("month_dt")
        except Exception:
            pass
        ch = alt.Chart(df_month).mark_line(point=True).encode(
            x=alt.X("month:N", title="Mês"),
            y=alt.Y("runs:Q", title="Runs"),
            color=alt.Color("tipo:N", title=None)
        ).properties(height=300)
        st.altair_chart(ch, use_container_width=True)

    # ---------- Automation in regressive
    st.markdown("#### Automation in regressive")
    if f_ze.empty or "testType" not in f_ze.columns:
        st.info("Sem dados suficientes para regressão.")
    else:
        z = f_ze.copy()
        reg = z["testType"].astype(str).str.lower().str.contains("regress")
        is_auto = z["automated"].astype(str).str.lower().isin(["1","true","yes"]) if "automated" in df_ze.columns else False
        df_reg = pd.DataFrame({
            "status": ["Automated", "Manual"],
            "runs": [int((reg & is_auto).sum()), int((reg & ~is_auto).sum())]
        })
        ch = alt.Chart(df_reg).mark_bar().encode(
            x=alt.X("status:N", title=None),
            y=alt.Y("runs:Q", title="Runs"),
            color=alt.Color("status:N", legend=None)
        ).properties(height=260)
        st.altair_chart(ch, use_container_width=True)

# debug isolado
if __name__ == "__main__":
    pagina_dashboard_coverage_and_run()
