-- backend/db/ddl/2026-06-21_fund_style_bias_v.sql
-- A1 (style-bias) — z-scores cross-section por fator de estilo, db-first.
-- Espelha _style_bias: para cada (instrument_id, as_of), z = (value − AVG) /
-- STDDEV_SAMP sobre todos os fundos daquele as_of. Long-format: uma linha por
-- (instrument_id, as_of, factor). É VIEW (sem materialização) — leve e sempre
-- fresca sobre equity_characteristics_monthly (spec §6 A1, "view/função SQL").

CREATE OR REPLACE VIEW fund_style_bias_v AS
WITH stats AS (
    SELECT
        instrument_id,
        as_of,
        size_log_mkt_cap,
        book_to_market,
        mom_12_1,
        quality_roa,
        investment_growth,
        profitability_gross,
        avg(size_log_mkt_cap)        OVER (PARTITION BY as_of) AS a_size,
        stddev_samp(size_log_mkt_cap) OVER (PARTITION BY as_of) AS s_size,
        avg(book_to_market)          OVER (PARTITION BY as_of) AS a_btm,
        stddev_samp(book_to_market)  OVER (PARTITION BY as_of) AS s_btm,
        avg(mom_12_1)                OVER (PARTITION BY as_of) AS a_mom,
        stddev_samp(mom_12_1)        OVER (PARTITION BY as_of) AS s_mom,
        avg(quality_roa)             OVER (PARTITION BY as_of) AS a_qua,
        stddev_samp(quality_roa)     OVER (PARTITION BY as_of) AS s_qua,
        avg(investment_growth)       OVER (PARTITION BY as_of) AS a_inv,
        stddev_samp(investment_growth) OVER (PARTITION BY as_of) AS s_inv,
        avg(profitability_gross)     OVER (PARTITION BY as_of) AS a_pro,
        stddev_samp(profitability_gross) OVER (PARTITION BY as_of) AS s_pro
    FROM equity_characteristics_monthly
)
SELECT instrument_id, as_of, factor, value, z_score FROM (
    SELECT instrument_id, as_of, 'size'::text AS factor, size_log_mkt_cap AS value,
           CASE WHEN s_size > 0 THEN (size_log_mkt_cap - a_size) / s_size END AS z_score FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'book_to_market', book_to_market,
           CASE WHEN s_btm > 0 THEN (book_to_market - a_btm) / s_btm END FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'momentum', mom_12_1,
           CASE WHEN s_mom > 0 THEN (mom_12_1 - a_mom) / s_mom END FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'quality', quality_roa,
           CASE WHEN s_qua > 0 THEN (quality_roa - a_qua) / s_qua END FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'investment', investment_growth,
           CASE WHEN s_inv > 0 THEN (investment_growth - a_inv) / s_inv END FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'profitability', profitability_gross,
           CASE WHEN s_pro > 0 THEN (profitability_gross - a_pro) / s_pro END FROM stats
) z;
