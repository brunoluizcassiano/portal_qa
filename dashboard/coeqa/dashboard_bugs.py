# coeqa/dashboard_bugs.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from pathlib import Path
from datetime import datetime, date, timedelta

DATA = Path("config/data")

ISSUE_COLS = ["key","summary","status","type","priority","created","resolutiondate","assignee","reporter"]
PROJ_COLS  = ["id","key","name","projectTypeKey","lead"]

# ----------------- utils -----------------
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
            df = df[keep]
        return df
    except Exception:
        return pd.DataFrame(columns=columns or [])

def key_project_prefix(key: str) -> str:
    if isinstance(key, str) and "-" in key:
        return key.split("-")[0]
    return ""

def _normalize_dates(df: pd.DataFrame):
    # cria created_dt/date e resolved_dt/date
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

def _ensure_range_key(key: str, fallback: tuple[date,date]):
    v = st.session_state.get(key)
    if isinstance(v, (list,tuple)) and len(v)==2:
        st.session_state[key] = (to_date(v[0]), to_date(v[1]))
    elif isinstance(v, date):
        st.session_state[key] = (v, v)
    else:
        st.session_state[key] = fallback

def to_date(x):
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return date.today()

def _days_between(a, b):
    if pd.isna(a) or pd.isna(b): return np.nan
    return (b - a).days + (b - a).seconds/86400

def _bucketize_days(d):
    # buckets semelhantes aos que você mostrou
    if pd.isna(d): return "N/A"
    x = float(d)
    if x <= 2:    return "≤ 2 days"
    if x <= 3:    return "≤ 3 days"
    if x <= 10:   return "≤ 10 days"
    if x <= 30:   return "≤ 30 days"
    if x <= 60:   return "≤ 60 days"
    return  "> 60 days"

# ----------------- página -----------------
def pagina_dashboard_bugs():
    try:
        st.set_page_config(page_title="Bugs", layout="wide")
    except Exception:
        pass

    # ====== ESTILO ======
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

    st.markdown("### Bugs & Sub-bugs")

    # ====== Carrega bases ======
    df_bug    = safe_read_csv("jira_issues_bug_latest.csv",    ISSUE_COLS)
    df_subbug = safe_read_csv("jira_issues_subbug_latest.csv", ISSUE_COLS)
    df_proj   = safe_read_csv("jira_projetos_latest.csv",      PROJ_COLS)

    # prepara projectKey + datas
    for d in (df_bug, df_subbug):
        if not d.empty:
            if "projectKey" not in d.columns:
                d["projectKey"] = d["key"].apply(key_project_prefix)
            _normalize_dates(d)

    # ====== Filtros (Data + Domain) ======
    # usamos intervalo pela data de criação (Created)
    pool = []
    for d in (df_bug, df_subbug):
        if "created_date" in d.columns:
            pool += [to_date(x) for x in d["created_date"].dropna().tolist()]

    if pool:
        min_d_raw, max_d_raw = min(pool), max(pool)
    else:
        min_d_raw, max_d_raw = date.today(), date.today()

    # Garante date puro e evita min==max no slider
    min_d, max_d = to_date(min_d_raw), to_date(max_d_raw)
    if min_d == max_d:
        # abre uma janela de 30 dias para não quebrar o slider
        min_d = max_d - timedelta(days=30)

    if "bugs_periodo_master" not in st.session_state:
        st.session_state["bugs_periodo_master"] = (min_d, max_d)

    _ensure_range_key("bugs_intervalo_data",   st.session_state["bugs_periodo_master"])
    _ensure_range_key("bugs_intervalo_slider", st.session_state["bugs_periodo_master"])

    def _on_calendar_change():
        st.session_state["bugs_periodo_master"] = st.session_state["bugs_intervalo_data"]
        st.session_state["bugs_intervalo_slider"] = st.session_state["bugs_intervalo_data"]

    def _on_slider_change():
        st.session_state["bugs_periodo_master"] = st.session_state["bugs_intervalo_slider"]
        st.session_state["bugs_intervalo_data"] = st.session_state["bugs_intervalo_slider"]

    c0, c1, c2 = st.columns([0.50, 0.30, 0.20])
    with c0:
        if not df_proj.empty:
            projects = ["Todos"] + sorted(df_proj["key"].dropna().unique().tolist())
        else:
            pref = []
            for d in (df_bug, df_subbug):
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
            st.date_input("Date (calendário)",
                          key="bugs_intervalo_data",
                          min_value=min_d, max_value=max_d,
                          format="DD/MM/YYYY",
                          on_change=_on_calendar_change)
        with cb:
            st.slider("Date (slider)",
                      key="bugs_intervalo_slider",
                      min_value=min_d, max_value=max_d,
                      format="DD/MM/YYYY",
                      on_change=_on_slider_change)
    with c1:
        st.caption("")
    with c2:
        st.caption("")

    d_start, d_end = st.session_state["bugs_periodo_master"]

    def f_proj(df, col="projectKey"):
        if df.empty: return df
        return df if sel_project=="Todos" else df[df[col]==sel_project]

    def f_period_created(df):
        if df.empty or "created_date" not in df.columns: return df
        return df[(df["created_date"]>=d_start) & (df["created_date"]<=d_end)].copy()

    # aplica filtros
    fb = f_proj(f_period_created(df_bug))
    fs = f_proj(f_period_created(df_subbug))

    # ====== KPIs ======
    total = int(fb.shape[0] + fs.shape[0])

    def is_closed(s):
        s = str(s).lower()
        return ("done" in s) or ("closed" in s) or ("resolvido" in s) or ("resolvida" in s)

    def is_cancelled(s):
        s = str(s).lower()
        return "cancel" in s

    closed = int(fb["status"].apply(is_closed).sum() + fs["status"].apply(is_closed).sum())
    cancelled = int(fb["status"].apply(is_cancelled).sum() + fs["status"].apply(is_cancelled).sum())
    open_ = total - closed - cancelled

    # AVG days resolution (bugs resolvidos)
    for d in (fb, fs):
        if "created_dt" not in d.columns: d["created_dt"] = pd.to_datetime(d.get("created"), errors="coerce")
        if "resolved_dt" not in d.columns: d["resolved_dt"] = pd.to_datetime(d.get("resolutiondate"), errors="coerce")

    def _avg_days(df):
        if df.empty: return np.nan
        d = df.dropna(subset=["created_dt","resolved_dt"]).copy()
        if d.empty: return np.nan
        dd = (d["resolved_dt"] - d["created_dt"]).dt.total_seconds()/86400
        return float(dd.mean()) if not dd.empty else np.nan

    avg_days = _avg_days(pd.concat([fb,fs], ignore_index=True))

    k = st.columns(6)
    with k[0]:
        st.metric("Total (Bug + Sub-bug)", total)
    with k[1]:
        st.metric("Closed", closed)
    with k[2]:
        st.metric("Cancelled", cancelled)
    with k[3]:
        st.metric("Open", open_)
    with k[4]:
        st.metric("AVG days resolution Bug", f"{avg_days:.2f} days" if not np.isnan(avg_days) else "0.00 days")
    with k[5]:
        st.metric("Bug / Sub-bug", f"{int(fb.shape[0])} / {int(fs.shape[0])}")

    st.markdown("---")

    # ====== Bugs Created, Closed & Open Monthly
    st.markdown("#### Bugs Created, Closed & Open Monthly")
    df_all = pd.concat([fb.assign(kind="Bug"), fs.assign(kind="Sub-bug")], ignore_index=True)

    created_m = df_all.groupby("created_month").size().rename("Created")
    if "resolved_month" not in df_all.columns:
        df_all["resolved_month"] = pd.to_datetime(df_all["resolutiondate"], errors="coerce").dt.strftime("%Y-%m")
    closed_mask = df_all["status"].apply(is_closed)
    closed_m = df_all[closed_mask].groupby("resolved_month").size().rename("Closed")

    idx = sorted(set(created_m.index).union(set(closed_m.index)))
    df_month = pd.DataFrame(index=idx)
    df_month["Created"] = created_m.reindex(idx).fillna(0).astype(int)
    df_month["Closed"]  = closed_m.reindex(idx).fillna(0).astype(int)
    df_month["Open"]    = (df_month["Created"].cumsum() - df_month["Closed"].cumsum()).astype(int)
    df_month = df_month.reset_index().rename(columns={"index":"month"})

    if df_month.empty:
        st.info("Sem dados mensais para o período selecionado.")
    else:
        df_m_long = df_month.melt(id_vars="month", var_name="tipo", value_name="qtd")
        ch = alt.Chart(df_m_long).mark_bar().encode(
            x=alt.X("month:N", title=None, sort=None),
            y=alt.Y("qtd:Q", title="Quantidade"),
            color=alt.Color("tipo:N", title=None)
        ).properties(height=240)
        st.altair_chart(ch, use_container_width=True)

    cA, cB = st.columns([0.55, 0.45])

    # ====== Critical (Priority P1..P5)
    with cA:
        st.markdown("#### Critical (por prioridade)")
        if df_all.empty or "priority" not in df_all.columns:
            st.info("Sem dados de prioridade.")
        else:
            pr = df_all["priority"].astype(str).str.upper().str.extract(r'(P[1-5])', expand=False).fillna("P?")
            df_pr = pr.value_counts().rename_axis("priority").reset_index(name="qtd")
            order = ["P1","P2","P3","P4","P5","P?"]
            df_pr["priority"] = pd.Categorical(df_pr["priority"], categories=order, ordered=True)
            df_pr = df_pr.sort_values("priority")
            ch = alt.Chart(df_pr).mark_bar().encode(
                x=alt.X("qtd:Q", title="Quantidade"),
                y=alt.Y("priority:N", title=None, sort=None),
                color=alt.Color("priority:N", legend=None)
            ).properties(height=220)
            st.altair_chart(ch, use_container_width=True)

    # ====== Status Bug (donut)
    with cB:
        st.markdown("#### % Status Bug")
        if df_all.empty or "status" not in df_all.columns:
            st.info("Sem dados de status.")
        else:
            def status_group(s):
                s = str(s).lower()
                if is_closed(s):    return "Done"
                if is_cancelled(s): return "Cancelled"
                return "Open"
            stc = df_all["status"].apply(status_group).value_counts().reset_index()
            stc.columns = ["status","qtd"]
            stc["pct"] = (stc["qtd"] / stc["qtd"].sum()*100).round(2)
            base = alt.Chart(stc).encode(theta="qtd:Q", color="status:N")
            pie  = base.mark_arc(innerRadius=60)
            text = base.mark_text(radius=80).encode(text="pct:Q")
            st.altair_chart(pie + text, use_container_width=True)

    st.markdown("---")

    c1, c2 = st.columns(2)

    # ====== Open Bug Elapsed Time
    with c1:
        st.markdown("#### Open Bug Elapsed Time")
        if df_all.empty:
            st.info("Sem dados.")
        else:
            now = pd.Timestamp.utcnow()
            open_mask = ~(df_all["status"].apply(is_closed) | df_all["status"].apply(is_cancelled))
            open_df = df_all[open_mask].copy()
            if open_df.empty:
                st.info("Sem bugs abertos.")
            else:
                if "created_dt" not in open_df.columns:
                    open_df["created_dt"] = pd.to_datetime(open_df["created"], errors="coerce")
                open_df["elapsed_days"] = open_df["created_dt"].apply(lambda c: _days_between(c, now))
                open_df["bucket"] = open_df["elapsed_days"].apply(_bucketize_days)
                order = ["≤ 2 days","≤ 3 days","≤ 10 days","≤ 30 days","≤ 60 days","> 60 days","N/A"]
                open_df["bucket"] = pd.Categorical(open_df["bucket"], categories=order, ordered=True)
                df_count = open_df.groupby("bucket").size().reset_index(name="qtd").sort_values("bucket")
                ch = alt.Chart(df_count).mark_bar().encode(
                    x=alt.X("bucket:N", title=None, sort=order),
                    y=alt.Y("qtd:Q", title="Quantidade"),
                    color=alt.Color("bucket:N", legend=None)
                ).properties(height=260)
                st.altair_chart(ch, use_container_width=True)

    # ====== Closed Bug Elapsed Time
    with c2:
        st.markdown("#### Closed Bug Elapsed Time")
        if df_all.empty:
            st.info("Sem dados.")
        else:
            closed_df = df_all[df_all["status"].apply(is_closed)].copy()
            if closed_df.empty:
                st.info("Sem bugs fechados.")
            else:
                if "created_dt" not in closed_df.columns:
                    closed_df["created_dt"]   = pd.to_datetime(closed_df["created"], errors="coerce")
                if "resolved_dt" not in closed_df.columns:
                    closed_df["resolved_dt"]  = pd.to_datetime(closed_df["resolutiondate"], errors="coerce")
                closed_df = closed_df.dropna(subset=["created_dt","resolved_dt"])
                closed_df["elapsed_days"] = (closed_df["resolved_dt"] - closed_df["created_dt"]).dt.total_seconds()/86400
                closed_df["bucket"] = closed_df["elapsed_days"].apply(_bucketize_days)
                order = ["≤ 2 days","≤ 3 days","≤ 10 days","≤ 30 days","≤ 60 days","> 60 days","N/A"]
                closed_df["bucket"] = pd.Categorical(closed_df["bucket"], categories=order, ordered=True)
                df_count = closed_df.groupby("bucket").size().reset_index(name="qtd").sort_values("bucket")
                ch = alt.Chart(df_count).mark_bar().encode(
                    x=alt.X("bucket:N", title=None, sort=order),
                    y=alt.Y("qtd:Q", title="Quantidade"),
                    color=alt.Color("bucket:N", legend=None)
                ).properties(height=260)
                st.altair_chart(ch, use_container_width=True)

# debug
if __name__ == "__main__":
    pagina_dashboard_bugs()
