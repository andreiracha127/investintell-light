-- Split broad Sector Equity and over-assigned Convertible Securities buckets.
--
-- Sector Equity is too heterogeneous to be a benchmarkable strategic label, so
-- this migration promotes identifiable sector funds into sector-specific labels
-- with ETF proxies. Convertible Securities is kept only for funds whose name or
-- real declared benchmark says convertible; other rows are routed by explicit
-- name/benchmark signals, with latest N-PORT asset mix as the final fallback.

INSERT INTO fund_strategy_benchmark_proxy_map (
    strategy_label,
    proxy_etf_ticker,
    proxy_asset_class,
    fit_quality_score,
    source,
    notes
) VALUES
    ('Biotechnology Equity', 'IBB', 'equity', 0.9500, 'strategy_label_proxy', 'Biotechnology sector ETF proxy.'),
    ('Clean Energy Equity', 'ICLN', 'equity', 0.9000, 'strategy_label_proxy', 'Global clean-energy equity ETF proxy.'),
    ('Communication Services Equity', 'XLC', 'equity', 0.9800, 'strategy_label_proxy', 'Communication services sector ETF proxy.'),
    ('Consumer Discretionary Equity', 'XLY', 'equity', 0.9800, 'strategy_label_proxy', 'Consumer discretionary sector ETF proxy.'),
    ('Consumer Staples Equity', 'XLP', 'equity', 0.9800, 'strategy_label_proxy', 'Consumer staples sector ETF proxy.'),
    ('Energy Equity', 'XLE', 'equity', 0.9800, 'strategy_label_proxy', 'Energy sector ETF proxy.'),
    ('Financials Equity', 'XLF', 'equity', 0.9800, 'strategy_label_proxy', 'Financials sector ETF proxy.'),
    ('Health Care Equity', 'XLV', 'equity', 0.9800, 'strategy_label_proxy', 'Health care sector ETF proxy.'),
    ('Industrials Equity', 'XLI', 'equity', 0.9800, 'strategy_label_proxy', 'Industrials sector ETF proxy.'),
    ('Infrastructure Equity', 'IFRA', 'equity', 0.9000, 'strategy_label_proxy', 'US infrastructure equity ETF proxy.'),
    ('Materials Equity', 'XLB', 'equity', 0.9800, 'strategy_label_proxy', 'Materials sector ETF proxy.'),
    ('Natural Resources Equity', 'GUNR', 'equity', 0.9000, 'strategy_label_proxy', 'Global natural-resources equity ETF proxy.'),
    ('Preferred Securities', 'PFF', 'fixed_income', 0.9500, 'strategy_label_proxy', 'Preferred and hybrid income securities ETF proxy.'),
    ('Sector Rotation Equity', 'EQL', 'equity', 0.8500, 'strategy_label_proxy', 'Equal-sector ETF proxy for sector-rotation or sector-neutral products.'),
    ('Utilities Equity', 'XLU', 'equity', 0.9800, 'strategy_label_proxy', 'Utilities sector ETF proxy.')
ON CONFLICT (strategy_label) DO UPDATE SET
    proxy_etf_ticker = EXCLUDED.proxy_etf_ticker,
    proxy_asset_class = EXCLUDED.proxy_asset_class,
    fit_quality_score = EXCLUDED.fit_quality_score,
    source = EXCLUDED.source,
    notes = EXCLUDED.notes,
    effective_from = EXCLUDED.effective_from,
    effective_to = EXCLUDED.effective_to,
    updated_at = now();

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
    WHERE f.strategy_label IN ('Sector Equity', 'Convertible Securities')
),
latest_holding AS (
    SELECT h.series_id, max(h.report_date) AS report_date
    FROM sec_nport_holdings h
    JOIN base_universe b ON b.series_id = h.series_id
    GROUP BY h.series_id
),
holding_mix AS (
    SELECT
        h.series_id,
        sum(coalesce(h.pct_of_nav, 0)) FILTER (
            WHERE h.asset_class IN ('EC', 'EP', 'EF', 'EU')
        ) AS equity_pct,
        sum(coalesce(h.pct_of_nav, 0)) FILTER (
            WHERE h.asset_class IN ('DBT', 'DB', 'D', 'LON')
        ) AS debt_pct,
        sum(coalesce(h.pct_of_nav, 0)) FILTER (
            WHERE h.asset_class IN ('ABS-MBS', 'ABS-CBDO', 'ABS-O', 'SN')
        ) AS structured_pct,
        sum(coalesce(h.pct_of_nav, 0)) FILTER (
            WHERE h.asset_class IN ('RF', 'STIV')
        ) AS cash_pct
    FROM sec_nport_holdings h
    JOIN latest_holding l
      ON l.series_id = h.series_id
     AND l.report_date = h.report_date
    GROUP BY h.series_id
),
base AS (
    SELECT
        b.*,
        coalesce(m.equity_pct, 0) AS equity_pct,
        coalesce(m.debt_pct, 0) AS debt_pct,
        coalesce(m.structured_pct, 0) AS structured_pct,
        coalesce(m.cash_pct, 0) AS cash_pct
    FROM base_universe b
    LEFT JOIN holding_mix m ON m.series_id = b.series_id
),
classified AS (
    SELECT
        *,
        CASE
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(biotech|biotechnology|genome|genomics)'
                THEN 'Biotechnology Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(health|healthcare|health care|pharma|pharmaceutical|medical technology|medical devices|medical|life sciences)'
                THEN 'Health Care Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(clean energy|solar|renewable energy|green energy|energy transition)'
                THEN 'Clean Energy Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(semiconductor|software|cloud|internet|cyber|robotics|automation|artificial intelligence|\mai\M|technology|tech|nasdaq|exponential technologies|innovation leaders)'
                THEN 'Technology'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(communication services|communications|media|telecom)'
                THEN 'Communication Services Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(consumer discretionary|consumer cyclic|consumer services|retail|luxury goods|consumer focused)'
                THEN 'Consumer Discretionary Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(consumer staples|consumer goods|food|beverage|household)'
                THEN 'Consumer Staples Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(financial|financials|finance|bank|banks|insurance|broker|capital markets)'
                THEN 'Financials Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(aerospace|defense|industrial|industrials|transportation|producer durables)'
                THEN 'Industrials Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(infrastructure|smart grid|water)'
                THEN 'Infrastructure Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(natural resources|global resources|capital cycles|resource|upstream natural)'
                THEN 'Natural Resources Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(mlp|midstream|pipeline|energy infrastructure|energy|oil|gas)'
                THEN 'Energy Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(uranium|nuclear|copper|lithium|battery|materials|mining|metals)'
                THEN 'Materials Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(utilities|utility)'
                THEN 'Utilities Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(real estate|reit|realty)'
                THEN 'Real Estate'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(emerging markets|new asia|india|latin america|africa|middle east|emerging europe)'
                THEN 'Emerging Markets Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(european stock|europe fund|europe equity)'
                THEN 'European Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(international|overseas|eafe)'
                THEN 'International Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(global equity|worldwide|global fund)'
                THEN 'Global Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(sector rotation|equal sector|sector neutral|subsector|sector dividend|sector plus|sector weight)'
                THEN 'Sector Rotation Equity'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(large cap value|large.cap value|dividend|high dividend|value fund|durable high dividend)'
                THEN 'Large Value'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(large cap growth|large.cap growth|blue chip growth|growth equity|growth fund|innovative growth)'
                THEN 'Large Growth'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(small cap growth|small.cap growth)'
                THEN 'Small Growth'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(small cap|small.cap|smallcap|extended equity market|extended market)'
                THEN 'Small Blend'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(mid cap growth|mid.cap growth)'
                THEN 'Mid Growth'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(mid cap value|mid.cap value)'
                THEN 'Mid Value'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(mid cap|mid.cap|midcap|smid)'
                THEN 'Mid Blend'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(s&p 500|500 index|russell 1000|equity index|stock index|total equity market|total stock|wilshire 5000|broad market|all.cap|all cap|contrarian|core growth|large cap|focused fund|wide moat)'
                THEN 'Large Blend'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(multi.?sector income|floating income|fixed income|bond|credit)'
                THEN 'Intermediate-Term Bond'

            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(convertible|convertibles|all convertibles)'
                THEN 'Convertible Securities'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(market neutral|alternative strategy)'
                THEN 'Alternative'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(preferred|capital securities|contingent capital|junior subordinated)'
                THEN 'Preferred Securities'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(ultra.short|ultra short|short duration|short.term|short term|low duration|limited duration)'
                THEN 'Cash Equivalent'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(high yield|high-yield|high income|bank loan|floating rate|senior loan)'
                THEN 'High Yield Bond'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(municipal|tax-aware|tax aware|tax-exempt|tax exempt|muni)'
                THEN 'Municipal Bond'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(local markets|emerging markets total return bond|emerging market debt|emerging markets debt)'
                THEN 'Emerging Markets Debt'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(securitized|mortgage|mbs|asset.backed|asset backed)'
                THEN 'Mortgage-Backed Securities'
            WHEN current_strategy_label = 'Convertible Securities'
             AND structured_pct >= 50
                THEN 'Structured Credit'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(investment grade|corp inv grade|corporate credit|corporate bond|credit income|opportunistic credit|credit opportunities|core plus|core fixed income|fixed income|barc capital us corp)'
                THEN 'Investment Grade Bond'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(total return bond|strategic income|multisector income|income opportunities|pimco income|pimco total return|bond fund|aggregate bond|bloomberg u.s. aggregate|bloomberg us aggregate|global total return|income fund|total return fund)'
                THEN 'Intermediate-Term Bond'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(allocation|multi.?asset|conservative allocation|muni and stock|growth and income|fund of funds)'
                THEN 'Balanced'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(ethical|esg)'
                THEN 'ESG/Sustainable Equity'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(technology|tech|semiconductor|software|internet|cloud|cyber)'
                THEN 'Technology'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(health sciences|health care|healthcare|biotech|medical)'
                THEN 'Health Care Equity'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(utilities|utility)'
                THEN 'Utilities Equity'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(energy opportunities|energy transition|natural resources)'
                THEN 'Energy Equity'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(latin america|india|emerging economies|emerging markets)'
                THEN 'Emerging Markets Equity'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(international fund|international opportunities|international equity|international dividend|international index|overseas|global ex|msci eafe|ac world index ex usa|acwi ex)'
                THEN 'International Equity'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(smallcap world|global all.cap|global equity|global rising income|global luxury|global mini mites|world equity income)'
                THEN 'Global Equity'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(mid cap growth|mid.cap growth)'
                THEN 'Mid Growth'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(mid cap value|mid.cap value|mid value)'
                THEN 'Mid Value'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(mid cap|mid.cap|midcap)'
                THEN 'Mid Blend'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(small cap growth|small.cap growth)'
                THEN 'Small Growth'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(small cap|small.cap|smallcap|small-cap)'
                THEN 'Small Blend'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(large cap growth|large.cap growth|blue chip growth|growth fund|dynamic opportunities|systematic growth|dividend growth)'
                THEN 'Large Growth'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(large cap index|russell.*large cap index|s&p 500|equity 500|stock index|exchange portfolio|relative value large cap)'
                THEN 'Large Blend'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(dividend income|dividend value|equity income|value fund|large cap value|high dividend|quality dividend|dividend focus|relative value)'
                THEN 'Large Value'

            WHEN structured_pct >= 50
                THEN 'Structured Credit'
            WHEN debt_pct + structured_pct >= 70
                THEN 'Intermediate-Term Bond'
            WHEN equity_pct >= 70
                THEN 'Large Blend'
            WHEN equity_pct >= 50 AND debt_pct + structured_pct >= 20
                THEN 'Balanced'
            ELSE current_strategy_label
        END AS proposed_strategy_label,
        CASE
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(biotech|biotechnology|genome|genomics)'
                THEN 'sector_convertible_review_sector_biotechnology'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(health|healthcare|health care|pharma|pharmaceutical|medical technology|medical devices|medical|life sciences)'
                THEN 'sector_convertible_review_sector_health_care'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(clean energy|solar|renewable energy|green energy|energy transition)'
                THEN 'sector_convertible_review_sector_clean_energy'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(semiconductor|software|cloud|internet|cyber|robotics|automation|artificial intelligence|\mai\M|technology|tech|nasdaq|exponential technologies|innovation leaders)'
                THEN 'sector_convertible_review_sector_technology'
            WHEN current_strategy_label = 'Sector Equity'
             AND text_blob ~ '(sector rotation|equal sector|sector neutral|subsector|sector dividend|sector plus|sector weight)'
                THEN 'sector_convertible_review_sector_rotation'
            WHEN current_strategy_label = 'Sector Equity'
                THEN 'sector_convertible_review_sector_split'
            WHEN current_strategy_label = 'Convertible Securities'
             AND text_blob ~ '(convertible|convertibles|all convertibles)'
                THEN 'sector_convertible_review_keep_convertible'
            WHEN current_strategy_label = 'Convertible Securities'
                THEN 'sector_convertible_review_convertible_cleanup'
            WHEN structured_pct >= 50
                THEN 'sector_convertible_review_holdings_structured_credit'
            WHEN debt_pct + structured_pct >= 70
                THEN 'sector_convertible_review_holdings_fixed_income'
            WHEN equity_pct >= 70
                THEN 'sector_convertible_review_holdings_equity'
            WHEN equity_pct >= 50 AND debt_pct + structured_pct >= 20
                THEN 'sector_convertible_review_holdings_balanced'
            ELSE 'sector_convertible_review_keep'
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
        WHEN overrides.matched_pattern LIKE 'sector_convertible_review_holdings_%'
            THEN 'medium'
        WHEN overrides.matched_pattern = 'sector_convertible_review_convertible_cleanup'
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
    FROM (
        SELECT DISTINCT ON (source_pk)
               source_pk,
               proposed_strategy_label
        FROM strategy_reclassification_stage
        WHERE source_table = 'instruments_universe'
          AND classification_source = 'manual_override'
        ORDER BY source_pk, classified_at DESC, stage_id DESC
    ) existing
    WHERE existing.source_pk = overrides.instrument_id::text
      AND existing.proposed_strategy_label = overrides.proposed_strategy_label
);

UPDATE instruments_universe iu
SET asset_class = public.asset_class_from_strategy(fv.strategy_label)
FROM funds_v fv
WHERE fv.instrument_id = iu.instrument_id
  AND public.asset_class_from_strategy(fv.strategy_label) IS NOT NULL
  AND iu.asset_class IS DISTINCT FROM public.asset_class_from_strategy(fv.strategy_label);
