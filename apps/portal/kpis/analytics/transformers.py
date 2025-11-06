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
    """Normaliza Issues JIRA para [id, key, projectKey, created, month, year]."""
    if df.empty:
        return pd.DataFrame(columns=["id", "key", "projectKey", "created", "month", "year"])
    out = pd.DataFrame()
    out["id"] = pd.to_numeric(first_non_null_col(df, ["id"]), errors="coerce").astype("Int64")
    out["key"] = first_non_null_col(df, ["key"]).astype(str)

    if "projectKey" in df.columns:
        out["projectKey"] = df["projectKey"].astype(str)
    else:
        out["projectKey"] = out["key"].apply(key_project_prefix)

    created = first_non_null_col(df, ["created", "fields.created"])
    out["created"] = pd.to_datetime(created, errors="coerce", utc=True)
    out["month"] = out["created"].dt.strftime("%Y-%m")
    out["year"]  = out["created"].dt.year.astype("Int64")

    # para filtrar mais rápido
    out["projectKey"] = out["projectKey"].astype("category")

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
    """Filtra por ano usando coluna 'year' se houver; caso contrário, tenta criar UMA vez."""
    if df.empty or sel_year == "Todos":
        return df
    year = int(sel_year)
    if "year" in df.columns:
        return df[df["year"] == year].copy()

    # fallback: cria 'year' a partir de alguma coluna temporal, mas grava na cópia
    candidates = [
        "created", "fields.created", "resolutiondate", "fields.resolutiondate",
        "dta_criacao", "dta_resolutiondate", "actualEndDate", "executedOn", "createdOn"
    ]
    df2 = df.copy()
    for c in candidates:
        if c in df2.columns:
            df2["year"] = pd.to_datetime(df2[c], errors="coerce", utc=True).dt.year.astype("Int64")
            return df2[df2["year"] == year].copy()
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
    """Garante projectKey + month + year nas execuções Zephyr."""
    if df.empty:
        return df.copy()
    out = df.copy()

    # projectKey por diversas origens
    if "projectKey" in out.columns:
        out["projectKey"] = out["projectKey"].astype(str)
    else:
        if "issueKey" in out.columns:
            out["projectKey"] = out["issueKey"].astype(str).apply(_extract_proj_from_text)
        elif any(c in out.columns for c in ["testCase.key","testcase.key","testCaseKey"]):
            c = next(c for c in ["testCase.key","testcase.key","testCaseKey"] if c in out.columns)
            out["projectKey"] = out[c].astype(str).apply(_extract_proj_from_text)
        else:
            out["projectKey"] = ""

    # data de execução
    exec_col = "actualEndDate" if "actualEndDate" in out.columns else ("executedOn" if "executedOn" in out.columns else None)
    if exec_col:
        exec_dt = pd.to_datetime(out[exec_col], errors="coerce", utc=True)
        out["month"] = exec_dt.dt.strftime("%Y-%m")
        out["year"]  = exec_dt.dt.year.astype("Int64")
    else:
        out["month"] = pd.NA
        out["year"]  = pd.NA

    out["projectKey"] = out["projectKey"].astype("category")
    return out

def normalize_bugs(df: pd.DataFrame) -> pd.DataFrame:
    """Padroniza DF de bugs/sub-bugs com created_dt/resolved_dt/year."""
    if df.empty:
        return df.copy()
    out = df.copy()
    created_candidates  = ["created", "fields.created", "dta_criacao", "createdDate"]
    resolved_candidates = ["resolutiondate", "fields.resolutiondate", "dta_resolutiondate", "dta_resolucao", "resolved"]

    created_s  = next((out[c] for c in created_candidates  if c in out.columns), pd.Series(dtype="object"))
    resolved_s = next((out[c] for c in resolved_candidates if c in out.columns), pd.Series(dtype="object"))

    out["created_dt"]  = pd.to_datetime(created_s,  errors="coerce", utc=True)
    out["resolved_dt"] = pd.to_datetime(resolved_s, errors="coerce", utc=True)
    out["year"]        = out["created_dt"].dt.year.astype("Int64")
    return out


def _extract_proj_from_text(txt: str) -> str:
    if not isinstance(txt, str):
        return ""
    m = re.search(r"([A-Z][A-Z0-9_]+)-\d+", txt)
    return m.group(1) if m else ""
