# extractor/jira/jira_client.py
from typing import Dict, Any, List, Optional
import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
import pandas as pd
import datetime as dt

class JiraClient:
    """
    Cliente Jira usando requests + Retry.
    - Paginação automática do /search (v3).
    - Autenticação Basic (email + API token).
    """
    def __init__(self, base_url: str, email: str, api_token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
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
        return s

    def search(self, jql: str, fields: List[str], max_results: int = 1000, batch: int = 100) -> List[Dict[str, Any]]:
        """
        Retorna lista de issues (dict) via /rest/api/3/search.
        Faz paginação até atingir 'max_results' ou o 'total' retornado.
        """
        url = f"{self.base_url}/rest/api/3/search"
        start_at = 0
        out: List[Dict[str, Any]] = []

        while True:
            params = {
                "jql": jql,
                "fields": ",".join(fields),
                "startAt": start_at,
                "maxResults": min(batch, max_results - len(out)),
            }
            resp = self._session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            issues = data.get("issues", [])
            out.extend(issues)

            total = data.get("total", 0)
            start_at += params["maxResults"]

            if start_at >= total or len(out) >= max_results:
                break

        return out

    def get_issue(self, issue_key: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()


# ================= Helpers de extração (usados pelo FastAPI) =================

def _now_tag() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")

def run_extracao_jira_sprint(
    jira_cfg: Dict[str, Any],
    app_cfg: Dict[str, Any],
    quantidade: int = 1,
    data_dir: Path | str = "config/data",
) -> Dict[str, Any]:
    """
    Executa a extração de issues do Jira e grava CSVs em data_dir.
    Retorna um resumo p/ a API responder ao scheduler.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    jc = JiraClient(
        base_url=jira_cfg["base_url"],
        email=jira_cfg["email"],
        api_token=jira_cfg["api_token"],
    )

    project = app_cfg.get("default_project", "PROJ")
    jql = f'project = "{project}" AND issuetype in ("Story","Bug") ORDER BY created DESC'
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
