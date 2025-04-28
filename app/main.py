from fastapi import FastAPI
from pydantic import BaseModel
from agent.fluxo_cartao_agent import FluxoCartaoAgent
from agent.validator import MassaValidator
from agent.scheduler import scheduler_worker
import threading
import yaml
import requests

# Lê configurações do settings.yaml
with open('config/settings.yaml') as f:
    settings = yaml.safe_load(f)

webhook_url = settings.get('webhook_url', '')

# Inicializa a aplicação FastAPI
app = FastAPI()

# Inicia o agendador de tarefas em uma thread separada
threading.Thread(target=scheduler_worker, daemon=True).start()

# Instancia agentes de fluxo e validação
agent = FluxoCartaoAgent(
    'config/api_routes.yaml',
    'config/fluxos.yaml',
    'config/massai-config.yaml'
)

class FluxoRequest(BaseModel):
    fluxo_name: str
    quantidade: int

@app.get("/")
def read_root():
    return {"MassAI": "Running"}

@app.post("/run_fluxo/")
def run_fluxo(request: FluxoRequest):
    try:
        contexto_list = agent.run_fluxo(request.fluxo_name, request.quantidade)
        return {"status": "Sucesso", "contexto": contexto_list}
    except Exception as e:
        send_teams_alert([str(e)])
        return {"status": "Falha", "erros": [str(e)]}

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
