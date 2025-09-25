# scheduler.py
import time
import datetime
import requests
import yaml
import os

# ====== Constantes originais (mantidas) ======
CONFIG_AGENDAMENTOS_FILE = 'config/massai_agendamentos.yaml'
CONFIG_HISTORICO_FILE = 'config/massai_historico_execucoes.yaml'

# ====== Novos tunáveis por ENV (retrocompatíveis) ======
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))   # checagem a cada Xs (padrão 60s)
TOLERANCIA_MINUTOS = int(os.getenv("TOL_MIN", "1"))     # tolerância de horário ±X min (padrão 1)
QUIET_WAIT_LOGS = os.getenv("QUIET_WAIT_LOGS", "0") == "1"  # suprime logs de "aguardando", opcional

# ====== Carrega a URL da API (mantido, com fallback seguro) ======
API_URL = 'http://massai-api:8000'
try:
    if os.path.exists('config/settings.yaml'):
        with open('config/settings.yaml', 'r', encoding='utf-8') as f:
            settings = yaml.safe_load(f) or {}
            API_URL = settings.get('api_url', API_URL)
except Exception:
    # mantém default se der erro
    pass

# Permite override total pela ENV sem quebrar o padrão acima
API_URL = os.getenv('API_URL', API_URL)

# Cache de execuções do dia/horário (mantido)
EXECUCOES_REGISTRADAS = set()


# ====== Funções utilitárias originais (mantidas/nome idêntico) ======
def carregar_agendamentos():
    if os.path.exists(CONFIG_AGENDAMENTOS_FILE):
        with open(CONFIG_AGENDAMENTOS_FILE, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or []
    else:
        return []

def carregar_historico_execucoes():
    if os.path.exists(CONFIG_HISTORICO_FILE):
        with open(CONFIG_HISTORICO_FILE, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or []
    else:
        return []

def salvar_historico_execucoes(historico):
    with open(CONFIG_HISTORICO_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(historico, f, allow_unicode=True, sort_keys=False)

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


# ====== Novas helpers (backward-compatible) ======
def _resolver_base_url(agendamento) -> str:
    """
    Ordem de precedência para base URL (retrocompatível):
    1) ENV API_URL (se definida)
    2) Campo 'api_url' no item do agendamento (opcional)
    3) API_URL carregada de settings.yaml ou default http://massai-api:8000
    """
    if os.getenv('API_URL'):
        return os.getenv('API_URL')
    if isinstance(agendamento, dict) and agendamento.get('api_url'):
        return str(agendamento['api_url'])
    return API_URL

def _resolver_endpoint(agendamento) -> str:
    """
    Define endpoint por agendamento, cobrindo Jira/Zephyr sem quebrar o comportamento antigo.
    Regras:
      - Se 'endpoint' estiver presente, usa-o.
      - Senão, se 'servico' == 'jira'  -> '/run_jira/'
      - Senão, se 'servico' == 'zephyr'-> '/run_zephyr/'
      - Caso contrário -> '/run_fluxo/' (comportamento original)
    """
    if isinstance(agendamento, dict):
        endpoint = agendamento.get('endpoint')
        if endpoint:
            return endpoint if endpoint.startswith('/') else f"/{endpoint}"
        servico = (agendamento.get('servico') or "").strip().lower()
        if servico == 'jira':
            return '/run_jira/'
        if servico == 'zephyr':
            return '/run_zephyr/'
    return '/run_fluxo/'

def _post_agendamento(base_url: str, endpoint: str, fluxo: str, quantidade: int):
    url = f"{base_url.rstrip('/')}{endpoint}"
    payload = {"fluxo_name": fluxo, "quantidade": int(quantidade)}
    # timeout para evitar travas indefinidas
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    return resp


# ====== Worker principal (mantido de nome) ======
def scheduler_worker():
    print("✅ Scheduler iniciado e rodando...")
    print(f"   → Base API: {API_URL}")
    print(f"   → Agendamentos: {CONFIG_AGENDAMENTOS_FILE}")
    print(f"   → Histórico: {CONFIG_HISTORICO_FILE}")
    print(f"   → Poll: {POLL_INTERVAL}s | Tolerância: ±{TOLERANCIA_MINUTOS} min")

    while True:
        try:
            agendamentos = carregar_agendamentos()
            now = datetime.datetime.now()
            horario_atual = now.strftime("%H:%M")
            dia_semana = traduzir_dia(now.strftime("%A"))

            for agendamento in agendamentos:
                fluxo = agendamento.get('fluxo_name')
                horario = agendamento.get('horario')
                dias_semana = agendamento.get('dias_semana', ["Todos"])
                quantidade = agendamento.get('quantidade', 1)

                if not fluxo or not horario:
                    print(f"[⚠️] Agendamento inválido encontrado. Ignorando.")
                    continue

                # Verifica dia da semana
                if "Todos" not in dias_semana and dia_semana not in dias_semana:
                    continue

                chave_execucao = f"{fluxo}_{horario}_{now.strftime('%d/%m/%Y')}"
                if chave_execucao in EXECUCOES_REGISTRADAS:
                    # Já executado este fluxo hoje neste horário
                    continue

                if horarios_compatíveis(horario, horario_atual, tolerancia_minutos=TOLERANCIA_MINUTOS):
                    # Resolve base_url/endpoint por item (Jira/Zephyr/Fluxo genérico)
                    base_url = _resolver_base_url(agendamento)
                    endpoint = _resolver_endpoint(agendamento)

                    print(f"[⏰] Executando agendamento: {fluxo} - {horario} → {base_url}{endpoint}")

                    status = "Sucesso"
                    mensagem = ""
                    try:
                        response = _post_agendamento(base_url, endpoint, fluxo, quantidade)
                        # sucesso HTTP: 2xx
                        mensagem = (response.text or "")[:600]
                        print(f"[✅] Fluxo {fluxo} executado com status HTTP {response.status_code}.")
                    except Exception as e:
                        status = "Falha"
                        mensagem = str(e)[:600]
                        print(f"[❌] Erro ao executar agendamento '{fluxo}': {mensagem}")

                    # Atualiza histórico
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

                    # Memoriza execução para não duplicar no mesmo minuto/horário
                    EXECUCOES_REGISTRADAS.add(chave_execucao)

                else:
                    if not QUIET_WAIT_LOGS:
                        print(f"[⏳] Fluxo '{fluxo}' agendado para {horario}, horário atual {horario_atual}, aguardando.")

        except Exception as e:
            print(f"[❌] Erro geral no scheduler: {e}")

        time.sleep(POLL_INTERVAL)  # Checa periodicamente
