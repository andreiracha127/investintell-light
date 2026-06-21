-- Reclassify contaminated real-asset and balanced buckets.
--
-- Upstream strategy labels were over-assigning Balanced, Real Estate,
-- Commodities, and Precious Metals. This migration applies conservative
-- name/declared-benchmark rules and persists the result as manual overrides so
-- funds_v remains DB-first.

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
    WHERE f.strategy_label IN (
        'Balanced',
        'Commodities',
        'Precious Metals',
        'Real Estate'
    )
),
classified AS (
    SELECT
        *,
        CASE
            WHEN text_blob ~ '(target date|target retirement|smartretirement|retirement 20[0-9][0-9]|lifepath|freedom [0-9]{4})'
                THEN 'Target Date'
            WHEN text_blob ~ '(multi[- ]asset|asset allocation|balanced allocation|conservative allocation|moderate allocation|inflation response multi[- ]asset)'
                THEN 'Balanced'
            WHEN text_blob ~ '(real estate securities|real estate fund|reit)'
                THEN 'Real Estate'
            WHEN current_strategy_label = 'Real Estate'
             AND text_blob ~ '(real estate|reit|realty|real estate select sector|real estate index|real estate income|real estate securities)'
                THEN 'Real Estate'
            WHEN current_strategy_label = 'Precious Metals'
             AND text_blob ~ '(gold|silver|precious metals|rare earth|strategic metals|gold miners|silver miners)'
                THEN 'Precious Metals'
            WHEN text_blob ~ '(precious metals|silver|gold fund|gold strategy|go gold|gold explorers|gold enhanced|gold high income|physical gold)'
             AND text_blob !~ 'goldman'
                THEN 'Precious Metals'
            WHEN text_blob ~ '(balanced-risk allocation|multi[- ]asset|asset allocation|global allocation|risk allocation)'
                THEN 'Balanced'
            WHEN text_blob ~ '(managed futures|systematic macro|diversified macro|macro fund|futures strategy)'
                THEN 'Alternative'
            WHEN text_blob ~ '(commodity|commodities|all commodity|commodity strategy|commodity return|bloomberg commodity)'
                THEN 'Commodities'
            WHEN text_blob ~ '(balanced|asset allocation|global allocation|risk allocation|multi[- ]asset|growth and income|income builder|managed income|puritan|wellesley|star fund|conservative|moderate|crescent|franklin income fund|60%|60/40|50%)'
                THEN 'Balanced'
            WHEN text_blob ~ '(materials|natural resources|global resources|commodity stock|capital cycles|metals & mining|metals and mining|mining producers|uranium|nuclear|copper|lithium|battery|energy infrastructure|mlp|world energy)'
                THEN 'Sector Equity'
            WHEN text_blob ~ '(municipal|tax.free|tax free|muni)'
                THEN 'Municipal Bond'
            WHEN text_blob ~ '(high yield)'
             AND text_blob !~ '(dividend|equity)'
                THEN 'High Yield Bond'
            WHEN text_blob ~ '(treasury|u.s. government|us government|government bond|government securities|short duration government)'
                THEN 'Government Bond'
            WHEN text_blob ~ '(bond|fixed income|core plus|aggregate|duration|short.term|short duration|limited duration|income fund)'
             AND text_blob !~ '(equity income|income builder|growth and income)'
                THEN 'Intermediate-Term Bond'
            WHEN text_blob ~ '(emerging markets equity|emerging markets value|emerging markets index|emerging markets fund)'
                THEN 'Emerging Markets Equity'
            WHEN text_blob ~ '(global equity|global managed beta|msci world|global fund)'
                THEN 'Global Equity'
            WHEN text_blob ~ '(international equity|international index|acwi ex usa|eafe|overseas)'
                THEN 'International Equity'
            WHEN text_blob ~ '(mid cap value)'
                THEN 'Mid Value'
            WHEN text_blob ~ '(small.cap value)'
                THEN 'Small Value'
            WHEN text_blob ~ '(mid cap|mid.cap|midcap|smid)'
                THEN 'Mid Blend'
            WHEN text_blob ~ '(small cap|small.cap|smallcap)'
                THEN 'Small Blend'
            WHEN text_blob ~ '(growth|dynatech|technology|science)'
             AND text_blob !~ '(growth and income)'
                THEN 'Large Growth'
            WHEN text_blob ~ '(value|dividend|equity income|high dividend|comstock|oakmark)'
                THEN 'Large Value'
            WHEN text_blob ~ '(stock index|equity index|large cap|quality index|stock account|equity portfolio|focus fund|pioneer fund|tax-managed u.s. large cap|tax managed u.s. large cap|government street equity)'
                THEN 'Large Blend'
            WHEN current_strategy_label = 'Real Estate'
                THEN 'Large Blend'
            WHEN current_strategy_label = 'Precious Metals'
                THEN 'Alternative'
            ELSE current_strategy_label
        END AS proposed_strategy_label,
        CASE
            WHEN text_blob ~ '(target date|target retirement|smartretirement|retirement 20[0-9][0-9]|lifepath|freedom [0-9]{4})'
                THEN 'real_asset_review_target_date'
            WHEN text_blob ~ '(multi[- ]asset|asset allocation|balanced allocation|conservative allocation|moderate allocation|inflation response multi[- ]asset)'
                THEN 'real_asset_review_balanced_allocation'
            WHEN text_blob ~ '(real estate securities|real estate fund|reit)'
                THEN 'real_asset_review_real_estate_explicit'
            WHEN current_strategy_label = 'Real Estate'
             AND text_blob ~ '(real estate|reit|realty|real estate select sector|real estate index|real estate income|real estate securities)'
                THEN 'real_asset_review_keep_real_estate'
            WHEN current_strategy_label = 'Precious Metals'
             AND text_blob ~ '(gold|silver|precious metals|rare earth|strategic metals|gold miners|silver miners)'
                THEN 'real_asset_review_keep_precious_metals'
            WHEN text_blob ~ '(precious metals|silver|gold fund|gold strategy|go gold|gold explorers|gold enhanced|gold high income|physical gold)'
             AND text_blob !~ 'goldman'
                THEN 'real_asset_review_precious_metals'
            WHEN text_blob ~ '(balanced-risk allocation|multi[- ]asset|asset allocation|global allocation|risk allocation)'
                THEN 'real_asset_review_balanced_allocation'
            WHEN text_blob ~ '(managed futures|systematic macro|diversified macro|macro fund|futures strategy)'
                THEN 'real_asset_review_alternative_macro_futures'
            WHEN text_blob ~ '(commodity|commodities|all commodity|commodity strategy|commodity return|bloomberg commodity)'
                THEN 'real_asset_review_commodities'
            WHEN text_blob ~ '(balanced|asset allocation|global allocation|risk allocation|multi[- ]asset|growth and income|income builder|managed income|puritan|wellesley|star fund|conservative|moderate|crescent|franklin income fund|60%|60/40|50%)'
                THEN 'real_asset_review_balanced'
            WHEN text_blob ~ '(materials|natural resources|global resources|commodity stock|capital cycles|metals & mining|metals and mining|mining producers|uranium|nuclear|copper|lithium|battery|energy infrastructure|mlp|world energy)'
                THEN 'real_asset_review_sector_equity'
            WHEN text_blob ~ '(municipal|tax.free|tax free|muni)'
                THEN 'real_asset_review_municipal_bond'
            WHEN text_blob ~ '(high yield)'
             AND text_blob !~ '(dividend|equity)'
                THEN 'real_asset_review_high_yield_bond'
            WHEN text_blob ~ '(treasury|u.s. government|us government|government bond|government securities|short duration government)'
                THEN 'real_asset_review_government_bond'
            WHEN text_blob ~ '(bond|fixed income|core plus|aggregate|duration|short.term|short duration|limited duration|income fund)'
             AND text_blob !~ '(equity income|income builder|growth and income)'
                THEN 'real_asset_review_intermediate_bond'
            WHEN text_blob ~ '(emerging markets equity|emerging markets value|emerging markets index|emerging markets fund)'
                THEN 'real_asset_review_emerging_markets_equity'
            WHEN text_blob ~ '(global equity|global managed beta|msci world|global fund)'
                THEN 'real_asset_review_global_equity'
            WHEN text_blob ~ '(international equity|international index|acwi ex usa|eafe|overseas)'
                THEN 'real_asset_review_international_equity'
            WHEN text_blob ~ '(mid cap value)'
                THEN 'real_asset_review_mid_value'
            WHEN text_blob ~ '(small.cap value)'
                THEN 'real_asset_review_small_value'
            WHEN text_blob ~ '(mid cap|mid.cap|midcap|smid)'
                THEN 'real_asset_review_mid_blend'
            WHEN text_blob ~ '(small cap|small.cap|smallcap)'
                THEN 'real_asset_review_small_blend'
            WHEN text_blob ~ '(growth|dynatech|technology|science)'
             AND text_blob !~ '(growth and income)'
                THEN 'real_asset_review_large_growth'
            WHEN text_blob ~ '(value|dividend|equity income|high dividend|comstock|oakmark)'
                THEN 'real_asset_review_large_value'
            WHEN text_blob ~ '(stock index|equity index|large cap|quality index|stock account|equity portfolio|focus fund|pioneer fund|tax-managed u.s. large cap|tax managed u.s. large cap|government street equity)'
                THEN 'real_asset_review_large_blend'
            WHEN current_strategy_label = 'Real Estate'
                THEN 'real_asset_review_real_estate_fallback_large_blend'
            WHEN current_strategy_label = 'Precious Metals'
                THEN 'real_asset_review_precious_fallback_alternative'
            ELSE 'real_asset_review_keep'
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
        WHEN overrides.matched_pattern LIKE '%fallback%' THEN 'medium'
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

WITH run AS (
    SELECT gen_random_uuid() AS run_id
),
latest_precious_fallbacks AS (
    SELECT DISTINCT ON (source_pk)
        source_pk,
        fund_name,
        fund_type,
        proposed_strategy_label AS current_strategy_label,
        CASE
            WHEN lower(fund_name) ~ '(precious|gold|silver|mineral)'
                THEN 'Precious Metals'
            WHEN lower(fund_name) ~ '(resource|resources|materials|metals|mining)'
                THEN 'Sector Equity'
            ELSE 'Alternative'
        END AS proposed_strategy_label,
        CASE
            WHEN lower(fund_name) ~ '(precious|gold|silver|mineral)'
                THEN 'real_asset_review_precious_fallback_to_precious_metals'
            WHEN lower(fund_name) ~ '(resource|resources|materials|metals|mining)'
                THEN 'real_asset_review_precious_fallback_to_sector_equity'
            ELSE 'real_asset_review_precious_fallback_to_alternative'
        END AS matched_pattern,
        classified_at
    FROM strategy_reclassification_stage
    WHERE source_table = 'instruments_universe'
      AND classification_source = 'manual_override'
      AND matched_pattern = 'real_asset_review_precious_fallback_sector_equity'
    ORDER BY source_pk, classified_at DESC, stage_id DESC
),
fallback_repairs AS (
    SELECT *
    FROM latest_precious_fallbacks
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
    fallback_repairs.source_pk,
    fallback_repairs.fund_name,
    fallback_repairs.fund_type,
    fallback_repairs.current_strategy_label,
    fallback_repairs.proposed_strategy_label,
    'manual_override',
    fallback_repairs.matched_pattern,
    'medium',
    now(),
    now(),
    'codex',
    run.run_id
FROM fallback_repairs
CROSS JOIN run
WHERE NOT EXISTS (
    SELECT 1
    FROM strategy_reclassification_stage existing
    WHERE existing.source_table = 'instruments_universe'
      AND existing.source_pk = fallback_repairs.source_pk
      AND existing.classification_source = 'manual_override'
      AND existing.proposed_strategy_label = fallback_repairs.proposed_strategy_label
      AND existing.classified_at > fallback_repairs.classified_at
);

UPDATE instruments_universe iu
SET asset_class = public.asset_class_from_strategy(fv.strategy_label)
FROM funds_v fv
WHERE fv.instrument_id = iu.instrument_id
  AND public.asset_class_from_strategy(fv.strategy_label) IS NOT NULL
  AND iu.asset_class IS DISTINCT FROM public.asset_class_from_strategy(fv.strategy_label);
