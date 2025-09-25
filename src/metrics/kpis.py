import pandas as pd

def pass_rate(execs_df: pd.DataFrame) -> float:
    if execs_df.empty: return 0.0
    total = len(execs_df)
    passed = (execs_df["status"]=="Pass").sum()
    return round(100*passed/total, 2)

def automation_coverage(issues_df: pd.DataFrame, link_df: pd.DataFrame) -> float:
    # % de stories com pelo menos 1 test case
    if issues_df.empty: return 0.0
    covered = link_df["issueKey"].nunique()
    total   = issues_df["key"].nunique()
    return round(100*covered/total, 2)

def defect_escape_rate(prod_bugs: int, total_bugs: int) -> float:
    if total_bugs == 0: return 0.0
    return round(100*prod_bugs/total_bugs, 2)

def dde(pre_prod_bugs: int, total_bugs: int) -> float:
    if total_bugs == 0: return 0.0
    return round(100*pre_prod_bugs/total_bugs, 2)

def mttr(incidents_df: pd.DataFrame) -> float:
    # média em horas (assumindo created/resolved)
    if incidents_df.empty: return 0.0
    df = incidents_df.dropna(subset=["created","resolved"]).copy()
    if df.empty: return 0.0
    df["created"]  = pd.to_datetime(df["created"])
    df["resolved"] = pd.to_datetime(df["resolved"])
    return round((df["resolved"] - df["created"]).dt.total_seconds().mean()/3600, 2)
