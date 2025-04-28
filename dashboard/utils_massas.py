import yaml
import os
import datetime
import random
import string

MASSAS_FILE = "config/massai_massas_geradas.yaml"

def gerar_id_unico():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def carregar_massas_geradas():
    if os.path.exists(MASSAS_FILE):
        with open(MASSAS_FILE, 'r') as f:
            return yaml.safe_load(f) or []
    else:
        return []

def salvar_massas_geradas(massas):
    with open(MASSAS_FILE, 'w') as f:
        yaml.dump(massas, f, allow_unicode=True)

def salvar_massa_gerada(fluxo, quantidade, conteudo):
    massas = carregar_massas_geradas()

    nova_massa = {
        "id": gerar_id_unico(),
        "fluxo_gerado": fluxo,
        "quantidade": quantidade,
        "conteudo": conteudo,
        "data_hora_geracao": datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "tipo_execucao": "adhoc",
        "status_validacao": "pendente"
    }

    massas.append(nova_massa)
    salvar_massas_geradas(massas)
