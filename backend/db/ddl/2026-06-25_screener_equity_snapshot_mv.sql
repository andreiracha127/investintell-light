-- Materialized read model for the equities screener.
--
-- The request path filters, sorts and builds histograms over this active-only
-- projection instead of joining universe_constituents to screener_metrics per
-- request.  Re-run after refreshing screener_metrics.

DROP MATERIALIZED VIEW IF EXISTS screener_equity_snapshot_mv_new;

CREATE MATERIALIZED VIEW screener_equity_snapshot_mv_new AS
SELECT
    uc.ticker,
    uc.name,
    uc.sector,
    uc.status,
    sm.computed_at,
    sm.as_of,
    sm.ret_1w,
    sm.ret_1m,
    sm.ret_3m,
    sm.ret_6m,
    sm.ret_1y,
    sm.ret_ytd,
    sm.ret_mtd,
    sm.vol_1m,
    sm.vol_3m,
    sm.vol_6m,
    sm.vol_1y,
    sm.beta_3m_spy,
    sm.beta_6m_spy,
    sm.beta_1y_spy,
    sm.beta_2y_spy,
    sm.corr_spy,
    sm.corr_gld,
    sm.corr_agg,
    sm.corr_tlt,
    sm.corr_uso,
    sm.pct_above_sma20,
    sm.pct_above_sma50,
    sm.pct_above_sma200,
    sm.price_close,
    sm.avg_volume_1m,
    sm.market_cap,
    sm.pe_ratio,
    sm.roe,
    sm.roa,
    sm.gross_margin,
    sm.de_ratio,
    sm.investment_growth,
    sm.profitability_gross,
    sm.fundamentals_period_end
FROM universe_constituents uc
LEFT JOIN screener_metrics sm ON sm.ticker = uc.ticker
WHERE uc.status = 'active';

CREATE UNIQUE INDEX screener_equity_snapshot_mv_new_pk
    ON screener_equity_snapshot_mv_new (ticker);

CREATE INDEX screener_equity_snapshot_mv_new_status_ticker_idx
    ON screener_equity_snapshot_mv_new (status, ticker);

CREATE INDEX screener_equity_snapshot_mv_new_ticker_lower_prefix_idx
    ON screener_equity_snapshot_mv_new (lower(ticker) text_pattern_ops);

CREATE INDEX screener_equity_snapshot_mv_new_name_lower_prefix_idx
    ON screener_equity_snapshot_mv_new (lower(name) text_pattern_ops);

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS screener_equity_snapshot_mv;
ALTER MATERIALIZED VIEW screener_equity_snapshot_mv_new RENAME TO screener_equity_snapshot_mv;
ALTER INDEX screener_equity_snapshot_mv_new_pk RENAME TO screener_equity_snapshot_mv_pk;
ALTER INDEX screener_equity_snapshot_mv_new_status_ticker_idx RENAME TO screener_equity_snapshot_mv_status_ticker_idx;
ALTER INDEX screener_equity_snapshot_mv_new_ticker_lower_prefix_idx RENAME TO screener_equity_snapshot_mv_ticker_lower_prefix_idx;
ALTER INDEX screener_equity_snapshot_mv_new_name_lower_prefix_idx RENAME TO screener_equity_snapshot_mv_name_lower_prefix_idx;
COMMIT;

ANALYZE screener_equity_snapshot_mv;
