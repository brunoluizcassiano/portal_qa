# extractor/zephyr/zephyr_client.py
from typing import Dict, Any, List, Optional, Tuple, Iterable, Union, Set
import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
import pandas as pd
import datetime as dt
import time, random
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
os.environ['PYTHONHTTPSVERIFY'] = '0'
# ---------------------------
# utils básicos
# ---------------------------
def _now_tag() -> str:
   return dt.datetime.now().strftime("%Y%m%d_%H%M%S")
def _to_iso(v: Union[str, dt.date, dt.datetime, None]) -> Optional[str]:
   if v is None:
       return None
   if isinstance(v, str):
       return v
   if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
       v = dt.datetime(v.year, v.month, v.day)
   if isinstance(v, dt.datetime):
       if v.tzinfo is None:
           return v.isoformat() + "Z"
       return v.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
   return str(v)
def _safe_get(d: Any, path: str, default=None):
   cur = d
   for part in path.split("."):
       if isinstance(cur, dict) and part in cur:
           cur = cur[part]
       else:
           return default
   return cur
def _join_list(v, sep=";"):
   if isinstance(v, list):
       return sep.join([str(x) for x in v if x is not None])
   return v
def _norm_projects(app_cfg: Dict[str, Any]) -> List[str]:
   # aceita app.projects como lista ou CSV; senão usa default_project
   projs = app_cfg.get("projects")
   if isinstance(projs, str):
       projs = [p.strip() for p in projs.split(",") if p.strip()]
   if isinstance(projs, Iterable) and not isinstance(projs, (str, bytes)):
       projs = [str(p).strip() for p in projs if str(p).strip()]
   if not projs:
       dp = app_cfg.get("default_project", "PROJ")
       projs = [dp]
   return projs
class ZephyrClient:
   """
   Cliente Zephyr Scale (Cloud) usando requests + Retry.
   - Paginação via startAt/maxResults
   - Bearer token no header
   - Coleta concorrente de páginas
   """
   def __init__(self, base_url: str, api_token: str, timeout: int = 30):
       self.base_url = base_url.rstrip("/")
       self.timeout = timeout
       self._session = self._build_session(api_token)
   def _build_session(self, api_token: str) -> Session:
       s = requests.Session()
       s.trust_env = False
       s.proxies = {}
       s.verify = False
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
       s.headers.update({
           "Authorization": f"Bearer {api_token}",
           "Accept": "application/json",
           "Content-Type": "application/json; charset=utf-8",
       })
       return s
   # ---------------------------
   # paginação concorrente
   # ---------------------------
   def _first_page_and_total(self, path: str, params: Dict[str, Any], page_size: int) -> Tuple[List[Dict[str, Any]], int]:
       url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
       p = dict(params or {})
       p.update({"startAt": 0, "maxResults": max(1, page_size)})
       resp = self._session.get(url, params=p, timeout=self.timeout)
       resp.raise_for_status()
       data = resp.json() or {}
       chunk = data.get("values") or data.get("items") or data.get("results") or []
       total = data.get("total", len(chunk))
       return chunk, int(total)
   def _fetch_page(self, path: str, params: Dict[str, Any], start_at: int, page_size: int) -> List[Dict[str, Any]]:
       url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
       p = dict(params or {})
       p.update({"startAt": start_at, "maxResults": page_size})
       resp = self._session.get(url, params=p, timeout=self.timeout)
       resp.raise_for_status()
       data = resp.json() or {}
       return data.get("values") or data.get("items") or data.get("results") or []
   def _get_paged_concurrent(
       self,
       path: str,
       params: Optional[Dict[str, Any]] = None,
       page_size: int = 100,
       max_workers: int = 12,
       pause_every: int = 100,
       pause_secs: float = 0.2,
   ) -> List[Dict[str, Any]]:
       params = params or {}
       first_chunk, total = self._first_page_and_total(path, params, page_size)
       if total <= len(first_chunk):
           return list(first_chunk)
       starts = list(range(page_size, total, page_size))
       results: List[Dict[str, Any]] = list(first_chunk)
       with ThreadPoolExecutor(max_workers=max_workers) as ex:
           futs = [ex.submit(self._fetch_page, path, params, s, page_size) for s in starts]
           for i, fut in enumerate(as_completed(futs), 1):
               try:
                   results.extend(fut.result())
               except Exception:
                   # log opcional
                   pass
               if pause_every and (i % pause_every == 0):
                   time.sleep(pause_secs)
       return results
   # ---------------------------
   # Endpoints: TEST CASES
   # ---------------------------
   def testcases(
       self,
       project_key: Optional[str] = None,
       *,
       created_on_after: Optional[Union[str, dt.datetime, dt.date]] = None,
       created_on_before: Optional[Union[str, dt.datetime, dt.date]] = None,
       page_size: int = 100,
       max_workers: int = 12,
   ) -> List[Dict[str, Any]]:
       """
       GET /v2/testcases com filtros:
       - projectKey
       - createdOnAfter / createdOnBefore (se suportado pela API)
         (se não suportar, aplicamos filtro pós-coleta)
       """
       params: Dict[str, Any] = {}
       if project_key:
           params["projectKey"] = project_key
       if created_on_after:
           params["createdOnAfter"] = _to_iso(created_on_after)
       if created_on_before:
           params["createdOnBefore"] = _to_iso(created_on_before)
       raw = self._get_paged_concurrent(
           "/testcases",
           params=params,
           page_size=page_size,
           max_workers=max_workers,
       )
       # fallback: pós-filtro por createdOn
       if created_on_after or created_on_before:
           after_iso = _to_iso(created_on_after) if created_on_after else None
           before_iso = _to_iso(created_on_before) if created_on_before else None
           def _keep(tc: Dict[str, Any]) -> bool:
               c = tc.get("createdOn")
               if not isinstance(c, str):
                   return False if after_iso else True
               ok = True
               if after_iso and c < after_iso:
                   ok = False
               if before_iso and c > before_iso:
                   ok = False
               return ok
           raw = [tc for tc in raw if _keep(tc)]
       return raw
   def testcases_by_project(self, project_key: str, **kwargs) -> List[Dict[str, Any]]:
       return self.testcases(project_key=project_key, **kwargs)
   # ---------------------------
   # Endpoints: TEST EXECUTIONS
   # ---------------------------
   def executions(
       self,
       project_key: Optional[str] = None,
       *,
       actual_end_after: Optional[Union[str, dt.datetime, dt.date]] = None,
       actual_end_before: Optional[Union[str, dt.datetime, dt.date]] = None,
       test_case: Optional[str] = None,
       include_step_links: Optional[bool] = None,
       only_last_executions: Optional[bool] = None,
       jira_project_version_id: Optional[int] = None,
       page_size: int = 100,
       max_workers: int = 12,
   ) -> List[Dict[str, Any]]:
       """
       GET /v2/testexecutions com filtros:
       - projectKey
       - actualEndDateAfter / actualEndDateBefore
       - testCase
       - includeStepLinks
       - onlyLastExecutions
       - jiraProjectVersionId
       """
       params: Dict[str, Any] = {}
       if project_key:
           params["projectKey"] = project_key
       if actual_end_after:
           params["actualEndDateAfter"] = _to_iso(actual_end_after)
       if actual_end_before:
           params["actualEndDateBefore"] = _to_iso(actual_end_before)
       if test_case:
           params["testCase"] = test_case
       if include_step_links is not None:
           params["includeStepLinks"] = str(bool(include_step_links)).lower()
       if only_last_executions is not None:
           params["onlyLastExecutions"] = str(bool(only_last_executions)).lower()
       if jira_project_version_id is not None:
           params["jiraProjectVersionId"] = jira_project_version_id
       return self._get_paged_concurrent(
           "/testexecutions",
           params=params,
           page_size=page_size,
           max_workers=max_workers,
       )
   # compat: última execução de um TC
   def latest_execution_by_testcase(self, test_case_key: str) -> Optional[Dict[str, Any]]:
       url = f"{self.base_url}/testexecutions"
       params = {"testCaseKey": test_case_key, "orderBy": "executedOn DESC", "maxResults": 1}
       resp = self._session.get(url, params=params, timeout=self.timeout)
       resp.raise_for_status()
       data = resp.json() or {}
       values = data.get("values", [])
       return values[0] if values else None
   # ---------------------------
   # Endpoint: STATUSES
   # ---------------------------
   def statuses(
       self,
       *,
       page_size: int = 2000,
       max_workers: int = 8,
   ) -> List[Dict[str, Any]]:
       """
       GET /v2/statuses
       Não exige filtros; retornamos todos (paginado) e o caller filtra por projeto.
       """
       return self._get_paged_concurrent(
           "/statuses",
           params={},
           page_size=page_size,
           max_workers=max_workers,
       )
   # ---------------------------
   # Endpoint: TEST CYCLES
   # ---------------------------
   def testcycles(
       self,
       project_key: Optional[str] = None,
       *,
       page_size: int = 100,
       max_workers: int = 12,
   ) -> List[Dict[str, Any]]:
       """
       GET /v2/testcycles
       Suporta projectKey; demais filtros faremos depois se precisar.
       """
       params: Dict[str, Any] = {}
       if project_key:
           params["projectKey"] = project_key
       return self._get_paged_concurrent(
           "/testcycles",
           params=params,
           page_size=page_size,
           max_workers=max_workers,
       )
# ---- Colunas/flatten (iguais ao que você já consome) ----
TC_COLUMNS = [
   "id", "key", "name", "project.id", "createdOn",
   "objective", "precondition", "estimatedTime", "labels", "component",
   "priority.id", "priority.self",
   "status.id", "status.self",
   "folder.id", "folder.self",
   "owner.self", "owner.accountId",
   "testScript.self",
   "customFields.Automation Status",
   "customFields.Test Class",
   "customFields.Test Type",
   "customFields.Workstream",
   "links.issues.issueId", "links.issues.id", "links.issues.target", "links.issues.type",
   "links.webLinks.self", "links.webLinks.description", "links.webLinks.url",
   "links.webLinks.id", "links.webLinks.type",
   "projects.jiraProjectId", "projects.key", "projects.projetos_jira.name",
]
EXEC_COLUMNS = [
   "id", "key", "project.id",
   "testCase.self", "testCase.id",
   "environment.id",
   "jiraProjectVersion",
   "testExecutionStatus.id", "testExecutionStatus.self",
   "actualEndDate",
   "estimatedTime", "executionTime",
   "executedById", "assignedToId",
   "comment", "automated",
   "testCycle.self", "testCycle.id",
   "customFields.Execution Type",
   "links.self",
   "links.issues.self", "links.issues.issueId", "links.issues.id", "links.issues.target", "links.issues.type",
]
STATUS_COLUMNS = [
   "id",
   "project.id", "project.self",
   "name", "description", "index", "color", "archived", "default",
]
CYCLE_COLUMNS = [
   "id", "key", "name",
   "project.id",
   "jiraProjectVersion",
   "status.id",
   "folder.id",
   "description",
   "plannedStartDate", "plannedEndDate",
   "owner.accountId",
   "Environment",  # customFields.Environment
   "links.issues.self", "links.issues.issueId", "links.issues.id", "links.issues.target", "links.issues.type",
   "links.webLinks.self", "links.webLinks.description", "links.webLinks.url", "links.webLinks.id", "links.webLinks.type",
   "links.testPlans.id", "links.testPlans.testPlanId", "links.testPlans.type", "links.testPlans.target",
]
def _flatten_testcase(tc: Dict[str, Any]) -> Dict[str, Any]:
   out: Dict[str, Any] = {}
   out["id"] = tc.get("id")
   out["key"] = tc.get("key")
   out["name"] = tc.get("name")
   out["project.id"] = _safe_get(tc, "project.id")
   out["createdOn"] = tc.get("createdOn")
   out["objective"] = tc.get("objective")
   out["precondition"] = tc.get("precondition")
   out["estimatedTime"] = tc.get("estimatedTime")
   out["labels"] = _join_list(tc.get("labels"))
   out["component"] = _join_list(tc.get("component"))
   out["priority.id"] = _safe_get(tc, "priority.id")
   out["priority.self"] = _safe_get(tc, "priority.self")
   out["status.id"] = _safe_get(tc, "status.id")
   out["status.self"] = _safe_get(tc, "status.self")
   out["folder.id"] = _safe_get(tc, "folder.id")
   out["folder.self"] = _safe_get(tc, "folder.self")
   out["owner.self"] = _safe_get(tc, "owner.self")
   out["owner.accountId"] = _safe_get(tc, "owner.accountId")
   out["testScript.self"] = _safe_get(tc, "testScript.self")
   out["customFields.Automation Status"] = _safe_get(tc, "customFields.Automation Status")
   out["customFields.Test Class"] = _safe_get(tc, "customFields.Test Class")
   out["customFields.Test Type"] = _safe_get(tc, "customFields.Test Type")
   out["customFields.Workstream"] = _safe_get(tc, "customFields.Workstream")
   issues = _safe_get(tc, "links.issues") or []
   if isinstance(issues, list):
       out["links.issues.issueId"] = _join_list([_safe_get(i, "issueId") for i in issues])
       out["links.issues.id"] = _join_list([_safe_get(i, "id") for i in issues])
       out["links.issues.target"] = _join_list([_safe_get(i, "target") for i in issues])
       out["links.issues.type"] = _join_list([_safe_get(i, "type") for i in issues])
   else:
       out["links.issues.issueId"] = None
       out["links.issues.id"] = None
       out["links.issues.target"] = None
       out["links.issues.type"] = None
   wlinks = _safe_get(tc, "links.webLinks") or []
   if isinstance(wlinks, list):
       out["links.webLinks.self"] = _join_list([_safe_get(w, "self") for w in wlinks])
       out["links.webLinks.description"] = _join_list([_safe_get(w, "description") for w in wlinks])
       out["links.webLinks.url"] = _join_list([_safe_get(w, "url") for w in wlinks])
       out["links.webLinks.id"] = _join_list([_safe_get(w, "id") for w in wlinks])
       out["links.webLinks.type"] = _join_list([_safe_get(w, "type") for w in wlinks])
   else:
       out["links.webLinks.self"] = None
       out["links.webLinks.description"] = None
       out["links.webLinks.url"] = None
       out["links.webLinks.id"] = None
       out["links.webLinks.type"] = None
   # placeholders de join (compat Power BI)
   out["projects.jiraProjectId"] = None
   out["projects.key"] = None
   out["projects.projetos_jira.name"] = None
   return out
def _flatten_execution(ex: Dict[str, Any]) -> Dict[str, Any]:
   out: Dict[str, Any] = {}
   out["id"] = ex.get("id")
   out["key"] = ex.get("key")
   out["project.id"] = _safe_get(ex, "project.id")
   out["testCase.self"] = _safe_get(ex, "testCase.self")
   out["testCase.id"] = _safe_get(ex, "testCase.id")
   out["environment.id"] = _safe_get(ex, "environment.id")
   out["jiraProjectVersion"] = ex.get("jiraProjectVersion")
   out["testExecutionStatus.id"] = _safe_get(ex, "testExecutionStatus.id")
   out["testExecutionStatus.self"] = _safe_get(ex, "testExecutionStatus.self")
   out["actualEndDate"] = ex.get("actualEndDate")
   out["estimatedTime"] = ex.get("estimatedTime")
   out["executionTime"] = ex.get("executionTime")
   out["executedById"] = ex.get("executedById")
   out["assignedToId"] = ex.get("assignedToId")
   out["comment"] = ex.get("comment")
   out["automated"] = ex.get("automated")
   out["testCycle.self"] = _safe_get(ex, "testCycle.self")
   out["testCycle.id"] = _safe_get(ex, "testCycle.id")
   out["customFields.Execution Type"] = _safe_get(ex, "customFields.Execution Type")
   out["links.self"] = _safe_get(ex, "links.self")
   issues = _safe_get(ex, "links.issues") or []
   if isinstance(issues, list):
       out["links.issues.self"] = _join_list([_safe_get(i, "self") for i in issues])
       out["links.issues.issueId"] = _join_list([_safe_get(i, "issueId") for i in issues])
       out["links.issues.id"] = _join_list([_safe_get(i, "id") for i in issues])
       out["links.issues.target"] = _join_list([_safe_get(i, "target") for i in issues])
       out["links.issues.type"] = _join_list([_safe_get(i, "type") for i in issues])
   else:
       out["links.issues.self"] = None
       out["links.issues.issueId"] = None
       out["links.issues.id"] = None
       out["links.issues.target"] = None
       out["links.issues.type"] = None
   return out
def _flatten_status(st: Dict[str, Any]) -> Dict[str, Any]:
   out: Dict[str, Any] = {}
   out["id"] = st.get("id")
   out["project.id"] = _safe_get(st, "project.id")
   out["project.self"] = _safe_get(st, "project.self")
   out["name"] = st.get("name")
   out["description"] = st.get("description")
   out["index"] = st.get("index")
   out["color"] = st.get("color")
   out["archived"] = st.get("archived")
   out["default"] = st.get("default")
   return out
def _flatten_cycle(cy: Dict[str, Any]) -> Dict[str, Any]:
   out: Dict[str, Any] = {}
   out["id"] = cy.get("id")
   out["key"] = cy.get("key")
   out["name"] = cy.get("name")
   out["project.id"] = _safe_get(cy, "project.id")
   out["jiraProjectVersion"] = cy.get("jiraProjectVersion")
   out["status.id"] = _safe_get(cy, "status.id")
   out["folder.id"] = _safe_get(cy, "folder.id")
   out["description"] = cy.get("description")
   out["plannedStartDate"] = cy.get("plannedStartDate")
   out["plannedEndDate"] = cy.get("plannedEndDate")
   out["owner.accountId"] = _safe_get(cy, "owner.accountId")
   out["Environment"] = _safe_get(cy, "customFields.Environment")
   # links.issues (lista)
   issues = _safe_get(cy, "links.issues") or []
   if isinstance(issues, list):
       out["links.issues.self"] = _join_list([_safe_get(i, "self") for i in issues])
       out["links.issues.issueId"] = _join_list([_safe_get(i, "issueId") for i in issues])
       out["links.issues.id"] = _join_list([_safe_get(i, "id") for i in issues])
       out["links.issues.target"] = _join_list([_safe_get(i, "target") for i in issues])
       out["links.issues.type"] = _join_list([_safe_get(i, "type") for i in issues])
   else:
       out["links.issues.self"] = None
       out["links.issues.issueId"] = None
       out["links.issues.id"] = None
       out["links.issues.target"] = None
       out["links.issues.type"] = None
   # links.webLinks (lista)
   wlinks = _safe_get(cy, "links.webLinks") or []
   if isinstance(wlinks, list):
       out["links.webLinks.self"] = _join_list([_safe_get(w, "self") for w in wlinks])
       out["links.webLinks.description"] = _join_list([_safe_get(w, "description") for w in wlinks])
       out["links.webLinks.url"] = _join_list([_safe_get(w, "url") for w in wlinks])
       out["links.webLinks.id"] = _join_list([_safe_get(w, "id") for w in wlinks])
       out["links.webLinks.type"] = _join_list([_safe_get(w, "type") for w in wlinks])
   else:
       out["links.webLinks.self"] = None
       out["links.webLinks.description"] = None
       out["links.webLinks.url"] = None
       out["links.webLinks.id"] = None
       out["links.webLinks.type"] = None
   # links.testPlans (lista)
   tps = _safe_get(cy, "links.testPlans") or []
   if isinstance(tps, list):
       out["links.testPlans.id"] = _join_list([_safe_get(t, "id") for t in tps])
       out["links.testPlans.testPlanId"] = _join_list([_safe_get(t, "testPlanId") for t in tps])
       out["links.testPlans.type"] = _join_list([_safe_get(t, "type") for t in tps])
       out["links.testPlans.target"] = _join_list([_safe_get(t, "target") for t in tps])
   else:
       out["links.testPlans.id"] = None
       out["links.testPlans.testPlanId"] = None
       out["links.testPlans.type"] = None
       out["links.testPlans.target"] = None
   return out
def run_extracao_zephyr_diaria(
   zephyr_cfg: Dict[str, Any],
   app_cfg: Dict[str, Any],
   quantidade: int = 1,
   data_dir: Path | str = "config/data",
) -> Dict[str, Any]:
   """
   Executa a extração no Zephyr Scale para **lista de projetos**:
   • Test cases (com filtros de criação)
   • Test executions (com filtros de data de execução)
   • Test cycles
   • Statuses (filtrados pelos project.id encontrados)
   Salva:
     - config/data/zephyr_testcases_latest.csv
     - config/data/zephyr_testexecutions_latest.csv
     - config/data/zephyr_testcycles_latest.csv
     - config/data/zephyr_statuses_latest.csv
   (+ versões com timestamp)
   """
   data_dir = Path(data_dir)
   data_dir.mkdir(parents=True, exist_ok=True)
   # Concurrency tunables
   MAX_WORKERS = int(app_cfg.get("zephyr_max_workers", 12))
   PAGE_SIZE = int(app_cfg.get("zephyr_page_size", 100))
   PAUSE_EVERY = int(app_cfg.get("zephyr_pause_every", 200))
   PAUSE_SECS = float(app_cfg.get("zephyr_pause_secs", 0.2))
   zc = ZephyrClient(
       base_url=zephyr_cfg["base_url"],
       api_token=zephyr_cfg["api_token"],
   )
   projects = _norm_projects(app_cfg)
   # ---- filtros de test cases (criação) ----
   tc_created_after = app_cfg.get("zephyr_tc_created_after")  # "2025-01-01T00:00:00Z"
   tc_created_before = app_cfg.get("zephyr_tc_created_before")
   # ---- filtros de test executions (execução) ----
   exec_after = app_cfg.get("zephyr_exec_after")              # "2025-01-01T00:00:00Z"
   exec_before = app_cfg.get("zephyr_exec_before")
   exec_test_case = app_cfg.get("zephyr_exec_test_case")      # opcional
   exec_include_step_links = app_cfg.get("zephyr_exec_include_step_links", False)
   exec_only_last = app_cfg.get("zephyr_exec_only_last", False)
   exec_version_id = app_cfg.get("zephyr_exec_version_id")
   # ----------------- COLETA (por projeto) -----------------
   all_tcs: List[Dict[str, Any]] = []
   all_execs: List[Dict[str, Any]] = []
   all_cycles: List[Dict[str, Any]] = []
   for proj in projects:
       # test cases
       tcs = zc.testcases(
           project_key=proj,
           created_on_after=tc_created_after,
           created_on_before=tc_created_before,
           page_size=PAGE_SIZE,
           max_workers=MAX_WORKERS,
       )
       all_tcs.extend(tcs)
       # test executions
       execs = zc.executions(
           project_key=proj,
           actual_end_after=exec_after,
           actual_end_before=exec_before,
           test_case=exec_test_case,
           include_step_links=bool(exec_include_step_links),
           only_last_executions=bool(exec_only_last),
           jira_project_version_id=exec_version_id,
           page_size=PAGE_SIZE,
           max_workers=MAX_WORKERS,
       )
       all_execs.extend(execs)
       # test cycles
       cycles = zc.testcycles(
           project_key=proj,
           page_size=PAGE_SIZE,
           max_workers=MAX_WORKERS,
       )
       all_cycles.extend(cycles)
       # pausa leve entre projetos (opcional)
       if PAUSE_EVERY and (len(all_execs) % PAUSE_EVERY == 0):
           time.sleep(PAUSE_SECS)
   # ----------------- STATUS: coleta + filtro por project.id -----------------
   all_statuses_raw = zc.statuses(page_size=max(2000, PAGE_SIZE), max_workers=8)
   # project ids usados nas coletas (evita depender de mapeamento key→id)
   used_proj_ids: Set[Any] = set()
   for t in all_tcs:
       pid = _safe_get(t, "project.id")
       if pid is not None:
           used_proj_ids.add(pid)
   for e in all_execs:
       pid = _safe_get(e, "project.id")
       if pid is not None:
           used_proj_ids.add(pid)
   for c in all_cycles:
       pid = _safe_get(c, "project.id")
       if pid is not None:
           used_proj_ids.add(pid)
   def _status_keep(st: Dict[str, Any]) -> bool:
       pid = _safe_get(st, "project.id")
       # mantém se global (pid None) ou se pertence aos ids usados
       return (pid is None) or (pid in used_proj_ids)
   statuses_filtered = [st for st in all_statuses_raw if _status_keep(st)]
   # ----------------- FLATTEN + CSV -----------------
   df_tcs = pd.DataFrame([_flatten_testcase(t) for t in all_tcs], columns=TC_COLUMNS)
   df_exec = pd.DataFrame([_flatten_execution(e) for e in all_execs], columns=EXEC_COLUMNS)
   df_cyc  = pd.DataFrame([_flatten_cycle(c) for c in all_cycles], columns=CYCLE_COLUMNS)
   df_stat = pd.DataFrame([_flatten_status(s) for s in statuses_filtered], columns=STATUS_COLUMNS)
   tag = _now_tag()
   out_tc = data_dir / f"zephyr_testcases_{tag}.csv"
   out_ex = data_dir / f"zephyr_testexecutions_{tag}.csv"
   out_cy = data_dir / f"zephyr_testcycles_{tag}.csv"
   out_st = data_dir / f"zephyr_statuses_{tag}.csv"
   df_tcs.to_csv(out_tc, index=False)
   df_exec.to_csv(out_ex, index=False)
   df_cyc.to_csv(out_cy, index=False)
   df_stat.to_csv(out_st, index=False)
   # versões "latest"
   df_tcs.to_csv(data_dir / "zephyr_testcases_latest.csv", index=False)
   df_exec.to_csv(data_dir / "zephyr_testexecutions_latest.csv", index=False)
   df_cyc.to_csv(data_dir / "zephyr_testcycles_latest.csv", index=False)
   df_stat.to_csv(data_dir / "zephyr_statuses_latest.csv", index=False)
   return {
       "ok": True,
       "source": "zephyr",
       "projects": projects,
       "testcases": int(len(df_tcs)),
       "executions": int(len(df_exec)),
       "testcycles": int(len(df_cyc)),
       "statuses": int(len(df_stat)),
       "saved": [str(out_tc), str(out_ex), str(out_cy), str(out_st)],
       "latest": [
           "config/data/zephyr_testcases_latest.csv",
           "config/data/zephyr_testexecutions_latest.csv",
           "config/data/zephyr_testcycles_latest.csv",
           "config/data/zephyr_statuses_latest.csv",
       ],
       "concurrency": {
           "max_workers": MAX_WORKERS,
           "page_size": PAGE_SIZE,
           "pause_every": PAUSE_EVERY,
           "pause_secs": PAUSE_SECS,
       },
       "filters_used": {
           "tc_createdAfter": tc_created_after,
           "tc_createdBefore": tc_created_before,
           "exec_actualEndAfter": exec_after,
           "exec_actualEndBefore": exec_before,
           "exec_testCase": exec_test_case,
           "exec_includeStepLinks": bool(exec_include_step_links),
           "exec_onlyLastExecutions": bool(exec_only_last),
           "exec_versionId": exec_version_id,
       }
   }
