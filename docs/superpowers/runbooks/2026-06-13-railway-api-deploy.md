# Runbook — Deploy FastAPI to Railway (api service)

## STATUS: EXECUTED 2026-06-14
The flip is live. The Railway `api` service serves the catalog/timeseries +
authenticated user routes from Tiger; the legacy InsForge `investintell-api`
compute is stopped; the Vercel frontend points at Railway; the snapshot tables
are renamed `*_deprecated`. Concrete values below reflect what was applied.

- Railway service: `api` (id 6c7ae990-2751-466e-89d0-5b94c72f4679), project
  `investintell-light` (f8f11e07-409d-45c0-835e-3338bef02ead), env `production`.
- Public URL: https://api-production-2b6d.up.railway.app
- Deployed via `railway up` (tarball; no GitHub remote). Railway reads
  `backend/railway.toml` (dockerfile builder, healthcheck `/health`); the
  Dockerfile CMD is shell-form so it binds Railway's `$PORT`.

## Prereqs
- Railway project `investintell-light`, env `production`.
- Tiger `t83f4np6x4` (`tsdb` db, `public` schema) reachable from Railway.

## Env vars (NEVER commit these — set on the Railway service)
- DATABASE_URL    = postgresql+asyncpg://…@t83f4np6x4…:33132/tsdb?ssl=require
  # MUST be pre-normalized: the main engine (app/core/db.py) does NOT translate
  # the DSN. Use the `+asyncpg` driver and `ssl=require` (NOT libpq `sslmode=`).
- DATALAKE_DB_URL = postgresql://…@t83f4np6x4…:33132/tsdb?sslmode=require
  # raw libpq form is fine here — app/core/datalake.py normalizes it.
- INSFORGE_JWT_SECRET = <InsForge JWT_SECRET>  # HS256 shared secret (NOT JWKS)
  # InsForge issues HS256 tokens signed with this shared secret (no JWKS, no
  # iss/aud). auth.py verifies signature + exp + sub locally. Source of truth:
  # `npx @insforge/cli secrets get JWT_SECRET`.
- CORS_ALLOW_ORIGINS = ["https://jgpu5cz3.insforge.site","https://www.investintell.com","https://investintell.com","http://localhost:3000","http://127.0.0.1:3000"]
  # The production frontend origin is the Vercel app jgpu5cz3.insforge.site.
- TIINGO_TOKEN = <token>
- REDIS_URL = <optional; unset → in-process memory cache, fail-open>

## Deploy / flip — executed sequence (the safe order; renames MUST be last)
1. Deploy + confirm `/health` 200 (Railway health-gates on it).
2. Smoke: GET /funds, GET /stocks/SPY/timeseries?range=1Y (public); GET
   /portfolios with a valid HS256 token → 200, without → 401.
3. Point the frontend at Railway: `deployments env set NEXT_PUBLIC_API_URL
   <railway-url>` + `deployments deploy frontend --env {…}` (Vercel rebuild —
   NEXT_PUBLIC_* are baked at build time).
4. Decommission the legacy API: `compute stop <investintell-api id>` (reversible
   via `compute start`). Auth/login stays up — it is the InsForge backend, not
   this compute.
5. ONLY NOW rename the snapshot tables (they break the legacy reader the instant
   they run; the Railway API reads the dynamic views, unaffected):
     ALTER TABLE IF EXISTS funds            RENAME TO funds_deprecated;
     ALTER TABLE IF EXISTS fund_risk_latest RENAME TO fund_risk_latest_deprecated;
     ALTER TABLE IF EXISTS fund_nav         RENAME TO fund_nav_deprecated;
     ALTER TABLE IF EXISTS fund_holdings    RENAME TO fund_holdings_deprecated;
     ALTER TABLE IF EXISTS fund_classes     RENAME TO fund_classes_deprecated;

## Rollback
- API: `compute start <investintell-api id>` + revert `NEXT_PUBLIC_API_URL` to the
  InsForge endpoint + redeploy frontend.
- Tables: `ALTER TABLE <x>_deprecated RENAME TO <x>;` (reverse of step 5).
- Additive Tiger objects: DROP MATERIALIZED VIEW IF EXISTS cagg_eod_weekly,
  cagg_eod_monthly, cagg_nav_weekly, fund_risk_latest_mv CASCADE; DROP VIEW IF
  EXISTS funds_v, fund_holdings_v, fund_classes_v CASCADE;

## Worker coordination — DONE
`fund_risk_latest_mv` is a PLAIN materialized view (no auto-refresh). The
`risk_metrics` worker (repo `investintell-datalake-workers`, branch
`feat/risk-metrics-mv-refresh`) now runs, as the last step of a successful daily
run, in a fresh autocommit connection OUTSIDE the advisory lock:
  REFRESH MATERIALIZED VIEW CONCURRENTLY fund_risk_latest_mv;
(CONCURRENTLY needs the unique index `fund_risk_latest_mv_pk`, already in place.)
That branch must be merged + the worker redeployed for the refresh to run in prod.
