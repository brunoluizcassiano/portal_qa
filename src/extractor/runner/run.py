import os
import sys
import json
import requests

API_URL         = os.getenv("API_URL", "http://massai-api:8000").rstrip("/")
ENDPOINT_JIRA   = os.getenv("ENDPOINT_JIRA", "/run_jira/")
ENDPOINT_ZEPHYR = os.getenv("ENDPOINT_ZEPHYR", "/run_zephyr/")

FLUXO_JIRA      = os.getenv("FLUXO_JIRA", "extracao_jira_sprint")
QTD_JIRA        = int(os.getenv("QUANTIDADE_JIRA", "1"))

FLUXO_ZEPHYR    = os.getenv("FLUXO_ZEPHYR", "extracao_zephyr_diaria")
QTD_ZEPHYR      = int(os.getenv("QUANTIDADE_ZEPHYR", "1"))

TIMEOUT         = int(os.getenv("RUN_TIMEOUT", "60"))

def call_api(endpoint: str, fluxo: str, quantidade: int):
    url = f"{API_URL}{endpoint if endpoint.startswith('/') else '/'+endpoint}"
    payload = {"fluxo_name": fluxo, "quantidade": quantidade}
    print(f"→ POST {url}  payload={payload}")
    r = requests.post(url, json=payload, timeout=TIMEOUT)
    try:
        r.raise_for_status()
    except Exception as e:
        print(f"❌ erro HTTP: {e}\n{r.text}")
        sys.exit(1)
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(r.text)

def main():
    target = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()

    if target in ("jira",):
        call_api(ENDPOINT_JIRA, FLUXO_JIRA, QTD_JIRA)
    elif target in ("zephyr",):
        call_api(ENDPOINT_ZEPHYR, FLUXO_ZEPHYR, QTD_ZEPHYR)
    elif target in ("all", "", "both"):
        call_api(ENDPOINT_JIRA,   FLUXO_JIRA,   QTD_JIRA)
        call_api(ENDPOINT_ZEPHYR, FLUXO_ZEPHYR, QTD_ZEPHYR)
    else:
        print("Uso:")
        print("  docker compose run --rm massai-run jira")
        print("  docker compose run --rm massai-run zephyr")
        print("  docker compose run --rm massai-run all")
        print("\nVars úteis (override com -e):")
        print(f"  API_URL={API_URL}")
        print(f"  ENDPOINT_JIRA={ENDPOINT_JIRA}  FLUXO_JIRA={FLUXO_JIRA}  QUANTIDADE_JIRA={QTD_JIRA}")
        print(f"  ENDPOINT_ZEPHYR={ENDPOINT_ZEPHYR}  FLUXO_ZEPHYR={FLUXO_ZEPHYR}  QUANTIDADE_ZEPHYR={QTD_ZEPHYR}")
        sys.exit(0)

if __name__ == "__main__":
    main()
