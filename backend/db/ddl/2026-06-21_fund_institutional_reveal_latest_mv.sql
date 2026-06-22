-- backend/db/ddl/2026-06-21_fund_institutional_reveal_latest_mv.sql
-- A3 — read-model do backend: artefato JSONB mais recente por série.
-- Alimentado pelo worker fund_institutional_reveal. REFRESH … CONCURRENTLY exige UNIQUE.
DROP MATERIALIZED VIEW IF EXISTS fund_institutional_reveal_latest_mv;
CREATE MATERIALIZED VIEW IF NOT EXISTS fund_institutional_reveal_latest_mv AS
SELECT DISTINCT ON (series_id)
       series_id, as_of, schema_version, payload
FROM fund_institutional_reveal_artifacts
WHERE organization_id IS NULL
ORDER BY series_id, as_of DESC;

CREATE UNIQUE INDEX IF NOT EXISTS fund_institutional_reveal_latest_mv_pk
  ON fund_institutional_reveal_latest_mv (series_id);

REFRESH MATERIALIZED VIEW fund_institutional_reveal_latest_mv;
