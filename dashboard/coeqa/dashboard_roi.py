# coeqa/dashboard_roi.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from pathlib import Path
from datetime import datetime, date, timedelta

DATA = Path("config/data")

# Bases Zephyr
Z_CASES_COLS = [
    "key","name","status","automated","testType","labels","created",
    "projectKey","environment","wave","component"
]
Z_EXEC_COLS  = [
    "executionKey","testKey","status","automated","testType","labels",
    "executedOn","projectKey","issueKey","environment","wave","component"
]
PROJ_COLS = ["id","key","name","projectTypeKey","lead"]

# =================== Utils ===================
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

def pct(a,b):
    return float(a)/float(b)*100 if b not in (0, None, 0.0, np.nan) else 0.0

def lbl_auto(v):
    s = str(v).lower()
    if s in ["1","true","yes"]: return "Automated"
    if s in ["0","false","no"]: return "Manual"
    return "N/A"

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

# =================== Página ===================
def pagina_dashboard_roi():
    try:
        st.set_page_config(page_title="ROI da Qualidade", layout="wide")
    except Exception:
        pass

    # -------- CSS padrão das telas --------
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

    st.markdown("### ROI da Qualidade")

    # --------- Dados ---------
    df_proj = safe_read_csv("jira_projetos_latest.csv", PROJ_COLS)
    df_cases = safe_read_csv("zephyr_testcases_latest.csv", Z_CASES_COLS)
    df_exec  = safe_read_csv("zephyr_executions_latest.csv", Z_EXEC_COLS)

    norm_created(df_cases)
    norm_executed(df_exec)

    # --------- Filtros superiores ---------
    # Datas via execuções
    if not df_exec.empty and "executed_date" in df_exec.columns:
        pool = [to_date(x) for x in df_exec["executed_date"].dropna().tolist()]
        min_raw, max_raw = (min(pool), max(pool)) if pool else (date.today(), date.today())
    else:
        min_raw, max_raw = (date.today(), date.today())

    min_d, max_d = to_date(min_raw), to_date(max_raw)
    if min_d == max_d:
        min_d = max_d - timedelta(days=30)  # acolchoa p/ slider

    if "roi_periodo_master" not in st.session_state:
        st.session_state["roi_periodo_master"] = (min_d, max_d)
    ensure_range_key("roi_intervalo_cal",    st.session_state["roi_periodo_master"])
    ensure_range_key("roi_intervalo_slider", st.session_state["roi_periodo_master"])

    def on_cal_change():
        st.session_state["roi_periodo_master"]   = st.session_state["roi_intervalo_cal"]
        st.session_state["roi_intervalo_slider"] = st.session_state["roi_intervalo_cal"]

    def on_slider_change():
        st.session_state["roi_periodo_master"] = st.session_state["roi_intervalo_slider"]
        st.session_state["roi_intervalo_cal"]  = st.session_state["roi_intervalo_slider"]

    top0, top1, top2 = st.columns([0.52, 0.33, 0.15])
    with top0:
        ca, cb = st.columns(2)
        with ca:
            st.date_input("Date (calendário)", key="roi_intervalo_cal",
                          min_value=min_d, max_value=max_d, format="DD/MM/YYYY",
                          on_change=on_cal_change)
        with cb:
            st.slider("Date (slider)", key="roi_intervalo_slider",
                      min_value=min_d, max_value=max_d, format="DD/MM/YYYY",
                      on_change=on_slider_change)
    with top1:
        # Domain (Projeto)
        if not df_proj.empty:
            domains = ["Todos"] + sorted(df_proj["key"].dropna().unique().tolist())
        else:
            domains = ["Todos"] + sorted(list(set(df_exec.get("projectKey", pd.Series(dtype=str)).dropna().tolist())))
        sel_domain = st.selectbox("Domain (Projeto)", domains, index=0)

        # Environment / Wave (opcionais)
        env_opts = ["Todos"] + sorted(list(set(
            df_exec.get("environment", pd.Series(dtype=str)).dropna().astype(str).tolist()
        ))) if "environment" in df_exec.columns else ["Todos"]
        sel_env = st.selectbox("Environment", env_opts, index=0)

        wave_opts = ["Todos"] + sorted(list(set(
            df_exec.get("wave", pd.Series(dtype=str)).dropna().astype(str).tolist()
        ))) if "wave" in df_exec.columns else ["Todos"]
        sel_wave = st.selectbox("Wave", wave_opts, index=0)
    with top2:
        st.caption(datetime.now().strftime("Atualizado: %d/%m/%Y %H:%M"))

    d_start, d_end = st.session_state["roi_periodo_master"]

    # --------- Parâmetros de Custo / Assunções ---------
    with st.expander("Parâmetros do modelo (ajuste para sua realidade)", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            custo_exec_manual = st.number_input("Custo por execução manual (R$)", min_value=0.0, value=12.0, step=1.0, help="Tempo da execução x custo hora. Ex: 6 min ~ R$12.")
            custo_dev_automacao_por_teste = st.number_input("Custo p/ desenvolver 1 teste automatizado (R$)", min_value=0.0, value=300.0, step=10.0)
        with c2:
            custo_manutencao_por_exec = st.number_input("Custo de manutenção por execução automatizada (R$)", min_value=0.0, value=0.80, step=0.10, help="Infra + flakiness + ajuste fino.")
            vida_util_execucoes = st.number_input("Vida útil média de um teste (execuções)", min_value=1, value=200, step=10, help="Depois disso, assume-se refactor/obsolescência.")
        with c3:
            custo_bug_pre = st.number_input("Custo p/ corrigir bug PRÉ-produção (R$)", min_value=0.0, value=300.0, step=10.0)
            custo_bug_pos = st.number_input("Custo p/ corrigir bug PÓS-produção (R$)", min_value=0.0, value=3000.0, step=50.0)
        st.caption("Dica: comece conservador e ajuste após 1–2 sprints com dados reais.")

    delta_bug = max(custo_bug_pos - custo_bug_pre, 0.0)

    with st.expander("Suposições de detecção", expanded=False):
        c4, c5, c6 = st.columns(3)
        with c4:
            frac_exec_regressivo = st.slider("Fração de execuções com escopo regressivo", 0.0, 1.0, 0.6, 0.05,
                                             help="Quanto das execuções automatizadas cobrem regressão.")
        with c5:
            taxa_escaparia_sem_teste = st.slider("Dos fails, % que escapariam p/ produção sem os testes", 0.0, 1.0, 0.35, 0.05)
        with c6:
            aproveitamento_suite = st.slider("Aproveitamento médio da suíte (%)", 0, 100, 85, 5, help="Penaliza suíte instável/desatualizada.")
        aproveitamento_suite = aproveitamento_suite / 100.0

    # --------- Filtragem base ---------
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

    e = f_exec(df_exec)
    if not e.empty:
        # flags
        e = e.copy()
        e["auto_flag"] = e.apply(lambda r: ("autom" in f"{r.get('automated','')}{r.get('testType','')}{r.get('labels','')}".lower()) or (str(r.get("automated")).lower() in ["1","true","yes"]), axis=1)
        e["status_grp"] = e["status"].apply(map_status)

    # --------- Métricas de volume ---------
    total_exec     = int(e.shape[0])
    auto_exec      = int(e["auto_flag"].sum()) if "auto_flag" in e.columns else 0
    manual_exec    = max(total_exec - auto_exec, 0)
    unique_auto_ts = e[e["auto_flag"]]["testKey"].nunique() if not e.empty and "testKey" in e.columns else 0

    # --------- CUSTO: cenário 1 (sem automação) ---------
    custo_somente_manual = total_exec * custo_exec_manual

    # --------- CUSTO: cenário 2 (com automação) ----------
    # Dev: por teste automatizado único (amortizado por vida útil)
    custo_dev_total = unique_auto_ts * custo_dev_automacao_por_teste
    amortizacao_por_exec = custo_dev_total / max(vida_util_execucoes, 1)

    # Manutenção por execução automatizada
    custo_manut_total = auto_exec * custo_manutencao_por_exec

    # Execuções manuais remanescentes (parte do escopo ainda manual)
    custo_manual_restante = manual_exec * custo_exec_manual

    custo_com_automacao = custo_manual_restante + custo_manut_total + amortizacao_por_exec

    # --------- Economia operacional com automação ---------
    economia_operacional = max(custo_somente_manual - custo_com_automacao, 0.0)

    # --------- Benefício de bugs pegos mais cedo ---------
    # Falhas detectadas nas execuções automatizadas com “perfil regressivo”
    if not e.empty:
        e_reg = e[e["auto_flag"]].copy()
        # aproxima regressivo por testType/labels/name
        is_reg = e_reg.apply(lambda r: any("regress" in str(r.get(c,"")).lower() for c in ["testType","labels","executionKey","testKey","issueKey"]), axis=1)
        e_reg = e_reg[is_reg] if isinstance(is_reg, pd.Series) else e_reg
        fails_reg = int(e_reg[e_reg["status_grp"]=="Fail"].shape[0]) if not e_reg.empty else 0
    else:
        fails_reg = 0

    bugs_prevenidos = int(round(fails_reg * taxa_escaparia_sem_teste * aproveitamento_suite))
    beneficio_bugs = bugs_prevenidos * delta_bug

    # --------- ROI total ---------
    roi_total = economia_operacional + beneficio_bugs

    # --------- KPIs ---------
    k = st.columns(6)
    with k[0]: st.metric("Execuções (total)", total_exec)
    with k[1]: st.metric("Automatizadas", auto_exec, f"{pct(auto_exec,total_exec):.1f}%")
    with k[2]: st.metric("Únicos automatizados", unique_auto_ts)
    with k[3]: st.metric("Economia operacional", f"R$ {economia_operacional:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
    with k[4]: st.metric("Benefício bugs cedo", f"R$ {beneficio_bugs:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
    with k[5]: st.metric("ROI total", f"R$ {roi_total:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))

    st.caption(f"""
    • Sem automação: **R$ {custo_somente_manual:,.2f}** — Com automação: **R$ {custo_com_automacao:,.2f}**  
    • Bugs prevenidos estimados: **{bugs_prevenidos}** (Δ custo bug = R$ {delta_bug:,.2f})
    """.replace(",", "X").replace(".", ",").replace("X","."))

    st.markdown("---")

    # --------- Gráfico: custos comparados ---------
    st.markdown("#### Custos comparados (cenário do período)")
    df_cost = pd.DataFrame({
        "Categoria": ["Somente Manual",
                      "Manual remanescente",
                      "Manutenção automação",
                      "Amortização dev automação"],
        "Valor": [custo_somente_manual,
                  custo_manual_restante,
                  custo_manut_total,
                  amortizacao_por_exec]
    })
    bar_cost = alt.Chart(df_cost).mark_bar().encode(
        x=alt.X("Categoria:N", title=None, sort=None),
        y=alt.Y("Valor:Q", title="R$"),
        tooltip=["Categoria","Valor"]
    ).properties(height=280)
    st.altair_chart(bar_cost, use_container_width=True)

    st.markdown("---")

    # --------- Gráfico: economia acumulada por mês ---------
    st.markdown("#### Tendência mensal de economia (estimada)")
    if e.empty or "executed_month" not in e.columns:
        st.info("Sem execuções no período para calcular tendência.")
    else:
        # Para cada mês: estima custo sem automação (exec_total * custo_manual)
        # e custo com automação (manual_rest + manutenção + amortização pró-rata)
        d = e.copy()
        d["kind"] = d["auto_flag"].map(lambda x: "auto" if x else "manual")
        grp = d.groupby(["executed_month","kind"]).size().unstack(fill_value=0)
        grp = grp.rename(columns={"auto":"auto", "manual":"manual"})
        grp["total"] = grp.sum(axis=1)

        # amortização pró-rata ~ proporcional à fração das execs no mês
        total_exec_periodo = grp["total"].sum() if grp["total"].sum() else 1
        grp["amortizacao"] = (grp["total"] / total_exec_periodo) * amortizacao_por_exec

        grp["custo_sem_auto"] = grp["total"] * custo_exec_manual
        grp["custo_com_auto"] = grp["manual"] * custo_exec_manual + grp["auto"] * custo_manutencao_por_exec + grp["amortizacao"]
        grp["economia_mes"]   = (grp["custo_sem_auto"] - grp["custo_com_auto"]).clip(lower=0)

        trend = grp.reset_index()[["executed_month","economia_mes"]]
        trend["acumulado"] = trend["economia_mes"].cumsum()

        ch_line = alt.Chart(trend).mark_line(point=True).encode(
            x=alt.X("executed_month:N", title=None, sort=None),
            y=alt.Y("acumulado:Q", title="R$"),
            tooltip=["executed_month","economia_mes","acumulado"]
        ).properties(height=280)
        st.altair_chart(ch_line, use_container_width=True)

    st.markdown("---")

    # --------- Tabela: insumos do cálculo ---------
    st.markdown("#### Insumos do período (amostra)")
    if e.empty:
        st.info("Sem execuções para exibir.")
    else:
        show_cols = [c for c in ["executedOn","executed_month","projectKey","testKey","status","environment","wave","issueKey","automated","testType","labels"] if c in e.columns]
        st.dataframe(e.sort_values("executed_dt", ascending=False)[show_cols].head(200), use_container_width=True)

# debug local
if __name__ == "__main__":
    pagina_dashboard_roi()
