-- Additive, non-destructive dynamic-catalog DDL (Tiger t83f4np6x4, public).
-- Idempotent where possible; safe to re-run. Rollback in the deploy runbook.

-- 1) EOD daily OHLCV for DB-first Highcharts reads across every range.
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_eod_daily
WITH (timescaledb.continuous) AS
SELECT ticker,
       time_bucket('1 day', date) AS bucket,
       first(open,  date) AS open,
       max(high)          AS high,
       min(low)           AS low,
       last(close, date)  AS close,
       sum(volume)        AS volume,
       first(adj_open,  date) AS adj_open,
       max(adj_high)          AS adj_high,
       min(adj_low)           AS adj_low,
       last(adj_close, date)  AS adj_close,
       sum(adj_volume)        AS adj_volume
FROM eod_prices
GROUP BY ticker, time_bucket('1 day', date)
WITH NO DATA;

CREATE INDEX IF NOT EXISTS cagg_eod_daily_ticker_bucket_idx
  ON cagg_eod_daily (ticker, bucket);

-- 2) EOD weekly OHLC (adjusted) retained for non-chart analytical workloads.
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_eod_weekly
WITH (timescaledb.continuous) AS
SELECT ticker,
       time_bucket('1 week', date) AS bucket,
       first(adj_open,  date) AS adj_open,
       max(adj_high)          AS adj_high,
       min(adj_low)           AS adj_low,
       last(adj_close, date)  AS adj_close,
       sum(adj_volume)        AS adj_volume
FROM eod_prices
GROUP BY ticker, time_bucket('1 week', date)
WITH NO DATA;

-- 3) EOD monthly OHLC (adjusted).
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_eod_monthly
WITH (timescaledb.continuous) AS
SELECT ticker,
       time_bucket('1 month', date) AS bucket,
       first(adj_open,  date) AS adj_open,
       max(adj_high)          AS adj_high,
       min(adj_low)           AS adj_low,
       last(adj_close, date)  AS adj_close,
       sum(adj_volume)        AS adj_volume
FROM eod_prices
GROUP BY ticker, time_bucket('1 month', date)
WITH NO DATA;

-- 4) NAV daily/weekly (last-of-period) — cagg_nav_monthly already exists.
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_nav_daily
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket('1 day', nav_date) AS bucket,
       last(nav, nav_date)       AS nav,
       last(return_1d, nav_date) AS return_1d,
       count(*)                  AS n_obs,
       last(aum_usd, nav_date)   AS aum_usd
FROM nav_timeseries
GROUP BY instrument_id, time_bucket('1 day', nav_date)
WITH NO DATA;

CREATE INDEX IF NOT EXISTS cagg_nav_daily_instrument_bucket_idx
  ON cagg_nav_daily (instrument_id, bucket);

CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_nav_weekly
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket('1 week', nav_date) AS bucket,
       last(nav, nav_date)      AS nav_eow,
       first(nav, nav_date)     AS nav_bow,
       count(*)                 AS n_obs,
       last(aum_usd, nav_date)  AS aum_eow
FROM nav_timeseries
GROUP BY instrument_id, time_bucket('1 week', nav_date)
WITH NO DATA;

-- Populate once, then keep fresh daily (ingestion writes daily).
CALL refresh_continuous_aggregate('cagg_eod_daily',   NULL, NULL);
CALL refresh_continuous_aggregate('cagg_eod_weekly',  NULL, NULL);
CALL refresh_continuous_aggregate('cagg_eod_monthly', NULL, NULL);
CALL refresh_continuous_aggregate('cagg_nav_daily',   NULL, NULL);
CALL refresh_continuous_aggregate('cagg_nav_weekly',  NULL, NULL);

SELECT add_continuous_aggregate_policy('cagg_eod_daily',
  start_offset => INTERVAL '90 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
SELECT add_continuous_aggregate_policy('cagg_eod_weekly',
  start_offset => INTERVAL '90 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
SELECT add_continuous_aggregate_policy('cagg_eod_monthly',
  start_offset => INTERVAL '180 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
SELECT add_continuous_aggregate_policy('cagg_nav_daily',
  start_offset => INTERVAL '90 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
SELECT add_continuous_aggregate_policy('cagg_nav_weekly',
  start_offset => INTERVAL '90 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);

-- Latest risk metrics per fund (replaces the sync_funds.py fund_risk_latest
-- snapshot). organization_id IS NULL = the global (non-org) calc. The column
-- set mirrors the MV-backed model plus the Tier-1 class regression metrics
-- (empirical_duration/credit_beta/inflation_beta/crisis_alpha_score) and the
-- Tier-2 EVT/GARCH tail columns (cvar_99_evt/cvar_999_evt/evt_xi_shape +
-- volatility_garch/vol_model).
-- DROP+CREATE (not CREATE IF NOT EXISTS) so column additions take effect — the
-- MV is read-only and rebuilt by the risk_metrics worker's
-- REFRESH MATERIALIZED VIEW CONCURRENTLY path; the unique index below must be
-- recreated after the DROP for CONCURRENTLY to work.
DROP MATERIALIZED VIEW IF EXISTS fund_risk_latest_mv;
CREATE MATERIALIZED VIEW fund_risk_latest_mv AS
SELECT DISTINCT ON (instrument_id)
       instrument_id, calc_date, organization_id,
       cvar_95_1m, cvar_95_3m, cvar_95_6m, cvar_95_12m,
       var_95_1m, var_95_3m, var_95_6m, var_95_12m,
       return_1m, return_3m, return_6m, return_1y,
       return_3y_ann, return_5y_ann, return_10y_ann,
       volatility_1y, volatility_garch, vol_model,
       max_drawdown_1y, max_drawdown_3y,
       sharpe_1y, sharpe_3y, sortino_1y, calmar_ratio_3y,
       alpha_1y, beta_1y, information_ratio_1y, tracking_error_1y,
       upside_capture_1y, downside_capture_1y,
       sharpe_cf, sharpe_cf_skew, sharpe_cf_kurt,
       sharpe_cf_ci_lower, sharpe_cf_ci_upper,
       cvar_99_evt, cvar_999_evt, evt_xi_shape,
       fed_funds_rate_at_calc, data_quality_flags,
       peer_sharpe_pctl, peer_sortino_pctl, peer_return_pctl, peer_drawdown_pctl,
       peer_overall_quartile, peer_band_low, peer_band_mid, peer_band_high,
       manager_score,
       equity_correlation_252d, peer_strategy_label, peer_count, elite_flag,
       empirical_duration, empirical_duration_r2,
       credit_beta, credit_beta_r2,
       inflation_beta, inflation_beta_r2,
       crisis_alpha_score, scoring_model,
       -- Active-share / overlap columns (db-first A5). These live on
       -- fund_risk_metrics (seeded by the active-share worker) and are
       -- projected here so the dossier reads active share off the same latest
       -- MV instead of a standalone fund_active_share_mv (now removed).
       active_share_normalized, overlap_normalized, overlap_nav_raw,
       fund_cusip_coverage_nav, benchmark_cusip_coverage_nav,
       n_fund_holdings, n_benchmark_holdings, n_common_holdings,
       n_fund_only, n_benchmark_only, holdings_jaccard,
       fund_report_age_days, benchmark_report_age_days, report_date_gap_days,
       active_share_benchmark_instrument_id, active_share_benchmark_series_id,
       active_share_fund_report_date, active_share_benchmark_report_date,
       score_components,
       dtw_drift_score, rsi_14, bb_position,
       nav_momentum_score, flow_momentum_score, blended_momentum_score,
       cvar_95_conditional,
       elite_rank_within_strategy, elite_target_count_per_strategy,
       yield_proxy_12m, duration_adj_drawdown_1y,
       seven_day_net_yield, nav_per_share_mmf,
       pct_weekly_liquid, weighted_avg_maturity_days,
       nav_quality_ok, nav_glitch_count,
       flow_momentum_as_of, flow_momentum_observation_count,
       nport_flow_momentum_score, nport_flow_as_of,
       nport_flow_staleness_days, nport_flow_observation_count
FROM fund_risk_metrics
WHERE organization_id IS NULL
ORDER BY instrument_id, calc_date DESC;

CREATE UNIQUE INDEX IF NOT EXISTS fund_risk_latest_mv_pk
  ON fund_risk_latest_mv (instrument_id);

-- ---------------------------------------------------------------------------
-- funds_v — dynamic catalog VIEW replacing the sync_funds.py `funds` snapshot
-- ---------------------------------------------------------------------------
-- Faithful SQL port of app/sync/funds.py (build_fund_row + cascade helpers +
-- the ELIGIBLE_FUNDS_SQL F8.1-2 eligibility filter). The snapshot was built
-- against the mother DB; on Tiger the same source tables live in `public`, so
-- the view reproduces the lineage column-by-column. Verified parity (Task 2.3,
-- 2026-06-13): on the 4562 shared ids fund_type / strategy_label /
-- expense_ratio / aum_usd mismatches = 0. The one snapshot id not in the view
-- (CRFRX, S000076003) fell out of NAV-freshness eligibility (max nav_date is
-- one day past current_date - 30) — a frozen-snapshot vs current_date()
-- artifact, not a lineage divergence; it reappears as NAV ingestion advances.
--
-- Eligibility (ELIGIBLE_FUNDS_SQL): instrument_identity with sec_series_id, in
-- the latest fund_risk_metrics calc (max calc_date >= 2026-01-01), NAV history
-- spanning >= 2y (min nav_date <= current_date - 730) and fresh within 30 days
-- (max nav_date >= current_date - 30).
--
-- NOTE: synced_at / source_calc_date / source_nav_max_date are intentionally
-- ABSENT — a dynamic view has no sync markers (Task 2.4 sources staleness from
-- fund_risk_latest_mv.calc_date and nav_timeseries directly).
-- Canonical strategy_label -> asset_class map. instruments_universe.asset_class
-- is frozen at initial load and drifts hard from the (reclassified) strategy
-- label — e.g. "Real Estate"/"Precious Metals"/"Emerging Markets Equity" funds
-- carried asset_class='fixed_income', polluting the broad fixed_income universe
-- by ~29%. strategy_label is the trustworthy field (sourced from SEC metadata +
-- strategy_reclassification_stage), so the data migration at the end of this
-- file rewrites the STORED instruments_universe.asset_class from it via this
-- map; multi-asset labels (Balanced, Target Date, Multi-Asset) map to the
-- dedicated 'multi_asset' class, while genuinely unknown labels (Index /
-- Passive, Unclassified) return NULL and keep the stored value (the column is
-- NOT NULL, so they cannot be nulled — Unclassified is instead excluded from
-- the optimizable universe in select_universe_funds). asset_class stays a
-- stored column (NOT a view expression) so the optimizer's
-- WHERE asset_class = :class predicate remains sargable.
CREATE OR REPLACE FUNCTION public.asset_class_from_strategy(label text)
RETURNS varchar
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
  SELECT CASE label
    WHEN 'Asset-Backed Securities' THEN 'fixed_income'
    WHEN 'Convertible Securities' THEN 'fixed_income'
    WHEN 'ESG/Sustainable Bond' THEN 'fixed_income'
    WHEN 'Emerging Markets Debt' THEN 'fixed_income'
    WHEN 'Government Bond' THEN 'fixed_income'
    WHEN 'High Yield Bond' THEN 'fixed_income'
    WHEN 'Inflation-Linked Bond' THEN 'fixed_income'
    WHEN 'Intermediate-Term Bond' THEN 'fixed_income'
    WHEN 'Investment Grade Bond' THEN 'fixed_income'
    WHEN 'Mortgage-Backed Securities' THEN 'fixed_income'
    WHEN 'Municipal Bond' THEN 'fixed_income'
    WHEN 'Private Credit' THEN 'fixed_income'
    WHEN 'Preferred Securities' THEN 'fixed_income'
    WHEN 'Structured Credit' THEN 'fixed_income'
    WHEN 'Defined Outcome / Option Income' THEN 'alternatives'
    WHEN 'Crypto / Digital Assets' THEN 'alternatives'
    WHEN 'Leveraged' THEN 'alternatives'
    WHEN 'Inverse / Hedge' THEN 'alternatives'
    WHEN 'Asian Equity' THEN 'equity'
    WHEN 'Biotechnology Equity' THEN 'equity'
    WHEN 'Clean Energy Equity' THEN 'equity'
    WHEN 'Communication Services Equity' THEN 'equity'
    WHEN 'Consumer Discretionary Equity' THEN 'equity'
    WHEN 'Consumer Staples Equity' THEN 'equity'
    WHEN 'Emerging Markets Equity' THEN 'equity'
    WHEN 'Energy Equity' THEN 'equity'
    WHEN 'ESG/Sustainable Equity' THEN 'equity'
    WHEN 'European Equity' THEN 'equity'
    WHEN 'Financials Equity' THEN 'equity'
    WHEN 'Global Equity' THEN 'equity'
    WHEN 'Health Care Equity' THEN 'equity'
    WHEN 'Industrials Equity' THEN 'equity'
    WHEN 'Infrastructure Equity' THEN 'equity'
    WHEN 'International Equity' THEN 'equity'
    WHEN 'Large Blend' THEN 'equity'
    WHEN 'Large Growth' THEN 'equity'
    WHEN 'Large Value' THEN 'equity'
    WHEN 'Long/Short Equity' THEN 'equity'
    WHEN 'Mid Blend' THEN 'equity'
    WHEN 'Mid Growth' THEN 'equity'
    WHEN 'Mid Value' THEN 'equity'
    WHEN 'Materials Equity' THEN 'equity'
    WHEN 'Natural Resources Equity' THEN 'equity'
    WHEN 'Sector Equity' THEN 'equity'
    WHEN 'Sector Rotation Equity' THEN 'equity'
    WHEN 'Size-Focused Equity' THEN 'equity'
    WHEN 'Small Blend' THEN 'equity'
    WHEN 'Small Growth' THEN 'equity'
    WHEN 'Small Value' THEN 'equity'
    WHEN 'Technology' THEN 'equity'
    WHEN 'Utilities Equity' THEN 'equity'
    WHEN 'Alternative' THEN 'alternatives'
    WHEN 'Commodities' THEN 'alternatives'
    WHEN 'Precious Metals' THEN 'alternatives'
    WHEN 'Real Estate' THEN 'alternatives'
    WHEN 'Cash Equivalent' THEN 'cash'
    WHEN 'Government Money Market' THEN 'cash'
    WHEN 'Balanced' THEN 'multi_asset'
    WHEN 'Target Date' THEN 'multi_asset'
    WHEN 'Multi-Asset' THEN 'multi_asset'
    ELSE NULL
  END::varchar;
$fn$;

-- High-confidence ETF identity overrides. Some upstream ETF rows carry a
-- contaminated strategy_label (notably iShares/MSCI equity ETFs classified as
-- Government Bond). When SEC/N-CEN metadata is missing or wrong, the ETF name,
-- ticker, and tracked index are safer for broad strategy/asset-class routing.
CREATE OR REPLACE FUNCTION public.etf_strategy_label_from_identity(
    ticker text,
    fund_name text,
    benchmark_name text DEFAULT NULL
)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
WITH normalized AS (
    SELECT
        upper(coalesce(ticker, '')) AS ticker_code,
        regexp_replace(
            lower(
                coalesce(fund_name, '') || ' ' ||
                coalesce(benchmark_name, '') || ' ' ||
                coalesce(ticker, '')
            ),
            '[^a-z0-9]+',
            ' ',
            'g'
        ) AS text_blob
)
SELECT CASE
    WHEN text_blob ~ '\m(ultra short|short term income|short duration|short term bond)\M'
        THEN 'Cash Equivalent'
    WHEN text_blob ~ '\m(preferred|capital securities|contingent capital|junior subordinated)\M'
        THEN 'Preferred Securities'
    WHEN text_blob ~ '\m(treasury|bond|fixed income|aggregate bond|municipal|corporate|high yield|credit|senior loan|floating rate|mortgage|mbs|abs|clo|securitized|duration|inflation protected|tips|preferred securities|core plus)\M'
        THEN NULL
    WHEN text_blob ~ '\m(bitcoin|btc|ether|crypto)\M'
        THEN 'Crypto / Digital Assets'
    WHEN text_blob ~ '\m(1x short|bear|inverse)\M'
      OR text_blob LIKE '%short qqq%'
      OR text_blob LIKE '%short s p%'
      OR text_blob LIKE '%short s&p%'
      OR text_blob LIKE '%short 20%'
      OR text_blob LIKE '%short innovation%'
        THEN 'Inverse / Hedge'
    WHEN text_blob ~ '\m(leveraged long|ultrapro|ultra|2x|3x|25x|5x|bull)\M'
        THEN 'Leveraged'
    WHEN text_blob ~ '\m(buffer|defined outcome|option strategy|option income|yieldmax|yieldboost|covered call|weeklypay|income strategy)\M'
        THEN 'Defined Outcome / Option Income'
    WHEN text_blob ~ '\m(managed futures|merger arbitrage|alternative|multi strategy|hedge|long short|market neutral)\M'
        THEN 'Alternative'
    WHEN text_blob ~ '\m(real estate|reit)\M'
        THEN 'Real Estate'
    WHEN text_blob ~ '\m(gold|silver|precious metals|gold miners|silver miners)\M'
        THEN 'Precious Metals'
    WHEN text_blob ~ '\m(commodity|commodities|all commodity|commodity strategy|commodity return|agriculture)\M'
        THEN 'Commodities'
    WHEN text_blob ~ '\m(biotech|biotechnology|genome|genomics)\M'
        THEN 'Biotechnology Equity'
    WHEN text_blob ~ '\m(health care|healthcare|health|pharmaceutical|pharma|medical devices|medical technology|life sciences)\M'
        THEN 'Health Care Equity'
    WHEN text_blob ~ '\m(clean energy|solar|wind energy|renewable energy|green energy|energy transition)\M'
        THEN 'Clean Energy Equity'
    WHEN text_blob ~ '\m(communication services|communications|media|telecom)\M'
        THEN 'Communication Services Equity'
    WHEN text_blob ~ '\m(consumer discretionary|consumer cyclic|consumer services|retail)\M'
        THEN 'Consumer Discretionary Equity'
    WHEN text_blob ~ '\m(consumer staples|consumer goods|food beverage|household products)\M'
        THEN 'Consumer Staples Equity'
    WHEN text_blob ~ '\m(financial|financials|bank|banks|insurance|broker|capital markets)\M'
        THEN 'Financials Equity'
    WHEN text_blob ~ '\m(aerospace|defense|industrial|industrials|transportation|producer durables)\M'
        THEN 'Industrials Equity'
    WHEN text_blob ~ '\m(infrastructure|smart grid|water infrastructure)\M'
        THEN 'Infrastructure Equity'
    WHEN text_blob ~ '\m(natural resources|global resources|capital cycles|resource fund|upstream natural)\M'
        THEN 'Natural Resources Equity'
    WHEN text_blob ~ '\m(energy|oil|gas|pipeline|midstream|mlp|energy infrastructure|world energy)\M'
        THEN 'Energy Equity'
    WHEN text_blob ~ '\m(materials|metals mining|mining producers|uranium|nuclear|copper|lithium|battery)\M'
        THEN 'Materials Equity'
    WHEN text_blob ~ '\m(utility|utilities)\M'
        THEN 'Utilities Equity'
    WHEN text_blob ~ '\m(equal sector|sector rotation|sector neutral|subsector|sector dividend|sector plus)\M'
        THEN 'Sector Rotation Equity'
    WHEN text_blob LIKE '%ex technology%'
      OR text_blob LIKE '%ex tech%'
        THEN 'Large Blend'
    WHEN text_blob ~ '\m(information technology|tech|technology select sector|technology index|technology fund|technology portfolio|science and technology|semiconductor|software|cloud computing|internet|cybersecurity|cyber|artificial intelligence|generative ai|robotics|automation|blockchain|fintech|data and digital revolution|digital revolution|expanded technology|technology dividend|technology alphadex|technology momentum|nanotechnology|cleantech)\M'
      OR text_blob LIKE '%science & technology%'
      OR text_blob LIKE '%fang%'
      OR text_blob LIKE '%exponential technologies%'
      OR text_blob LIKE '%innovation leaders%'
        THEN 'Technology'
    WHEN ticker_code = 'QQQ'
      OR text_blob LIKE '%nasdaq 100%'
      OR text_blob LIKE '%nasdaq100%'
        THEN 'Large Growth'
    WHEN text_blob LIKE '%russell 2000 growth%'
        THEN 'Small Growth'
    WHEN text_blob LIKE '%russell 2000 value%'
        THEN 'Small Value'
    WHEN ticker_code = 'IWM'
      OR text_blob LIKE '%russell 2000%'
        THEN 'Small Blend'
    WHEN text_blob LIKE '%russell midcap growth%'
      OR text_blob LIKE '%midcap growth%'
      OR text_blob LIKE '%mid cap growth%'
        THEN 'Mid Growth'
    WHEN text_blob LIKE '%russell midcap value%'
      OR text_blob LIKE '%midcap value%'
      OR text_blob LIKE '%mid cap value%'
        THEN 'Mid Value'
    WHEN text_blob LIKE '%s p midcap 400%'
      OR text_blob LIKE '%s&p midcap 400%'
      OR text_blob LIKE '%midcap%'
      OR text_blob LIKE '%mid cap%'
        THEN 'Mid Blend'
    WHEN text_blob LIKE '%small cap growth%'
      OR text_blob LIKE '%smallcap growth%'
        THEN 'Small Growth'
    WHEN text_blob LIKE '%small cap value%'
      OR text_blob LIKE '%smallcap value%'
        THEN 'Small Value'
    WHEN text_blob LIKE '%s p smallcap 600%'
      OR text_blob LIKE '%s&p smallcap 600%'
      OR text_blob LIKE '%small cap%'
      OR text_blob LIKE '%smallcap%'
        THEN 'Small Blend'
    WHEN text_blob LIKE '%russell 1000 growth%'
      OR text_blob LIKE '%s p 500 growth%'
      OR text_blob LIKE '%s&p 500 growth%'
        THEN 'Large Growth'
    WHEN text_blob LIKE '%russell 1000 value%'
      OR text_blob LIKE '%s p 500 value%'
      OR text_blob LIKE '%s&p 500 value%'
        THEN 'Large Value'
    WHEN text_blob ~ '\m(msci emerging markets|emerging markets|msci em|china|india|brazil|mexico|south korea|taiwan|thailand|turkey|saudi arabia|qatar|kuwait|uae|south africa|indonesia|malaysia|philippines|poland|chile|bic)\M'
        THEN 'Emerging Markets Equity'
    WHEN text_blob ~ '\m(europe|european|eurozone|euro area|stoxx|msci europe|ftse developed europe|germany|france|spain|italy|switzerland|united kingdom|ireland|norway|denmark|sweden|finland|netherlands|austria|belgium)\M'
        THEN 'European Equity'
    WHEN text_blob ~ '\m(all country asia ex japan|asia ex japan|asia pacific|pacific ex japan|japan|australia|hong kong|singapore|new zealand|kokusai)\M'
        THEN 'Asian Equity'
    WHEN text_blob ~ '\m(msci eafe|eafe|international|intl|world ex|global ex us|global ex u s|global ex|acwi ex|developed)\M'
        THEN 'International Equity'
    WHEN text_blob LIKE '%msci acwi%'
      OR text_blob LIKE '%total world stock%'
      OR text_blob LIKE '%global equity%'
        THEN 'Global Equity'
    WHEN text_blob ~ '\m(technology|tech|cybersecurity|semiconductor|solar|energy storage|consumer focused|regional banks|bank|environmental solutions|exponential technologies|self driving|multisector tech)\M'
        THEN 'Sector Equity'
    WHEN text_blob LIKE '%russell 1000%'
      OR text_blob LIKE '%russell 3000%'
      OR text_blob LIKE '%s p 500%'
      OR text_blob LIKE '%s&p 500%'
      OR text_blob LIKE '%large cap%'
      OR text_blob LIKE '%broad market%'
      OR text_blob LIKE '%dividend equity%'
      OR text_blob LIKE '%msci usa%'
      OR text_blob LIKE '%msci us%'
      OR text_blob LIKE '%us equity%'
      OR text_blob LIKE '%u s equity%'
        THEN 'Large Blend'
    ELSE NULL
END
FROM normalized;
$fn$;

CREATE OR REPLACE VIEW funds_v AS
WITH eligible AS (
    SELECT ii.instrument_id, ii.sec_series_id, ii.ticker, ii.isin,
           ii.cusip_9, ii.lei
    FROM instrument_identity ii
    JOIN (
        SELECT instrument_id, max(calc_date) AS calc_date
        FROM fund_risk_metrics
        GROUP BY instrument_id
        HAVING max(calc_date) >= DATE '2026-01-01'
    ) lr ON lr.instrument_id = ii.instrument_id
    JOIN (
        SELECT instrument_id, max(nav_date) AS max_nav_date,
               count(*) AS n_nav
        FROM nav_timeseries
        GROUP BY instrument_id
    ) ns ON ns.instrument_id = ii.instrument_id
    WHERE ii.sec_series_id IS NOT NULL
      -- RELAXED gate (Frente 1, 2026-06-20): established funds were being cut
      -- for short IN-SYSTEM history (JP Morgan / T. Rowe / PIMCO etc.), starving
      -- the optimizer's universe. Drop the ">= 2 years history" floor and widen
      -- the recency window 30 -> 90 days; keep a small observation floor so every
      -- catalogued fund still has a usable return series. Long-horizon metrics
      -- (3y/5y) are simply null until the series accumulates.
      AND ns.max_nav_date >= (current_date - 90)
      AND ns.n_nav >= 60
),
-- index_profiles_by_series: one row per series_id, preferring a labeled row.
rf AS (
    SELECT DISTINCT ON (series_id) series_id, fund_name, strategy_label, is_index,
           management_fee, net_operating_expenses, monthly_avg_net_assets,
           primary_benchmark, inception_date, domicile, currency
    FROM sec_registered_funds
    WHERE series_id IS NOT NULL
    ORDER BY series_id, (strategy_label IS NULL)
),
etf AS (
    SELECT DISTINCT ON (series_id) series_id, fund_name, strategy_label, is_index,
           index_tracked, management_fee, net_operating_expenses,
           monthly_avg_net_assets, inception_date, domicile, currency
    FROM sec_etfs
    WHERE series_id IS NOT NULL
    ORDER BY series_id, (strategy_label IS NULL)
),
mmf AS (
    SELECT DISTINCT ON (series_id) series_id, fund_name, strategy_label,
           domicile, currency
    FROM sec_money_market_funds
    WHERE series_id IS NOT NULL
    ORDER BY series_id, (strategy_label IS NULL)
),
-- SERIES_NAME_SQL: the N-CEN series-level fund name (one per series, latest
-- filing). sec_registered_funds is trust-level and some sec_etfs rows carry
-- the trust/umbrella name, so this is the only catalog source of the SPECIFIC
-- fund name (e.g. "WisdomTree Siegel Longevity Digital Fund", not the trust
-- "WisdomTree Digital Trust"). Used to repair trust-named registrants below.
fc AS (
    SELECT DISTINCT ON (series_id) series_id, series_name
    FROM sec_fund_classes
    WHERE series_id IS NOT NULL AND NULLIF(btrim(series_name), '') IS NOT NULL
    ORDER BY series_id, xbrl_period_end DESC NULLS LAST
),
-- STAGE_LABELS_SQL: explicit manual overrides are durable corrections and win
-- over generated proposals; otherwise use the latest proposed label.
stage AS (
    SELECT DISTINCT ON (source_pk) source_pk::uuid AS instrument_id,
           proposed_strategy_label AS label
    FROM strategy_reclassification_stage
    WHERE source_table = 'instruments_universe'
      AND proposed_strategy_label IS NOT NULL
    ORDER BY source_pk,
             (classification_source = 'manual_override') DESC,
             classified_at DESC,
             stage_id DESC
),
manual_stage AS (
    SELECT DISTINCT ON (source_pk) source_pk::uuid AS instrument_id,
           proposed_strategy_label AS label
    FROM strategy_reclassification_stage
    WHERE source_table = 'instruments_universe'
      AND proposed_strategy_label IS NOT NULL
      AND classification_source = 'manual_override'
    ORDER BY source_pk, classified_at DESC, stage_id DESC
),
-- merge_risk_duplicates: latest calc_date per instrument; the peer-labeled
-- variant wins ties (peer_strategy_label is the cascade's last specific label).
peer AS (
    SELECT DISTINCT ON (instrument_id) instrument_id, peer_strategy_label
    FROM fund_risk_metrics
    ORDER BY instrument_id, calc_date DESC, (peer_strategy_label IS NULL)
),
-- PROSPECTUS_FEES_SQL: latest filing per series, cheapest share class.
prospectus AS (
    SELECT s.series_id,
           min(coalesce(s.net_expense_ratio_pct, s.expense_ratio_pct,
                        s.management_fee_pct)) AS expense_ratio
    FROM sec_fund_prospectus_stats s
    JOIN (
        SELECT series_id, max(filing_date) AS filing_date
        FROM sec_fund_prospectus_stats
        GROUP BY series_id
    ) l ON l.series_id = s.series_id AND l.filing_date = s.filing_date
    WHERE coalesce(s.net_expense_ratio_pct, s.expense_ratio_pct,
                   s.management_fee_pct) IS NOT NULL
    GROUP BY s.series_id
),
-- CLASSES_AUM_SQL: max(net_assets) at the latest reported xbrl period (series
-- level, repeated per class — take max, never sum).
classes_aum AS (
    SELECT c.series_id, max(c.net_assets) AS aum_usd
    FROM sec_fund_classes c
    JOIN (
        SELECT series_id, max(xbrl_period_end) AS period_end
        FROM sec_fund_classes
        WHERE net_assets IS NOT NULL
        GROUP BY series_id
    ) l ON l.series_id = c.series_id
       AND c.xbrl_period_end IS NOT DISTINCT FROM l.period_end
    WHERE c.net_assets IS NOT NULL
    GROUP BY c.series_id
),
-- NPORT_AUM_SQL: last N-PORT total market value, coverage in [80,120]%.
nport_aum AS (
    SELECT DISTINCT ON (series_id) series_id, total_market_value AS aum_usd
    FROM cagg_nport_series_profile
    WHERE total_market_value > 0 AND coverage_pct BETWEEN 80 AND 120
    ORDER BY series_id, report_day DESC
),
-- ETP_TICKERS_SQL: tickers listed as Exchange Traded Product (OpenFIGI map).
etp AS (
    SELECT DISTINCT upper(ticker) AS ticker
    FROM sec_cusip_ticker_map
    WHERE security_type = 'ETP' AND ticker IS NOT NULL
),
universe AS (
    SELECT instrument_id, name, currency, asset_class
    FROM instruments_universe
),
-- latest_aum_by_instrument: aum_usd at the latest nav_date carrying a value
-- (funds.aum_usd fallback applied by the orchestrator's step 4b).
nav_latest_aum AS (
    SELECT DISTINCT ON (instrument_id) instrument_id, aum_usd
    FROM nav_timeseries
    WHERE aum_usd IS NOT NULL
    ORDER BY instrument_id, nav_date DESC
)
SELECT
    e.instrument_id,
    e.sec_series_id AS series_id,
    -- ticker: identity.ticker only (REGISTERED/ETFS SQL never select ticker).
    NULLIF(btrim(e.ticker), '') AS ticker,
    e.isin,
    e.cusip_9 AS cusip,
    e.lei,
    COALESCE(
        -- Trust/umbrella registrants surface the TRUST name, not the fund's
        -- (sec_registered_funds is trust-level; some sec_etfs rows do the same).
        -- When the resolved catalog name ends in "Trust" (optionally a numeral)
        -- or is an "Exchange-Traded Fund" umbrella, prefer the N-CEN
        -- series-level name so the look-through sunburst labels the fund series,
        -- not the trust. "First Trust ... ETF" (manager) is intentionally NOT
        -- matched — the pattern anchors "trust" at the end of the name.
        CASE
            WHEN COALESCE(
                     NULLIF(btrim(rf.fund_name), ''),
                     NULLIF(btrim(etf.fund_name), ''),
                     NULLIF(btrim(mmf.fund_name), ''),
                     NULLIF(btrim(u.name), ''), ''
                 ) ~* '(trust\s*[ivxl0-9]*\s*$|exchange.?traded\s+fund)'
            THEN NULLIF(btrim(fc.series_name), '')
        END,
        NULLIF(btrim(rf.fund_name), ''),
        NULLIF(btrim(etf.fund_name), ''),
        NULLIF(btrim(mmf.fund_name), ''),
        NULLIF(btrim(u.name), ''),
        NULLIF(btrim(fc.series_name), ''),
        e.sec_series_id
    ) AS name,
    CASE
        WHEN etf.series_id IS NOT NULL
          OR (e.ticker IS NOT NULL AND etp.ticker IS NOT NULL) THEN 'etf'
        WHEN mmf.series_id IS NOT NULL THEN 'mmf'
        ELSE 'mutual_fund'
    END AS fund_type,
    COALESCE(
        NULLIF(btrim(manual_stage.label), ''),
        CASE
            WHEN etf.series_id IS NOT NULL
              OR (e.ticker IS NOT NULL AND etp.ticker IS NOT NULL)
            THEN public.etf_strategy_label_from_identity(
                e.ticker,
                COALESCE(
                    NULLIF(btrim(fc.series_name), ''),
                    NULLIF(btrim(rf.fund_name), ''),
                    NULLIF(btrim(etf.fund_name), ''),
                    NULLIF(btrim(u.name), '')
                ),
                NULLIF(btrim(etf.index_tracked), '')
            )
        END,
        NULLIF(btrim(rf.strategy_label), ''),
        NULLIF(btrim(etf.strategy_label), ''),
        NULLIF(btrim(mmf.strategy_label), ''),
        NULLIF(btrim(stage.label), ''),
        CASE
            WHEN lower(btrim(peer.peer_strategy_label))
                 IN ('mutual_fund', 'etf', 'mmf', 'ucits') THEN NULL
            ELSE NULLIF(btrim(peer.peer_strategy_label), '')
        END,
        'Unclassified'
    ) AS strategy_label,
    -- Plain passthrough of the STORED instruments_universe.asset_class (kept
    -- sargable: the broad/ranked optimizer filters WHERE asset_class = :class
    -- with window_days=NULL, and a computed expression here makes the predicate
    -- non-pushdownable — it forced a full materialization of this view + the
    -- 27M-row NAV aggregation before filtering, turning a ~7s resolve into an
    -- 18-minute hang. The correction lives in the column itself: the data
    -- migration below rewrites instruments_universe.asset_class from the
    -- reclassified strategy_label via asset_class_from_strategy().
    u.asset_class,
    COALESCE(rf.is_index, etf.is_index) AS is_index,
    COALESCE(
        rf.net_operating_expenses, etf.net_operating_expenses,
        prospectus.expense_ratio,
        rf.management_fee, etf.management_fee
    ) AS expense_ratio,
    COALESCE(
        rf.monthly_avg_net_assets, etf.monthly_avg_net_assets,
        classes_aum.aum_usd, nport_aum.aum_usd, nav_latest_aum.aum_usd
    ) AS aum_usd,
    COALESCE(NULLIF(btrim(rf.primary_benchmark), ''),
             NULLIF(btrim(etf.index_tracked), '')) AS primary_benchmark,
    COALESCE(rf.inception_date, etf.inception_date) AS inception_date,
    COALESCE(
        NULLIF(btrim(rf.domicile), ''),
        NULLIF(btrim(etf.domicile), ''),
        NULLIF(btrim(mmf.domicile), ''),
        'US'
    ) AS domicile,
    COALESCE(
        NULLIF(btrim(rf.currency), ''),
        NULLIF(btrim(etf.currency), ''),
        NULLIF(btrim(mmf.currency), ''),
        NULLIF(btrim(u.currency), '')
    ) AS currency
FROM eligible e
LEFT JOIN rf             ON rf.series_id = e.sec_series_id
LEFT JOIN etf            ON etf.series_id = e.sec_series_id
LEFT JOIN mmf            ON mmf.series_id = e.sec_series_id
LEFT JOIN fc             ON fc.series_id = e.sec_series_id
LEFT JOIN stage          ON stage.instrument_id = e.instrument_id
LEFT JOIN manual_stage   ON manual_stage.instrument_id = e.instrument_id
LEFT JOIN peer           ON peer.instrument_id = e.instrument_id
LEFT JOIN prospectus     ON prospectus.series_id = e.sec_series_id
LEFT JOIN classes_aum    ON classes_aum.series_id = e.sec_series_id
LEFT JOIN nport_aum      ON nport_aum.series_id = e.sec_series_id
LEFT JOIN etp            ON etp.ticker = upper(e.ticker)
LEFT JOIN universe u     ON u.instrument_id = e.instrument_id
LEFT JOIN nav_latest_aum ON nav_latest_aum.instrument_id = e.instrument_id;

-- ---------------------------------------------------------------------------
-- DATA MIGRATION (idempotent): correct instruments_universe.asset_class from
-- the reclassified strategy_label. Run after funds_v + asset_class_from_strategy
-- exist. Reads the resolved strategy_label via funds_v and rewrites the stored
-- column for funds the canonical map places definitively; ambiguous labels
-- (map -> NULL) keep their stored value. Re-running is a no-op (the DISTINCT
-- guard skips already-correct rows). NOTE: if a future mother-DB resync rewrites
-- instruments_universe.asset_class, re-run this block.
-- ---------------------------------------------------------------------------
UPDATE instruments_universe iu
SET asset_class = public.asset_class_from_strategy(fv.strategy_label)
FROM funds_v fv
WHERE fv.instrument_id = iu.instrument_id
  AND public.asset_class_from_strategy(fv.strategy_label) IS NOT NULL
  AND iu.asset_class IS DISTINCT FROM public.asset_class_from_strategy(fv.strategy_label);

-- ---------------------------------------------------------------------------
-- fund_holdings_v / fund_classes_v — dynamic VIEWs replacing the sync_funds.py
-- `fund_holdings` and `fund_classes` snapshots (Task 2.5, 2026-06-13).
-- ---------------------------------------------------------------------------
-- Both are keyed by series_id (a class links to a fund via series_id; the
-- profile/portfolio readers resolve series→instrument through funds_v). The
-- snapshot may have CAPPED holdings per series; this view is uncapped — the
-- profile route display-caps to top-50 by rank, so the visible slice matches.

-- Latest N-PORT holdings per series, ranked by pct_of_nav desc.
CREATE OR REPLACE VIEW fund_holdings_v AS
WITH latest AS (
  SELECT series_id, max(report_date) AS report_date
  FROM sec_nport_holdings GROUP BY series_id
)
SELECT h.series_id, h.report_date,
       row_number() OVER (PARTITION BY h.series_id ORDER BY h.pct_of_nav DESC NULLS LAST) AS rank,
       h.issuer_name, h.cusip, h.isin, h.asset_class, h.sector,
       NULL::text AS gics_sector,
       h.market_value, h.pct_of_nav
FROM sec_nport_holdings h
JOIN latest l ON l.series_id = h.series_id AND l.report_date = h.report_date;

-- Share classes from sec_fund_classes (latest period per class).
CREATE OR REPLACE VIEW fund_classes_v AS
SELECT DISTINCT ON (class_id)
       class_id, series_id, class_name, ticker,
       expense_ratio_pct AS expense_ratio, xbrl_period_end AS source_period_end,
       now() AS synced_at
FROM sec_fund_classes
WHERE ticker IS NOT NULL
ORDER BY class_id, xbrl_period_end DESC NULLS LAST;

-- ===========================================================================
-- PHASE 4 — STAGED, NOT EXECUTED BY THIS MIGRATION.
-- ===========================================================================
-- The statements below are intentionally NOT run when this file is applied.
-- They are staged here for the human runbook flip and must be executed MANUALLY
-- ONLY after the dynamic catalog path (funds_v / fund_*_v / *_mv) has been
-- verified in production. Renaming the snapshot tables before verification would
-- break the live serving path. Keep this block last and inert until the flip.
--
-- PHASE 4 — run ONLY after the dynamic path is verified in production.
ALTER TABLE IF EXISTS funds            RENAME TO funds_deprecated;
ALTER TABLE IF EXISTS fund_risk_latest RENAME TO fund_risk_latest_deprecated;
ALTER TABLE IF EXISTS fund_nav         RENAME TO fund_nav_deprecated;
ALTER TABLE IF EXISTS fund_holdings    RENAME TO fund_holdings_deprecated;
ALTER TABLE IF EXISTS fund_classes     RENAME TO fund_classes_deprecated;
