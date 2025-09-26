# coeqa/dashboard_score.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from pathlib import Path
from datetime import datetime

DATA = Path("config/data")

ISSUE_COLS = ["key","summary","status","type","priority","created","resolutiondate","assignee","reporter"]
PROJ_COLS  = ["id","key","name","projectTypeKey","lead"]

# Zephyr (opcionais)
Z_CASES_COLS = ["key","name","status","automated","testType","labels","created","projectKey"]
Z_EXEC_COLS  = ["executionKey","testKey","status","automated","testType","labels","executedOn","projectKey","issueKey"]

# ========= Alvos e pesos para conversão em nota (0–4) =========
TARGETS = {
    "coverage_pct_best": 100.0,   # 100% coverage -> nota 4 (linear)
    "test_avg_best":     10.0,    # 10 execuções/issue -> nota 4 (linear, cap)
    "auto_runs_best":    80.0,    # 80% -> 4
    "auto_reg_best":     80.0,    # 80% -> 4
    "test_reg_best":     0.0,     # quanto MENOR melhor: 0% -> 4, 50% -> 0
    "negative_best":     50.0,    # 50% -> 4 (linear até 0)
    "bug_days_best":     2.0,     # 2 dias -> 4 (quanto MENOR, melhor; 30d -> 0)
    "bug_days_worst":    30.0,
}

WEIGHTS = {
    "coverage": 2.0,
    "test_avg": 1.0,
    "created_auto": 1.0,
    "auto_runs": 1.0,
    "test_reg": 1.0,
    "negative": 1.0,
    "bug_days": 1.0,
}

# ========= util =========
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

# ========= conversão métrica -> nota (0–4) =========
def score_linear(value, best, cap=True):
    """0..best mapeado para 0..4 (linear)."""
    if value is None or np.isnan(value): return 0.0
    v = max(0.0, float(value))
    s = 4.0 * v / float(best) if best else 0.0
    return min(4.0, s) if cap else s

def score_inverse(value, best_zero, worst_full):
    """
    Menor é melhor: best_zero -> 4; worst_full -> 0 (linear).
    Ex.: test_reg %, bug_days.
    """
    if value is None or np.isnan(value): return 0.0
    v = float(value)
    if v <= best_zero: return 4.0
    if v >= worst_full: return 0.0
    return 4.0 * (worst_full - v) / (worst_full - best_zero)

# ========= página =========
def pagina_dashboard_score():
    # evita erro se já setado fora
    try:
        st.set_page_config(page_title="Quality Score", layout="wide")
    except Exception:
        pass

    # CSS cards compactos (uma linha)
    st.markdown("""
    <style>
    .stButton > button {
      height: 78px;
      width: 100%;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,.12);
      background: rgba(255,255,255,.04);
      white-space: pre-line;
      line-height: 1.05;
      padding: 8px 8px;
      text-align: center;
      font-size: 12px;
      font-weight: 700;
      min-width: 0;
    }
    .stButton > button:hover {
      border-color: rgba(186,85,211,.6);
      background: rgba(186,85,211,.10);
    }
    .score-selected > button {
      outline: 2px solid #ba55d3 !important;
      background: rgba(186,85,211,.16) !important;
      border-color: transparent !important;
    }
    .block-container { padding-left: 1rem; padding-right: 1rem; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### Quality Score")

    # ---- Carrega bases
    df_func   = safe_read_csv("jira_issues_func_latest.csv",   ISSUE_COLS)
    df_epic   = safe_read_csv("jira_issues_epic_latest.csv",   ISSUE_COLS)
    df_story  = safe_read_csv("jira_issues_story_latest.csv",  ISSUE_COLS)
    df_bug    = safe_read_csv("jira_issues_bug_latest.csv",    ISSUE_COLS)
    df_subbug = safe_read_csv("jira_issues_subbug_latest.csv", ISSUE_COLS)
    df_proj   = safe_read_csv("jira_projetos_latest.csv",      PROJ_COLS)
    df_zc     = safe_read_csv("zephyr_testcases_latest.csv",   Z_CASES_COLS)     # opcional (created automations)
    df_ze     = safe_read_csv("zephyr_executions_latest.csv",  Z_EXEC_COLS)      # opcional (runs, tipos)

    # colunas auxiliares
    for d in (df_func, df_epic, df_story, df_bug, df_subbug):
        if "projectKey" not in d.columns:
            d["projectKey"] = d["key"].apply(key_project_prefix)
        d["month"] = d["created"].apply(to_month)
    if not df_zc.empty and "projectKey" not in df_zc.columns:
        df_zc["projectKey"] = df_zc.get("key","").apply(key_project_prefix)
    if not df_ze.empty:
        if "projectKey" not in df_ze.columns:
            df_ze["projectKey"] = df_ze["issueKey"].apply(key_project_prefix)
        df_ze["month"] = df_ze["executedOn"].apply(to_month)

    # Filtro topo
    if not df_proj.empty:
        projects = sorted(df_proj["key"].dropna().unique().tolist())
    else:
        pref = pd.concat(
            [d["projectKey"] for d in (df_func, df_epic, df_story, df_bug, df_subbug) if not d.empty] +
            ([df_ze["projectKey"]] if not df_ze.empty else []),
            ignore_index=True
        )
        projects = sorted([p for p in pref.dropna().unique().tolist() if p])

    c1, c2, c3 = st.columns([0.35, 0.3, 0.35])
    with c1:
        sel_project = st.selectbox("Domain (Projeto)", options=["Todos"] + projects, index=0)
    with c2:
        st.caption("")
    with c3:
        st.caption(datetime.now().strftime("Atualizado: %d/%m/%Y %H:%M"))
    
    c1, c2, c3 = st.columns([0.35, 0.3, 0.35])
    with c1:
        st.caption("Clique em um card para alternar o gráfico.")
    with c2:
        st.caption("")
    with c3:
        st.caption("")

    def apply_project(df):
        if df.empty or sel_project == "Todos": return df
        return df[df["projectKey"] == sel_project].copy()

    df_func_f   = apply_project(df_func)
    df_epic_f   = apply_project(df_epic)
    df_story_f  = apply_project(df_story)
    df_bug_f    = apply_project(df_bug)
    df_subbug_f = apply_project(df_subbug)
    df_zc_f     = apply_project(df_zc)
    df_ze_f     = apply_project(df_ze)

    # ===== métricas brutas (como na KPI), para converter em notas =====
    cov_num = len(df_func_f) + len(df_story_f)
    cov_den = cov_num + len(df_epic_f)
    coverage_pct = pct(cov_num, cov_den)

    # Test AVG por issue (Zephyr)
    if not df_ze_f.empty:
        by_issue = df_ze_f.dropna(subset=["issueKey"]).groupby("issueKey").size()
        test_avg = float(by_issue.mean()) if not by_issue.empty else 0.0
    else:
        test_avg = 0.0

    # Created Automations (% de testcases marcados automated no Zephyr)
    if not df_zc_f.empty and "automated" in df_zc_f.columns:
        created_auto = df_zc_f["automated"].astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
    else:
        created_auto = 0.0

    # Automated Runs
    if not df_ze_f.empty and "automated" in df_ze_f.columns:
        auto_runs = df_ze_f["automated"].astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
    else:
        auto_runs = 0.0

    # Test Regression %
    if not df_ze_f.empty and "testType" in df_ze_f.columns:
        test_reg = (df_ze_f["testType"].astype(str).str.lower().str.contains("regress").mean()) * 100.0
    else:
        test_reg = 0.0

    # Negative Test %
    if not df_ze_f.empty:
        neg = pd.Series(False, index=df_ze_f.index)
        if "testType" in df_ze_f.columns:
            neg |= df_ze_f["testType"].astype(str).str.lower().str.contains("negative|negativo")
        if "labels" in df_ze_f.columns:
            neg |= df_ze_f["labels"].astype(str).str.lower().str.contains("negative|negativo")
        negative = neg.mean() * 100.0
    else:
        negative = 0.0

    # AVG days resolution Bug
    def avg_bug_days(df_a, df_b):
        if df_a.empty and df_b.empty: return 0.0
        d = pd.concat([df_a, df_b], ignore_index=True)
        try:
            c = pd.to_datetime(d["created"], errors="coerce")
            r = pd.to_datetime(d["resolutiondate"], errors="coerce")
            val = (r - c).dt.total_seconds() / 86400.0
            val = val[(val.notna()) & (val >= 0)]
            return float(val.mean()) if not val.empty else 0.0
        except Exception:
            return 0.0
    bug_days = avg_bug_days(df_bug_f, df_subbug_f)

    # ===== conversão para NOTAS (0–4) =====
    note_coverage   = round(score_linear(coverage_pct, TARGETS["coverage_pct_best"]), 2)
    note_test_avg   = round(score_linear(test_avg,     TARGETS["test_avg_best"]),     2)
    note_auto_runs  = round(score_linear(auto_runs,    TARGETS["auto_runs_best"]),    2)
    note_auto_reg   = round(score_linear(
                            # % de regressão automatizada = auto em regressão / total regressão (%)
                            # aproximamos usando test_reg (%) e supomos proporção de auto igual ao geral
                            min(auto_runs, 100.0) if test_reg > 0 else 0.0,
                            TARGETS["auto_reg_best"]), 2)
    note_test_reg   = round(score_inverse(test_reg, TARGETS["test_reg_best"], 50.0), 2)  # 50% -> 0
    note_negative   = round(score_linear(negative, TARGETS["negative_best"]), 2)
    note_bug_days   = round(score_inverse(bug_days, TARGETS["bug_days_best"], TARGETS["bug_days_worst"]), 2)

    # Created Automations (se não houver Zephyr cases, fica 0)
    note_created_auto = round(score_linear(created_auto, TARGETS["auto_runs_best"]), 2)

    # Score Qualidade (média ponderada)
    weighted_sum = (
        note_coverage   * WEIGHTS["coverage"] +
        note_test_avg   * WEIGHTS["test_avg"] +
        note_created_auto*WEIGHTS["created_auto"] +
        note_auto_runs  * WEIGHTS["auto_runs"] +
        note_test_reg   * WEIGHTS["test_reg"] +
        note_negative   * WEIGHTS["negative"] +
        note_bug_days   * WEIGHTS["bug_days"]
    )
    weights_total = sum(WEIGHTS.values())
    note_quality = round(weighted_sum / weights_total if weights_total else 0.0, 2)

    SCORE_DEFS = {
        "coverage":   {"title": "Total Coverage",            "value": f"{note_coverage:.2f}"},
        "test_avg":   {"title": "Test AVG per issue",        "value": f"{note_test_avg:.2f}"},
        "created":    {"title": "Created Automations",       "value": f"{note_created_auto:.2f}"},
        "auto_runs":  {"title": "Automated Runs",            "value": f"{note_auto_runs:.2f}"},
        "test_reg":   {"title": "Test Regression",           "value": f"{note_test_reg:.2f}"},
        "negative":   {"title": "Negative Test",             "value": f"{note_negative:.2f}"},
        "bug_days":   {"title": "AVG days resolution Bug",   "value": f"{note_bug_days:.2f}"},
        "quality":    {"title": "Score Qualidade",           "value": f"{note_quality:.2f}"},
    }

    if "score_selected" not in st.session_state:
        st.session_state["score_selected"] = "coverage"

    # ===== cards em linha única =====
    cols = st.columns(8)
    def score_button(col, key, label, value):
        selected = (st.session_state["score_selected"] == key)
        with col.container():
            st.write(f'<div class="{ "score-selected" if selected else "" }">', unsafe_allow_html=True)
            clicked = st.button(f"{label}\n{value}", key=f"btn_score_{key}", use_container_width=True)
            st.write("</div>", unsafe_allow_html=True)
            if clicked:
                st.session_state["score_selected"] = key

    order = ["coverage","test_avg","created","auto_runs","test_reg","negative","bug_days","quality"]
    for i, k in enumerate(order):
        score_button(cols[i], k, SCORE_DEFS[k]["title"], SCORE_DEFS[k]["value"])

    st.markdown("---")

    # ===== séries mensais (nota 0–4 por mês) =====
    # Reaproveitamos dados mensais e aplicamos a mesma conversão -> nota
    def monthly_series_coverage():
        def agg(df): return df.groupby("month").size().rename("n")
        s_func, s_story, s_epic = agg(df_func_f), agg(df_story_f), agg(df_epic_f)
        idx = sorted(set(s_func.index) | set(s_story.index) | set(s_epic.index))
        out = []
        for m in idx:
            num = int(s_func.get(m,0) + s_story.get(m,0))
            den = int(num + s_epic.get(m,0))
            cov = pct(num, den)
            out.append({"month": m, "value": round(score_linear(cov, TARGETS["coverage_pct_best"]), 2)})
        return pd.DataFrame(out)

    def monthly_series_test_avg():
        if df_ze_f.empty or "issueKey" not in df_ze_f.columns:
            return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.dropna(subset=["issueKey"]).copy()
        tmp["month"] = tmp["executedOn"].apply(to_month)
        by_issue = tmp.groupby(["month","issueKey"]).size().reset_index(name="runs")
        s = by_issue.groupby("month")["runs"].mean().reset_index()
        s["value"] = s["runs"].apply(lambda v: round(score_linear(v, TARGETS["test_avg_best"]), 2))
        return s[["month","value"]]

    def monthly_series_created():
        if df_zc_f.empty or "automated" not in df_zc_f.columns:
            return pd.DataFrame(columns=["month","value"])
        tmp = df_zc_f.copy()
        tmp["month"] = tmp["created"].apply(to_month) if "created" in tmp.columns else None
        if "month" not in tmp.columns or tmp["month"].isna().all():
            # fallback: única linha com média global
            val = tmp["automated"].astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
            return pd.DataFrame([{"month": "Total", "value": round(score_linear(val, TARGETS["auto_runs_best"]), 2)}])
        s = tmp.groupby("month")["automated"].apply(
            lambda x: x.astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
        ).reset_index(name="pct")
        s["value"] = s["pct"].apply(lambda v: round(score_linear(v, TARGETS["auto_runs_best"]), 2))
        return s[["month","value"]]

    def monthly_series_auto_runs():
        if df_ze_f.empty or "automated" not in df_ze_f.columns:
            return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.copy()
        s = tmp.groupby("month")["automated"].apply(
            lambda x: x.astype(str).str.lower().isin(["1","true","yes"]).mean() * 100.0
        ).reset_index(name="pct")
        s["value"] = s["pct"].apply(lambda v: round(score_linear(v, TARGETS["auto_runs_best"]), 2))
        return s[["month","value"]]

    def monthly_series_test_reg():
        if df_ze_f.empty or "testType" not in df_ze_f.columns:
            return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.copy()
        s = tmp.groupby("month")["testType"].apply(
            lambda x: x.astype(str).str.lower().str.contains("regress").mean() * 100.0
        ).reset_index(name="pct")
        s["value"] = s["pct"].apply(lambda v: round(score_inverse(v, TARGETS["test_reg_best"], 50.0), 2))
        return s[["month","value"]]

    def monthly_series_negative():
        if df_ze_f.empty:
            return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.copy()
        def is_neg(dfm):
            m = pd.Series(False, index=dfm.index)
            if "testType" in dfm.columns:
                m |= dfm["testType"].astype(str).str.lower().str.contains("negative|negativo")
            if "labels" in dfm.columns:
                m |= dfm["labels"].astype(str).str.lower().str.contains("negative|negativo")
            return m.mean() * 100.0
        s = tmp.groupby("month").apply(is_neg).reset_index(name="pct")
        s["value"] = s["pct"].apply(lambda v: round(score_linear(v, TARGETS["negative_best"]), 2))
        return s[["month","value"]]

    def monthly_series_bug_days():
        if df_bug_f.empty and df_subbug_f.empty:
            return pd.DataFrame(columns=["month","value"])
        d = pd.concat([df_bug_f, df_subbug_f], ignore_index=True)
        d["c"] = pd.to_datetime(d["created"], errors="coerce")
        d["r"] = pd.to_datetime(d["resolutiondate"], errors="coerce")
        d = d[d["c"].notna() & d["r"].notna()].copy()
        if d.empty: return pd.DataFrame(columns=["month","value"])
        d["month"] = d["c"].dt.strftime("%Y-%m")
        d["days"] = (d["r"] - d["c"]).dt.total_seconds() / 86400.0
        s = d.groupby("month")["days"].mean().reset_index(name="days")
        s["value"] = s["days"].apply(lambda v: round(score_inverse(v, TARGETS["bug_days_best"], TARGETS["bug_days_worst"]), 2))
        return s[["month","value"]]

    SERIES_FUNCS = {
        "coverage": monthly_series_coverage,
        "test_avg": monthly_series_test_avg,
        "created":  monthly_series_created,
        "auto_runs":monthly_series_auto_runs,
        "test_reg": monthly_series_test_reg,
        "negative": monthly_series_negative,
        "bug_days": monthly_series_bug_days,
        # quality poderia ser uma média mensal dos demais; por simplicidade mostramos coverage:
        "quality":  monthly_series_coverage,
    }

    sel_key = st.session_state["score_selected"]
    title = SCORE_DEFS[sel_key]["title"]
    st.markdown(f"#### {title} (nota 0–4)")

    df_series = SERIES_FUNCS[sel_key]()
    if df_series.empty:
        st.info("Sem dados suficientes para este indicador com os filtros atuais.")
        return

    # ordenar por mês quando possível
    try:
        df_series["month_dt"] = pd.to_datetime(df_series["month"] + "-01")
        df_series = df_series.sort_values("month_dt")
    except Exception:
        pass

    chart = (
        alt.Chart(df_series)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:N", title="Mês"),
            y=alt.Y("value:Q", title="Nota (0–4)", scale=alt.Scale(domain=[0,4])),
            tooltip=["month:N","value:Q"]
        )
        .properties(height=340, width="container")
    )
    st.altair_chart(chart, use_container_width=True)

# debug isolado
if __name__ == "__main__":
    pagina_dashboard_score()
