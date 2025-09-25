from fastapi import FastAPI
from pydantic import BaseModel
from agent.fluxo_cartao_agent import FluxoCartaoAgent
from agent.validator import MassaValidator
from agent.scheduler import scheduler_worker
import threading
import yaml
import requests
import os
import tomllib  # Python 3.11+
from pathlib import Path

# ==== Lê configurações do settings.yaml (Teams webhook etc.) ====
with open('config/settings.yaml', 'r', encoding='utf-8') as f:
    settings = yaml.safe_load(f) or {}

webhook_url = settings.get('webhook_url', '')

# ==== Lê secrets.toml (Jira/Zephyr/App) ====
SECRETS_PATH = os.getenv("SECRETS_PATH", "/app/.streamlit/secrets.toml")
SECRETS = {}
if os.path.exists(SECRETS_PATH):
    with open(SECRETS_PATH, "rb") as f:
        SECRETS = tomllib.load(f)
JIRA   = SECRETS.get("jira", {})
ZEPHYR = SECRETS.get("zephyr", {})
APP    = SECRETS.get("app", {})

# Pasta onde salvaremos os arquivos para o dashboard
DATA_DIR = Path("config/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ==== Imports das funções de extração (ficam nos módulos dos clients) ====
from extractor.jira.jira_client import run_extracao_jira_sprint
from extractor.zephyr.zephyr_client import run_extracao_zephyr_diaria

# Inicializa a aplicação FastAPI
app = FastAPI()

# Inicia o agendador de tarefas em uma thread separada (mantido)
threading.Thread(target=scheduler_worker, daemon=True).start()

# Instancia agentes de fluxo e validação (mantido)
agent = FluxoCartaoAgent(
    'config/api_routes.yaml',
    'config/fluxos.yaml',
    'config/massai-config.yaml'
)

class FluxoRequest(BaseModel):
    fluxo_name: str
    quantidade: int = 1

@app.get("/")
def read_root():
    return {"MassAI": "Running"}

# ====== Endpoint genérico (compatível com scheduler) ======
@app.post("/run_fluxo/")
def run_fluxo(request: FluxoRequest):
    name = (request.fluxo_name or "").lower().strip()

    # Despacha para Jira/Zephyr quando identificado pelo nome
    if "jira" in name:
        return run_extracao_jira_sprint(jira_cfg=JIRA, app_cfg=APP, quantidade=request.quantidade, data_dir=DATA_DIR)
    if "zephyr" in name:
        return run_extracao_zephyr_diaria(zephyr_cfg=ZEPHYR, app_cfg=APP, quantidade=request.quantidade, data_dir=DATA_DIR)

    # Caso contrário, mantém o comportamento anterior (FluxoCartaoAgent)
    try:
        contexto_list = agent.run_fluxo(request.fluxo_name, request.quantidade)
        return {"status": "Sucesso", "contexto": contexto_list}
    except Exception as e:
        send_teams_alert([str(e)])
        return {"status": "Falha", "erros": [str(e)]}

# ====== Endpoints específicos (opcionais) ======
@app.post("/run_jira/")
def run_jira(request: FluxoRequest):
    return run_extracao_jira_sprint(jira_cfg=JIRA, app_cfg=APP, quantidade=request.quantidade, data_dir=DATA_DIR)

@app.post("/run_zephyr/")
def run_zephyr(request: FluxoRequest):
    return run_extracao_zephyr_diaria(zephyr_cfg=ZEPHYR, app_cfg=APP, quantidade=request.quantidade, data_dir=DATA_DIR)

# ====== Alertas Teams (mantido) ======
def send_teams_alert(errors):
    if not webhook_url:
        print("[MassAI] Webhook do Teams não configurado. Alerta não enviado.")
        return

    payload = {
        "text": f"🚨 Erro detectado na geração de massa MassAI:\n\n{chr(10).join(errors)}"
    }
    headers = {'Content-Type': 'application/json'}

    try:
        requests.post(webhook_url, json=payload, headers=headers)
    except Exception as e:
        print(f"[MassAI] Erro ao enviar alerta para Teams: {e}")
