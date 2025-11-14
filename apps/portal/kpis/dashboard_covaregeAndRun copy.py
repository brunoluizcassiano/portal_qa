# -*- coding: utf-8 -*-
import re
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import plotly.graph_objects as go
from datetime import date, timedelta
from pandas.api.types import is_datetime64_any_dtype, is_datetime64tz_dtype

from .analytics.constants import (
    KPI_LASTUPDATE,
    JIRA_EPIC, JIRA_STORY, JIRA_BUG, JIRA_SUBBUG, JIRA_PROJ,
    ZEPHYR_TC, ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK,
)

# FUNC opcional
try:
    from .analytics.constants import JIRA_FUNC
except Exception:
    JIRA_FUNC = None

# CYCLES opcionais
try:
    from .analytics.constants import ZEPHYR_CYCLE_MAIN, ZEPHYR_CYCLE_FALLBACK
except Exception:
    ZEPHYR_CYCLE_MAIN = None
    ZEPHYR_CYCLE_FALLBACK = None

from .analytics.data_access import safe_read_csv, read_last_update
from .analytics.transformers import normalize_issue_df, normalize_bugs
try:
    from .analytics.transformers import ensure_project_on_executions
except Exception:
    def ensure_project_on_executions(df: pd.DataFrame) -> pd.DataFrame:
        return df

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def _pct(a, b):
    return (float(a) / float(b) * 100.0) if (b not in (0, None, np.nan) and float(b) != 0.0) else 0.0

def _project_from_key(s: pd.Series) -> pd.Series:
    return s.astype(str).str.extract(r"^([A-Z0-9_]+)-", expand=False).fillna("")

def _first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    for n in names:
        if n in df.columns:
            return n
    return None

def _norm_cols(df: pd.DataFrame) -> dict:
    mapping = {}
    for c in df.columns:
        nc = str(c).replace("\xa0", " ")
        nc = re.sub(r"\s+", " ", nc).strip().lower()
        mapping[nc] = c
    return mapping

def _is_automated_bool_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(["1", "true", "y", "yes", "sim", "automated"])

def _is_automated_from_custom_status_exact(value) -> bool:
    if pd.isna(value): return False
    return str(value).strip().lower() == "automated"

def _status_series(df: pd.DataFrame) -> pd.Series:
    for c in ["status", "fields.status.name", "fields.status", "Status", "status.name"]:
        if c in df.columns:
            return df[c].astype(str)
    return pd.Series([""] * len(df), index=df.index)

def _is_closed(status: str) -> bool:
    s = str(status).upper()
    return bool(re.search(r"(DONE|CLOSED|RESOLVED)", s))

def _gauge_percent_plotly(total: int, automated: int, not_applicable: int, title: str = "% Automated Test"):
    import plotly.graph_objects as go
    import numpy as np
    pct_now = (automated / total * 100.0) if total else 0.0
    cap_pct = ((total - not_applicable) / total * 100.0) if total else 0.0
    cap_pct = float(np.clip(cap_pct, 0.0, 100.0))
    dom_x = [0.08, 0.92]
    dom_y = [0.15, 0.92]
    c_val  = "#21BA45"
    c_able = "rgba(15,122,110,0.18)"
    c_na   = "rgba(156,163,175,0.85)"
    c_teto = "#F59E0B"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=float(np.clip(pct_now, 0.0, 100.0)),
        number={"suffix": "%", "font": {"size": 26}},
        title={"text": title, "font": {"size": 14}},
        gauge={
            "shape": "angular",
            "axis": {"range": [0, 100], "tickmode": "array",
                     "tickvals": [0, 20, 40, 60, 80, 100], "tickfont": {"size": 10}},
            "bar": {"color": c_val},
            "steps": [
                {"range": [0, cap_pct],   "color": c_able},
                {"range": [cap_pct, 100], "color": c_na},
            ],
            "threshold": {"line": {"color": c_teto, "width": 6}, "thickness": 1.0, "value": cap_pct},
            "bgcolor": "rgba(0,0,0,0)",
        },
        domain={"x": dom_x, "y": dom_y}
    ))
    # Geometria do ponto do teto em coords "paper"
    ang = np.deg2rad(170.0 - (cap_pct * 170.0 / 100.0))
    cx = (dom_x[0] + dom_x[1]) / 2.0
    cy = dom_y[0]
    r  = (dom_y[1] - dom_y[0]) * 0.70
    px = max(0.01, min(0.99, cx + r * np.cos(ang)))
    py = max(0.01, min(0.99, cy + r * np.sin(ang)))
    # OFFSETS EM PIXELS para posicionar a caixa (seta vai até x=px,y=py)
    # ajuste fino: ax (+ direita / - esquerda), ay (- para cima / + para baixo)
    label_html = (
        f"<b>Máx. {cap_pct:.1f}%</b><br>"
        f"<span style='font-size:12px; color:#e5e7eb'>{not_applicable:,} Not applicable</span>"
    )
    # --- deslocar APENAS a seta um pouco para a esquerda ---
    # quanto mover a ponta da seta em coordenada "paper" (fração da largura do gráfico)
    delta_tip_paper = -0.020   # -0.010 ≈ 1% da largura; negativo = para a esquerda
    # definimos uma largura fixa para converter paper->pixels (ajuste fino se quiser)
    chart_width_px = 900
    paper_span_x   = (dom_x[1] - dom_x[0])          # fração da largura reservada ao gauge
    px_per_paper   = chart_width_px * paper_span_x  # conversor aproximado
    comp_px        = int(delta_tip_paper * px_per_paper)
    # nova posição do head (x,y) da seta
    x_head = px + delta_tip_paper
    y_head = py
    # offsets do balão (mantêm o balão onde já estava)
    ax_px = -40 - comp_px   # <— compensação contrária para o balão ficar no mesmo lugar
    ay_px = -60
    fig.add_annotation(
        x=x_head, y=y_head, xref="paper", yref="paper",
        ax=ax_px, ay=ay_px, axref="pixel", ayref="pixel",   # offsets em PIXELS (só do balão)
        text=label_html, showarrow=False, arrowhead=2, arrowwidth=2, arrowcolor=c_teto,
        xanchor="center", yanchor="bottom", align="center",
        bgcolor="rgba(0,0,0,0.65)", bordercolor=c_teto, borderwidth=1, borderpad=6
    )
    fig.update_layout(height=300, margin=dict(l=16, r=40, t=54, b=0))
    return fig


def _extract_issue_ids_from_testcases(df_zc: pd.DataFrame) -> pd.DataFrame:
    if df_zc.empty:
        return pd.DataFrame(columns=["tc_key", "issue_id"])

    cols_norm = _norm_cols(df_zc)

    tc_col = None
    for cand in ["key", "testcasekey", "testcase key", "id", "test case key"]:
        if cand in cols_norm:
            tc_col = cols_norm[cand]
            break
    if not tc_col:
        df = df_zc.copy()
        df["_tc_tmp_"] = np.arange(len(df))
        tc_col = "_tc_tmp_"
    else:
        df = df_zc

    frames = []

    id_like = [k for k in cols_norm.keys() if re.fullmatch(r"links\.issues\.(.*\sid|id)$", k)]
    for k in id_like:
        col = cols_norm[k]
        tmp = df[[tc_col, col]].dropna()
        if not tmp.empty:
            s = tmp[col].astype(str)
            vals = s.str.findall(r"\d+")
            tmp = tmp.assign(_id=vals).explode("_id")
            tmp["_id"] = pd.to_numeric(tmp["_id"], errors="coerce")
            tmp = tmp.dropna(subset=["_id"])
            frames.append(tmp[[tc_col, "_id"]].rename(columns={tc_col: "tc_key", "_id": "issue_id"}))

    for cand in ["links.issues.target", "links.issues url", "links.issues.target url"]:
        if cand in cols_norm:
            col = cols_norm[cand]
            tmp = df[[tc_col, col]].dropna()
            if not tmp.empty:
                vals = tmp[col].astype(str).str.findall(r"/issue/(\d+)")
                tmp = tmp.assign(_id=vals).explode("_id")
                tmp["_id"] = pd.to_numeric(tmp["_id"], errors="coerce")
                tmp = tmp.dropna(subset=["_id"])
                frames.append(tmp[[tc_col, "_id"]].rename(columns={tc_col: "tc_key", "_id": "issue_id"}))
            break

    if not frames:
        return pd.DataFrame(columns=["tc_key", "issue_id"])

    df_links = pd.concat(frames, ignore_index=True)
    df_links["issue_id"] = df_links["issue_id"].astype("Int64")
    df_links = df_links.drop_duplicates().dropna(subset=["issue_id"])
    return df_links

def _find_col_norm(df: pd.DataFrame, candidates: list[str]) -> str | None:
    if df is None or df.empty:
        return None
    mapping = {}
    for c in df.columns:
        nc = str(c).replace("\xa0", " ")
        nc = re.sub(r"\s+", " ", nc).strip().lower()
        mapping[nc] = c
    for cand in candidates:
        nc = re.sub(r"\s+", " ", str(cand).strip().lower())
        if nc in mapping:
            return mapping[nc]
    return None

def _is_not_applicable_from_custom_status(value) -> bool:
    if pd.isna(value):
        return False
    s = str(value).replace("\xa0", " ").strip().lower()
    if s in {"n/a", "na"}:
        return True
    return ("not applic" in s) or ("nor applic" in s)

_PROJ_CANDS = [
    "projectkey", "project key", "project.key", "project", "project.name", "project name",
    "domain", "tribe", "tribo", "tribo (projeto)"
]

# --------------------------------------------------------------------
# Página
# --------------------------------------------------------------------
def pagina_dashboard_coverage_and_run():
    try:
        st.set_page_config(page_title="Coverage and Run", layout="wide")
    except Exception:
        pass

    st.markdown("""
    <style>
      .block-container { padding-left: 1rem; padding-right: 1rem; }
      [data-testid="stMetric"] { padding:.4rem .6rem;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08); }
      [data-testid="stMetricLabel"] { font-size:12px;opacity:.85;letter-spacing:.2px; }
      [data-testid="stMetricValue"] { font-weight:800;font-size:28px;line-height:1.05; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### Coverage and Run")

    # ---------------- Carregamento ----------------
    df_story_raw  = safe_read_csv(JIRA_STORY)
    df_epic_raw   = safe_read_csv(JIRA_EPIC)
    df_bug        = normalize_bugs(safe_read_csv(JIRA_BUG))
    df_subbug     = normalize_bugs(safe_read_csv(JIRA_SUBBUG))
    df_proj       = safe_read_csv(JIRA_PROJ)
    df_zc         = safe_read_csv(ZEPHYR_TC)

    df_ze_raw     = safe_read_csv([ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK])
    df_ze         = ensure_project_on_executions(df_ze_raw.copy())

    cycle_sources = [s for s in [ZEPHYR_CYCLE_MAIN, ZEPHYR_CYCLE_FALLBACK] if s]
    df_cycle      = safe_read_csv(cycle_sources) if cycle_sources else pd.DataFrame()

    if JIRA_FUNC:
        try:
            df_func_raw = safe_read_csv(JIRA_FUNC)
            df_func = normalize_issue_df(df_func_raw)
        except Exception:
            df_func_raw = pd.DataFrame()
            df_func = pd.DataFrame()
    else:
        df_func_raw = pd.DataFrame()
        df_func = pd.DataFrame()

    # ---------------- Normalize Issues ----------------
    df_story = normalize_issue_df(df_story_raw)
    df_epic  = normalize_issue_df(df_epic_raw)
    for d in (df_story, df_epic, df_func):
        if not d.empty and "created" in d.columns:
            d["created_date"] = pd.to_datetime(d["created"], errors="coerce", utc=True).dt.date
        elif not d.empty:
            d["created_date"] = pd.NaT

    # ---------------- Execuções ----------------
    if not df_ze.empty:
        exec_col = _first_col(df_ze, ["actualEndDate", "executedOn"])
        if exec_col:
            cdt = pd.to_datetime(df_ze[exec_col], errors="coerce", utc=True)
            df_ze["executed_date"] = cdt.dt.date
            df_ze["month"] = cdt.dt.strftime("%Y-%m")
        else:
            df_ze["executed_date"] = pd.NaT

        need_proj = ("projectKey" not in df_ze.columns) or df_ze["projectKey"].astype(str).str.strip().eq("").all()
        if need_proj:
            proj_series = None
            for cand in ["testCaseKey", "testCase.key"]:
                if cand in df_ze.columns:
                    proj_series = _project_from_key(df_ze[cand])
                    break
            if proj_series is None or proj_series.fillna("").eq("").all():
                cand = _first_col(df_ze, ["testCycle.key", "testCycleKey", "cycleKey"])
                if cand:
                    proj_series = _project_from_key(df_ze[cand])
            if (proj_series is None or proj_series.fillna("").eq("").all()) and "key" in df_ze.columns:
                proj_series = _project_from_key(df_ze["key"])
            if proj_series is None or proj_series.fillna("").eq("").all():
                cand = _first_col(df_ze, ["issueKey", "testKey", "Test Case Key"])
                if cand:
                    proj_series = _project_from_key(df_ze[cand])
            if proj_series is None:
                proj_series = pd.Series([""] * len(df_ze), index=df_ze.index)
            df_ze["projectKey"] = proj_series.fillna("").astype(str)

        df_ze["projectKey"] = df_ze["projectKey"].astype("category")

    # ---------------- Test Cases ----------------
    if not df_zc.empty:
        if "projectKey" not in df_zc.columns:
            df_zc["projectKey"] = _project_from_key(df_zc["key"]) if "key" in df_zc.columns else ""
        created_col = _first_col(df_zc, ["created","createdOn","createdDate","creationDate","created_at"])
        if created_col:
            cdt = pd.to_datetime(df_zc[created_col], errors="coerce", utc=True)
            df_zc["created_date"] = cdt.dt.date
            df_zc["month"]        = cdt.dt.strftime("%Y-%m")
            df_zc["year"]         = cdt.dt.year.astype("Int64")
        else:
            if "month" in df_zc.columns:
                cdt = pd.to_datetime(df_zc["month"].astype(str) + "-01", errors="coerce", utc=True)
                df_zc["created_date"] = cdt.dt.date
            else:
                df_zc["created_date"] = pd.NaT
            if "year" not in df_zc.columns:
                df_zc["year"] = pd.NA
        df_zc["projectKey"] = df_zc["projectKey"].astype("category")

    # ---------------- Test Cycles ----------------
    if not df_cycle.empty:
        if "projectKey" not in df_cycle.columns:
            src_col = "key" if "key" in df_cycle.columns else ("name" if "name" in df_cycle.columns else None)
            if src_col:
                df_cycle["projectKey"] = _project_from_key(df_cycle[src_col]).str.upper()
            else:
                df_cycle["projectKey"] = ""
        cyc_col = _find_col_norm(
            df_cycle, ["planned start date", "plannedstartdate", "start date", "startdate"]
        )
        if cyc_col:
            cdt = pd.to_datetime(df_cycle[cyc_col], errors="coerce", utc=True)
            df_cycle["cycle_date"] = cdt.dt.date
            df_cycle["month"] = cdt.dt.strftime("%Y-%m")
        else:
            if "cycle_date" not in df_cycle.columns:
                df_cycle["cycle_date"] = pd.NaT

    # ---------------- Filtros ----------------
    def _collect_projects(df: pd.DataFrame) -> list[str]:
        if df is None or df.empty:
            return []
        col = _find_col_norm(df, _PROJ_CANDS)
        if not col:
            return []
        return (
            df[col]
            .dropna()
            .astype(str)
            .str.replace("\xa0", " ")
            .str.strip()
            .str.upper()
            .tolist()
        )

    candidatos = set()
    for _df in [df_story, df_epic, df_func, df_ze, df_zc, df_proj, df_cycle]:
        candidatos.update(_collect_projects(_df))
    projects = ["Todos"] + sorted([p for p in candidatos if p])

    if not df_ze.empty and "executed_date" in df_ze.columns:
        all_dates = df_ze["executed_date"].dropna().tolist()
    elif not df_story.empty:
        all_dates = df_story["created_date"].dropna().tolist()
    else:
        all_dates = []
    min_d, max_d = (min(all_dates), max(all_dates)) if all_dates else (date.today()-timedelta(days=180), date.today())

    if "periodo_master_car" not in st.session_state:
        st.session_state["periodo_master_car"] = (min_d, max_d)

    def _ensure_range_key(key: str, fallback: tuple[date, date]):
        v = st.session_state.get(key, None)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            st.session_state[key] = (v[0], v[1])
        elif isinstance(v, date):
            st.session_state[key] = (v, v)
        else:
            st.session_state[key] = fallback

    _ensure_range_key("intervalo_data_car",   st.session_state["periodo_master_car"])
    _ensure_range_key("intervalo_slider_car", st.session_state["periodo_master_car"])

    def _on_calendar_change():
        st.session_state["periodo_master_car"] = st.session_state["intervalo_data_car"]
        st.session_state["intervalo_slider_car"] = st.session_state["intervalo_data_car"]

    def _on_slider_change():
        st.session_state["periodo_master_car"] = st.session_state["intervalo_slider_car"]
        st.session_state["intervalo_data_car"] = st.session_state["intervalo_slider_car"]

    c0, c1, c2 = st.columns([0.50, 0.30, 0.20])
    with c0:
        sel_project = st.selectbox("Tribo (Projeto)", options=projects, index=0)
    with c1: st.caption("")
    with c2:
        dt = read_last_update(KPI_LASTUPDATE)
        if dt: st.caption(f"Atualizado: {dt}")

    c0, c1, c2 = st.columns([0.50, 0.30, 0.20])
    with c0:
        ca, cb = st.columns(2)
        with ca:
            st.date_input("Date (calendário)", key="intervalo_data_car",
                          min_value=min_d, max_value=max_d, format="DD/MM/YYYY", on_change=_on_calendar_change)
        with cb:
            st.slider("Date (slider)", key="intervalo_slider_car",
                      min_value=min_d, max_value=max_d, format="DD/MM/YYYY", on_change=_on_slider_change)
    with c1: st.caption("")
    with c2: st.caption("")

    d_start, d_end = st.session_state["periodo_master_car"]

    def _f_proj(df: pd.DataFrame, proj_sel: str) -> pd.DataFrame:
        if df is None or df.empty or not proj_sel or proj_sel == "Todos":
            return df
        col = _find_col_norm(df, _PROJ_CANDS)
        if not col:
            return df
        s = df[col].astype(str).str.replace("\xa0", " ").str.strip().str.upper()
        return df.loc[s.eq(proj_sel)].copy()

    def _f_period_created(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or "created_date" not in df.columns: return df
        s = df["created_date"]
        if is_datetime64_any_dtype(s):
            s_ts = pd.to_datetime(s, errors="coerce")
            try:
                if is_datetime64tz_dtype(s_ts.dtype): s_ts = s_ts.dt.tz_localize(None)
            except Exception:
                try: s_ts = s_ts.dt.tz_convert(None)
                except Exception: pass
            start_ts = pd.Timestamp(d_start); end_ts = pd.Timestamp(d_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
            return df[s_ts.between(start_ts, end_ts, inclusive="both")].copy()
        try:
            return df[(s >= d_start) & (s <= d_end)].copy()
        except Exception:
            s2 = pd.to_datetime(s, errors="coerce").dt.date
            df2 = df.copy(); df2["created_date"] = s2
            return df2[(s2 >= d_start) & (s2 <= d_end)].copy()

    def _f_period_exec(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or "executed_date" not in df.columns: return df
        s = df["executed_date"]
        if is_datetime64_any_dtype(s):
            s_ts = pd.to_datetime(s, errors="coerce")
            try:
                if is_datetime64tz_dtype(s_ts.dtype): s_ts = s_ts.dt.tz_localize(None)
            except Exception:
                try: s_ts = s_ts.dt.tz_convert(None)
                except Exception: pass
            start_ts = pd.Timestamp(d_start); end_ts = pd.Timestamp(d_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
            return df[s_ts.between(start_ts, end_ts, inclusive="both")].copy()
        try:
            return df[(s >= d_start) & (s <= d_end)].copy()
        except Exception:
            s2 = pd.to_datetime(s, errors="coerce").dt.date
            df2 = df.copy(); df2["executed_date"] = s2
            return df2[(s2 >= d_start) & (s2 <= d_end)].copy()

    def _f_period_cycle(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or "cycle_date" not in df.columns: return df
        s = df["cycle_date"]
        if is_datetime64_any_dtype(s):
            s_ts = pd.to_datetime(s, errors="coerce")
            try:
                if is_datetime64tz_dtype(s_ts.dtype): s_ts = s_ts.dt.tz_localize(None)
            except Exception:
                try: s_ts = s_ts.dt.tz_convert(None)
                except Exception: pass
            start_ts = pd.Timestamp(d_start); end_ts = pd.Timestamp(d_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
            return df[s_ts.between(start_ts, end_ts, inclusive="both")].copy()
        try:
            return df[(s >= d_start) & (s <= d_end)].copy()
        except Exception:
            s2 = pd.to_datetime(s, errors="coerce").dt.date
            df2 = df.copy(); df2["cycle_date"] = s2
            return df2[(s2 >= d_start) & (s2 <= d_end)].copy()

    f_story = _f_proj(_f_period_created(df_story), sel_project)
    f_epic  = _f_proj(_f_period_created(df_epic),  sel_project)
    f_func  = _f_proj(_f_period_created(df_func),  sel_project)
    f_zc    = _f_proj(_f_period_created(df_zc),    sel_project)
    f_ze    = _f_proj(_f_period_exec(df_ze),       sel_project)
    f_cyc   = _f_proj(_f_period_cycle(df_cycle),   sel_project)

    # ---------------- Cards topo ----------------
    col1 = st.columns(4)
    with col1[0]:
        if not df_proj.empty and {"name","key"}.issubset(df_proj.columns):
            domains = len(df_proj if sel_project == "Todos" else df_proj[df_proj["key"].astype(str).str.upper().eq(str(sel_project).upper())])
        else:
            base = pd.concat(
                [s for s in [
                    f_story.get("projectKey", pd.Series(dtype="object")),
                    f_epic.get("projectKey",  pd.Series(dtype="object")),
                ] if not s.empty],
                ignore_index=True
            )
            domains = base.dropna().astype(str).str.upper().nunique()
        st.metric("Tribo", int(domains) if pd.notna(domains) else 0)
    with col1[1]: st.metric("QTD Story", int(f_story.shape[0]))
    with col1[2]: st.metric("QTD Epic",  int(f_epic.shape[0]))
    cov_slot = col1[3].empty()
    cov_slot.metric("% Story Coverage", "—")

    # ---------------- TEST CASES ----------------
    automated_tests = total_tests = manual_tests = 0
    if not f_zc.empty:
        auto_col = _first_col(f_zc, ["customFields.Automation Status"])
        auto_series_cases = f_zc[auto_col].apply(_is_automated_from_custom_status_exact) if auto_col else pd.Series(False, index=f_zc.index)
        automated_tests = int(auto_series_cases.sum())
        total_tests     = int(len(f_zc))
        manual_tests    = int(total_tests - automated_tests)

    if total_tests == 0 and not f_ze.empty:
        key_run = _first_col(f_ze, ["testCaseKey","testCase.key","testKey","testCaseId","testId"])
        if key_run:
            z = f_ze.dropna(subset=[key_run]).copy()
            is_auto_run = _is_automated_bool_series(z.get("automated", pd.Series(dtype="object")))
            auto_by_case = z.assign(_auto=is_auto_run).groupby(z[key_run].astype(str))["_auto"].any()
            automated_tests = int(auto_by_case.sum())
            manual_tests    = int((~auto_by_case).sum())
            total_tests     = int(auto_by_case.shape[0])

    col2 = st.columns(4)
    with col2[0]: st.metric("# Manual Test",    int(manual_tests))
    with col2[1]: st.metric("# Automated Test", int(automated_tests))
    with col2[2]: st.metric("# Total Test",     int(total_tests))
    with col2[3]:
        if not f_cyc.empty:
            cyc_key = _first_col(f_cyc, ["key","cycleKey","name","cycleId","id"])
            cycles = f_cyc[cyc_key].dropna().astype(str).nunique() if cyc_key else int(len(f_cyc))
        elif not f_ze.empty:
            cycle_col = _first_col(f_ze, ["testCycle.key","testCycle.id","cycleKey","cycleId"])
            cycles = f_ze[cycle_col].dropna().astype(str).nunique() if cycle_col else 0
        else:
            cycles = 0
        st.metric("# Test Cycle", int(cycles))

    col3 = st.columns(4)
    with col3[0]:
        man_runs = int((~_is_automated_bool_series(f_ze.get("automated", pd.Series(dtype="object")))).sum()) if not f_ze.empty else 0
        st.metric("# Manual Run", man_runs)
    with col3[1]:
        aut_runs = int((_is_automated_bool_series(f_ze.get("automated", pd.Series(dtype="object")))).sum()) if not f_ze.empty else 0
        st.metric("# Automated Run", aut_runs)
    with col3[2]:
        total_runs = int(man_runs + aut_runs)
        st.metric("# Total Run", total_runs)

    # ---------------- Cálculos especiais ----------------
    links_by_id = _extract_issue_ids_from_testcases(f_zc) if not f_zc.empty else pd.DataFrame(columns=["tc_key","issue_id"])
    story_ids = pd.to_numeric(f_story.get("id", pd.Series(dtype="object")), errors="coerce").dropna().astype("Int64")
    if not links_by_id.empty and not story_ids.empty:
        covered_story_ids = set(links_by_id["issue_id"].dropna().astype("Int64")) & set(story_ids.tolist())
        pct_story_cov = _pct(len(covered_story_ids), int(f_story.shape[0]))
    else:
        pct_story_cov = 0.0
    cov_slot.metric("% Story Coverage", f"{pct_story_cov:.2f}%")

    issue_id_sets = []
    for df_ in (f_story, f_epic, f_func):
        if not df_.empty and "id" in df_.columns:
            ids = pd.to_numeric(df_["id"], errors="coerce").dropna().astype("Int64")
            if not ids.empty:
                issue_id_sets.append(set(ids.tolist()))
    relevant_issue_ids = set().union(*issue_id_sets) if issue_id_sets else set()

    if not links_by_id.empty and relevant_issue_ids:
        df_link_rel = links_by_id[links_by_id["issue_id"].isin(list(relevant_issue_ids))]
        if not df_link_rel.empty:
            by_issue = df_link_rel.groupby("issue_id")["tc_key"].nunique()
            avg_tests_per_issue = float(by_issue.mean()) if not by_issue.empty else 0.0
        else:
            avg_tests_per_issue = 0.0
    else:
        avg_tests_per_issue = 0.0

    with col3[3]:
        st.metric("# Test average per issue", f"{avg_tests_per_issue:.2f}")

    story_status_map = dict(zip(df_story_raw.get("key", pd.Series(dtype="object")).astype(str), _status_series(df_story_raw))) if not df_story_raw.empty and "key" in df_story_raw.columns else {}
    epic_status_map  = dict(zip(df_epic_raw.get("key",  pd.Series(dtype="object")).astype(str), _status_series(df_epic_raw)))  if not df_epic_raw.empty and "key" in df_epic_raw.columns  else {}

    col4 = st.columns(4)
    with col4[0]:
        if not f_story.empty and story_status_map:
            keys = f_story.get("key", pd.Series(dtype="object")).dropna().astype(str)
            story_closed = sum(1 for k in keys if _is_closed(story_status_map.get(k, "")))
        else:
            story_closed = 0
        st.metric("# QTD Story Closed", int(story_closed))
    with col4[1]:
        if not f_epic.empty and epic_status_map:
            keys = f_epic.get("key", pd.Series(dtype="object")).dropna().astype(str)
            epic_closed = sum(1 for k in keys if _is_closed(epic_status_map.get(k, "")))
        else:
            epic_closed = 0
        st.metric("# QTD Epic Closed", int(epic_closed))
    with col4[2]: st.metric("% Automated Test", f"{_pct(automated_tests, total_tests):.2f}%")
    with col4[3]: st.metric("% Automated Run",  f"{_pct(aut_runs if 'aut_runs' in locals() else 0, total_runs if 'total_runs' in locals() else 0):.2f}%")

    st.markdown("---")

    # ---------------- Gráficos ----------------
    cA, cB = st.columns(2)

    with cA:
        st.markdown("#### Automated Backlog")

        if f_zc.empty:
            st.info("Sem dados de casos de teste (Zephyr Test Cases).")
        else:
            auto_col = _find_col_norm(
                f_zc,
                ["customfields.automation status", "custom fields.automation status", "automation status"]
            )

            if auto_col:
                s_status = f_zc[auto_col].astype(str).str.replace("\xa0", " ").str.strip().str.lower()
                auto_mask = s_status.eq("automated")
                not_app_mask = s_status.apply(_is_not_applicable_from_custom_status)
            else:
                auto_mask = pd.Series(False, index=f_zc.index)
                not_app_mask = pd.Series(False, index=f_zc.index)

            n_total    = int(len(f_zc))
            n_auto     = int(auto_mask.sum())
            n_not_app  = int(not_app_mask.sum())
            n_backlog  = max(0, n_total - n_auto - n_not_app)

            st.plotly_chart(_gauge_percent_plotly(n_total, n_auto, n_not_app, "% Automated Test"),
                                use_container_width=True)
            st.caption("The gray area indicates the unattainable portion of 100% due to tests marked as Not applicable.")

            c1, c2, c3 = st.columns(3)
            c1.metric("Automated", n_auto)
            c2.metric("Backlog automated", n_backlog)
            c3.metric("Not applicable automated", n_not_app)

    with cB:

        cA2, cB2 = st.columns(2)

        with cA2:
            st.markdown("#### Regressive × Others (Test type)")

            if f_zc.empty:
                st.info("Sem dados de casos de teste (Zephyr Test Cases).")
            else:
                tt_col = _find_col_norm(
                    f_zc,
                    ["custom fields.test type", "customfields.test type", "test type"]
                )

                if not tt_col:
                    st.info("Coluna 'Custom Fields.Test Type' não encontrada nos Test Cases.")
                else:
                    s = (
                        f_zc[tt_col]
                        .astype(str)
                        .str.replace("\xa0", " ")
                        .str.strip()
                        .str.lower()
                    )

                    is_reg = s.str.contains(r"\bregress", na=False)

                    df_rr = pd.DataFrame({
                        "Categoria": ["Regression", "Others"],
                        "Qtd": [int(is_reg.sum()), int((~is_reg).sum())]
                    }).sort_values("Qtd", ascending=False)

                    bars = (
                        alt.Chart(df_rr)
                        .mark_bar(size=60)
                        .encode(
                            x=alt.X("Categoria:N", title=None, sort='-y'),
                            y=alt.Y("Qtd:Q", title="Test Cases", axis=alt.Axis(format=",d", grid=True)),
                            color=alt.Color(
                                "Categoria:N",
                                legend=None,
                                scale=alt.Scale(
                                    domain=["Regression", "Others"],
                                    range=["#22c55e", "#6B7280"]
                                ),
                            ),
                            tooltip=[alt.Tooltip("Categoria:N"), alt.Tooltip("Qtd:Q", title="Quantidade", format=",d")],
                        )
                        .properties(height=460)
                    )

                    labels = (
                        alt.Chart(df_rr)
                        .mark_text(dy=-8, size=12, color="#E5E7EB")
                        .encode(
                            x=alt.X("Categoria:N", sort='-y'),
                            y=alt.Y("Qtd:Q"),
                            text=alt.Text("Qtd:Q", format=",d"),
                        )
                    )

                    st.altair_chart((bars + labels), use_container_width=True)

        with cB2:
            st.markdown("#### Positive × Negative (Test class)")

            if f_zc.empty:
                st.info("Sem dados de casos de teste (Zephyr Test Cases).")
            else:
                tc_col = _find_col_norm(
                    f_zc,
                    ["custom fields.test class", "customfields.test class", "test class"]
                )

                if not tc_col:
                    st.info("Coluna 'Custom Fields.Test Class' não encontrada nos Test Cases.")
                else:
                    s = (
                        f_zc[tc_col]
                        .astype(str)
                        .str.replace("\xa0", " ")
                        .str.strip()
                        .str.lower()
                    )
                    is_pos = s.eq("positive")
                    is_neg = s.eq("negative")

                    n_pos = int(is_pos.sum())
                    n_neg = int(is_neg.sum())

                    if (n_pos + n_neg) == 0:
                        st.info("Não há registros Positive/Negative no período/projeto selecionado.")
                    else:
                        df_pn = pd.DataFrame({
                            "Classe": ["Positive", "Negative"],
                            "Qtd": [n_pos, n_neg]
                        }).sort_values("Qtd", ascending=False)

                        bars = (
                            alt.Chart(df_pn)
                            .mark_bar(size=60)
                            .encode(
                                x=alt.X("Classe:N", title=None, sort='-y'),
                                y=alt.Y("Qtd:Q", title="Test Cases", axis=alt.Axis(format=",d", grid=True)),
                                color=alt.Color(
                                    "Classe:N",
                                    legend=None,
                                    scale=alt.Scale(
                                        domain=["Positive", "Negative"],
                                        range=["#22c55e", "#ef4444"]
                                    ),
                                ),
                                tooltip=[alt.Tooltip("Classe:N"), alt.Tooltip("Qtd:Q", title="Quantidade", format=",d")],
                            )
                            .properties(height=460)
                        )

                        labels = (
                            alt.Chart(df_pn)
                            .mark_text(dy=-8, size=12, color="#E5E7EB")
                            .encode(
                                x=alt.X("Classe:N", sort='-y'),
                                y=alt.Y("Qtd:Q"),
                                text=alt.Text("Qtd:Q", format=",d"),
                            )
                        )

                        st.altair_chart((bars + labels), use_container_width=True)

    st.markdown("---")

    # ---------------- Linha mensal e barras de runs ----------------
    cL, cR = st.columns(2)

    with cL:
        st.markdown("#### Test evolution (mensal)")
        if f_ze.empty:
            st.info("Sem execuções no período selecionado.")
        else:
            # Legenda embaixo (horizontal), com 2 colunas
            legend_opts = alt.Legend(
                orient="bottom",
                direction="horizontal",
                columns=2,
                title=None,
                labelFontSize=12,
                symbolSize=140,
                padding=10,
            )

            z = f_ze.copy()
            z["is_auto"] = z.get("automated", pd.Series(dtype="object")).astype(str).str.lower().isin(["1","true","yes","automated","sim"])
            df_month = z.groupby(["month","is_auto"]).size().reset_index(name="runs")
            df_month["tipo"] = df_month["is_auto"].map({True:"Automated Run", False:"Manual Run"})
            try:
                df_month["month_dt"] = pd.to_datetime(df_month["month"] + "-01", errors="coerce")
                df_month = df_month.sort_values("month_dt")
            except Exception:
                pass
            ch = alt.Chart(df_month).mark_line(point=True).encode(
                x=alt.X("month:N", title="Mês"),
                y=alt.Y("runs:Q", title="Runs"),
                color=alt.Color("tipo:N", legend=legend_opts)
            ).properties(height=420, padding={"bottom": 40})
            st.altair_chart(ch, use_container_width=True)

    with cR:
        cR1, cR2 = st.columns(2)

        with cR1:
            # >>>>>>>>> ATUALIZADO: Automated run × Manual run (barras altas, rótulos, ordenação) <<<<<<<<
            st.markdown("#### Automated run × Manual run")
            if f_ze.empty or "automated" not in f_ze.columns:
                st.info("Sem execuções no período.")
            else:
                is_auto = _is_automated_bool_series(f_ze["automated"])
                df_am = pd.DataFrame({"tipo": ["Automated","Manual"], "runs": [int(is_auto.sum()), int((~is_auto).sum())]}) \
                        .sort_values("runs", ascending=False)

                bars = (
                    alt.Chart(df_am)
                    .mark_bar(size=60)
                    .encode(
                        x=alt.X("tipo:N", title=None, sort='-y'),
                        y=alt.Y("runs:Q", title="Runs", axis=alt.Axis(format=",d", grid=True)),
                        color=alt.Color(
                            "tipo:N",
                            legend=None,
                            scale=alt.Scale(domain=["Automated","Manual"], range=["#60A5FA","#93C5FD"])
                        ),
                        tooltip=[alt.Tooltip("tipo:N"), alt.Tooltip("runs:Q", title="Quantidade", format=",d")],
                    )
                    .properties(height=340)
                )
                labels = (
                    alt.Chart(df_am)
                    .mark_text(dy=-8, size=12, color="#E5E7EB")
                    .encode(
                        x=alt.X("tipo:N", sort='-y'),
                        y=alt.Y("runs:Q"),
                        text=alt.Text("runs:Q", format=",d"),
                    )
                )
                st.altair_chart((bars + labels), use_container_width=True)

        with cR2:
            # >>>>>>>>> ATUALIZADO: Automation in regressive (barras altas, rótulos, ordenação) <<<<<<<<
            st.markdown("#### Automation in regressive")
            if f_zc.empty:
                st.info("Sem dados de casos de teste (Zephyr Test Cases).")
            else:
                tt_col  = _find_col_norm(f_zc, ["custom fields.test type", "customfields.test type", "test type"])
                auto_tc = _find_col_norm(f_zc, ["custom fields.automation status", "customfields.automation status", "automation status"])

                if not tt_col or not auto_tc:
                    st.info("Colunas 'Test Type' / 'Automation Status' não encontradas nos Test Cases.")
                else:
                    s_type = f_zc[tt_col].astype(str).str.replace("\xa0", " ").str.strip().str.lower()
                    s_auto = f_zc[auto_tc].astype(str).str.replace("\xa0", " ").str.strip().str.lower()

                    reg_mask     = s_type.str.contains(r"\bregress", na=False)
                    not_app_mask = s_auto.isin({"n/a", "na"}) | s_auto.str.contains("not applic|nor applic", na=False)

                    base = f_zc[reg_mask & ~not_app_mask].copy()
                    if base.empty:
                        st.info("Sem registros Regression automatizáveis no período/projeto selecionado.")
                    else:
                        auto_reg = (s_auto.loc[base.index] == "automated").sum()
                        man_reg  = len(base) - auto_reg

                        df_reg = pd.DataFrame({
                            "Categoria": ["Automated (Regression)", "Manual (Regression)"],
                            "Qtd": [int(auto_reg), int(man_reg)]
                        }).sort_values("Qtd", ascending=False)

                        bars = (
                            alt.Chart(df_reg)
                            .mark_bar(size=60)
                            .encode(
                                x=alt.X("Categoria:N", title=None, sort='-y'),
                                y=alt.Y("Qtd:Q", title="Test Cases", axis=alt.Axis(format=",d", grid=True)),
                                color=alt.Color(
                                    "Categoria:N",
                                    legend=None,
                                    scale=alt.Scale(
                                        domain=["Automated (Regression)", "Manual (Regression)"],
                                        range=["#22c55e", "#6B7280"]
                                    ),
                                ),
                                tooltip=[alt.Tooltip("Categoria:N"), alt.Tooltip("Qtd:Q", title="Quantidade", format=",d")],
                            )
                            .properties(height=340)
                        )
                        labels = (
                            alt.Chart(df_reg)
                            .mark_text(dy=-8, size=12, color="#E5E7EB")
                            .encode(
                                x=alt.X("Categoria:N", sort='-y'),
                                y=alt.Y("Qtd:Q"),
                                text=alt.Text("Qtd:Q", format=",d"),
                            )
                        )
                        st.altair_chart((bars + labels), use_container_width=True)

                        total_reg = int(len(base))
                        pct = (auto_reg / total_reg * 100.0) if total_reg else 0.0
                        st.caption(f"**% Automated em Regression**: {pct:.2f}%  (Automated {auto_reg} de {total_reg})")


if __name__ == "__main__":
    pagina_dashboard_coverage_and_run()
