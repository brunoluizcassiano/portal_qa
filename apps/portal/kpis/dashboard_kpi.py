import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

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

def pagina_dashboard_kpi():
    # set_page_config apenas uma vez
    try:
        st.set_page_config(page_title="Quality KPI's", layout="wide")
    except Exception:
        pass

    # CSS dos cards
    st.markdown("""
<style>
.stButton > button {
  height: 78px; width: 100%;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,.12);
  background: rgba(255,255,255,.04);
  white-space: pre-line; line-height: 1.05;
  padding: 8px 8px; text-align: center;
  font-size: 12px; font-weight: 700; min-width: 0;
}
.stButton > button:hover {
  border-color: rgba(186,85,211,.6);
  background: rgba(186,85,211,.10);
}
.kpi-selected button { outline: 2px solid #ba55d3 !important; background: rgba(186,85,211,.16) !important; border-color: transparent !important; }
.block-container { padding-left: 1rem; padding-right: 1rem; }
.kpi-below button  { outline: 2px solid #d9534f !important; background: rgba(217,83,79,.16) !important;  border-color: transparent !important; }
.kpi-near  button  { outline: 2px solid #f0ad4e !important; background: rgba(240,173,78,.16) !important; border-color: transparent !important; }
.kpi-ok    button  { outline: 2px solid #5cb85c !important; background: rgba(92,184,92,.16) !important;  border-color: transparent !important; }
</style>
""", unsafe_allow_html=True)

    st.markdown("### Quality KPI’s")

    # --- Carregamento (cacheado por mtime) ---
    df_func_raw = safe_read_csv(JIRA_FUNC)
    df_epic_raw = safe_read_csv(JIRA_EPIC)
    df_story_raw = safe_read_csv(JIRA_STORY)
    df_bug      = normalize_bugs(safe_read_csv(JIRA_BUG))
    df_subbug   = normalize_bugs(safe_read_csv(JIRA_SUBBUG))
    df_proj     = safe_read_csv(JIRA_PROJ)

    df_zc       = safe_read_csv(ZEPHYR_TC)
    df_ze       = ensure_project_on_executions(
                 safe_read_csv([ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK])
             )
    df_cyc      = safe_read_csv([ZEPHYR_CYCLE_MAIN, ZEPHYR_CYCLE_FALLBACK])

    df_targets  = safe_read_csv(KPI_TARGETS, columns=["kpi", "projectKey", "year", "target", "goal"])
    if not df_targets.empty:
        df_targets["kpi"] = df_targets["kpi"].astype(str)
        df_targets["projectKey"] = df_targets["projectKey"].astype(str)
        df_targets["year"] = pd.to_numeric(df_targets["year"], errors="coerce").astype("Int64")
        df_targets["target"] = pd.to_numeric(df_targets["target"], errors="coerce")
        df_targets["goal"] = df_targets["goal"].astype(str).str.lower()
    else:
        df_targets = pd.DataFrame(columns=["kpi", "projectKey", "year", "target", "goal"])

    # --- Normalizações
    df_func  = normalize_issue_df(df_func_raw)
    df_epic  = normalize_issue_df(df_epic_raw)
    df_story = normalize_issue_df(df_story_raw)

    if not df_ze.empty:
        df_ze = ensure_project_on_executions(df_ze)

    tc_issue_ids  = extract_linked_issue_ids(df_zc, ("links.issues.issueId",))
    cyc_issue_ids = extract_linked_issue_ids(df_cyc, ("links.issues.issueId",))
    linked_issue_ids = tc_issue_ids | cyc_issue_ids

    # --- Projetos para filtro
    if not df_proj.empty and {"name", "key"}.issubset(df_proj.columns):
        projects_tuples = [(row["name"], row["key"]) for _, row in df_proj.iterrows() if pd.notna(row["name"]) and pd.notna(row["key"])]
        project_names = [name for name, _ in projects_tuples]
        name_to_key = {name: key for name, key in projects_tuples}
    else:
        pref = pd.concat([df_func["projectKey"], df_epic["projectKey"], df_story["projectKey"]], ignore_index=True)
        project_names = sorted([p for p in pref.dropna().unique().tolist() if p])
        name_to_key = {p: p for p in project_names}

    # --- Anos disponíveis
    all_years = extract_years_from_dfs([df_func_raw, df_epic_raw, df_story_raw, df_bug, df_subbug, df_ze, df_zc, df_cyc])
    year_options = ["Todos"] + [str(y) for y in all_years]

    c1, c2, c3 = st.columns([0.35, 0.3, 0.35])
    with c1:
        sel_project_name = st.selectbox("Tribo (Projeto)", options=["Todos"] + project_names, index=0)
    with c2:
        sel_year = st.selectbox("Ano", options=year_options, index=0)
    with c3:
        dt = read_last_update(KPI_LASTUPDATE)
        if dt: st.caption(f"Atualizado: {dt}")

    c1, _, _ = st.columns([0.35, 0.3, 0.35])
    with c1:
        st.caption("Clique em um card abaixo para trocar o gráfico do KPI.")

    # --- Filtros de projeto/ano
    def project_key_selected():
        return name_to_key.get(sel_project_name, sel_project_name)

    # Issues (projeto + ano)
    def apply_project_issues(df):
        if df.empty or sel_project_name == "Todos":
            return apply_year_filter(df, sel_year)
        pk = project_key_selected()
        return apply_year_filter(df[df["projectKey"] == pk].copy(), sel_year)

    df_func_f  = apply_project_issues(df_func)
    df_epic_f  = apply_project_issues(df_epic)
    df_story_f = apply_project_issues(df_story)

    df_bug_f    = apply_year_filter(apply_project_bugs(df_bug, project_key_selected()), sel_year)
    df_subbug_f = apply_year_filter(apply_project_bugs(df_subbug, project_key_selected()), sel_year)

    # Execuções (projeto + ano)
    def executions_filtered_by_project(df_ze_in: pd.DataFrame) -> pd.DataFrame:
        if df_ze_in.empty or sel_project_name == "Todos":
            return apply_year_filter(df_ze_in, sel_year)
        pk = project_key_selected()
        if "projectKey" not in df_ze_in.columns:
            return df_ze_in[[]]
        return apply_year_filter(df_ze_in[df_ze_in["projectKey"].astype(str) == str(pk)].copy(), sel_year)

    df_ze_f = executions_filtered_by_project(df_ze)

    # Conjunto de issues do projeto/ano
    base_issues_sel = pd.concat([df_func_f, df_story_f, df_epic_f], ignore_index=True)
    issue_ids_sel = set(int(x) for x in base_issues_sel["id"].dropna().astype(int).tolist())

    # ---------- KPIs (atuais) ----------
    kpi_coverage = kpi_coverage_now(base_issues_sel, linked_issue_ids)
    kpi_test_avg = kpi_test_avg_per_issue_now(base_issues_sel, df_zc)
    kpi_auto_runs = kpi_auto_runs_now(df_ze_f)
    kpi_auto_reg  = kpi_auto_reg_now(df_zc, df_ze_f, issue_ids_sel)
    kpi_test_reg  = kpi_test_reg_now(df_zc, issue_ids_sel)
    kpi_negative  = kpi_negative_now(df_zc, issue_ids_sel)
    kpi_bug_days_ = avg_bug_days(df_bug_f, df_subbug_f)

    # ---------- Targets/visual ----------
    def resolve_project_for_target():
        return "*" if sel_project_name == "Todos" else project_key_selected()

    def _format_delta(kpi_key: str, val: float, as_pct: bool) -> str:
        tgt, _goal = get_target(df_targets, resolve_project_for_target(), kpi_key, None if sel_year == "Todos" else int(sel_year))
        if tgt is None:
            return ""
        delta = float(val) - float(tgt)
        return f"\nΔ {delta:+.2f}{'pp' if as_pct else ''}"

    def _fmt_with_target(kpi_key: str, val: float, as_pct: bool) -> str:
        tgt, goal = get_target(df_targets, resolve_project_for_target(), kpi_key, None if sel_year == "Todos" else int(sel_year))
        v = f"{val:.2f}%" if as_pct else f"{val:.2f}"
        if tgt is None:
            return v
        tgt_s = f"{tgt:.0f}%" if as_pct else f"{tgt:.2f}"
        arrow = "↑" if (goal or "max") == "max" else "↓"
        return f"{v}\nTarget {arrow} {tgt_s}{_format_delta(kpi_key, val, as_pct)}"

    def _kpi_state_class(kpi_key: str, val: float, as_pct: bool) -> str:
        tgt, goal = get_target(df_targets, resolve_project_for_target(), kpi_key, None if sel_year == "Todos" else int(sel_year))
        if tgt is None:
            return ""
        goal = (goal or "max").lower()
        band = abs(tgt) * WARN_RATIO
        if goal == "max":
            if val < (tgt - band): return "kpi-below"
            elif val < tgt:        return "kpi-near"
            else:                  return "kpi-ok"
        else:
            if val > (tgt + band): return "kpi-below"
            elif val > tgt:        return "kpi-near"
            else:                  return "kpi-ok"

    KPI_DEFS = {
        "coverage":  {"title": "% Total Coverage",       "value": _fmt_with_target("coverage",  kpi_coverage, True)},
        "test_avg":  {"title": "Test AVG per issue",     "value": _fmt_with_target("test_avg",  kpi_test_avg, False)},
        "auto_reg":  {"title": "% Automated Regression", "value": _fmt_with_target("auto_reg",  kpi_auto_reg, True)},
        "auto_runs": {"title": "% Automated Runs",       "value": _fmt_with_target("auto_runs", kpi_auto_runs, True)},
        "test_reg":  {"title": "% Test Regression",      "value": _fmt_with_target("test_reg",  kpi_test_reg, True)},
        "negative":  {"title": "% Negative Test",        "value": _fmt_with_target("negative",  kpi_negative, True)},
        "bug_days":  {"title": "AVG days resolution Bug","value": _fmt_with_target("bug_days",  kpi_bug_days_, False)},
    }
    KPI_CLASS = {
        "coverage":  _kpi_state_class("coverage",  kpi_coverage, True),
        "test_avg":  _kpi_state_class("test_avg",  kpi_test_avg, False),
        "auto_reg":  _kpi_state_class("auto_reg",  kpi_auto_reg, True),
        "auto_runs": _kpi_state_class("auto_runs", kpi_auto_runs, True),
        "test_reg":  _kpi_state_class("test_reg",  kpi_test_reg, True),
        "negative":  _kpi_state_class("negative",  kpi_negative, True),
        "bug_days":  _kpi_state_class("bug_days",  kpi_bug_days_, False),
    }

    if "kpi_selected" not in st.session_state:
        st.session_state["kpi_selected"] = "coverage"

    # ---------- Cards ----------
    def kpi_button(col, key, label, value, btn_key, extra_cls=""):
        selected = (st.session_state["kpi_selected"] == key)
        klass = " ".join(cls for cls in ["kpi-selected" if selected else "", extra_cls] if cls)
        with col.container():
            st.write(f'<div class="{klass}">', unsafe_allow_html=True)
            clicked = st.button(f"{label}\n{value}", key=btn_key, use_container_width=True)
            st.write("</div>", unsafe_allow_html=True)
        if clicked:
            st.session_state["kpi_selected"] = key

    cols = st.columns(7)
    kpi_button(cols[0], "coverage",  KPI_DEFS["coverage"]["title"],  KPI_DEFS["coverage"]["value"],  "btn_cov",  KPI_CLASS["coverage"])
    kpi_button(cols[1], "test_avg",  KPI_DEFS["test_avg"]["title"],  KPI_DEFS["test_avg"]["value"],  "btn_tavg", KPI_CLASS["test_avg"])
    kpi_button(cols[2], "auto_reg",  KPI_DEFS["auto_reg"]["title"],  KPI_DEFS["auto_reg"]["value"],  "btn_areg", KPI_CLASS["auto_reg"])
    kpi_button(cols[3], "auto_runs", KPI_DEFS["auto_runs"]["title"], KPI_DEFS["auto_runs"]["value"], "btn_aruns",KPI_CLASS["auto_runs"])
    kpi_button(cols[4], "test_reg",  KPI_DEFS["test_reg"]["title"],  KPI_DEFS["test_reg"]["value"],  "btn_treg", KPI_CLASS["test_reg"])
    kpi_button(cols[5], "negative",  KPI_DEFS["negative"]["title"],  KPI_DEFS["negative"]["value"],  "btn_neg",  KPI_CLASS["negative"])
    kpi_button(cols[6], "bug_days",  KPI_DEFS["bug_days"]["title"],  KPI_DEFS["bug_days"]["value"],  "btn_bug",  KPI_CLASS["bug_days"])

    st.markdown("---")

    # ---------- Série mensal para o KPI selecionado ----------
    df_func_all = df_func_f.copy()
    df_epic_all = df_epic_f.copy()
    df_story_all = df_story_f.copy()
    base_issues_all = pd.concat([df_func_all, df_story_all, df_epic_all], ignore_index=True)

    sel_key = st.session_state["kpi_selected"]
    st.markdown(f"#### {KPI_DEFS[sel_key]['title']}")

    if sel_key == "coverage":
        df_series = monthly_series_coverage(base_issues_all, linked_issue_ids)
    elif sel_key == "test_avg":
        df_series = monthly_series_test_avg(base_issues_all, df_zc)
    elif sel_key == "auto_runs":
        df_series = monthly_series_auto_runs(df_ze_f)
    elif sel_key == "auto_reg":
        df_series = monthly_series_auto_reg(df_zc, df_ze_f, issue_ids_sel)
    elif sel_key == "test_reg":
        df_series = monthly_series_test_reg(df_zc, issue_ids_sel)
    elif sel_key == "negative":
        df_series = monthly_series_negative(df_zc, issue_ids_sel)
    else:  # bug_days não tem série
        df_series = pd.DataFrame(columns=["month", "value"])

    if df_series.empty:
        st.info("Sem dados suficientes para este KPI com os filtros atuais.")
        return

    try:
        df_series["month_dt"] = pd.to_datetime(df_series["month"] + "-01", errors="coerce")
        df_series = df_series.sort_values("month_dt")
    except Exception:
        pass

    y_title = "%" if sel_key in {"coverage", "auto_reg", "auto_runs", "test_reg", "negative"} else "Valor"
    chart = (
        alt.Chart(df_series)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:N", title="Mês"),
            y=alt.Y("value:Q", title=y_title),
            tooltip=["month:N", "value:Q"],
        )
        .properties(height=340, width="container")
    )
    st.altair_chart(chart, use_container_width=True)

# debug local
if __name__ == "__main__":
    pagina_dashboard_kpi()
