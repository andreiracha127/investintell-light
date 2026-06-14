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

# Código da aplicação. O cron fund-catalog-sync (scripts/sync_funds.py) foi
# APOSENTADO (catálogo agora é VIEW/MV dinâmica no Tiger); scripts/ ainda entra
# na imagem para as demais ferramentas batch (sync_universe, backfill_universe_eod,
# compute_screener_metrics, enrich_sectors, evaluate_rebalance, etc.).
# tests/alembic continuam fora (migrations rodam fora do container).
COPY app ./app
COPY scripts ./scripts

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
