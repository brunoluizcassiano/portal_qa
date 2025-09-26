# -*- coding: utf-8 -*-
import os
import time
import datetime
import requests
import yaml
import time, requests

# ====== Constantes originais (mantidas) ======
CONFIG_AGENDAMENTOS_FILE = 'config/massai_agendamentos.yaml'
CONFIG_HISTORICO_FILE = 'config/massai_historico_execucoes.yaml'

# ====== Tunáveis por ENV (retrocompatíveis) ======
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))     # checagem a cada Xs
TOLERANCIA_MINUTOS = int(os.getenv("TOL_MIN", "1"))       # tolerância ±X min

# ====== API_URL (settings.yaml + override por ENV) ======
def _carregar_api_url_default():
    api_url = 'http://massai-api:8000'
    try:
        if os.path.exists('config/settings.yaml'):
            with open('config/settings.yaml', 'r', encoding='utf-8') as f:
                settings = yaml.safe_load(f) or {}
                if isinstance(settings, dict):
                    api_url = settings.get('api_url', api_url)
    except Exception as e:
        print(f"[WARN] Falha lendo config/settings.yaml: {e}", flush=True)
    return os.getenv('API_URL', api_url)

API_URL = _carregar_api_url_default()

# ====== Cache p/ evitar duplicidade no mesmo dia/horário ======
EXECUCOES_REGISTRADAS = set()


# ====== Funções utilitárias originais (mantidas/nome idêntico) ======
def carregar_agendamentos():
    if not os.path.exists(CONFIG_AGENDAMENTOS_FILE):
        print(f"[WARN] Arquivo de agendamentos não encontrado: {CONFIG_AGENDAMENTOS_FILE}", flush=True)
        return []
    try:
        with open(CONFIG_AGENDAMENTOS_FILE, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or []
            if not isinstance(data, list):
                print(f"[WARN] {CONFIG_AGENDAMENTOS_FILE} não contém lista; ignorando.", flush=True)
                return []
            return data
    except Exception as e:
        print(f"[ERROR] Falha lendo {CONFIG_AGENDAMENTOS_FILE}: {e}", flush=True)
        return []

def carregar_historico_execucoes():
    if not os.path.exists(CONFIG_HISTORICO_FILE):
        return []
    try:
        with open(CONFIG_HISTORICO_FILE, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or []
            if isinstance(data, list):
                return data
            return []
    except Exception as e:
        print(f"[WARN] Falha lendo histórico: {e}", flush=True)
        return []

def salvar_historico_execucoes(historico):
    try:
        os.makedirs(os.path.dirname(CONFIG_HISTORICO_FILE), exist_ok=True)
        with open(CONFIG_HISTORICO_FILE, 'w', encoding='utf-8') as f:
            yaml.safe_dump(historico, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        print(f"[ERROR] Falha salvando histórico: {e}", flush=True)

def traduzir_dia(dia_ingles):
    dias = {
        "Monday": "Segunda",
        "Tuesday": "Terça",
        "Wednesday": "Quarta",
        "Thursday": "Quinta",
        "Friday": "Sexta",
        "Saturday": "Sábado",
        "Sunday": "Domingo"
    }
    return dias.get(dia_ingles, dia_ingles)

def horarios_compatíveis(horario_agendado, horario_atual, tolerancia_minutos=1):
    """ Verifica se o horário atual está dentro de uma tolerância (± minutos). """
    formato = "%H:%M"
    try:
        h_agendado = datetime.datetime.strptime(horario_agendado, formato)
        h_atual = datetime.datetime.strptime(horario_atual, formato)
    except ValueError:
        return False
    diferenca = abs((h_agendado - h_atual).total_seconds() / 60)
    return diferenca <= tolerancia_minutos


# ====== Helpers para endpoint/URL (backward-compatible) ======
def _resolver_base_url(agendamento) -> str:
    """
    Precedência:
      1) ENV API_URL (se setada)
      2) agendamento['api_url'] (opcional)
      3) API_URL (settings.yaml ou default http://massai-api:8000)
    """
    if os.getenv('API_URL'):
        return os.getenv('API_URL')
    if isinstance(agendamento, dict) and agendamento.get('api_url'):
        return str(agendamento['api_url'])
    return API_URL

def _resolver_endpoint(agendamento) -> str:
    """
    Compatível com modelo anterior:
      - se existir 'endpoint', usa-o;
      - senão, se 'servico' == jira → /run_jira/
      - senão, se 'servico' == zephyr → /run_zephyr/
      - caso contrário → /run_fluxo/
    """
    if isinstance(agendamento, dict):
        endpoint = agendamento.get('endpoint')
        if endpoint:
            return endpoint if endpoint.startswith('/') else f"/{endpoint}"
        servico = (agendamento.get('servico') or "").strip().lower()
        if servico == "jira":
            return "/run_jira/"
        if servico == "zephyr":
            return "/run_zephyr/"
    return "/run_fluxo/"

def _post_agendamento(base_url: str, endpoint: str, fluxo: str, quantidade: int):
    url = f"{base_url.rstrip('/')}{endpoint}"
    payload = {"fluxo_name": fluxo, "quantidade": int(quantidade)}
    resp = requests.post(url, json=payload, timeout=90)
    resp.raise_for_status()
    return resp


def _api_alive(url: str) -> bool:
    try:
        r = requests.get(url.rstrip("/") + "/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def _aguarda_api(api_base: str, tentativas: int = 60, intervalo: int = 2):
    print(f"[INIT] Aguardando API em {api_base}…", flush=True)
    for i in range(tentativas):
        if _api_alive(api_base):
            print("[INIT] API respondendo. Iniciando scheduler.", flush=True)
            return
        time.sleep(intervalo)
    print("[WARN] API não respondeu no tempo esperado, seguirei mesmo assim.", flush=True)

# ====== Worker principal (mantido de nome) ======
def scheduler_worker():
    print("✅ Scheduler iniciado…", flush=True)
    print(f"   → API base: {API_URL}", flush=True)
    print(f"   → Agendamentos: {CONFIG_AGENDAMENTOS_FILE}", flush=True)
    print(f"   → Histórico: {CONFIG_HISTORICO_FILE}", flush=True)
    print(f"   → Poll: {POLL_INTERVAL}s | Tolerância: ±{TOLERANCIA_MINUTOS} min", flush=True)

    _aguarda_api(API_URL, tentativas=60, intervalo=2)

    while True:
        try:
            agendamentos = carregar_agendamentos()
            now = datetime.datetime.now()
            horario_atual = now.strftime("%H:%M")
            dia_semana = traduzir_dia(now.strftime("%A"))

            for agendamento in agendamentos:
                if not isinstance(agendamento, dict):
                    continue

                fluxo = agendamento.get('fluxo_name') or agendamento.get('fluxo') or ''
                horario = agendamento.get('horario') or ''
                dias_semana = agendamento.get('dias_semana') or ["Todos"]
                quantidade = int(agendamento.get('quantidade') or 1)

                if not fluxo or not horario:
                    # item inválido: continue sem derrubar
                    print(f"[WARN] Agendamento inválido (faltando fluxo/horário): {agendamento}", flush=True)
                    continue

                # Verifica dia da semana
                if "Todos" not in dias_semana and dia_semana not in dias_semana:
                    continue

                chave_execucao = f"{fluxo}|{horario}|{now.strftime('%d/%m/%Y')}"
                if chave_execucao in EXECUCOES_REGISTRADAS:
                    continue

                if horarios_compatíveis(horario, horario_atual, tolerancia_minutos=TOLERANCIA_MINUTOS):
                    base_url = _resolver_base_url(agendamento)
                    endpoint = _resolver_endpoint(agendamento)

                    print(f"[⏰] {fluxo} @ {horario_atual} → {base_url}{endpoint}", flush=True)

                    status = "Sucesso"
                    mensagem = ""
                    try:
                        r = _post_agendamento(base_url, endpoint, fluxo, quantidade)
                        mensagem = (r.text or "")[:800]
                        print(f"[OK] HTTP {r.status_code} para {fluxo}", flush=True)
                    except Exception as e:
                        status = "Falha"
                        mensagem = str(e)[:800]
                        print(f"[ERRO] {fluxo}: {mensagem}", flush=True)

                    historico = carregar_historico_execucoes()
                    historico.append({
                        "fluxo_name": fluxo,
                        "horario": horario,
                        "data": now.strftime("%d/%m/%Y"),
                        "status": status,
                        "mensagem": mensagem,
                        "endpoint": endpoint,
                        "api_url": base_url
                    })
                    salvar_historico_execucoes(historico)
                    EXECUCOES_REGISTRADAS.add(chave_execucao)

        except Exception as e:
            print(f"[FATAL] erro no loop principal: {e}", flush=True)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    # roda em modo unbuffered se possível (melhor ainda se o Dockerfile tiver "python -u")
    try:
        scheduler_worker()
    except KeyboardInterrupt:
        print("Encerrando scheduler…", flush=True)
