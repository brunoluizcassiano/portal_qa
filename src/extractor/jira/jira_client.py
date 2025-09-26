# extractor/jira/jira_client.py
from typing import Dict, Any, List, Optional
import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
import pandas as pd
import datetime as dt

def _now_tag() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")

def _clean_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url.endswith("/jira"):
        url = url[:-5]
    return url

class JiraClient:
    """
    Cliente Jira usando requests + Retry.
    - /project/search com paginação
    - /search/jql (endpoint novo) com paginação via nextPageToken
    - Autenticação Basic (email + API token)
    """
    def __init__(self, base_url: str, email: str, api_token: str, timeout: int = 30):
        self.base_url = _clean_base_url(base_url)
        self.auth = (email, api_token)
        self.timeout = timeout
        self._session = self._build_session()

    def _build_session(self) -> Session:
        s = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        s.auth = self.auth
        s.headers.update({"Accept": "application/json"})
        return s

    # ------------ Projetos ------------
    def list_projects(self, max_page: int = 1000) -> List[Dict[str, Any]]:
        """GET /rest/api/3/project/search com paginação por startAt/maxResults."""
        url = f"{self.base_url}/rest/api/3/project/search"
        start_at = 0
        page_size = 50
        out: List[Dict[str, Any]] = []

        while True:
            params = {"startAt": start_at, "maxResults": page_size}
            resp = self._session.get(url, params=params, timeout=self.timeout)
            if resp.status_code >= 400:
                raise requests.HTTPError(
                    f"/project/search {resp.status_code} {resp.reason} | {resp.text[:800]}",
                    response=resp
                )
            data = resp.json() or {}
            values = data.get("values") or data.get("projects") or []
            out.extend(values)

            is_last = data.get("isLast", None)
            if is_last is True:
                break

            if len(values) < page_size or len(out) >= max_page:
                break
            start_at += page_size

        return out

    # ------------ Search (novo endpoint /search/jql) ------------
    def _jql_search_url(self) -> str:
        return f"{self.base_url}/rest/api/3/search/jql"

    def search(self, jql: str, fields: List[str], max_results: int = 1000, batch: int = 100) -> List[Dict[str, Any]]:
        """
        Usa o endpoint novo: POST /rest/api/3/search/jql (payload top-level).
        Faz paginação por nextPageToken. Aceita tanto resposta top-level
        quanto resposta aninhada em 'results[0]'.
        """
        url = f"{self.base_url}/rest/api/3/search/jql"
        out: List[Dict[str, Any]] = []
        next_token = None

        while True:
            page_size = min(batch, max_results - len(out))
            if page_size <= 0:
                break

            payload: Dict[str, Any] = {
                "jql": jql,
                "maxResults": page_size,
            }
            if fields:
                payload["fields"] = fields
            if next_token:
                payload["nextPageToken"] = next_token

            resp = self._session.post(url, json=payload, timeout=self.timeout)
            if resp.status_code >= 400:
                # log explicativo para facilitar debug
                raise requests.HTTPError(
                    f"/search/jql {resp.status_code} {resp.reason} | {resp.text[:800]}",
                    response=resp
                )

            data = resp.json() or {}

            # Formato A: top-level
            issues = data.get("issues")
            next_token = data.get("nextPageToken")

            # Formato B: aninhado em results[0]
            if issues is None:
                results = data.get("results") or []
                if results:
                    issues = results[0].get("issues") or []
                    next_token = results[0].get("nextPageToken")

            issues = issues or []
            out.extend(issues)

            if not next_token or len(out) >= max_results:
                break

        return out


    # ------------ Issue by key (ainda útil) ------------
    def get_issue(self, issue_key: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        resp = self._session.get(url, params=params, timeout=self.timeout)
        if resp.status_code >= 400:
            raise requests.HTTPError(f"/issue {resp.status_code} {resp.reason} | {resp.text[:800]}", response=resp)
        return resp.json()


# ================= Helpers de extração (usados pelo FastAPI) =================

def run_extracao_jira_sprint(
    jira_cfg: Dict[str, Any],
    app_cfg: Dict[str, Any],
    quantidade: int = 1,
    data_dir: Path | str = "config/data",
) -> Dict[str, Any]:
    """
    EXTRATOR LEGADO (mantido p/ compatibilidade):
    Busca issues do projeto padrão (mix de tipos) e salva um CSV único.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    for k in ("base_url", "email", "api_token"):
        if not jira_cfg.get(k):
            raise ValueError(f"[jira] faltando chave '{k}' no secrets")

    jc = JiraClient(
        base_url=jira_cfg["base_url"],
        email=jira_cfg["email"],
        api_token=jira_cfg["api_token"],
    )

    project = app_cfg.get("default_project", "PROJ")
    # Mantive os tipos que você já usava, incluindo customizados "Func"/"Sub-Bug"
    tipo_lista = ['Func','Fun','Epic','Story','Bug','Sub-Bug']
    tipos_str = ",".join([f'"{t}"' for t in tipo_lista])   # ex.: "Func","Bug","Story"
    jql = f'project = "{project}" AND issuetype in ({tipos_str}) ORDER BY created DESC'
    fields = ["key","summary","status","issuetype","priority","created","resolutiondate","assignee","reporter"]

    issues = jc.search(jql, fields=fields, max_results=max(100, quantidade * 200))
    rows = []
    for it in issues:
        f = it.get("fields", {}) or {}
        rows.append({
            "key": it.get("key"),
            "summary": f.get("summary"),
            "status": (f.get("status") or {}).get("name"),
            "type": (f.get("issuetype") or {}).get("name"),
            "priority": (f.get("priority") or {}).get("name"),
            "created": f.get("created"),
            "resolutiondate": f.get("resolutiondate"),
            "assignee": ((f.get("assignee") or {}).get("displayName")),
            "reporter": ((f.get("reporter") or {}).get("displayName")),
        })
    df = pd.DataFrame(rows)

    tag = _now_tag()
    out_csv = data_dir / f"jira_issues_{tag}.csv"
    df.to_csv(out_csv, index=False)
    df.to_csv(data_dir / "jira_issues_latest.csv", index=False)

    return {
        "ok": True,
        "source": "jira",
        "count": len(df),
        "saved": str(out_csv),
        "latest": "config/data/jira_issues_latest.csv",
    }


def run_extracao_jira_bases(
    jira_cfg: Dict[str, Any],
    app_cfg: Dict[str, Any],
    quantidade: int = 1,
    data_dir: Path | str = "config/data",
) -> Dict[str, Any]:
    """
    NOVO EXTRATOR:
    1) Extrai Projetos → jira_projetos_latest.csv
    2) Extrai issues do projeto padrão e grava bases separadas por tipo:
       Func/Fun, Epic, Story, Bug, Sub-Bug → 5 CSVs (cada um com 'latest' + timestamp)
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    for k in ("base_url", "email", "api_token"):
        if not jira_cfg.get(k):
            raise ValueError(f"[jira] faltando chave '{k}' no secrets")

    jc = JiraClient(
        base_url=jira_cfg["base_url"],
        email=jira_cfg["email"],
        api_token=jira_cfg["api_token"],
    )

    tag = _now_tag()

    # --------- 1) Projetos ----------
    projetos = jc.list_projects()
    proj_rows = []
    for p in projetos:
        lead = (p.get("lead") or {})
        proj_rows.append({
            "id": p.get("id"),
            "key": p.get("key"),
            "name": p.get("name"),
            "projectTypeKey": p.get("projectTypeKey"),
            "lead": lead.get("displayName"),
        })
    df_proj = pd.DataFrame(proj_rows)
    proj_ts = data_dir / f"jira_projetos_{tag}.csv"
    df_proj.to_csv(proj_ts, index=False)
    df_proj.to_csv(data_dir / "jira_projetos_latest.csv", index=False)

    # --------- 2) Issues por tipo ----------
    project = app_cfg.get("default_project", "PROJ")
    tipos = {
        "func": ["Func", "Fun"],  # aceita as duas grafias
        "epic": ["Epic"],
        "story": ["Story"],
        "bug": ["Bug"],
        "subbug": ["Sub-Bug"],
    }
    fields = ["key","summary","status","issuetype","priority","created","resolutiondate","assignee","reporter"]

    saved = {
        "projetos": {
            "latest": "config/data/jira_projetos_latest.csv",
            "timestamped": str(proj_ts),
            "count": int(len(df_proj)),
        }
    }

    for label, tipolist in tipos.items():
        tipos_str = ",".join([f'"{t}"' for t in tipolist])   # ex.: "Func","Bug","Story"
        jql = f'project = "{project}" AND issuetype in ({tipos_str}) ORDER BY created DESC'
        issues = jc.search(jql, fields=fields, max_results=max(100, quantidade * 300))
        rows = []
        for it in issues:
            f = it.get("fields", {}) or {}
            rows.append({
                "key": it.get("key"),
                "summary": f.get("summary"),
                "status": (f.get("status") or {}).get("name"),
                "type": (f.get("issuetype") or {}).get("name"),
                "priority": (f.get("priority") or {}).get("name"),
                "created": f.get("created"),
                "resolutiondate": f.get("resolutiondate"),
                "assignee": ((f.get("assignee") or {}).get("displayName")),
                "reporter": ((f.get("reporter") or {}).get("displayName")),
            })
        df = pd.DataFrame(rows)
        ts_path = data_dir / f"jira_issues_{label}_{tag}.csv"
        latest_path = data_dir / f"jira_issues_{label}_latest.csv"
        df.to_csv(ts_path, index=False)
        df.to_csv(latest_path, index=False)

        saved[label] = {
            "latest": str(latest_path),
            "timestamped": str(ts_path),
            "count": int(len(df)),
        }

    return {
        "ok": True,
        "source": "jira",
        "saved": saved,
    }
