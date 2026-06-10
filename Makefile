.PHONY: check serve web migrate types types-check smoke db-up db-down

# ── Quality gates ────────────────────────────────────────────────────────────
check:
	cd backend && uv run ruff check .
	cd backend && uv run mypy app
	cd backend && uv run pytest -q
	cd frontend && pnpm lint
	cd frontend && pnpm run typecheck
	$(MAKE) types-check

# ── Dev servers ──────────────────────────────────────────────────────────────
serve:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

web:
	cd frontend && pnpm dev

# ── Database ─────────────────────────────────────────────────────────────────
migrate:
	cd backend && uv run alembic upgrade head

db-up:
	docker compose up -d db

db-down:
	docker compose down

# ── Contract artifacts ───────────────────────────────────────────────────────
types:
	cd backend && uv run python scripts/export_openapi.py
	cd frontend && pnpm run types

types-check:
	cd backend && uv run python scripts/export_openapi.py
	cd frontend && pnpm run types
	git diff --exit-code -- backend/openapi.json frontend/src/lib/api/api.d.ts

# ── Smoke test (requires live backend on :8000) ───────────────────────────────
smoke:
	cd backend && uv run python scripts/smoke.py
