# -*- coding: utf-8 -*-
import os
import re
import yaml
import json
import requests
from typing import Any, Dict, List, Optional, Tuple, Union
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests.auth import HTTPBasicAuth


def _asbool(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in ("false", "0", "no", "off")


def _safe_yaml_load(path: Optional[str]) -> dict:
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _jsonish(obj: Any) -> Any:
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


def _get_value_from_path(data: Any, path: str) -> Any:
    """
    Lê caminhos do tipo:
      - client.nome
      - data[0].id
      - cards[0].cardId
    Sem libs externas (jsonpath).
    """
    try:
        parts = [p for p in re.split(r"[.\[\]]+", str(path).strip()) if p != ""]
        cur: Any = data
        for p in parts:
            if isinstance(cur, list):
                idx = int(p)
                if idx < 0 or idx >= len(cur):
                    return None
                cur = cur[idx]
            elif isinstance(cur, dict):
                cur = cur.get(p)
            else:
                return None
        return cur
    except Exception:
        return None


def _substitute_templates(value: Any, ctx: Dict[str, Any]) -> Any:
    """
    Substitui {{variavel}} em strings; aplica recursivamente em dicts/listas.
    """
    if isinstance(value, str):
        def repl(m):
            key = m.group(1).strip()
            v = ctx.get(key)
            return "" if v is None else str(v)
        return re.sub(r"\{\{\s*([^}]+)\s*\}\}", repl, value)
    if isinstance(value, dict):
        return {k: _substitute_templates(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_templates(v, ctx) for v in value]
    return value


class FluxoCartaoAgent:
    """
    Executa fluxos HTTP a partir de YAML.

    SUPORTA NOVA ESTRUTURA (recomendada):
    ---
    ' Onboarding gluon':
      - tipo: api
        nome: ' Onboarding'
        metodo: POST
        url: https://.../v1/card_onboardings/00000001280/onboarding
        params: {}
        headers: { Content-Type: application/json }
        payload: { ... }
        auth:
          type: none | bearer | basic
          per_env: false
          bearer: { DEFAULT: "<token>" }           # se type=bearer
          basic: { DEV: {user: "...", password: "..."} }  # se type=basic
        variaveis:
          - nome: cartao
            origem: cards[0].cardId

    BACKWARD COMPAT:
    Consultar Todo Externo:
      - api_name: https://jsonplaceholder.typicode.com/todos/1
        tipo_acao: GET
        payload: {}
    """

    def __init__(
        self,
        api_routes_file: Optional[str],
        fluxos_file: str,
        massai_config_file: Optional[str] = None,
    ):
        self.api_routes = _safe_yaml_load(api_routes_file)
        self.fluxos = _safe_yaml_load(fluxos_file)
        self.massai_config = _safe_yaml_load(massai_config_file) if massai_config_file else {}

        # ambiente atual (para url_por_ambiente, payload_por_ambiente e auth per_env)
        self.current_env: str = (
            os.getenv("MASSAI_ENV")
            or os.getenv("ENV_CURRENT")
            or self.massai_config.get("current_env")
            or "DEV"
        ).upper()

        # headers padrão opcionais
        self.headers_default: Dict[str, str] = self.massai_config.get("default_headers", {}) or {}

        # base_url usada somente no modo legacy quando api_name não é URL
        self.base_url: str = self.massai_config.get("api_base_url", "http://127.0.0.1:8000")

        # auth global básica opcional via massai_config (legacy)
        self.auth_basic_global = self._resolve_basic_auth(self.massai_config)

        # sessão estilo jira_client
        self.session: Session = self._build_session()

    # -------------------- Session --------------------

    def _resolve_basic_auth(self, cfg: dict):
        if not isinstance(cfg, dict):
            return None
        auth_cfg = cfg.get("basic_auth") or cfg.get("auth") or {}
        if not isinstance(auth_cfg, dict):
            return None
        user = auth_cfg.get("user") or auth_cfg.get("email")
        pwd = auth_cfg.get("password") or auth_cfg.get("api_token") or auth_cfg.get("token")
        if user and pwd:
            return (user, pwd)
        return None

    def _build_session(self) -> Session:
        s = requests.Session()
        s.trust_env = _asbool(os.getenv("MASSAI_TRUST_ENV"), self.massai_config.get("trust_env", False))
        s.proxies = {} if not s.trust_env else s.proxies
        s.verify = _asbool(os.getenv("MASSAI_SSL_VERIFY"), self.massai_config.get("ssl_verify", False))

        retries = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
        s.mount("http://", adapter)
        s.mount("https://", adapter)

        # headers default + Accept JSON
        s.headers.update({"Accept": "application/json"})
        if self.headers_default:
            s.headers.update(self.headers_default)

        # auth básica global (legacy)
        if self.auth_basic_global:
            s.auth = self.auth_basic_global

        return s

    # -------------------- Legacy route resolver --------------------

    def _is_absolute_url(self, name_or_url: str) -> bool:
        n = (name_or_url or "").strip().lower()
        return n.startswith("http://") or n.startswith("https://")

    def _from_api_routes(self, api_name: str) -> Tuple[str, Optional[str], Dict[str, str]]:
        routes = self.api_routes.get("routes") or self.api_routes
        if not isinstance(routes, dict):
            return "", None, {}
        cfg = routes.get(api_name) or {}
        url = (cfg.get("url") or cfg.get("endpoint") or "").strip()
        method = (cfg.get("method") or "").strip().upper() or None
        headers = cfg.get("headers") or {}
        return url, method, headers

    # -------------------- Per-step auth --------------------

    def _apply_step_auth(
        self,
        step: Dict[str, Any],
        headers: Dict[str, str]
    ) -> Tuple[Optional[HTTPBasicAuth], Dict[str, str]]:
        """
        Retorna (http_basic_auth, headers_atualizados_com_bearer_se_existir)
        """
        auth_cfg = step.get("auth") or {}
        auth_type = (auth_cfg.get("type") or "none").lower()
        per_env = bool(auth_cfg.get("per_env", False))

        # clone headers para não poluir o que veio da session
        final_headers = dict(headers or {})

        if auth_type == "bearer":
            token_map = auth_cfg.get("bearer") or {}
            token = None
            if per_env:
                token = token_map.get(self.current_env)
            else:
                token = token_map.get("DEFAULT") or token_map.get(self.current_env)
            if token and "Authorization" not in {k.title(): v for k, v in final_headers.items()}:
                final_headers["Authorization"] = f"Bearer {token}"
            return None, final_headers

        if auth_type == "basic":
            basic_map = auth_cfg.get("basic") or {}
            creds = None
            if per_env:
                creds = basic_map.get(self.current_env) or {}
            else:
                creds = basic_map.get("DEFAULT") or basic_map.get(self.current_env) or {}
            user = creds.get("user")
            pwd = creds.get("password")
            if user and pwd:
                return HTTPBasicAuth(user, pwd), final_headers
            return None, final_headers

        # none -> usa auth da Session (se houver)
        return None, final_headers

    # -------------------- HTTP call --------------------

    def _call(self, method: str, url: str, params: Dict[str, Any], json_body: Any,
              headers: Dict[str, str], basic_auth: Optional[HTTPBasicAuth]):
        if method == "GET":
            return self.session.get(url, params=params or {}, headers=headers, auth=basic_auth, timeout=180, verify=self.session.verify)
        elif method in ("POST", "PUT", "PATCH", "DELETE"):
            return self.session.request(method, url, params=params or {}, json=json_body, headers=headers, auth=basic_auth, timeout=180, verify=self.session.verify)
        else:
            raise ValueError(f"Método HTTP não suportado: {method}")

    def _parse_body(self, resp: requests.Response) -> Any:
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "application/json" in ct:
            try:
                return resp.json()
            except Exception:
                try:
                    return json.loads(resp.text)
                except Exception:
                    return resp.text
        return resp.text

    # -------------------- Execução (nova estrutura) --------------------

    def _run_step_new(self, step: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        step novo formato:
          tipo/nome/metodo/url|url_por_ambiente/params/headers/payload|payload_por_ambiente/auth/variaveis
        """
        nome = (step.get("nome") or "").strip() or "(sem-nome)"
        method = (step.get("metodo") or "GET").strip().upper()

        # URL (suporta por ambiente)
        if "url_por_ambiente" in step and isinstance(step["url_por_ambiente"], dict):
            raw_url = step["url_por_ambiente"].get(self.current_env, "")
        else:
            raw_url = step.get("url", "")

        # Params / Headers / Payload (suporta payload por ambiente)
        raw_params = step.get("params", {}) or {}
        raw_headers = step.get("headers", {}) or {}

        if "payload_por_ambiente" in step and isinstance(step["payload_por_ambiente"], dict):
            raw_payload = step["payload_por_ambiente"].get(self.current_env, {})
        else:
            raw_payload = step.get("payload", {})

        # Substitui {{variavel}} em tudo com base no contexto acumulado
        url = _substitute_templates(raw_url, ctx)
        params = _substitute_templates(raw_params, ctx)
        headers = _substitute_templates(raw_headers, ctx)
        payload = _substitute_templates(raw_payload, ctx)

        # headers precisam ser str
        headers = {str(k): str(v) for k, v in (headers or {}).items()}

        # Auth do passo (bearer/basic por ambiente)
        basic_auth, headers = self._apply_step_auth(step, headers)

        # Chamada HTTP
        resp = self._call(method, url, params, payload if method != "GET" else None, headers, basic_auth)
        resp_data = self._parse_body(resp)

        # Extrai variáveis do response e guarda no contexto
        for var in step.get("variaveis", []) or []:
            nome_var = (var.get("nome") or "").strip()
            origem = (var.get("origem") or "").strip()
            if not nome_var or not origem:
                continue
            valor = _get_value_from_path(resp_data, origem)
            ctx[nome_var] = valor

        return {
            "step": nome,
            "method": method,
            "url": url,
            "status_code": resp.status_code,
            "response": _jsonish(resp_data),
        }

    # -------------------- Execução (legacy) --------------------

    def _run_step_legacy(self, step: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        api_name = step.get("api_name")
        tipo_acao = (step.get("tipo_acao") or "GET").strip().upper()
        payload = step.get("payload", {}) or {}
        step_headers = step.get("headers", {}) or {}

        if not api_name:
            return {"step": "(legacy sem api_name)", "status_code": None, "error": "Passo sem 'api_name'."}

        # resolve url/method/headers
        headers: Dict[str, str] = dict(self.session.headers or {})
        if self._is_absolute_url(api_name):
            url = api_name.strip()
            method = tipo_acao
        else:
            url_routes, method_routes, headers_routes = self._from_api_routes(api_name)
            if not url_routes:
                url_routes = f"{self.base_url.rstrip('/')}/{api_name.lstrip('/')}"
            url = url_routes
            method = tipo_acao or method_routes or "GET"
            headers.update(headers_routes or {})
        headers.update(step_headers or {})
        headers = {k: str(v) for k, v in headers.items()}

        # substituição de {{variavel}} também vale no modo legacy
        url = _substitute_templates(url, ctx)
        payload = _substitute_templates(payload, ctx)
        headers = _substitute_templates(headers, ctx)
        headers = {k: str(v) for k, v in headers.items()}

        # chamada
        resp = self._call(method, url, {}, payload if method != "GET" else None, headers, None)
        resp_data = self._parse_body(resp)

        # legacy não tem 'variaveis' no passo — nada a extrair
        return {
            "step": api_name,
            "method": method,
            "url": url,
            "status_code": resp.status_code,
            "response": _jsonish(resp_data),
        }

    # -------------------- API pública --------------------

    def run_fluxo(self, fluxo_name: str, quantidade: int = 1) -> List[Dict[str, Any]]:
        """
        Executa N vezes o fluxo `fluxo_name`.
        - Suporta nova estrutura de etapas (tipo=api) e legacy.
        - Mantém um contexto de variáveis entre as etapas (e entre repetições é limpo).
        """
        passos = self.fluxos.get(fluxo_name, [])
        if not isinstance(passos, list) or not passos:
            raise ValueError(f"Fluxo '{fluxo_name}' não encontrado ou sem passos.")

        resultados: List[Dict[str, Any]] = []

        for _ in range(int(quantidade or 1)):
            contexto: Dict[str, Any] = {}
            exec_result: Dict[str, Any] = {}

            for step in passos:
                try:
                    if step.get("tipo") == "api" or step.get("metodo") or step.get("url") or step.get("url_por_ambiente"):
                        out = self._run_step_new(step, contexto)
                        key = out.get("step") or out.get("url")
                        exec_result[key] = out
                    else:
                        # legacy
                        out = self._run_step_legacy(step, contexto)
                        key = out.get("step") or out.get("url")
                        exec_result[key] = out
                except Exception as e:
                    key = (step.get("nome") or step.get("api_name") or "(erro)") or "(erro)"
                    exec_result[key] = {"status_code": None, "error": str(e)}

            resultados.append(exec_result)

        return resultados
