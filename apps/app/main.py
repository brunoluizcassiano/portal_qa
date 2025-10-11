from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from apps.agent.fluxo_cartao_agent import FluxoCartaoAgent
from apps.agent.validator import MassaValidator
from apps.agent.scheduler import scheduler_worker
import threading
import yaml
import requests
import os
# import tomllib  # Python 3.11+
try:
   import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10
   import tomli as tomllib
import sys, pathlib
# garante que /app (raiz do projeto no container) está no PYTHONPATH
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
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
DATA_DIR = Path("config/database")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ==== Imports das funções de extração (ficam nos módulos dos clients) ====
from extractor.jira.jira_client import (
    run_extracao_jira_sprint,
    run_extracao_jira_bases,
)
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

# ====== MODELOS ======
class FluxoRequest(BaseModel):
    fluxo_name: str
    quantidade: int = 1
    env: Optional[str] = None  # <-- NOVO: ambiente opcional vindo do body

@app.get("/")
def read_root():
    return {"MassAI": "Running"}

@app.get("/health")
def health():
    return {"ok": True}

# ====== Endpoint genérico (compatível com scheduler) ======
@app.post("/run_fluxo/")
def run_fluxo(request_body: FluxoRequest, req: Request):
    """
    - Se vier env no body, usa ele.
    - Se não, tenta X-MassAI-Env no header.
    - Repassa env para o Agent executar no ambiente selecionado.
    """
    name = (request_body.fluxo_name or "").lower().strip()

    # 1) checa primeiro o fluxo específico "jira_bases"
    if "jira_bases" in name:
        return run_extracao_jira_bases(
            jira_cfg=JIRA, app_cfg=APP,
            quantidade=request_body.quantidade, data_dir=DATA_DIR
        )

    # 2) depois os fluxos "jira" e "zephyr" genéricos
    if "jira" in name:
        return run_extracao_jira_sprint(
            jira_cfg=JIRA, app_cfg=APP,
            quantidade=request_body.quantidade, data_dir=DATA_DIR
        )
    if "zephyr" in name:
        return run_extracao_zephyr_diaria(
            zephyr_cfg=ZEPHYR, app_cfg=APP,
            quantidade=request_body.quantidade, data_dir=DATA_DIR
        )

    # 3) fallback: FluxoCartaoAgent (respeitando o ambiente)
    try:
        env = request_body.env or req.headers.get("X-MassAI-Env")  # <-- pega do body ou do header
        contexto_list = agent.run_fluxo(request_body.fluxo_name, quantidade=request_body.quantidade, env=env)
        return {"status": "Sucesso", "contexto": contexto_list}
    except Exception as e:
        send_teams_alert([str(e)])
        return {"status": "Falha", "erros": [str(e)]}

# ====== Endpoints específicos (opcionais) ======
@app.post("/run_jira/")
def run_jira(request_body: FluxoRequest):
    return run_extracao_jira_sprint(jira_cfg=JIRA, app_cfg=APP, quantidade=request_body.quantidade, data_dir=DATA_DIR)

@app.post("/run_jira_bases/")
def run_jira_bases(request_body: FluxoRequest):
    return run_extracao_jira_bases(jira_cfg=JIRA, app_cfg=APP, quantidade=request_body.quantidade, data_dir=DATA_DIR)

@app.post("/run_zephyr/")
def run_zephyr(request_body: FluxoRequest):
    return run_extracao_zephyr_diaria(zephyr_cfg=ZEPHYR, app_cfg=APP, quantidade=request_body.quantidade, data_dir=DATA_DIR)

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
