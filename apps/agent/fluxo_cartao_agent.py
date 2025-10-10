# -*- coding: utf-8 -*-
import os
import yaml
import requests
from typing import Any, Dict, List, Optional, Tuple
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class FluxoCartaoAgent:
    """
    Executa fluxos HTTP a partir de um YAML de fluxos.
    - `api_name` pode ser URL absoluta (http/https) OU chave em api_routes.yaml.
    - `tipo_acao`: GET | POST | PUT | DELETE
    - GET usa params=payload; os demais, json=payload.
    - Usa uma Session robusta (igual ao jira_client): trust_env=False, proxies={}, verify=False, Retry, Adapter.
    - Headers default podem vir de massai_config (default_headers) ou do próprio passo.
    - Auth (Basic) opcional via massai_config: basic_auth: { user/email, password/api_token/token }.

    Exemplo que deve funcionar:
    ---
    Consultar Todo Externo:
      - api_name: https://jsonplaceholder.typicode.com/todos/1
        tipo_acao: GET
        payload: {}
    """

    def __init__(self, api_routes_file: Optional[str], fluxos_file: str, massai_config_file: Optional[str] = None):
        self.api_routes = self._load_yaml(api_routes_file)
        self.fluxos = self._load_yaml(fluxos_file)
        self.massai_config = self._load_yaml(massai_config_file) if massai_config_file else {}

        # URL base opcional (quando api_name não é URL absoluta)
        self.base_url: str = self.massai_config.get('api_base_url', 'http://127.0.0.1:8000')
        # headers default vindos do config
        self.headers_default: Dict[str, str] = self.massai_config.get('default_headers', {}) or {}

        # auth opcional (Basic) a partir do massai_config
        self.auth = self._resolve_basic_auth(self.massai_config)

        # cria uma Session “blindada” (igual jira_client)
        self.session: Session = self._build_session()

    # ---------------- infra ----------------

    def _load_yaml(self, path: Optional[str]) -> dict:
        if path and os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}

    def _resolve_basic_auth(self, cfg: dict):
        """
        Tenta montar (user, token|password) para Basic Auth a partir do massai_config.
        Chaves suportadas: user/email + (password|api_token|token)
        """
        if not isinstance(cfg, dict):
            return None
        auth_cfg = cfg.get('basic_auth') or cfg.get('auth') or {}
        if not isinstance(auth_cfg, dict):
            return None
        user = auth_cfg.get('user') or auth_cfg.get('email')
        pwd  = auth_cfg.get('password') or auth_cfg.get('api_token') or auth_cfg.get('token')
        if user and pwd:
            return (user, pwd)
        return None

    def _build_session(self) -> Session:
        """
        Modelo idêntico ao jira_client (como você pediu):
          - trust_env = False
          - proxies   = {}
          - verify    = False
          - Retry + HTTPAdapter
          - s.auth    = self.auth
          - header    Accept: application/json
        """
        s = requests.Session()
        s.trust_env = False
        s.proxies = {}
        s.verify = False

        retries = Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
        s.mount("http://", adapter)
        s.mount("https://", adapter)

        s.auth = self.auth
        s.headers.update({"Accept": "application/json"})

        # se houver headers_default no config, aplica também na Session
        if self.headers_default:
            s.headers.update(self.headers_default)

        return s

    # ------------- resolução de rota -------------

    def _is_absolute_url(self, name_or_url: str) -> bool:
        n = (name_or_url or "").strip().lower()
        return n.startswith("http://") or n.startswith("https://")

    def _from_api_routes(self, api_name: str) -> Tuple[str, Optional[str], Dict[str, str]]:
        """
        Resolve url/method/headers a partir de api_routes.yaml quando api_name não é URL absoluta.
        Formatos suportados:
          routes:
            minha_api:
              url: https://exemplo.com/recurso
              method: GET
              headers: { Authorization: Bearer ... }
        ou
          minha_api:
            url: ...
            method: ...
        Retorna: (url, method|None, headers)
        """
        routes = self.api_routes.get("routes") or self.api_routes
        if not isinstance(routes, dict):
            return "", None, {}

        cfg = routes.get(api_name) or {}
        url = (cfg.get("url") or cfg.get("endpoint") or "").strip()
        method = (cfg.get("method") or "").strip().upper() or None
        headers = cfg.get("headers") or {}
        return url, method, headers

    def _resolve_url_method_headers(
        self, api_name: str, tipo_acao: Optional[str], step_headers: Optional[Dict[str, str]]
    ) -> Tuple[str, str, Dict[str, str]]:
        """
        1) Se api_name for URL absoluta → usa direto e método = tipo_acao (default GET)
        2) Senão, consulta api_routes.yaml (url/method/headers)
        3) tipo_acao (do passo) sobrepõe o method da rota
        4) headers = session.headers + headers_da_rota + headers_do_passo (com prioridade do passo)
        """
        # começa com os headers atuais da Session (Accept + default_headers + possivel Authorization)
        headers: Dict[str, str] = dict(self.session.headers or {})

        if self._is_absolute_url(api_name):
            url = api_name.strip()
            method = (tipo_acao or "GET").strip().upper()
        else:
            url_routes, method_routes, headers_routes = self._from_api_routes(api_name)
            if not url_routes:
                # como fallback, considera api_name como path relativo à base_url
                url_routes = f"{self.base_url.rstrip('/')}/{api_name.lstrip('/')}"
            url = url_routes
            method = (tipo_acao or method_routes or "GET").strip().upper()
            headers.update(headers_routes or {})

        if step_headers:
            headers.update(step_headers)

        return url, method, headers

    # ---------------- execução ----------------

    def _call_step(self, url: str, method: str, payload: Dict[str, Any], headers: Dict[str, str]):
        """
        GET → params=payload
        POST/PUT/DELETE → json=payload
        Usa SEMPRE a mesma Session (retry/verify/proxy/auth).
        """
        if method == "GET":
            return self.session.get(url, params=payload or {}, headers=headers, timeout=180, verify=self.session.verify)
        elif method == "POST":
            return self.session.post(url, json=payload or {}, headers=headers, timeout=180, verify=self.session.verify)
        elif method == "PUT":
            return self.session.put(url, json=payload or {}, headers=headers, timeout=180, verify=self.session.verify)
        elif method == "DELETE":
            return self.session.delete(url, json=payload or {}, headers=headers, timeout=180, verify=self.session.verify)
        else:
            raise ValueError(f"Método HTTP não suportado: {method}")

    def _parse_body(self, resp: requests.Response) -> Any:
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "application/json" in ct:
            try:
                return resp.json()
            except Exception:
                return resp.text
        return resp.text

    # --------------- API pública ---------------

    def run_fluxo(self, fluxo_name: str, quantidade: int) -> List[Dict[str, Any]]:
        """
        Executa N vezes o fluxo `fluxo_name` conforme definido no YAML de fluxos.
        Retorna uma lista (por execução) de dicts com status/response por passo.
        """
        fluxo = self.fluxos.get(fluxo_name, [])
        if not isinstance(fluxo, list) or not fluxo:
            raise ValueError(f"Fluxo '{fluxo_name}' não encontrado ou sem passos.")

        resultados: List[Dict[str, Any]] = []

        for _ in range(int(quantidade or 1)):
            contexto: Dict[str, Any] = {}

            for etapa in fluxo:
                api_name = etapa.get('api_name')
                payload = etapa.get('payload', {}) or {}
                tipo_acao = (etapa.get('tipo_acao') or 'GET').upper()
                step_headers = etapa.get('headers') or {}

                if not api_name:
                    contexto["__erro_config"] = "Passo sem 'api_name'."
                    continue

                try:
                    url, method, headers = self._resolve_url_method_headers(api_name, tipo_acao, step_headers)
                    resp = self._call_step(url, method, payload, headers)

                    contexto[api_name] = {
                        "method": method,
                        "url": url,
                        "status_code": resp.status_code,
                        "response": self._parse_body(resp)
                    }
                except Exception as e:
                    contexto[api_name] = {
                        "method": tipo_acao,
                        "url": api_name,
                        "status_code": None,
                        "error": str(e)
                    }

            resultados.append(contexto)

        return resultados
