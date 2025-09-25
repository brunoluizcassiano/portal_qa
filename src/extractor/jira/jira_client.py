# extractor/jira/jira_client.py
from typing import Dict, Any, List, Optional, Tuple
import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
        Retorna uma lista de issues (dict) via /rest/api/3/search.
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
