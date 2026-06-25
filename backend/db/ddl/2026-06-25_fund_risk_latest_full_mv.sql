-- Full latest risk read-model.
--
-- fund_risk_metrics is the rich worker-owned table; fund_risk_latest_mv is the
-- latest global row per instrument used by API/UI reads. Build the replacement
-- MVs under *_new names first, then swap names in a short transaction so the
-- request path is unavailable only for the metadata rename window.

DROP MATERIALIZED VIEW IF EXISTS fund_class_resolution_mv_new;
DROP MATERIALIZED VIEW IF EXISTS funds_list_mv_new;
DROP MATERIALIZED VIEW IF EXISTS fund_risk_latest_mv_new;

CREATE MATERIALIZED VIEW fund_risk_latest_mv_new AS
WITH latest_global AS (
    SELECT DISTINCT ON (instrument_id) *
    FROM fund_risk_metrics
    WHERE organization_id IS NULL
    ORDER BY instrument_id, calc_date DESC
),
latest_active_share AS (
    SELECT DISTINCT ON (instrument_id)
           instrument_id AS active_instrument_id,
           active_share_normalized AS as_active_share_normalized,
           overlap_normalized AS as_overlap_normalized,
           overlap_nav_raw AS as_overlap_nav_raw,
           fund_cusip_coverage_nav AS as_fund_cusip_coverage_nav,
           benchmark_cusip_coverage_nav AS as_benchmark_cusip_coverage_nav,
           n_fund_holdings AS as_n_fund_holdings,
           n_benchmark_holdings AS as_n_benchmark_holdings,
           n_common_holdings AS as_n_common_holdings,
           n_fund_only AS as_n_fund_only,
           n_benchmark_only AS as_n_benchmark_only,
           holdings_jaccard AS as_holdings_jaccard,
           fund_report_age_days AS as_fund_report_age_days,
           benchmark_report_age_days AS as_benchmark_report_age_days,
           report_date_gap_days AS as_report_date_gap_days,
           active_share_benchmark_instrument_id AS as_active_share_benchmark_instrument_id,
           active_share_benchmark_series_id AS as_active_share_benchmark_series_id,
           active_share_fund_report_date AS as_active_share_fund_report_date,
           active_share_benchmark_report_date AS as_active_share_benchmark_report_date
    FROM fund_risk_metrics
    WHERE organization_id IS NULL
      AND active_share_normalized IS NOT NULL
    ORDER BY instrument_id, active_share_fund_report_date DESC NULLS LAST, calc_date DESC
)
SELECT
       instrument_id,
       calc_date,
       organization_id,
       cvar_95_1m,
       cvar_95_3m,
       cvar_95_6m,
       cvar_95_12m,
       var_95_1m,
       var_95_3m,
       var_95_6m,
       var_95_12m,
       return_1m,
       return_3m,
       return_6m,
       return_1y,
       return_3y_ann,
       return_5y_ann,
       return_10y_ann,
       volatility_1y,
       volatility_garch,
       vol_model,
       max_drawdown_1y,
       max_drawdown_3y,
       sharpe_1y,
       sharpe_3y,
       sortino_1y,
       calmar_ratio_3y,
       alpha_1y,
       beta_1y,
       tracking_error_1y,
       information_ratio_1y,
       upside_capture_1y,
       downside_capture_1y,
       sharpe_cf,
       sharpe_cf_skew,
       sharpe_cf_kurt,
       sharpe_cf_ci_lower,
       sharpe_cf_ci_upper,
       cvar_99_evt,
       cvar_999_evt,
       evt_xi_shape,
       fed_funds_rate_at_calc,
       data_quality_flags,
       peer_strategy_label,
       peer_sharpe_pctl,
       peer_sortino_pctl,
       peer_return_pctl,
       peer_drawdown_pctl,
       peer_count,
       manager_score,
       elite_flag,
       equity_correlation_252d,
       empirical_duration,
       credit_beta,
       crisis_alpha_score,
       inflation_beta,
       COALESCE(active_share_normalized, as_active_share_normalized) AS active_share_normalized,
       COALESCE(overlap_normalized, as_overlap_normalized) AS overlap_normalized,
       COALESCE(overlap_nav_raw, as_overlap_nav_raw) AS overlap_nav_raw,
       COALESCE(fund_cusip_coverage_nav, as_fund_cusip_coverage_nav) AS fund_cusip_coverage_nav,
       COALESCE(benchmark_cusip_coverage_nav, as_benchmark_cusip_coverage_nav) AS benchmark_cusip_coverage_nav,
       COALESCE(n_fund_holdings, as_n_fund_holdings) AS n_fund_holdings,
       COALESCE(n_benchmark_holdings, as_n_benchmark_holdings) AS n_benchmark_holdings,
       COALESCE(n_common_holdings, as_n_common_holdings) AS n_common_holdings,
       COALESCE(n_fund_only, as_n_fund_only) AS n_fund_only,
       COALESCE(n_benchmark_only, as_n_benchmark_only) AS n_benchmark_only,
       COALESCE(holdings_jaccard, as_holdings_jaccard) AS holdings_jaccard,
       COALESCE(fund_report_age_days, as_fund_report_age_days) AS fund_report_age_days,
       COALESCE(benchmark_report_age_days, as_benchmark_report_age_days) AS benchmark_report_age_days,
       COALESCE(report_date_gap_days, as_report_date_gap_days) AS report_date_gap_days,
       COALESCE(active_share_benchmark_instrument_id, as_active_share_benchmark_instrument_id) AS active_share_benchmark_instrument_id,
       COALESCE(active_share_benchmark_series_id, as_active_share_benchmark_series_id) AS active_share_benchmark_series_id,
       COALESCE(active_share_fund_report_date, as_active_share_fund_report_date) AS active_share_fund_report_date,
       COALESCE(active_share_benchmark_report_date, as_active_share_benchmark_report_date) AS active_share_benchmark_report_date,
       score_components,
       dtw_drift_score,
       rsi_14,
       bb_position,
       nav_momentum_score,
       flow_momentum_score,
       blended_momentum_score,
       cvar_95_conditional,
       elite_rank_within_strategy,
       elite_target_count_per_strategy,
       empirical_duration_r2,
       credit_beta_r2,
       yield_proxy_12m,
       duration_adj_drawdown_1y,
       scoring_model,
       seven_day_net_yield,
       nav_per_share_mmf,
       pct_weekly_liquid,
       weighted_avg_maturity_days,
       inflation_beta_r2,
       peer_overall_quartile,
       peer_band_low,
       peer_band_mid,
       peer_band_high,
       nav_quality_ok,
       nav_glitch_count,
       flow_momentum_as_of,
       flow_momentum_observation_count,
       nport_flow_momentum_score,
       nport_flow_as_of,
       nport_flow_staleness_days,
       nport_flow_observation_count
FROM latest_global
LEFT JOIN latest_active_share
  ON active_instrument_id = instrument_id;

CREATE UNIQUE INDEX fund_risk_latest_mv_new_pk
    ON fund_risk_latest_mv_new (instrument_id);

CREATE MATERIALIZED VIEW funds_list_mv_new AS
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
LEFT JOIN fund_risk_latest_mv_new r ON r.instrument_id = f.instrument_id
CROSS JOIN nav_staleness ns
WHERE f.strategy_label IS DISTINCT FROM 'Unclassified'
  AND f.aum_usd IS NOT NULL;

CREATE UNIQUE INDEX funds_list_mv_new_pk
    ON funds_list_mv_new (instrument_id);

CREATE INDEX funds_list_mv_new_aum_sort_idx
    ON funds_list_mv_new (aum_usd DESC NULLS LAST, ticker, instrument_id);

CREATE INDEX funds_list_mv_new_ticker_sort_idx
    ON funds_list_mv_new (ticker ASC NULLS LAST, instrument_id);

CREATE INDEX funds_list_mv_new_name_sort_idx
    ON funds_list_mv_new (name ASC, instrument_id);

CREATE INDEX funds_list_mv_new_filters_idx
    ON funds_list_mv_new (fund_type, asset_class, strategy_label);

CREATE INDEX funds_list_mv_new_sharpe_sort_idx
    ON funds_list_mv_new (sharpe_1y DESC NULLS LAST, ticker, instrument_id);

CREATE INDEX funds_list_mv_new_risk_filters_idx
    ON funds_list_mv_new (return_1y, volatility_1y, max_drawdown_1y);

CREATE MATERIALIZED VIEW fund_class_resolution_mv_new AS
SELECT
    fc.class_id,
    fc.ticker AS class_ticker,
    fc.class_name,
    fc.series_id,
    fl.instrument_id,
    fl.ticker AS fund_ticker,
    fl.name AS fund_name,
    fl.fund_type,
    fl.strategy_label,
    fl.asset_class
FROM fund_classes_v fc
JOIN funds_list_mv_new fl ON fl.series_id = fc.series_id
WHERE fc.ticker IS NOT NULL;

CREATE UNIQUE INDEX fund_class_resolution_mv_new_pk
    ON fund_class_resolution_mv_new (class_id, instrument_id);

CREATE INDEX fund_class_resolution_mv_new_ticker_idx
    ON fund_class_resolution_mv_new (class_ticker, instrument_id);

CREATE INDEX fund_class_resolution_mv_new_instrument_idx
    ON fund_class_resolution_mv_new (instrument_id);

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DROP MATERIALIZED VIEW IF EXISTS fund_class_resolution_mv;
DROP MATERIALIZED VIEW IF EXISTS funds_list_mv;
DROP MATERIALIZED VIEW IF EXISTS fund_risk_latest_mv;

ALTER MATERIALIZED VIEW fund_risk_latest_mv_new RENAME TO fund_risk_latest_mv;
ALTER INDEX fund_risk_latest_mv_new_pk RENAME TO fund_risk_latest_mv_pk;

ALTER MATERIALIZED VIEW funds_list_mv_new RENAME TO funds_list_mv;
ALTER INDEX funds_list_mv_new_pk RENAME TO funds_list_mv_pk;
ALTER INDEX funds_list_mv_new_aum_sort_idx RENAME TO funds_list_mv_aum_sort_idx;
ALTER INDEX funds_list_mv_new_ticker_sort_idx RENAME TO funds_list_mv_ticker_sort_idx;
ALTER INDEX funds_list_mv_new_name_sort_idx RENAME TO funds_list_mv_name_sort_idx;
ALTER INDEX funds_list_mv_new_filters_idx RENAME TO funds_list_mv_filters_idx;
ALTER INDEX funds_list_mv_new_sharpe_sort_idx RENAME TO funds_list_mv_sharpe_sort_idx;
ALTER INDEX funds_list_mv_new_risk_filters_idx RENAME TO funds_list_mv_risk_filters_idx;

ALTER MATERIALIZED VIEW fund_class_resolution_mv_new RENAME TO fund_class_resolution_mv;
ALTER INDEX fund_class_resolution_mv_new_pk RENAME TO fund_class_resolution_mv_pk;
ALTER INDEX fund_class_resolution_mv_new_ticker_idx RENAME TO fund_class_resolution_mv_ticker_idx;
ALTER INDEX fund_class_resolution_mv_new_instrument_idx RENAME TO fund_class_resolution_mv_instrument_idx;

COMMIT;

ANALYZE fund_risk_latest_mv;
ANALYZE funds_list_mv;
ANALYZE fund_class_resolution_mv;
