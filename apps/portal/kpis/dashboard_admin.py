import streamlit as st
import yaml
import os
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

AGENDAMENTOS_FILE = 'config/kpis_agendamentos.yaml'
TZ = ZoneInfo("America/Sao_Paulo")

# ----------------- Utils YAML -----------------
def salvar_agendamentos(agendamentos):
    with open(AGENDAMENTOS_FILE, 'w', encoding="utf-8") as f:
        yaml.dump(agendamentos, f, allow_unicode=True, sort_keys=False)

def carregar_agendamentos():
    """Carrega e NORMALIZA com persistência (id, enabled, dias_semana, created_at, quantidade)."""
    changed = False
    if os.path.exists(AGENDAMENTOS_FILE):
        with open(AGENDAMENTOS_FILE, 'r', encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
    else:
        data = []

    for it in data:
        if "id" not in it or not it.get("id"):
            it["id"] = str(uuid.uuid4())
            changed = True
        if "enabled" not in it:
            it["enabled"] = True
            changed = True
        if "dias_semana" not in it or not it.get("dias_semana"):
            it["dias_semana"] = ["Todos"]
            changed = True
        if "created_at" not in it:
            it["created_at"] = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
            changed = True
        if "quantidade" not in it:
            it["quantidade"] = 1
            changed = True

    if changed:
        salvar_agendamentos(data)

    return data

# ----------------- Validações -----------------
DIAS_VALIDOS = ["Todos", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
MAP_PT_WEEKDAY = {"Segunda": 0, "Terça": 1, "Quarta": 2, "Quinta": 3, "Sexta": 4, "Sábado": 5, "Domingo": 6}

def parse_hhmm(hhmm: str) -> time | None:
    try:
        hh, mm = hhmm.strip().split(":")
        hh, mm = int(hh), int(mm)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return time(hour=hh, minute=mm, tzinfo=TZ)
    except Exception:
        pass
    return None

def dias_validos(dias):
    return bool(dias) and all(d in DIAS_VALIDOS for d in dias)

def is_duplicate(existing, fluxo, horario, dias, skip_id=None):
    """Evita dois agendamentos idênticos para o mesmo fluxo (mesmo horário + mesmos dias)."""
    probe = (fluxo or "").strip(), (horario or "").strip(), tuple(sorted(dias or []))
    for it in existing:
        if skip_id and it.get("id") == skip_id:
            continue
        key = (it.get("fluxo_name","").strip(), it.get("horario","").strip(), tuple(sorted(it.get("dias_semana") or [])))
        if key == probe:
            return True
    return False

# ----------------- Próximo disparo (preview) -----------------
def _weekday_matches(dias_semana, dt: datetime) -> bool:
    if "Todos" in (dias_semana or []):
        return True
    return dt.weekday() in {MAP_PT_WEEKDAY[d] for d in dias_semana if d in MAP_PT_WEEKDAY}

def proximo_disparo(dias_semana, hhmm: str, now: datetime | None = None) -> datetime | None:
    if not parse_hhmm(hhmm) or not dias_validos(dias_semana):
        return None
    now = now or datetime.now(TZ)
    hh, mm = map(int, hhmm.split(":"))
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    for i in range(0, 14):  # procura até 2 semanas
        dt = candidate + timedelta(days=i if candidate < now else 0)
        if dt < now:
            dt = dt + timedelta(days=1)
        for _ in range(7):
            if _weekday_matches(dias_semana, dt):
                if dt >= now:
                    return dt
            dt = dt + timedelta(days=1)
    return None

# ----------------- Página -----------------
def pagina_dashboardo_admin():
    st.title("🗓️ Administração de Agendamentos – KPI (Jira/Zephyr)")

    # Estado de edição único
    if "editing_id" not in st.session_state:
        st.session_state["editing_id"] = None

    agendamentos = carregar_agendamentos()

    st.subheader("📋 Agendamentos Existentes")
    if not agendamentos:
        st.warning("Nenhum agendamento encontrado.")
        return

    for idx, ag in enumerate(agendamentos):
        prox = proximo_disparo(ag.get("dias_semana",["Todos"]), ag.get("horario",""))
        status = "🟢 Ativo" if ag.get("enabled", True) else "⚪ Desativado"
        subtitle = f"({status}) – Próximo: {prox.strftime('%d/%m %H:%M') if prox else '—'}"
        with st.expander(f"{idx+1}. {ag.get('fluxo_name','(sem nome)')} {subtitle}", expanded=False):
            c1, c2, c3, c4 = st.columns([0.28, 0.22, 0.22, 0.28])
            with c1:
                st.markdown(f"**Fluxo:** `{ag.get('fluxo_name','')}`")
            with c2:
                st.markdown(f"**Quantidade:** `{ag.get('quantidade','')}`")
            with c3:
                st.markdown(f"**Horário:** `{ag.get('horario','')}`")
            with c4:
                st.markdown("**Dias:** " + ", ".join(ag.get("dias_semana", [])))

            # ---- Habilitar ----
            col_a, col_b = st.columns([0.3, 0.7])
            with col_a:
                new_state = st.toggle("Habilitado", value=ag.get("enabled", True), key=f"toggle_{ag['id']}")
                if new_state != ag.get("enabled", True):
                    agendamentos[idx]["enabled"] = new_state
                    salvar_agendamentos(agendamentos)
                    st.success("Estado atualizado!")
                    st.rerun()

            # ---- Editar ----
            with col_b:
                if st.button("✏️ Editar", key=f"edit_{ag['id']}"):
                    st.session_state["editing_id"] = ag["id"]  # mantém entre reruns

            # ------ Form de edição (somente para o item clicado) -------
            if st.session_state.get("editing_id") == ag["id"]:
                st.markdown("---")
                st.markdown("**Editar agendamento**")

                with st.form(f"form_edit_{ag['id']}"):
                    # Fluxo e Quantidade: somente leitura
                    st.text_input("Fluxo (somente leitura)", value=ag.get("fluxo_name",""), disabled=True)
                    st.text_input("Quantidade (somente leitura)", value=str(ag.get("quantidade", 1)), disabled=True)

                    # Campos editáveis
                    horario = st.text_input("Horário (HH:MM)", value=ag.get("horario",""))
                    dias = st.multiselect("Dias da Semana", DIAS_VALIDOS, default=ag.get("dias_semana",["Todos"]))

                    csa, csb = st.columns([0.3, 0.7])
                    with csa:
                        salvar = st.form_submit_button("Salvar alterações ✅")
                    with csb:
                        cancelar = st.form_submit_button("Cancelar")

                if salvar:
                    fluxo = ag.get("fluxo_name","")
                    if not parse_hhmm(horario):
                        st.error("Formato de horário inválido. Use HH:MM (24h).")
                    elif not dias_validos(dias):
                        st.error("Selecione dias válidos.")
                    elif is_duplicate(agendamentos, fluxo, horario, dias, skip_id=ag["id"]):
                        st.error("Já existe um agendamento idêntico para este fluxo.")
                    else:
                        ag.update({
                            # quantidade NÃO é alterada aqui
                            "horario": horario,
                            "dias_semana": dias
                        })
                        salvar_agendamentos(agendamentos)
                        st.success("Agendamento atualizado!")
                        st.session_state["editing_id"] = None
                        st.rerun()

                if cancelar:
                    st.session_state["editing_id"] = None
                    st.info("Edição cancelada.")
                    st.rerun()

    # ✅ Sem criar novo agendamento
    # ✅ Sem excluir
    # ✅ Sem executar agora
    # ✅ Quantidade somente leitura

# Runner local
if __name__ == "__main__":
    pagina_dashboardo_admin()
