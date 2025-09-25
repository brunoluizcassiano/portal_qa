# extractor/zephyr/zephyr_client.py
from typing import Dict, Any, List, Optional
import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
import pandas as pd
import datetime as dt

class ZephyrClient:
    """
    Cliente Zephyr Scale (Cloud) usando requests + Retry.
    - Paginação via startAt/maxResults
    - Bearer token no header
    """
    def __init__(self, base_url: str, api_token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = self._build_session(api_token)

    def _build_session(self, api_token: str) -> Session:
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
        s.headers.update({"Authorization": f"Bearer {api_token}"})
        return s

    def _get_paged(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        start_at, page_size = 0, 100
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

        while True:
            p = dict(params or {})
            p.update({"startAt": start_at, "maxResults": page_size})
            resp = self._session.get(url, params=p, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            # Zephyr varia entre "values", "items" ou "results"
            chunk = data.get("values") or data.get("items") or data.get("results") or []
            items.extend(chunk)

            if len(chunk) < page_size:
                break
            start_at += page_size

        return items

    # ===== Endpoints utilitários =====
    def testcases_by_issue(self, issue_key: str) -> List[Dict[str, Any]]:
        # GET /testcases?issueKey=PROJ-123
        return self._get_paged("/testcases", params={"issueKey": issue_key})

    def testcases_by_project(self, project_key: str) -> List[Dict[str, Any]]:
        # GET /testcases?projectKey=PROJ
        return self._get_paged("/testcases", params={"projectKey": project_key})

    def executions_by_cycle(self, cycle_key: str) -> List[Dict[str, Any]]:
        # GET /testexecutions?testCycleKey=CYCLE-1
        return self._get_paged("/testexecutions", params={"testCycleKey": cycle_key})

    def latest_execution_by_testcase(self, test_case_key: str) -> Optional[Dict[str, Any]]:
        # GET /testexecutions?testCaseKey=TC-1&orderBy=executedOn DESC&maxResults=1
        url = f"{self.base_url}/testexecutions"
        params = {"testCaseKey": test_case_key, "orderBy": "executedOn DESC", "maxResults": 1}
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        values = data.get("values", [])
        return values[0] if values else None


# ================= Helpers de extração (usados pelo FastAPI) =================

def _now_tag() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")

def run_extracao_zephyr_diaria(
    zephyr_cfg: Dict[str, Any],
    app_cfg: Dict[str, Any],
    quantidade: int = 1,
    data_dir: Path | str = "config/data",
) -> Dict[str, Any]:
    """
    Executa a extração no Zephyr Scale (test cases + últimas execuções) e grava CSVs.
    Retorna um resumo p/ a API responder ao scheduler.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    zc = ZephyrClient(
        base_url=zephyr_cfg["base_url"],
        api_token=zephyr_cfg["api_token"],
    )

    project = app_cfg.get("default_project", "PROJ")
    tcs = zc.testcases_by_project(project_key=project)
    tc_rows = [{"testCaseKey": t.get("key"), "name": t.get("name")} for t in tcs]

    # pega últimas execuções dos primeiros N*50 testes (heurística simples)
    exec_rows = []
    limit = max(1, quantidade * 50)
    for row in tc_rows[:limit]:
        last = zc.latest_execution_by_testcase(row["testCaseKey"])
        if last:
            exec_rows.append(last)

    df_tcs = pd.DataFrame(tc_rows)
    df_exec = pd.DataFrame(exec_rows)

    tag = _now_tag()
    out_tc = data_dir / f"zephyr_testcases_{tag}.csv"
    out_ex = data_dir / f"zephyr_executions_{tag}.csv"
    df_tcs.to_csv(out_tc, index=False)
    df_exec.to_csv(out_ex, index=False)

    # versões "latest" para o dashboard
    df_tcs.to_csv(data_dir / "zephyr_testcases_latest.csv", index=False)
    df_exec.to_csv(data_dir / "zephyr_executions_latest.csv", index=False)

    return {
        "ok": True,
        "source": "zephyr",
        "testcases": len(df_tcs),
        "executions": len(df_exec),
        "saved": [str(out_tc), str(out_ex)],
        "latest": [
            "config/data/zephyr_testcases_latest.csv",
            "config/data/zephyr_executions_latest.csv",
        ],
    }
