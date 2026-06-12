# Investintell Light — FastAPI quant engine (InsForge compute / Fly.io).
# Build: uv com lockfile congelado; runtime: uvicorn na porta 8000.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

WORKDIR /app

# Dependências primeiro (camada cacheável).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Código da aplicação (app/ apenas — scripts/tests/alembic ficam fora do
# request path; migrations rodam fora do container).
COPY app ./app

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
