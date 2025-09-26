# coeqa/dashboard_kpi.py
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

# ---------- util ----------
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

# =========================================================
def pagina_dashboard_kpi():
    # set_page_config pode já ter sido chamado no app principal — evitar erro
    try:
        st.set_page_config(page_title="Quality KPI's", layout="wide")
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

    st.markdown("### Quality KPI’s")

    # ---- Carrega bases
    df_func   = safe_read_csv("jira_issues_func_latest.csv",   ISSUE_COLS)
    df_epic   = safe_read_csv("jira_issues_epic_latest.csv",   ISSUE_COLS)
    df_story  = safe_read_csv("jira_issues_story_latest.csv",  ISSUE_COLS)
    df_bug    = safe_read_csv("jira_issues_bug_latest.csv",    ISSUE_COLS)
    df_subbug = safe_read_csv("jira_issues_subbug_latest.csv", ISSUE_COLS)
    df_proj   = safe_read_csv("jira_projetos_latest.csv",      PROJ_COLS)
    df_zc     = safe_read_csv("zephyr_testcases_latest.csv",   Z_CASES_COLS)     # opcional
    df_ze     = safe_read_csv("zephyr_executions_latest.csv",  Z_EXEC_COLS)      # opcional

    # ---- colunas auxiliares
    for d in (df_func, df_epic, df_story, df_bug, df_subbug):
        if "projectKey" not in d.columns:
            d["projectKey"] = d["key"].apply(key_project_prefix)
        d["month"] = d["created"].apply(to_month)

    if not df_ze.empty:
        if "projectKey" not in df_ze.columns:
            df_ze["projectKey"] = df_ze["issueKey"].apply(key_project_prefix)
        df_ze["month"] = df_ze["executedOn"].apply(to_month)
    if not df_zc.empty and "projectKey" not in df_zc.columns:
        df_zc["projectKey"] = df_zc.get("key","").apply(key_project_prefix)

    # ---- Filtros topo
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
        st.caption("Clique em um card abaixo para trocar o gráfico do KPI.")
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
    df_ze_f     = apply_project(df_ze)

    # ---- KPIs principais
    cov_num = len(df_func_f) + len(df_story_f)
    cov_den = cov_num + len(df_epic_f)
    kpi_coverage = round(pct(cov_num, cov_den), 2)

    if not df_ze_f.empty:
        by_issue = df_ze_f.dropna(subset=["issueKey"]).groupby("issueKey").size()
        kpi_test_avg = round(by_issue.mean(), 2) if not by_issue.empty else 0.0
    else:
        kpi_test_avg = 0.0

    if not df_ze_f.empty and "automated" in df_ze_f.columns:
        auto_runs = df_ze_f["automated"].astype(str).str.lower().isin(["1","true","yes"]).sum()
        kpi_auto_runs = round(pct(auto_runs, len(df_ze_f)), 2)
    else:
        kpi_auto_runs = 0.0

    if not df_ze_f.empty and {"automated","testType"}.issubset(df_ze_f.columns):
        reg = df_ze_f["testType"].astype(str).str.lower().str.contains("regress")
        reg_total = int(reg.sum())
        reg_auto  = int(df_ze_f[reg]["automated"].astype(str).str.lower().isin(["1","true","yes"]).sum())
        kpi_auto_reg = round(pct(reg_auto, reg_total), 2) if reg_total else 0.0
    else:
        kpi_auto_reg = 0.0

    if not df_ze_f.empty and "testType" in df_ze_f.columns:
        reg_total = int(df_ze_f["testType"].astype(str).str.lower().str.contains("regress").sum())
        kpi_test_reg = round(pct(reg_total, len(df_ze_f)), 2)
    else:
        kpi_test_reg = 0.0

    if not df_ze_f.empty:
        neg_mask = pd.Series(False, index=df_ze_f.index)
        if "testType" in df_ze_f.columns:
            neg_mask |= df_ze_f["testType"].astype(str).str.lower().str.contains("negative|negativo")
        if "labels" in df_ze_f.columns:
            neg_mask |= df_ze_f["labels"].astype(str).str.lower().str.contains("negative|negativo")
        kpi_negative = round(pct(int(neg_mask.sum()), len(df_ze_f)), 2)
    else:
        kpi_negative = 0.0

    def avg_bug_days(df_a, df_b):
        if df_a.empty and df_b.empty: return 0.0
        d = pd.concat([df_a, df_b], ignore_index=True)
        if "created" not in d or "resolutiondate" not in d: return 0.0
        try:
            c = pd.to_datetime(d["created"], errors="coerce")
            r = pd.to_datetime(d["resolutiondate"], errors="coerce")
            valid = (r.notna() & c.notna())
            days = (r[valid] - c[valid]).dt.total_seconds() / 86400.0
            return round(float(days.mean()) if not days.empty else 0.0, 2)
        except Exception:
            return 0.0

    kpi_bug_days = avg_bug_days(df_bug_f, df_subbug_f)

    KPI_DEFS = {
        "coverage":  {"title": "% Total Coverage",        "value": f"{kpi_coverage:.2f}%"},
        "test_avg":  {"title": "Test AVG per issue",      "value": f"{kpi_test_avg:.2f}"},
        "auto_reg":  {"title": "% Automated Regression",  "value": f"{kpi_auto_reg:.2f}%"},
        "auto_runs": {"title": "% Automated Runs",        "value": f"{kpi_auto_runs:.2f}%"},
        "test_reg":  {"title": "% Test Regression",       "value": f"{kpi_test_reg:.2f}%"},
        "negative":  {"title": "% Negative Test",         "value": f"{kpi_negative:.2f}%"},
        "bug_days":  {"title": "AVG days resolution Bug", "value": f"{kpi_bug_days:.2f}"},
    }

    if "kpi_selected" not in st.session_state:
        st.session_state["kpi_selected"] = "coverage"

    # ---------- cards-botão (título + valor DENTRO do botão) ----------
    def kpi_button(col, key, label, value):
        selected = (st.session_state["kpi_selected"] == key)
        # wrapper com classe para estilizar "selecionado"
        with col.container():
            # aplica uma classe CSS na div do botão
            st.write(f'<div class="{ "kpi-selected" if selected else "" }">', unsafe_allow_html=True)
            clicked = st.button(f"{label}\n{value}", key=f"btn_{key}", use_container_width=True)
            st.write("</div>", unsafe_allow_html=True)
            if clicked:
                st.session_state["kpi_selected"] = key

    # linha única com 7 colunas
    cols = st.columns(7)  # se quiser mais espaço entre eles: st.columns(7, gap="small")

    kpi_button(cols[0], "coverage",  KPI_DEFS["coverage"]["title"],  KPI_DEFS["coverage"]["value"])
    kpi_button(cols[1], "test_avg",  KPI_DEFS["test_avg"]["title"],  KPI_DEFS["test_avg"]["value"])
    kpi_button(cols[2], "auto_reg",  KPI_DEFS["auto_reg"]["title"],  KPI_DEFS["auto_reg"]["value"])
    kpi_button(cols[3], "auto_runs", KPI_DEFS["auto_runs"]["title"], KPI_DEFS["auto_runs"]["value"])
    kpi_button(cols[4], "test_reg",  KPI_DEFS["test_reg"]["title"],  KPI_DEFS["test_reg"]["value"])
    kpi_button(cols[5], "negative",  KPI_DEFS["negative"]["title"],  KPI_DEFS["negative"]["value"])
    kpi_button(cols[6], "bug_days",  KPI_DEFS["bug_days"]["title"],  KPI_DEFS["bug_days"]["value"])


    st.markdown("---")

    # ---- séries mensais para cada KPI
    def monthly_series_coverage():
        def agg(df): return df.groupby("month").size().rename("n")
        s_func  = agg(df_func_f)
        s_story = agg(df_story_f)
        s_epic  = agg(df_epic_f)
        idx = sorted(set(s_func.index) | set(s_story.index) | set(s_epic.index))
        out = []
        for m in idx:
            num = int(s_func.get(m,0) + s_story.get(m,0))
            den = int(num + s_epic.get(m,0))
            out.append({"month": m, "value": pct(num, den)})
        return pd.DataFrame(out)

    def monthly_series_test_avg():
        if df_ze_f.empty or "issueKey" not in df_ze_f.columns:
            return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.dropna(subset=["issueKey"]).copy()
        tmp["month"] = tmp["executedOn"].apply(to_month)
        out = tmp.groupby(["month","issueKey"]).size().reset_index(name="runs")
        s = out.groupby("month")["runs"].mean().reset_index(name="value")
        return s

    def monthly_series_auto_runs():
        if df_ze_f.empty or "automated" not in df_ze_f.columns:
            return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.copy()
        tmp["is_auto"] = tmp["automated"].astype(str).str.lower().isin(["1","true","yes"])
        s = tmp.groupby("month").apply(lambda d: pct(d["is_auto"].sum(), len(d))).reset_index(name="value")
        return s

    def monthly_series_auto_reg():
        if df_ze_f.empty or not {"automated","testType"}.issubset(df_ze_f.columns):
            return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.copy()
        tmp["is_reg"]  = tmp["testType"].astype(str).str.lower().str.contains("regress")
        tmp["is_auto"] = tmp["automated"].astype(str).str.lower().isin(["1","true","yes"])
        def f(d):
            den = int(d["is_reg"].sum())
            num = int((d["is_reg"] & d["is_auto"]).sum())
            return pct(num, den) if den else 0.0
        s = tmp.groupby("month").apply(f).reset_index(name="value")
        return s

    def monthly_series_test_reg():
        if df_ze_f.empty or "testType" not in df_ze_f.columns:
            return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.copy()
        tmp["is_reg"] = tmp["testType"].astype(str).str.lower().str.contains("regress")
        s = tmp.groupby("month").apply(lambda d: pct(int(d["is_reg"].sum()), len(d))).reset_index(name="value")
        return s

    def monthly_series_negative():
        if df_ze_f.empty:
            return pd.DataFrame(columns=["month","value"])
        tmp = df_ze_f.copy()
        neg = pd.Series(False, index=tmp.index)
        if "testType" in tmp.columns:
            neg |= tmp["testType"].astype(str).str.lower().str.contains("negative|negativo")
        if "labels" in tmp.columns:
            neg |= tmp["labels"].astype(str).str.lower().str.contains("negative|negativo")
        s = tmp.groupby("month").apply(lambda d: pct(int(neg.loc[d.index].sum()), len(d))).reset_index(name="value")
        return s

    def monthly_series_bug_days():
        if df_bug_f.empty and df_subbug_f.empty:
            return pd.DataFrame(columns=["month","value"])
        d = pd.concat([df_bug_f, df_subbug_f], ignore_index=True)
        d["c"] = pd.to_datetime(d["created"], errors="coerce")
        d["r"] = pd.to_datetime(d["resolutiondate"], errors="coerce")
        d = d[d["c"].notna() & d["r"].notna()].copy()
        if d.empty:
            return pd.DataFrame(columns=["month","value"])
        d["month"] = d["c"].dt.strftime("%Y-%m")
        d["days"] = (d["r"] - d["c"]).dt.total_seconds() / 86400.0
        s = d.groupby("month")["days"].mean().reset_index(name="value")
        return s

    SERIES_FUNCS = {
        "coverage": monthly_series_coverage,
        "test_avg": monthly_series_test_avg,
        "auto_reg": monthly_series_auto_reg,
        "auto_runs": monthly_series_auto_runs,
        "test_reg": monthly_series_test_reg,
        "negative": monthly_series_negative,
        "bug_days": monthly_series_bug_days,
    }

    sel_key = st.session_state["kpi_selected"]
    title = KPI_DEFS[sel_key]['title']
    st.markdown(f"#### {title}")

    df_series = SERIES_FUNCS[sel_key]()
    if df_series.empty:
        st.info("Sem dados suficientes para este KPI com os filtros atuais.")
        return

    # ordenar por mês (quando possível)
    try:
        df_series["month_dt"] = pd.to_datetime(df_series["month"] + "-01")
        df_series = df_series.sort_values("month_dt")
    except Exception:
        pass

    y_title = "%" if sel_key in {"coverage","auto_reg","auto_runs","test_reg","negative"} else "Valor"
    chart = (
        alt.Chart(df_series)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:N", title="Mês"),
            y=alt.Y("value:Q", title=y_title),
            tooltip=["month:N","value:Q"]
        )
        .properties(height=340, width="container")
    )
    st.altair_chart(chart, use_container_width=True)


# para debug isolado:
if __name__ == "__main__":
    pagina_dashboard_kpi()
