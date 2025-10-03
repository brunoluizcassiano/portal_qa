# -*- coding: utf-8 -*-
"""
Scheduler unificado (MASSA + KPI)
Lê dois arquivos de agendamento (SCHEDULE_FILE e SCHEDULE_KPI_FILE) e grava em históricos distintos
(HIST_FILE e HIST_KPI_FILE). Suporta itens com `servico` ou com `endpoint`.

ENV:
  SCHEDULE_FILE       = config/massai_agendamentos.yaml
  HIST_FILE           = config/massai_historico_execucoes.yaml
  SCHEDULE_KPI_FILE   = config/kpis_agendamentos.yaml
  HIST_KPI_FILE       = config/kpis_historico_execucoes.yaml
  API_URL             = http://massai-api:8000
  POLL_INTERVAL       = 60
  TOL_MIN             = 1
  TZ                  = America/Sao_Paulo
"""

import os
import time
import json
import yaml
import requests
import tempfile
import datetime
import csv
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# =================== Config / ENV ===================

SCHEDULE_FILE       = os.getenv("SCHEDULE_FILE", "config/massai_agendamentos.yaml")        # MASSA
HIST_FILE           = os.getenv("HIST_FILE", "config/massai_historico_execucoes.yaml")     # MASSA
SCHEDULE_KPI_FILE   = os.getenv("SCHEDULE_KPI_FILE")                                       # KPI (opcional)
HIST_KPI_FILE       = os.getenv("HIST_KPI_FILE", "config/kpis_historico_execucoes.yaml")   # KPI
POLL_INTERVAL       = int(os.getenv("POLL_INTERVAL", "60"))
TOL_MIN             = int(os.getenv("TOL_MIN", "1"))
TZ_NAME             = os.getenv("TZ", "America/Sao_Paulo")

if ZoneInfo:
    TZ = ZoneInfo(TZ_NAME)
else:
    TZ = None

def _write_last_update_csv(dt: datetime.datetime, path_str: str = "config/database/lastUpdate.csv"):
    """Cria/atualiza um CSV de 1 coluna com a data/hora da última execução (Jira/Zephyr)."""
    path = _ensure_parent(Path(path_str))  # garante config/database/
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["last_update"])
        w.writerow([dt.strftime("%d/%m/%Y %H:%M:%S")])  # formato DD/MM/AAAA HH:MM:SS

def _carregar_api_url_default():
    api_url = "http://massai-api:8000"
    try:
        if os.path.exists("config/settings.yaml"):
            with open("config/settings.yaml", "r", encoding="utf-8") as f:
                settings = yaml.safe_load(f) or {}
            if isinstance(settings, dict):
                api_url = settings.get("api_url", api_url)
    except Exception as e:
        print(f"[WARN] Falha lendo config/settings.yaml: {e}", flush=True)
    return os.getenv("API_URL", api_url)

API_URL = _carregar_api_url_default()

# =================== Utils arquivo ===================

def _ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def _atomic_yaml_write(path: Path, data):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, str(path))
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

# =================== Leitura/Normalização ===================

DIAS_VALIDOS = {"Todos","Segunda","Terça","Quarta","Quinta","Sexta","Sábado","Domingo"}

def _carregar_lista(path: str) -> list:
    if not path:
        return []
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[WARN] Falha lendo {path}: {e}", flush=True)
        return []

def _normalize_items(data: list, default_hist_file: str, source_key: str) -> list:
    """
    Normaliza itens e anota metadados:
      - hist_file: para onde escrever o histórico desse item
      - source: 'MASSA' ou 'KPI' (ou outro label)
    Aceita formatos com `servico` ou com `endpoint`.
    """
    out = []
    for it in data:
        if not isinstance(it, dict):
            continue
        fluxo = (it.get("fluxo_name") or it.get("fluxo") or "").strip()
        hhmm  = (it.get("horario") or "").strip()
        if not fluxo or not hhmm:
            continue

        dias  = it.get("dias_semana") or ["Todos"]
        if not isinstance(dias, list) or not all(d in DIAS_VALIDOS for d in dias):
            dias = ["Todos"]

        out.append({
            "fluxo_name": fluxo,
            "horario": hhmm,
            "dias_semana": dias,
            "quantidade": int(it.get("quantidade", 1)),
            "enabled": bool(it.get("enabled", True)),

            # compat
            "servico": (it.get("servico") or "").strip().lower(),
            "endpoint": (it.get("endpoint") or "").strip(),
            "api_url": (it.get("api_url") or API_URL).strip(),

            # metadata
            "hist_file": default_hist_file,
            "source": source_key,
        })
    return out

def carregar_agendamentos_unificados() -> list:
    massa_raw = _carregar_lista(SCHEDULE_FILE)
    kpi_raw   = _carregar_lista(SCHEDULE_KPI_FILE) if SCHEDULE_KPI_FILE else []

    massa = _normalize_items(massa_raw, HIST_FILE, "MASSA")
    kpi   = _normalize_items(kpi_raw,   HIST_KPI_FILE, "KPI")

    all_items = massa + kpi
    return all_items

# =================== Datas/Horas ===================

DIAS_PT = {
    "Monday": "Segunda",
    "Tuesday": "Terça",
    "Wednesday": "Quarta",
    "Thursday": "Quinta",
    "Friday": "Sexta",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}
MAP_PT_WEEKDAY = {"Segunda":0,"Terça":1,"Quarta":2,"Quinta":3,"Sexta":4,"Sábado":5,"Domingo":6}

def traduzir_dia_en_pt(dia_ingles: str) -> str:
    return DIAS_PT.get(dia_ingles, dia_ingles)

def _weekday_matches(dias_semana, dt: datetime.datetime) -> bool:
    if "Todos" in (dias_semana or []):
        return True
    return dt.weekday() in {MAP_PT_WEEKDAY.get(d, -1) for d in dias_semana}

def horarios_compatíveis(hhmm: str, now: datetime.datetime, tolerancia_minutos: int) -> bool:
    try:
        hh, mm = [int(x) for x in hhmm.split(":")[:2]]
    except Exception:
        return False
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    delta_min = abs((now - target).total_seconds()) / 60.0
    return delta_min <= tolerancia_minutos

# =================== Endpoint / API ===================

def _resolver_base_url(item: dict) -> str:
    # 1) ENV API_URL (se setada) sobrepõe tudo
    if os.getenv("API_URL"):
        return os.getenv("API_URL")
    # 2) item.api_url
    if item.get("api_url"):
        return str(item["api_url"])
    # 3) settings/default
    return API_URL

def _resolver_endpoint(item: dict) -> str:
    ep = (item.get("endpoint") or "").strip()
    if ep:
        if not ep.startswith("/"): ep = "/" + ep
        if not ep.endswith("/"):   ep = ep + "/"
        return ep

    serv = (item.get("servico") or "").strip().lower()
    fluxo = (item.get("fluxo_name") or "").strip().lower()

    if serv == "zephyr":
        return "/run_zephyr/"
    if serv == "jira":
        if "sprint" in fluxo:
            return "/run_jira_sprint/"
        return "/run_jira_bases/"
    return "/run_fluxo/"

def _post_agendamento(base_url: str, endpoint: str, fluxo: str, quantidade: int, timeout: int = 180):
    url = f"{base_url.rstrip('/')}{endpoint}"
    payload = {"fluxo_name": fluxo, "quantidade": int(quantidade)}
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        return r, None
    except Exception as e:
        return None, str(e)

# =================== Histórico ===================

def _append_historico(item: dict, status: str, mensagem: str, endpoint: str):
    hist_path = item.get("hist_file") or HIST_FILE
    path = _ensure_parent(Path(hist_path))
    historico = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                historico = yaml.safe_load(f) or []
                if not isinstance(historico, list):
                    historico = []
        except Exception as e:
            print(f"[WARN] Falha lendo histórico para append: {e}", flush=True)

    reg = {
        "fluxo_name": item["fluxo_name"],
        "horario": item["horario"],
        "data": (datetime.datetime.now(TZ) if TZ else datetime.datetime.now()).strftime("%d/%m/%Y"),
        "status": status,                         # "Sucesso" | "Falha" | "HTTP 4xx/5xx"
        "mensagem": (mensagem or "")[:4000],
        "endpoint": endpoint,
        "api_url": item.get("api_url") or API_URL,
    }
    historico.append(reg)
    _atomic_yaml_write(path, historico)

# =================== Deduplicação ===================

EXECUCOES_REGISTRADAS = set()

def _chave_execucao(item: dict, now: datetime.datetime) -> str:
    # inclui origem/hist_file p/ não bloquear KPI x MASSA com mesmo fluxo/horário
    origem = item.get("source") or "UNK"
    hist   = item.get("hist_file") or ""
    return f"{origem}|{hist}|{item['fluxo_name']}|{item['horario']}|{now.strftime('%d/%m/%Y')}"

# =================== Worker ===================

def scheduler_worker():
    print("✅ Scheduler unificado iniciado", flush=True)
    print(f"   → MASSA:   SCHEDULE_FILE={SCHEDULE_FILE}  | HIST_FILE={HIST_FILE}", flush=True)
    print(f"   → KPI:     SCHEDULE_KPI_FILE={SCHEDULE_KPI_FILE}  | HIST_KPI_FILE={HIST_KPI_FILE}", flush=True)
    print(f"   → API base: {API_URL}", flush=True)
    print(f"   → Poll: {POLL_INTERVAL}s | Tolerância: ±{TOL_MIN} min | TZ: {TZ_NAME}", flush=True)

    while True:
        try:
            items = carregar_agendamentos_unificados()
            now = datetime.datetime.now(TZ) if TZ else datetime.datetime.now()
            dia_semana = traduzir_dia_en_pt(now.strftime("%A"))
            horario_atual = now.strftime("%H:%M")

            for it in items:
                if not it.get("enabled", True):
                    continue
                fluxo = it["fluxo_name"]
                hhmm  = it["horario"]
                dias  = it.get("dias_semana") or ["Todos"]
                qtd   = int(it.get("quantidade", 1))

                if "Todos" not in dias and dia_semana not in dias:
                    continue

                key = _chave_execucao(it, now)
                if key in EXECUCOES_REGISTRADAS:
                    continue
                if not horarios_compatíveis(hhmm, now, TOL_MIN):
                    continue

                base_url = _resolver_base_url(it)
                ep = _resolver_endpoint(it)
                endpoint_efetivo = ep

                print(f"[⏰] {it.get('source','?')} | {fluxo} @ {horario_atual} → {base_url}{ep}", flush=True)

                status = "Sucesso"
                mensagem = ""

                r, err = _post_agendamento(base_url, ep, fluxo, qtd)
                # fallback sprint → bases (se for o caso)
                if r and r.status_code == 404 and ep == "/run_jira_sprint/":
                    endpoint_efetivo = "/run_jira_bases/"
                    r, err = _post_agendamento(base_url, endpoint_efetivo, fluxo, qtd)

                if r and r.status_code < 400:
                    mensagem = (r.text or "")[:1500]
                    print(f"[OK] HTTP {r.status_code} para {fluxo}", flush=True)
                else:
                    status = f"HTTP {r.status_code}" if r else "Falha"
                    mensagem = (r.text if r else err) or ""
                    mensagem = mensagem[:1500]
                    print(f"[ERRO] {fluxo}: {status} | {mensagem}", flush=True)

                _append_historico(it, status, mensagem, endpoint_efetivo)
                EXECUCOES_REGISTRADAS.add(key)

                # >>> ATUALIZA lastUpdate.csv quando for Jira/Zephyr **e** sucesso
                is_jira_zephyr = (it.get("servico") in ("jira", "zephyr")) \
                                or ("jira" in it["fluxo_name"].lower()) \
                                or ("zephyr" in it["fluxo_name"].lower())

                if is_jira_zephyr and status == "Sucesso":
                    _write_last_update_csv(now)

        except Exception as e:
            print(f"[FATAL] Erro no loop principal: {e}", flush=True)

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    try:
        scheduler_worker()
    except KeyboardInterrupt:
        print("Encerrando scheduler…", flush=True)
