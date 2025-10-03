# kpis/dashboard_kpi.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from pathlib import Path
from datetime import datetime

DATA = Path("config/database")

# nomes “alvo” (serão buscados com fallback)
JIRA_FUNC = "jira_issues_func_latest.csv"
JIRA_EPIC = "jira_issues_epic_latest.csv"
JIRA_STORY = "jira_issues_story_latest.csv"
JIRA_BUG = "jira_issues_bug_latest.csv"
JIRA_SUBBUG = "jira_issues_subbug_latest.csv"
JIRA_PROJ = "jira_projetos_latest.csv"

ZEPHYR_TC = "zephyr_testcases_latest.csv"
ZEPHYR_EXEC_MAIN = "zephyr_testexecutions_latest.csv"
ZEPHYR_EXEC_FALLBACK = "zephyr_executions_latest.csv"
ZEPHYR_CYCLE_MAIN = "zephyr_testcycles_latest.csv"
ZEPHYR_CYCLE_FALLBACK = "zephyr_test_cycles_latest.csv"

KPI_TARGETS = "kpi_targets.csv"

KPI_LASTUPDATE = "lastUpdate.csv"  # criado pelo scheduler.py

# --- Config visu (cores por meta) ---
WARN_RATIO = 0.10  # banda "amarela" = 10% da meta

# ---------- utils “seguros” ----------
def _first_existing(file_candidates):
    """retorna o primeiro arquivo existente (e não vazio) dentre as opções"""
    for name in ([file_candidates] if isinstance(file_candidates, str) else file_candidates):
        p = DATA / name
        if p.exists() and p.stat().st_size > 0:
            return p
    return None

def safe_read_csv(file_candidates, columns=None) -> pd.DataFrame:
    p = _first_existing(file_candidates)
    if not p:
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

def first_non_null_col(df: pd.DataFrame, candidates) -> pd.Series:
    if df.empty:
        return pd.Series([], dtype="object")
    for c in candidates:
        if c in df.columns:
            return df[c]
    return pd.Series([pd.NA] * len(df))

def to_month_from_str(dt_str):
    if pd.isna(dt_str):
        return None
    try:
        return pd.to_datetime(dt_str, errors="coerce").strftime("%Y-%m")
    except Exception:
        return None

def to_month_from_dt(dt_series: pd.Series) -> pd.Series:
    s = pd.to_datetime(dt_series, errors="coerce")
    return s.dt.strftime("%Y-%m")

def pct(a, b):
    return (float(a) / float(b) * 100.0) if (b not in (0, None, np.nan)) else 0.0

def normalize_issue_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza JIRA issues para colunas [id, key, projectKey, created, month]."""
    if df.empty:
        return pd.DataFrame(columns=["id", "key", "projectKey", "created", "month"])
    out = pd.DataFrame()
    out["id"] = pd.to_numeric(first_non_null_col(df, ["id"]), errors="coerce").astype("Int64")
    out["key"] = first_non_null_col(df, ["key"]).astype(str)
    if "projectKey" in df.columns:
        out["projectKey"] = df["projectKey"].astype(str)
    else:
        out["projectKey"] = out["key"].apply(key_project_prefix)
    created = first_non_null_col(df, ["created", "fields.created"])
    out["created"] = pd.to_datetime(created, errors="coerce")
    out["month"] = out["created"].dt.strftime("%Y-%m")
    out = out.dropna(subset=["id"]).drop_duplicates(subset=["id"])
    return out

def _split_ids_to_ints(val) -> list[int]:
    """Split de '123;456' ou '123,456' em ints; ignora lixo."""
    ids = []
    if pd.isna(val):
        return ids
    if isinstance(val, (int, np.integer)):
        return [int(val)]
    s = str(val).replace(",", ";")
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(float(part)))
        except Exception:
            pass
    return ids

def extract_linked_issue_ids(df: pd.DataFrame, col_candidates=("links.issues.issueId",)) -> set[int]:
    """Coleta os IDs de issues linkados (coluna lista/semicolons)."""
    if df.empty:
        return set()
    col = None
    for c in col_candidates:
        if c in df.columns:
            col = c
            break
    if not col:
        return set()
    out = set()
    for v in df[col].dropna().tolist():
        for i in _split_ids_to_ints(v):
            out.add(i)
    return out

# --------- NOVO: anos e filtro por ano ---------
def _extract_years_from_col(series: pd.Series) -> list[int]:
    """Extrai anos válidos de uma série com datas ou 'YYYY-MM'."""
    if series.empty:
        return []
    s = series.copy()
    if series.dtype == "O":
        # tenta 'YYYY-MM' primeiro
        if s.str.match(r"^\d{4}-\d{2}$", na=False).any():
            years = pd.to_datetime(s + "-01", errors="coerce").dt.year
        else:
            years = pd.to_datetime(s, errors="coerce").dt.year
    else:
        years = pd.to_datetime(s, errors="coerce").dt.year
    return [int(y) for y in years.dropna().astype(int).tolist() if 2000 < int(y) < 2100]

def extract_years_from_dfs(dfs: list[pd.DataFrame]) -> list[int]:
    """Varre dataframes e agrega todos os anos encontrados nas colunas conhecidas."""
    candidates = [
        # JIRA issues
        "created", "fields.created", "resolutiondate", "fields.resolutiondate", "month",
        # BUGs
        "dta_criacao", "dta_resolutiondate",
        # Zephyr
        "actualEndDate", "executedOn", "createdOn"
    ]
    years = set()
    for df in dfs:
        if df.empty:
            continue
        for c in candidates:
            if c in df.columns:
                years.update(_extract_years_from_col(df[c]))
    out = sorted(years)
    return out

def apply_year_filter(df: pd.DataFrame, sel_year: str) -> pd.DataFrame:
    """Filtra por ano usando a 1ª coluna de data encontrada no DF."""
    if df.empty or sel_year == "Todos":
        return df
    year = int(sel_year)
    candidates = [
        "created", "fields.created", "resolutiondate", "fields.resolutiondate", "month",
        "dta_criacao", "dta_resolutiondate", "actualEndDate", "executedOn", "createdOn"
    ]
    df2 = df.copy()
    for c in candidates:
        if c in df2.columns:
            if c == "month":
                # month = 'YYYY-MM'
                m = df2["month"].astype(str).str.slice(0, 4)
                return df2[m == str(year)]
            years = pd.to_datetime(df2[c], errors="coerce").dt.year.astype("Int64")
            return df2[years == year]
    return df2

# =========================================================
def pagina_dashboard_kpi():
    # evitar erro se já setado em outro lugar
    try:
        st.set_page_config(page_title="Quality KPI's", layout="wide")
    except Exception:
        pass

    # CSS
    st.markdown(
        """
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
.kpi-selected button {
  outline: 2px solid #ba55d3 !important;
  background: rgba(186,85,211,.16) !important;
  border-color: transparent !important;
}
.block-container { padding-left: 1rem; padding-right: 1rem; }

/* === Cores leves por estado do KPI === */
.kpi-below button { /* Vermelho leve */
  outline: 2px solid #d9534f !important;
  background: rgba(217,83,79,.16) !important;
  border-color: transparent !important;
}
.kpi-near button { /* Amarelo leve */
  outline: 2px solid #f0ad4e !important;
  background: rgba(240,173,78,.16) !important;
  border-color: transparent !important;
}
.kpi-ok button { /* Verde leve */
  outline: 2px solid #5cb85c !important;
  background: rgba(92,184,92,.16) !important;
  border-color: transparent !important;
}
</style>
""",
        unsafe_allow_html=True,
    )

    st.markdown("### Quality KPI’s")

    # ---- Carrega bases (com fallback onde precisa)
    df_func_raw = safe_read_csv(JIRA_FUNC)
    df_epic_raw = safe_read_csv(JIRA_EPIC)
    df_story_raw = safe_read_csv(JIRA_STORY)
    df_bug = safe_read_csv(JIRA_BUG)
    df_subbug = safe_read_csv(JIRA_SUBBUG)
    df_proj = safe_read_csv(JIRA_PROJ)

    # Zephyr – test cases / test executions / test cycles
    df_zc = safe_read_csv(ZEPHYR_TC)  # precisa para cobertura/avg e KPIs de TC
    df_ze = safe_read_csv([ZEPHYR_EXEC_MAIN, ZEPHYR_EXEC_FALLBACK])
    df_cyc = safe_read_csv([ZEPHYR_CYCLE_MAIN, ZEPHYR_CYCLE_FALLBACK])

    df_targets = safe_read_csv(KPI_TARGETS, columns=["kpi", "projectKey", "year", "target", "goal"])
    if not df_targets.empty:
        # normaliza tipos
        df_targets["kpi"] = df_targets["kpi"].astype(str)
        df_targets["projectKey"] = df_targets["projectKey"].astype(str)
        df_targets["year"] = pd.to_numeric(df_targets["year"], errors="coerce").astype("Int64")
        df_targets["target"] = pd.to_numeric(df_targets["target"], errors="coerce")
        df_targets["goal"] = df_targets["goal"].astype(str).str.lower()
    else:
        df_targets = pd.DataFrame(columns=["kpi", "projectKey", "year", "target", "goal"])

    # ---- Normaliza issues JIRA
    df_func = normalize_issue_df(df_func_raw)
    df_epic = normalize_issue_df(df_epic_raw)
    df_story = normalize_issue_df(df_story_raw)

    # ---- auxiliares execuções (datas e project key) – AGORA via coluna key
    if not df_ze.empty:
        # projectKey = prefixo da coluna "key" (ex.: TBCC-E10062 -> TBCC)
        if "key" in df_ze.columns:
            df_ze["projectKey"] = df_ze["key"].astype(str).str.split("-").str[0]
        else:
            df_ze["projectKey"] = pd.NA
        exec_date_col = (
            "actualEndDate"
            if "actualEndDate" in df_ze.columns
            else ("executedOn" if "executedOn" in df_ze.columns else None)
        )
        df_ze["month"] = df_ze[exec_date_col].apply(to_month_from_str) if exec_date_col else pd.NA

    # ---- test cases / cycles → conjunto de IDs de issues linkados
    tc_issue_ids = extract_linked_issue_ids(df_zc, ("links.issues.issueId",))
    cyc_issue_ids = extract_linked_issue_ids(df_cyc, ("links.issues.issueId",))
    linked_issue_ids = tc_issue_ids | cyc_issue_ids  # usado no %coverage e filtros de TC

    # ---- Projetos para filtro (lookup por nome → key)
    if not df_proj.empty and {"name", "key"}.issubset(df_proj.columns):
        projects_tuples = [
            (row["name"], row["key"])
            for _, row in df_proj.iterrows()
            if pd.notna(row["name"]) and pd.notna(row["key"])
        ]
        project_names = [name for name, _ in projects_tuples]
        name_to_key = {name: key for name, key in projects_tuples}
    else:
        pref = pd.concat([df_func["projectKey"], df_epic["projectKey"], df_story["projectKey"]], ignore_index=True)
        project_names = sorted([p for p in pref.dropna().unique().tolist() if p])
        name_to_key = {p: p for p in project_names}

    # -------- NOVO: anos disponíveis (depois de montar month nas execuções)
    all_years = extract_years_from_dfs([df_func_raw, df_epic_raw, df_story_raw, df_bug, df_subbug, df_ze, df_zc, df_cyc])
    year_options = ["Todos"] + [str(y) for y in all_years]

    c1, c2, c3 = st.columns([0.35, 0.3, 0.35])
    with c1:
        sel_project_name = st.selectbox("Tribo (Projeto)", options=["Todos"] + project_names, index=0)
    with c2:
        sel_year = st.selectbox("Ano", options=year_options, index=0)
    with c3:
        p = _first_existing(KPI_LASTUPDATE)
        dt = pd.read_csv(p).iloc[0,0]
        st.caption(f"Atualizado: {dt}")

    c1, c2, c3 = st.columns([0.35, 0.3, 0.35])
    with c1:
        st.caption("Clique em um card abaixo para trocar o gráfico do KPI.")
    with c2:
        st.caption("")
    with c3:
        st.caption("")

    # ---- aplica filtro de projeto nos datasets JIRA
    def apply_project_issues(df):
        if df.empty or sel_project_name == "Todos":
            return df
        project_key = name_to_key.get(sel_project_name, sel_project_name)
        return df[df["projectKey"] == project_key].copy()

    def executions_filtered_by_project() -> pd.DataFrame:
        if df_ze.empty or sel_project_name == "Todos":
            return df_ze
        project_key = name_to_key.get(sel_project_name, sel_project_name)
        return df_ze[df_ze["projectKey"].astype(str) == str(project_key)].copy()

    # ---- auxiliares execuções (datas e project key) – mantido para outros KPIs
    def _extract_proj_from_text(txt: str) -> str:
        """Tenta achar um padrão PROJ-123 em qualquer string e retorna só o PROJ."""
        if not isinstance(txt, str):
            return ""
        import re
        m = re.search(r"([A-Z][A-Z0-9_]+)-\d+", txt)
        return m.group(1) if m else ""

    def _ensure_project_on_executions(df: pd.DataFrame) -> pd.DataFrame:
        """Garante coluna projectKey nas execuções Zephyr, usando várias fontes possíveis."""
        if df.empty:
            return df.copy()
        out = df.copy()
        # 1) Se já existe, normaliza pra string
        if "projectKey" in out.columns:
            out["projectKey"] = out["projectKey"].astype(str)
        # 2) issueKey (ex.: TRBC-123) -> prefixo
        if "projectKey" not in out.columns or out["projectKey"].isna().all():
            if "issueKey" in out.columns:
                out["projectKey"] = out["issueKey"].astype(str).apply(_extract_proj_from_text)
        # 3) testCase.key (ex.: TRBC-T123, TRBC-123 etc)
        if "projectKey" not in out.columns or out["projectKey"].replace("", pd.NA).isna().all():
            for c in ["testCase.key", "testcase.key", "testCaseKey"]:
                if c in out.columns:
                    out["projectKey"] = out[c].astype(str).apply(_extract_proj_from_text)
                    break
        # 4) URLs: testCase.self / testCycle.self
        if "projectKey" not in out.columns or out["projectKey"].replace("", pd.NA).isna().all():
            for c in ["testCase.self", "testcase.self", "testCase.url", "testCycle.self", "testcycle.self"]:
                if c in out.columns:
                    proj = out[c].astype(str).apply(_extract_proj_from_text)
                    if proj.notna().any():
                        out["projectKey"] = proj
                        break
        if "projectKey" not in out.columns:
            out["projectKey"] = ""
        exec_date_col = (
            "actualEndDate" if "actualEndDate" in out.columns else ("executedOn" if "executedOn" in out.columns else None)
        )
        out["month"] = out[exec_date_col].apply(to_month_from_str) if exec_date_col else pd.NA
        return out

    if not df_ze.empty:
        df_ze = _ensure_project_on_executions(df_ze)

    def executions_filtered_by_project() -> pd.DataFrame:
        """Retorna execuções filtradas pelo projeto do select, se possível."""
        if df_ze.empty or sel_project_name == "Todos":
            return df_ze
        project_key = name_to_key.get(sel_project_name, sel_project_name)
        if "projectKey" not in df_ze.columns:
            return pd.DataFrame(columns=df_ze.columns)
        return df_ze[df_ze["projectKey"].astype(str) == str(project_key)].copy()

    def filter_executions_by_project(exec_df: pd.DataFrame) -> pd.DataFrame:
        """
        Retorna df_ze filtrado pelo projeto selecionado.
        Estratégia:
        1) Se houver projectKey em exec_df, filtra direto por ele.
        2) Caso contrário, cruza testCase.id -> df_zc.id -> links.issues.issueId
           e mantém apenas executions cujos TCs estão linkados a issues do projeto.
        """
        if exec_df.empty or sel_project_name == "Todos":
            return exec_df
        project_key = name_to_key.get(sel_project_name, sel_project_name)
        if "projectKey" in exec_df.columns:
            tmp = exec_df[exec_df["projectKey"].astype(str) == str(project_key)].copy()
            return tmp
        if "testCase.id" not in exec_df.columns or df_zc.empty:
            return exec_df[[]].copy()
        if not issue_ids_sel:
            return exec_df[[]].copy()
        tc_link_col = "links.issues.issueId" if "links.issues.issueId" in df_zc.columns else None
        if tc_link_col is None:
            return exec_df[[]].copy()
        tcz = df_zc[["id", tc_link_col]].dropna(subset=["id"]).copy()
        tcz["id"] = pd.to_numeric(tcz["id"], errors="coerce").astype("Int64")
        tcz = tcz.dropna(subset=["id"])

        def tc_belongs(val):
            for iid in _split_ids_to_ints(val):
                if iid in issue_ids_sel:
                    return True
            return False

        tcz["in_project"] = tcz[tc_link_col].apply(tc_belongs)
        tmp = exec_df.copy()
        tmp["testCase.id"] = pd.to_numeric(tmp["testCase.id"], errors="coerce").astype("Int64")
        tmp = tmp.merge(tcz[["id", "in_project"]], left_on="testCase.id", right_on="id", how="left")
        tmp = tmp[tmp["in_project"] == True].copy()
        tmp.drop(columns=["id", "in_project"], inplace=True)
        return tmp

    def _resolve_project_key_for_targets() -> str:
        # usa o projectKey do select; se "Todos", usa '*'
        if sel_project_name == "Todos":
            return "*"
        return name_to_key.get(sel_project_name, sel_project_name)

    def get_target(kpi_key: str, year: int | None = None) -> tuple[float | None, str | None]:
        """
        Retorna (target, goal) para o KPI e projeto selecionado, com fallback:
        1) projectKey específico no ano
        2) default '*' no ano
        3) projectKey sem ano (year nulo)
        4) default '*' sem ano
        """
        if df_targets.empty:
            return (None, None)
        pk = _resolve_project_key_for_targets()
        yr = year or datetime.now().year
        candidates = [
            (pk, yr),
            ("*", yr),
            (pk, pd.NA),
            ("*", pd.NA),
        ]
        for proj, y in candidates:
            mask = (df_targets["kpi"] == kpi_key) & (df_targets["projectKey"] == str(proj))
            if pd.isna(y):
                mask = mask & (df_targets["year"].isna())
            else:
                mask = mask & (df_targets["year"] == yr)
            row = df_targets[mask].head(1)
            if not row.empty:
                return (
                    float(row["target"].iloc[0]) if pd.notna(row["target"].iloc[0]) else None,
                    row["goal"].iloc[0] if pd.notna(row["goal"].iloc[0]) else None,
                )
        return (None, None)

    # helper: aplica filtro de projeto nos datasets de BUGs
    def apply_project_bugs(df):
        if df.empty or sel_project_name == "Todos":
            return df
        project_key = name_to_key.get(sel_project_name, sel_project_name)
        for col in ["projectKey", "cod_projeto", "project_key", "project"]:
            if col in df.columns:
                try:
                    return df[df[col].astype(str) == str(project_key)].copy()
                except Exception:
                    pass
        return df

    # ------- NOVO: aplicar filtro de ano nos DFs relevantes -------
    df_func_f = apply_year_filter(apply_project_issues(df_func), sel_year)
    df_epic_f = apply_year_filter(apply_project_issues(df_epic), sel_year)
    df_story_f = apply_year_filter(apply_project_issues(df_story), sel_year)

    df_bug_f = apply_year_filter(apply_project_bugs(df_bug), sel_year)
    df_subbug_f = apply_year_filter(apply_project_bugs(df_subbug), sel_year)

    df_zc = apply_year_filter(df_zc, sel_year)   # createdOn (se existir)
    df_cyc = apply_year_filter(df_cyc, sel_year) # createdOn (se existir)
    df_ze = apply_year_filter(executions_filtered_by_project(), sel_year)  # actualEndDate/executedOn ou month

    # helper: set de issueIds do projeto selecionado (já com ano aplicado)
    base_issues_sel = pd.concat([df_func_f, df_story_f, df_epic_f], ignore_index=True)
    issue_ids_sel = set(int(x) for x in base_issues_sel["id"].dropna().astype(int).tolist())

    # === KPI: % Total Coverage (mantido) ===
    def coverage_now():
        base = base_issues_sel
        if base.empty:
            return 0.0
        covered = base["id"].astype("Int64").isin(linked_issue_ids).sum()
        return round(pct(covered, len(base)), 2)

    # === KPI: Test AVG por issue (MÉDIA DE TEST CASES por issue COM TEST CASE) ===
    def test_avg_per_issue_now():
        base = base_issues_sel
        if base.empty or df_zc.empty:
            return 0.0
        col_tc = "links.issues.issueId" if "links.issues.issueId" in df_zc.columns else None
        if not col_tc:
            return 0.0
        tc_counts = {}
        for v in df_zc[col_tc].dropna().tolist():
            for iid in _split_ids_to_ints(v):
                tc_counts[iid] = tc_counts.get(iid, 0) + 1
        if not tc_counts:
            return 0.0
        issue_ids_proj = set(int(x) for x in base["id"].dropna().astype(int).tolist())
        issues_com_tc = [iid for iid in issue_ids_proj if tc_counts.get(iid, 0) > 0]
        den = len(issues_com_tc)
        if den == 0:
            return 0.0
        total_tc = sum(tc_counts[iid] for iid in issues_com_tc)
        return round(float(total_tc) / float(den), 2)

    # === KPI: % Automated Runs (mantido – baseado em executions) ===
    def kpi_auto_runs_now():
        tmp = df_ze  # já filtrado por projeto + ano
        if tmp.empty or "automated" not in tmp.columns:
            return 0.0
        is_auto = tmp["automated"].astype(str).str.lower().isin(["1", "true", "yes"])
        return round(pct(int(is_auto.sum()), len(tmp)), 2)

    # === KPI: % Test Regression (via TEST CASES + projeto)
    def kpi_test_reg_now():
        if df_zc.empty:
            return 0.0
        tcz = df_zc.copy()
        li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
        if sel_project_name != "Todos" and issue_ids_sel and li_col:
            mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
            tcz = tcz[mask_link]
        if tcz.empty:
            return 0.0
        tc_type_col = None
        for c in ["customFields.Test Type", "customFields.TestType", "customFields.Test type", "customFields.Test_Type"]:
            if c in tcz.columns:
                tc_type_col = c
                break
        if tc_type_col is None:
            return 0.0
        den = len(tcz)
        num = int(tcz[tc_type_col].astype(str).str.lower().str.contains("regress").sum())
        return round(pct(num, den), 2)

    # === KPI: % Automated Regression (AJUSTE: usa Automation Status OU PASS)
    def kpi_auto_reg_now():
        if df_zc.empty:
            return 0.0
        tc_type_col = None
        for c in ["customFields.Test Type", "customFields.TestType", "customFields.Test type", "customFields.Test_Type"]:
            if c in df_zc.columns:
                tc_type_col = c
                break
        auto_col = None
        for c in ["customFields.Automation Status", "customFields.AutomationStatus", "automationStatus"]:
            if c in df_zc.columns:
                auto_col = c
                break
        if tc_type_col is None:
            return 0.0
        tcz = df_zc.copy()
        if sel_project_name != "Todos" and issue_ids_sel:
            li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
            if li_col:
                mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
                tcz = tcz[mask_link]
        tcz = tcz[tcz[tc_type_col].astype(str).str.lower().str.contains("regress")].copy()
        if tcz.empty:
            return 0.0
        reg_tc_ids = set(int(x) for x in pd.to_numeric(tcz.get("id"), errors="coerce").dropna().astype(int).tolist())
        den = len(reg_tc_ids)
        if den == 0:
            return 0.0

        # Automated por status e/ou PASS em execuções (já filtradas por ano)
        auto_ids = set()
        if auto_col:
            auto_mask = tcz[auto_col].astype(str).str.strip().str.lower().eq("automated")
            auto_ids = set(pd.to_numeric(tcz.loc[auto_mask, "id"], errors="coerce").dropna().astype(int).tolist())

        pass_ids = set()
        if not df_ze.empty and "testCase.id" in df_ze.columns:
            pass_mask = pd.Series(False, index=df_ze.index)
            if "status" in df_ze.columns:
                pass_mask |= df_ze["status"].astype(str).str.lower().str.contains("pass")
            if "testExecutionStatus.self" in df_ze.columns:
                pass_mask |= df_ze["testExecutionStatus.self"].astype(str).str.lower().str.contains("pass")
            pass_ids = set(pd.to_numeric(df_ze.loc[pass_mask, "testCase.id"], errors="coerce").dropna().astype(int).tolist())

        automated_reg_ids = (auto_ids | pass_ids) & reg_tc_ids
        num = len(automated_reg_ids)
        return round(pct(num, den), 2)

    # === KPI: % Negative Test (via TEST CASES + projeto)
    def kpi_negative_now():
        if df_zc.empty:
            return 0.0
        tcz = df_zc.copy()
        li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
        if sel_project_name != "Todos" and issue_ids_sel and li_col:
            mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
            tcz = tcz[mask_link]
        if tcz.empty:
            return 0.0
        tc_class_col = None
        for c in ["customFields.Test Class", "customFields.TestClass", "customFields.Test class", "customFields.Test_Class"]:
            if c in tcz.columns:
                tc_class_col = c
                break
        if tc_class_col is None:
            return 0.0
        den = len(tcz)
        num = int(tcz[tc_class_col].astype(str).str.lower().str.contains("negative").sum())
        return round(pct(num, den), 2)

    def avg_bug_days(df_a, df_b):
        """
        Média de dias entre abertura e resolução de BUGs.
        - Respeita o projeto selecionado.
        - Considera somente linhas com data de criação e de resolução válidas.
        - Retorna 0.0 se não houver linhas válidas.
        """
        dfa = apply_project_bugs(df_a) if isinstance(df_a, pd.DataFrame) else pd.DataFrame()
        dfb = apply_project_bugs(df_b) if isinstance(df_b, pd.DataFrame) else pd.DataFrame()
        # aplica filtro de ano nos bugs também
        dfa = apply_year_filter(dfa, sel_year)
        dfb = apply_year_filter(dfb, sel_year)

        if dfa.empty and dfb.empty:
            return 0.0
        d = pd.concat([dfa, dfb], ignore_index=True) if not (dfa.empty or dfb.empty) else (dfa if dfb.empty else dfb)
        created_candidates = ["created", "fields.created", "dta_criacao", "createdDate"]
        resolved_candidates = ["resolutiondate", "fields.resolutiondate", "dta_resolutiondate", "dta_resolucao", "resolved"]
        created_s = first_non_null_col(d, created_candidates)
        resolved_s = first_non_null_col(d, resolved_candidates)
        c = pd.to_datetime(created_s, errors="coerce", utc=True)
        r = pd.to_datetime(resolved_s, errors="coerce", utc=True)
        valid = c.notna() & r.notna()
        if not valid.any():
            return 0.0
        days = (r[valid] - c[valid]).dt.total_seconds() / 86400.0
        return round(float(days.mean()), 2) if not days.empty else 0.0

    # ----- valores dos cartões
    kpi_coverage = coverage_now()
    kpi_test_avg = test_avg_per_issue_now()
    kpi_auto_runs = kpi_auto_runs_now()
    kpi_auto_reg = kpi_auto_reg_now()  # <<< ajuste aplicado
    kpi_test_reg = kpi_test_reg_now()
    kpi_negative = kpi_negative_now()  # por Test Cases
    kpi_bug_days = avg_bug_days(df_bug_f, df_subbug_f)

    # --- helpers de formatação de meta/Δ e da classe visual ---
    def _format_delta(kpi_key: str, val: float, as_pct: bool) -> str:
        # usa o ano selecionado
        tgt, _goal = get_target(kpi_key, None if sel_year == "Todos" else int(sel_year))
        if tgt is None:
            return ""
        delta = float(val) - float(tgt)
        if as_pct:
            # delta em pontos percentuais
            return f"\nΔ {delta:+.2f}pp"
        else:
            return f"\nΔ {delta:+.2f}"

    def _fmt_with_target(kpi_key: str, val: float, as_pct: bool) -> str:
        tgt, goal = get_target(kpi_key, None if sel_year == "Todos" else int(sel_year))
        v = f"{val:.2f}%" if as_pct else f"{val:.2f}"
        if tgt is None:
            return v
        tgt_s = f"{tgt:.0f}%" if as_pct else f"{tgt:.2f}"
        arrow = "↑" if (goal or "max") == "max" else "↓"
        return f"{v}\nTarget {arrow} {tgt_s}{_format_delta(kpi_key, val, as_pct)}"

    def _kpi_state_class(kpi_key: str, val: float, as_pct: bool) -> str:
        tgt, goal = get_target(kpi_key, None if sel_year == "Todos" else int(sel_year))
        if tgt is None:
            return ""
        goal = (goal or "max").lower()
        band = abs(tgt) * WARN_RATIO
        if goal == "max":
            if val < (tgt - band):
                return "kpi-below"   # vermelho
            elif val < tgt:
                return "kpi-near"    # amarelo
            else:
                return "kpi-ok"      # verde
        else:  # menor é melhor
            if val > (tgt + band):
                return "kpi-below"
            elif val > tgt:
                return "kpi-near"
            else:
                return "kpi-ok"

    KPI_DEFS = {
        "coverage": {"title": "% Total Coverage", "value": _fmt_with_target("coverage", kpi_coverage, True)},
        "test_avg": {"title": "Test AVG per issue", "value": _fmt_with_target("test_avg", kpi_test_avg, False)},
        "auto_reg": {"title": "% Automated Regression", "value": _fmt_with_target("auto_reg", kpi_auto_reg, True)},
        "auto_runs": {"title": "% Automated Runs", "value": _fmt_with_target("auto_runs", kpi_auto_runs, True)},
        "test_reg": {"title": "% Test Regression", "value": _fmt_with_target("test_reg", kpi_test_reg, True)},
        "negative": {"title": "% Negative Test", "value": _fmt_with_target("negative", kpi_negative, True)},
        "bug_days": {"title": "AVG days resolution Bug", "value": _fmt_with_target("bug_days", kpi_bug_days, False)},
    }

    # --- classe (cor) por KPI ---
    KPI_CLASS = {
        "coverage": _kpi_state_class("coverage", kpi_coverage, True),
        "test_avg": _kpi_state_class("test_avg", kpi_test_avg, False),
        "auto_reg": _kpi_state_class("auto_reg", kpi_auto_reg, True),
        "auto_runs": _kpi_state_class("auto_runs", kpi_auto_runs, True),
        "test_reg": _kpi_state_class("test_reg", kpi_test_reg, True),
        "negative": _kpi_state_class("negative", kpi_negative, True),
        "bug_days": _kpi_state_class("bug_days", kpi_bug_days, False),
    }

    if "kpi_selected" not in st.session_state:
        st.session_state["kpi_selected"] = "coverage"

    # ---------- cards-botão ----------
    def kpi_button(col, key, label, value, btn_key, extra_cls=""):
        selected = (st.session_state["kpi_selected"] == key)
        klass = " ".join(cls for cls in [
            "kpi-selected" if selected else "",
            extra_cls
        ] if cls)
        with col.container():
            st.write(f'<div class="{klass}">', unsafe_allow_html=True)
            clicked = st.button(f"{label}\n{value}", key=btn_key, use_container_width=True)
            st.write("</div>", unsafe_allow_html=True)
        if clicked:
            st.session_state["kpi_selected"] = key

    cols = st.columns(7)
    kpi_button(cols[0], "coverage", KPI_DEFS["coverage"]["title"], KPI_DEFS["coverage"]["value"], "btn_cov", KPI_CLASS["coverage"])
    kpi_button(cols[1], "test_avg", KPI_DEFS["test_avg"]["title"], KPI_DEFS["test_avg"]["value"], "btn_tavg", KPI_CLASS["test_avg"])
    kpi_button(cols[2], "auto_reg", KPI_DEFS["auto_reg"]["title"], KPI_DEFS["auto_reg"]["value"], "btn_areg", KPI_CLASS["auto_reg"])
    kpi_button(cols[3], "auto_runs", KPI_DEFS["auto_runs"]["title"], KPI_DEFS["auto_runs"]["value"], "btn_aruns", KPI_CLASS["auto_runs"])
    kpi_button(cols[4], "test_reg", KPI_DEFS["test_reg"]["title"], KPI_DEFS["test_reg"]["value"], "btn_treg", KPI_CLASS["test_reg"])
    kpi_button(cols[5], "negative", KPI_DEFS["negative"]["title"], KPI_DEFS["negative"]["value"], "btn_neg", KPI_CLASS["negative"])
    kpi_button(cols[6], "bug_days", KPI_DEFS["bug_days"]["title"], KPI_DEFS["bug_days"]["value"], "btn_bug", KPI_CLASS["bug_days"])

    st.markdown("---")

    # ---- séries mensais (mantidas + Negative/Test Regression/AutoReg ajustadas)
    df_func_all = df_func_f.copy()
    df_epic_all = df_epic_f.copy()
    df_story_all = df_story_f.copy()

    def monthly_series_coverage():
        base = pd.concat([df_func_all, df_story_all, df_epic_all], ignore_index=True)
        if sel_project_name != "Todos":
            project_key = name_to_key.get(sel_project_name, sel_project_name)
            base = base[base["projectKey"] == project_key]
        if base.empty:
            return pd.DataFrame(columns=["month", "value"])
        tmp = base.copy()
        tmp["covered"] = tmp["id"].astype("Int64").isin(linked_issue_ids)
        g = tmp.groupby("month", dropna=False)["covered"].agg(["sum", "count"]).reset_index()
        g["value"] = g.apply(lambda r: pct(r["sum"], r["count"]), axis=1)
        g = g[["month", "value"]]
        g = g[g["month"].notna()]
        return g

    def monthly_series_test_avg():
        base = pd.concat([df_func_all, df_story_all, df_epic_all], ignore_index=True)
        if sel_project_name != "Todos":
            project_key = name_to_key.get(sel_project_name, sel_project_name)
            base = base[base["projectKey"] == project_key]
        if base.empty or df_zc.empty:
            return pd.DataFrame(columns=["month", "value"])
        col_tc = "links.issues.issueId" if "links.issues.issueId" in df_zc.columns else None
        if not col_tc:
            return pd.DataFrame(columns=["month", "value"])
        tc_counts = {}
        for v in df_zc[col_tc].dropna().tolist():
            for iid in _split_ids_to_ints(v):
                tc_counts[iid] = tc_counts.get(iid, 0) + 1
        if not tc_counts:
            return pd.DataFrame(columns=["month", "value"])
        rows = []
        for m, bucket in base.groupby("month"):
            if pd.isna(m):
                continue
            issue_ids_m = set(int(x) for x in bucket["id"].dropna().astype(int).tolist())
            issues_com_tc_m = [iid for iid in issue_ids_m if tc_counts.get(iid, 0) > 0]
            den = len(issues_com_tc_m)
            if den == 0:
                rows.append({"month": m, "value": 0.0})
                continue
            total_tc_m = sum(tc_counts[iid] for iid in issues_com_tc_m)
            rows.append({"month": m, "value": float(total_tc_m) / float(den)})
        return pd.DataFrame(rows)

    def monthly_series_auto_runs():
        tmp = df_ze  # já filtrado (projeto + ano)
        if tmp.empty or "automated" not in tmp.columns:
            return pd.DataFrame(columns=["month", "value"])
        tmp = tmp[tmp["month"].notna()].copy()
        tmp["is_auto"] = tmp["automated"].astype(str).str.lower().isin(["1", "true", "yes"])
        g = tmp.groupby("month", dropna=False).apply(lambda d: pct(d["is_auto"].sum(), len(d))).reset_index(name="value")
        return g[g["month"].notna()]

    # --- % Automated Regression (mês = createdOn do TC, same rule)
    def monthly_series_auto_reg():
        if df_zc.empty:
            return pd.DataFrame(columns=["month", "value"])
        tc_type_col = None
        for c in ["customFields.Test Type", "customFields.TestType", "customFields.Test type", "customFields.Test_Type"]:
            if c in df_zc.columns:
                tc_type_col = c
                break
        auto_col = None
        for c in ["customFields.Automation Status", "customFields.AutomationStatus", "automationStatus"]:
            if c in df_zc.columns:
                auto_col = c
                break
        if tc_type_col is None:
            return pd.DataFrame(columns=["month", "value"])
        tcz = df_zc.copy()
        if sel_project_name != "Todos" and issue_ids_sel:
            li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
            if li_col:
                mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
                tcz = tcz[mask_link]
        tcz = tcz[tcz[tc_type_col].astype(str).str.lower().str.contains("regress")].copy()
        if tcz.empty:
            return pd.DataFrame(columns=["month", "value"])
        if "createdOn" in tcz.columns:
            tcz["month_tc"] = tcz["createdOn"].apply(to_month_from_str)
        else:
            tcz["month_tc"] = pd.NA

        auto_ids_all = set()
        if auto_col:
            auto_ids_all = set(
                pd.to_numeric(
                    tcz.loc[tcz[auto_col].astype(str).str.strip().str.lower().eq("automated"), "id"], errors="coerce"
                )
                .dropna()
                .astype(int)
                .tolist()
            )
        pass_ids_all = set()
        if not df_ze.empty and "testCase.id" in df_ze.columns:
            pass_mask = pd.Series(False, index=df_ze.index)
            if "status" in df_ze.columns:
                pass_mask |= df_ze["status"].astype(str).str.lower().str.contains("pass")
            if "testExecutionStatus.self" in df_ze.columns:
                pass_mask |= df_ze["testExecutionStatus.self"].astype(str).str.lower().str.contains("pass")
            pass_ids_all = set(
                pd.to_numeric(df_ze.loc[pass_mask, "testCase.id"], errors="coerce").dropna().astype(int).tolist()
            )
        rows = []
        for m, bucket in tcz.groupby("month_tc"):
            if pd.isna(m):
                continue
            ids_month = set(pd.to_numeric(bucket["id"], errors="coerce").dropna().astype(int).tolist())
            den = len(ids_month)
            if den == 0:
                rows.append({"month": m, "value": 0.0})
                continue
            num = len(ids_month & (auto_ids_all | pass_ids_all))
            rows.append({"month": m, "value": pct(num, den)})
        return pd.DataFrame(rows)

    def monthly_series_test_reg():
        if df_zc.empty:
            return pd.DataFrame(columns=["month", "value"])
        tcz = df_zc.copy()
        li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
        if sel_project_name != "Todos" and issue_ids_sel and li_col:
            mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
            tcz = tcz[mask_link]
        if tcz.empty:
            return pd.DataFrame(columns=["month", "value"])
        tc_type_col = None
        for c in ["customFields.Test Type", "customFields.TestType", "customFields.Test type", "customFields.Test_Type"]:
            if c in tcz.columns:
                tc_type_col = c
                break
        if "createdOn" in tcz.columns:
            tcz["month_tc"] = tcz["createdOn"].apply(to_month_from_str)
        else:
            tcz["month_tc"] = pd.NA

        def f(grp: pd.DataFrame):
            den = len(grp)
            if den == 0 or tc_type_col is None:
                return 0.0
            num = int(grp[tc_type_col].astype(str).str.lower().str.contains("regress").sum())
            return pct(num, den)

        g = tcz.groupby("month_tc", dropna=False).apply(f).reset_index(name="value")
        g = g.rename(columns={"month_tc": "month"})
        g = g[g["month"].notna()]
        return g

    def monthly_series_negative():
        if df_zc.empty:
            return pd.DataFrame(columns=["month", "value"])
        tcz = df_zc.copy()
        li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
        if sel_project_name != "Todos" and issue_ids_sel and li_col:
            mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
            tcz = tcz[mask_link]
        if tcz.empty:
            return pd.DataFrame(columns=["month", "value"])
        tc_class_col = None
        for c in ["customFields.Test Class", "customFields.TestClass", "customFields.Test class", "customFields.Test_Class"]:
            if c in tcz.columns:
                tc_class_col = c
                break
        if "createdOn" in tcz.columns:
            tcz["month_tc"] = tcz["createdOn"].apply(to_month_from_str)
        else:
            tcz["month_tc"] = pd.NA

        def f(grp: pd.DataFrame):
            den = len(grp)
            if den == 0 or tc_class_col is None:
                return 0.0
            num = int(grp[tc_class_col].astype(str).str.lower().str.contains("negative").sum())
            return pct(num, den)

        g = tcz.groupby("month_tc", dropna=False).apply(f).reset_index(name="value")
        g = g.rename(columns={"month_tc": "month"})
        g = g[g["month"].notna()]
        return g

    SERIES_FUNCS = {
        "coverage": monthly_series_coverage,
        "test_avg": monthly_series_test_avg,
        "auto_reg": monthly_series_auto_reg,  # <<< ajuste aplicado
        "auto_runs": monthly_series_auto_runs,
        "test_reg": monthly_series_test_reg,
        "negative": monthly_series_negative,  # por Test Cases
        "bug_days": lambda: pd.DataFrame(columns=["month", "value"]),
    }

    sel_key = st.session_state["kpi_selected"]
    title = KPI_DEFS[sel_key]["title"]
    st.markdown(f"#### {title}")
    df_series = SERIES_FUNCS[sel_key]()
    if df_series.empty:
        st.info("Sem dados suficientes para este KPI com os filtros atuais.")
        return

    try:
        df_series["month_dt"] = pd.to_datetime(df_series["month"] + "-01", errors="coerce")
        df_series = df_series.sort_values("month_dt")
    except Exception:
        pass

    y_title = "%" if sel_key in {"coverage", "auto_reg", "auto_runs", "test_reg", "negative"} else "Valor"
    chart = (
        alt.Chart(df_series)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:N", title="Mês"),
            y=alt.Y("value:Q", title=y_title),
            tooltip=["month:N", "value:Q"],
        )
        .properties(height=340, width="container")
    )
    st.altair_chart(chart, use_container_width=True)

# para debug isolado:
if __name__ == "__main__":
    pagina_dashboard_kpi()
