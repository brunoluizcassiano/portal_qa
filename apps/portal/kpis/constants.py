from pathlib import Path

# Pasta base dos dados (mesma do seu arquivo atual)
DATA = Path("config/database")

# --- Nomes de arquivos “alvo” (com fallback onde aplicável) ---
JIRA_FUNC = "jira_issues_func_latest.csv"
JIRA_EPIC = "jira_issues_epic_latest.csv"
JIRA_STORY = "jira_issues_story_latest.csv"
JIRA_BUG = "jira_issues_bug_latest.csv"
JIRA_SUBBUG = "jira_issues_subbug_latest.csv"
JIRA_PROJ = "jira_projetos_latest.csv"

ZEPHYR_TC = "zephyr_testcases_latest.csv"
ZEPHYR_EXEC_MAIN = "zephyr_testexecutions_latest.csv"
ZEPHYR_EXEC_FALLBACK = "zephyr_executions_latest.csv"
ZEPHYR_CYCLE_MAIN = "zephyr_testcycles_latest.csv"
ZEPHYR_CYCLE_FALLBACK = "zephyr_test_cycles_latest.csv"

KPI_TARGETS = "kpi_targets.csv"
KPI_LASTUPDATE = "lastUpdate.csv"  # criado pelo scheduler.py

# Visual (banda amarela em torno da meta)
WARN_RATIO = 0.10
