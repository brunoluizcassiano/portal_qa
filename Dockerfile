# FROM artifactory.santanderbr.corp/registry/python:3.11-slim
# FROM 654654544680.dkr.ecr.us-east-1.amazonaws.com/python:3.10-slim
FROM python:3.11-slim

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV NO_PROXY=${NO_PROXY}
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/var/cache/pypoetry' \
    POETRY_HOME='/usr/local' \
    TZ=America/Sao_Paulo \
    PYTHONPATH=/app:/app/apps:/app/src
WORKDIR /app

# RUN pip install -U pip && pip install pipx --index-url http://artifactory.santanderbr.corp/artifactory/api/pypi/pypi-all/simple --trusted-host artifactory.santanderbr.corp
# RUN pip install -U pip && pip install pipx

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata curl && \
    rm -rf /var/lib/apt/lists/*

    # deps (se existir requirements.txt na raiz)
COPY requirements.txt /tmp/requirements.txt

RUN if [ -f /tmp/requirements.txt ]; then \
      # pip install --upgrade pip && pip install -r /tmp/requirements.txt --index-url http://artifactory.santanderbr.corp/artifactory/api/pypi/pypi-all/simple --trusted-host artifactory.santanderbr.corp; \
    pip install --upgrade pip && pip install -r /tmp/requirements.txt ; \
    else \
      # pip install --upgrade pip --index-url http://artifactory.santanderbr.corp/artifactory/api/pypi/pypi-all/simple --trusted-host artifactory.santanderbr.corp; \
    pip install --upgrade pip ; \
    fi

    # código
COPY . /app

# fallback de libs (caso não estejam no requirements)
RUN pip install --no-cache-dir fastapi uvicorn[standard] streamlit requests pyyaml tomli || true

# caminhos fixos conforme tua árvore
ENV APP_ROLE=api \
   API_HOST=0.0.0.0 \
   API_PORT=8000 \
   DASHBOARD_HOST=0.0.0.0 \
   DASHBOARD_PORT=8501 \
   API_APP_DIR=/app/apps/app \
   API_TARGET=main:app \
   DASHBOARD_APP_FILE=/app/apps/app.py

   # entrypoint (LF, sem CRLF)
RUN printf '%s\n' \
'#!/bin/sh' \
'set -e' \
'echo "[entrypoint] APP_ROLE=${APP_ROLE}"' \
'case "${APP_ROLE}" in' \
'  api)' \
'    export PYTHONPATH="/app:/app/apps:/app/src:${PYTHONPATH}"' \
'    if [ ! -f "${API_APP_DIR}/main.py" ]; then echo "ERRO: ${API_APP_DIR}/main.py não encontrado"; exit 1; fi' \
'    exec uvicorn "${API_TARGET}" --app-dir "${API_APP_DIR}" --host "${API_HOST}" --port "${API_PORT}" --proxy-headers --forwarded-allow-ips="*"' \
'    ;;' \
'  dashboard)' \
'    if [ ! -f "${DASHBOARD_APP_FILE}" ]; then echo "ERRO: ${DASHBOARD_APP_FILE} não encontrado"; exit 1; fi' \
'    exec streamlit run "${DASHBOARD_APP_FILE}" --server.address "${DASHBOARD_HOST}" --server.port "${DASHBOARD_PORT}"' \
'    ;;' \
'  all)' \
'    # inicia API em background' \
'    export PYTHONPATH="/app:/app/apps:/app/src:${PYTHONPATH}"' \
'    export API_URL="${API_URL:-http://127.0.0.1:8000}"' \
'    echo "→ API base (ALL) = ${API_URL}"' \
'    if [ ! -f "${API_APP_DIR}/main.py" ]; then echo "ERRO: ${API_APP_DIR}/main.py não encontrado"; exit 1; fi' \
'    uvicorn "${API_TARGET}" --app-dir "${API_APP_DIR}" --host "${API_HOST}" --port "${API_PORT}" --proxy-headers --forwarded-allow-ips="*" & ' \
'    API_PID=$!' \
'    # inicia Streamlit em foreground' \
'    if [ ! -f "${DASHBOARD_APP_FILE}" ]; then echo "ERRO: ${DASHBOARD_APP_FILE} não encontrado"; exit 1; fi' \
'    exec streamlit run "${DASHBOARD_APP_FILE}" --server.address "${DASHBOARD_HOST}" --server.port "${DASHBOARD_PORT}"' \
'    ;;' \
'  *) echo "APP_ROLE inválido: ${APP_ROLE} (use: api|dashboard|all)"; exit 1 ;;' \
'esac' \
> /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 8000 8501
ENTRYPOINT ["/entrypoint.sh"]
