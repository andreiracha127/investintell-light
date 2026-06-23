-- NAV data-quality eligibility flag (Bug 2). Computed by the risk_metrics
-- worker; honored by the optimizer universe gate and the backtest service.
--
-- Additive + idempotent: both columns are nullable, so existing rows read NULL
-- (fail-open) until the worker populates them. The fund_risk_latest_mv
-- projection (2026-06-13_dynamic_catalog.sql) must be DROP/CREATE'd once for the
-- new columns to surface in the MV (the worker's REFRESH ... CONCURRENTLY then
-- keeps it fresh).
ALTER TABLE fund_risk_metrics
  ADD COLUMN IF NOT EXISTS nav_quality_ok boolean,
  ADD COLUMN IF NOT EXISTS nav_glitch_count integer;
