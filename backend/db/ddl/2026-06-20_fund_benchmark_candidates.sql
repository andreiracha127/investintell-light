-- Fund benchmark resolution candidates.
--
-- This view is additive/read-only. It repairs the SEC registered-fund benchmark
-- lineage where most source rows carry primary_benchmark but no series_id by
-- crosswalking the registered fund name back to the series name / instrument
-- universe name, then resolving the benchmark name through the canonical
-- benchmark -> proxy ETF map.

CREATE OR REPLACE VIEW fund_benchmark_candidates_v AS
WITH direct_sources AS (
    SELECT
        NULLIF(btrim(series_id), '') AS series_id,
        NULLIF(btrim(primary_benchmark), '') AS benchmark_name,
        'direct_series'::text AS resolution_method
    FROM sec_registered_funds
    WHERE NULLIF(btrim(series_id), '') IS NOT NULL
      AND NULLIF(btrim(primary_benchmark), '') IS NOT NULL
),
missing_series_sources AS (
    SELECT
        fund_name,
        NULLIF(btrim(primary_benchmark), '') AS benchmark_name,
        lower(regexp_replace(coalesce(fund_name, ''), '[^a-zA-Z0-9]+', '', 'g')) AS normalized_name
    FROM sec_registered_funds
    WHERE NULLIF(btrim(primary_benchmark), '') IS NOT NULL
      AND NULLIF(btrim(series_id), '') IS NULL
),
class_names AS (
    SELECT DISTINCT
        series_id,
        lower(regexp_replace(coalesce(series_name, ''), '[^a-zA-Z0-9]+', '', 'g')) AS normalized_name
    FROM sec_fund_classes
    WHERE series_id IS NOT NULL
      AND NULLIF(btrim(series_name), '') IS NOT NULL
),
universe_names AS (
    SELECT DISTINCT
        ii.sec_series_id AS series_id,
        lower(regexp_replace(coalesce(iu.name, ''), '[^a-zA-Z0-9]+', '', 'g')) AS normalized_name
    FROM instruments_universe iu
    JOIN instrument_identity ii ON ii.instrument_id = iu.instrument_id
    WHERE ii.sec_series_id IS NOT NULL
      AND NULLIF(btrim(iu.name), '') IS NOT NULL
),
crosswalk_sources AS (
    SELECT
        c.series_id,
        s.benchmark_name,
        'class_name_exact'::text AS resolution_method
    FROM missing_series_sources s
    JOIN class_names c
      ON c.normalized_name = s.normalized_name
     AND s.normalized_name <> ''
    UNION
    SELECT
        u.series_id,
        s.benchmark_name,
        'universe_name_exact'::text AS resolution_method
    FROM missing_series_sources s
    JOIN universe_names u
      ON u.normalized_name = s.normalized_name
     AND s.normalized_name <> ''
),
all_sources AS (
    SELECT * FROM direct_sources
    UNION
    SELECT * FROM crosswalk_sources
),
per_series AS (
    SELECT
        series_id,
        min(benchmark_name) AS benchmark_name,
        count(DISTINCT benchmark_name) AS benchmark_name_count,
        CASE min(
            CASE resolution_method
                WHEN 'direct_series' THEN 1
                WHEN 'class_name_exact' THEN 2
                WHEN 'universe_name_exact' THEN 3
                ELSE 99
            END
        )
            WHEN 1 THEN 'direct_series'
            WHEN 2 THEN 'class_name_exact'
            WHEN 3 THEN 'universe_name_exact'
            ELSE 'unknown'
        END AS benchmark_resolution_method
    FROM all_sources
    WHERE series_id IS NOT NULL
      AND benchmark_name IS NOT NULL
    GROUP BY series_id
),
active_map AS (
    SELECT
        benchmark_name_canonical,
        benchmark_name_aliases,
        proxy_etf_ticker,
        asset_class::text AS proxy_asset_class,
        fit_quality_score
    FROM benchmark_etf_canonical_map
    WHERE current_date BETWEEN effective_from AND effective_to
),
map_matches AS (
    SELECT
        p.series_id,
        p.benchmark_name,
        p.benchmark_name_count,
        p.benchmark_resolution_method,
        m.benchmark_name_canonical,
        m.proxy_etf_ticker,
        m.proxy_asset_class,
        m.fit_quality_score
    FROM per_series p
    LEFT JOIN active_map m
      ON p.benchmark_name = m.benchmark_name_canonical
      OR p.benchmark_name = ANY(m.benchmark_name_aliases)
),
resolved AS (
    SELECT
        series_id,
        benchmark_name,
        benchmark_resolution_method,
        benchmark_name_count,
        count(DISTINCT proxy_etf_ticker) FILTER (WHERE proxy_etf_ticker IS NOT NULL) AS proxy_count,
        array_remove(array_agg(DISTINCT proxy_etf_ticker ORDER BY proxy_etf_ticker), NULL) AS proxy_candidates,
        array_remove(array_agg(DISTINCT benchmark_name_canonical ORDER BY benchmark_name_canonical), NULL) AS canonical_name_matches,
        min(proxy_etf_ticker) AS proxy_etf_ticker,
        max(proxy_asset_class) AS proxy_asset_class,
        max(fit_quality_score) AS fit_quality_score
    FROM map_matches
    GROUP BY series_id, benchmark_name, benchmark_resolution_method, benchmark_name_count
)
SELECT
    series_id,
    benchmark_name,
    CASE WHEN proxy_count = 1 THEN proxy_etf_ticker END AS benchmark_proxy_ticker,
    CASE WHEN proxy_count = 1 THEN fit_quality_score END AS benchmark_proxy_fit_quality_score,
    CASE WHEN proxy_count = 1 THEN proxy_asset_class END AS benchmark_proxy_asset_class,
    benchmark_resolution_method,
    (benchmark_name_count > 1 OR proxy_count > 1) AS benchmark_resolution_conflict,
    coalesce(proxy_candidates, ARRAY[]::text[]) AS benchmark_proxy_candidates,
    coalesce(canonical_name_matches, ARRAY[]::text[]) AS benchmark_canonical_name_matches
FROM resolved;
