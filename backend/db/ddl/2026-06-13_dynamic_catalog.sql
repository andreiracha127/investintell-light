-- Additive, non-destructive dynamic-catalog DDL (Tiger t83f4np6x4, public).
-- Idempotent where possible; safe to re-run. Rollback in the deploy runbook.

-- 1) EOD weekly OHLC (adjusted) for Highcharts long-range downsample.
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

-- 2) EOD monthly OHLC (adjusted).
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

-- 3) NAV weekly (last-of-week) — cagg_nav_monthly already exists.
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
CALL refresh_continuous_aggregate('cagg_eod_weekly',  NULL, NULL);
CALL refresh_continuous_aggregate('cagg_eod_monthly', NULL, NULL);
CALL refresh_continuous_aggregate('cagg_nav_weekly',  NULL, NULL);

SELECT add_continuous_aggregate_policy('cagg_eod_weekly',
  start_offset => INTERVAL '90 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
SELECT add_continuous_aggregate_policy('cagg_eod_monthly',
  start_offset => INTERVAL '180 days', end_offset => INTERVAL '1 day',
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
       instrument_id, calc_date,
       return_1m, return_3m, return_1y, return_3y_ann, return_5y_ann,
       volatility_1y, volatility_garch, vol_model,
       max_drawdown_1y, max_drawdown_3y,
       sharpe_1y, sharpe_3y, sortino_1y, calmar_ratio_3y,
       alpha_1y, beta_1y, information_ratio_1y, tracking_error_1y,
       var_95_1m, cvar_95_1m, cvar_95_12m,
       cvar_99_evt, cvar_999_evt, evt_xi_shape,
       peer_sharpe_pctl, peer_sortino_pctl, peer_return_pctl, peer_drawdown_pctl,
       manager_score, downside_capture_1y, upside_capture_1y,
       equity_correlation_252d, peer_strategy_label, peer_count, elite_flag,
       empirical_duration, credit_beta, inflation_beta, crisis_alpha_score
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
    WHEN 'Structured Credit' THEN 'fixed_income'
    WHEN 'Asian Equity' THEN 'equity'
    WHEN 'Emerging Markets Equity' THEN 'equity'
    WHEN 'ESG/Sustainable Equity' THEN 'equity'
    WHEN 'European Equity' THEN 'equity'
    WHEN 'Global Equity' THEN 'equity'
    WHEN 'International Equity' THEN 'equity'
    WHEN 'Large Blend' THEN 'equity'
    WHEN 'Large Growth' THEN 'equity'
    WHEN 'Large Value' THEN 'equity'
    WHEN 'Long/Short Equity' THEN 'equity'
    WHEN 'Mid Blend' THEN 'equity'
    WHEN 'Mid Growth' THEN 'equity'
    WHEN 'Mid Value' THEN 'equity'
    WHEN 'Sector Equity' THEN 'equity'
    WHEN 'Size-Focused Equity' THEN 'equity'
    WHEN 'Small Blend' THEN 'equity'
    WHEN 'Small Growth' THEN 'equity'
    WHEN 'Small Value' THEN 'equity'
    WHEN 'Technology' THEN 'equity'
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
        SELECT instrument_id, min(nav_date) AS min_nav_date,
               max(nav_date) AS max_nav_date
        FROM nav_timeseries
        GROUP BY instrument_id
    ) ns ON ns.instrument_id = ii.instrument_id
    WHERE ii.sec_series_id IS NOT NULL
      AND ns.min_nav_date <= (current_date - 730)
      AND ns.max_nav_date >= (current_date - 30)
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
        NULLIF(btrim(rf.fund_name), ''),
        NULLIF(btrim(etf.fund_name), ''),
        NULLIF(btrim(mmf.fund_name), ''),
        NULLIF(btrim(u.name), ''),
        e.sec_series_id
    ) AS name,
    CASE
        WHEN etf.series_id IS NOT NULL
          OR (e.ticker IS NOT NULL AND etp.ticker IS NOT NULL) THEN 'etf'
        WHEN mmf.series_id IS NOT NULL THEN 'mmf'
        ELSE 'mutual_fund'
    END AS fund_type,
    COALESCE(
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
LEFT JOIN stage          ON stage.instrument_id = e.instrument_id
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
