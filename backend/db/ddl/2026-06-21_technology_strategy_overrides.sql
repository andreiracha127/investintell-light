-- Reclassify technology funds that were trapped in Large Blend / Sector Equity.
--
-- Technology was nearly empty because upstream labels routed most tech-sector
-- products into generic Large Blend or broad Sector Equity. This migration
-- keeps biotech/medical devices as Sector Equity, sends ex-technology broad
-- funds back to Large Blend, keeps option-income and inverse products in their
-- own buckets, and promotes pure technology exposure to Technology.

WITH run AS (
    SELECT gen_random_uuid() AS run_id
),
base AS (
    SELECT
        f.instrument_id,
        f.ticker,
        f.name,
        f.fund_type,
        f.strategy_label AS current_strategy_label,
        lower(
            f.name || ' ' ||
            CASE
                WHEN c.benchmark_resolution_method = 'strategy_label_proxy' THEN ''
                ELSE coalesce(c.benchmark_name, '')
            END
        ) AS text_blob
    FROM funds_v f
    LEFT JOIN fund_benchmark_candidates_v c
      ON c.series_id = f.series_id
    WHERE f.strategy_label IN ('Large Blend', 'Sector Equity', 'Technology')
      AND lower(f.name || ' ' || coalesce(c.benchmark_name, '')) ~
          '(technology|tech|semiconductor|software|cloud|internet|cyber|artificial intelligence|generative ai|robotics|automation|blockchain|fintech|data and digital|digital revolution|fang|cleantech|biotech|biotechnology|genome|medical devices|medical technology|nasdaq|option income|premium income|target income|weekly distribution|defined risk|short)'
),
classified AS (
    SELECT
        *,
        CASE
            WHEN text_blob ~ '(option income|premium income|target income|weekly distribution|covered call|defined risk|yieldmax|enhanced yield)'
                THEN 'Defined Outcome / Option Income'
            WHEN text_blob ~ '(ultrashort|ultra short|short nasdaq|short nvda|short qqq|short s[& ]p|inverse|bear)'
                THEN 'Inverse / Hedge'
            WHEN text_blob ~ '(ex-technology|ex technology|ex-tech)'
                THEN 'Large Blend'
            WHEN text_blob ~ '(biotech|biotechnology|genome|genomics|medical technology|medical devices|health and information technology|health technology)'
                THEN 'Sector Equity'
            WHEN text_blob ~ '(information technology|\mtech\M|technology select sector|technology index|technology fund|technology portfolio|science and technology|semiconductor|software|cloud computing|internet|cybersecurity|cybersecurity and tech|artificial intelligence|generative ai|robotics|automation|blockchain|fintech|data and digital revolution|digital revolution|expanded technology|technology dividend|technology alphadex|technology momentum|nanotechnology|cleantech)'
              OR text_blob ~ '(science & technology|fang|\mai\m)'
                THEN 'Technology'
            ELSE current_strategy_label
        END AS proposed_strategy_label,
        CASE
            WHEN text_blob ~ '(option income|premium income|target income|weekly distribution|covered call|defined risk|yieldmax|enhanced yield)'
                THEN 'technology_review_option_income'
            WHEN text_blob ~ '(ultrashort|ultra short|short nasdaq|short nvda|short qqq|short s[& ]p|inverse|bear)'
                THEN 'technology_review_inverse_hedge'
            WHEN text_blob ~ '(ex-technology|ex technology|ex-tech)'
                THEN 'technology_review_ex_technology_large_blend'
            WHEN text_blob ~ '(biotech|biotechnology|genome|genomics|medical technology|medical devices|health and information technology|health technology)'
                THEN 'technology_review_biotech_sector_equity'
            WHEN text_blob ~ '(information technology|\mtech\M|technology select sector|technology index|technology fund|technology portfolio|science and technology|semiconductor|software|cloud computing|internet|cybersecurity|cybersecurity and tech|artificial intelligence|generative ai|robotics|automation|blockchain|fintech|data and digital revolution|digital revolution|expanded technology|technology dividend|technology alphadex|technology momentum|nanotechnology|cleantech)'
              OR text_blob ~ '(science & technology|fang|\mai\m)'
                THEN 'technology_review_pure_technology'
            ELSE 'technology_review_keep'
        END AS matched_pattern
    FROM base
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
    CASE
        WHEN overrides.matched_pattern IN (
            'technology_review_option_income',
            'technology_review_inverse_hedge'
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
      AND existing.proposed_strategy_label = overrides.proposed_strategy_label
);

UPDATE instruments_universe iu
SET asset_class = public.asset_class_from_strategy(fv.strategy_label)
FROM funds_v fv
WHERE fv.instrument_id = iu.instrument_id
  AND public.asset_class_from_strategy(fv.strategy_label) IS NOT NULL
  AND iu.asset_class IS DISTINCT FROM public.asset_class_from_strategy(fv.strategy_label);
