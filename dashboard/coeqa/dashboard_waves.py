# coeqa/dashboard_wave.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from pathlib import Path
from datetime import datetime, date, timedelta

DATA = Path("config/data")

ISSUE_COLS = ["key","summary","status","type","priority","created","resolutiondate","assignee","reporter","labels","components"]
PROJ_COLS  = ["id","key","name","projectTypeKey","lead"]

Z_CASES_COLS = ["key","name","status","automated","testType","labels","created","projectKey","environment","wave"]
Z_EXEC_COLS  = ["executionKey","testKey","status","automated","testType","labels","executedOn","projectKey","issueKey","environment","wave"]

# ============== helpers ==============
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
            keep = [c for c in columns if c in df.columns]
            if keep:
                df = df[keep]
        return df
    except Exception:
        return pd.DataFrame(columns=columns or [])

def key_project_prefix(key: str) -> str:
    if isinstance(key, str) and "-" in key:
        return key.split("-")[0]
    return ""

def to_date(x):
    if isinstance(x, date) and not isinstance(x, datetime): return x
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return date.today()

def ensure_range_key(key: str, fallback: tuple[date, date]):
    v = st.session_state.get(key)
    if isinstance(v, (list, tuple)) and len(v) == 2:
        st.session_state[key] = (to_date(v[0]), to_date(v[1]))
    elif isinstance(v, date):
        st.session_state[key] = (v, v)
    else:
        st.session_state[key] = fallback

def normalize_issue_dates(df: pd.DataFrame):
    if df.empty: return
    if "created" in df.columns:
        cdt = pd.to_datetime(df["created"], errors="coerce")
        df["created_dt"] = cdt
        df["created_date"] = cdt.dt.date
        df["created_month"] = cdt.dt.strftime("%Y-%m")
    if "resolutiondate" in df.columns:
        rdt = pd.to_datetime(df["resolutiondate"], errors="coerce")
        df["resolved_dt"] = rdt
        df["resolved_date"] = rdt.dt.date
        df["resolved_month"] = rdt.dt.strftime("%Y-%m")

def normalize_zephyr_dates(df: pd.DataFrame, col: str = "executedOn"):
    if df.empty or col not in df.columns: return
    dt = pd.to_datetime(df[col], errors="coerce")
    df["executed_dt"] = dt
    df["executed_date"] = dt.dt.date
    df["executed_month"] = dt.dt.strftime("%Y-%m")

def coalesce(a, b):
    return a if a else b

def pct(a, b):
    return float(a) / float(b) * 100 if b not in (0, None, 0.0, np.nan) else 0.0

def has_flag(val, keywords):
    s = str(val).lower()
    return any(k in s for k in keywords)

# ============== página ==============
def pagina_dashboard_waves():
    try:
        st.set_page_config(page_title="Wave", layout="wide")
    except Exception:
        pass

    # ---------- CSS (padrão) ----------
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
      .small-caption { font-size: 12px; opacity:.75; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### Wave")

    # ---------- Bases ----------
    df_story  = safe_read_csv("jira_issues_story_latest.csv",  ISSUE_COLS)
    df_epic   = safe_read_csv("jira_issues_epic_latest.csv",   ISSUE_COLS)
    df_bug    = safe_read_csv("jira_issues_bug_latest.csv",    ISSUE_COLS)
    df_subbug = safe_read_csv("jira_issues_subbug_latest.csv", ISSUE_COLS)
    df_proj   = safe_read_csv("jira_projetos_latest.csv",      PROJ_COLS)

    df_zc     = safe_read_csv("zephyr_testcases_latest.csv",   Z_CASES_COLS)
    df_ze     = safe_read_csv("zephyr_executions_latest.csv",  Z_EXEC_COLS)

    for d in (df_story, df_epic, df_bug, df_subbug):
        if not d.empty:
            if "projectKey" not in d.columns:
                d["projectKey"] = d["key"].apply(key_project_prefix)
            normalize_issue_dates(d)

    if not df_zc.empty:
        if "projectKey" not in df_zc.columns:
            df_zc["projectKey"] = df_zc.get("key","").apply(key_project_prefix)
        normalize_issue_dates(df_zc.rename(columns={"created":"_created"}))  # ignora datas se não quiser
        if "created" in df_zc.columns:
            dt = pd.to_datetime(df_zc["created"], errors="coerce")
            df_zc["created_date"] = dt.dt.date

    if not df_ze.empty:
        if "projectKey" not in df_ze.columns:
            df_ze["projectKey"] = df_ze["issueKey"].apply(key_project_prefix)
        normalize_zephyr_dates(df_ze, "executedOn")

    # ---------- Filtros superiores ----------
    # Datas de referência
    exec_dates = df_ze["executed_date"].dropna().tolist() if "executed_date" in df_ze.columns else []
    if exec_dates:
        min_raw, max_raw = min(exec_dates), max(exec_dates)
    else:
        pool = []
        for d in (df_story, df_epic, df_bug, df_subbug):
            if "created_date" in d.columns:
                pool += d["created_date"].dropna().tolist()
        if pool:
            min_raw, max_raw = min(pool), max(pool)
        else:
            min_raw, max_raw = date.today(), date.today()

    min_d, max_d = to_date(min_raw), to_date(max_raw)
    if min_d == max_d:
        min_d = max_d - timedelta(days=30)  # acolchoa para slider

    if "wave_periodo_master" not in st.session_state:
        st.session_state["wave_periodo_master"] = (min_d, max_d)
    ensure_range_key("wave_intervalo_data",   st.session_state["wave_periodo_master"])
    ensure_range_key("wave_intervalo_slider", st.session_state["wave_periodo_master"])

    def on_cal_change():
        st.session_state["wave_periodo_master"]  = st.session_state["wave_intervalo_data"]
        st.session_state["wave_intervalo_slider"] = st.session_state["wave_intervalo_data"]

    def on_slider_change():
        st.session_state["wave_periodo_master"]  = st.session_state["wave_intervalo_slider"]
        st.session_state["wave_intervalo_data"]  = st.session_state["wave_intervalo_slider"]

    ctop0, ctop1, ctop2 = st.columns([0.52, 0.33, 0.15])
    with ctop0:
        cdt1, cdt2 = st.columns(2)
        with cdt1:
            st.date_input("Date (calendário)",
                          key="wave_intervalo_data",
                          min_value=min_d, max_value=max_d,
                          format="DD/MM/YYYY",
                          on_change=on_cal_change)
        with cdt2:
            st.slider("Date (slider)",
                      key="wave_intervalo_slider",
                      min_value=min_d, max_value=max_d,
                      format="DD/MM/YYYY",
                      on_change=on_slider_change)
    with ctop1:
        # Domain
        if not df_proj.empty:
            projects = ["Todos"] + sorted(df_proj["key"].dropna().unique().tolist())
        else:
            pref = []
            for d in (df_story, df_epic, df_bug, df_subbug, df_ze, df_zc):
                if not d.empty and "projectKey" in d.columns:
                    pref += d["projectKey"].dropna().tolist()
            projects = ["Todos"] + sorted(list(set(pref)))
        sel_proj = st.selectbox("Domain", projects, index=0)

        # Environment (a partir de execuções/casos)
        env_src = []
        if "environment" in df_ze.columns: env_src += df_ze["environment"].dropna().astype(str).tolist()
        if "environment" in df_zc.columns: env_src += df_zc["environment"].dropna().astype(str).tolist()
        env_opts = ["Todos"] + sorted(list(set(env_src))) if env_src else ["Todos"]
        sel_env = st.selectbox("Environment", env_opts, index=0)

        # Test type
        tt_src = []
        if "testType" in df_ze.columns: tt_src += df_ze["testType"].dropna().astype(str).tolist()
        if "testType" in df_zc.columns: tt_src += df_zc["testType"].dropna().astype(str).tolist()
        tt_opts = ["Todos"] + sorted(list(set(tt_src))) if tt_src else ["Todos"]
        sel_tt = st.selectbox("Test type", tt_opts, index=0)

        # Wave
        wave_src = []
        if "wave" in df_ze.columns: wave_src += df_ze["wave"].dropna().astype(str).tolist()
        if "wave" in df_zc.columns: wave_src += df_zc["wave"].dropna().astype(str).tolist()
        wave_opts = ["Todos"] + sorted(list(set(wave_src))) if wave_src else ["Todos"]
        sel_wave = st.selectbox("Wave", wave_opts, index=0)

    with ctop2:
        st.caption(datetime.now().strftime("Atualizado: %d/%m/%Y %H:%M"))

    # período aplicável
    d_start, d_end = st.session_state["wave_periodo_master"]

    # ---------- Filtros auxiliares ----------
    def f_proj(df, col="projectKey"):
        if df.empty: return df
        return df if sel_proj == "Todos" else df[df[col] == sel_proj]

    def f_period_created(df):
        if df.empty or "created_date" not in df.columns: return df
        return df[(df["created_date"] >= d_start) & (df["created_date"] <= d_end)].copy()

    def f_period_exec(df):
        if df.empty or "executed_date" not in df.columns: return df
        return df[(df["executed_date"] >= d_start) & (df["executed_date"] <= d_end)].copy()

    def f_env_tt_wave(df):
        if df.empty: return df
        out = df.copy()
        if sel_env != "Todos" and "environment" in out.columns:
            out = out[out["environment"].astype(str) == sel_env]
        if sel_tt != "Todos" and "testType" in out.columns:
            out = out[out["testType"].astype(str) == sel_tt]
        if sel_wave != "Todos" and "wave" in out.columns:
            out = out[out["wave"].astype(str) == sel_wave]
        return out

    f_story  = f_env_tt_wave(f_proj(f_period_created(df_story)))
    f_epic   = f_env_tt_wave(f_proj(f_period_created(df_epic)))
    f_bug    = f_env_tt_wave(f_proj(f_period_created(df_bug)))
    f_subbug = f_env_tt_wave(f_proj(f_period_created(df_subbug)))
    f_ze     = f_env_tt_wave(f_proj(f_period_exec(df_ze)))
    f_zc     = f_env_tt_wave(f_proj(f_period_created(df_zc)))

    # ---------- Métricas Top ----------
    total_func = len(pd.unique(f_zc["labels"])) if ("labels" in f_zc.columns and not f_zc.empty) else 0
    total_epic = int(f_epic.shape[0])
    total_story = int(f_story.shape[0])

    def status_is(s, keys): return has_flag(s, keys)

    story_elaboration = f_story["status"].apply(lambda s: status_is(s, ["elaboration","refin","groom","elabora"])).sum() if not f_story.empty else 0
    story_development = f_story["status"].apply(lambda s: status_is(s, ["develop","dev","desenv"])).sum() if not f_story.empty else 0
    story_canceled   = f_story["status"].apply(lambda s: status_is(s, ["cancel"])).sum() if not f_story.empty else 0

    # “testable stories” = histórias com ao menos 1 execução/caso linkado (heurística por issueKey)
    testable_story = 0
    if not f_story.empty and "key" in f_story.columns:
        keys = set(f_story["key"])
        if not f_ze.empty and "issueKey" in f_ze.columns:
            testable_story = len(keys & set(f_ze["issueKey"]))
        elif not f_zc.empty and "labels" in f_zc.columns:
            # alternativa: histórias citadas em labels
            testable_story = len([k for k in keys if has_flag(",".join(f_zc["labels"].astype(str).tolist()), [k.lower()])])

    stories_with_tests = testable_story
    stories_without_tests = max(total_story - stories_with_tests, 0)

    # “com testes completos e cancelados” (heurística por status de execuções)
    stories_completed_and_canceled = 0
    if not f_ze.empty and "issueKey" in f_ze.columns and "status" in f_ze.columns:
        by_issue = f_ze.groupby("issueKey")["status"].apply(lambda s: set(str(x).lower() for x in s))
        for issue, sts in by_issue.items():
            if any("pass" in x or "done" in x for x in sts) and any("cancel" in x for x in sts):
                stories_completed_and_canceled += 1

    # KPIs em cards
    r1 = st.columns(5)
    with r1[0]: st.metric("# total de func", total_func)
    with r1[1]: st.metric("# total de epic", total_epic)
    with r1[2]: st.metric("# total de Stories", total_story)
    with r1[3]: st.metric("Storys in elaboration", int(story_elaboration), f"{pct(story_elaboration, total_story):.2f}%")
    with r1[4]: st.metric("Storys in development", int(story_development), f"{pct(story_development, total_story):.2f}%")

    r2 = st.columns(5)
    with r2[0]: st.metric("Storys canceled", int(story_canceled), f"{pct(story_canceled, total_story):.2f}%")
    with r2[1]: st.metric("Testable storys", int(testable_story), f"{pct(testable_story, total_story):.2f}%")
    with r2[2]: st.metric("stories with tests", int(stories_with_tests), f"{pct(stories_with_tests, total_story):.2f}%")
    with r2[3]: st.metric("stories without tests", int(stories_without_tests), f"{pct(stories_without_tests, total_story):.2f}%")
    with r2[4]: st.metric("stories with completed tests and cancels", int(stories_completed_and_canceled))

    st.markdown("---")

    # ---------- Linha “Testes”: donuts ----------
    cA, cB, cC = st.columns([0.36, 0.32, 0.32])

    # Total cycles / total test
    total_cycles = f_ze["executed_month"].nunique() if not f_ze.empty and "executed_month" in f_ze.columns else 0
    total_test   = int(f_ze.shape[0]) if not f_ze.empty else 0
    with cA:
        kcol1, kcol2 = st.columns(2)
        with kcol1: st.metric("Total test cycles", total_cycles)
        with kcol2: st.metric("Total test", total_test)

        st.caption("Automated × Manual × Not applicable")
        if f_ze.empty or "automated" not in f_ze.columns:
            st.info("Sem execuções.")
        else:
            def lab_auto(v): 
                s = str(v).lower()
                if s in ["1","true","yes"]: return "Automated"
                if s in ["0","false","no"]: return "Manual"
                return "Not applicable"
            donut = f_ze["automated"].apply(lab_auto).value_counts().reset_index()
            donut.columns = ["cat","qtd"]
            base = alt.Chart(donut).encode(theta="qtd:Q", color=alt.Color("cat:N", title=None))
            chart = base.mark_arc(innerRadius=60)
            text  = base.mark_text(radius=80).encode(text="qtd:Q")
            st.altair_chart(chart + text, use_container_width=True)

    # Donut de status das execuções
    with cB:
        st.caption("Status das execuções")
        if f_ze.empty or "status" not in f_ze.columns:
            st.info("Sem execuções.")
        else:
            # mapeia status em 5-6 grupos
            def map_status(s):
                s = str(s).lower()
                if "pass" in s or "ok" in s or "done" in s: return "Pass"
                if "progress" in s:  return "In Progress"
                if "block" in s:     return "Blocked"
                if "not exec" in s:  return "Not Executed"
                if "fail" in s or "error" in s: return "Fail"
                if "cancel" in s:    return "Canceled"
                return "Others"
            d = f_ze["status"].apply(map_status).value_counts().reset_index()
            d.columns = ["status","qtd"]
            base = alt.Chart(d).encode(theta="qtd:Q", color=alt.Color("status:N", title=None))
            chart = base.mark_arc(innerRadius=60)
            text  = base.mark_text(radius=80).encode(text="qtd:Q")
            st.altair_chart(chart + text, use_container_width=True)

    # ---------- Funcionalidade (barras horizontais empilhadas) ----------
    with cC:
        st.caption("Funcionalidade (percentual por status)")
        # tenta extrair “funcionalidade” de components ou labels
        if f_ze.empty:
            st.info("Sem execuções.")
        else:
            # heurística: usa labels como feature, senão components, senão projectKey
            feat = None
            if "labels" in f_ze.columns and f_ze["labels"].notna().any():
                # pega primeiro label quando múltiplos
                feat = f_ze["labels"].astype(str).str.split("[,;]").str[0].str.strip()
            elif "components" in f_ze.columns and f_ze["components"].notna().any():
                feat = f_ze["components"].astype(str).str.split("[,;]").str[0].str.strip()
            else:
                feat = f_ze.get("projectKey", pd.Series(["N/A"]*len(f_ze)))

            zz = f_ze.copy()
            zz["feature"] = feat
            def map_status2(s):
                s = str(s).lower()
                if "pass" in s or "done" in s: return "Pass"
                if "cancel" in s:              return "Canceled"
                if "block" in s:               return "Blocked"
                if "progress" in s:            return "In Progress"
                if "not exec" in s:            return "Not Executed"
                if "fail" in s:                return "Fail"
                return "Others"
            zz["grp"] = zz["status"].apply(map_status2)

            grp = zz.groupby(["feature","grp"]).size().reset_index(name="qtd")
            # normaliza para 100% (stacked bar)
            total_by_feat = grp.groupby("feature")["qtd"].transform("sum")
            grp["pct"] = grp["qtd"] / total_by_feat * 100
            # pega top 8 features por volume
            top_feats = (zz.groupby("feature").size().sort_values(ascending=False).head(8).index)
            grp_top = grp[grp["feature"].isin(top_feats)]
            ch = alt.Chart(grp_top).mark_bar().encode(
                y=alt.Y("feature:N", sort="-x", title=None),
                x=alt.X("pct:Q", title="%"),
                color=alt.Color("grp:N", title=None)
            ).properties(height=220)
            st.altair_chart(ch, use_container_width=True)

    st.markdown("---")

    # ---------- Bugs (cards + mini barras) ----------
    st.markdown("#### Bugs")
    df_all_bug = pd.concat([f_bug.assign(kind="Bug"), f_subbug.assign(kind="Sub-bug")], ignore_index=True)
    def is_closed(s): return has_flag(s, ["done","closed","resolvido","resolvida"])
    def is_cancel(s): return has_flag(s, ["cancel"])
    if df_all_bug.empty:
        st.info("Sem Bugs/Sub-bugs no período.")
        return

    total_bugs = int(df_all_bug.shape[0])
    open_bugs  = int((~df_all_bug["status"].apply(lambda s: is_closed(s) or is_cancel(s))).sum())
    canc_bugs  = int(df_all_bug["status"].apply(is_cancel).sum())
    done_bugs  = int(df_all_bug["status"].apply(is_closed).sum())

    cc = st.columns([0.10, 0.10, 0.10, 0.10, 0.60])
    with cc[0]: st.metric("Open", open_bugs, f"{pct(open_bugs, total_bugs):.2f}%")
    with cc[1]: st.metric("Canceled", canc_bugs, f"{pct(canc_bugs, total_bugs):.2f}%")
    with cc[2]: st.metric("Done", done_bugs, f"{pct(done_bugs, total_bugs):.2f}%")
    with cc[3]: st.metric("Total", total_bugs)
    with cc[4]:
        # barras empilhadas por issueKey (top N) mostrando % de bloqueio por issue
        if "key" in df_all_bug.columns:
            bug_counts = df_all_bug.groupby("key").size().sort_values(ascending=False).head(12)
            dd = pd.DataFrame({"issue": bug_counts.index, "qtd": bug_counts.values})
            ch = alt.Chart(dd).mark_bar().encode(
                x=alt.X("issue:N", sort=None, title=None),
                y=alt.Y("qtd:Q", title="Qtd"),
                color=alt.value("#ba55d3")
            ).properties(height=220)
            st.altair_chart(ch, use_container_width=True)
        else:
            st.info("Sem chave de issue para detalhamento.")

# debug
if __name__ == "__main__":
    pagina_dashboard_waves()
