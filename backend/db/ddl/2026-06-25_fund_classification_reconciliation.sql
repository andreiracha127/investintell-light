-- Reconcile broad Large Blend labels against ETF identity and N-PORT look-through.
--
-- This migration addresses the failure mode where low-confidence generic
-- reclassification rows (especially classification_source='asset_class') and
-- peer_strategy_label collapse non-equity funds into Large Blend / equity.
--
-- Prerequisite: run the updated 2026-06-13_dynamic_catalog.sql first so funds_v
-- detects ETF identity from series/name text and recognizes Long/Short Equity.

WITH run AS (
    SELECT gen_random_uuid() AS run_id
),
base_universe AS (
    SELECT
        f.instrument_id,
        f.series_id,
        f.ticker,
        f.name,
        f.fund_type,
        f.strategy_label AS current_strategy_label,
        f.asset_class AS current_asset_class,
        lower(coalesce(f.name, '') || ' ' || coalesce(f.ticker, '')) AS text_blob
    FROM funds_v f
    WHERE f.strategy_label = 'Large Blend'
      AND f.asset_class = 'equity'
),
latest_lookthrough AS (
    SELECT e.series_id, max(e.report_date) AS report_date
    FROM nport_lookthrough_exposures e
    JOIN base_universe b ON b.series_id = e.series_id
    WHERE e.dimension = 'asset_class'
    GROUP BY e.series_id
),
asset_mix AS (
    SELECT
        b.instrument_id,
        b.series_id,
        b.ticker,
        b.name,
        b.fund_type,
        b.current_strategy_label,
        b.current_asset_class,
        b.text_blob,
        l.report_date,
        coalesce(s.coverage_pct, 0) AS coverage_pct,
        sum(coalesce(e.direct_pct, 0) + coalesce(e.indirect_pct, 0)) FILTER (
            WHERE e.key IN ('DBT', 'DB', 'D', 'LON')
        ) AS debt_pct,
        sum(coalesce(e.direct_pct, 0) + coalesce(e.indirect_pct, 0)) FILTER (
            WHERE e.key IN ('ABS-MBS', 'ABS-CBDO', 'ABS-O', 'SN')
        ) AS structured_pct,
        sum(coalesce(e.direct_pct, 0) + coalesce(e.indirect_pct, 0)) FILTER (
            WHERE e.key IN ('STIV', 'RF')
        ) AS cash_pct,
        sum(coalesce(e.direct_pct, 0) + coalesce(e.indirect_pct, 0)) FILTER (
            WHERE e.key IN ('EC', 'EP', 'EF', 'EU')
        ) AS equity_pct
    FROM base_universe b
    JOIN latest_lookthrough l ON l.series_id = b.series_id
    JOIN nport_lookthrough_exposures e
      ON e.series_id = l.series_id
     AND e.report_date = l.report_date
     AND e.dimension = 'asset_class'
    LEFT JOIN nport_lookthrough_summary s
      ON s.series_id = l.series_id
     AND s.report_date = l.report_date
    GROUP BY
        b.instrument_id,
        b.series_id,
        b.ticker,
        b.name,
        b.fund_type,
        b.current_strategy_label,
        b.current_asset_class,
        b.text_blob,
        l.report_date,
        s.coverage_pct
),
eligible AS (
    SELECT
        *,
        coalesce(debt_pct, 0) + coalesce(structured_pct, 0) + coalesce(cash_pct, 0)
            AS fi_cash_pct
    FROM asset_mix
    WHERE coverage_pct >= 80
      AND coalesce(debt_pct, 0) + coalesce(structured_pct, 0) + coalesce(cash_pct, 0) >= 70
      AND coalesce(equity_pct, 0) < 50
),
classified AS (
    SELECT
        *,
        CASE
            WHEN text_blob ~ '(1x short|short dow|short s[& ]p|inverse|bear)'
                THEN 'Inverse / Hedge'
            WHEN text_blob ~ '(managed futures|arbitrage|market neutral|alternative|multi.?strategy|volatility premium)'
                THEN 'Alternative'
            WHEN text_blob ~ '(putwrite|put.write|option income|covered call|defined outcome|buffer)'
                THEN 'Defined Outcome / Option Income'
            WHEN text_blob ~ '(doge|bitcoin|btc|crypto|ether)'
                THEN 'Crypto / Digital Assets'
            WHEN text_blob ~ '(municipal|tax.?free|tax.?exempt|\mmuni\M)'
                THEN 'Municipal Bond'
            WHEN text_blob ~ '(inflation|tips)'
                THEN 'Inflation-Linked Bond'
            WHEN text_blob ~ '(treasury|government)'
                THEN 'Government Bond'
            WHEN text_blob ~ '(senior loan|floating rate|bank loan|high.?yield)'
                THEN 'High Yield Bond'
            WHEN text_blob ~ '(mortgage|mbs|cmbs)'
                THEN 'Mortgage-Backed Securities'
            WHEN text_blob ~ '(clo|collateralized loan|asset.?backed|\mabs\M|securitized)'
              OR coalesce(structured_pct, 0) >= 50
                THEN 'Structured Credit'
            WHEN text_blob ~ '(corporate|investment grade|ibonds|term corporate|\maaa\M)'
                THEN 'Investment Grade Bond'
            WHEN coalesce(cash_pct, 0) >= 80
             AND coalesce(debt_pct, 0) + coalesce(structured_pct, 0) < 20
                THEN 'Cash Equivalent'
            WHEN coalesce(debt_pct, 0) + coalesce(structured_pct, 0) >= 70
                THEN 'Structured Credit'
            WHEN fi_cash_pct >= 70
                THEN 'Intermediate-Term Bond'
        END AS proposed_strategy_label,
        CASE
            WHEN text_blob ~ '(1x short|short dow|short s[& ]p|inverse|bear)'
                THEN 'large_blend_reconcile_inverse_name'
            WHEN text_blob ~ '(managed futures|arbitrage|market neutral|alternative|multi.?strategy|volatility premium)'
                THEN 'large_blend_reconcile_alternative_name'
            WHEN text_blob ~ '(putwrite|put.write|option income|covered call|defined outcome|buffer)'
                THEN 'large_blend_reconcile_option_income_name'
            WHEN text_blob ~ '(doge|bitcoin|btc|crypto|ether)'
                THEN 'large_blend_reconcile_crypto_name'
            WHEN text_blob ~ '(municipal|tax.?free|tax.?exempt|\mmuni\M)'
                THEN 'large_blend_reconcile_municipal_name'
            WHEN text_blob ~ '(inflation|tips)'
                THEN 'large_blend_reconcile_inflation_name'
            WHEN text_blob ~ '(treasury|government)'
                THEN 'large_blend_reconcile_government_name'
            WHEN text_blob ~ '(senior loan|floating rate|bank loan|high.?yield)'
                THEN 'large_blend_reconcile_high_yield_name'
            WHEN text_blob ~ '(mortgage|mbs|cmbs)'
                THEN 'large_blend_reconcile_mbs_name'
            WHEN text_blob ~ '(clo|collateralized loan|asset.?backed|\mabs\M|securitized)'
              OR coalesce(structured_pct, 0) >= 50
                THEN 'large_blend_reconcile_structured_name_or_holdings'
            WHEN text_blob ~ '(corporate|investment grade|ibonds|term corporate|\maaa\M)'
                THEN 'large_blend_reconcile_investment_grade_name'
            WHEN coalesce(cash_pct, 0) >= 80
             AND coalesce(debt_pct, 0) + coalesce(structured_pct, 0) < 20
                THEN 'large_blend_reconcile_cash_holdings'
            WHEN coalesce(debt_pct, 0) + coalesce(structured_pct, 0) >= 70
                THEN 'large_blend_reconcile_debt_holdings'
            WHEN fi_cash_pct >= 70
                THEN 'large_blend_reconcile_fi_cash_holdings'
        END AS matched_pattern
    FROM eligible
),
overrides AS (
    SELECT *
    FROM classified
    WHERE proposed_strategy_label IS NOT NULL
      AND proposed_strategy_label <> current_strategy_label
)
INSERT INTO strategy_reclassification_stage (
    run_id,
    source_table,
    source_pk,
    fund_name,
    fund_type,
    current_strategy_label,
    proposed_strategy_label,
    classification_source,
    matched_pattern,
    confidence,
    classified_at,
    applied_at,
    applied_by,
    applied_batch_id
)
SELECT
    run.run_id,
    'instruments_universe',
    overrides.instrument_id::text,
    overrides.name,
    overrides.fund_type,
    overrides.current_strategy_label,
    overrides.proposed_strategy_label,
    'manual_override',
    overrides.matched_pattern,
    CASE
        WHEN overrides.matched_pattern IN (
            'large_blend_reconcile_debt_holdings',
            'large_blend_reconcile_fi_cash_holdings'
        ) THEN 'medium'
        ELSE 'high'
    END,
    now(),
    now(),
    'codex',
    run.run_id
FROM overrides
CROSS JOIN run
WHERE NOT EXISTS (
    SELECT 1
    FROM strategy_reclassification_stage existing
    WHERE existing.source_table = 'instruments_universe'
      AND existing.source_pk = overrides.instrument_id::text
      AND existing.classification_source = 'manual_override'
);

UPDATE instruments_universe iu
SET asset_class = public.asset_class_from_strategy(fv.strategy_label)
FROM funds_v fv
WHERE fv.instrument_id = iu.instrument_id
  AND public.asset_class_from_strategy(fv.strategy_label) IS NOT NULL
  AND iu.asset_class IS DISTINCT FROM public.asset_class_from_strategy(fv.strategy_label);

DO $$
BEGIN
    IF to_regclass('public.funds_profile_mv') IS NOT NULL THEN
        EXECUTE 'REFRESH MATERIALIZED VIEW public.funds_profile_mv';
    END IF;
    IF to_regclass('public.funds_list_mv') IS NOT NULL THEN
        EXECUTE 'REFRESH MATERIALIZED VIEW public.funds_list_mv';
    END IF;
    IF to_regclass('public.fund_class_resolution_mv') IS NOT NULL THEN
        EXECUTE 'REFRESH MATERIALIZED VIEW public.fund_class_resolution_mv';
    END IF;
END $$;
