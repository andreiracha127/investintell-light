-- backend/db/ddl/2026-06-25_fund_profile_read_models_mv.sql
-- Shared request-path read models for fund identity and share classes.
--
-- funds_v and fund_classes_v remain the lineage views. These snapshots keep
-- profile, analytics, builder, and portfolio reads from recomputing the
-- dynamic catalog graph per request.

DROP MATERIALIZED VIEW IF EXISTS fund_classes_latest_mv;
DROP MATERIALIZED VIEW IF EXISTS funds_profile_mv;

CREATE MATERIALIZED VIEW funds_profile_mv AS
SELECT
    instrument_id,
    series_id,
    ticker,
    isin,
    cusip,
    lei,
    name,
    fund_type,
    strategy_label,
    asset_class,
    is_index,
    expense_ratio,
    aum_usd,
    primary_benchmark,
    inception_date,
    domicile,
    currency
FROM funds_v
WITH NO DATA;

CREATE UNIQUE INDEX funds_profile_mv_pk
    ON funds_profile_mv (instrument_id);

CREATE INDEX funds_profile_mv_series_idx
    ON funds_profile_mv (series_id);

CREATE INDEX funds_profile_mv_ticker_idx
    ON funds_profile_mv (ticker)
    WHERE ticker IS NOT NULL;

CREATE INDEX funds_profile_mv_taxonomy_idx
    ON funds_profile_mv (fund_type, strategy_label, asset_class);

CREATE MATERIALIZED VIEW fund_classes_latest_mv AS
SELECT
    class_id,
    series_id,
    class_name,
    ticker,
    expense_ratio,
    source_period_end,
    synced_at
FROM fund_classes_v
WITH NO DATA;

CREATE UNIQUE INDEX fund_classes_latest_mv_pk
    ON fund_classes_latest_mv (class_id);

CREATE INDEX fund_classes_latest_mv_series_idx
    ON fund_classes_latest_mv (series_id, expense_ratio, ticker);

CREATE INDEX fund_classes_latest_mv_ticker_idx
    ON fund_classes_latest_mv (ticker, series_id);

REFRESH MATERIALIZED VIEW funds_profile_mv;
REFRESH MATERIALIZED VIEW fund_classes_latest_mv;

ANALYZE funds_profile_mv;
ANALYZE fund_classes_latest_mv;
