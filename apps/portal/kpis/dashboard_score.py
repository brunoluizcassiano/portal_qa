# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import numpy as np
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
# Tabela de limiares → nota base (1–4) conforme sua imagem
#   1) % Total Coverage:     4: >=100 | 3: >=90 | 2: >=70 | 1: <70
#   2) # Test Avg Per Issue: 4: >10   | 3: >=6  | 2: >=3  | 1: <3
#   3) % Created Automations:4: >=80  | 3: >=70 | 2: >=60 | 1: <60
#   4) % Automated Run:      4: >=80  | 3: >=70 | 2: >=50 | 1: <50
#   5) % Regression Test:    4: >=50  | 3: >=35 | 2: >=25 | 1: <20
#   6) % Negative Test:      4: >=20  | 3: >=15 | 2: >=10 | 1: <5
#   7) # AVG days bug:       4: <=2d  | 3: <=3d | 2: <=5d | 1: >5
# Ponderação: coverage=15, test_avg=15, created=15, auto_runs=15, test_reg=20, negative=10, bug_days=10
# --------------------------------------------------------------------
WEIGHTS = {
    "coverage": 15,
    "test_avg": 15,
    "created":  15,
    "auto_runs":15,
    "test_reg": 20,
    "negative": 10,
    "bug_days": 10,
}

def _pct(a, b):
    return (float(a) / float(b) * 100.0) if (b not in (0, None, np.nan)) else 0.0

def _score_higher_better(v: float, t4: float, t3: float, t2: float, strict_gt4: bool = False) -> int:
    """retorna 4/3/2/1 para métricas de 'quanto maior, melhor'."""
    if v is None or (isinstance(v, float) and np.isnan(v)): return 1
    x = float(v)
    if strict_gt4:
        if x >  t4: return 4
    else:
        if x >= t4: return 4
    if x >= t3: return 3
    if x >= t2: return 2
    return 1

def _score_lower_better(v: float, t4_max: float, t3_max: float, t2_max: float) -> int:
    """retorna 4/3/2/1 para métricas de 'quanto menor, melhor'."""
    if v is None or (isinstance(v, float) and np.isnan(v)): return 1
    x = float(v)
    if x <= t4_max: return 4
    if x <= t3_max: return 3
    if x <= t2_max: return 2
    return 1

# Mapeamentos dos indicadores → nota base (1–4)
def score_coverage(coverage_pct: float) -> int:
    return _score_higher_better(coverage_pct, t4=100.0, t3=90.0, t2=70.0)

def score_test_avg(test_avg: float) -> int:
    # nota 4 exige >10 (estrita)
    return _score_higher_better(test_avg, t4=10.0, t3=6.0, t2=3.0, strict_gt4=True)

def score_created_auto(created_pct: float) -> int:
    return _score_higher_better(created_pct, t4=80.0, t3=70.0, t2=60.0)

def score_auto_runs(auto_runs_pct: float) -> int:
    return _score_higher_better(auto_runs_pct, t4=80.0, t3=70.0, t2=50.0)

def score_test_reg(reg_pct: float) -> int:
    return _score_higher_better(reg_pct, t4=50.0, t3=35.0, t2=25.0)

def score_negative(neg_pct: float) -> int:
    return _score_higher_better(neg_pct, t4=20.0, t3=15.0, t2=10.0)

def score_bug_days(days_avg: float) -> int:
    return _score_lower_better(days_avg, t4_max=2.0, t3_max=3.0, t2_max=5.0)

# --------------------------------------------------------------------
# Página
# --------------------------------------------------------------------
def pagina_dashboard_score():
    try:
        st.set_page_config(page_title="Quality Score", layout="wide")
    except Exception:
        pass

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
    .score-selected button { outline: 2px solid #ba55d3 !important; background: rgba(186,85,211,.16) !important; border-color: transparent !important; }
    .block-container { padding-left: 1rem; padding-right: 1rem; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### Quality Score")

    # ---------------- Carregamento normalizado (com cache por mtime) ----------------
    df_func_raw   = safe_read_csv(JIRA_FUNC)
    df_epic_raw   = safe_read_csv(JIRA_EPIC)
    df_story_raw  = safe_read_csv(JIRA_STORY)
    df_bug        = normalize_bugs(safe_read_csv(JIRA_BUG))
    df_subbug     = normalize_bugs(safe_read_csv(JIRA_SUBBUG))
    df_proj       = safe_read_csv(JIRA_PROJ)

    df_zc         = safe_read_csv(ZEPHYR_TC)  # test cases (Created Automations)
    df_ze         = ensure_project_on_executions(
                        safe_read_csv([ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK])
                    )  # execuções (month/year/projectKey)

    # normaliza issues (id, key, projectKey, month, year)
    df_func   = normalize_issue_df(df_func_raw)
    df_epic   = normalize_issue_df(df_epic_raw)
    df_story  = normalize_issue_df(df_story_raw)

    # zc: garantir projectKey e month/year (se houver "created")
    if not df_zc.empty:
        if "projectKey" not in df_zc.columns:
            if "key" in df_zc.columns:
                df_zc["projectKey"] = df_zc["key"].astype(str).str.extract(r"^([A-Z0-9_]+)-", expand=False).fillna("")
            else:
                df_zc["projectKey"] = ""
        if "created" in df_zc.columns:
            cdt = pd.to_datetime(df_zc["created"], errors="coerce", utc=True)
            df_zc["month"] = cdt.dt.strftime("%Y-%m")
            df_zc["year"]  = cdt.dt.year.astype("Int64")
        else:
            df_zc["month"] = pd.NA
            df_zc["year"]  = pd.NA
        df_zc["projectKey"] = df_zc["projectKey"].astype("category")

    # ---------------- Filtros topo (Projeto/Ano + Atualizado) ----------------
    # projetos
    if not df_proj.empty and {"name", "key"}.issubset(df_proj.columns):
        projects = [k for k in df_proj["key"].dropna().astype(str).unique().tolist() if k]
    else:
        pref = pd.concat(
            [
                s for s in [
                    df_func["projectKey"], df_epic["projectKey"], df_story["projectKey"],
                    df_bug.get("projectKey", pd.Series(dtype="object")),
                    df_subbug.get("projectKey", pd.Series(dtype="object")),
                    df_ze.get("projectKey", pd.Series(dtype="object")),
                    df_zc.get("projectKey", pd.Series(dtype="object")),
                ] if not s.empty
            ],
            ignore_index=True
        )
        projects = sorted([p for p in pref.dropna().astype(str).unique().tolist() if p])

    # anos
    all_years = extract_years_from_dfs([df_func, df_epic, df_story, df_bug, df_subbug, df_ze, df_zc])
    year_options = ["Todos"] + [str(y) for y in all_years]

    c1, c2, c3 = st.columns([0.35, 0.3, 0.35])
    with c1:
        sel_project = st.selectbox("Tribo (Projeto)", options=["Todos"] + projects, index=0)
    with c2:
        sel_year = st.selectbox("Ano", options=year_options, index=0)
    with c3:
        dt = read_last_update(KPI_LASTUPDATE)
        if dt: st.caption(f"Atualizado: {dt}")

    c1, _, _ = st.columns([0.35, 0.3, 0.35])
    with c1:
        st.caption("Clique em um card para alternar o gráfico.")

    # ---------------- Aplicar filtros (Projeto + Ano) ----------------
    def _apply_project(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or sel_project == "Todos": return apply_year_filter(df, sel_year)
        if "projectKey" in df.columns:
            df2 = df[df["projectKey"].astype(str) == str(sel_project)].copy()
            return apply_year_filter(df2, sel_year)
        return apply_year_filter(df, sel_year)

    df_func_f   = _apply_project(df_func)
    df_epic_f   = _apply_project(df_epic)
    df_story_f  = _apply_project(df_story)
    df_bug_f    = _apply_project(df_bug)
    df_subbug_f = _apply_project(df_subbug)
    df_zc_f     = _apply_project(df_zc) if not df_zc.empty else df_zc
    df_ze_f     = _apply_project(df_ze) if not df_ze.empty else df_ze

    # ---------------- Métricas brutas ----------------
    cov_num = len(df_func_f) + len(df_story_f)
    cov_den = cov_num + len(df_epic_f)
    coverage_pct = _pct(cov_num, cov_den)

    if not df_ze_f.empty and "issueKey" in df_ze_f.columns:
        by_issue = df_ze_f.dropna(subset=["issueKey"]).groupby("issueKey").size()
        test_avg = float(by_issue.mean()) if not by_issue.empty else 0.0
    else:
        test_avg = 0.0

    if not df_zc_f.empty and "automated" in df_zc_f.columns:
        created_auto = df_zc_f["automated"].astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
    else:
        created_auto = 0.0

    if not df_ze_f.empty and "automated" in df_ze_f.columns:
        auto_runs = df_ze_f["automated"].astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
    else:
        auto_runs = 0.0

    if not df_ze_f.empty and "testType" in df_ze_f.columns:
        test_reg = (df_ze_f["testType"].astype(str).str.lower().str.contains("regress").mean()) * 100.0
    else:
        test_reg = 0.0

    if not df_ze_f.empty:
        neg = pd.Series(False, index=df_ze_f.index)
        if "testType" in df_ze_f.columns:
            neg |= df_ze_f["testType"].astype(str).str.lower().str.contains("negative|negativo")
        if "labels" in df_ze_f.columns:
            neg |= df_ze_f["labels"].astype(str).str.lower().str.contains("negative|negativo")
        negative = neg.mean() * 100.0
    else:
        negative = 0.0

    def _avg_bug_days(df_a, df_b):
        if df_a.empty and df_b.empty: return 0.0
        d = pd.concat([df_a, df_b], ignore_index=True) if not (df_a.empty or df_b.empty) else (df_a if df_b.empty else df_b)
        if "created_dt" in d.columns and "resolved_dt" in d.columns:
            c, r = d["created_dt"], d["resolved_dt"]
        else:
            c = pd.to_datetime(d.get("created"), errors="coerce", utc=True)
            r = pd.to_datetime(d.get("resolutiondate"), errors="coerce", utc=True)
        valid = c.notna() & r.notna()
        if not valid.any(): return 0.0
        days = (r[valid] - c[valid]).dt.total_seconds() / 86400.0
        days = days[(days.notna()) & (days >= 0)]
        return float(days.mean()) if not days.empty else 0.0

    bug_days = _avg_bug_days(df_bug_f, df_subbug_f)

    # ---------------- Notas base (1–4) por indicador ----------------
    note_coverage     = score_coverage(coverage_pct)
    note_test_avg     = score_test_avg(test_avg)
    note_created_auto = score_created_auto(created_auto)
    note_auto_runs    = score_auto_runs(auto_runs)
    note_test_reg     = score_test_reg(test_reg)
    note_negative     = score_negative(negative)
    note_bug_days     = score_bug_days(bug_days)

    # ---------------- Score final ponderado (1–4) ----------------
    weighted_sum = (
        note_coverage     * WEIGHTS["coverage"] +
        note_test_avg     * WEIGHTS["test_avg"] +
        note_created_auto * WEIGHTS["created"] +
        note_auto_runs    * WEIGHTS["auto_runs"] +
        note_test_reg     * WEIGHTS["test_reg"] +
        note_negative     * WEIGHTS["negative"] +
        note_bug_days     * WEIGHTS["bug_days"]
    )
    weights_total = sum(WEIGHTS.values())
    note_quality  = round((weighted_sum / weights_total) if weights_total else 0.0, 2)

    SCORE_DEFS = {
        "coverage":   {"title": "% Total Coverage",            "value": f"{note_coverage:.0f}"},
        "test_avg":   {"title": "# Test Avg Per Issue",        "value": f"{note_test_avg:.0f}"},
        "created":    {"title": "% Created Automations",       "value": f"{note_created_auto:.0f}"},
        "auto_runs":  {"title": "% Automated Run",             "value": f"{note_auto_runs:.0f}"},
        "test_reg":   {"title": "% Regression Test",           "value": f"{note_test_reg:.0f}"},
        "negative":   {"title": "% Negative Test",             "value": f"{note_negative:.0f}"},
        "bug_days":   {"title": "# AVG days resolution bug",   "value": f"{note_bug_days:.0f}"},
        "quality":    {"title": "Score Qualidade (ponderado)", "value": f"{note_quality:.2f}"},
    }

    if "score_selected" not in st.session_state:
        st.session_state["score_selected"] = "coverage"

    # ---------------- Cards ----------------
    cols = st.columns(8)
    def _score_btn(col, key, label, value):
        selected = (st.session_state["score_selected"] == key)
        with col.container():
            st.write(f'<div class="{ "score-selected" if selected else "" }">', unsafe_allow_html=True)
            clicked = st.button(f"{label}\n{value}", key=f"btn_score_{key}", use_container_width=True)
            st.write("</div>", unsafe_allow_html=True)
        if clicked:
            st.session_state["score_selected"] = key

    order = ["coverage","test_avg","created","auto_runs","test_reg","negative","bug_days","quality"]
    for i, k in enumerate(order):
        _score_btn(cols[i], k, SCORE_DEFS[k]["title"], SCORE_DEFS[k]["value"])

    st.markdown("---")

    # ---------------- Séries mensais (nota base 1–4 do indicador) ----------------
    def series_coverage():
        def agg(df): return df.groupby("month").size().rename("n") if "month" in df.columns else pd.Series(dtype=int)
        s_func, s_story, s_epic = agg(df_func_f), agg(df_story_f), agg(df_epic_f)
        idx = sorted(set(s_func.index) | set(s_story.index) | set(s_epic.index))
        rows = []
        for m in idx:
            num = int(s_func.get(m,0) + s_story.get(m,0))
            den = int(num + s_epic.get(m,0))
            cov = _pct(num, den)
            rows.append({"month": m, "value": float(score_coverage(cov))})
        return pd.DataFrame(rows)

    def series_test_avg():
        if df_ze_f.empty or "issueKey" not in df_ze_f.columns: return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.dropna(subset=["issueKey"]).copy()
        by_issue = tmp.groupby(["month","issueKey"]).size().reset_index(name="runs")
        s = by_issue.groupby("month")["runs"].mean().reset_index()
        s["value"] = s["runs"].apply(lambda v: float(score_test_avg(v)))
        return s[["month","value"]]

    def series_created():
        if df_zc_f.empty or "automated" not in df_zc_f.columns: return pd.DataFrame(columns=["month","value"])
        tmp = df_zc_f.copy()
        if "month" not in tmp.columns or tmp["month"].isna().all():
            v = tmp["automated"].astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
            return pd.DataFrame([{"month": "Total", "value": float(score_created_auto(v))}])
        s = tmp.groupby("month")["automated"].apply(
            lambda x: x.astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
        ).reset_index(name="pct")
        s["value"] = s["pct"].apply(lambda v: float(score_created_auto(v)))
        return s[["month","value"]]

    def series_auto_runs():
        if df_ze_f.empty or "automated" not in df_ze_f.columns: return pd.DataFrame(columns=["month","value"])
        s = df_ze_f.groupby("month")["automated"].apply(
            lambda x: x.astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
        ).reset_index(name="pct")
        s["value"] = s["pct"].apply(lambda v: float(score_auto_runs(v)))
        return s[["month","value"]]

    def series_test_reg():
        if df_ze_f.empty or "testType" not in df_ze_f.columns: return pd.DataFrame(columns=["month","value"])
        s = df_ze_f.groupby("month")["testType"].apply(
            lambda x: x.astype(str).str.lower().str.contains("regress").mean() * 100.0
        ).reset_index(name="pct")
        s["value"] = s["pct"].apply(lambda v: float(score_test_reg(v)))
        return s[["month","value"]]

    def series_negative():
        if df_ze_f.empty: return pd.DataFrame(columns=["month","value"])
        def _neg(dfm):
            m = pd.Series(False, index=dfm.index)
            if "testType" in dfm.columns:
                m |= dfm["testType"].astype(str).str.lower().str.contains("negative|negativo")
            if "labels" in dfm.columns:
                m |= dfm["labels"].astype(str).str.lower().str.contains("negative|negativo")
            return m.mean() * 100.0
        s = df_ze_f.groupby("month").apply(_neg).reset_index(name="pct")
        s["value"] = s["pct"].apply(lambda v: float(score_negative(v)))
        return s[["month","value"]]

    def series_bug_days():
        if df_bug_f.empty and df_subbug_f.empty: return pd.DataFrame(columns=["month","value"])
        d = pd.concat([df_bug_f, df_subbug_f], ignore_index=True)
        c = d.get("created_dt"); r = d.get("resolved_dt")
        if c is None or r is None:
            c = pd.to_datetime(d.get("created"), errors="coerce", utc=True)
            r = pd.to_datetime(d.get("resolutiondate"), errors="coerce", utc=True)
        ok = c.notna() & r.notna()
        if not ok.any(): return pd.DataFrame(columns=["month","value"])
        d = d.loc[ok].copy()
        d["month"] = c[ok].dt.strftime("%Y-%m")
        d["days"]  = (r[ok] - c[ok]).dt.total_seconds() / 86400.0
        s = d.groupby("month")["days"].mean().reset_index(name="days")
        s["value"] = s["days"].apply(lambda v: float(score_bug_days(v)))
        return s[["month","value"]]

    SERIES_FUNCS = {
        "coverage":  series_coverage,
        "test_avg":  series_test_avg,
        "created":   series_created,
        "auto_runs": series_auto_runs,
        "test_reg":  series_test_reg,
        "negative":  series_negative,
        "bug_days":  series_bug_days,
        "quality":   series_coverage,  # opcional: poderia ser uma média ponderada mensal
    }

    sel_key = st.session_state["score_selected"]
    st.markdown(f"#### {SCORE_DEFS[sel_key]['title']} (nota base 1–4)")

    df_series = SERIES_FUNCS[sel_key]()
    if df_series.empty:
        st.info("Sem dados suficientes para este indicador com os filtros atuais.")
        return

    try:
        df_series["month_dt"] = pd.to_datetime(df_series["month"] + "-01", errors="coerce")
        df_series = df_series.sort_values("month_dt")
    except Exception:
        pass

    chart = (
        alt.Chart(df_series)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:N", title="Mês"),
            y=alt.Y("value:Q", title="Nota (1–4)", scale=alt.Scale(domain=[1,4])),
            tooltip=["month:N","value:Q"],
        )
        .properties(height=340, width="container")
    )
    st.altair_chart(chart, use_container_width=True)

# debug local
if __name__ == "__main__":
    pagina_dashboard_score()
