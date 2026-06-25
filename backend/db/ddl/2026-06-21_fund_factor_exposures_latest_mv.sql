-- backend/db/ddl/2026-06-21_fund_factor_exposures_latest_mv.sql
-- A1 — read-model do backend: última exposição de fator por (instrument_id, factor).
-- Alimentado pelo worker fund_factors (escreve fund_factor_exposures). Refrescado
-- por esse worker (REFRESH … CONCURRENTLY exige o índice UNIQUE abaixo).
DROP MATERIALIZED VIEW IF EXISTS fund_factor_exposures_latest_mv;
CREATE MATERIALIZED VIEW IF NOT EXISTS fund_factor_exposures_latest_mv AS
SELECT DISTINCT ON (instrument_id, factor)
       instrument_id, factor, beta, t_stat, significance, as_of
FROM fund_factor_exposures
WHERE organization_id IS NULL
ORDER BY instrument_id, factor, as_of DESC;

CREATE UNIQUE INDEX IF NOT EXISTS fund_factor_exposures_latest_mv_pk
  ON fund_factor_exposures_latest_mv (instrument_id, factor);

REFRESH MATERIALIZED VIEW fund_factor_exposures_latest_mv;
