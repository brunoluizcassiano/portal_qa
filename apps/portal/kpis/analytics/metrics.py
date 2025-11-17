import pandas as pd
from .transformers import (
    pct, _split_ids_to_ints, to_month_from_str,
)

# ---------- TARGETS ----------
def get_target(df_targets: pd.DataFrame, project_key_or_star: str, kpi_key: str, year: int | None):
    """
    Retorna (target, goal) seguindo a ordem:
    1) projectKey específico no ano
    2) '*' no ano
    3) projectKey sem ano
    4) '*' sem ano
    """
    if df_targets.empty:
        return (None, None)
    pk = project_key_or_star
    yr = year
    candidates = [
        (pk, yr),
        ("*", yr),
        (pk, pd.NA),
        ("*", pd.NA),
    ]
    for proj, y in candidates:
        mask = (df_targets["kpi"] == kpi_key) & (df_targets["projectKey"] == str(proj))
        mask = mask & (df_targets["year"].isna() if pd.isna(y) else (df_targets["year"] == yr))
        row = df_targets[mask].head(1)
        if not row.empty:
            tgt = float(row["target"].iloc[0]) if pd.notna(row["target"].iloc[0]) else None
            goal = row["goal"].iloc[0] if pd.notna(row["goal"].iloc[0]) else None
            return (tgt, goal)
    return (None, None)

# ---------- KPIs “atuais” ----------
def kpi_coverage_now(base_issues_sel: pd.DataFrame, linked_issue_ids: set[int]) -> float:
    if base_issues_sel.empty:
        return 0.0
    covered = base_issues_sel["id"].astype("Int64").isin(linked_issue_ids).sum()
    return round(pct(covered, len(base_issues_sel)), 2)

def kpi_test_avg_per_issue_now(base_issues_sel: pd.DataFrame, df_zc: pd.DataFrame) -> float:
    if base_issues_sel.empty or df_zc.empty:
        return 0.0
    col_tc = "links.issues.issueId" if "links.issues.issueId" in df_zc.columns else None
    if not col_tc:
        return 0.0
    tc_counts = {}
    for v in df_zc[col_tc].dropna().tolist():
        for iid in _split_ids_to_ints(v):
            tc_counts[iid] = tc_counts.get(iid, 0) + 1
    if not tc_counts:
        return 0.0
    issue_ids_proj = set(int(x) for x in base_issues_sel["id"].dropna().astype(int).tolist())
    issues_com_tc = [iid for iid in issue_ids_proj if tc_counts.get(iid, 0) > 0]
    den = len(issues_com_tc)
    if den == 0:
        return 0.0
    total_tc = sum(tc_counts[iid] for iid in issues_com_tc)
    return round(float(total_tc) / float(den), 2)

def kpi_auto_runs_now(df_ze_filtered: pd.DataFrame) -> float:
    tmp = df_ze_filtered
    if tmp.empty or "automated" not in tmp.columns:
        return 0.0
    is_auto = tmp["automated"].astype(str).str.lower().isin(["1", "true", "yes"])
    return round(pct(int(is_auto.sum()), len(tmp)), 2)

# def kpi_test_reg_now(df_zc: pd.DataFrame, issue_ids_sel: set[int] | None) -> float:
#     if df_zc.empty:
#         return 0.0
#     tcz = df_zc.copy()
#     li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
#     if issue_ids_sel and li_col:
#         mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
#         tcz = tcz[mask_link]
#     if tcz.empty:
#         return 0.0
#     tc_type_col = next((c for c in [
#         "customFields.Test Type", "customFields.TestType", "customFields.Test type", "customFields.Test_Type"
#     ] if c in tcz.columns), None)
#     if tc_type_col is None:
#         return 0.0
#     den = len(tcz)
#     num = int(tcz[tc_type_col].astype(str).str.lower().str.contains("regress").sum())
#     return round(pct(num, den), 2)
def kpi_test_reg_now(df_zc: pd.DataFrame) -> float:
    """
    % Test Regression:
    - Numerador: quantidade de test cases cujo Test Type contém 'regress'
    - Denominador: total de test cases no df_zc (já filtrado por tribo/ano fora daqui)
    """
    if df_zc.empty:
        return 0.0

    # Descobre a coluna de "Test Type"
    tc_type_col = next(
        (
            c
            for c in [
                "customFields.Test Type",
                "customFields.TestType",
                "customFields.Test type",
                "customFields.Test_Type",
                "Test Type",
            ]
            if c in df_zc.columns
        ),
        None,
    )
    if tc_type_col is None:
        return 0.0

    den = len(df_zc)
    if den == 0:
        return 0.0

    num = int(
        df_zc[tc_type_col]
        .astype(str)
        .str.lower()
        .str.contains("regress", na=False)
        .sum()
    )

    return round(pct(num, den), 2)

# def kpi_auto_reg_now(df_zc: pd.DataFrame, df_ze_filtered: pd.DataFrame, issue_ids_sel: set[int] | None) -> float:
#     if df_zc.empty:
#         return 0.0
#     tc_type_col = next((c for c in [
#         "customFields.Test Type", "customFields.TestType", "customFields.Test type", "customFields.Test_Type"
#     ] if c in df_zc.columns), None)
#     auto_col = next((c for c in [
#         "customFields.Automation Status", "customFields.AutomationStatus", "automationStatus"
#     ] if c in df_zc.columns), None)
#     if tc_type_col is None:
#         return 0.0
#     tcz = df_zc.copy()
#     if issue_ids_sel:
#         li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
#         if li_col:
#             mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
#             tcz = tcz[mask_link]
#     tcz = tcz[tcz[tc_type_col].astype(str).str.lower().str.contains("regress")].copy()
#     if tcz.empty:
#         return 0.0
#     reg_tc_ids = set(int(x) for x in pd.to_numeric(tcz.get("id"), errors="coerce").dropna().astype(int).tolist())
#     den = len(reg_tc_ids)
#     if den == 0:
#         return 0.0

#     auto_ids = set()
#     if auto_col:
#         auto_mask = tcz[auto_col].astype(str).str.strip().str.lower().eq("automated")
#         auto_ids = set(pd.to_numeric(tcz.loc[auto_mask, "id"], errors="coerce").dropna().astype(int).tolist())

#     pass_ids = set()
#     if not df_ze_filtered.empty and "testCase.id" in df_ze_filtered.columns:
#         pass_mask = pd.Series(False, index=df_ze_filtered.index)
#         if "status" in df_ze_filtered.columns:
#             pass_mask |= df_ze_filtered["status"].astype(str).str.lower().str.contains("pass")
#         if "testExecutionStatus.self" in df_ze_filtered.columns:
#             pass_mask |= df_ze_filtered["testExecutionStatus.self"].astype(str).str.lower().str.contains("pass")
#         pass_ids = set(pd.to_numeric(df_ze_filtered.loc[pass_mask, "testCase.id"], errors="coerce").dropna().astype(int).tolist())

#     automated_reg_ids = (auto_ids | pass_ids) & reg_tc_ids
#     num = len(automated_reg_ids)
#     return round(pct(num, den), 2)

def kpi_auto_reg_now(df_zc_f, df_ze_f, issue_ids_sel):
    """
    Calcula o % Automated Regression considerando APENAS testes regressivos.

    Regras:
    - Considera apenas test cases ligados às issues filtradas (issue_ids_sel).
    - Considera test cases cujo tipo de teste é regressivo
      (mesma coluna usada no gráfico "Regressive x Others (Test type)").
    - Um teste é considerado "automatizado em regressivo" se:
        * estiver marcado como automatizado no cadastro do test case
          (mesma coluna usada no gráfico de Automation in regressive), OU
        * tiver pelo menos uma execução com status "Pass".

    Retorna:
        (percentual, qtd_automatizados, qtd_manualmente, total_regressivos)
    """

    # 1) Filtra somente test cases ligados às issues selecionadas
    df_tc_sel = df_zc_f[df_zc_f["issue_key"].isin(issue_ids_sel)].copy()

    # 2) Mantém apenas os testes REGRESSIVOS
    #    👉 aqui use a MESMA coluna/critério que você usa no gráfico
    #    "Regressive x Others (Test type)" da tela Coverage and Run.
    mask_reg = df_tc_sel["test_type"].str.contains("regress", case=False, na=False)
    df_reg = df_tc_sel[mask_reg]

    # IDs dos test cases regressivos
    reg_tc_ids = set(df_reg["testcase_key"].dropna().astype(str))

    if not reg_tc_ids:
        # Não há regressivos nesse recorte
        return 0.0, 0, 0, 0

    # 3) Testes regressivos marcados como AUTOMATED no cadastro
    #    👉 use aqui a mesma coluna do gráfico "Automation in regressive"
    mask_auto = df_reg["automation_status"].str.contains("auto", case=False, na=False)
    auto_ids = set(df_reg.loc[mask_auto, "testcase_key"].dropna().astype(str))

    # 4) Testes regressivos que já tiveram pelo menos uma execução PASS
    df_exec_reg = df_ze_f[
        df_ze_f["testcase_key"].isin(reg_tc_ids)
        & df_ze_f["status"].str.lower().eq("pass")
    ]
    pass_ids = set(df_exec_reg["testcase_key"].dropna().astype(str))

    # 5) Conjunto final de "automatizados em regressivo"
    #    (marcados como auto OU com execução PASS) ∩ regressivos
    auto_reg_ids = (auto_ids | pass_ids) & reg_tc_ids

    num_auto = len(auto_reg_ids)       # ex: 268
    total_reg = len(reg_tc_ids)        # ex: 352
    pct_auto = pct(num_auto, total_reg)  # 268 / 352 * 100 = 76.14

    num_manual = total_reg - num_auto  # ex: 84

    return pct_auto, num_auto, num_manual, total_reg

# def kpi_negative_now(df_zc: pd.DataFrame, issue_ids_sel: set[int] | None) -> float:
#     if df_zc.empty:
#         return 0.0
#     tcz = df_zc.copy()
#     li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
#     if issue_ids_sel and li_col:
#         mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
#         tcz = tcz[mask_link]
#     if tcz.empty:
#         return 0.0
#     tc_class_col = next((c for c in [
#         "customFields.Test Class", "customFields.TestClass", "customFields.Test class", "customFields.Test_Class"
#     ] if c in tcz.columns), None)
#     if tc_class_col is None:
#         return 0.0
#     den = len(tcz)
#     num = int(tcz[tc_class_col].astype(str).str.lower().str.contains("negative").sum())
#     return round(pct(num, den), 2)

def kpi_negative_now(df_zc: pd.DataFrame) -> float:
    """
    % Test Negative (KPI):
    - Denominador: total de test cases em df_zc (já filtrado por tribo/ano fora daqui)
    - Numerador: test cases cujo *Test Class* contém 'negative'
      (mesma lógica do gráfico Positive x Negative (Test class))
    """
    if df_zc.empty:
        return 0.0

    # Descobre a coluna de "Test Class" (NÃO Test Type)
    tc_class_col = next(
        (
            c
            for c in [
                "customFields.Test Class",
                "customFields.TestClass",
                "customFields.Test class",
                "customFields.Test_Class",
                "Test Class",
            ]
            if c in df_zc.columns
        ),
        None,
    )
    if tc_class_col is None:
        return 0.0

    den = len(df_zc)
    if den == 0:
        return 0.0

    num = int(
        df_zc[tc_class_col]
        .astype(str)
        .str.lower()
        .str.contains("negative", na=False)
        .sum()
    )

    return round(pct(num, den), 2)

def avg_bug_days(df_bug_f: pd.DataFrame, df_subbug_f: pd.DataFrame) -> float:
    if df_bug_f.empty and df_subbug_f.empty:
        return 0.0
    d = (pd.concat([df_bug_f, df_subbug_f], ignore_index=True)
         if not (df_bug_f.empty or df_subbug_f.empty)
         else (df_bug_f if df_subbug_f.empty else df_subbug_f))

    if "created_dt" in d.columns and "resolved_dt" in d.columns:
        c = d["created_dt"]; r = d["resolved_dt"]
    else:
        created_candidates  = ["created","fields.created","dta_criacao","createdDate"]
        resolved_candidates = ["resolutiondate","fields.resolutiondate","dta_resolutiondate","dta_resolucao","resolved"]
        c = pd.to_datetime(next((d[c] for c in created_candidates  if c in d.columns), pd.Series(dtype="object")), errors="coerce", utc=True)
        r = pd.to_datetime(next((d[c] for c in resolved_candidates if c in d.columns), pd.Series(dtype="object")), errors="coerce", utc=True)

    valid = c.notna() & r.notna()
    if not valid.any():
        return 0.0
    days = (r[valid] - c[valid]).dt.total_seconds() / 86400.0
    return round(float(days.mean()), 2) if not days.empty else 0.0

# ---------- Séries mensais (retornam df [month, value]) ----------
def monthly_series_coverage(base_issues: pd.DataFrame, linked_issue_ids: set[int]) -> pd.DataFrame:
    if base_issues.empty:
        return pd.DataFrame(columns=["month", "value"])
    tmp = base_issues.copy()
    tmp["covered"] = tmp["id"].astype("Int64").isin(linked_issue_ids)
    g = tmp.groupby("month", dropna=False)["covered"].agg(["sum", "count"]).reset_index()
    g["value"] = g.apply(lambda r: pct(r["sum"], r["count"]), axis=1)
    g = g[["month", "value"]]
    return g[g["month"].notna()]

def monthly_series_test_avg(base_issues: pd.DataFrame, df_zc: pd.DataFrame) -> pd.DataFrame:
    if base_issues.empty or df_zc.empty:
        return pd.DataFrame(columns=["month", "value"])
    col_tc = "links.issues.issueId" if "links.issues.issueId" in df_zc.columns else None
    if not col_tc:
        return pd.DataFrame(columns=["month", "value"])
    tc_counts = {}
    for v in df_zc[col_tc].dropna().tolist():
        for iid in _split_ids_to_ints(v):
            tc_counts[iid] = tc_counts.get(iid, 0) + 1
    if not tc_counts:
        return pd.DataFrame(columns=["month", "value"])
    rows = []
    for m, bucket in base_issues.groupby("month"):
        if pd.isna(m):
            continue
        issue_ids_m = set(int(x) for x in bucket["id"].dropna().astype(int).tolist())
        issues_com_tc_m = [iid for iid in issue_ids_m if tc_counts.get(iid, 0) > 0]
        den = len(issues_com_tc_m)
        if den == 0:
            rows.append({"month": m, "value": 0.0})
            continue
        total_tc_m = sum(tc_counts[iid] for iid in issues_com_tc_m)
        rows.append({"month": m, "value": float(total_tc_m) / float(den)})
    return pd.DataFrame(rows)

def monthly_series_auto_runs(df_ze_filtered: pd.DataFrame) -> pd.DataFrame:
    if df_ze_filtered.empty or "automated" not in df_ze_filtered.columns:
        return pd.DataFrame(columns=["month", "value"])
    tmp = df_ze_filtered[df_ze_filtered["month"].notna()].copy()
    tmp["is_auto"] = tmp["automated"].astype(str).str.lower().isin(["1", "true", "yes"])
    g = tmp.groupby("month", dropna=False).apply(lambda d: pct(d["is_auto"].sum(), len(d))).reset_index(name="value")
    return g[g["month"].notna()]

def monthly_series_auto_reg(df_zc: pd.DataFrame, df_ze_filtered: pd.DataFrame, issue_ids_sel: set[int] | None) -> pd.DataFrame:
    if df_zc.empty:
        return pd.DataFrame(columns=["month", "value"])
    tc_type_col = next((c for c in [
        "customFields.Test Type", "customFields.TestType", "customFields.Test type", "customFields.Test_Type"
    ] if c in df_zc.columns), None)
    auto_col = next((c for c in [
        "customFields.Automation Status", "customFields.AutomationStatus", "automationStatus"
    ] if c in df_zc.columns), None)
    if tc_type_col is None:
        return pd.DataFrame(columns=["month", "value"])
    tcz = df_zc.copy()
    if issue_ids_sel:
        li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
        if li_col:
            mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
            tcz = tcz[mask_link]
    tcz = tcz[tcz[tc_type_col].astype(str).str.lower().str.contains("regress")].copy()
    if tcz.empty:
        return pd.DataFrame(columns=["month", "value"])
    if "createdOn" in tcz.columns:
        tcz["month_tc"] = tcz["createdOn"].apply(to_month_from_str)
    else:
        tcz["month_tc"] = pd.NA

    auto_ids_all = set()
    if auto_col:
        auto_ids_all = set(pd.to_numeric(
            tcz.loc[tcz[auto_col].astype(str).str.strip().str.lower().eq("automated"), "id"],
            errors="coerce"
        ).dropna().astype(int).tolist())

    pass_ids_all = set()
    if not df_ze_filtered.empty and "testCase.id" in df_ze_filtered.columns:
        pass_mask = pd.Series(False, index=df_ze_filtered.index)
        if "status" in df_ze_filtered.columns:
            pass_mask |= df_ze_filtered["status"].astype(str).str.lower().str.contains("pass")
        if "testExecutionStatus.self" in df_ze_filtered.columns:
            pass_mask |= df_ze_filtered["testExecutionStatus.self"].astype(str).str.lower().str.contains("pass")
        pass_ids_all = set(pd.to_numeric(
            df_ze_filtered.loc[pass_mask, "testCase.id"], errors="coerce"
        ).dropna().astype(int).tolist())

    rows = []
    for m, bucket in tcz.groupby("month_tc"):
        if pd.isna(m):
            continue
        ids_month = set(pd.to_numeric(bucket["id"], errors="coerce").dropna().astype(int).tolist())
        den = len(ids_month)
        if den == 0:
            rows.append({"month": m, "value": 0.0})
            continue
        num = len(ids_month & (auto_ids_all | pass_ids_all))
        rows.append({"month": m, "value": pct(num, den)})
    return pd.DataFrame(rows)

def monthly_series_test_reg(df_zc: pd.DataFrame, issue_ids_sel: set[int] | None) -> pd.DataFrame:
    if df_zc.empty:
        return pd.DataFrame(columns=["month", "value"])
    tcz = df_zc.copy()
    li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
    if issue_ids_sel and li_col:
        mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
        tcz = tcz[mask_link]
    if tcz.empty:
        return pd.DataFrame(columns=["month", "value"])
    tc_type_col = next((c for c in [
        "customFields.Test Type", "customFields.TestType", "customFields.Test type", "customFields.Test_Type"
    ] if c in tcz.columns), None)
    if "createdOn" in tcz.columns:
        tcz["month_tc"] = tcz["createdOn"].apply(to_month_from_str)
    else:
        tcz["month_tc"] = pd.NA

    def f(grp: pd.DataFrame):
        den = len(grp)
        if den == 0 or tc_type_col is None:
            return 0.0
        num = int(grp[tc_type_col].astype(str).str.lower().str.contains("regress").sum())
        return pct(num, den)

    g = tcz.groupby("month_tc", dropna=False).apply(f).reset_index(name="value")
    g = g.rename(columns={"month_tc": "month"})
    return g[g["month"].notna()]

def monthly_series_negative(df_zc: pd.DataFrame, issue_ids_sel: set[int] | None) -> pd.DataFrame:
    if df_zc.empty:
        return pd.DataFrame(columns=["month", "value"])
    tcz = df_zc.copy()
    li_col = "links.issues.issueId" if "links.issues.issueId" in tcz.columns else None
    if issue_ids_sel and li_col:
        mask_link = tcz[li_col].apply(lambda x: any(i in issue_ids_sel for i in _split_ids_to_ints(x)))
        tcz = tcz[mask_link]
    if tcz.empty:
        return pd.DataFrame(columns=["month", "value"])
    tc_class_col = next((c for c in [
        "customFields.Test Class", "customFields.TestClass", "customFields.Test class", "customFields.Test_Class"
    ] if c in tcz.columns), None)
    if "createdOn" in tcz.columns:
        tcz["month_tc"] = tcz["createdOn"].apply(to_month_from_str)
    else:
        tcz["month_tc"] = pd.NA

    def f(grp: pd.DataFrame):
        den = len(grp)
        if den == 0 or tc_class_col is None:
            return 0.0
        num = int(grp[tc_class_col].astype(str).str.lower().str.contains("negative").sum())
        return pct(num, den)

    g = tcz.groupby("month_tc", dropna=False).apply(f).reset_index(name="value")
    g = g.rename(columns={"month_tc": "month"})
    return g[g["month"].notna()]
