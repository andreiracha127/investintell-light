-- backend/db/ddl/2026-06-21_fund_style_drift_mv.sql
-- A2 — Style drift db-first. Materializa a MESMA agregação de
-- fetch_fund_style_drift (sec_nport_holdings → setor por CUSIP/N-PORT case-map →
-- SUM(pct_of_nav) por report_date+sector), SEM o LIMIT de quarters (o quarters
-- vira filtro na leitura). weight fica em percent-points (igual a SUM(pct_of_nav));
-- o backend divide por 100 ao montar FundStyleSectorWeight.weight (paridade).
-- Refrescada por matview_refresh (REFRESH … CONCURRENTLY exige o índice UNIQUE).

CREATE MATERIALIZED VIEW IF NOT EXISTS fund_style_drift_mv AS
WITH resolved AS (
    SELECT h.series_id,
           h.report_date,
           COALESCE(
               NULLIF(btrim(m.gics_sector), ''),
               CASE upper(btrim(h.sector))
                   WHEN 'CORP'  THEN 'Corporate'
                   WHEN 'UST'   THEN 'U.S. Treasury'
                   WHEN 'GOVT'  THEN 'Government'
                   WHEN 'USGA'  THEN 'U.S. Gov Agency'
                   WHEN 'MUNI'  THEN 'Municipal'
                   WHEN 'MUN'   THEN 'Municipal'
                   WHEN 'MBS'   THEN 'Mortgage-Backed'
                   WHEN 'ABS'   THEN 'Asset-Backed'
                   WHEN 'CMO'   THEN 'Collateralized Mortgage'
                   WHEN 'SUPRA' THEN 'Supranational'
                   WHEN 'NUSS'  THEN 'Non-U.S. Sovereign'
                   WHEN 'RF'    THEN 'Registered Fund'
                   ELSE NULLIF(btrim(h.sector), '')
               END,
               'Unknown'
           ) AS sector,
           h.pct_of_nav
    FROM sec_nport_holdings h
    LEFT JOIN LATERAL (
        SELECT gics_sector
        FROM sec_cusip_ticker_map
        WHERE cusip = h.cusip
          AND NULLIF(btrim(gics_sector), '') IS NOT NULL
        LIMIT 1
    ) m ON TRUE
)
SELECT series_id, report_date, sector, SUM(pct_of_nav) AS weight
FROM resolved
GROUP BY series_id, report_date, sector
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS fund_style_drift_mv_pk
  ON fund_style_drift_mv (series_id, report_date, sector);

-- Aceleração de leitura: filtro por série + ordenação por report_date desc.
CREATE INDEX IF NOT EXISTS fund_style_drift_mv_series_date_idx
  ON fund_style_drift_mv (series_id, report_date DESC);

REFRESH MATERIALIZED VIEW fund_style_drift_mv;
