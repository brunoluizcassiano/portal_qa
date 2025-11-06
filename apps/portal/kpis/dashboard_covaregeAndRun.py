# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import datetime, date, timedelta

from .analytics.constants import (
    WARN_RATIO, KPI_LASTUPDATE,
    JIRA_FUNC, JIRA_EPIC, JIRA_STORY, JIRA_BUG, JIRA_SUBBUG, JIRA_PROJ,
    ZEPHYR_TC, ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK,
    ZEPHYR_CYCLE_MAIN, ZEPHYR_CYCLE_FALLBACK,
    KPI_TARGETS
)
from .analytics.data_access import safe_read_csv, read_last_update
from .analytics.transformers import (
    normalize_issue_df, normalize_bugs, extract_linked_issue_ids, extract_years_from_dfs, apply_year_filter,
    ensure_project_on_executions, apply_project_bugs
)
from .analytics.metrics import (
    get_target,
    kpi_coverage_now, kpi_test_avg_per_issue_now, kpi_auto_runs_now,
    kpi_auto_reg_now, kpi_test_reg_now, kpi_negative_now, avg_bug_days,
    monthly_series_coverage, monthly_series_test_avg, monthly_series_auto_runs,
    monthly_series_auto_reg, monthly_series_test_reg, monthly_series_negative
)

# --------------------------------------------------------------------
# Utils
# --------------------------------------------------------------------
def _pct(a, b):
    return (float(a) / float(b) * 100.0) if (b not in (0, None, np.nan)) else 0.0

def _project_from_key(s: pd.Series) -> pd.Series:
    return s.astype(str).str.extract(r"^([A-Z0-9_]+)-", expand=False).fillna("")

# --------------------------------------------------------------------
# Página
# --------------------------------------------------------------------
def pagina_dashboard_coverage_and_run():
    try:
        st.set_page_config(page_title="Coverage and Run", layout="wide")
    except Exception:
        pass

    # ---- ESTILO (mesmo look das outras páginas)
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
      .block-container { padding-left: 1rem; padding-right: 1rem; }
      [data-testid="stMetric"] { padding: .4rem .6rem; border-radius: 10px; background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08); }
      [data-testid="stMetricLabel"] { font-size: 12px; opacity: .85; letter-spacing: .2px; }
      [data-testid="stMetricValue"] { font-weight: 800; font-size: 28px; line-height: 1.05; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### Coverage and Run")

    # ---------------- Carregamento normalizado (cache por mtime) ----------------
    df_story_raw  = safe_read_csv(JIRA_STORY)
    df_epic_raw   = safe_read_csv(JIRA_EPIC)
    df_bug        = normalize_bugs(safe_read_csv(JIRA_BUG))
    df_subbug     = normalize_bugs(safe_read_csv(JIRA_SUBBUG))
    df_proj       = safe_read_csv(JIRA_PROJ)

    df_zc         = safe_read_csv(ZEPHYR_TC)  # test cases (para backlog/created/automated)
    df_ze         = ensure_project_on_executions(
                        safe_read_csv([ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK])
                    )  # execuções (month/year/projectKey)

    # Issues normalizadas (id/key/projectKey/created/month/year)
    df_story = normalize_issue_df(df_story_raw)
    df_epic  = normalize_issue_df(df_epic_raw)

    # Deriva datas prontas (uma vez só)
    for d in (df_story, df_epic):
        if "created" in d.columns:
            d["created_date"] = pd.to_datetime(d["created"], errors="coerce", utc=True).dt.date
        else:
            d["created_date"] = pd.NaT

    # Zephyr executions: já tem month/year/projectKey; compute executed_date
    if not df_ze.empty:
        exec_col = "actualEndDate" if "actualEndDate" in df_ze.columns else ("executedOn" if "executedOn" in df_ze.columns else None)
        if exec_col:
            edt = pd.to_datetime(df_ze[exec_col], errors="coerce", utc=True)
            df_ze["executed_date"] = edt.dt.date
        else:
            df_ze["executed_date"] = pd.NaT

    # Zephyr cases: projectKey + created_date/month/year (se existir)
    if not df_zc.empty:
        if "projectKey" not in df_zc.columns:
            if "key" in df_zc.columns:
                df_zc["projectKey"] = _project_from_key(df_zc["key"])
            else:
                df_zc["projectKey"] = ""
        if "created" in df_zc.columns:
            cdt = pd.to_datetime(df_zc["created"], errors="coerce", utc=True)
            df_zc["created_date"] = cdt.dt.date
            df_zc["month"]        = cdt.dt.strftime("%Y-%m")
            df_zc["year"]         = cdt.dt.year.astype("Int64")
        else:
            df_zc["created_date"] = pd.NaT
            if "month" not in df_zc.columns: df_zc["month"] = pd.NA
            if "year"  not in df_zc.columns: df_zc["year"]  = pd.NA
        df_zc["projectKey"] = df_zc["projectKey"].astype("category")

    # ---------------- Filtros topo (Domain/Período + Atualizado) ----------------
    # Domains
    if not df_proj.empty and {"name","key"}.issubset(df_proj.columns):
        projects = ["Todos"] + sorted(df_proj["key"].dropna().astype(str).unique().tolist())
    else:
        pref = pd.concat(
            [
                s for s in [
                    df_story["projectKey"], df_epic["projectKey"],
                    df_ze.get("projectKey", pd.Series(dtype="object")),
                    df_zc.get("projectKey", pd.Series(dtype="object")),
                ] if not s.empty
            ],
            ignore_index=True
        )
        projects = ["Todos"] + sorted([p for p in pref.dropna().astype(str).unique().tolist() if p])

    # Período baseado nas execuções (fallback: created de story)
    if not df_ze.empty and "executed_date" in df_ze.columns:
        all_dates = df_ze["executed_date"].dropna().tolist()
    elif not df_story.empty:
        all_dates = df_story["created_date"].dropna().tolist()
    else:
        all_dates = []

    if all_dates:
        min_d, max_d = min(all_dates), max(all_dates)
    else:
        min_d, max_d = date.today() - timedelta(days=180), date.today()

    # Fonte única de período em session_state
    if "periodo_master_car" not in st.session_state:
        st.session_state["periodo_master_car"] = (min_d, max_d)

    def _ensure_range_key(key: str, fallback: tuple[date, date]):
        v = st.session_state.get(key, None)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            st.session_state[key] = (v[0], v[1])
        elif isinstance(v, date):
            st.session_state[key] = (v, v)
        else:
            st.session_state[key] = fallback

    _ensure_range_key("intervalo_data_car",   st.session_state["periodo_master_car"])
    _ensure_range_key("intervalo_slider_car", st.session_state["periodo_master_car"])

    def _on_calendar_change():
        st.session_state["periodo_master_car"] = st.session_state["intervalo_data_car"]
        st.session_state["intervalo_slider_car"] = st.session_state["intervalo_data_car"]

    def _on_slider_change():
        st.session_state["periodo_master_car"] = st.session_state["intervalo_slider_car"]
        st.session_state["intervalo_data_car"] = st.session_state["intervalo_slider_car"]

    c0, c1, c2 = st.columns([0.50, 0.30, 0.20])
    with c0:
        sel_project = st.selectbox("Domain", options=projects, index=0)
    with c1:
        st.caption("")
    with c2:
        dt = read_last_update(KPI_LASTUPDATE)
        if dt: st.caption(f"Atualizado: {dt}")

    c0, c1, c2 = st.columns([0.50, 0.30, 0.20])
    with c0:
        ca, cb = st.columns(2)
        with ca:
            st.date_input(
                "Date (calendário)",
                key="intervalo_data_car",
                min_value=min_d, max_value=max_d,
                format="DD/MM/YYYY",
                on_change=_on_calendar_change,
            )
        with cb:
            st.slider(
                "Date (slider)",
                key="intervalo_slider_car",
                min_value=min_d, max_value=max_d,
                format="DD/MM/YYYY",
                on_change=_on_slider_change,
            )
    with c1:
        st.caption("")
    with c2:
        st.caption("")

    d_start, d_end = st.session_state["periodo_master_car"]

    # ---------------- Aplicar filtros (Domain + Período) ----------------
    def _f_proj(df: pd.DataFrame, col="projectKey") -> pd.DataFrame:
        if df.empty or sel_project == "Todos": return df
        if col in df.columns:
            return df[df[col].astype(str) == str(sel_project)].copy()
        return df
    
    def _f_period_created(df: pd.DataFrame) -> pd.DataFrame:
        """Filtra por período usando created_date, tolerando datetime64[ns] ou date."""
        if df.empty or "created_date" not in df.columns:
            return df
        s = df["created_date"]

        # Caso a coluna esteja como datetime64[ns] (ou com tz)
        if np.issubdtype(s.dtype, np.datetime64):
            start_ts = pd.to_datetime(d_start)   # date -> Timestamp
            end_ts   = pd.to_datetime(d_end)
            mask = s.between(start_ts, end_ts, inclusive="both")
            return df[mask].copy()

        # Caso esteja como objetos date/strings
        try:
            mask = (s >= d_start) & (s <= d_end)
            return df[mask].copy()
        except Exception:
            # último recurso: normaliza para date uma única vez
            s2 = pd.to_datetime(s, errors="coerce").dt.date
            df2 = df.copy()
            df2["created_date"] = s2
            mask = (s2 >= d_start) & (s2 <= d_end)
            return df2[mask].copy()
        
    def _f_period_exec(df: pd.DataFrame) -> pd.DataFrame:
        """Filtra por período usando executed_date, tolerando datetime64[ns] ou date."""
        if df.empty or "executed_date" not in df.columns:
            return df
        s = df["executed_date"]

        if np.issubdtype(s.dtype, np.datetime64):
            start_ts = pd.to_datetime(d_start)
            end_ts   = pd.to_datetime(d_end)
            mask = s.between(start_ts, end_ts, inclusive="both")
            return df[mask].copy()

        try:
            mask = (s >= d_start) & (s <= d_end)
            return df[mask].copy()
        except Exception:
            s2 = pd.to_datetime(s, errors="coerce").dt.date
            df2 = df.copy()
            df2["executed_date"] = s2
            mask = (s2 >= d_start) & (s2 <= d_end)
            return df2[mask].copy()


    f_story = _f_proj(_f_period_created(df_story))
    f_epic  = _f_proj(_f_period_created(df_epic))
    f_zc    = _f_proj(_f_period_created(df_zc))
    f_ze    = _f_proj(_f_period_exec(df_ze))

    # ---------------- Cards ----------------
    col1 = st.columns(4)
    with col1[0]:
        if not df_proj.empty:
            domains = len(df_proj if sel_project == "Todos" else df_proj[df_proj["key"].astype(str) == str(sel_project)])
        else:
            domains = len(set([*f_story["projectKey"].dropna().unique(), *f_epic["projectKey"].dropna().unique()]))
        st.metric("Domain", int(domains) if pd.notna(domains) else 0)

    with col1[1]:
        st.metric("QTD Story", int(f_story.shape[0]))

    with col1[2]:
        st.metric("QTD Epic", int(f_epic.shape[0]))

    with col1[3]:
        num = int(f_story.shape[0]); den = num + int(f_epic.shape[0])
        st.metric("% Story Coverage", f"{_pct(num, den):.2f}%")

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
        if not f_ze.empty and {"month","issueKey"}.issubset(f_ze.columns):
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
        st.metric("Test average per issue", f"{float(avg_issue):.2f}")

    st.markdown("---")

    # ---------------- Automated backlog ----------------
    st.markdown("#### Automated Backlog")
    if f_zc.empty:
        st.info("Sem dados de casos de teste (Zephyr Test Cases).")
    else:
        auto_mask = f_zc.get("automated", pd.Series(dtype="object")).astype(str).str.lower().isin(["1","true","yes"])
        n_auto = int(auto_mask.sum())
        n_total = int(len(f_zc))
        n_not_app = int((f_zc.get("status", pd.Series(dtype="object")).astype(str).str.contains("not applic", case=False)).sum())
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

    # ---------------- Regressive × Others ----------------
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

    # ---------------- Positive × Negative ----------------
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

    # ---------------- Automated run × Manual run ----------------
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

    # ---------------- Test evolution (linha mensal) ----------------
    st.markdown("#### Test evolution (mensal)")
    if f_ze.empty:
        st.info("Sem execuções no período selecionado.")
    else:
        z = f_ze.copy()
        z["is_auto"] = z.get("automated", pd.Series(dtype="object")).astype(str).str.lower().isin(["1","true","yes"])
        df_month = z.groupby(["month","is_auto"]).size().reset_index(name="runs")
        df_month["tipo"] = df_month["is_auto"].map({True:"Automated Run", False:"Manual Run"})
        try:
            df_month["month_dt"] = pd.to_datetime(df_month["month"] + "-01", errors="coerce")
            df_month = df_month.sort_values("month_dt")
        except Exception:
            pass
        ch = alt.Chart(df_month).mark_line(point=True).encode(
            x=alt.X("month:N", title="Mês"),
            y=alt.Y("runs:Q", title="Runs"),
            color=alt.Color("tipo:N", title=None)
        ).properties(height=300)
        st.altair_chart(ch, use_container_width=True)

    # ---------------- Automation in regressive ----------------
    st.markdown("#### Automation in regressive")
    if f_ze.empty or "testType" not in f_ze.columns:
        st.info("Sem dados suficientes para regressão.")
    else:
        z = f_ze.copy()
        reg = z["testType"].astype(str).str.lower().str.contains("regress")
        is_auto = z.get("automated", pd.Series(dtype="object")).astype(str).str.lower().isin(["1","true","yes"])
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
