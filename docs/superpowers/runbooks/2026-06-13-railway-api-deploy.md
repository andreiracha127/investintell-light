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
4. Regenerate the frontend API types so they match the slimmed contract: `FundRiskOut`
   dropped 15 always-null asset-class analytics fields (scoring_model, empirical_duration,
   credit_beta, …). Run the OpenAPI export + the frontend codegen
   (`backend/scripts/export_openapi.py` → regenerate `frontend/src/.../api.d.ts`) and
   commit the updated `backend/openapi.json` + `api.d.ts`. The frontend still compiles
   without this (the dropped fields were optional and always null), so it is non-blocking,
   but keep the generated client in sync.

## Tiger DDL rollback (if needed)
Run backend/db/ddl/2026-06-13_dynamic_catalog.sql is additive. To roll back:
  DROP MATERIALIZED VIEW IF EXISTS cagg_eod_weekly, cagg_eod_monthly, cagg_nav_weekly, fund_risk_latest_mv CASCADE;
  DROP VIEW IF EXISTS funds_v, fund_holdings_v, fund_classes_v CASCADE;

Phase-4 staged rename (`fund_nav → fund_nav_deprecated`) is SAFE to execute at
flip time: after Task 4.3 the `fund_nav` snapshot is fully unread — the FundNav
ORM model reads the live `nav_timeseries` hypertable directly, and nothing in
app/ references the `fund_nav` table name anymore.

## Worker coordination (Phase 4) — REQUIRED, not optional
`fund_risk_latest_mv` is a PLAIN materialized view: it does NOT auto-refresh.
Until it is refreshed it keeps serving the calc that was current when it was
last populated, so EVERY fund risk metric the API returns (GET /funds,
/funds/{id}, screener) silently goes stale after the daily risk calc runs.

REQUIRED: the `risk_metrics` worker (repo `investintell-datalake-workers`) MUST
run the following as the LAST step of its daily job, AFTER it commits the new
fund_risk_metrics rows:
  REFRESH MATERIALIZED VIEW CONCURRENTLY fund_risk_latest_mv;
(CONCURRENTLY needs the unique index `fund_risk_latest_mv_pk` on instrument_id,
created by 2026-06-13_dynamic_catalog.sql — already in place.)

This repo (investintell-light) CANNOT make that change; it must be applied in
investintell-datalake-workers. If the worker run cannot refresh, run the REFRESH
manually after the calc — the MV is the API's sole source of fund risk metrics.
