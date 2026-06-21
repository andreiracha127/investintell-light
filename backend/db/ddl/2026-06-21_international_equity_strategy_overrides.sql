-- Reclassify international equity regional buckets.
--
-- International Equity was absorbing Europe/Asia/EM/global funds, while some
-- Emerging Markets rows were actually broad international/global products.
-- This migration uses the fund name first and the declared benchmark as a
-- fallback, then persists the reviewed regional label as a manual override.

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
        lower(f.name) AS name_blob,
        lower(
            CASE
                WHEN c.benchmark_resolution_method = 'strategy_label_proxy' THEN ''
                ELSE coalesce(c.benchmark_name, '')
            END
        ) AS benchmark_blob
    FROM funds_v f
    LEFT JOIN fund_benchmark_candidates_v c
      ON c.series_id = f.series_id
    WHERE f.strategy_label IN (
        'Asian Equity',
        'Emerging Markets Equity',
        'European Equity',
        'Global Equity',
        'International Equity'
    )
),
classified AS (
    SELECT
        *,
        CASE
            WHEN name_blob ~ '(eupac|international|intl|foreign|eafe|developed markets|ex-us|ex us|ex usa|world ex|global ex us|global ex-u.s.|global ex u.s.|global ex u s|global ex-us|international developed|developed ex)'
                THEN 'International Equity'
            WHEN name_blob ~ '(emerging markets|emerging market|frontier|china|india|brazil|latin america|latin american|south africa|indonesia|malaysia|philippines|thailand|turkey|saudi|qatar|kuwait|uae|poland|chile|bic)'
                THEN 'Emerging Markets Equity'
            WHEN name_blob ~ '(europe|european|eurozone|euro area|stoxx|germany|france|switzerland|united kingdom|\muk\M|italy|spain|netherlands|denmark|sweden|norway|finland|ireland|austria|belgium)'
                THEN 'European Equity'
            WHEN name_blob ~ '(all country asia ex japan|asia pacific|pacific ex japan|asia ex japan|asia|japan|hong kong|singapore|australia|new zealand|korea|taiwan)'
                THEN 'Asian Equity'
            WHEN name_blob ~ '(global|world|all country|acwi)'
             AND name_blob !~ '(world ex|ex-us|ex us|ex usa|global ex)'
                THEN 'Global Equity'
            WHEN benchmark_blob ~ '(emerging markets|emerging market|frontier|msci em|emimi|em ex|china|india|brazil|latin america)'
                THEN 'Emerging Markets Equity'
            WHEN benchmark_blob ~ '(europe|eurozone|euro area|stoxx|ftse developed europe|msci europe|germany|france|switzerland|united kingdom|\muk\M|italy|spain|netherlands)'
                THEN 'European Equity'
            WHEN benchmark_blob ~ '(asia pacific|pacific ex japan|asia ex japan|japan|hong kong|singapore|australia|new zealand)'
                THEN 'Asian Equity'
            WHEN benchmark_blob ~ '(international|intl|foreign|eafe|developed markets|ex-us|ex us|ex usa|world ex|global ex us|global ex-u.s.|global ex u.s.|global ex u s|global ex-us)'
                THEN 'International Equity'
            WHEN benchmark_blob ~ '(global|world|acwi|all country world|msci world)'
             AND benchmark_blob !~ '(world ex|ex-us|ex us|ex usa|global ex)'
                THEN 'Global Equity'
            ELSE current_strategy_label
        END AS proposed_strategy_label,
        CASE
            WHEN name_blob ~ '(eupac|international|intl|foreign|eafe|developed markets|ex-us|ex us|ex usa|world ex|global ex us|global ex-u.s.|global ex u.s.|global ex u s|global ex-us|international developed|developed ex)'
                THEN 'international_review_name_international'
            WHEN name_blob ~ '(emerging markets|emerging market|frontier|china|india|brazil|latin america|latin american|south africa|indonesia|malaysia|philippines|thailand|turkey|saudi|qatar|kuwait|uae|poland|chile|bic)'
                THEN 'international_review_name_emerging_markets'
            WHEN name_blob ~ '(europe|european|eurozone|euro area|stoxx|germany|france|switzerland|united kingdom|\muk\M|italy|spain|netherlands|denmark|sweden|norway|finland|ireland|austria|belgium)'
                THEN 'international_review_name_european'
            WHEN name_blob ~ '(all country asia ex japan|asia pacific|pacific ex japan|asia ex japan|asia|japan|hong kong|singapore|australia|new zealand|korea|taiwan)'
                THEN 'international_review_name_asian'
            WHEN name_blob ~ '(global|world|all country|acwi)'
             AND name_blob !~ '(world ex|ex-us|ex us|ex usa|global ex)'
                THEN 'international_review_name_global'
            WHEN benchmark_blob ~ '(emerging markets|emerging market|frontier|msci em|emimi|em ex|china|india|brazil|latin america)'
                THEN 'international_review_benchmark_emerging_markets'
            WHEN benchmark_blob ~ '(europe|eurozone|euro area|stoxx|ftse developed europe|msci europe|germany|france|switzerland|united kingdom|\muk\M|italy|spain|netherlands)'
                THEN 'international_review_benchmark_european'
            WHEN benchmark_blob ~ '(asia pacific|pacific ex japan|asia ex japan|japan|hong kong|singapore|australia|new zealand)'
                THEN 'international_review_benchmark_asian'
            WHEN benchmark_blob ~ '(international|intl|foreign|eafe|developed markets|ex-us|ex us|ex usa|world ex|global ex us|global ex-u.s.|global ex u.s.|global ex u s|global ex-us)'
                THEN 'international_review_benchmark_international'
            WHEN benchmark_blob ~ '(global|world|acwi|all country world|msci world)'
             AND benchmark_blob !~ '(world ex|ex-us|ex us|ex usa|global ex)'
                THEN 'international_review_benchmark_global'
            ELSE 'international_review_keep'
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
        WHEN overrides.matched_pattern LIKE 'international_review_benchmark_%'
            THEN 'medium'
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
