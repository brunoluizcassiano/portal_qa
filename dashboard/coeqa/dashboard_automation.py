# coeqa/dashboard_automation.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from pathlib import Path
from datetime import datetime, date, timedelta

DATA = Path("config/data")

PROJ_COLS = ["id","key","name","projectTypeKey","lead"]

# Casos e Execuções do Zephyr (ajuste conforme nomes gerados no seu ETL)
Z_CASES_COLS = [
    "key","name","status","automated","testType","labels","created",
    "projectKey","environment","wave","component"
]
Z_EXEC_COLS  = [
    "executionKey","testKey","status","automated","testType","labels",
    "executedOn","projectKey","issueKey","environment","wave","component"
]

# =============== Utils / Helpers ===============
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

def pct(a, b):
    return float(a)/float(b)*100 if b not in (0, None, 0.0, np.nan) else 0.0

def lbl_auto(v):
    s = str(v).lower()
    if s in ["1","true","yes"]: return "Automated"
    if s in ["0","false","no"]: return "Manual"
    return "N/A"

def is_auto(row):
    # heurística ampla para “automated”
    fields = []
    for f in ("automated","testType","labels","name"):
        if f in row and pd.notna(row[f]): fields.append(str(row[f]).lower())
    s = " ".join(fields)
    return ("true" in s) or ("autom" in s)

def map_status(s):
    s = str(s).lower()
    if "pass" in s or "ok" in s or "done" in s: return "Pass"
    if "fail" in s or "error" in s: return "Fail"
    if "block" in s: return "Blocked"
    if "progress" in s: return "In Progress"
    if "not exec" in s: return "Not Executed"
    if "cancel" in s: return "Canceled"
    return "Others"

def norm_created(df: pd.DataFrame):
    if df.empty or "created" not in df.columns: return
    dt = pd.to_datetime(df["created"], errors="coerce")
    df["created_dt"]   = dt
    df["created_date"] = dt.dt.date
    df["created_month"]= dt.dt.strftime("%Y-%m")

def norm_executed(df: pd.DataFrame):
    if df.empty or "executedOn" not in df.columns: return
    dt = pd.to_datetime(df["executedOn"], errors="coerce")
    df["executed_dt"]   = dt
    df["executed_date"] = dt.dt.date
    df["executed_month"]= dt.dt.strftime("%Y-%m")

# =============== Página ===============
def pagina_dashboard_automation():
    try:
        st.set_page_config(page_title="Indicadores de Automação", layout="wide")
    except Exception:
        pass

    # -------- CSS (mesmo visual das demais) --------
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

    st.markdown("### Indicadores de Automação")

    # -------- Dados --------
    df_proj = safe_read_csv("jira_projetos_latest.csv", PROJ_COLS)
    df_cases = safe_read_csv("zephyr_testcases_latest.csv", Z_CASES_COLS)
    df_exec  = safe_read_csv("zephyr_executions_latest.csv", Z_EXEC_COLS)

    norm_created(df_cases)
    norm_executed(df_exec)

    # -------- Filtros superiores --------
    # Janela por execuções (se faltar, usa hoje)
    if not df_exec.empty and "executed_date" in df_exec.columns:
        pool = [to_date(x) for x in df_exec["executed_date"].dropna().tolist()]
        min_raw, max_raw = (min(pool), max(pool)) if pool else (date.today(), date.today())
    else:
        min_raw, max_raw = (date.today(), date.today())

    min_d, max_d = to_date(min_raw), to_date(max_raw)
    if min_d == max_d:
        min_d = max_d - timedelta(days=30)  # acolchoa p/ slider

    if "auto_periodo_master" not in st.session_state:
        st.session_state["auto_periodo_master"] = (min_d, max_d)
    ensure_range_key("auto_intervalo_cal",    st.session_state["auto_periodo_master"])
    ensure_range_key("auto_intervalo_slider", st.session_state["auto_periodo_master"])

    def on_cal_change():
        st.session_state["auto_periodo_master"]   = st.session_state["auto_intervalo_cal"]
        st.session_state["auto_intervalo_slider"] = st.session_state["auto_intervalo_cal"]

    def on_slider_change():
        st.session_state["auto_periodo_master"] = st.session_state["auto_intervalo_slider"]
        st.session_state["auto_intervalo_cal"]  = st.session_state["auto_intervalo_slider"]

    ctop0, ctop1, ctop2 = st.columns([0.52, 0.33, 0.15])
    with ctop0:
        ca, cb = st.columns(2)
        with ca:
            st.date_input("Date (calendário)", key="auto_intervalo_cal",
                          min_value=min_d, max_value=max_d, format="DD/MM/YYYY",
                          on_change=on_cal_change)
        with cb:
            st.slider("Date (slider)", key="auto_intervalo_slider",
                      min_value=min_d, max_value=max_d, format="DD/MM/YYYY",
                      on_change=on_slider_change)
    with ctop1:
        if not df_proj.empty:
            domains = ["Todos"] + sorted(df_proj["key"].dropna().unique().tolist())
        else:
            domains = ["Todos"] + sorted(list(set(df_exec.get("projectKey", pd.Series(dtype=str)).dropna().tolist())))
        sel_domain = st.selectbox("Domain (Projeto)", domains, index=0)

        env_opts = ["Todos"] + sorted(list(set(
            df_exec.get("environment", pd.Series(dtype=str)).dropna().astype(str).tolist() +
            df_cases.get("environment", pd.Series(dtype=str)).dropna().astype(str).tolist()
        ))) if ("environment" in df_exec.columns or "environment" in df_cases.columns) else ["Todos"]
        sel_env = st.selectbox("Environment", env_opts, index=0)

        wave_opts = ["Todos"] + sorted(list(set(
            df_exec.get("wave", pd.Series(dtype=str)).dropna().astype(str).tolist() +
            df_cases.get("wave", pd.Series(dtype=str)).dropna().astype(str).tolist()
        ))) if ("wave" in df_exec.columns or "wave" in df_cases.columns) else ["Todos"]
        sel_wave = st.selectbox("Wave", wave_opts, index=0)

    with ctop2:
        st.caption(datetime.now().strftime("Atualizado: %d/%m/%Y %H:%M"))

    d_start, d_end = st.session_state["auto_periodo_master"]

    # -------- Aplica filtros básicos --------
    def f_cases(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df
        out = df.copy()
        # opcional: filtrar período por created_date (caso deseje)
        if "created_date" in out.columns:
            out = out[(out["created_date"] <= d_end)]
        if sel_domain != "Todos" and "projectKey" in out.columns:
            out = out[out["projectKey"] == sel_domain]
        if sel_env != "Todos" and "environment" in out.columns:
            out = out[out["environment"].astype(str) == sel_env]
        if sel_wave != "Todos" and "wave" in out.columns:
            out = out[out["wave"].astype(str) == sel_wave]
        return out

    def f_exec(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df
        out = df.copy()
        if "executed_date" in out.columns:
            out = out[(out["executed_date"]>=d_start) & (out["executed_date"]<=d_end)]
        if sel_domain != "Todos" and "projectKey" in out.columns:
            out = out[out["projectKey"] == sel_domain]
        if sel_env != "Todos" and "environment" in out.columns:
            out = out[out["environment"].astype(str) == sel_env]
        if sel_wave != "Todos" and "wave" in out.columns:
            out = out[out["wave"].astype(str) == sel_wave]
        return out

    c_filtered = f_cases(df_cases)
    e_filtered = f_exec(df_exec)

    # Marca flag automated/categoria
    if not c_filtered.empty:
        c_filtered = c_filtered.copy()
        c_filtered["auto_flag"] = c_filtered.apply(is_auto, axis=1)
    if not e_filtered.empty:
        e_filtered = e_filtered.copy()
        e_filtered["auto_flag"] = e_filtered.apply(is_auto, axis=1)
        e_filtered["status_grp"] = e_filtered["status"].apply(map_status)

    # -------- KPIs --------
    total_cases = int(c_filtered.shape[0])
    automated_cases = int(c_filtered["auto_flag"].sum()) if "auto_flag" in c_filtered.columns else 0
    coverage_cases = pct(automated_cases, total_cases)

    total_exec = int(e_filtered.shape[0])
    auto_exec   = int(e_filtered["auto_flag"].sum()) if "auto_flag" in e_filtered.columns else 0
    manual_exec = total_exec - auto_exec

    auto_pass = int(((e_filtered["status_grp"]=="Pass") & (e_filtered["auto_flag"])).sum()) if not e_filtered.empty else 0
    auto_fail = int(((e_filtered["status_grp"]=="Fail") & (e_filtered["auto_flag"])).sum()) if not e_filtered.empty else 0
    auto_pass_rate = pct(auto_pass, auto_pass + auto_fail)

    backlog_to_automate = max(total_cases - automated_cases, 0)

    # “Estabilidade” (flakiness inversa nos automatizados)
    flaky_auto = 0
    stability_auto = 100.0
    if not e_filtered.empty and {"testKey","status_grp","auto_flag"}.issubset(e_filtered.columns):
        g = e_filtered[e_filtered["auto_flag"]].groupby("testKey")["status_grp"].apply(lambda s: set(s))
        flaky_auto = int(sum(1 for v in g.values if ("Pass" in v and "Fail" in v)))
        uniq = g.shape[0] if g.shape[0] else 1
        stability_auto = 100.0 - pct(flaky_auto, uniq)

    k = st.columns(6)
    with k[0]: st.metric("Total test cases", total_cases)
    with k[1]: st.metric("Automated cases", automated_cases, f"{coverage_cases:.2f}%")
    with k[2]: st.metric("Total executions", total_exec)
    with k[3]: st.metric("Automated executions", auto_exec)
    with k[4]: st.metric("Auto pass rate", f"{auto_pass_rate:.2f}%")
    with k[5]: st.metric("Automation stability", f"{stability_auto:.2f}%")

    st.caption(f"Backlog para automatizar: **{backlog_to_automate}** casos")

    st.markdown("---")

    # -------- Linha 1: Distribuição + Cobertura por Domain --------
    c1, c2 = st.columns([0.45, 0.55])

    with c1:
        st.markdown("#### Distribuição de casos (Automated × Manual × N/A)")
        if c_filtered.empty:
            st.info("Sem casos no filtro atual.")
        else:
            dist = c_filtered["auto_flag"].map(lambda x: "Automated" if x else "Manual").value_counts().rename_axis("tipo").reset_index(name="qtd")
            if "N/A" in c_filtered.get("automated", pd.Series(dtype=str)).astype(str).str.lower().tolist():
                # tentativa simples de detectar N/A; caso não exista, segue só com 2 fatias
                pass
            base = alt.Chart(dist).encode(theta="qtd:Q", color=alt.Color("tipo:N", title=None))
            chart = base.mark_arc(innerRadius=60)
            text  = base.mark_text(radius=80).encode(text="qtd:Q")
            st.altair_chart(chart + text, use_container_width=True)

    with c2:
        st.markdown("#### Cobertura de automação por Domain")
        if c_filtered.empty:
            st.info("Sem casos para calcular cobertura.")
        else:
            by_proj_total = c_filtered.groupby("projectKey").size().rename("total")
            by_proj_auto  = c_filtered[c_filtered["auto_flag"]].groupby("projectKey").size().rename("auto")
            df_cov = pd.concat([by_proj_total, by_proj_auto], axis=1).fillna(0)
            df_cov["coverage_%"] = (df_cov["auto"]/df_cov["total"]*100).round(2)
            df_cov = df_cov.reset_index().rename(columns={"index":"projectKey"})
            ch = alt.Chart(df_cov).mark_bar().encode(
                x=alt.X("projectKey:N", title=None, sort="-y"),
                y=alt.Y("coverage_%:Q", title="% automated cases"),
                tooltip=["projectKey","total","auto","coverage_%"]
            ).properties(height=280)
            st.altair_chart(ch, use_container_width=True)

    st.markdown("---")

    # -------- Linha 2: Tendência mensal + Top candidatos a automação --------
    c3, c4 = st.columns([0.55, 0.45])

    with c3:
        st.markdown("#### Tendência mensal de execuções (Automated × Manual)")
        if e_filtered.empty or "executed_month" not in e_filtered.columns:
            st.info("Sem execuções no período.")
        else:
            d = e_filtered.copy()
            d["kind"] = d["auto_flag"].map(lambda x: "Automated" if x else "Manual")
            agg = d.groupby(["executed_month","kind"]).size().reset_index(name="qtd")
            ch = alt.Chart(agg).mark_line(point=True).encode(
                x=alt.X("executed_month:N", title=None, sort=None),
                y=alt.Y("qtd:Q", title="Execuções"),
                color=alt.Color("kind:N", title=None)
            ).properties(height=280)
            st.altair_chart(ch, use_container_width=True)

    with c4:
        st.markdown("#### Top candidatos à automação (manuais mais executados)")
        if e_filtered.empty:
            st.info("Sem execuções.")
        else:
            d = e_filtered[~e_filtered["auto_flag"]].copy()
            if d.empty:
                st.success("Não há execuções manuais neste período 🎉")
            else:
                top = d.groupby("testKey").size().sort_values(ascending=False).head(20)
                df_top = pd.DataFrame({"testKey": top.index, "runs": top.values})
                ch = alt.Chart(df_top).mark_bar().encode(
                    x=alt.X("testKey:N", title=None, sort=None),
                    y=alt.Y("runs:Q", title="Execuções manuais"),
                    tooltip=["testKey","runs"]
                ).properties(height=280)
                st.altair_chart(ch, use_container_width=True)

    st.markdown("---")

    # -------- Linha 3: Pass/Fail automatizado por componente/feature --------
    st.markdown("#### Pass/Fail automatizado por Componente (Top 10)")
    if e_filtered.empty:
        st.info("Sem execuções.")
    else:
        d = e_filtered[e_filtered["auto_flag"]].copy()
        feat = None
        if "component" in d.columns and d["component"].notna().any():
            feat = d["component"].astype(str).str.split("[,;]").str[0].str.strip()
        elif "labels" in d.columns and d["labels"].notna().any():
            feat = d["labels"].astype(str).str.split("[,;]").str[0].str.strip()
        else:
            feat = d.get("projectKey", pd.Series(["N/A"]*len(d)))
        d["feature"] = feat
        d["grp"] = d["status"].apply(map_status)
        top_feats = d.groupby("feature").size().sort_values(ascending=False).head(10).index
        dd = d[d["feature"].isin(top_feats)]
        agg = dd.groupby(["feature","grp"]).size().reset_index(name="qtd")
        # foca em Pass e Fail
        agg = agg[agg["grp"].isin(["Pass","Fail"])]
        ch = alt.Chart(agg).mark_bar().encode(
            y=alt.Y("feature:N", sort="-x", title=None),
            x=alt.X("qtd:Q", title="Qtd"),
            color=alt.Color("grp:N", title=None)
        ).properties(height=320)
        st.altair_chart(ch, use_container_width=True)

    st.markdown("---")

    # -------- Amostra de execuções automatizadas recentes --------
    st.markdown("#### Execuções automatizadas recentes (amostra)")
    if e_filtered.empty:
        st.info("Sem execuções.")
    else:
        d = e_filtered[e_filtered["auto_flag"]].copy()
        if "executed_dt" in d.columns:
            d = d.sort_values("executed_dt", ascending=False)
        cols = [c for c in ["executedOn","projectKey","testKey","status","environment","wave","issueKey","component"] if c in d.columns]
        st.dataframe(d[cols].head(200), use_container_width=True)

# debug local
if __name__ == "__main__":
    pagina_dashboard_automation()
