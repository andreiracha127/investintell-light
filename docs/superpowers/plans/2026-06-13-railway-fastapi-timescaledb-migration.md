# Railway FastAPI + Dynamic TimescaleDB Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the FastAPI engine to Railway (always-on, no cold start), validate InsForge JWTs locally (JWKS/RS256), and replace the `sync_funds.py` static snapshots with dynamic TimescaleDB queries (VIEW + MATERIALIZED VIEW + CAGGs), exposing Highcharts-Stock array timeseries.

**Architecture:** The FastAPI keeps its single async engine (`app/core/db.py` → `DATABASE_URL` → Tiger `public`). Snapshot tables (`funds`, `fund_risk_latest`, `fund_nav`, `fund_holdings`, `fund_classes`) are replaced by DB-native objects in the SAME Tiger DB: a `funds_v` VIEW and `fund_risk_latest_mv` MATERIALIZED VIEW over the source tables (`instruments_universe`, `fund_risk_metrics`, …), refreshed by the existing daily `risk_metrics` worker; new `cagg_eod_weekly/monthly` and `cagg_nav_weekly` continuous aggregates power downsampled timeseries. Auth is a `HTTPBearer` dependency verifying RS256 against a cached JWKS, applied only to user-data routes.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, asyncpg, TimescaleDB (Tiger Cloud `t83f4np6x4`, `us-west-2`), PyJWT[crypto], pytest + httpx ASGITransport, Railway (Dockerfile builder), uv.

**Execution boundary (this effort):** write ALL code/SQL/tests; **execute the additive Tiger DDL in prod** (VIEW/MV/CAGGs — non-destructive); **do NOT** deploy/flip the Railway service (deliver a runbook). Snapshot tables are renamed `_deprecated` (Phase 4), never dropped.

**Source spec:** `docs/superpowers/specs/2026-06-13-railway-fastapi-timescaledb-migration-design.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `backend/railway.api.toml` | Railway deploy config for the API service (Dockerfile, always-on, healthcheck) | Create |
| `docs/superpowers/runbooks/2026-06-13-railway-api-deploy.md` | Env vars + deploy/flip steps + Tiger DDL rollback + worker REFRESH coordination | Create |
| `backend/pyproject.toml` | Add `pyjwt[crypto]` runtime dep | Modify |
| `backend/app/core/config.py` | Add `insforge_issuer`/`insforge_jwks_url`/`insforge_audience` settings | Modify |
| `backend/app/core/auth.py` | JWKS/RS256 verification + `get_current_user` dependency | Create |
| `backend/app/api/routes/portfolios.py` | Require auth on user-data routes | Modify |
| `backend/app/api/routes/builder.py` | Require auth on the save route | Modify |
| `backend/db/ddl/2026-06-13_dynamic_catalog.sql` | All additive Tiger DDL (MV, VIEWs, CAGGs, policies) | Create |
| `backend/app/models/fund.py` | Repoint `FundRiskLatest`→`fund_risk_latest_mv`, `Fund`→`funds_v`, `FundHolding`→`fund_holdings_v`, `FundClass`→`fund_classes_v`; drop `FundNav` | Modify |
| `backend/app/services/funds_catalog.py` | NAV reads from `nav_timeseries`; keep public surface | Modify |
| `backend/app/schemas/timeseries.py` | Highcharts array response models | Create |
| `backend/app/services/timeseries.py` | range→interval resolution + table/CAGG selection + `[t_ms, value]` packing | Create |
| `backend/app/api/routes/stocks.py` | `GET /stocks/{ticker}/timeseries` | Modify |
| `backend/app/api/routes/funds.py` | `GET /funds/{id}/timeseries` | Modify |
| `backend/app/sync/funds.py`, `backend/scripts/sync_funds.py`, `backend/railway.toml` | Retire the snapshot sync (Phase 4) | Delete/retire |
| `backend/tests/test_auth.py`, `test_timeseries_*.py`, parity tests | New test modules | Create |

**Conventions (verified in repo):** route tests build the app with `create_app()`, override `app.dependency_overrides[get_session] = lambda: None`, and `monkeypatch.setattr` the service/selector at its canonical module — no live DB. `asyncio_mode = "auto"`. Run tests with `uv run pytest` from `backend/`. Lint: `uv run ruff check`. Types: `uv run mypy app`.

---

## PHASE 0 — Deploy config (independent)

### Task 0.1: Railway API service config

**Files:**
- Create: `backend/railway.api.toml`

- [ ] **Step 1: Create the config**

```toml
# Railway deploy config for the FastAPI API service (always-on, NOT cron).
# Pointed at by the API service via the `railway_config_file` setting, like
# railway.livefeed.toml in the workers repo. Does NOT replace railway.toml
# (the fund-catalog-sync cron, retired in Phase 4 of this migration).
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port $PORT"
restartPolicyType = "always"
healthcheckPath = "/health"
healthcheckTimeout = 120
```

- [ ] **Step 2: Verify `/health` exists and boots without secrets**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: PASS (the health route needs no DB/token — confirms the container can pass the Railway healthcheck before any env var is wired).

- [ ] **Step 3: Commit**

```bash
git add backend/railway.api.toml
git commit -m "feat(deploy): Railway API service config (always-on uvicorn, healthcheck)"
```

### Task 0.2: Deploy runbook

**Files:**
- Create: `docs/superpowers/runbooks/2026-06-13-railway-api-deploy.md`

- [ ] **Step 1: Write the runbook**

```markdown
# Runbook — Deploy FastAPI to Railway (api service)

## Prereqs
- Railway project `investintell-light` (id f8f11e07-409d-45c0-835e-3338bef02ead), env `production`.
- Tiger `t83f4np6x4` reachable from Railway us-west.

## Create the service
1. New service → Deploy from repo (backend/ root) → set `railway_config_file = railway.api.toml`.
2. Region: us-west (co-locate with Tiger us-west-2).

## Env vars (NEVER commit these)
- DATABASE_URL = <Tiger DSN, public schema>            # postgres://…?sslmode=require
- DATALAKE_DB_URL = <same Tiger DSN>                    # look-through reads
- INSFORGE_ISSUER = <InsForge token issuer>             # e.g. https://<project>.insforge.app
- INSFORGE_JWKS_URL = <issuer>/.well-known/jwks.json    # discovered in Phase 1
- INSFORGE_AUDIENCE = <InsForge audience/api id>
- CORS_ALLOW_ORIGINS = ["https://www.investintell.com","https://investintell.com"]
- TIINGO_TOKEN = <token>
- REDIS_URL = <optional>

## Deploy / flip (HUMAN-DRIVEN — not automated by this migration)
1. Deploy; confirm `/health` 200 in Railway logs.
2. Smoke: GET /funds, GET /stocks/SPY/timeseries?range=1Y with a valid InsForge JWT on a protected route.
3. Point the frontend API base at the Railway domain; decommission the InsForge compute service.

## Tiger DDL rollback (if needed)
Run backend/db/ddl/2026-06-13_dynamic_catalog.sql is additive. To roll back:
  DROP MATERIALIZED VIEW IF EXISTS cagg_eod_weekly, cagg_eod_monthly, cagg_nav_weekly, fund_risk_latest_mv CASCADE;
  DROP VIEW IF EXISTS funds_v, fund_holdings_v, fund_classes_v CASCADE;

## Worker coordination (Phase 4)
Add to the risk_metrics worker (repo investintell-datalake-workers), AFTER its commit:
  REFRESH MATERIALIZED VIEW CONCURRENTLY fund_risk_latest_mv;
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/runbooks/2026-06-13-railway-api-deploy.md
git commit -m "docs(runbook): Railway API deploy + env vars + DDL rollback"
```

---

## PHASE 1 — Auth (JWKS/RS256) (independent)

### Task 1.1: Add the JWT dependency and settings

**Files:**
- Modify: `backend/pyproject.toml:5-21`
- Modify: `backend/app/core/config.py:33-43`
- Test: `backend/tests/test_auth.py`

- [ ] **Step 1: Write the failing test (settings load)**

Create `backend/tests/test_auth.py`:

```python
"""Tests for InsForge JWT verification (app/core/auth.py)."""
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from types import SimpleNamespace

from app.core.config import Settings


def test_settings_expose_insforge_auth_fields() -> None:
    s = Settings(
        insforge_issuer="https://proj.insforge.app",
        insforge_jwks_url="https://proj.insforge.app/.well-known/jwks.json",
        insforge_audience="investintell-light",
    )
    assert s.insforge_issuer == "https://proj.insforge.app"
    assert s.insforge_jwks_url.endswith("/jwks.json")
    assert s.insforge_audience == "investintell-light"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_auth.py::test_settings_expose_insforge_auth_fields -v`
Expected: FAIL (`Settings` has no `insforge_issuer`).

- [ ] **Step 3: Add the dependency and settings**

In `backend/pyproject.toml`, add to `dependencies` (after `"redis>=8.0.0",`):

```toml
    "pyjwt[crypto]>=2.9",
```

In `backend/app/core/config.py`, add inside `Settings` (after the `datalake_db_url` block, around line 33):

```python
    # --- InsForge auth (JWT validated locally; Auth stays on InsForge) ---
    # The FastAPI verifies RS256 InsForge JWTs against a cached JWKS — no
    # round-trip per request. Unset → protected routes return 503 (declared).
    insforge_issuer: str | None = None
    insforge_jwks_url: str | None = None
    insforge_audience: str | None = None
```

- [ ] **Step 4: Sync deps and run the test**

Run: `cd backend && uv sync && uv run pytest tests/test_auth.py::test_settings_expose_insforge_auth_fields -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/core/config.py backend/tests/test_auth.py
git commit -m "feat(auth): add pyjwt[crypto] dep and InsForge auth settings"
```

### Task 1.2: JWKS/RS256 verification module

**Files:**
- Create: `backend/app/core/auth.py`
- Test: `backend/tests/test_auth.py`

- [ ] **Step 1: Write the failing tests (token verification)**

Append to `backend/tests/test_auth.py`:

```python
_ISSUER = "https://proj.insforge.app"
_AUD = "investintell-light"


@pytest.fixture
def rsa_keys() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _make_token(private_pem: bytes, **overrides: object) -> str:
    payload: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "iss": _ISSUER,
        "aud": _AUD,
        "exp": int(time.time()) + 3600,
        "org_id": "org-123",
    }
    payload.update(overrides)
    return jwt.encode(payload, private_pem, algorithm="RS256")


def _patch_jwks(monkeypatch: pytest.MonkeyPatch, public_pem: bytes) -> None:
    import app.core.auth as auth

    monkeypatch.setattr(auth.get_settings, "cache_clear", lambda: None, raising=False)
    monkeypatch.setattr(
        auth,
        "_get_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_pem)
        ),
    )
    monkeypatch.setenv("INSFORGE_ISSUER", _ISSUER)
    monkeypatch.setenv("INSFORGE_JWKS_URL", _ISSUER + "/.well-known/jwks.json")
    monkeypatch.setenv("INSFORGE_AUDIENCE", _AUD)
    auth.get_settings.cache_clear()


async def test_valid_token_returns_claims(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[bytes, bytes]
) -> None:
    import app.core.auth as auth

    private_pem, public_pem = rsa_keys
    _patch_jwks(monkeypatch, public_pem)
    user = await auth.verify_bearer(_make_token(private_pem, sub="u-1"))
    assert user.sub == "u-1"
    assert user.org_id == "org-123"


async def test_expired_token_is_401(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[bytes, bytes]
) -> None:
    import app.core.auth as auth
    from fastapi import HTTPException

    private_pem, public_pem = rsa_keys
    _patch_jwks(monkeypatch, public_pem)
    token = _make_token(private_pem, exp=int(time.time()) - 10)
    with pytest.raises(HTTPException) as exc:
        await auth.verify_bearer(token)
    assert exc.value.status_code == 401


async def test_wrong_audience_is_401(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[bytes, bytes]
) -> None:
    import app.core.auth as auth
    from fastapi import HTTPException

    private_pem, public_pem = rsa_keys
    _patch_jwks(monkeypatch, public_pem)
    token = _make_token(private_pem, aud="some-other-api")
    with pytest.raises(HTTPException) as exc:
        await auth.verify_bearer(token)
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_auth.py -v`
Expected: FAIL (`app.core.auth` does not exist).

- [ ] **Step 3: Implement `app/core/auth.py`**

```python
"""InsForge JWT verification (RS256 against a cached JWKS).

Auth stays on InsForge: the frontend obtains tokens via @insforge/sdk; this
module verifies them LOCALLY (no per-request round-trip). Applied only to
user-data routes — public catalog/timeseries routes stay open (CORS-gated),
matching the boundary CatalogCacheMiddleware already encodes.

Failure is closed: missing/invalid token on a protected route -> 401; the
auth backend being unconfigured -> 503 (declared, never silently open).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=True)
_jwks_client: PyJWKClient | None = None


@dataclass(frozen=True)
class CurrentUser:
    """Identity extracted from a verified InsForge JWT."""

    sub: str
    org_id: str | None
    claims: dict[str, Any]


def _get_jwks_client() -> PyJWKClient:
    """Process-cached JWKS client (refreshes its key set on a kid miss)."""
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        if not settings.insforge_jwks_url:
            raise HTTPException(
                status_code=503,
                detail="Auth backend not configured (INSFORGE_JWKS_URL).",
            )
        _jwks_client = PyJWKClient(settings.insforge_jwks_url)
    return _jwks_client


async def verify_bearer(token: str) -> CurrentUser:
    """Verify an RS256 InsForge JWT and return the identity, else raise 401."""
    settings = get_settings()
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.insforge_audience,
            issuer=settings.insforge_issuer,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token.") from exc
    return CurrentUser(
        sub=str(claims["sub"]),
        org_id=claims.get("org_id"),
        claims=claims,
    )


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> CurrentUser:
    """FastAPI dependency: 401 on missing/invalid token, else the identity."""
    return await verify_bearer(creds.credentials)
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_auth.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/auth.py backend/tests/test_auth.py
git commit -m "feat(auth): JWKS/RS256 InsForge token verification + get_current_user"
```

### Task 1.3: Protect user-data routes

**Files:**
- Modify: `backend/app/api/routes/portfolios.py` (router-level dependency)
- Modify: `backend/app/api/routes/builder.py` (save route only)
- Test: `backend/tests/test_auth_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_auth_routes.py`:

```python
"""Protected routes require a valid InsForge JWT (401 without)."""
from httpx import ASGITransport, AsyncClient

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_session
from app.main import create_app


def _client(authed: bool) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    if authed:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            sub="u-1", org_id="org-1", claims={}
        )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_portfolios_list_requires_auth() -> None:
    async with _client(authed=False) as client:
        resp = await client.get("/portfolios")
    assert resp.status_code in (401, 403)  # missing bearer


async def test_public_funds_list_stays_open() -> None:
    # Catalog stays public — no auth override, must not 401.
    async with _client(authed=False) as client:
        resp = await client.get("/funds")
    assert resp.status_code != 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_auth_routes.py::test_portfolios_list_requires_auth -v`
Expected: FAIL (portfolios currently open → 200, not 401/403).

- [ ] **Step 3: Add the router dependency**

In `backend/app/api/routes/portfolios.py`, find the `APIRouter(...)` construction and add a router-wide dependency. Change:

```python
router = APIRouter(prefix="/portfolios", tags=["portfolios"])
```

to:

```python
from app.core.auth import get_current_user
from fastapi import Depends

router = APIRouter(
    prefix="/portfolios",
    tags=["portfolios"],
    dependencies=[Depends(get_current_user)],
)
```

(If the existing `APIRouter(...)` already imports `Depends`, do not duplicate the import.)

In `backend/app/api/routes/builder.py`, add `dependencies=[Depends(get_current_user)]` ONLY to the save route decorator (the optimize preview can stay public if it has no persistence; protect the route that writes saved positions). Example for the save endpoint decorator:

```python
@router.post("/builder/save", response_model=SaveResponse, dependencies=[Depends(get_current_user)])
```

- [ ] **Step 4: Run the tests + regression**

Run: `cd backend && uv run pytest tests/test_auth_routes.py tests/test_portfolios_crud_route.py tests/test_builder_save_route.py -v`
Expected: `test_portfolios_list_requires_auth` PASS, `test_public_funds_list_stays_open` PASS. The existing CRUD/save route tests may now 401 — fix them by adding `app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub="u-1", org_id=None, claims={})` to their client builders (apply the same override pattern as `_client(authed=True)` above).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/portfolios.py backend/app/api/routes/builder.py backend/tests/
git commit -m "feat(auth): require InsForge JWT on portfolios + builder save routes"
```

---

## PHASE 2 — Dynamic persistence + CAGGs (executes additive Tiger DDL)

### Task 2.1: Continuous aggregates for downsampling

**Files:**
- Create: `backend/db/ddl/2026-06-13_dynamic_catalog.sql` (CAGG section)

- [ ] **Step 1: Write the CAGG DDL**

Create `backend/db/ddl/2026-06-13_dynamic_catalog.sql`:

```sql
-- Additive, non-destructive dynamic-catalog DDL (Tiger t83f4np6x4, public).
-- Idempotent where possible; safe to re-run. Rollback in the deploy runbook.

-- 1) EOD weekly OHLC (adjusted) for Highcharts long-range downsample.
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_eod_weekly
WITH (timescaledb.continuous) AS
SELECT ticker,
       time_bucket('1 week', date) AS bucket,
       first(adj_open,  date) AS adj_open,
       max(adj_high)          AS adj_high,
       min(adj_low)           AS adj_low,
       last(adj_close, date)  AS adj_close,
       sum(adj_volume)        AS adj_volume
FROM eod_prices
GROUP BY ticker, time_bucket('1 week', date)
WITH NO DATA;

-- 2) EOD monthly OHLC (adjusted).
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_eod_monthly
WITH (timescaledb.continuous) AS
SELECT ticker,
       time_bucket('1 month', date) AS bucket,
       first(adj_open,  date) AS adj_open,
       max(adj_high)          AS adj_high,
       min(adj_low)           AS adj_low,
       last(adj_close, date)  AS adj_close,
       sum(adj_volume)        AS adj_volume
FROM eod_prices
GROUP BY ticker, time_bucket('1 month', date)
WITH NO DATA;

-- 3) NAV weekly (last-of-week) — cagg_nav_monthly already exists.
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_nav_weekly
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket('1 week', nav_date) AS bucket,
       last(nav, nav_date)      AS nav_eow,
       first(nav, nav_date)     AS nav_bow,
       count(*)                 AS n_obs,
       last(aum_usd, nav_date)  AS aum_eow
FROM nav_timeseries
GROUP BY instrument_id, time_bucket('1 week', nav_date)
WITH NO DATA;

-- Populate once, then keep fresh daily (ingestion writes daily).
CALL refresh_continuous_aggregate('cagg_eod_weekly',  NULL, NULL);
CALL refresh_continuous_aggregate('cagg_eod_monthly', NULL, NULL);
CALL refresh_continuous_aggregate('cagg_nav_weekly',  NULL, NULL);

SELECT add_continuous_aggregate_policy('cagg_eod_weekly',
  start_offset => INTERVAL '90 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
SELECT add_continuous_aggregate_policy('cagg_eod_monthly',
  start_offset => INTERVAL '180 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
SELECT add_continuous_aggregate_policy('cagg_nav_weekly',
  start_offset => INTERVAL '90 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
```

- [ ] **Step 2: Execute the CAGG section on Tiger**

Run the three `CREATE MATERIALIZED VIEW … WITH NO DATA`, the three `refresh_continuous_aggregate` calls, and the three policy calls against `t83f4np6x4` (via the Tiger MCP `db_execute_query`, one statement per call — continuous-aggregate `CREATE` and `CALL refresh` cannot run inside a multi-statement transaction block).

- [ ] **Step 3: Verify CAGG parity for a sample ticker**

Run this verification query (expected: 0 mismatching weeks):

```sql
WITH raw AS (
  SELECT time_bucket('1 week', date) AS bucket,
         last(adj_close, date) AS adj_close
  FROM eod_prices WHERE ticker = 'SPY'
  GROUP BY 1)
SELECT count(*)
FROM raw
JOIN cagg_eod_weekly c ON c.bucket = raw.bucket AND c.ticker = 'SPY'
WHERE c.adj_close IS DISTINCT FROM raw.adj_close;
```

Expected: `count = 0`.

- [ ] **Step 4: Commit the DDL file**

```bash
git add backend/db/ddl/2026-06-13_dynamic_catalog.sql
git commit -m "feat(db): continuous aggregates for eod/nav downsampling (executed on Tiger)"
```

### Task 2.2: `fund_risk_latest_mv` MATERIALIZED VIEW + repoint model

**Files:**
- Modify: `backend/db/ddl/2026-06-13_dynamic_catalog.sql` (MV section)
- Modify: `backend/app/models/fund.py` (`FundRiskLatest.__tablename__`, trim columns to the MV's column set)
- Test: parity SQL (verification) + `backend/tests/test_models.py` (model maps cleanly)

- [ ] **Step 1: Append the MV DDL**

Append to `backend/db/ddl/2026-06-13_dynamic_catalog.sql`:

```sql
-- Latest risk metrics per fund (replaces the sync_funds.py fund_risk_latest
-- snapshot). organization_id IS NULL = the global (non-org) calc. The column
-- set EXACTLY mirrors the current fund_risk_latest table (33 columns) so the
-- repointed model and the parity test stay valid.
CREATE MATERIALIZED VIEW IF NOT EXISTS fund_risk_latest_mv AS
SELECT DISTINCT ON (instrument_id)
       instrument_id, calc_date,
       return_1m, return_3m, return_1y, return_3y_ann, return_5y_ann,
       volatility_1y, max_drawdown_1y, max_drawdown_3y,
       sharpe_1y, sharpe_3y, sortino_1y, calmar_ratio_3y,
       alpha_1y, beta_1y, information_ratio_1y, tracking_error_1y,
       var_95_1m, cvar_95_1m, cvar_95_12m, cvar_99_evt,
       peer_sharpe_pctl, peer_sortino_pctl, peer_return_pctl, peer_drawdown_pctl,
       manager_score, downside_capture_1y, upside_capture_1y,
       equity_correlation_252d, peer_strategy_label, peer_count, elite_flag
FROM fund_risk_metrics
WHERE organization_id IS NULL
ORDER BY instrument_id, calc_date DESC;

CREATE UNIQUE INDEX IF NOT EXISTS fund_risk_latest_mv_pk
  ON fund_risk_latest_mv (instrument_id);
```

- [ ] **Step 2: Execute it on Tiger and verify parity vs the snapshot**

Execute the `CREATE MATERIALIZED VIEW` + `CREATE UNIQUE INDEX` on `t83f4np6x4`. Then run (expected: both 0):

```sql
-- (a) same instrument set
SELECT count(*) FROM fund_risk_latest_mv m
FULL JOIN fund_risk_latest s USING (instrument_id)
WHERE m.instrument_id IS NULL OR s.instrument_id IS NULL;
-- (b) same sharpe_1y on the shared set (allow snapshot staleness drift)
SELECT count(*) FROM fund_risk_latest_mv m
JOIN fund_risk_latest s USING (instrument_id)
WHERE round(m.sharpe_1y, 6) IS DISTINCT FROM round(s.sharpe_1y, 6)
  AND m.calc_date = s.calc_date;
```

Expected: `(a) = 0`. `(b) = 0` for rows at the same `calc_date` (non-zero only where the snapshot lags the latest calc — acceptable, and exactly what going dynamic fixes).

- [ ] **Step 3: Repoint and reconcile the model**

In `backend/app/models/fund.py`, change `FundRiskLatest.__tablename__` from `"fund_risk_latest"` to `"fund_risk_latest_mv"`, and **delete the model columns that are NOT in the MV's 33-column list** (the asset-class analytics blocks: `scoring_model`, `empirical_duration`, `empirical_duration_r2`, `credit_beta`, `credit_beta_r2`, `yield_proxy_12m`, `duration_adj_drawdown_1y`, `seven_day_net_yield`, `fed_funds_rate_at_calc`, `nav_per_share_mmf`, `pct_weekly_liquid`, `weighted_avg_maturity_days`, `crisis_alpha_score`, `inflation_beta`, `inflation_beta_r2`, `var_95_3m`/`var_95_6m`/etc. if present). These are absent from the source `fund_risk_metrics`/snapshot and were unpopulated. Keep exactly the 33 columns listed in the MV.

Map `FundRiskLatest.instrument_id` as a plain `mapped_column(Uuid, primary_key=True)` (drop the `ForeignKey("funds.instrument_id")` — a MV is not a FK target).

- [ ] **Step 4: Verify the model and service still type/load**

Run: `cd backend && uv run pytest tests/test_funds_catalog_service.py tests/test_models.py -v && uv run mypy app/models/fund.py app/services/funds_catalog.py`
Expected: PASS / no type errors. (The `_RISK_SORT_FIELDS` whitelist in `funds_catalog.py` is built from `FundRiskLatest.__table__.columns`, so trimming columns automatically narrows the sort whitelist to live columns — confirm no test asserts a now-removed sort key; if one does, drop that key from the assertion.)

- [ ] **Step 5: Commit**

```bash
git add backend/db/ddl/2026-06-13_dynamic_catalog.sql backend/app/models/fund.py backend/tests/
git commit -m "feat(db): fund_risk_latest_mv (latest-per-fund) + repoint FundRiskLatest model"
```

### Task 2.3: `funds_v` VIEW + repoint `Fund` model

**Files:**
- Modify: `backend/db/ddl/2026-06-13_dynamic_catalog.sql` (funds VIEW section)
- Modify: `backend/app/models/fund.py` (`Fund.__tablename__ = "funds_v"`)
- Test: parity SQL (verification)

- [ ] **Step 1: Append the `funds_v` VIEW DDL**

This translates the `sync_funds.py` cascade (identity from `instruments_universe` where `instrument_type='fund'`; classification label cascade registered→etf→mmf→reclassification→'Unclassified'; `fund_type` from presence in sec_etfs/sec_money_market_funds; expense `net_operating_expenses` registered→etf then `management_fee`; aum `monthly_avg_net_assets` registered→etf, fallback `sec_fund_classes.net_assets`). Append to the DDL file:

```sql
CREATE OR REPLACE VIEW funds_v AS
WITH reclass AS (
  SELECT DISTINCT ON (source_pk)
         source_pk::uuid AS instrument_id, proposed_strategy_label AS label
  FROM strategy_reclassification_stage
  WHERE source_table = 'instruments_universe' AND proposed_strategy_label IS NOT NULL
  ORDER BY source_pk, classified_at DESC
),
fc_aum AS (
  SELECT series_id, max(net_assets) AS aum_usd
  FROM sec_fund_classes
  GROUP BY series_id
)
SELECT
  iu.instrument_id,
  COALESCE(rf.series_id, etf.series_id, mmf.series_id)                     AS series_id,
  iu.ticker,
  iu.isin,
  NULL::text                                                              AS cusip,
  COALESCE(rf.lei, etf.lei)                                               AS lei,
  iu.name,
  CASE
    WHEN mmf.series_id IS NOT NULL THEN 'mmf'
    WHEN etf.series_id IS NOT NULL THEN 'etf'
    ELSE 'mutual_fund'
  END                                                                     AS fund_type,
  COALESCE(rf.strategy_label, etf.strategy_label, mmf.strategy_label,
           rc.label, 'Unclassified')                                      AS strategy_label,
  iu.asset_class,
  COALESCE(rf.is_index, etf.is_index)                                     AS is_index,
  COALESCE(rf.net_operating_expenses, etf.net_operating_expenses,
           rf.management_fee, etf.management_fee)                         AS expense_ratio,
  COALESCE(rf.monthly_avg_net_assets, etf.monthly_avg_net_assets,
           fa.aum_usd)                                                    AS aum_usd,
  rf.primary_benchmark                                                    AS primary_benchmark,
  COALESCE(rf.inception_date, etf.inception_date)                         AS inception_date,
  COALESCE(rf.domicile, etf.domicile, mmf.domicile)                       AS domicile,
  COALESCE(iu.currency, rf.currency, etf.currency, mmf.currency)          AS currency
FROM instruments_universe iu
LEFT JOIN reclass rc          ON rc.instrument_id = iu.instrument_id
LEFT JOIN sec_registered_funds rf ON rf.series_id = (iu.attributes->>'series_id')
LEFT JOIN sec_etfs etf            ON etf.series_id = (iu.attributes->>'series_id')
LEFT JOIN sec_money_market_funds mmf ON mmf.series_id = (iu.attributes->>'series_id')
LEFT JOIN fc_aum fa           ON fa.series_id = COALESCE(rf.series_id, etf.series_id, mmf.series_id)
WHERE iu.instrument_type = 'fund' AND iu.is_active IS TRUE;
```

> NOTE for the executor: the `iu.attributes->>'series_id'` join key is the assumed series-id location in `instruments_universe.attributes` (jsonb). **Confirm the real key** with `SELECT attributes FROM instruments_universe WHERE instrument_type='fund' LIMIT 3;` and adjust the three joins. The parity test (Step 3) is the gate — iterate the join/COALESCE until parity passes. The synced `funds` table is the source of truth to match.

- [ ] **Step 2: Execute on Tiger**

Execute the `CREATE OR REPLACE VIEW funds_v` on `t83f4np6x4`.

- [ ] **Step 3: Verify parity vs the `funds` snapshot**

Run (expected: small/zero diffs; investigate any structural gap):

```sql
-- (a) row-count parity (Unclassified excluded in BOTH for the screen)
SELECT
  (SELECT count(*) FROM funds   WHERE strategy_label <> 'Unclassified') AS snap,
  (SELECT count(*) FROM funds_v WHERE strategy_label <> 'Unclassified') AS dyn;
-- (b) per-fund field parity on the shared id set
SELECT count(*) FROM funds s JOIN funds_v v USING (instrument_id)
WHERE s.fund_type IS DISTINCT FROM v.fund_type
   OR s.strategy_label IS DISTINCT FROM v.strategy_label
   OR round(s.expense_ratio,6) IS DISTINCT FROM round(v.expense_ratio,6);
```

Expected: `(a)` snap ≈ dyn (exact match once joins are correct); `(b)` near 0. Iterate the VIEW until `(b)` is 0 for `fund_type`/`strategy_label` (expense/aum may differ where the snapshot used a NAV fallback — acceptable, documented divergence).

- [ ] **Step 4: Repoint the `Fund` model**

In `backend/app/models/fund.py`, change `Fund.__tablename__` from `"funds"` to `"funds_v"`. Remove the three staleness columns (`synced_at`, `source_calc_date`, `source_nav_max_date`) from the `Fund` model — a dynamic view has no sync markers (see Task 2.4 for how the API staleness fields are sourced instead).

- [ ] **Step 5: Run service tests + commit**

Run: `cd backend && uv run pytest tests/test_funds_catalog_service.py -v`
Expected: PASS (the service tests stub SQL; they validate the pure helpers, unaffected by the table name).

```bash
git add backend/db/ddl/2026-06-13_dynamic_catalog.sql backend/app/models/fund.py
git commit -m "feat(db): funds_v dynamic VIEW over source tables + repoint Fund model"
```

### Task 2.4: NAV reads from `nav_timeseries`; staleness from sources

**Files:**
- Modify: `backend/app/services/funds_catalog.py` (`fetch_fund_profile` NAV read; `fetch_staleness`)
- Modify: `backend/app/api/routes/funds.py` (`_select_nav_rows` for `/history`)
- Test: `backend/tests/test_funds_catalog_service.py`, `backend/tests/test_fund_history_route.py`

- [ ] **Step 1: Write the failing test (NAV read targets nav_timeseries)**

Add to `backend/tests/test_funds_catalog_service.py` a test asserting the NAV select uses the `nav_timeseries` columns (`instrument_id`, `nav_date`, `nav`) rather than the `fund_nav` model. Since these are pure-SQL-builder tests, assert on the compiled SQL text:

```python
from sqlalchemy import select
from app.services.funds_catalog import build_nav_series_select  # new pure builder
import uuid, datetime as dt


def test_nav_series_select_targets_nav_timeseries() -> None:
    stmt = build_nav_series_select(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        dt.date(2024, 1, 1),
    )
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "nav_timeseries" in sql
    assert "nav_date" in sql
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_funds_catalog_service.py::test_nav_series_select_targets_nav_timeseries -v`
Expected: FAIL (`build_nav_series_select` undefined).

- [ ] **Step 3: Implement the dynamic NAV reads**

In `backend/app/services/funds_catalog.py`, add a pure builder and use it in `fetch_fund_profile` (replace the `FundNav` query). Add at module top: `from sqlalchemy import text`. Implement:

```python
from sqlalchemy import Select

def build_nav_series_select(instrument_id: "uuid.UUID", start: "dt.date") -> "Select[Any]":
    """NAV (nav_date, nav) for one fund from the raw nav_timeseries hypertable."""
    return (
        select(
            text("nav_date"),
            text("nav"),
        )
        .select_from(text("nav_timeseries"))
        .where(
            text("instrument_id = :iid"),
            text("nav_date >= :start"),
            text("nav IS NOT NULL"),
        )
        .order_by(text("nav_date"))
        .params(iid=str(instrument_id), start=start)
    )
```

In `fetch_fund_profile`, replace the `max(FundNav.nav_date)` / `FundNav` window query with:

```python
    max_nav_date = await session.scalar(
        text("SELECT max(nav_date) FROM nav_timeseries WHERE instrument_id = :iid"),
        {"iid": str(instrument_id)},
    )
    nav: list[tuple[dt.date, float | None]] = []
    if max_nav_date is not None:
        window_start = max_nav_date - dt.timedelta(days=NAV_WINDOW_DAYS)
        result = await session.execute(
            build_nav_series_select(instrument_id, window_start)
        )
        raw = [
            (cast("dt.date", d), float(v) if v is not None else None)
            for d, v in result.all()
        ]
        nav = decimate_nav(raw)
```

Update `fetch_staleness` to derive markers from the sources instead of `Fund.synced_at`:

```python
async def fetch_staleness(session: AsyncSession) -> Staleness:
    row = (
        await session.execute(
            text(
                "SELECT now() AS synced_at, "
                "(SELECT max(calc_date) FROM fund_risk_latest_mv) AS source_calc_date, "
                "(SELECT max(nav_date) FROM nav_timeseries) AS source_nav_max_date"
            )
        )
    ).one()
    return Staleness(synced_at=row[0], source_calc_date=row[1], source_nav_max_date=row[2])
```

In `backend/app/api/routes/funds.py`, change `_select_nav_rows` to query `nav_timeseries` via `text(...)` with the same `(nav_date, nav)` shape (drop the `FundNav` import). Keep the route's response identical.

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_funds_catalog_service.py tests/test_fund_history_route.py tests/test_funds_routes.py -v`
Expected: PASS. Fix any test that constructed a `FundNav` stub to stub the new `text`-based read instead (the history route tests monkeypatch `_select_nav_rows` at module level — keep that seam).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/funds_catalog.py backend/app/api/routes/funds.py backend/tests/
git commit -m "feat(funds): read NAV from nav_timeseries; derive staleness from sources"
```

### Task 2.5: `fund_holdings_v` / `fund_classes_v` VIEWs + repoint models

**Files:**
- Modify: `backend/db/ddl/2026-06-13_dynamic_catalog.sql` (holdings/classes section)
- Modify: `backend/app/models/fund.py` (`FundHolding.__tablename__`, `FundClass.__tablename__`)
- Test: parity SQL

- [ ] **Step 1: Append the holdings/classes VIEWs**

```sql
-- Latest N-PORT holdings per series, ranked by pct_of_nav desc.
CREATE OR REPLACE VIEW fund_holdings_v AS
WITH latest AS (
  SELECT series_id, max(report_date) AS report_date
  FROM sec_nport_holdings GROUP BY series_id
)
SELECT h.series_id, h.report_date,
       row_number() OVER (PARTITION BY h.series_id ORDER BY h.pct_of_nav DESC NULLS LAST) AS rank,
       h.issuer_name, h.cusip, h.isin, h.asset_class, h.sector,
       NULL::text AS gics_sector,
       h.market_value, h.pct_of_nav
FROM sec_nport_holdings h
JOIN latest l ON l.series_id = h.series_id AND l.report_date = h.report_date;

-- Share classes from sec_fund_classes (latest period per class).
CREATE OR REPLACE VIEW fund_classes_v AS
SELECT DISTINCT ON (class_id)
       class_id, series_id, class_name, ticker,
       expense_ratio_pct AS expense_ratio, xbrl_period_end AS source_period_end,
       now() AS synced_at
FROM sec_fund_classes
WHERE ticker IS NOT NULL
ORDER BY class_id, xbrl_period_end DESC NULLS LAST;
```

> NOTE: `fund_classes_v` omits the `instrument_id` FK that the current `FundClass` model carries (the series→instrument link). If the profile needs classes joined by `instrument_id`, resolve series→instrument via `funds_v` in the service query (Task 2.3 exposes `series_id` on `funds_v`). The parity test below uses `series_id`.

- [ ] **Step 2: Execute + parity check**

Execute both VIEWs on Tiger. Verify (expected ≈ 0):

```sql
SELECT
 (SELECT count(*) FROM fund_holdings)   AS snap_h,
 (SELECT count(*) FROM fund_holdings_v) AS dyn_h;
```

(Counts differ if the snapshot capped per series; the VIEW is uncapped — the profile route already display-caps to top-50, so a larger source set is fine. Confirm the top-50 slice matches for a sample series.)

- [ ] **Step 3: Repoint models**

In `backend/app/models/fund.py`: `FundHolding.__tablename__ = "fund_holdings_v"`; `FundClass.__tablename__ = "fund_classes_v"` and drop the `instrument_id` FK column from `FundClass` (resolve via service join). Adjust `fetch_fund_profile`'s class query to join `funds_v.series_id` if it previously filtered by `FundClass.instrument_id`.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_funds_catalog_service.py tests/test_funds_routes.py tests/test_lookthrough.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/db/ddl/2026-06-13_dynamic_catalog.sql backend/app/models/fund.py backend/app/services/funds_catalog.py backend/tests/
git commit -m "feat(db): fund_holdings_v/fund_classes_v VIEWs + repoint models"
```

---

## PHASE 3 — Timeseries endpoints + Highcharts format

### Task 3.1: Highcharts array schemas

**Files:**
- Create: `backend/app/schemas/timeseries.py`
- Test: `backend/tests/test_timeseries_schema.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_timeseries_schema.py`:

```python
from app.schemas.timeseries import LineSeriesResponse, OhlcSeriesResponse


def test_line_series_serializes_as_arrays() -> None:
    r = LineSeriesResponse(id="SPY", interval="daily", series=[[1700000000000, 1.5]])
    assert r.model_dump()["series"] == [[1700000000000, 1.5]]


def test_ohlc_series_serializes_as_arrays() -> None:
    r = OhlcSeriesResponse(
        id="SPY", interval="weekly",
        ohlc=[[1700000000000, 1.0, 2.0, 0.5, 1.8]],
        volume=[[1700000000000, 1000]],
    )
    dumped = r.model_dump()
    assert dumped["ohlc"][0] == [1700000000000, 1.0, 2.0, 0.5, 1.8]
    assert dumped["volume"][0] == [1700000000000, 1000]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_timeseries_schema.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the schemas**

```python
"""Highcharts Stock array contracts: [[t_ms, value], ...] / [[t_ms,o,h,l,c], ...]."""
from typing import Literal

from pydantic import BaseModel

Interval = Literal["daily", "weekly", "monthly"]


class LineSeriesResponse(BaseModel):
    id: str
    interval: Interval
    series: list[list[float]]  # [[t_ms, value], ...]


class OhlcSeriesResponse(BaseModel):
    id: str
    interval: Interval
    ohlc: list[list[float]]    # [[t_ms, o, h, l, c], ...]
    volume: list[list[float]]  # [[t_ms, v], ...]
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_timeseries_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/timeseries.py backend/tests/test_timeseries_schema.py
git commit -m "feat(timeseries): Highcharts array response schemas"
```

### Task 3.2: Timeseries service (range→interval, table/CAGG selection, packing)

**Files:**
- Create: `backend/app/services/timeseries.py`
- Test: `backend/tests/test_timeseries_service.py`

- [ ] **Step 1: Write the failing tests (pure logic)**

```python
import datetime as dt
from app.services.timeseries import resolve_interval, to_ms_pairs, to_ms_ohlc


def test_resolve_interval_by_range() -> None:
    assert resolve_interval("1Y") == "daily"
    assert resolve_interval("5Y") == "weekly"
    assert resolve_interval("MAX") == "monthly"


def test_to_ms_pairs() -> None:
    pairs = to_ms_pairs([(dt.date(2026, 6, 11), 105.5)])
    assert pairs == [[int(dt.datetime(2026, 6, 11, tzinfo=dt.UTC).timestamp() * 1000), 105.5]]


def test_to_ms_ohlc() -> None:
    rows = [(dt.date(2026, 6, 11), 1.0, 2.0, 0.5, 1.8, 1000)]
    ohlc, vol = to_ms_ohlc(rows)
    t = int(dt.datetime(2026, 6, 11, tzinfo=dt.UTC).timestamp() * 1000)
    assert ohlc == [[t, 1.0, 2.0, 0.5, 1.8]]
    assert vol == [[t, 1000.0]]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_timeseries_service.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the service**

```python
"""Timeseries assembly: pick raw vs CAGG by range, pack into Highcharts arrays.

Granularity by visible range: <=1Y daily (raw hypertable), 1-5Y weekly CAGG,
>5Y monthly CAGG. Downsample happens in the DB (CAGG), never in Python.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Interval = Literal["daily", "weekly", "monthly"]
RangeKey = Literal["1M", "6M", "1Y", "5Y", "MAX"]

_INTERVAL_BY_RANGE: dict[str, Interval] = {
    "1M": "daily", "6M": "daily", "1Y": "daily", "5Y": "weekly", "MAX": "monthly",
}
_RANGE_DAYS: dict[str, int] = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 1826}


def resolve_interval(range_key: str) -> Interval:
    return _INTERVAL_BY_RANGE.get(range_key, "daily")


def range_start(range_key: str, last: dt.date) -> dt.date | None:
    """Start date for the visible range; None = MAX (full history)."""
    days = _RANGE_DAYS.get(range_key)
    return None if days is None else last - dt.timedelta(days=days)


def _ms(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp() * 1000)


def to_ms_pairs(rows: list[tuple[dt.date, float]]) -> list[list[float]]:
    return [[_ms(d), float(v)] for d, v in rows]


def to_ms_ohlc(
    rows: list[tuple[dt.date, float, float, float, float, float]],
) -> tuple[list[list[float]], list[list[float]]]:
    ohlc = [[_ms(d), float(o), float(h), float(lo), float(c)] for d, o, h, lo, c, _v in rows]
    vol = [[_ms(d), float(v or 0)] for d, *_rest, v in rows]
    return ohlc, vol


# --- DB reads (return ascending (date, …) tuples) -------------------------

_EOD_TABLE: dict[Interval, tuple[str, str]] = {
    "daily":   ("eod_prices",      "date"),
    "weekly":  ("cagg_eod_weekly", "bucket"),
    "monthly": ("cagg_eod_monthly","bucket"),
}


async def select_eod_ohlc(
    session: AsyncSession, ticker: str, interval: Interval, start: dt.date | None
) -> list[tuple[dt.date, float, float, float, float, float]]:
    table, tcol = _EOD_TABLE[interval]
    where = "ticker = :ticker" + ("" if start is None else f" AND {tcol} >= :start")
    sql = text(
        f"SELECT {tcol} AS d, adj_open, adj_high, adj_low, adj_close, adj_volume "
        f"FROM {table} WHERE {where} ORDER BY {tcol}"
    )
    params: dict[str, object] = {"ticker": ticker}
    if start is not None:
        params["start"] = start
    rows = (await session.execute(sql, params)).all()
    return [tuple(r) for r in rows]  # type: ignore[misc]


_NAV_TABLE: dict[Interval, tuple[str, str, str]] = {
    "daily":   ("nav_timeseries",  "nav_date", "nav"),
    "weekly":  ("cagg_nav_weekly", "bucket",   "nav_eow"),
    "monthly": ("cagg_nav_monthly","month",    "nav_eom"),
}


async def select_nav_line(
    session: AsyncSession, instrument_id: str, interval: Interval, start: dt.date | None
) -> list[tuple[dt.date, float]]:
    table, tcol, vcol = _NAV_TABLE[interval]
    where = "instrument_id = :iid" + ("" if start is None else f" AND {tcol} >= :start")
    sql = text(
        f"SELECT {tcol} AS d, {vcol} AS v FROM {table} "
        f"WHERE {where} AND {vcol} IS NOT NULL ORDER BY {tcol}"
    )
    params: dict[str, object] = {"iid": instrument_id}
    if start is not None:
        params["start"] = start
    rows = (await session.execute(sql, params)).all()
    return [(d, float(v)) for d, v in rows]
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_timeseries_service.py -v`
Expected: PASS (3 tests; pure functions only — DB selects are exercised in route tests via stubs).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/timeseries.py backend/tests/test_timeseries_service.py
git commit -m "feat(timeseries): range->interval resolution, CAGG selection, ms packing"
```

### Task 3.3: `GET /stocks/{ticker}/timeseries`

**Files:**
- Modify: `backend/app/api/routes/stocks.py`
- Test: `backend/tests/test_stocks_timeseries_route.py`

- [ ] **Step 1: Write the failing test**

```python
"""GET /stocks/{ticker}/timeseries — Highcharts OHLC arrays (DB stubbed)."""
import datetime as dt
from httpx import ASGITransport, AsyncClient

import app.api.routes.stocks as stocks_routes
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_stock_timeseries_ohlc_arrays(monkeypatch) -> None:
    async def fake_ensure(session, client, symbols, start, end):
        return None

    async def fake_select(session, ticker, interval, start):
        assert ticker == "SPY" and interval == "daily"
        return [(dt.date(2026, 6, 11), 1.0, 2.0, 0.5, 1.8, 1000)]

    monkeypatch.setattr(stocks_routes, "_ensure_eod_or_http_error", fake_ensure)
    monkeypatch.setattr(stocks_routes, "_select_eod_ohlc", fake_select)
    async with _client() as client:
        resp = await client.get("/stocks/spy/timeseries?range=1Y")
    assert resp.status_code == 200
    body = resp.json()
    t = int(dt.datetime(2026, 6, 11, tzinfo=dt.UTC).timestamp() * 1000)
    assert body["interval"] == "daily"
    assert body["ohlc"] == [[t, 1.0, 2.0, 0.5, 1.8]]
    assert body["volume"] == [[t, 1000.0]]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_stocks_timeseries_route.py -v`
Expected: FAIL (route missing).

- [ ] **Step 3: Implement the route**

In `backend/app/api/routes/stocks.py`, add imports and a module-level seam + route:

```python
from app.schemas.timeseries import OhlcSeriesResponse
from app.services.timeseries import (
    RangeKey,
    range_start,
    resolve_interval,
    select_eod_ohlc as _select_eod_ohlc_impl,
    to_ms_ohlc,
)

# Module-level alias so tests can monkeypatch the DB read.
_select_eod_ohlc = _select_eod_ohlc_impl


@router.get("/{ticker}/timeseries", response_model=OhlcSeriesResponse)
async def get_stock_timeseries(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
    range: Annotated[RangeKey, Query(description="Visible range preset.")] = "1Y",
) -> OhlcSeriesResponse:
    """Adjusted OHLC + volume in Highcharts Stock arrays; granularity by range."""
    symbol = ticker.strip().upper()
    today = dt.date.today()
    interval = resolve_interval(range)
    start = range_start(range, today)
    # Warm raw daily before any read (keeps the cache fresh for all intervals).
    await _ensure_eod_or_http_error(
        session, client, [symbol], start or (today - dt.timedelta(days=3650)), today
    )
    rows = await _select_eod_ohlc(session, symbol, interval, start)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No price data for {symbol}.")
    ohlc, volume = to_ms_ohlc(rows)
    return OhlcSeriesResponse(id=symbol, interval=interval, ohlc=ohlc, volume=volume)
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_stocks_timeseries_route.py tests/test_stocks_history_route.py -v`
Expected: PASS (new route + existing history route untouched).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/stocks.py backend/tests/test_stocks_timeseries_route.py
git commit -m "feat(stocks): GET /stocks/{ticker}/timeseries (Highcharts OHLC arrays)"
```

### Task 3.4: `GET /funds/{id}/timeseries`

**Files:**
- Modify: `backend/app/api/routes/funds.py`
- Test: `backend/tests/test_funds_timeseries_route.py`

- [ ] **Step 1: Write the failing test**

```python
"""GET /funds/{id}/timeseries — Highcharts NAV line arrays (DB stubbed)."""
import datetime as dt
import uuid
from httpx import ASGITransport, AsyncClient

import app.api.routes.funds as funds_routes
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_fund_timeseries_line_arrays(monkeypatch) -> None:
    async def fake_select(session, instrument_id, interval, start):
        assert str(instrument_id) == str(_FUND_ID) and interval == "weekly"
        return [(dt.date(2026, 6, 5), 306.2)]

    monkeypatch.setattr(funds_routes, "_select_nav_line", fake_select)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/timeseries?range=5Y")
    assert resp.status_code == 200
    body = resp.json()
    t = int(dt.datetime(2026, 6, 5, tzinfo=dt.UTC).timestamp() * 1000)
    assert body["interval"] == "weekly"
    assert body["series"] == [[t, 306.2]]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_funds_timeseries_route.py -v`
Expected: FAIL (route missing).

- [ ] **Step 3: Implement the route**

In `backend/app/api/routes/funds.py`, add:

```python
from app.schemas.timeseries import LineSeriesResponse
from app.services.timeseries import (
    RangeKey,
    range_start,
    resolve_interval,
    select_nav_line as _select_nav_line_impl,
    to_ms_pairs,
)

_select_nav_line = _select_nav_line_impl  # monkeypatch seam


@router.get("/funds/{instrument_id}/timeseries", response_model=LineSeriesResponse)
async def get_fund_timeseries(
    instrument_id: uuid.UUID,
    session: SessionDep,
    range: Annotated[RangeKey, Query(description="Visible range preset.")] = "1Y",
) -> LineSeriesResponse:
    """Fund NAV line in Highcharts arrays; granularity by range (raw/weekly/monthly CAGG)."""
    today = dt.date.today()
    interval = resolve_interval(range)
    start = range_start(range, today)
    rows = await _select_nav_line(session, str(instrument_id), interval, start)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No NAV history for fund {instrument_id}.")
    return LineSeriesResponse(id=str(instrument_id), interval=interval, series=to_ms_pairs(rows))
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_funds_timeseries_route.py tests/test_fund_history_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/funds.py backend/tests/test_funds_timeseries_route.py
git commit -m "feat(funds): GET /funds/{id}/timeseries (Highcharts NAV arrays)"
```

---

## PHASE 4 — Decommission snapshots (after parity green)

### Task 4.1: Retire the sync cron and deprecate snapshot tables

**Files:**
- Delete: `backend/railway.toml` (the fund-catalog-sync cron config)
- Modify: `backend/Dockerfile` (stop copying `scripts/` if only used by the retired cron)
- Modify: `backend/db/ddl/2026-06-13_dynamic_catalog.sql` (append the rename section — RUN ONLY after Phase 2/3 parity is green and the new code is deployed)

- [ ] **Step 1: Append the deprecation DDL (do NOT execute yet)**

```sql
-- PHASE 4 — run ONLY after the dynamic path is verified in production.
ALTER TABLE IF EXISTS funds            RENAME TO funds_deprecated;
ALTER TABLE IF EXISTS fund_risk_latest RENAME TO fund_risk_latest_deprecated;
ALTER TABLE IF EXISTS fund_nav         RENAME TO fund_nav_deprecated;
ALTER TABLE IF EXISTS fund_holdings    RENAME TO fund_holdings_deprecated;
ALTER TABLE IF EXISTS fund_classes     RENAME TO fund_classes_deprecated;
```

- [ ] **Step 2: Remove the retired cron config**

```bash
git rm backend/railway.toml
```

(The workers repo retains its own cron services; this file was the Light's snapshot sync, now obsolete.)

- [ ] **Step 3: Verify nothing imports the sync at runtime**

Run: `cd backend && uv run python -c "import app.main"` then `grep -rn "sync.funds\|sync_funds" app/ | grep -v tests`
Expected: app imports cleanly; no runtime import of the sync from `app/` (only `scripts/` referenced it).

- [ ] **Step 4: Commit (code only — the rename SQL stays unexecuted until the runbook flip)**

```bash
git add -A backend/railway.toml backend/db/ddl/2026-06-13_dynamic_catalog.sql backend/Dockerfile
git commit -m "chore(decommission): retire fund-catalog-sync cron; stage snapshot rename DDL"
```

### Task 4.2: Delete the dead sync code + worker REFRESH coordination

**Files:**
- Delete: `backend/app/sync/funds.py`, `backend/scripts/sync_funds.py`
- Modify: `backend/app/models/fund.py` (remove `FundNav` model — no longer mapped)
- Modify: `docs/superpowers/runbooks/2026-06-13-railway-api-deploy.md` (worker REFRESH note already present — mark as required)

- [ ] **Step 1: Remove the dead modules and model**

```bash
git rm backend/app/sync/funds.py backend/scripts/sync_funds.py
```

Remove the `FundNav` class from `backend/app/models/fund.py` and any now-dead import of it. Update `backend/tests/test_funds_sync.py` — delete it (the sync it tested is gone) or convert its useful pure-helper assertions into `funds_v` parity notes.

- [ ] **Step 2: Run the full suite**

Run: `cd backend && uv run pytest -q && uv run ruff check && uv run mypy app`
Expected: all green; no references to removed symbols.

- [ ] **Step 3: Confirm the worker REFRESH is scheduled (cross-repo)**

In `investintell-datalake-workers`, the `risk_metrics` worker must append, after its commit:
`REFRESH MATERIALIZED VIEW CONCURRENTLY fund_risk_latest_mv;`
This is the only thing keeping `fund_risk_latest_mv` fresh once the sync is gone. Track as a linked task in that repo; until it lands, refresh manually post-run.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(decommission): delete sync_funds + FundNav; document worker REFRESH"
```

---

## Self-Review

**Spec coverage:**
- §1 Deploy → Task 0.1/0.2. ✓
- §2 Persistence + CAGGs → Tasks 2.1–2.5 (D1 MV, D2 funds_v VIEW, D3 CAGGs). ✓
- §3 Timeseries endpoints → Tasks 3.3/3.4. ✓
- §4 Auth → Tasks 1.1–1.3 (JWKS/RS256, boundary public vs protected). ✓
- §5 Highcharts arrays → Tasks 3.1/3.2 + routes. ✓
- Non-goal "no Railway flip" honored (runbook only). Snapshot rename-not-drop honored (Task 4.1). ✓

**Placeholder scan:** No "TBD/TODO/handle edge cases". Two explicit executor NOTEs (the `instruments_universe.attributes->>'series_id'` join key in Task 2.3 and the holdings cap in Task 2.5) are gated by concrete parity queries with expected `0`, not vague instructions.

**Type/name consistency:** `_select_eod_ohlc`/`select_eod_ohlc`, `_select_nav_line`/`select_nav_line`, `resolve_interval`, `range_start`, `to_ms_pairs`, `to_ms_ohlc`, `LineSeriesResponse`/`OhlcSeriesResponse`, `fund_risk_latest_mv`, `funds_v`, `CurrentUser`, `get_current_user`, `verify_bearer` are used consistently across tasks. CAGG names (`cagg_eod_weekly/monthly`, `cagg_nav_weekly`) match between the DDL and the service's `_EOD_TABLE`/`_NAV_TABLE` maps.

**Known risk flagged for execution:** Tasks 2.2/2.3 carry latent model-vs-table column drift (the live `fund_risk_latest` has 33 cols; the model declared more). The reconcile step + parity queries make this explicit; the executor trims the model to the MV's column set.
