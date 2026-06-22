-- backend/db/ddl/2026-06-21_fund_top_holdings_mv.sql
-- A4 — Top holdings db-first. Top-50 holdings por série no report_date mais
-- recente, com GICS já resolvido por CUSIP (sec_cusip_ticker_map). O limit do
-- endpoint vira WHERE rank <= :limit na leitura. O sector breakdown NÃO é
-- materializado aqui — continua lido de nport_lookthrough_exposures (A4 / spec).
-- Refrescada por matview_refresh (REFRESH … CONCURRENTLY exige o índice UNIQUE).

CREATE MATERIALIZED VIEW IF NOT EXISTS fund_top_holdings_mv AS
WITH latest AS (
    SELECT series_id, max(report_date) AS report_date
    FROM sec_nport_holdings
    GROUP BY series_id
),
ranked AS (
    SELECT h.series_id,
           h.report_date,
           row_number() OVER (
               PARTITION BY h.series_id
               ORDER BY h.pct_of_nav DESC NULLS LAST, h.market_value DESC NULLS LAST
           ) AS rank,
           h.issuer_name,
           upper(h.cusip) AS cusip,
           h.isin,
           h.asset_class,
           h.sector,
           h.market_value,
           h.pct_of_nav
    FROM sec_nport_holdings h
    JOIN latest l ON l.series_id = h.series_id AND l.report_date = h.report_date
)
SELECT r.series_id,
       r.report_date,
       r.rank,
       r.issuer_name,
       r.cusip,
       r.isin,
       r.asset_class,
       r.sector,
       NULLIF(btrim(m.gics_sector), '') AS gics_sector,
       r.market_value,
       r.pct_of_nav
FROM ranked r
LEFT JOIN LATERAL (
    SELECT gics_sector
    FROM sec_cusip_ticker_map
    WHERE cusip = r.cusip
      AND NULLIF(btrim(gics_sector), '') IS NOT NULL
    LIMIT 1
) m ON TRUE
WHERE r.rank <= 50
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS fund_top_holdings_mv_pk
  ON fund_top_holdings_mv (series_id, report_date, rank);

REFRESH MATERIALIZED VIEW fund_top_holdings_mv;
