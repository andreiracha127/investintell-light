-- backend/db/ddl/2026-06-21_stock_institutional_holders_mv.sql
-- B1 read-model (datalake DB): holders 13F (universo >$5bn) por ticker no
-- período mais recente, com manager_name resolvido em 3 níveis, entry_date da
-- MV sec_13f_entry e entry_price/current_price/shares_outstanding já resolvidos.
-- Refrescado por matview_refresh (passo datalake). Espelha _HOLDERS_SQL de
-- backend/app/services/stock_holders.py (paridade exata).
--
-- PERF (redesign 2026-06-22): a versão original resolvia entry_price/current_price/
-- shares_outstanding via 3 SUBQUERIES CORRELACIONADAS por linha de holder. No
-- período mais recente há ~770k holders mas só ~7,2k tickers distintos e ~74k
-- pares (ticker, entry_date) distintos, então as subqueries recalculavam o mesmo
-- valor ~100x e o REFRESH passava de 14 min. Agora cada valor é precomputado UMA
-- vez por chave (CTEs current_px / so / entry_px) e ligado por JOIN — semântica
-- idêntica, ~25x menos probes correlacionados.
--
-- NOTA price_latest_mv: NÃO usado aqui. entry_price = primeiro adj_close em/após
-- entry_date (data arbitrária) — price_latest_mv só tem last/prev close. Mantemos
-- a leitura de eod_prices para entry_price e current_price.

DROP MATERIALIZED VIEW IF EXISTS stock_institutional_holders_mv;

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
        SELECT mm.firm_name
        FROM sec_managers mm
        WHERE mm.cik = lpad(h.cik, 10, '0') AND mm.firm_name IS NOT NULL
        ORDER BY mm.aum_total DESC NULLS LAST
        LIMIT 1
    ) mgr ON true
    LEFT JOIN sec_13f_entry entry ON entry.cik = h.cik AND entry.cusip = h.cusip
    WHERE h.report_date = (SELECT period FROM latest)
),
-- Conjunto de tickers a precificar (poucos milhares, não ~770k linhas).
tickers AS (
    SELECT DISTINCT ticker FROM base
),
-- current_price: último adj_close conhecido por ticker
-- (paridade com a subquery "ORDER BY p.date DESC LIMIT 1", sem filtro de NULL).
current_px AS (
    SELECT DISTINCT ON (e.ticker) e.ticker, e.adj_close AS current_price
    FROM eod_prices e
    JOIN tickers t ON t.ticker = e.ticker
    ORDER BY e.ticker, e.date DESC
),
-- shares_outstanding: último period_end com SO>0 por upper(ticker).
so AS (
    SELECT DISTINCT ON (upper(f.ticker)) upper(f.ticker) AS ticker, f.shares_outstanding
    FROM fundamentals_snapshot f
    WHERE f.shares_outstanding > 0
    ORDER BY upper(f.ticker), f.period_end DESC
),
-- entry_price: primeiro adj_close em/após entry_date, por par DISTINTO
-- (ticker, entry_date) — ~74k pares vs ~770k linhas. Mesma semântica do subquery.
entry_pairs AS (
    SELECT DISTINCT ticker, entry_date FROM base WHERE entry_date IS NOT NULL
),
entry_px AS (
    SELECT ep.ticker, ep.entry_date, e.adj_close AS entry_price
    FROM entry_pairs ep
    LEFT JOIN LATERAL (
        SELECT p.adj_close
        FROM eod_prices p
        WHERE p.ticker = ep.ticker AND p.date >= ep.entry_date
        ORDER BY p.date ASC
        LIMIT 1
    ) e ON true
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
    epx.entry_price,
    cpx.current_price,
    so.shares_outstanding
FROM base
LEFT JOIN entry_px epx
       ON epx.ticker = base.ticker
      AND epx.entry_date IS NOT DISTINCT FROM base.entry_date
LEFT JOIN current_px cpx ON cpx.ticker = base.ticker
LEFT JOIN so            ON so.ticker  = base.ticker
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS stock_institutional_holders_mv_pk
    ON stock_institutional_holders_mv (ticker, cik, cusip);
CREATE INDEX IF NOT EXISTS stock_institutional_holders_mv_ticker
    ON stock_institutional_holders_mv (ticker);

-- Supporting index (base table): a CTE `so` ordena por upper(ticker); o índice
-- funcional mantém esse passo trivial sem seq-scan.
CREATE INDEX IF NOT EXISTS fundamentals_snapshot_upper_ticker_idx
    ON fundamentals_snapshot (upper(ticker));

REFRESH MATERIALIZED VIEW stock_institutional_holders_mv;
