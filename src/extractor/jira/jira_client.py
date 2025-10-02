# extractor/jira/jira_client.py
from typing import Dict, Any, List, Optional
import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
import pandas as pd
import datetime as dt
import os
os.environ["PYTHONHTTPSVERIFY"] = "0"
def _now_tag() -> str:
   return dt.datetime.now().strftime("%Y%m%d_%H%M%S")
def _clean_base_url(url: str) -> str:
   url = (url or "").strip().rstrip("/")
   if url.endswith("/jira"):
       url = url[:-5]
   return url
def _load_project_keys_from_csv(data_dir: Path) -> List[str]:
   """Lê config/data/jira_projetos_latest.csv e retorna as project keys."""
   try:
       p = data_dir / "jira_projetos_latest.csv"
       if p.exists() and p.stat().st_size > 0:
           df = pd.read_csv(p)
           if "key" in df.columns:
               keys = (
                   df["key"]
                   .dropna()
                   .astype(str)
                   .str.strip()
                   .unique()
                   .tolist()
               )
               return [k for k in keys if k]
   except Exception:
       pass
   return []
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
       s.auth = self.auth
       s.headers.update({"Accept": "application/json"})
       return s
   # ------------ Projetos ------------
   def list_projects(self, max_page: int = 1000) -> List[Dict[str, Any]]:
       url = f"{self.base_url}/rest/api/3/project/search?categoryId=10018"
       start_at = 0
       page_size = 50
       out: List[Dict[str, Any]] = []
       while True:
           params = {"startAt": start_at, "maxResults": page_size}
           resp = self._session.get(url, params=params, verify=False, timeout=self.timeout)
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
       url = self._jql_search_url()
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
           resp = self._session.post(url, json=payload, verify=False, timeout=self.timeout)
           if resp.status_code >= 400:
               raise requests.HTTPError(
                   f"/search/jql {resp.status_code} {resp.reason} | {resp.text[:800]}",
                   response=resp
               )
           data = resp.json() or {}
           # Formato A: top-level
           issues = data.get("issues")
           next_token = data.get("nextPageToken")
           # Formato B: results[0]
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
   # ------------ Issue by key ------------
   def get_issue(self, issue_key: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
       url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
       params = {}
       if fields:
           params["fields"] = ",".join(fields)
       resp = self._session.get(url, params=params, verify=False, timeout=self.timeout)
       if resp.status_code >= 400:
           raise requests.HTTPError(f"/issue {resp.status_code} {resp.reason} | {resp.text[:800]}", response=resp)
       return resp.json()
# ================= Layout Power BI: FUNC =================
FUNC_COLUMNS = [
   "id", "key",
   "fields.parent.id", "fields.parent.key",
   "fields.parent.fields.summary",
   "fields.parent.fields.status.description",
   "fields.parent.fields.status.name",
   "fields.parent.fields.status.id",
   "fields.parent.fields.status.statusCategory.id",
   "fields.parent.fields.status.statusCategory.key",
   "fields.parent.fields.status.statusCategory.colorName",
   "fields.parent.fields.status.statusCategory.name",
   "fields.parent.fields.priority.name",
   "fields.parent.fields.priority.id",
   "fields.parent.fields.issuetype.id",
   "fields.parent.fields.issuetype.name",
   "fields.parent.fields.issuetype.hierarchyLevel",
   "fields.labels",
   "fields.assignee.accountId",
   "fields.assignee.emailAddress",
   "fields.assignee.displayName",
   "fields.reporter.accountId",
   "fields.reporter.emailAddress",
   "fields.reporter.displayName",
   "fields.issuetype.id",
   "fields.issuetype.name",
   "fields.issuetype.hierarchyLevel",
   "fields.project.id",
   "fields.project.key",
   "fields.project.name",
   "fields.project.projectCategory.id",
   "fields.project.projectCategory.description",
   "fields.project.projectCategory.name",
   "fields.resolutiondate",
   "fields.updated",
   "fields.summary",
   "fields.customfield_10001.id",
   "fields.customfield_10001.name",
   "fields.duedate",
   "fields.status.name",
   "fields.status.id",
   "fields.customfield_10695",
   "fields.creator.accountId",
   "fields.creator.emailAddress",
   "fields.creator.displayName",
   "fields.created",
]
FUNC_FIELD_KEYS = [
   "parent","labels","assignee","reporter","issuetype","project","priority",
   "resolutiondate","updated","summary","customfield_10001","duedate",
   "status","creator","created","customfield_10695"
]
def _flatten_func_issue(it: Dict[str, Any]) -> Dict[str, Any]:
   f = it.get("fields", {}) or {}
   parent = f.get("parent") or {}
   parent_f = parent.get("fields") or {}
   status = (f.get("status") or {})
   parent_status = (parent_f.get("status") or {})
   parent_stat_cat = (parent_status.get("statusCategory") or {})
   parent_pri = (parent_f.get("priority") or {})
   parent_type = (parent_f.get("issuetype") or {})
   assignee = (f.get("assignee") or {})
   reporter = (f.get("reporter") or {})
   issuetype = (f.get("issuetype") or {})
   proj = (f.get("project") or {})
   proj_cat = (proj.get("projectCategory") or {})
   creator = (f.get("creator") or {})
   cf_10001 = f.get("customfield_10001")
   cf_10001_id = cf_10001.get("id") if isinstance(cf_10001, dict) else None
   cf_10001_nm = cf_10001.get("name") if isinstance(cf_10001, dict) else None
   labels = f.get("labels")
   if isinstance(labels, list):
       labels = ",".join(labels)
   return {
       "id": it.get("id"),
       "key": it.get("key"),
       "fields.parent.id": parent.get("id"),
       "fields.parent.key": parent.get("key"),
       "fields.parent.fields.summary": parent_f.get("summary"),
       "fields.parent.fields.status.description": parent_status.get("description"),
       "fields.parent.fields.status.name": parent_status.get("name"),
       "fields.parent.fields.status.id": parent_status.get("id"),
       "fields.parent.fields.status.statusCategory.id": parent_stat_cat.get("id"),
       "fields.parent.fields.status.statusCategory.key": parent_stat_cat.get("key"),
       "fields.parent.fields.status.statusCategory.colorName": parent_stat_cat.get("colorName"),
       "fields.parent.fields.status.statusCategory.name": parent_stat_cat.get("name"),
       "fields.parent.fields.priority.name": parent_pri.get("name"),
       "fields.parent.fields.priority.id": parent_pri.get("id"),
       "fields.parent.fields.issuetype.id": parent_type.get("id"),
       "fields.parent.fields.issuetype.name": parent_type.get("name"),
       "fields.parent.fields.issuetype.hierarchyLevel": parent_type.get("hierarchyLevel"),
       "fields.labels": labels,
       "fields.assignee.accountId": assignee.get("accountId"),
       "fields.assignee.emailAddress": assignee.get("emailAddress"),
       "fields.assignee.displayName": assignee.get("displayName"),
       "fields.reporter.accountId": reporter.get("accountId"),
       "fields.reporter.emailAddress": reporter.get("emailAddress"),
       "fields.reporter.displayName": reporter.get("displayName"),
       "fields.issuetype.id": issuetype.get("id"),
       "fields.issuetype.name": issuetype.get("name"),
       "fields.issuetype.hierarchyLevel": issuetype.get("hierarchyLevel"),
       "fields.project.id": proj.get("id"),
       "fields.project.key": proj.get("key"),
       "fields.project.name": proj.get("name"),
       "fields.project.projectCategory.id": proj_cat.get("id"),
       "fields.project.projectCategory.description": proj_cat.get("description"),
       "fields.project.projectCategory.name": proj_cat.get("name"),
       "fields.resolutiondate": f.get("resolutiondate"),
       "fields.updated": f.get("updated"),
       "fields.summary": f.get("summary"),
       "fields.customfield_10001.id": cf_10001_id,
       "fields.customfield_10001.name": cf_10001_nm,
       "fields.duedate": f.get("duedate"),
       "fields.status.name": status.get("name"),
       "fields.status.id": status.get("id"),
       "fields.customfield_10695": f.get("customfield_10695"),
       "fields.creator.accountId": creator.get("accountId"),
       "fields.creator.emailAddress": creator.get("emailAddress"),
       "fields.creator.displayName": creator.get("displayName"),
       "fields.created": f.get("created"),
   }
# ================= Layout Power BI: EPIC =================
EPIC_COLUMNS = [
   "id", "key",
   "fields.parent.id", "fields.parent.key",
   "fields.parent.fields.summary",
   "fields.parent.fields.status.name",
   "fields.parent.fields.status.id",
   "fields.parent.fields.status.statusCategory.id",
   "fields.parent.fields.status.statusCategory.key",
   "fields.parent.fields.status.statusCategory.colorName",
   "fields.parent.fields.status.statusCategory.name",
   "fields.parent.fields.priority.name",
   "fields.parent.fields.priority.id",
   "fields.parent.fields.issuetype.id",
   "fields.parent.fields.issuetype.name",
   "fields.parent.fields.issuetype.hierarchyLevel",
   "fields.labels",
   "fields.assignee.accountId",
   "fields.assignee.emailAddress",
   "fields.assignee.displayName",
   "fields.reporter.accountId",
   "fields.reporter.emailAddress",
   "fields.reporter.displayName",
   "fields.issuetype.id",
   "fields.issuetype.name",
   "fields.issuetype.hierarchyLevel",
   "fields.project.id",
   "fields.project.key",
   "fields.project.name",
   "fields.project.projectCategory.id",
   "fields.project.projectCategory.description",
   "fields.project.projectCategory.name",
   "fields.resolutiondate",
   "fields.updated",
   "fields.summary",
   "fields.customfield_10001.id",
   "fields.customfield_10001.name",
   "fields.duedate",
   "fields.status.name",
   "fields.status.id",
   "fields.creator.accountId",
   "fields.creator.emailAddress",
   "fields.creator.displayName",
   "fields.created",
   "category_id", "category",
]
EPIC_FIELD_KEYS = [
   "labels", "issuelinks", "assignee", "reporter", "issuetype", "project",
   "resolutiondate", "updated", "summary", "customfield_10001", "duedate",
   "status", "creator", "created", "parent", "customfield_10554",
]
def _flatten_epic_issue(it: Dict[str, Any]) -> Dict[str, Any]:
   f = it.get("fields", {}) or {}
   parent = f.get("parent") or {}
   parent_f = parent.get("fields") or {}
   p_status = (parent_f.get("status") or {})
   p_cat = (p_status.get("statusCategory") or {})
   p_pri = (parent_f.get("priority") or {})
   p_type = (parent_f.get("issuetype") or {})
   assignee = (f.get("assignee") or {})
   reporter = (f.get("reporter") or {})
   issuetype = (f.get("issuetype") or {})
   proj = (f.get("project") or {})
   proj_cat = (proj.get("projectCategory") or {})
   status = (f.get("status") or {})
   creator = (f.get("creator") or {})
   cf_10001 = f.get("customfield_10001")
   cf_10001_id = cf_10001.get("id") if isinstance(cf_10001, dict) else None
   cf_10001_nm = cf_10001.get("name") if isinstance(cf_10001, dict) else None
   cf_10554 = f.get("customfield_10554")
   category_id = cf_10554.get("id") if isinstance(cf_10554, dict) else None
   category = cf_10554.get("value") if isinstance(cf_10554, dict) else None
   labels = f.get("labels")
   if isinstance(labels, list):
       labels = ";".join(map(str, labels))
   return {
       "id": it.get("id"),
       "key": it.get("key"),
       "fields.parent.id": parent.get("id"),
       "fields.parent.key": parent.get("key"),
       "fields.parent.fields.summary": parent_f.get("summary"),
       "fields.parent.fields.status.name": p_status.get("name"),
       "fields.parent.fields.status.id": p_status.get("id"),
       "fields.parent.fields.status.statusCategory.id": p_cat.get("id"),
       "fields.parent.fields.status.statusCategory.key": p_cat.get("key"),
       "fields.parent.fields.status.statusCategory.colorName": p_cat.get("colorName"),
       "fields.parent.fields.status.statusCategory.name": p_cat.get("name"),
       "fields.parent.fields.priority.name": p_pri.get("name"),
       "fields.parent.fields.priority.id": p_pri.get("id"),
       "fields.parent.fields.issuetype.id": p_type.get("id"),
       "fields.parent.fields.issuetype.name": p_type.get("name"),
       "fields.parent.fields.issuetype.hierarchyLevel": p_type.get("hierarchyLevel"),
       "fields.labels": labels,
       "fields.assignee.accountId": assignee.get("accountId"),
       "fields.assignee.emailAddress": assignee.get("emailAddress"),
       "fields.assignee.displayName": assignee.get("displayName"),
       "fields.reporter.accountId": reporter.get("accountId"),
       "fields.reporter.emailAddress": reporter.get("emailAddress"),
       "fields.reporter.displayName": reporter.get("displayName"),
       "fields.issuetype.id": issuetype.get("id"),
       "fields.issuetype.name": issuetype.get("name"),
       "fields.issuetype.hierarchyLevel": issuetype.get("hierarchyLevel"),
       "fields.project.id": proj.get("id"),
       "fields.project.key": proj.get("key"),
       "fields.project.name": proj.get("name"),
       "fields.project.projectCategory.id": proj_cat.get("id"),
       "fields.project.projectCategory.description": proj_cat.get("description"),
       "fields.project.projectCategory.name": proj_cat.get("name"),
       "fields.resolutiondate": f.get("resolutiondate"),
       "fields.updated": f.get("updated"),
       "fields.summary": f.get("summary"),
       "fields.customfield_10001.id": cf_10001_id,
       "fields.customfield_10001.name": cf_10001_nm,
       "fields.duedate": f.get("duedate"),
       "fields.status.name": status.get("name"),
       "fields.status.id": status.get("id"),
       "fields.creator.accountId": creator.get("accountId"),
       "fields.creator.emailAddress": creator.get("emailAddress"),
       "fields.creator.displayName": creator.get("displayName"),
       "fields.created": f.get("created"),
       "category_id": category_id,
       "category": category,
   }
# ================= Layout Power BI: STORY =================
STORY_COLUMNS = [
   "id", "key",
   "fields.parent.id", "fields.parent.key",
   "fields.parent.fields.summary",
   "fields.parent.fields.status.description",
   "fields.parent.fields.status.name",
   "fields.parent.fields.status.id",
   "fields.parent.fields.status.statusCategory.id",
   "fields.parent.fields.status.statusCategory.key",
   "fields.parent.fields.status.statusCategory.colorName",
   "fields.parent.fields.status.statusCategory.name",
   "fields.parent.fields.priority.name",
   "fields.parent.fields.priority.id",
   "fields.parent.fields.issuetype.id",
   "fields.parent.fields.issuetype.name",
   "fields.parent.fields.issuetype.hierarchyLevel",
   "fields.labels",
   "fields.assignee.accountId",
   "fields.assignee.emailAddress",
   "fields.assignee.displayName",
   "fields.reporter.accountId",
   "fields.reporter.emailAddress",
   "fields.reporter.displayName",
   "fields.issuetype.id",
   "fields.issuetype.name",
   "fields.issuetype.hierarchyLevel",
   "fields.project.id",
   "fields.project.key",
   "fields.project.name",
   "fields.project.projectCategory.id",
   "fields.project.projectCategory.description",
   "fields.project.projectCategory.name",
   "fields.resolutiondate",
   "fields.updated",
   "fields.summary",
   "fields.customfield_10001.id",
   "fields.customfield_10001.name",
   "fields.customfield_10695.id",
   "fields.customfield_10695.value",
   "fields.duedate",
   "fields.status.name",
   "fields.status.id",
   "fields.creator.accountId",
   "fields.creator.emailAddress",
   "fields.creator.displayName",
   "fields.created",
]
STORY_FIELD_KEYS = [
   "parent", "labels", "issuelinks", "assignee", "reporter", "issuetype", "project",
   "resolutiondate", "updated", "summary", "customfield_10001", "customfield_10695",
   "duedate", "status", "creator", "created",
]
def _flatten_story_issue(it: Dict[str, Any]) -> Dict[str, Any]:
   f = it.get("fields", {}) or {}
   parent = f.get("parent") or {}
   parent_f = parent.get("fields") or {}
   p_status = (parent_f.get("status") or {})
   p_cat = (p_status.get("statusCategory") or {})
   p_pri = (parent_f.get("priority") or {})
   p_type = (parent_f.get("issuetype") or {})
   assignee = (f.get("assignee") or {})
   reporter = (f.get("reporter") or {})
   issuetype = (f.get("issuetype") or {})
   proj = (f.get("project") or {})
   proj_cat = (proj.get("projectCategory") or {})
   status = (f.get("status") or {})
   creator = (f.get("creator") or {})
   cf_10001 = f.get("customfield_10001")
   cf_10001_id = cf_10001.get("id") if isinstance(cf_10001, dict) else None
   cf_10001_nm = cf_10001.get("name") if isinstance(cf_10001, dict) else None
   cf_10695 = f.get("customfield_10695")
   cf_10695_id = cf_10695.get("id") if isinstance(cf_10695, dict) else None
   cf_10695_val = cf_10695.get("value") if isinstance(cf_10695, dict) else None
   labels = f.get("labels")
   if isinstance(labels, list):
       labels = ";".join(map(str, labels))
   return {
       "id": it.get("id"),
       "key": it.get("key"),
       "fields.parent.id": parent.get("id"),
       "fields.parent.key": parent.get("key"),
       "fields.parent.fields.summary": parent_f.get("summary"),
       "fields.parent.fields.status.description": p_status.get("description"),
       "fields.parent.fields.status.name": p_status.get("name"),
       "fields.parent.fields.status.id": p_status.get("id"),
       "fields.parent.fields.status.statusCategory.id": p_cat.get("id"),
       "fields.parent.fields.status.statusCategory.key": p_cat.get("key"),
       "fields.parent.fields.status.statusCategory.colorName": p_cat.get("colorName"),
       "fields.parent.fields.status.statusCategory.name": p_cat.get("name"),
       "fields.parent.fields.priority.name": p_pri.get("name"),
       "fields.parent.fields.priority.id": p_pri.get("id"),
       "fields.parent.fields.issuetype.id": p_type.get("id"),
       "fields.parent.fields.issuetype.name": p_type.get("name"),
       "fields.parent.fields.issuetype.hierarchyLevel": p_type.get("hierarchyLevel"),
       "fields.labels": labels,
       "fields.assignee.accountId": assignee.get("accountId"),
       "fields.assignee.emailAddress": assignee.get("emailAddress"),
       "fields.assignee.displayName": assignee.get("displayName"),
       "fields.reporter.accountId": reporter.get("accountId"),
       "fields.reporter.emailAddress": reporter.get("emailAddress"),
       "fields.reporter.displayName": reporter.get("displayName"),
       "fields.issuetype.id": issuetype.get("id"),
       "fields.issuetype.name": issuetype.get("name"),
       "fields.issuetype.hierarchyLevel": issuetype.get("hierarchyLevel"),
       "fields.project.id": proj.get("id"),
       "fields.project.key": proj.get("key"),
       "fields.project.name": proj.get("name"),
       "fields.project.projectCategory.id": proj_cat.get("id"),
       "fields.project.projectCategory.description": proj_cat.get("description"),
       "fields.project.projectCategory.name": proj_cat.get("name"),
       "fields.resolutiondate": f.get("resolutiondate"),
       "fields.updated": f.get("updated"),
       "fields.summary": f.get("summary"),
       "fields.customfield_10001.id": cf_10001_id,
       "fields.customfield_10001.name": cf_10001_nm,
       "fields.customfield_10695.id": cf_10695_id,
       "fields.customfield_10695.value": cf_10695_val,
       "fields.duedate": f.get("duedate"),
       "fields.status.name": status.get("name"),
       "fields.status.id": status.get("id"),
       "fields.creator.accountId": creator.get("accountId"),
       "fields.creator.emailAddress": creator.get("emailAddress"),
       "fields.creator.displayName": creator.get("displayName"),
       "fields.created": f.get("created"),
   }
# ================= Layout Power BI: BUG & SUB-BUG =================
# Colunas finais RENOMEADAS como no seu M (linha "Colunas Renomeadas")
BUG_COLUMNS = [
   "id_bug", "cod_bug",
   "id_etapa", "nom_etapa",
   "id_projeto", "cod_projeto", "nom_projeto",
   "nom_status", "id_status",
   "nom_bug",
   "nom_epico",
   "nom_ambiente", "id_ambiente",
   "id_relacionamento_in", "id_relacionamento_out",
   "cod_relacionamento_in", "cod_relacionamento_out",
   "nom_etapa_relacionamento_in", "nom_etapa_relacionamento_out",
   "id_etapa_relacionamento_in", "id_etapa_relacionamento_out",
   "dta_criacao",
   "id_causa_raiz", "nom_causa_raiz",
   "id_sla", "nom_sla",
   "id_usuario_criador", "nom_usuario_criador",
   "nom_assignee", "id_assignee",
   "id_classificacao", "nom_classificacao",
   "dta_correcao_dev", "dta_fechamento", "dta_updated", "dta_resolutiondate",
   "nom_label", "dta_prevista",
   "nom_flag",
   "id_parent",
   "id_team", "team",
]
BUG_FIELD_KEYS = [
   # do seu M:
   "parent",
   "customfield_10190", "customfield_10192",
   "customfield_10180", "customfield_10182",
   "labels", "issuelinks", "assignee",
   "customfield_10166", "customfield_10038",
   "issuetype", "project", "customfield_10157",
   "resolutiondate", "updated", "summary",
   "customfield_10001", "duedate", "status",
   "creator", "customfield_10433", "created",
]
def _join_list(values, sep=";"):
   if isinstance(values, list):
       return sep.join([str(v) for v in values if v is not None])
   return values
def _first(obj_list: list) -> Optional[dict]:
   return obj_list[0] if isinstance(obj_list, list) and obj_list else None
def _flatten_bug_issue(it: Dict[str, Any]) -> Dict[str, Any]:
   f = it.get("fields", {}) or {}
   # campos base
   status = (f.get("status") or {})
   issuetype = (f.get("issuetype") or {})
   proj = (f.get("project") or {})
   # parent
   parent = f.get("parent") or {}
   parent_f = parent.get("fields") or {}
   # customfields
   cf_10157 = f.get("customfield_10157") or {}  # ambiente {id, value}
   cf_10182 = f.get("customfield_10182") or {}  # causa raiz {id, value}
   cf_10166 = f.get("customfield_10166") or {}  # SLA {id, value}
   cf_10180 = f.get("customfield_10180") or {}  # classificacao {id, value}
   cf_10192 = f.get("customfield_10192")        # data correcao dev
   cf_10190 = f.get("customfield_10190")        # data fechamento
   cf_10038 = f.get("customfield_10038") or []  # lista de flags [{value},...]
   cf_10001 = f.get("customfield_10001") or {}  # team {id,name}
   # cf_10433 está comentado no M; se precisar, adicionar aqui.
   # pessoas
   creator = f.get("creator") or {}
   assignee = f.get("assignee") or {}
   # issuelinks (agregamos em strings para manter 1 linha por bug)
   links = f.get("issuelinks") or []
   inward_ids, inward_keys, inward_types = [], [], []
   outward_ids, outward_keys, outward_types = [], [], []
   if isinstance(links, list):
       for lk in links:
           inward = lk.get("inwardIssue") or {}
           outward = lk.get("outwardIssue") or {}
           if inward:
               inward_ids.append(inward.get("id"))
               inward_keys.append(inward.get("key"))
               itype = ((inward.get("fields") or {}).get("issuetype") or {})
               inward_types.append(itype.get("name"))
           if outward:
               outward_ids.append(outward.get("id"))
               outward_keys.append(outward.get("key"))
               itype = ((outward.get("fields") or {}).get("issuetype") or {})
               outward_types.append(itype.get("name"))
   # flags (lista de dicts -> valores)
   flags_vals = []
   if isinstance(cf_10038, list):
       for el in cf_10038:
           if isinstance(el, dict) and "value" in el:
               flags_vals.append(str(el["value"]))
   # renomeações exatamente como no Power BI
   return {
       "id_bug": it.get("id"),
       "cod_bug": it.get("key"),
       "id_etapa": issuetype.get("id"),
       "nom_etapa": issuetype.get("name"),
       "id_projeto": proj.get("id"),
       "cod_projeto": proj.get("key"),
       "nom_projeto": proj.get("name"),
       "nom_status": status.get("name"),
       "id_status": status.get("id"),
       "nom_bug": f.get("summary"),
       "nom_epico": parent_f.get("summary"),
       "nom_ambiente": cf_10157.get("value"),
       "id_ambiente": cf_10157.get("id"),
       "id_relacionamento_in": _join_list(inward_ids, ";"),
       "id_relacionamento_out": _join_list(outward_ids, ";"),
       "cod_relacionamento_in": _join_list(inward_keys, ";"),
       "cod_relacionamento_out": _join_list(outward_keys, ";"),
       # Nomes das etapas dos relacionados (in/out)
       "nom_etapa_relacionamento_in": _join_list(inward_types, ";"),
       "nom_etapa_relacionamento_out": _join_list(outward_types, ";"),
       # O seu M renomeava invertendo id_in/out; seguimos literalmente:
       "id_etapa_relacionamento_in": None,   # não temos id do issuetype no link sem outra chamada
       "id_etapa_relacionamento_out": None,  # manter None (Power BI também só tinha name/id via expand)
       "dta_criacao": f.get("created"),
       "id_causa_raiz": cf_10182.get("id"),
       "nom_causa_raiz": cf_10182.get("value"),
       "id_sla": cf_10166.get("id"),
       "nom_sla": cf_10166.get("value"),
       "id_usuario_criador": creator.get("accountId"),
       "nom_usuario_criador": creator.get("displayName"),
       "nom_assignee": assignee.get("displayName"),
       "id_assignee": assignee.get("accountId"),
       "id_classificacao": cf_10180.get("id"),
       "nom_classificacao": cf_10180.get("value"),
       "dta_correcao_dev": cf_10192,
       "dta_fechamento": cf_10190,
       "dta_updated": f.get("updated"),
       "dta_resolutiondate": f.get("resolutiondate"),
       "nom_label": _join_list(f.get("labels") or [], ","),
       "dta_prevista": f.get("duedate"),
       "nom_flag": _join_list(flags_vals, ","),
       "id_parent": parent.get("id"),
       "id_team": (cf_10001.get("id") if isinstance(cf_10001, dict) else None),
       "team": (cf_10001.get("name") if isinstance(cf_10001, dict) else None),
   }
# ================= Helpers de extração =================
def run_extracao_jira_sprint(
   jira_cfg: Dict[str, Any],
   app_cfg: Dict[str, Any],
   quantidade: int = 1,
   data_dir: Path | str = "config/data",
) -> Dict[str, Any]:
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
   tipo_lista = ["Functionality", "Func", "Fun", "Funcionalidade", "Epic", "Story", "Bug", "Sub-Bug"]
   tipos_str = ",".join([f'"{t}"' for t in tipo_lista])
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
   1) Atualiza projetos → jira_projetos_latest.csv
   2) Extrai bases: func / epic / story / bug / subbug
      - func, epic e story com layout achatado (Power BI)
      - bug/subbug também achatado e RENOMEADO como no Power BI
      - percorre TODOS os projetos do CSV; se não houver, usa default_project
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
   # 1) Projetos
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
   # projetos a varrer
   project_keys = _load_project_keys_from_csv(data_dir)
   if not project_keys:
       project_keys = [app_cfg.get("default_project", "PROJ")]
   tipos = {
       "func":  ["Functionality", "Func", "Fun", "Funcionalidade"],
       "epic":  ["Epic"],
       "story": ["Story"],
       "bug":   ["Bug"],
       "subbug":["Sub-Bug"],
   }
   saved = {
       "projetos": {
           "latest": "config/data/jira_projetos_latest.csv",
           "timestamped": str(proj_ts),
           "count": int(len(df_proj)),
       }
   }
   # fields e flatteners por label
   for label, tipolist in tipos.items():
       if label == "func":
           fields = FUNC_FIELD_KEYS
           flattener = _flatten_func_issue
           out_cols = FUNC_COLUMNS
       elif label == "epic":
           fields = EPIC_FIELD_KEYS
           flattener = _flatten_epic_issue
           out_cols = EPIC_COLUMNS
       elif label == "story":
           fields = STORY_FIELD_KEYS
           flattener = _flatten_story_issue
           out_cols = STORY_COLUMNS
       elif label in ("bug", "subbug"):
           fields = BUG_FIELD_KEYS
           flattener = _flatten_bug_issue
           out_cols = BUG_COLUMNS
       else:
           # fallback nunca deve acontecer
           fields = ["key","summary","status","issuetype","priority","created","resolutiondate","assignee","reporter"]
           flattener = None
           out_cols = None
       # coleta issues de todos os projetos
       issues_all: List[Dict[str, Any]] = []
       for proj_key in project_keys:
           tipos_str = ",".join([f'"{t}"' for t in tipolist])
           jql = f'project = "{proj_key}" AND issuetype in ({tipos_str}) ORDER BY created DESC'
           part = jc.search(jql, fields=fields, max_results=max(200, quantidade * 400))
           issues_all.extend(part)
       # flattener / DF
       if flattener is not None:
           rows = [flattener(it) for it in issues_all]
           df = pd.DataFrame(rows, columns=out_cols)
       else:
           rows = []
           for it in issues_all:
               ff = it.get("fields", {}) or {}
               rows.append({
                   "key": it.get("key"),
                   "summary": ff.get("summary"),
                   "status": (ff.get("status") or {}).get("name"),
                   "type": (ff.get("issuetype") or {}).get("name"),
                   "priority": (ff.get("priority") or {}).get("name"),
                   "created": ff.get("created"),
                   "resolutiondate": ff.get("resolutiondate"),
                   "assignee": ((ff.get("assignee") or {}).get("displayName")),
                   "reporter": ((ff.get("reporter") or {}).get("displayName")),
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
       "projects_used": project_keys,
       "saved": saved,
   }
