# coeqa/dashboard_regression.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from pathlib import Path
from datetime import datetime, date, timedelta

DATA = Path("config/data")

Z_CASES_COLS = [
    "key","name","status","automated","testType","labels","created",
    "projectKey","environment","wave"
]
Z_EXEC_COLS = [
    "executionKey","testKey","status","automated","testType","labels",
    "executedOn","projectKey","issueKey","environment","wave"
]
PROJ_COLS = ["id","key","name","projectTypeKey","lead"]

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
            if keep: df = df[keep]
        return df
    except Exception:
        return pd.DataFrame(columns=columns or [])

def to_date(x):
    if isinstance(x, date) and not isinstance(x, datetime): return x
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return date.today()

def ensure_range_key(key: str, fallback: tuple[date,date]):
    v = st.session_state.get(key)
    if isinstance(v, (list,tuple)) and len(v)==2:
        st.session_state[key] = (to_date(v[0]), to_date(v[1]))
    elif isinstance(v, date):
        st.session_state[key] = (v, v)
    else:
        st.session_state[key] = fallback

def caption_ts():
    st.caption(datetime.now().strftime("Atualizado: %d/%m/%Y %H:%M"))

def pct(a,b):
    return float(a)/float(b)*100 if b not in (0,None,0.0,np.nan) else 0.0

def norm_exec_dates(df: pd.DataFrame, col="executedOn"):
    if df.empty or col not in df.columns: return
    dt = pd.to_datetime(df[col], errors="coerce")
    df["executed_dt"]   = dt
    df["executed_date"] = dt.dt.date
    df["executed_month"]= dt.dt.strftime("%Y-%m")

def label_auto(v):
    s = str(v).lower()
    if s in ["1","true","yes"]: return "Automated"
    if s in ["0","false","no"]: return "Manual"
    return "N/A"

def map_status(s):
    s = str(s).lower()
    if "pass" in s or "ok" in s or "done" in s: return "Pass"
    if "fail" in s or "error" in s:              return "Fail"
    if "block" in s:                              return "Blocked"
    if "progress" in s:                           return "In Progress"
    if "not exec" in s:                           return "Not Executed"
    if "cancel" in s:                             return "Canceled"
    return "Others"

def detect_regression_row(row, fields=("testType","labels","name","key")):
    """Heurística: considera regression se 'regress' aparecer em testType/labels/name/key."""
    for f in fields:
        if f in row and pd.notna(row[f]) and "regress" in str(row[f]).lower():
            return True
    return False

# ----------------- página -----------------
def pagina_dashboard_regression():
    try:
        st.set_page_config(page_title="Testes Regressivos", layout="wide")
    except Exception:
        pass

    # === CSS base (mesmo visual dos outros) ===
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

    st.markdown("### Testes Regressivos")

    # === Dados ===
    df_proj = safe_read_csv("jira_projetos_latest.csv", PROJ_COLS)
    df_cases = safe_read_csv("zephyr_testcases_latest.csv", Z_CASES_COLS)
    df_exec  = safe_read_csv("zephyr_executions_latest.csv", Z_EXEC_COLS)

    # normaliza datas de execução
    norm_exec_dates(df_exec)

    # === Filtros topo ===
    # janela de datas baseada em execuções
    if not df_exec.empty and "executed_date" in df_exec.columns:
        pool = [to_date(x) for x in df_exec["executed_date"].dropna().tolist()]
        min_raw, max_raw = (min(pool), max(pool)) if pool else (date.today(), date.today())
    else:
        min_raw, max_raw = (date.today(), date.today())

    min_d, max_d = to_date(min_raw), to_date(max_raw)
    if min_d == max_d:
        min_d = max_d - timedelta(days=30)  # acolchoa para o slider

    if "reg_periodo_master" not in st.session_state:
        st.session_state["reg_periodo_master"] = (min_d, max_d)
    ensure_range_key("reg_intervalo_cal",   st.session_state["reg_periodo_master"])
    ensure_range_key("reg_intervalo_slider",st.session_state["reg_periodo_master"])

    def on_cal_change():
        st.session_state["reg_periodo_master"]  = st.session_state["reg_intervalo_cal"]
        st.session_state["reg_intervalo_slider"]= st.session_state["reg_intervalo_cal"]

    def on_slider_change():
        st.session_state["reg_periodo_master"]  = st.session_state["reg_intervalo_slider"]
        st.session_state["reg_intervalo_cal"]   = st.session_state["reg_intervalo_slider"]

    ctop0, ctop1, ctop2 = st.columns([0.52, 0.33, 0.15])
    with ctop0:
        ca, cb = st.columns(2)
        with ca:
            st.date_input("Date (calendário)", key="reg_intervalo_cal",
                          min_value=min_d, max_value=max_d, format="DD/MM/YYYY",
                          on_change=on_cal_change)
        with cb:
            st.slider("Date (slider)", key="reg_intervalo_slider",
                      min_value=min_d, max_value=max_d, format="DD/MM/YYYY",
                      on_change=on_slider_change)
    with ctop1:
        if not df_proj.empty:
            domains = ["Todos"] + sorted(df_proj["key"].dropna().unique().tolist())
        else:
            domains = ["Todos"] + sorted(list(set(df_exec.get("projectKey", pd.Series(dtype=str)).dropna().tolist())))
        sel_domain = st.selectbox("Domain (Projeto)", options=domains, index=0)

        env_opts = ["Todos"] + sorted(list(set(
            df_exec.get("environment", pd.Series(dtype=str)).dropna().astype(str).tolist()
        ))) if "environment" in df_exec.columns else ["Todos"]
        sel_env = st.selectbox("Environment", env_opts, index=0)

        wave_opts = ["Todos"] + sorted(list(set(
            df_exec.get("wave", pd.Series(dtype=str)).dropna().astype(str).tolist()
        ))) if "wave" in df_exec.columns else ["Todos"]
        sel_wave = st.selectbox("Wave", wave_opts, index=0)

    with ctop2:
        caption_ts()

    d_start, d_end = st.session_state["reg_periodo_master"]

    # Detector de regressão (opções)
    with st.expander("Configurar detecção de testes regressivos", expanded=False):
        use_testtype = st.checkbox("Detectar por testType contém 'regress'", value=True)
        use_labels   = st.checkbox("Detectar por labels contém 'regress'", value=True)
        use_namekey  = st.checkbox("Detectar por nome/chave contém 'regress'", value=False)
        st.caption("Marque as heurísticas que valem para identificar casos/execuções de regressão.")

    # aplica filtros básicos
    def apply_basic_filters(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df
        out = df.copy()
        if "executed_date" in out.columns:
            out = out[(out["executed_date"]>=d_start) & (out["executed_date"]<=d_end)]
        if sel_domain != "Todos" and "projectKey" in out.columns:
            out = out[out["projectKey"]==sel_domain]
        if sel_env != "Todos" and "environment" in out.columns:
            out = out[out["environment"].astype(str)==sel_env]
        if sel_wave != "Todos" and "wave" in out.columns:
            out = out[out["wave"].astype(str)==sel_wave]
        return out

    df_exec_f = apply_basic_filters(df_exec)

    # marca regressivo
    def mark_regression_df(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df
        df = df.copy()
        fields = []
        if use_testtype: fields += ["testType"]
        if use_labels:   fields += ["labels"]
        if use_namekey:  fields += ["name","key","testKey"]
        if not fields:   fields = ["testType","labels","name","key","testKey"]
        df["is_regression"] = df.apply(lambda r: detect_regression_row(r, fields=tuple(fields)), axis=1)
        return df

    df_exec_f = mark_regression_df(df_exec_f)
    df_reg = df_exec_f[df_exec_f["is_regression"]] if "is_regression" in df_exec_f.columns else pd.DataFrame(columns=df_exec_f.columns)

    # === KPIs ===
    total_reg = int(df_reg.shape[0])
    auto_reg  = df_reg["automated"].apply(lambda v: label_auto(v)=="Automated").sum() if "automated" in df_reg.columns else 0

    status_map = df_reg["status"].apply(map_status) if "status" in df_reg.columns else pd.Series(dtype=str)
    n_pass = int((status_map=="Pass").sum())
    n_fail = int((status_map=="Fail").sum())
    n_total = int(status_map.shape[0])

    pass_rate = pct(n_pass, n_total)
    fail_rate = pct(n_fail, n_total)
    auto_rate = pct(auto_reg, total_reg)

    # flakiness (mesmo teste com pass e fail no período)
    flaky = 0
    stability = 100.0
    if not df_reg.empty and {"testKey","status"}.issubset(df_reg.columns):
        g = df_reg.groupby("testKey")["status"].apply(lambda s: set(map_status(x) for x in s))
        flaky = int(sum(1 for v in g.values if ("Pass" in v and "Fail" in v)))
        unique_tests = g.shape[0]
        # estabilidade inversamente proporcional à flakiness
        stability = 100.0 - pct(flaky, unique_tests if unique_tests else 1)

    k = st.columns(6)
    with k[0]: st.metric("Total Regression Execs", total_reg)
    with k[1]: st.metric("% Automated", f"{auto_rate:.2f}%")
    with k[2]: st.metric("Pass rate", f"{pass_rate:.2f}%")
    with k[3]: st.metric("Fail rate", f"{fail_rate:.2f}%")
    with k[4]: st.metric("# Flaky tests", flaky)
    with k[5]: st.metric("Stability score", f"{stability:.2f}%")

    st.markdown("---")

    c1, c2 = st.columns([0.55, 0.45])

    # === Tendência mensal
    with c1:
        st.markdown("#### Tendência mensal (Execuções / Pass / Fail)")
        if df_reg.empty or "executed_month" not in df_reg.columns:
            st.info("Sem execuções de regressão no período.")
        else:
            d = df_reg.copy()
            d["grp"] = d["status"].apply(map_status)
            all_cnt  = d.groupby("executed_month").size().rename("Execuções")
            pass_cnt = d[d["grp"]=="Pass"].groupby("executed_month").size().rename("Pass")
            fail_cnt = d[d["grp"]=="Fail"].groupby("executed_month").size().rename("Fail")
            idx = sorted(set(all_cnt.index) | set(pass_cnt.index) | set(fail_cnt.index))
            m = pd.DataFrame(index=idx)
            for s in (all_cnt, pass_cnt, fail_cnt):
                m = m.join(s, how="left")
            m = m.fillna(0).astype(int).reset_index().rename(columns={"index":"month"})
            melt = m.melt(id_vars="month", var_name="tipo", value_name="qtd")
            ch = alt.Chart(melt).mark_line(point=True).encode(
                x=alt.X("month:N", title=None, sort=None),
                y=alt.Y("qtd:Q", title="Quantidade"),
                color=alt.Color("tipo:N", title=None)
            ).properties(height=280)
            st.altair_chart(ch, use_container_width=True)

    # === Pass rate por projeto
    with c2:
        st.markdown("#### Pass rate por Domain")
        if df_reg.empty or "projectKey" not in df_reg.columns:
            st.info("Sem dados por projeto.")
        else:
            d = df_reg.copy()
            d["grp"] = d["status"].apply(map_status)
            tot = d.groupby("projectKey").size()
            pas = d[d["grp"]=="Pass"].groupby("projectKey").size()
            dfp = pd.DataFrame({"total":tot, "pass":pas}).fillna(0)
            dfp["pass_rate"] = (dfp["pass"]/dfp["total"]*100).round(2)
            dfp = dfp.sort_values("pass_rate", ascending=False).reset_index()
            ch = alt.Chart(dfp).mark_bar().encode(
                x=alt.X("projectKey:N", title=None, sort=None),
                y=alt.Y("pass_rate:Q", title="% Pass"),
                tooltip=["projectKey","total","pass","pass_rate"]
            ).properties(height=280)
            st.altair_chart(ch, use_container_width=True)

    st.markdown("---")

    c3, c4 = st.columns([0.55, 0.45])

    # === Top falhas por teste
    with c3:
        st.markdown("#### Top testes com mais falhas")
        if df_reg.empty or "testKey" not in df_reg.columns:
            st.info("Sem dados.")
        else:
            d = df_reg.copy()
            d["grp"] = d["status"].apply(map_status)
            fails = d[d["grp"]=="Fail"].groupby("testKey").size().sort_values(ascending=False).head(20)
            top = pd.DataFrame({"testKey":fails.index, "fails":fails.values})
            ch = alt.Chart(top).mark_bar().encode(
                x=alt.X("testKey:N", title=None, sort=None),
                y=alt.Y("fails:Q", title="Falhas"),
                tooltip=["testKey","fails"]
            ).properties(height=280)
            st.altair_chart(ch, use_container_width=True)

    # === Flaky tests
    with c4:
        st.markdown("#### Flaky tests (pass + fail no período)")
        if df_reg.empty or "testKey" not in df_reg.columns:
            st.info("Sem dados.")
        else:
            d = df_reg.copy()
            d["grp"] = d["status"].apply(map_status)
            g = d.groupby("testKey")["grp"].apply(lambda s: set(s))
            flaky_keys = [k for k,v in g.items() if ("Pass" in v and "Fail" in v)]
            if not flaky_keys:
                st.success("Nenhum flaky test identificado no período selecionado. 🎉")
            else:
                dd = d[d["testKey"].isin(flaky_keys)]
                # taxa de flakiness = fails / total por testKey
                met = dd.pivot_table(index="testKey", columns="grp", values="status", aggfunc="count").fillna(0)
                met["total"] = met.sum(axis=1)
                met["flaky_rate"] = (met.get("Fail",0)/met["total"]*100).round(2)
                met = met.sort_values("flaky_rate", ascending=False).reset_index().head(20)
                ch = alt.Chart(met).mark_bar().encode(
                    x=alt.X("testKey:N", title=None, sort=None),
                    y=alt.Y("flaky_rate:Q", title="% Flaky (fails/total)"),
                    tooltip=list(met.columns)
                ).properties(height=280)
                st.altair_chart(ch, use_container_width=True)

    st.markdown("---")

    # === Amostra das últimas execuções
    st.markdown("#### Últimas execuções (amostra)")
    if df_reg.empty:
        st.info("Sem execuções regressivas.")
    else:
        d = df_reg.copy()
        if "executed_dt" in d.columns:
            d = d.sort_values("executed_dt", ascending=False)
        cols_show = [c for c in ["executedOn","projectKey","testKey","status","automated","environment","wave","issueKey"] if c in d.columns]
        st.dataframe(d[cols_show].head(200), use_container_width=True)

# debug
if __name__ == "__main__":
    pagina_dashboard_regression()
