-- backend/db/ddl/2026-06-21_stock_fund_holders_mv.sql
-- B2 read-model (datalake DB): funds registrados (N-PORT) que detêm o ticker,
-- agregados por (ticker, series_id), com family resolvida em 3 níveis, fund_name,
-- instrument_id e trilha de 4 trimestres. Espelha _FUND_HOLDERS_SQL de
-- backend/app/services/stock_holders.py. O agrupamento family->funds é feito no
-- backend (sem cálculo). Refrescado por matview_refresh (passo datalake).

CREATE MATERIALIZED VIEW IF NOT EXISTS stock_fund_holders_mv AS
WITH map AS (
    SELECT DISTINCT upper(ticker) AS ticker, upper(cusip) AS cusip
    FROM sec_cusip_ticker_map
    WHERE cusip IS NOT NULL AND ticker IS NOT NULL
),
bounds AS (SELECT max(report_date) AS m FROM nport_holdings_history)
SELECT
    map.ticker,
    n.cik AS registrant_cik,
    COALESCE(fam.entity_name, sc.entity_name, 'CIK ' || n.cik) AS family,
    n.series_id,
    COALESCE(sc.series_name, n.series_id) AS fund_name,
    fv.instrument_id AS instrument_id,
    max(n.issuer_name) AS issuer_name,
    sum(n.quantity) AS quantity,
    sum(n.market_value) AS market_value,
    max(n.pct_nav_0) AS pct_of_nav,
    max(n.pct_nav_1) AS pct_nav_q1,
    max(n.pct_nav_2) AS pct_nav_q2,
    max(n.pct_nav_3) AS pct_nav_q3,
    max(n.report_date) AS report_date,
    map.cusip AS cusip
FROM nport_holdings_history n
JOIN map ON n.cusip = map.cusip
LEFT JOIN LATERAL (
    SELECT entity_name, series_name
    FROM sec_investment_company_series_class c
    WHERE c.series_id = n.series_id
    LIMIT 1
) sc ON true
LEFT JOIN LATERAL (
    SELECT entity_name
    FROM sec_investment_company_series_class c
    WHERE c.registrant_cik = n.cik
    LIMIT 1
) fam ON true
LEFT JOIN fund_instrument_map fv ON fv.series_id = n.series_id
WHERE n.report_date >= (SELECT m FROM bounds) - interval '130 days'
GROUP BY map.ticker, n.cik, fam.entity_name, sc.entity_name, n.series_id,
         sc.series_name, fv.instrument_id, map.cusip
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS stock_fund_holders_mv_pk
    ON stock_fund_holders_mv (ticker, series_id);
CREATE INDEX IF NOT EXISTS stock_fund_holders_mv_ticker
    ON stock_fund_holders_mv (ticker);

REFRESH MATERIALIZED VIEW stock_fund_holders_mv;
