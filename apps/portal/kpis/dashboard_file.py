import streamlit as st
from pathlib import Path
import datetime
import os

BASE_DIR = Path("config/database")

def _human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.1f} {u}"
        size /= 1024

def _list_csv_files(directory: Path):
    if not directory.exists():
        return []
    # Somente arquivos .csv na RAIZ de config/database (sem subpastas)
    files = [p for p in directory.glob("*.csv") if p.is_file()]
    # Ordena por data de modificação (desc)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files

def pagina_dashboard_file():
    st.title("📦 Arquivos CSV – Banco Local (config/database)")
    st.caption(f"Pasta monitorada: `{BASE_DIR.resolve()}`")

    # Botão de refresh (útil quando novos CSVs aparecem durante a sessão)
    if st.button("🔄 Atualizar lista"):
        st.rerun()

    if not BASE_DIR.exists():
        st.info(
            "A pasta `config/database` ainda não existe neste ambiente. "
            "Ela será criada automaticamente quando as extrações gerarem arquivos."
        )
        return

    csv_files = _list_csv_files(BASE_DIR)

    if not csv_files:
        st.info(
            "Nenhum arquivo **.csv** encontrado em `config/database` por enquanto. "
            "Assim que as execuções (Jira/Zephyr) salvarem resultados, eles aparecerão aqui."
        )
        return

    st.subheader(f"Encontrados {len(csv_files)} arquivo(s)")
    for p in csv_files:
        stat = p.stat()
        mod = datetime.datetime.fromtimestamp(stat.st_mtime)
        size = _human_size(stat.st_size)

        c1, c2, c3, c4 = st.columns([0.50, 0.18, 0.18, 0.14])
        with c1:
            st.markdown(f"**{p.name}**")
            st.caption(p.resolve().as_posix())
        with c2:
            st.text("Tamanho")
            st.write(size)
        with c3:
            st.text("Modificado em")
            st.write(mod.strftime("%d/%m/%Y %H:%M:%S"))
        with c4:
            # Usa um key único baseado no nome e mtime
            key = f"dl_{p.name}_{int(stat.st_mtime)}"
            with open(p, "rb") as f:
                st.download_button(
                    "⬇️ Baixar",
                    data=f.read(),
                    file_name=p.name,
                    mime="text/csv",
                    use_container_width=True,
                    key=key
                )
        st.divider()

# Execução direta (se rodar este arquivo como app)
if __name__ == "__main__":
    pagina_dashboard_file()
