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
