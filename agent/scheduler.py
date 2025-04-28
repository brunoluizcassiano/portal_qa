# scheduler.py

import time
import datetime
import requests
import yaml
import os

CONFIG_AGENDAMENTOS_FILE = 'config/massai_agendamentos.yaml'
CONFIG_HISTORICO_FILE = 'config/massai_historico_execucoes.yaml'

# Carrega a URL da API
with open('config/settings.yaml') as f:
    settings = yaml.safe_load(f)

API_URL = settings.get('api_url', 'http://massai-api:8000')

EXECUCOES_REGISTRADAS = set()

def carregar_agendamentos():
    if os.path.exists(CONFIG_AGENDAMENTOS_FILE):
        with open(CONFIG_AGENDAMENTOS_FILE, 'r') as f:
            return yaml.safe_load(f) or []
    else:
        return []

def carregar_historico_execucoes():
    if os.path.exists(CONFIG_HISTORICO_FILE):
        with open(CONFIG_HISTORICO_FILE, 'r') as f:
            return yaml.safe_load(f) or []
    else:
        return []

def salvar_historico_execucoes(historico):
    with open(CONFIG_HISTORICO_FILE, 'w') as f:
        yaml.dump(historico, f, allow_unicode=True)

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
    """ Verifica se o horário atual está dentro de uma tolerância """
    formato = "%H:%M"
    h_agendado = datetime.datetime.strptime(horario_agendado, formato)
    h_atual = datetime.datetime.strptime(horario_atual, formato)

    diferenca = abs((h_agendado - h_atual).total_seconds() / 60)
    return diferenca <= tolerancia_minutos

def scheduler_worker():
    print("✅ Scheduler iniciado e rodando...")

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

                # Não está no dia certo
                if "Todos" not in dias_semana and dia_semana not in dias_semana:
                    continue

                chave_execucao = f"{fluxo}_{horario}_{now.strftime('%d/%m/%Y')}"
                if chave_execucao in EXECUCOES_REGISTRADAS:
                    continue  # Já executou esse fluxo hoje nesse horário

                if horarios_compatíveis(horario, horario_atual):
                    print(f"[⏰] Executando agendamento: {fluxo} - {horario}")

                    try:
                        params = {"fluxo_name": fluxo, "quantidade": quantidade}
                        response = requests.post(f"{API_URL}/run_fluxo/", json=params)

                        status = "Sucesso" if response.status_code == 200 else "Falha"
                        print(f"[✅] Fluxo {fluxo} executado com status: {status}")

                    except Exception as e:
                        print(f"[❌] Erro ao executar agendamento '{fluxo}': {e}")
                        status = "Falha"

                    historico = carregar_historico_execucoes()
                    historico.append({
                        "fluxo_name": fluxo,
                        "horario": horario,
                        "data": now.strftime("%d/%m/%Y"),
                        "status": status
                    })
                    salvar_historico_execucoes(historico)

                    EXECUCOES_REGISTRADAS.add(chave_execucao)

                else:
                    print(f"[⏳] Fluxo '{fluxo}' agendado para {horario}, horário atual {horario_atual}, aguardando.")

        except Exception as e:
            print(f"[❌] Erro geral no scheduler: {e}")

        time.sleep(60)  # Checa a cada minuto
