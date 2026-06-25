-- backend/db/ddl/2026-06-25_fund_class_resolution_mv.sql
-- Share-class ticker resolver for portfolio overview misses.
--
-- funds_v and fund_classes_v remain the lineage views. This MV keeps
-- request-time portfolio reads off those dynamic views by flattening
-- fund_classes_v -> funds_list_mv once per refresh cycle.

DROP MATERIALIZED VIEW IF EXISTS fund_class_resolution_mv;

CREATE MATERIALIZED VIEW fund_class_resolution_mv AS
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
JOIN funds_list_mv fl ON fl.series_id = fc.series_id
WHERE fc.ticker IS NOT NULL
WITH NO DATA;

CREATE UNIQUE INDEX fund_class_resolution_mv_pk
    ON fund_class_resolution_mv (class_id, instrument_id);

CREATE INDEX fund_class_resolution_mv_ticker_idx
    ON fund_class_resolution_mv (class_ticker, instrument_id);

CREATE INDEX fund_class_resolution_mv_instrument_idx
    ON fund_class_resolution_mv (instrument_id);

REFRESH MATERIALIZED VIEW fund_class_resolution_mv;
