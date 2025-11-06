import os
from pathlib import Path
import pandas as pd
import streamlit as st
from .constants import DATA

def _first_existing(file_candidates):
    """Retorna o primeiro arquivo existente e não-vazio dentro de DATA."""
    for name in ([file_candidates] if isinstance(file_candidates, str) else file_candidates):
        p = (DATA / name)
        if p.exists() and p.stat().st_size > 0:
            return p
    return None

@st.cache_data(show_spinner=False)
def _load_csv_cached(path: str, mtime: int, columns=None) -> pd.DataFrame:
    """Carregador cacheado por mtime do arquivo."""
    df = pd.read_csv(path)
    if columns:
        for c in columns:
            if c not in df.columns:
                df[c] = pd.NA
        df = df[[c for c in columns if c in df.columns]]
    return df

def safe_read_csv(file_candidates, columns=None) -> pd.DataFrame:
    """
    Igual à sua função atual, porém cacheada por mtime.
    - Sem arquivo → DataFrame vazio com colunas pedidas.
    - Com arquivo → leitura com cache que invalida ao trocar o arquivo.
    """
    p = _first_existing(file_candidates)
    if not p:
        return pd.DataFrame(columns=columns or [])
    try:
        return _load_csv_cached(str(p), int(p.stat().st_mtime), columns)
    except Exception:
        return pd.DataFrame(columns=columns or [])

def read_last_update(last_update_name: str) -> str | None:
    """Lê uma célula de timestamp do marcador de atualização (quando existir)."""
    p = _first_existing(last_update_name)
    if not p:
        return None
    try:
        return str(pd.read_csv(p).iloc[0, 0])
    except Exception:
        return None
