# -*- coding: utf-8 -*-
import os
import re
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import date, timedelta
from pandas.api.types import is_datetime64_any_dtype, is_datetime64tz_dtype

from .analytics.constants import (
    KPI_LASTUPDATE,
    JIRA_EPIC, JIRA_STORY, JIRA_FUNC,  # <- incluí o FUNC
    JIRA_BUG, JIRA_SUBBUG, JIRA_PROJ,
    ZEPHYR_TC, ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK,
)
from .analytics.data_access import safe_read_csv, read_last_update
from .analytics.transformers import (
    normalize_issue_df, normalize_bugs, ensure_project_on_executions,
)

# ---------------- Utils ----------------
def _pct(a, b):
    return (float(a) / float(b) * 100.0) if (b not in (0, None, np.nan) and float(b) != 0.0) else 0.0

def _project_from_key(s: pd.Series) -> pd.Series:
    return s.astype(str).str.extract(r"^([A-Z0-9_]+)-", expand=False).fillna("")

def _status_series(df: pd.DataFrame) -> pd.Series:
    for c in ["status", "fields.status.name", "fields.status", "Status", "status.name"]:
        if c in df.columns:
            return df[c].astype(str)
    return pd.Series([""] * len(df), index=df.index)

def _is_closed(status: str) -> bool:
    s = str(status).upper()
    return bool(re.search(r"(DONE|CLOSED|RESOLVED)", s))

def _first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    for n in names:
        if n in df.columns:
            return n
    return None

def _is_automated_bool_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(["1", "true", "y", "yes", "sim", "automated"])

def _is_automated_from_custom_status_exact(value) -> bool:
    if pd.isna(value): return False
    return str(value).strip().lower() == "automated"

# Extrai tabelas de links (issue_id/issue_key) a partir do CSV de Test Cases
def _extract_links_from_testcases(df_zc: pd.DataFrame):
    if df_zc.empty:
        return (pd.DataFrame(columns=["tc_id","issue_id"], dtype="Int64"),
                pd.DataFrame(columns=["tc_id","issue_key"], dtype="object"))

    tc_id_col = _first_col(df_zc, ["key", "testCaseKey", "id", "testcaseKey"])
    if not tc_id_col:
        # garante alguma identificação
        df_zc = df_zc.copy()
        df_zc["_row_id_"] = np.arange(len(df_zc))
        tc_id_col = "_row_id_"

    # ---- Por ID ----
    id_cols = ["Links.issues.id", "links.issues.id", "issue.id", "issueId"]
    frames_id = []
    for c in id_cols:
        if c in df_zc.columns:
            tmp = df_zc[[tc_id_col, c]].dropna()
            if not tmp.empty:
                tmp = tmp.assign(_ids=tmp[c].astype(str).str.findall(r"\d+")).explode("_ids")
                tmp["issue_id"] = pd.to_numeric(tmp["_ids"], errors="coerce").astype("Int64")
                frames_id.append(tmp[[tc_id_col, "issue_id"]])
    # URLs com id no final
    if "Links.issues.target" in df_zc.columns:
        tmp = df_zc[[tc_id_col, "Links.issues.target"]].dropna()
        if not tmp.empty:
            tmp = tmp.assign(_ids=tmp["Links.issues.target"].astype(str).str.findall(r"/issue/(\d+)")).explode("_ids")
            tmp["issue_id"] = pd.to_numeric(tmp["_ids"], errors="coerce").astype("Int64")
            frames_id.append(tmp[[tc_id_col, "issue_id"]])

    df_links_id = pd.concat(frames_id, ignore_index=True) if frames_id else pd.DataFrame(columns=[tc_id_col,"issue_id"])
    if not df_links_id.empty:
        df_links_id = df_links_id.dropna(subset=["issue_id"]).drop_duplicates()
        df_links_id = df_links_id.rename(columns={tc_id_col: "tc_id"}).astype({"issue_id":"Int64"})

    # ---- Por KEY ----
    key_cols = ["Links.issues.key", "links.issues.key", "issueKey", "issue.key", "jira.key", "jiraKey"]
    frames_key = []
    for c in key_cols:
        if c in df_zc.columns:
            tmp = df_zc[[tc_id_col, c]].dropna()
            if not tmp.empty:
                tmp = tmp.assign(_keys=tmp[c].astype(str).str.findall(r"[A-Z0-9_]+-\d+")).explode("_keys")
                tmp = tmp.rename(columns={tc_id_col: "tc_id"})
                tmp["issue_key"] = tmp["_keys"].astype(str)
                frames_key.append(tmp[["tc_id","issue_key"]])

    df_links_key = pd.concat(frames_key, ignore_index=True) if frames_key else pd.DataFrame(columns=["tc_id","issue_key"])
    if not df_links_key.empty:
        df_links_key = df_links_key.dropna(subset=["issue_key"]).drop_duplicates()

    return df_links_id, df_links_key

# ---------------- Página ----------------
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

    # -------- Carregar dados
    df_story_raw  = safe_read_csv(JIRA_STORY)
    df_epic_raw   = safe_read_csv(JIRA_EPIC)
    df_func_raw   = safe_read_csv(JIRA_FUNC)
    df_bug        = normalize_bugs(safe_read_csv(JIRA_BUG))
    df_subbug     = normalize_bugs(safe_read_csv(JIRA_SUBBUG))
    df_proj       = safe_read_csv(JIRA_PROJ)

    df_zc         = safe_read_csv(ZEPHYR_TC)  # Test Cases
    df_ze         = ensure_project_on_executions(safe_read_csv([ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK]))

    # -------- Normalizar issues (created_date como date)
    df_story = normalize_issue_df(df_story_raw)
    df_epic  = normalize_issue_df(df_epic_raw)
    df_func  = normalize_issue_df(df_func_raw)

    for d in (df_story, df_epic, df_func):
        if not d.empty and "created" in d.columns:
            d["created_date"] = pd.to_datetime(d["created"], errors="coerce", utc=True).dt.date
        elif not d.empty:
            d["created_date"] = pd.NaT

    # -------- Execuções: executed_date como date
    if not df_ze.empty:
        exec_col = _first_col(df_ze, ["actualEndDate","executedOn"])
        df_ze["executed_date"] = pd.to_datetime(df_ze[exec_col], errors="coerce", utc=True).dt.date if exec_col else pd.NaT

    # -------- Test Cases (df_zc)
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

    # -------- Filtros topo
    if not df_proj.empty and {"name","key"}.issubset(df_proj.columns):
        projects = ["Todos"] + sorted(df_proj["key"].dropna().astype(str).unique().tolist())
    else:
        pref = pd.concat([s for s in [
            df_story.get("projectKey", pd.Series(dtype="object")),
            df_epic.get("projectKey", pd.Series(dtype="object")),
            df_func.get("projectKey", pd.Series(dtype="object")),
            df_ze.get("projectKey", pd.Series(dtype="object")),
            df_zc.get("projectKey", pd.Series(dtype="object")),
        ] if not s.empty], ignore_index=True)
        projects = ["Todos"] + sorted([p for p in pref.dropna().astype(str).unique().tolist() if p])

    # intervalo base
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
        sel_project = st.selectbox("Domain", options=projects, index=0)
    with c1: st.caption("")
    with c2:
        dt = read_last_update(KPI_LASTUPDATE)
        if dt: st.caption(f"Atualizado: {dt}")

    c0, c1, c2 = st.columns([0.50, 0.30, 0.20])
    with c0:
        ca, cb = st.columns(2)
        with ca:
            st.date_input("Date (calendário)", key="intervalo_data_car", min_value=min_d, max_value=max_d,
                          format="DD/MM/YYYY", on_change=_on_calendar_change)
        with cb:
            st.slider("Date (slider)", key="intervalo_slider_car", min_value=min_d, max_value=max_d,
                      format="DD/MM/YYYY", on_change=_on_slider_change)
    with c1: st.caption("")
    with c2: st.caption("")

    d_start, d_end = st.session_state["periodo_master_car"]

    # -------- Filtros Domain/Período
    def _f_proj(df: pd.DataFrame, col="projectKey") -> pd.DataFrame:
        if df.empty or sel_project == "Todos": return df
        return df[df.get(col, "").astype(str) == str(sel_project)].copy()

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

    f_story = _f_proj(_f_period_created(df_story))
    f_epic  = _f_proj(_f_period_created(df_epic))
    f_func  = _f_proj(_f_period_created(df_func))
    f_zc    = _f_proj(_f_period_created(df_zc))
    f_ze    = _f_proj(_f_period_exec(df_ze))

    # ---------------- Cards topo ----------------
    col1 = st.columns(4)
    with col1[0]:
        if not df_proj.empty:
            domains = len(df_proj if sel_project == "Todos" else df_proj[df_proj["key"].astype(str) == str(sel_project)])
        else:
            domains = len(set([*f_story.get("projectKey", pd.Series(dtype="object")).dropna().unique(),
                               *f_epic.get("projectKey", pd.Series(dtype="object")).dropna().unique()]))
        st.metric("Domain", int(domains) if pd.notna(domains) else 0)

    with col1[1]: st.metric("QTD Story", int(f_story.shape[0]))
    with col1[2]: st.metric("QTD Epic",  int(f_epic.shape[0]))
    # (% Story Coverage será redefinido mais abaixo quando tivermos os links)
    with col1[3]: st.metric("% Story Coverage", "…")

    # ----- TEST CASES (Automated/Manual/Total)
    auto_series_cases = pd.Series(dtype="bool")
    manual_tests = automated_tests = total_tests = 0
    if not f_zc.empty:
        auto_col = _first_col(f_zc, ["customFields.Automation Status"])
        if auto_col:
            auto_series_cases = f_zc[auto_col].apply(_is_automated_from_custom_status_exact)
        else:
            auto_series_cases = pd.Series(False, index=f_zc.index)
        automated_tests = int(auto_series_cases.sum())
        total_tests     = int(len(f_zc))
        manual_tests    = int(total_tests - automated_tests)

    # Fallback por RUNS se não houver cases
    if total_tests == 0 and not f_ze.empty:
        key_run = _first_col(f_ze, ["testCaseKey", "testCase.key", "testKey", "testCaseId", "testId"])
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
        if not f_ze.empty:
            cycle_col = _first_col(f_ze, ["testCycle.key","testCycle.id","cycleKey","cycleId"])
            cycles = f_ze[cycle_col].dropna().astype(str).nunique() if cycle_col else f_ze.groupby(["month","issueKey"]).ngroups
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

    # ---------------- LINKS TestCase -> Issues ----------------
    links_id, links_key = _extract_links_from_testcases(f_zc)
    linked_ids  = set(links_id["issue_id"].dropna().astype("Int64").tolist()) if not links_id.empty else set()
    linked_keys = set(links_key["issue_key"].dropna().astype(str).tolist())     if not links_key.empty else set()

    # -------- % Story Coverage (Stories + Epics com pelo menos 1 link)
    def _covered_count(f_df: pd.DataFrame) -> int:
        if f_df.empty: return 0
        has_id  = "id" in f_df.columns
        has_key = "key" in f_df.columns
        m = pd.Series([False]*len(f_df), index=f_df.index)
        if has_id:
            try:
                ids = pd.to_numeric(f_df["id"], errors="coerce").astype("Int64")
                m = m | ids.isin(linked_ids)
            except Exception:
                pass
        if has_key:
            keys = f_df["key"].astype(str)
            m = m | keys.isin(linked_keys)
        return int(m.sum())

    covered_story = _covered_count(f_story)
    covered_epic  = _covered_count(f_epic)
    denom_cover   = int(f_story.shape[0] + f_epic.shape[0])
    pct_story_cov = _pct(covered_story + covered_epic, denom_cover)

    # atualiza o card
    with col1[3]:
        st.metric("% Story Coverage", f"{pct_story_cov:.2f}%")

    # -------- # Test average per issue (Stories + Epics + Func)
    # contabiliza quantos test cases (distinct por test case) cada issue tem
    counts_by_issue = []

    # por ID
    if not links_id.empty:
        # Filtra pelos IDs de issues relevantes
        ids_rel = set()
        for d in (f_story, f_epic, f_func):
            if not d.empty and "id" in d.columns:
                ids_rel |= set(pd.to_numeric(d["id"], errors="coerce").dropna().astype("Int64").tolist())
        if ids_rel:
            tmp = links_id[links_id["issue_id"].isin(ids_rel)]
            if not tmp.empty:
                by = tmp.groupby("issue_id")["tc_id"].nunique()
                counts_by_issue.extend(by.tolist())

    # por KEY (caso não haja ID disponível no CSV)
    if not links_key.empty:
        keys_rel = set()
        for d in (f_story, f_epic, f_func):
            if not d.empty and "key" in d.columns:
                keys_rel |= set(d["key"].dropna().astype(str).tolist())
        if keys_rel:
            tmp = links_key[links_key["issue_key"].isin(keys_rel)]
            if not tmp.empty:
                by = tmp.groupby("issue_key")["tc_id"].nunique()
                counts_by_issue.extend(by.tolist())

    total_issues = int(f_story.shape[0] + f_epic.shape[0] + f_func.shape[0])
    total_tests_linkados = int(sum(counts_by_issue))
    avg_tests_per_issue = (total_tests_linkados / total_issues) if total_issues > 0 else 0.0

    with col3[3]:
        st.metric("# Test average per issue", f"{avg_tests_per_issue:.2f}")

    # ---------------- Cards finais (Closed + %)
    col4 = st.columns(4)
    story_status_map = dict(zip(df_story_raw.get("key", pd.Series(dtype="object")).astype(str), _status_series(df_story_raw))) if not df_story_raw.empty and "key" in df_story_raw.columns else {}
    epic_status_map  = dict(zip(df_epic_raw.get("key",  pd.Series(dtype="object")).astype(str), _status_series(df_epic_raw)))  if not df_epic_raw.empty and "key" in df_epic_raw.columns  else {}

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

    # ---------------- Automated Backlog
    st.markdown("#### Automated Backlog")
    if f_zc.empty:
        if total_tests == 0:
            st.info("Sem dados de casos de teste (Zephyr Test Cases).")
    else:
        auto_col = _first_col(f_zc, ["customFields.Automation Status"])
        if auto_col:
            auto_mask = f_zc[auto_col].apply(_is_automated_from_custom_status_exact)
        else:
            auto_mask = pd.Series(False, index=f_zc.index)
        not_app   = f_zc.get("status", pd.Series(dtype="object")).astype(str).str.contains("not applic", case=False, na=False)
        n_auto, n_total, n_not_app = int(auto_mask.sum()), int(len(f_zc)), int(not_app.sum())
        n_backlog = max(0, n_total - n_auto - n_not_app)
        df_auto_stack = pd.DataFrame({"Categoria": ["Automated","Backlog automated","Not applicable"],
                                      "Quantidade": [n_auto, n_backlog, n_not_app]})
        chart_auto = alt.Chart(df_auto_stack).mark_bar().encode(
            x=alt.X("Quantidade:Q", title="Quantidade"),
            y=alt.Y("Categoria:N", sort=None, title=None),
            color=alt.Color("Categoria:N", legend=None)
        ).properties(height=120)
        st.altair_chart(chart_auto, use_container_width=True)

    # ---------------- Gráficos (mantidos)
    cA, cB, cC = st.columns(3)
    with cA:
        st.markdown("#### Regressive × Others (Test type)")
        if f_ze.empty or "testType" not in f_ze.columns:
            st.info("Sem dados suficientes para agrupar por 'testType'.")
        else:
            z = f_ze.copy()
            z["grp"] = np.where(z["testType"].astype(str).str.lower().str.contains("regress"), "Regressive", "Others")
            df_grp = z.groupby("grp").size().reset_index(name="runs")
            ch = alt.Chart(df_grp).mark_bar().encode(
                x=alt.X("grp:N", title=None), y=alt.Y("runs:Q", title="Runs"),
                color=alt.Color("grp:N", legend=None)
            ).properties(height=220)
            st.altair_chart(ch, use_container_width=True)

    with cB:
        st.markdown("#### Positive × Negative (labels/testType)")
        if f_ze.empty:
            st.info("Sem execuções no período.")
        else:
            z = f_ze.copy()
            neg = pd.Series(False, index=z.index)
            if "testType" in z.columns:
                neg |= z["testType"].astype(str).str.lower().str.contains("negative|negativo")
            if "labels" in z.columns:
                neg |= z["labels"].astype(str).str.lower().str.contains("negative|negativo")
            df_pn = pd.DataFrame({"class": ["Positive","Negative"], "runs": [int((~neg).sum()), int(neg.sum())]})
            ch = alt.Chart(df_pn).mark_bar().encode(
                x=alt.X("class:N", title=None), y=alt.Y("runs:Q", title="Runs"),
                color=alt.Color("class:N", legend=None)
            ).properties(height=220)
            st.altair_chart(ch, use_container_width=True)

    with cC:
        st.markdown("#### Automated run × Manual run")
        if f_ze.empty or "automated" not in f_ze.columns:
            st.info("Sem execuções no período.")
        else:
            is_auto = _is_automated_bool_series(f_ze["automated"])
            df_am = pd.DataFrame({"tipo": ["Automated","Manual"], "runs": [int(is_auto.sum()), int((~is_auto).sum())]})
            ch = alt.Chart(df_am).mark_bar().encode(
                x=alt.X("tipo:N", title=None), y=alt.Y("runs:Q", title="Runs"),
                color=alt.Color("tipo:N", legend=None)
            ).properties(height=220)
            st.altair_chart(ch, use_container_width=True)


if __name__ == "__main__":
    pagina_dashboard_coverage_and_run()
