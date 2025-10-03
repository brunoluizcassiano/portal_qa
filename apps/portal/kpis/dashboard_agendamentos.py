import streamlit as st
import yaml
import datetime
import os
import requests
from zoneinfo import ZoneInfo
import json
from pathlib import Path

AGENDAMENTOS_FILE = 'config/kpis_agendamentos.yaml'
# **Respeita HIST_FILE** se vier do ambiente; caso contrário, usa o padrão KPI:
HISTORICO_EXECUCOES_FILE = os.getenv('HIST_KPI_FILE', 'config/kpis_historico_execucoes.yaml')
TZ = ZoneInfo("America/Sao_Paulo")

DIAS_PT = {
    "Monday": "Segunda",
    "Tuesday": "Terça",
    "Wednesday": "Quarta",
    "Thursday": "Quinta",
    "Friday": "Sexta",
    "Saturday": "Sábado",
    "Sunday": "Domingo"
}
MAP_PT_WEEKDAY = {"Segunda":0,"Terça":1,"Quarta":2,"Quinta":3,"Sexta":4,"Sábado":5,"Domingo":6}

def carregar_agendamentos():
    if os.path.exists(AGENDAMENTOS_FILE):
        with open(AGENDAMENTOS_FILE, 'r', encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
    else:
        data = []
    for it in data:
        it.setdefault("enabled", True)
        it.setdefault("dias_semana", ["Todos"])
    return data

def carregar_historico_execucoes():
    if os.path.exists(HISTORICO_EXECUCOES_FILE):
        with open(HISTORICO_EXECUCOES_FILE, 'r', encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
            if isinstance(data, list):
                return data
            # tolera formato alternativo {historico: []}
            if isinstance(data, dict) and isinstance(data.get("historico"), list):
                return data["historico"]
    return []

def salvar_execucao_historico(execucao: dict):
    # garante que a pasta existe
    os.makedirs(os.path.dirname(HISTORICO_EXECUCOES_FILE), exist_ok=True)

    historico = []
    if os.path.exists(HISTORICO_EXECUCOES_FILE):
        with open(HISTORICO_EXECUCOES_FILE, 'r', encoding="utf-8") as f:
            historico = yaml.safe_load(f) or []
            if not isinstance(historico, list):
                historico = []

    historico.append(execucao)

    with open(HISTORICO_EXECUCOES_FILE, 'w', encoding="utf-8") as f:
        yaml.dump(historico, f, allow_unicode=True, sort_keys=False)

def traduzir_dia_en_pt(dia_ingles):
    return DIAS_PT.get(dia_ingles, dia_ingles)

def parse_hhmm(hhmm: str):
    try:
        hh, mm = hhmm.strip().split(":")
        hh, mm = int(hh), int(mm)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh, mm
    except Exception:
        pass
    return None

def weekday_matches(dias_semana, dt):
    if "Todos" in (dias_semana or []):
        return True
    return dt.weekday() in {MAP_PT_WEEKDAY.get(d, -1) for d in dias_semana}

def proximo_disparo(dias_semana, horario, now=None):
    p = parse_hhmm(horario)
    if not p:
        return None
    now = now or datetime.datetime.now(TZ)
    hh, mm = p
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate < now:
        candidate = candidate + datetime.timedelta(days=1)
    for i in range(14):
        dt = candidate + datetime.timedelta(days=i)
        if weekday_matches(dias_semana, dt):
            return dt
    return None

# ---------- Helpers de data/hora para o histórico ----------
def _parse_data_str(data_str: str):
    if not data_str:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(data_str.strip(), fmt).date()
        except Exception:
            continue
    return None

def _parse_horario_str(h_str: str):
    if not h_str:
        return (0, 0, 0)
    try:
        parts = [int(p) for p in h_str.strip().split(":")]
        if len(parts) == 2:
            return parts[0], parts[1], 0
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2]
    except Exception:
        pass
    return (0, 0, 0)

def _dt_execucao(item: dict) -> datetime.datetime:
    """Retorna datetime tz-aware a partir de item {'data': 'DD/MM/AAAA', 'horario': 'HH:MM[:SS]'}.
       Se não conseguir, retorna epoch (para ficar no fim da ordenação)."""
    d = _parse_data_str(item.get("data"))
    hh, mm, ss = _parse_horario_str(item.get("horario"))
    if d:
        return datetime.datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=TZ)
    # fallback: se não tem data, empurra pro passado
    return datetime.datetime(1970, 1, 1, 0, 0, 0, tzinfo=TZ)

# ---------- API helpers ----------
def _resolver_api_url() -> str:
    api = os.getenv("API_URL")
    if api:
        return api
    try:
        if os.path.exists("config/settings.yaml"):
            with open("config/settings.yaml", "r", encoding="utf-8") as f:
                s = yaml.safe_load(f) or {}
            if isinstance(s, dict) and s.get("api_url"):
                return str(s["api_url"])
    except Exception:
        pass
    return "http://massai-api:8000"

def _pretty_error(r: requests.Response) -> str:
    try:
        return json.dumps(r.json(), ensure_ascii=False, indent=2)[:1500]
    except Exception:
        return (r.text or "")[:1500]

def _post_agendamento(base_url: str, endpoint: str, fluxo_name: str, quantidade: int, timeout: int = 180):
    url = base_url.rstrip("/") + endpoint
    r = requests.post(url, json={"fluxo_name": fluxo_name, "quantidade": int(quantidade)}, timeout=timeout)
    return url, r

def executar_jira_agora():
    base = _resolver_api_url()
    endpoints = ["/run_jira_bases", "/run_fluxo", "/run_jira_bases/"]
    last = None
    for ep in endpoints:
        try:
            url, r = _post_agendamento(base, ep, "jira_bases", 1)
            if r.status_code < 400:
                salvar_execucao_historico({
                        "fluxo_name": "extracao_jira_bases",
                        "horario": datetime.datetime.now(TZ).strftime("%H:%M:%S"),
                        "data": datetime.datetime.now(TZ).strftime("%d/%m/%Y"),
                        "status": "Sucesso" if r.status_code == 200 else f"HTTP {r.status_code}",
                        "mensagem": (r.text or "")[:2000],
                        "endpoint": ep if ep.endswith("/") else ep + "/",
                        "api_url": base
                })
                return ep, r
            last = f"{url} -> {r.status_code}\n{_pretty_error(r)}"
        except Exception as e:
            last = f"{ep} -> ERR {e}"
    raise RuntimeError(last or "Nenhum endpoint de JIRA respondeu.")

def executar_zephyr_agora():
    base = _resolver_api_url()
    endpoints = ["/run_zephyr", "/run_fluxo", "/run_zephyr/"]
    last = None
    for ep in endpoints:
        try:
            url, r = _post_agendamento(base, ep, "zephyr_bases", 1)
            if r.status_code < 400:
                salvar_execucao_historico({
                    "fluxo_name": "extracao_zephyr_diaria",
                    "horario": datetime.datetime.now(TZ).strftime("%H:%M:%S"),
                    "data": datetime.datetime.now(TZ).strftime("%d/%m/%Y"),
                    "status": "Sucesso" if r.status_code == 200 else f"HTTP {r.status_code}",
                    "mensagem": (r.text or "")[:2000],
                    "endpoint": ep if ep.endswith("/") else ep + "/",
                    "api_url": base
                })
                return ep, r
            last = f"{url} -> {r.status_code}\n{_pretty_error(r)}"
        except Exception as e:
            last = f"{ep} -> ERR {e}"
    raise RuntimeError(last or "Nenhum endpoint de ZEPHYR respondeu.")

def pagina_dashboard_agendamentos():
    st.title("📅 Status de Agendamentos – Extração (Jira/Zephyr)")

    st.markdown(
        "Nesta página você pode visualizar os agendamentos configurados para extração de dados do Jira/Zephyr, "
        "ver os próximos disparos previstos e o histórico de execuções realizadas.\n\n"
        "Use os filtros para ajustar a visualização conforme necessário."
    )

    agendamentos = carregar_agendamentos()
    historico = carregar_historico_execucoes()

    now = datetime.datetime.now(TZ)
    dia_semana = traduzir_dia_en_pt(now.strftime("%A"))

    if not agendamentos:
        st.warning("Nenhum agendamento configurado.")
        return

    # Filtro por fluxo (se existir)
    fluxos_lista = sorted({a.get("fluxo_name","") for a in agendamentos if a.get("fluxo_name")})
    c1, c2 = st.columns([0.5,0.5])
    with c1:
        filtro_fluxo = st.selectbox("Filtrar por Fluxo", options=["Todos"] + fluxos_lista, index=0)
    with c2:
        st.caption(now.strftime("Atualizado: %d/%m/%Y %H:%M"))

    # ---------------- Agendamentos do Dia ----------------
    st.subheader("✅ Agendamentos do Dia")
    count_dia = 0
    for ag in agendamentos:
        if not ag.get("enabled", True):
            continue
        if filtro_fluxo != "Todos" and ag.get("fluxo_name") != filtro_fluxo:
            continue
        dias = ag.get('dias_semana', ["Todos"])
        if "Todos" not in dias and dia_semana not in dias:
            continue
        count_dia += 1
        st.info(f"📝 **Fluxo:** {ag.get('fluxo_name')}  |  🕑 **Horário:** {ag.get('horario')}  |  📅 **Dias:** {', '.join(dias)}")

    if count_dia == 0:
        st.info("Nenhum agendamento para hoje com os filtros atuais.")

    st.divider()

    # ---------------- Próximos disparos (prévia) ----------------
    st.subheader("⏭️ Próximos Disparos (prévia)")
    rows = []
    for ag in agendamentos:
        if not ag.get("enabled", True):
            continue
        if filtro_fluxo != "Todos" and ag.get("fluxo_name") != filtro_fluxo:
            continue
        nx = proximo_disparo(ag.get("dias_semana",["Todos"]), ag.get("horario",""), now)
        rows.append({
            "Fluxo": ag.get("fluxo_name"),
            "Horário": ag.get("horario"),
            "Dias": ", ".join(ag.get("dias_semana",[])),
            "Próximo": nx.strftime("%d/%m/%Y %H:%M") if nx else "—"
        })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum próximo disparo encontrado para os filtros atuais.")

    st.divider()

    # ---------------- Histórico (hoje e últimos) ----------------
    st.subheader("📈 Histórico de Execuções")
    if not historico:
        st.info("Nenhuma execução realizada ainda.")
        return

    # aplica filtro de fluxo (se houver)
    if filtro_fluxo != "Todos":
        historico = [h for h in historico if h.get("fluxo_name") == filtro_fluxo]

    # Ordena **por datetime real**, mais recente primeiro
    historico_sorted = sorted(historico, key=_dt_execucao, reverse=True)

    # HOJE (por datetime real)
    hoje_date = now.date()
    historico_hoje_sorted = [h for h in historico_sorted if _dt_execucao(h).date() == hoje_date]

    if historico_hoje_sorted:
        st.markdown("**Hoje (mais recentes primeiro)**")
        for execucao in historico_hoje_sorted:
            status_emoji = "🟢" if execucao.get("status") == "Sucesso" else "🔴"
            st.markdown(
                f"**Fluxo:** {execucao.get('fluxo_name','—')}  \n"
                f"**Horário Executado:** {execucao.get('horario','—')}  \n"
                f"**Status:** {status_emoji} {execucao.get('status','—')}"
            )
            st.markdown("---")
    else:
        st.info("Nenhuma execução para hoje ainda.")

    # ÚLTIMAS (não hoje), ordenadas por data/hora real (desc)
    outros_sorted = [h for h in historico_sorted if _dt_execucao(h).date() != hoje_date]
    if outros_sorted:
        st.markdown("**Últimas Execuções**")
        for execucao in outros_sorted[:50]:
            status_emoji = "🟢" if execucao.get("status") == "Sucesso" else "🔴"
            dt = _dt_execucao(execucao)
            st.markdown(
                f"*{dt.strftime('%d/%m/%Y %H:%M:%S')}* — **{execucao.get('fluxo_name','—')}** {status_emoji} {execucao.get('status','—')}"
            )

    if st.button("🔄 Atualizar Página"):
        st.rerun()

    # ---------------- Ações rápidas ----------------
    st.divider()
    st.subheader("⚡ Executar agora")
    cqa, cqb, cqc, cqd = st.columns([0.22, 0.22, 0.22, 0.34])
    with cqa:
        if st.button("▶️ Executar JIRA agora", use_container_width=True):
            try:
                ep, r = executar_jira_agora()
                st.success(f"JIRA OK ({ep}) — HTTP {r.status_code}")
                st.code((r.text or "")[:1500], language="json")
            except Exception as e:
                st.error(f"Falha ao executar JIRA: {e}")
        
    with cqb:
        if st.button("▶️ Executar ZEPHYR agora", use_container_width=True):
            try:
                ep, r = executar_zephyr_agora()
                st.success(f"ZEPHYR OK ({ep}) — HTTP {r.status_code}")
                st.code((r.text or "")[:1500], language="json")
            except Exception as e:
                st.error(f"Falha ao executar ZEPHYR: {e}")
        
    with cqc:
        st.caption("")
    with cqd:
        st.caption("")

# Runner local
if __name__ == "__main__":
    pagina_dashboard_agendamentos()
