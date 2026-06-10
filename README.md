# Investintell Light

A standalone stock and portfolio analysis application powered by the [Tiingo API](https://www.tiingo.com/) and a read-only sync from the investintell-allocation master database. The FastAPI + TimescaleDB backend computes all analytics (time-series aggregations, performance metrics, allocation summaries) and serves them as typed JSON; the Next.js frontend renders ready-made data with no client-side API calls.

## Stack

| Layer       | Technology                                    |
|-------------|-----------------------------------------------|
| Backend     | Python 3.12, FastAPI 0.115+, SQLAlchemy 2 async |
| Database    | TimescaleDB (PostgreSQL 16) via Docker         |
| Migrations  | Alembic                                        |
| Frontend    | Next.js 15, React 19, TypeScript 5, Tailwind 4 |
| Data fetching | TanStack Query v5                            |
| Type safety | openapi-typescript (typegen gate in CI)        |
| Package mgr | uv (backend), pnpm 10 (frontend)               |

## Repo layout

```
investintell-light/
├── backend/
│   ├── app/
│   │   ├── api/routes/     # FastAPI routers
│   │   ├── core/           # Config, DB engine
│   │   └── schemas/        # Pydantic response models
│   ├── alembic/            # Migration environment
│   ├── scripts/
│   │   ├── export_openapi.py  # Writes backend/openapi.json
│   │   └── smoke.py           # Hits /health, asserts 200 + payload
│   ├── tests/
│   ├── openapi.json        # Committed contract artifact
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/            # Next.js App Router pages
│   │   └── lib/api/
│   │       └── api.d.ts    # Committed contract artifact (generated)
│   └── package.json
├── .github/workflows/ci.yml
├── docker-compose.yml      # TimescaleDB on port 5436
├── Makefile
├── .env.example
└── pnpm-workspace.yaml
```

## Setup

**Prerequisites:** Python 3.12+, uv, Node 24+, pnpm 10, Docker.

```bash
# 1. Copy and fill in secrets
cp .env.example .env
# Edit .env — set TIINGO_TOKEN at minimum

# 2. Start the database
make db-up

# 3. Install backend dependencies and run migrations
cd backend && uv sync && cd ..
cd backend && uv run alembic upgrade head && cd ..

# 4. Install frontend dependencies
pnpm install

# 5. Run both dev servers (two terminals)
make serve   # backend on :8000
make web     # frontend on :3000
```

## Make targets

| Target      | Description                                                     |
|-------------|-----------------------------------------------------------------|
| `check`     | Backend: ruff, mypy, pytest. Frontend: lint, typecheck.        |
| `serve`     | Start backend with uvicorn --reload on port 8000.              |
| `web`       | Start frontend Next.js dev server.                             |
| `migrate`   | Run `alembic upgrade head`.                                    |
| `types`     | Export OpenAPI schema then regenerate `frontend/src/lib/api/api.d.ts`. |
| `smoke`     | Hit `/health` and assert 200 + expected payload (backend must be running). |
| `db-up`     | `docker compose up -d db`                                      |
| `db-down`   | `docker compose down`                                          |

## Conventions

- **Fail loud.** Routes never return 200 with a degraded payload; errors propagate as 4xx/5xx with detail messages.
- **DB-first.** Routes never call external APIs (Tiingo, investintell-allocation) directly — all external data is ingested by background sync workers and served from TimescaleDB.
- **`response_model` everywhere.** Every FastAPI route declares an explicit Pydantic response model.
- **Typegen gate.** `backend/openapi.json` and `frontend/src/lib/api/api.d.ts` are committed contract artifacts. CI fails if they are stale. Regenerate with `make types` after any schema change.

## Phase status

| Phase | Description                         | Status  |
|-------|-------------------------------------|---------|
| F0    | Scaffold (backend, frontend, glue)  | Done    |
| F1    | Data layer (Tiingo sync, models)    | Next    |
