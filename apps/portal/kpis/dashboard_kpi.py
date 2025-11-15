# apps/portal/kpis/dashboard_kpi.py

import streamlit as st
import pandas as pd
import altair as alt

from .analytics.constants import (
    WARN_RATIO, KPI_LASTUPDATE,
    JIRA_FUNC, JIRA_EPIC, JIRA_STORY, JIRA_BUG, JIRA_SUBBUG, JIRA_PROJ,
    ZEPHYR_TC, ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK,
    ZEPHYR_CYCLE_MAIN, ZEPHYR_CYCLE_FALLBACK,
    KPI_TARGETS
)
from .analytics.data_access import safe_read_csv, read_last_update
from .analytics.transformers import (
    normalize_issue_df,
    normalize_bugs,
    extract_linked_issue_ids,
    extract_years_from_dfs,
    apply_year_filter,
    ensure_project_on_executions,
    apply_project_bugs,
)
from .analytics.metrics import (
    get_target,
    kpi_test_avg_per_issue_now,
    kpi_auto_runs_now,
    kpi_auto_reg_now,
    kpi_test_reg_now,
    kpi_negative_now,
    avg_bug_days,
    monthly_series_coverage,
    monthly_series_test_avg,
    monthly_series_auto_runs,
    monthly_series_auto_reg,
    monthly_series_test_reg,
    monthly_series_negative,
)


# ---------- Helpers internos ----------

def _safe_issue_ids(df: pd.DataFrame) -> set:
    """Extrai os IDs numéricos de issue (coluna 'id') como set."""
    if df is None or df.empty or "id" not in df.columns:
        return set()
    s = pd.to_numeric(df["id"], errors="coerce").dropna().astype("Int64")
    return set(s.tolist())


def _compute_total_coverage(df_story_f: pd.DataFrame,
                            df_epic_f: pd.DataFrame,
                            df_func_f: pd.DataFrame,
                            df_zc_f: pd.DataFrame) -> float:
    """
    % Total Coverage:
      - Base = Story + Epic + Func filtradas (tribo + ano)
      - Coberta = issue que aparece em pelo menos 1 Test Case (coverage)
    """

    # 1) Conjunto de todas as issues (Story + Epic + Func)
    story_ids = _safe_issue_ids(df_story_f)
    epic_ids  = _safe_issue_ids(df_epic_f)
    func_ids  = _safe_issue_ids(df_func_f)

    all_issue_ids = story_ids | epic_ids | func_ids
    denom = len(all_issue_ids)
    if denom == 0:
        return 0.0

    # 2) Issues cobertas = IDs que aparecem nos Test Cases filtrados
    #    Usamos o helper padrão para extrair campos tipo "links.issues.issueId"
    covered_ids = extract_linked_issue_ids(
        df_zc_f,
        (
            "links.issues.issueId",
            "links.issues.issue id",
            "links.issues.issue idnbsp",
        ),
    )

    # Interseção: só conta como coberta se estiver na base total
    covered_total_ids = all_issue_ids & covered_ids
    num_cov = len(covered_total_ids)

    return (num_cov / denom) * 100.0


def pagina_dashboard_kpi():
    # Evita erro de múltiplas chamadas no Streamlit
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
.kpi-selected button {
  outline: 2px solid #ba55d3 !important;
  background: rgba(186,85,211,.16) !important;
  border-color: transparent !important;
}
.kpi-below button  {
  outline: 2px solid #d9534f !important;
  background: rgba(217,83,79,.16) !important;
  border-color: transparent !important;
}
.kpi-near  button  {
  outline: 2px solid #f0ad4e !important;
  background: rgba(240,173,78,.16) !important;
  border-color: transparent !important;
}
.kpi-ok    button  {
  outline: 2px solid #5cb85c !important;
  background: rgba(92,184,92,.16) !important;
  border-color: transparent !important;
}
.block-container { padding-left: 1rem; padding-right: 1rem; }
</style>
""", unsafe_allow_html=True)

    st.markdown("### Quality KPI’s")

    # ---------- Carregamento de dados ----------
    df_func_raw = safe_read_csv(JIRA_FUNC)
    df_epic_raw = safe_read_csv(JIRA_EPIC)
    df_story_raw = safe_read_csv(JIRA_STORY)
    df_bug_raw   = safe_read_csv(JIRA_BUG)
    df_subbug_raw = safe_read_csv(JIRA_SUBBUG)
    df_proj      = safe_read_csv(JIRA_PROJ)

    df_zc_raw    = safe_read_csv(ZEPHYR_TC)
    df_ze_raw    = safe_read_csv([ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK])
    df_cyc_raw   = safe_read_csv([ZEPHYR_CYCLE_MAIN, ZEPHYR_CYCLE_FALLBACK])

    df_targets   = safe_read_csv(KPI_TARGETS, columns=["kpi", "projectKey", "year", "target", "goal"])
    if not df_targets.empty:
        df_targets["kpi"]        = df_targets["kpi"].astype(str)
        df_targets["projectKey"] = df_targets["projectKey"].astype(str)
        df_targets["year"]       = pd.to_numeric(df_targets["year"], errors="coerce").astype("Int64")
        df_targets["target"]     = pd.to_numeric(df_targets["target"], errors="coerce")
        df_targets["goal"]       = df_targets["goal"].astype(str).str.lower()
    else:
        df_targets = pd.DataFrame(columns=["kpi", "projectKey", "year", "target", "goal"])

    # Normalizações
    df_func  = normalize_issue_df(df_func_raw)
    df_epic  = normalize_issue_df(df_epic_raw)
    df_story = normalize_issue_df(df_story_raw)

    df_bug    = normalize_bugs(df_bug_raw)
    df_subbug = normalize_bugs(df_subbug_raw)

    df_ze = ensure_project_on_executions(df_ze_raw) if not df_ze_raw.empty else df_ze_raw

    # ---------- Projetos (Tribo) ----------
    if not df_proj.empty and {"name", "key"}.issubset(df_proj.columns):
        projects_tuples = [
            (row["name"], row["key"])
            for _, row in df_proj.iterrows()
            if pd.notna(row["name"]) and pd.notna(row["key"])
        ]
        project_names = [name for name, _ in projects_tuples]
        name_to_key = {name: key for name, key in projects_tuples}
    else:
        pref = pd.concat(
            [
                df_func.get("projectKey", pd.Series(dtype=str)),
                df_epic.get("projectKey", pd.Series(dtype=str)),
                df_story.get("projectKey", pd.Series(dtype=str)),
            ],
            ignore_index=True,
        )
        project_names = sorted([p for p in pref.dropna().unique().tolist() if p])
        name_to_key = {p: p for p in project_names}

    # ---------- Anos disponíveis (Story/Epic/Func) ----------
    all_years = extract_years_from_dfs([df_func_raw, df_epic_raw, df_story_raw])
    year_options = ["Todos"] + [str(y) for y in all_years]

    # ---------- Filtros de topo ----------
    c1, c2, c3 = st.columns([0.35, 0.3, 0.35])
    with c1:
        sel_project_name = st.selectbox(
            "Tribo (Projeto)",
            options=["Todos"] + project_names,
            index=0,
        )
    with c2:
        sel_year = st.selectbox("Ano (criação da issue)", options=year_options, index=0)
    with c3:
        dt = read_last_update(KPI_LASTUPDATE)
        if dt:
            st.caption(f"Atualizado: {dt}")

    c1, _, _ = st.columns([0.35, 0.3, 0.35])
    with c1:
        st.caption("Clique em um card abaixo para trocar o gráfico do KPI.")

    # ---------- Helpers de filtro ----------
    def project_key_selected() -> str:
        return name_to_key.get(sel_project_name, sel_project_name)

    def apply_project_issues(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        if sel_project_name != "Todos":
            pk = project_key_selected()
            if "projectKey" in df.columns:
                df = df[df["projectKey"].astype(str) == str(pk)].copy()
        return df

    def apply_project_testcases(df: pd.DataFrame) -> pd.DataFrame:
        """Filtra test cases por tribo (coluna de projeto) se existir."""
        if df.empty:
            return df
        if sel_project_name != "Todos":
            pk = project_key_selected()
            # tenta achar coluna de projeto
            candidates = ["projectKey", "project key", "project.key", "project"]
            cols_norm = {str(c).strip().lower(): c for c in df.columns}
            col_proj = None
            for cand in candidates:
                if cand.lower() in cols_norm:
                    col_proj = cols_norm[cand.lower()]
                    break
            if col_proj:
                df = df[df[col_proj].astype(str).str.upper() == str(pk).upper()].copy()
        return df

    # Issues (projeto + ano)
    df_func_f  = apply_year_filter(apply_project_issues(df_func), sel_year)
    df_epic_f  = apply_year_filter(apply_project_issues(df_epic), sel_year)
    df_story_f = apply_year_filter(apply_project_issues(df_story), sel_year)

    # Bugs/Sub-bugs (projeto + ano)
    df_bug_f    = apply_year_filter(apply_project_bugs(df_bug, project_key_selected()), sel_year)
    df_subbug_f = apply_year_filter(apply_project_bugs(df_subbug, project_key_selected()), sel_year)

    # Execuções (projeto + ano)
    def executions_filtered_by_project(df_ze_in: pd.DataFrame) -> pd.DataFrame:
        if df_ze_in.empty:
            return df_ze_in
        if sel_project_name != "Todos":
            pk = project_key_selected()
            if "projectKey" in df_ze_in.columns:
                df_ze_in = df_ze_in[df_ze_in["projectKey"].astype(str) == str(pk)].copy()
        return apply_year_filter(df_ze_in, sel_year)

    df_ze_f = executions_filtered_by_project(df_ze)

    # Test Cases (projeto + ano) – importante para o % Total Coverage
    df_zc_f = apply_year_filter(apply_project_testcases(df_zc_raw), sel_year)

    # Base de issues combinada
    base_issues_sel = pd.concat(
        [df_func_f, df_story_f, df_epic_f],
        ignore_index=True,
    )

    issue_ids_sel = _safe_issue_ids(base_issues_sel)

    # ---------- KPIs de nível atual ----------
    # Aqui usamos o novo cálculo de % Total Coverage
    kpi_coverage = _compute_total_coverage(df_story_f, df_epic_f, df_func_f, df_zc_f)

    kpi_test_avg = kpi_test_avg_per_issue_now(base_issues_sel, df_zc_f)
    kpi_auto_runs_val = kpi_auto_runs_now(df_ze_f)
    kpi_auto_reg_val  = kpi_auto_reg_now(df_zc_f, df_ze_f, issue_ids_sel)
    kpi_test_reg_val  = kpi_test_reg_now(df_zc_f, issue_ids_sel)
    kpi_negative_val  = kpi_negative_now(df_zc_f, issue_ids_sel)
    kpi_bug_days_val  = avg_bug_days(df_bug_f, df_subbug_f)

    # ---------- Targets / cores ----------
    def resolve_project_for_target():
        return "*" if sel_project_name == "Todos" else project_key_selected()

    def _format_delta(kpi_key: str, val: float, as_pct: bool) -> str:
        tgt, _goal = get_target(
            df_targets,
            resolve_project_for_target(),
            kpi_key,
            None if sel_year == "Todos" else int(sel_year),
        )
        if tgt is None:
            return ""
        delta = float(val) - float(tgt)
        return f"\nΔ {delta:+.2f}{'pp' if as_pct else ''}"

    def _fmt_with_target(kpi_key: str, val: float, as_pct: bool) -> str:
        tgt, goal = get_target(
            df_targets,
            resolve_project_for_target(),
            kpi_key,
            None if sel_year == "Todos" else int(sel_year),
        )
        v = f"{val:.2f}%" if as_pct else f"{val:.2f}"
        if tgt is None:
            return v
        tgt_s = f"{tgt:.0f}%" if as_pct else f"{tgt:.2f}"
        arrow = "↑" if (goal or "max") == "max" else "↓"
        return f"{v}\nTarget {arrow} {tgt_s}{_format_delta(kpi_key, val, as_pct)}"

    def _kpi_state_class(kpi_key: str, val: float, as_pct: bool) -> str:
        tgt, goal = get_target(
            df_targets,
            resolve_project_for_target(),
            kpi_key,
            None if sel_year == "Todos" else int(sel_year),
        )
        if tgt is None:
            return ""
        goal = (goal or "max").lower()
        band = abs(tgt) * WARN_RATIO
        if goal == "max":
            if val < (tgt - band):
                return "kpi-below"
            elif val < tgt:
                return "kpi-near"
            else:
                return "kpi-ok"
        else:
            if val > (tgt + band):
                return "kpi-below"
            elif val > tgt:
                return "kpi-near"
            else:
                return "kpi-ok"

    KPI_DEFS = {
        "coverage": {
            "title": "% Total Coverage",
            "value": _fmt_with_target("coverage", kpi_coverage, True),
        },
        "test_avg": {
            "title": "Test AVG per issue",
            "value": _fmt_with_target("test_avg", kpi_test_avg, False),
        },
        "auto_reg": {
            "title": "% Automated Regression",
            "value": _fmt_with_target("auto_reg", kpi_auto_reg_val, True),
        },
        "auto_runs": {
            "title": "% Automated Runs",
            "value": _fmt_with_target("auto_runs", kpi_auto_runs_val, True),
        },
        "test_reg": {
            "title": "% Test Regression",
            "value": _fmt_with_target("test_reg", kpi_test_reg_val, True),
        },
        "negative": {
            "title": "% Negative Test",
            "value": _fmt_with_target("negative", kpi_negative_val, True),
        },
        "bug_days": {
            "title": "AVG days resolution Bug",
            "value": _fmt_with_target("bug_days", kpi_bug_days_val, False),
        },
    }

    KPI_CLASS = {
        "coverage":  _kpi_state_class("coverage",  kpi_coverage, True),
        "test_avg":  _kpi_state_class("test_avg",  kpi_test_avg, False),
        "auto_reg":  _kpi_state_class("auto_reg",  kpi_auto_reg_val, True),
        "auto_runs": _kpi_state_class("auto_runs", kpi_auto_runs_val, True),
        "test_reg":  _kpi_state_class("test_reg",  kpi_test_reg_val, True),
        "negative":  _kpi_state_class("negative",  kpi_negative_val, True),
        "bug_days":  _kpi_state_class("bug_days",  kpi_bug_days_val, False),
    }

    if "kpi_selected" not in st.session_state:
        st.session_state["kpi_selected"] = "coverage"

    # ---------- Cards de KPI ----------
    def kpi_button(col, key, label, value, btn_key, extra_cls=""):
        selected = (st.session_state["kpi_selected"] == key)
        klass = " ".join(
            cls for cls in ["kpi-selected" if selected else "", extra_cls] if cls
        )
        with col.container():
            st.write(f'<div class="{klass}">', unsafe_allow_html=True)
            clicked = st.button(
                f"{label}\n{value}",
                key=btn_key,
                use_container_width=True,
            )
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

    # ---------- Série mensal do KPI selecionado ----------
    sel_key = st.session_state["kpi_selected"]
    st.markdown(f"#### {KPI_DEFS[sel_key]['title']}")

    # Para as séries mensais, mantemos as funções do módulo metrics
    if sel_key == "coverage":
        df_series = monthly_series_coverage(base_issues_sel, extract_linked_issue_ids(df_zc_f, (
            "links.issues.issueId",
            "links.issues.issue id",
            "links.issues.issue idnbsp",
        )))
    elif sel_key == "test_avg":
        df_series = monthly_series_test_avg(base_issues_sel, df_zc_f)
    elif sel_key == "auto_runs":
        df_series = monthly_series_auto_runs(df_ze_f)
    elif sel_key == "auto_reg":
        df_series = monthly_series_auto_reg(df_zc_f, df_ze_f, issue_ids_sel)
    elif sel_key == "test_reg":
        df_series = monthly_series_test_reg(df_zc_f, issue_ids_sel)
    elif sel_key == "negative":
        df_series = monthly_series_negative(df_zc_f, issue_ids_sel)
    else:  # bug_days não tem série mensal aqui
        df_series = pd.DataFrame(columns=["month", "value"])

    if df_series.empty:
        st.info("Sem dados suficientes para este KPI com os filtros atuais.")
        return

    try:
        df_series["month_dt"] = pd.to_datetime(
            df_series["month"] + "-01",
            errors="coerce",
        )
        df_series = df_series.sort_values("month_dt")
    except Exception:
        pass

    y_title = "%"
    if sel_key == "test_avg":
        y_title = "Tests / Issue"
    if sel_key == "bug_days":
        y_title = "Dias"

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


# Execução direta local (debug)
if __name__ == "__main__":
    pagina_dashboard_kpi()
