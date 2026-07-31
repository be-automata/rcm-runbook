# Imagen del Facilitador RCM para Cloudflare Containers.
#
# El disco del contenedor es efímero: no se guarda nada que deba sobrevivir a un
# reinicio. Las sesiones van a Postgres (DATABASE_URL) y los entregables se
# regeneran desde la base al descargarlos.
FROM python:3.12-slim AS build

# uv resuelve e instala igual que en desarrollo, con el mismo uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Capa de dependencias aparte: cambiar el código no reinstala el mundo.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
# El wheel los mete en rcm_runbook/_docs vía force-include; consult_handbook
# no funciona sin ellos.
COPY docs/rcm_handbook_com.md docs/client_method_20_steps.md ./docs/
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# Usuario sin privilegios: el proceso no necesita root para servir HTTP.
RUN useradd --create-home --uid 10001 rcm

WORKDIR /app
COPY --from=build --chown=rcm:rcm /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RCM_HOST=0.0.0.0 \
    RCM_PORT=8080

USER rcm
EXPOSE 8080

# Cloudflare enruta al contenedor cuando responde; /health no exige llave.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status==200 else 1)"

CMD ["rcm-runbook"]
