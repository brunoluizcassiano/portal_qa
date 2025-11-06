import re
import numpy as np
import pandas as pd

# ---------- utilitários básicos ----------
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

def pct(a, b):
    return (float(a) / float(b) * 100.0) if (b not in (0, None, np.nan)) else 0.0

def normalize_issue_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza Issues JIRA para [id, key, projectKey, created, month]."""
    if df.empty:
        return pd.DataFrame(columns=["id", "key", "projectKey", "created", "month"])
    out = pd.DataFrame()
    out["id"] = pd.to_numeric(first_non_null_col(df, ["id"]), errors="coerce").astype("Int64")
    out["key"] = first_non_null_col(df, ["key"]).astype(str)
    out["projectKey"] = df["projectKey"].astype(str) if "projectKey" in df.columns else out["key"].apply(key_project_prefix)
    created = first_non_null_col(df, ["created", "fields.created"])
    out["created"] = pd.to_datetime(created, errors="coerce")
    out["month"] = out["created"].dt.strftime("%Y-%m")
    out = out.dropna(subset=["id"]).drop_duplicates(subset=["id"])
    return out

def _split_ids_to_ints(val) -> list[int]:
    """Split de '123;456' ou '123,456' em ints; ignora ruído."""
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
    """Coleta IDs de issues linkados a TCs/Cycles."""
    if df.empty:
        return set()
    col = next((c for c in col_candidates if c in df.columns), None)
    if not col:
        return set()
    out = set()
    for v in df[col].dropna().tolist():
        out.update(_split_ids_to_ints(v))
    return out

# --------- filtros por ano/projeto ----------
def _extract_years_from_col(series: pd.Series) -> list[int]:
    if series.empty:
        return []
    s = series.copy()
    if series.dtype == "O":
        if s.str.match(r"^\d{4}-\d{2}$", na=False).any():
            years = pd.to_datetime(s + "-01", errors="coerce").dt.year
        else:
            years = pd.to_datetime(s, errors="coerce").dt.year
    else:
        years = pd.to_datetime(s, errors="coerce").dt.year
    return [int(y) for y in years.dropna().astype(int).tolist() if 2000 < int(y) < 2100]

def extract_years_from_dfs(dfs: list[pd.DataFrame]) -> list[int]:
    candidates = [
        "created", "fields.created", "resolutiondate", "fields.resolutiondate", "month",
        "dta_criacao", "dta_resolutiondate", "actualEndDate", "executedOn", "createdOn"
    ]
    years = set()
    for df in dfs:
        if df.empty:
            continue
        for c in candidates:
            if c in df.columns:
                years.update(_extract_years_from_col(df[c]))
    return sorted(years)

def apply_year_filter(df: pd.DataFrame, sel_year: str) -> pd.DataFrame:
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
                m = df2["month"].astype(str).str.slice(0, 4)
                return df2[m == str(year)]
            years = pd.to_datetime(df2[c], errors="coerce").dt.year.astype("Int64")
            return df2[years == year]
    return df2

def apply_project_bugs(df: pd.DataFrame, project_key: str | None) -> pd.DataFrame:
    if df.empty or not project_key or project_key == "Todos":
        return df
    for col in ["projectKey", "cod_projeto", "project_key", "project"]:
        if col in df.columns:
            try:
                return df[df[col].astype(str) == str(project_key)].copy()
            except Exception:
                pass
    return df

def ensure_project_on_executions(df: pd.DataFrame) -> pd.DataFrame:
    """Garante coluna projectKey nas execuções Zephyr."""
    if df.empty:
        return df.copy()
    out = df.copy()
    if "projectKey" in out.columns:
        out["projectKey"] = out["projectKey"].astype(str)
    if "projectKey" not in out.columns or out["projectKey"].isna().all():
        if "issueKey" in out.columns:
            out["projectKey"] = out["issueKey"].astype(str).apply(_extract_proj_from_text)
    if "projectKey" not in out.columns or out["projectKey"].replace("", pd.NA).isna().all():
        for c in ["testCase.key", "testcase.key", "testCaseKey"]:
            if c in out.columns:
                out["projectKey"] = out[c].astype(str).apply(_extract_proj_from_text)
                break
    if "projectKey" not in out.columns:
        out["projectKey"] = ""
    exec_date_col = ("actualEndDate" if "actualEndDate" in out.columns
                     else ("executedOn" if "executedOn" in out.columns else None))
    out["month"] = out[exec_date_col].apply(to_month_from_str) if exec_date_col else pd.NA
    return out

def _extract_proj_from_text(txt: str) -> str:
    if not isinstance(txt, str):
        return ""
    m = re.search(r"([A-Z][A-Z0-9_]+)-\d+", txt)
    return m.group(1) if m else ""
