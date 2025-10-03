import requests
import yaml
import os

class FluxoCartaoAgent:
    def __init__(self, api_routes_file, fluxos_file, massai_config_file=None):
        self.api_routes = self.carregar_yaml(api_routes_file)
        self.fluxos = self.carregar_yaml(fluxos_file)
        self.massai_config = self.carregar_yaml(massai_config_file) if massai_config_file else {}

        self.base_url = self.massai_config.get('api_base_url', 'http://massai-api:8000')
        self.headers_default = self.massai_config.get('default_headers', {})

    def carregar_yaml(self, caminho):
        if caminho and os.path.exists(caminho):
            with open(caminho, 'r') as f:
                return yaml.safe_load(f)
        return {}

    def run_fluxo(self, fluxo_name, quantidade):
        contexto_list = []
        fluxo = self.fluxos.get(fluxo_name, [])

        for _ in range(quantidade):
            contexto = {}

            for etapa in fluxo:
                api_name = etapa.get('api_name')
                payload = etapa.get('payload', {})
                tipo_acao = etapa.get('tipo_acao', 'POST').upper()
                headers = etapa.get('headers', self.headers_default)

                if api_name.startswith('http'):
                    url = api_name
                else:
                    url = f"{self.base_url}/{self.api_routes.get(api_name, api_name)}"

                try:
                    if tipo_acao == "GET":
                        response = requests.get(url, headers=headers, timeout=10)
                    elif tipo_acao == "POST":
                        response = requests.post(url, json=payload, headers=headers, timeout=10)
                    elif tipo_acao == "PUT":
                        response = requests.put(url, json=payload, headers=headers, timeout=10)
                    elif tipo_acao == "DELETE":
                        response = requests.delete(url, headers=headers, timeout=10)
                    else:
                        raise Exception(f"Tipo de ação '{tipo_acao}' não suportado.")

                    response.raise_for_status()

                    contexto[api_name] = {
                        "status_code": response.status_code,
                        "response": response.json() if 'application/json' in response.headers.get('Content-Type', '') else response.text[:300]
                    }

                except Exception as e:
                    contexto[api_name] = {
                        "status_code": None,
                        "error": str(e)
                    }

            contexto_list.append(contexto)

        return contexto_list
