-- Materialized projection for the interactive GET /funds table.
--
-- funds_v remains the canonical lineage view, but it is too expensive to serve
-- every list miss directly because it recomputes eligibility, classification,
-- NAV/AUM fallbacks, and N-PORT joins. This MV flattens the list payload plus
-- sortable risk metrics into a small indexed rowset.

DROP MATERIALIZED VIEW IF EXISTS funds_list_mv;

CREATE MATERIALIZED VIEW funds_list_mv AS
WITH nav_staleness AS (
    SELECT max(nav_date) AS source_nav_max_date
    FROM nav_timeseries
)
SELECT
    f.instrument_id,
    f.series_id,
    f.ticker,
    f.name,
    f.fund_type,
    f.strategy_label,
    f.asset_class,
    f.is_index,
    f.expense_ratio,
    f.aum_usd,
    f.inception_date,
    r.calc_date,
    ns.source_nav_max_date,
    r.return_1m,
    r.return_3m,
    CASE
        WHEN r.return_1y IS NULL OR abs(r.return_1y) > 10 THEN NULL
        ELSE r.return_1y
    END AS return_1y,
    r.return_3y_ann,
    r.return_5y_ann,
    r.volatility_1y,
    r.max_drawdown_1y,
    r.max_drawdown_3y,
    r.sharpe_1y,
    r.sharpe_3y,
    r.sortino_1y,
    r.calmar_ratio_3y,
    r.alpha_1y,
    r.beta_1y,
    r.information_ratio_1y,
    r.tracking_error_1y,
    r.var_95_1m,
    r.cvar_95_1m,
    r.cvar_95_12m,
    r.cvar_99_evt,
    r.peer_strategy_label,
    r.peer_sharpe_pctl,
    r.peer_sortino_pctl,
    r.peer_return_pctl,
    r.peer_drawdown_pctl,
    r.peer_count,
    r.manager_score,
    r.blended_momentum_score,
    r.elite_flag,
    r.downside_capture_1y,
    r.upside_capture_1y,
    r.equity_correlation_252d
FROM funds_v f
LEFT JOIN fund_risk_latest_mv r ON r.instrument_id = f.instrument_id
CROSS JOIN nav_staleness ns
WHERE f.strategy_label IS DISTINCT FROM 'Unclassified'
  AND f.aum_usd IS NOT NULL;

CREATE UNIQUE INDEX funds_list_mv_pk
    ON funds_list_mv (instrument_id);

CREATE INDEX funds_list_mv_aum_sort_idx
    ON funds_list_mv (aum_usd DESC NULLS LAST, ticker, instrument_id);

CREATE INDEX funds_list_mv_ticker_sort_idx
    ON funds_list_mv (ticker ASC NULLS LAST, instrument_id);

CREATE INDEX funds_list_mv_name_sort_idx
    ON funds_list_mv (name ASC, instrument_id);

CREATE INDEX funds_list_mv_filters_idx
    ON funds_list_mv (fund_type, asset_class, strategy_label);

CREATE INDEX funds_list_mv_sharpe_sort_idx
    ON funds_list_mv (sharpe_1y DESC NULLS LAST, ticker, instrument_id);

CREATE INDEX funds_list_mv_risk_filters_idx
    ON funds_list_mv (return_1y, volatility_1y, max_drawdown_1y);
