-- Reclassify contaminated Alternative buckets into actionable strategy labels.
--
-- The broad "Alternative" label was catching cash-like ultra-short bond ETFs,
-- leveraged long products, inverse/hedge products, defined-outcome/option-income
-- products, and crypto-linked products. The catalog view now lets manual
-- overrides win over source labels; this idempotent data migration writes the
-- reviewed overrides to strategy_reclassification_stage.

INSERT INTO fund_strategy_benchmark_proxy_map (
    strategy_label,
    proxy_etf_ticker,
    proxy_asset_class,
    fit_quality_score,
    source,
    notes
) VALUES
    ('Crypto / Digital Assets', 'BITO', 'alternatives', 0.9000, 'strategy_label_proxy', 'Bitcoin-linked ETF proxy for digital-asset strategy funds.'),
    ('Defined Outcome / Option Income', 'BUFR', 'alternatives', 0.9000, 'strategy_label_proxy', 'Laddered buffer ETF proxy for defined-outcome and option-income funds.'),
    ('Inverse / Hedge', 'SH', 'alternatives', 0.8500, 'strategy_label_proxy', 'Short S&P 500 ETF proxy for inverse hedge strategies; preserves negative market exposure.'),
    ('Leveraged', 'SSO', 'alternatives', 0.8500, 'strategy_label_proxy', '2x S&P 500 ETF proxy for long leveraged equity exposure; declared benchmarks win when available.')
ON CONFLICT (strategy_label) DO UPDATE SET
    proxy_etf_ticker = EXCLUDED.proxy_etf_ticker,
    proxy_asset_class = EXCLUDED.proxy_asset_class,
    fit_quality_score = EXCLUDED.fit_quality_score,
    source = EXCLUDED.source,
    notes = EXCLUDED.notes,
    updated_at = now();

DELETE FROM fund_strategy_benchmark_proxy_map
WHERE strategy_label = 'Leveraged / Inverse';

WITH run AS (
    SELECT gen_random_uuid() AS run_id
),
classified AS (
    SELECT
        f.instrument_id,
        f.ticker,
        f.name,
        f.fund_type,
        f.strategy_label AS current_strategy_label,
        CASE
            WHEN lower(f.name) ~ '(ultra[- ]short|short[- ]term income|short duration|short[- ]term bond|municipal income|government active exchange-traded|duration fund)'
                THEN 'Cash Equivalent'
            WHEN lower(f.name) ~ '(bitcoin|btc|ether|crypto)'
                THEN 'Crypto / Digital Assets'
            WHEN lower(f.name) ~ '(inverse|bear|1x short|short qqq|short s[& ]p|short 20\+|short innovation)'
                THEN 'Inverse / Hedge'
            WHEN lower(f.name) ~ '(ultrapro|ultra |2x|3x|bull|leveraged long|[0-9]+(\.[0-9]+)?x long)'
                THEN 'Leveraged'
            WHEN lower(f.name) ~ '(buffer|defined outcome|floor|hedged equity|option strategy|option income|yieldmax|yieldboost|covered call|weeklypay|income strategy)'
                THEN 'Defined Outcome / Option Income'
            ELSE 'Alternative'
        END AS proposed_strategy_label,
        CASE
            WHEN lower(f.name) ~ '(ultra[- ]short|short[- ]term income|short duration|short[- ]term bond|municipal income|government active exchange-traded|duration fund)'
                THEN 'alternative_review_cash_like_fixed_income'
            WHEN lower(f.name) ~ '(bitcoin|btc|ether|crypto)'
                THEN 'alternative_review_crypto_digital_assets'
            WHEN lower(f.name) ~ '(inverse|bear|1x short|short qqq|short s[& ]p|short 20\+|short innovation)'
                THEN 'alternative_review_inverse_hedge'
            WHEN lower(f.name) ~ '(ultrapro|ultra |2x|3x|bull|leveraged long|[0-9]+(\.[0-9]+)?x long)'
                THEN 'alternative_review_leveraged'
            WHEN lower(f.name) ~ '(buffer|defined outcome|floor|hedged equity|option strategy|option income|yieldmax|yieldboost|covered call|weeklypay|income strategy)'
                THEN 'alternative_review_defined_outcome_option_income'
            ELSE 'alternative_review_classic_other'
        END AS matched_pattern
    FROM funds_v f
    WHERE f.strategy_label IN ('Alternative', 'Leveraged / Inverse')
       OR lower(f.name) ~ '(bitcoin|btc|ether|crypto)'
       OR lower(f.name) ~ '(inverse|bear|1x short|short qqq|short s[& ]p|short 20\+|short innovation)'
       OR lower(f.name) ~ '(ultrapro|ultra |2x|3x|bull|leveraged long|[0-9]+(\.[0-9]+)?x long)'
       OR lower(f.name) ~ '(buffer|defined outcome|floor|hedged equity|option strategy|option income|yieldmax|yieldboost|covered call|weeklypay|income strategy)'
),
overrides AS (
    SELECT *
    FROM classified
    WHERE proposed_strategy_label <> current_strategy_label
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
    'high',
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
      AND existing.proposed_strategy_label = overrides.proposed_strategy_label
);

WITH run AS (
    SELECT gen_random_uuid() AS run_id
),
latest_manual AS (
    SELECT DISTINCT ON (source_pk)
        source_pk,
        fund_name,
        fund_type,
        current_strategy_label,
        proposed_strategy_label,
        matched_pattern,
        classified_at
    FROM strategy_reclassification_stage
    WHERE source_table = 'instruments_universe'
      AND classification_source = 'manual_override'
    ORDER BY source_pk, classified_at DESC, stage_id DESC
),
cash_reverts AS (
    SELECT *
    FROM latest_manual
    WHERE proposed_strategy_label = 'Cash Equivalent'
      AND matched_pattern = 'alternative_review_cash_like_fixed_income'
      AND current_strategy_label IS NOT NULL
      AND current_strategy_label NOT IN ('Alternative', 'Leveraged / Inverse', 'Cash Equivalent')
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
    cash_reverts.source_pk,
    cash_reverts.fund_name,
    cash_reverts.fund_type,
    cash_reverts.proposed_strategy_label,
    cash_reverts.current_strategy_label,
    'manual_override',
    'alternative_review_cash_like_revert_broad_rule',
    'high',
    now(),
    now(),
    'codex',
    run.run_id
FROM cash_reverts
CROSS JOIN run
WHERE NOT EXISTS (
    SELECT 1
    FROM strategy_reclassification_stage existing
    WHERE existing.source_table = 'instruments_universe'
      AND existing.source_pk = cash_reverts.source_pk
      AND existing.classification_source = 'manual_override'
      AND existing.proposed_strategy_label = cash_reverts.current_strategy_label
      AND existing.classified_at > cash_reverts.classified_at
);

UPDATE instruments_universe iu
SET asset_class = public.asset_class_from_strategy(fv.strategy_label)
FROM funds_v fv
WHERE fv.instrument_id = iu.instrument_id
  AND public.asset_class_from_strategy(fv.strategy_label) IS NOT NULL
  AND iu.asset_class IS DISTINCT FROM public.asset_class_from_strategy(fv.strategy_label);
