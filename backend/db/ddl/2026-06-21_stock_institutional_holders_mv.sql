-- backend/db/ddl/2026-06-21_stock_institutional_holders_mv.sql
-- B1 read-model (datalake DB): holders 13F (universo >$5bn) por ticker no
-- período mais recente, com manager_name resolvido em 3 níveis, entry_date da
-- MV sec_13f_entry e entry_price/current_price/shares_outstanding já resolvidos.
-- Refrescado por matview_refresh (passo datalake). Espelha _HOLDERS_SQL de
-- backend/app/services/stock_holders.py (paridade exata).
--
-- NOTA price_latest_mv: NÃO usado aqui. entry_price = primeiro adj_close em/após
-- entry_date (data arbitrária) — price_latest_mv só tem last/prev close. Mantemos
-- o subquery de eod_prices para entry_price e current_price.

CREATE MATERIALIZED VIEW IF NOT EXISTS stock_institutional_holders_mv AS
WITH map AS (
    SELECT DISTINCT upper(ticker) AS ticker, upper(cusip) AS cusip
    FROM sec_cusip_ticker_map
    WHERE cusip IS NOT NULL AND ticker IS NOT NULL
),
latest AS (
    SELECT max(report_date) AS period FROM sec_13f_holdings
),
base AS (
    SELECT
        m.ticker,
        h.cik,
        COALESCE(fn.filer_name, mgr.firm_name, 'CIK ' || h.cik) AS manager_name,
        h.report_date,
        upper(h.cusip) AS cusip,
        h.issuer_name,
        h.shares,
        h.market_value,
        entry.entry_date
    FROM sec_13f_holdings h
    JOIN map m ON m.cusip = upper(h.cusip)
    LEFT JOIN sec_13f_filer_name fn ON fn.cik = lpad(h.cik, 10, '0')
    LEFT JOIN LATERAL (
        SELECT m.firm_name
        FROM sec_managers m
        WHERE m.cik = lpad(h.cik, 10, '0') AND m.firm_name IS NOT NULL
        ORDER BY m.aum_total DESC NULLS LAST
        LIMIT 1
    ) mgr ON true
    LEFT JOIN sec_13f_entry entry ON entry.cik = h.cik AND entry.cusip = h.cusip
    WHERE h.report_date = (SELECT period FROM latest)
)
SELECT
    base.ticker,
    base.cik,
    base.manager_name,
    base.report_date,
    base.cusip,
    base.issuer_name,
    base.shares,
    base.market_value,
    base.entry_date,
    -- primeiro adj_close em/após a data de entrada (preço de custo aproximado)
    (SELECT p.adj_close FROM eod_prices p
     WHERE p.ticker = base.ticker AND p.date >= base.entry_date
     ORDER BY p.date ASC LIMIT 1) AS entry_price,
    -- último adj_close conhecido do ticker
    (SELECT p.adj_close FROM eod_prices p
     WHERE p.ticker = base.ticker
     ORDER BY p.date DESC LIMIT 1) AS current_price,
    -- shares outstanding mais recentes (para % de ownership)
    (SELECT f.shares_outstanding FROM fundamentals_snapshot f
     WHERE upper(f.ticker) = base.ticker AND f.shares_outstanding > 0
     ORDER BY f.period_end DESC LIMIT 1) AS shares_outstanding
FROM base
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS stock_institutional_holders_mv_pk
    ON stock_institutional_holders_mv (ticker, cik, cusip);
CREATE INDEX IF NOT EXISTS stock_institutional_holders_mv_ticker
    ON stock_institutional_holders_mv (ticker);

-- Supporting index (base table): the shares_outstanding subquery matches on
-- upper(f.ticker); without a functional index this seq-scans fundamentals_snapshot
-- once PER holder row (~770k rows in the latest 13F period => ~4B comparisons).
-- This functional index turns that subquery into an index probe. Apply BEFORE the
-- initial REFRESH or the populate runs for many minutes.
CREATE INDEX IF NOT EXISTS fundamentals_snapshot_upper_ticker_idx
    ON fundamentals_snapshot (upper(ticker));

REFRESH MATERIALIZED VIEW stock_institutional_holders_mv;
