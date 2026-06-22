-- backend/db/ddl/2026-06-21_fund_active_share_mv.sql
-- A5 — Active share db-first vs benchmark PRIMÁRIO (mudança de produto, spec §6 A5).
-- Benchmark via fund_benchmark_candidates_v.benchmark_proxy_instrument_id → ticker
-- do ETF (instruments_universe) → série em sec_nport_holdings. Pesos = SUM(pct_of_nav)/100
-- por CUSIP no report_date mais recente de cada série. active_share = 0.5·Σ|w_f − w_b|;
-- overlap = Σ min(w_f, w_b). Refrescada por matview_refresh (índice UNIQUE obrigatório).

CREATE MATERIALIZED VIEW IF NOT EXISTS fund_active_share_mv AS
WITH bench AS (
    -- série N-PORT do ETF proxy primário de cada fundo
    SELECT c.series_id AS fund_series_id,
           c.benchmark_proxy_instrument_id,
           c.benchmark_name,
           bser.benchmark_series_id
    FROM fund_benchmark_candidates_v c
    JOIN LATERAL (
        SELECT min(nh.series_id) AS benchmark_series_id
        FROM instruments_universe iu
        JOIN sec_etfs se ON upper(se.ticker) = upper(iu.ticker)
        JOIN sec_nport_holdings nh ON nh.series_id = se.series_id
        WHERE iu.instrument_id = c.benchmark_proxy_instrument_id
    ) bser ON TRUE
    WHERE c.benchmark_proxy_instrument_id IS NOT NULL
      AND bser.benchmark_series_id IS NOT NULL
),
fund_w AS (
    SELECT h.series_id, upper(h.cusip) AS cusip,
           SUM(h.pct_of_nav) / 100.0 AS w,
           max(h.report_date) OVER (PARTITION BY h.series_id) AS as_of
    FROM sec_nport_holdings h
    JOIN (
        SELECT series_id, max(report_date) AS rd
        FROM sec_nport_holdings GROUP BY series_id
    ) lf ON lf.series_id = h.series_id AND lf.rd = h.report_date
    WHERE h.cusip IS NOT NULL AND h.pct_of_nav IS NOT NULL
    GROUP BY h.series_id, upper(h.cusip), h.report_date
),
bench_w AS (
    SELECT h.series_id, upper(h.cusip) AS cusip,
           SUM(h.pct_of_nav) / 100.0 AS w,
           max(h.report_date) OVER (PARTITION BY h.series_id) AS as_of
    FROM sec_nport_holdings h
    JOIN (
        SELECT series_id, max(report_date) AS rd
        FROM sec_nport_holdings GROUP BY series_id
    ) lb ON lb.series_id = h.series_id AND lb.rd = h.report_date
    WHERE h.cusip IS NOT NULL AND h.pct_of_nav IS NOT NULL
    GROUP BY h.series_id, upper(h.cusip), h.report_date
),
joined AS (
    SELECT b.fund_series_id AS series_id,
           b.benchmark_series_id,
           b.benchmark_proxy_instrument_id,
           b.benchmark_name,
           fw.cusip,
           COALESCE(fw.w, 0.0) AS wf,
           COALESCE(bw.w, 0.0) AS wb,
           fw.as_of AS fund_as_of,
           bw.as_of AS bench_as_of
    FROM bench b
    LEFT JOIN fund_w  fw ON fw.series_id = b.fund_series_id
    FULL OUTER JOIN bench_w bw
      ON bw.series_id = b.benchmark_series_id AND bw.cusip = fw.cusip
)
SELECT series_id,
       benchmark_series_id,
       benchmark_proxy_instrument_id,
       benchmark_name,
       0.5 * SUM(abs(wf - wb))                               AS active_share,
       SUM(LEAST(wf, wb))                                    AS overlap,
       count(*) FILTER (WHERE wf > 0)                        AS n_portfolio,
       count(*) FILTER (WHERE wb > 0)                        AS n_benchmark,
       count(*) FILTER (WHERE wf > 0 AND wb > 0)             AS n_common,
       LEAST(max(fund_as_of), max(bench_as_of))             AS as_of
FROM joined
GROUP BY series_id, benchmark_series_id, benchmark_proxy_instrument_id, benchmark_name
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS fund_active_share_mv_pk
  ON fund_active_share_mv (series_id);

REFRESH MATERIALIZED VIEW fund_active_share_mv;
