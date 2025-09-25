import pandas as pd
from typing import List, Dict, Any

def normalize_issues(issues: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for it in issues:
        f = it.get("fields", {})
        rows.append({
            "key": it.get("key"),
            "summary": f.get("summary"),
            "status": (f.get("status") or {}).get("name"),
            "issuetype": (f.get("issuetype") or {}).get("name"),
            "priority": (f.get("priority") or {}).get("name"),
            "created": f.get("created"),
            "resolved": f.get("resolutiondate"),
            "assignee": ((f.get("assignee") or {}).get("displayName")),
            "reporter": ((f.get("reporter") or {}).get("displayName")),
        })
    return pd.DataFrame(rows)

def normalize_testcases(tcs: List[Dict[str, Any]]) -> pd.DataFrame:
    rows=[]
    for t in tcs:
        rows.append({
            "testCaseKey": t.get("key") or t.get("testCaseKey"),
            "name": t.get("name"),
            "status": (t.get("status") or {}).get("name"),
            "folder": (t.get("folder") or {}).get("name"),
            "createdOn": t.get("createdOn"),
            "owner": (t.get("owner") or {}).get("displayName")
        })
    return pd.DataFrame(rows)

def normalize_executions(execs: List[Dict[str, Any]]) -> pd.DataFrame:
    rows=[]
    for e in execs:
        r = e.get("testResult") or {}
        rows.append({
            "executionKey": e.get("key"),
            "testCaseKey": (e.get("testCase") or {}).get("key"),
            "status": (r.get("status") or {}).get("name") or e.get("status"),
            "executedOn": r.get("executedOn") or e.get("executedOn"),
            "executedBy": (r.get("executedBy") or {}).get("displayName"),
            "cycleKey": (e.get("testCycle") or {}).get("key"),
        })
    return pd.DataFrame(rows)

def join_issue_testcases(issues_df: pd.DataFrame, tcs_df: pd.DataFrame, link_df: pd.DataFrame) -> pd.DataFrame:
    # link_df: colunas issueKey, testCaseKey (monte a partir das chamadas por issue)
    return (link_df
            .merge(issues_df, left_on="issueKey", right_on="key", how="left")
            .merge(tcs_df, on="testCaseKey", how="left"))
