-- backend/db/ddl/2026-06-25_fund_benchmark_candidates_mv.sql
-- Request-path snapshot for resolved fund benchmark proxies.
--
-- fund_benchmark_candidates_v preserves the full resolution lineage. The MV
-- keeps profile misses from recomputing that multi-source resolution graph.

DROP MATERIALIZED VIEW IF EXISTS fund_benchmark_candidates_mv;

CREATE MATERIALIZED VIEW fund_benchmark_candidates_mv AS
SELECT
    series_id,
    benchmark_name,
    benchmark_proxy_ticker,
    benchmark_proxy_instrument_id,
    benchmark_proxy_fit_quality_score,
    benchmark_proxy_asset_class,
    benchmark_resolution_method,
    benchmark_resolution_conflict,
    benchmark_proxy_candidates,
    benchmark_canonical_name_matches
FROM fund_benchmark_candidates_v
WHERE series_id IS NOT NULL
WITH NO DATA;

CREATE UNIQUE INDEX fund_benchmark_candidates_mv_pk
    ON fund_benchmark_candidates_mv (series_id);

REFRESH MATERIALIZED VIEW fund_benchmark_candidates_mv;

ANALYZE fund_benchmark_candidates_mv;
