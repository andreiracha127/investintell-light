-- Fund benchmark resolution candidates.
--
-- This DDL keeps real declared SEC/N-PORT benchmarks as the preferred source,
-- then falls back to a canonical strategy_label -> proxy ETF map. The fallback
-- is required for index ETFs and funds without a usable designated index: a
-- Small Blend fund, for example, should resolve to IWM; IWM resolves to itself.

CREATE TABLE IF NOT EXISTS sec_nport_fund_var_info (
    accession_number text PRIMARY KEY,
    series_id text NOT NULL,
    series_name text,
    report_date date,
    filing_date date,
    designated_index_name text,
    designated_index_identifier text,
    designated_index_quality text NOT NULL DEFAULT 'unknown',
    source_file text NOT NULL DEFAULT 'FUND_VAR_INFO.tsv',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT sec_nport_fund_var_info_quality_check
        CHECK (
            designated_index_quality IN (
                'declared_index',
                'missing',
                'self_reference',
                'unknown'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_sec_nport_fund_var_info_series_report
    ON sec_nport_fund_var_info (series_id, report_date DESC NULLS LAST, filing_date DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_sec_nport_fund_var_info_identifier
    ON sec_nport_fund_var_info (designated_index_identifier)
    WHERE designated_index_identifier IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sec_nport_fund_var_info_quality
    ON sec_nport_fund_var_info (designated_index_quality, series_id);

CREATE TABLE IF NOT EXISTS fund_strategy_benchmark_proxy_map (
    strategy_label text PRIMARY KEY,
    proxy_etf_ticker text NOT NULL,
    proxy_asset_class text,
    fit_quality_score numeric(5, 4) NOT NULL DEFAULT 0.8500,
    source text NOT NULL DEFAULT 'strategy_label_proxy',
    notes text,
    effective_from date NOT NULL DEFAULT DATE '1900-01-01',
    effective_to date NOT NULL DEFAULT DATE '9999-12-31',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fund_strategy_benchmark_proxy_map_fit_quality_check
        CHECK (fit_quality_score >= 0 AND fit_quality_score <= 1),
    CONSTRAINT fund_strategy_benchmark_proxy_map_effective_check
        CHECK (effective_from <= effective_to)
);

INSERT INTO fund_strategy_benchmark_proxy_map (
    strategy_label,
    proxy_etf_ticker,
    proxy_asset_class,
    fit_quality_score,
    source,
    notes
) VALUES
    ('Alternative', 'QAI', 'alternatives', 0.9500, 'strategy_label_proxy', 'NYLI hedge multi-strategy tracker ETF proxy.'),
    ('Asset-Backed Securities', 'DEED', 'fixed_income', 0.9000, 'strategy_label_proxy', 'Securitized fixed-income ETF proxy.'),
    ('Asian Equity', 'AAXJ', 'equity', 0.9500, 'strategy_label_proxy', 'Asia ex-Japan equity ETF proxy.'),
    ('Balanced', 'AOR', 'multi_asset', 0.9500, 'strategy_label_proxy', '60/40 allocation ETF proxy.'),
    ('Biotechnology Equity', 'IBB', 'equity', 0.9500, 'strategy_label_proxy', 'Biotechnology sector ETF proxy.'),
    ('Cash Equivalent', 'BIL', 'fixed_income', 1.0000, 'strategy_label_proxy', '1-3 month T-bill ETF proxy.'),
    ('Clean Energy Equity', 'ICLN', 'equity', 0.9000, 'strategy_label_proxy', 'Global clean-energy equity ETF proxy.'),
    ('Commodities', 'GCC', 'alternatives', 0.9500, 'strategy_label_proxy', 'Broad commodity strategy ETF proxy.'),
    ('Communication Services Equity', 'XLC', 'equity', 0.9800, 'strategy_label_proxy', 'Communication services sector ETF proxy.'),
    ('Consumer Discretionary Equity', 'XLY', 'equity', 0.9800, 'strategy_label_proxy', 'Consumer discretionary sector ETF proxy.'),
    ('Consumer Staples Equity', 'XLP', 'equity', 0.9800, 'strategy_label_proxy', 'Consumer staples sector ETF proxy.'),
    ('Convertible Securities', 'ICVT', 'fixed_income', 0.9500, 'strategy_label_proxy', 'Convertible bond ETF proxy.'),
    ('Crypto / Digital Assets', 'BITO', 'alternatives', 0.9000, 'strategy_label_proxy', 'Bitcoin-linked ETF proxy for digital-asset strategy funds.'),
    ('Defined Outcome / Option Income', 'BUFR', 'alternatives', 0.9000, 'strategy_label_proxy', 'Laddered buffer ETF proxy for defined-outcome and option-income funds.'),
    ('Emerging Markets Debt', 'EMB', 'fixed_income', 0.9800, 'strategy_label_proxy', 'USD emerging-markets bond ETF proxy.'),
    ('Emerging Markets Equity', 'IEMG', 'equity', 0.9800, 'strategy_label_proxy', 'Core emerging-markets equity ETF proxy.'),
    ('Energy Equity', 'XLE', 'equity', 0.9800, 'strategy_label_proxy', 'Energy sector ETF proxy.'),
    ('ESG/Sustainable Bond', 'VCEB', 'fixed_income', 0.9500, 'strategy_label_proxy', 'ESG corporate bond ETF proxy.'),
    ('ESG/Sustainable Equity', 'ESGV', 'equity', 0.9500, 'strategy_label_proxy', 'ESG US equity ETF proxy.'),
    ('European Equity', 'FEZ', 'equity', 0.9200, 'strategy_label_proxy', 'Eurozone large-cap equity ETF proxy.'),
    ('Financials Equity', 'XLF', 'equity', 0.9800, 'strategy_label_proxy', 'Financials sector ETF proxy.'),
    ('Global Equity', 'VT', 'equity', 0.9800, 'strategy_label_proxy', 'Total world equity ETF proxy.'),
    ('Government Bond', 'GOVT', 'fixed_income', 0.9800, 'strategy_label_proxy', 'Broad US Treasury bond ETF proxy.'),
    ('Government Money Market', 'BIL', 'fixed_income', 1.0000, 'strategy_label_proxy', '1-3 month T-bill ETF proxy.'),
    ('High Yield Bond', 'HYG', 'fixed_income', 0.9800, 'strategy_label_proxy', 'High-yield corporate bond ETF proxy.'),
    ('Health Care Equity', 'XLV', 'equity', 0.9800, 'strategy_label_proxy', 'Health care sector ETF proxy.'),
    ('Index / Passive', 'IVV', 'equity', 0.8500, 'strategy_label_proxy', 'Broad US equity proxy for generic passive funds.'),
    ('Inflation-Linked Bond', 'TIP', 'fixed_income', 0.9800, 'strategy_label_proxy', 'TIPS bond ETF proxy.'),
    ('Intermediate-Term Bond', 'BND', 'fixed_income', 0.9800, 'strategy_label_proxy', 'Total US bond market ETF proxy.'),
    ('Industrials Equity', 'XLI', 'equity', 0.9800, 'strategy_label_proxy', 'Industrials sector ETF proxy.'),
    ('Infrastructure Equity', 'IFRA', 'equity', 0.9000, 'strategy_label_proxy', 'US infrastructure equity ETF proxy.'),
    ('International Equity', 'IEFA', 'equity', 0.9800, 'strategy_label_proxy', 'Developed international equity ETF proxy.'),
    ('Investment Grade Bond', 'LQD', 'fixed_income', 0.9800, 'strategy_label_proxy', 'Investment-grade corporate bond ETF proxy.'),
    ('Large Blend', 'IVV', 'equity', 1.0000, 'strategy_label_proxy', 'S&P 500 ETF proxy.'),
    ('Large Growth', 'QQQ', 'equity', 0.9800, 'strategy_label_proxy', 'Nasdaq-100 ETF proxy.'),
    ('Large Value', 'VOOV', 'equity', 0.9500, 'strategy_label_proxy', 'S&P 500 value ETF proxy.'),
    ('Inverse / Hedge', 'SH', 'alternatives', 0.8500, 'strategy_label_proxy', 'Short S&P 500 ETF proxy for inverse hedge strategies; preserves negative market exposure.'),
    ('Leveraged', 'SSO', 'alternatives', 0.8500, 'strategy_label_proxy', '2x S&P 500 ETF proxy for long leveraged equity exposure; declared benchmarks win when available.'),
    ('Long/Short Equity', 'FTLS', 'equity', 0.9500, 'strategy_label_proxy', 'Long/short equity ETF proxy with materially longer Tiingo/NAV history than HFND.'),
    ('Mid Blend', 'SCHM', 'equity', 0.9500, 'strategy_label_proxy', 'US mid-cap ETF proxy.'),
    ('Mid Growth', 'IWP', 'equity', 0.9800, 'strategy_label_proxy', 'Russell Midcap Growth ETF proxy.'),
    ('Mid Value', 'IWS', 'equity', 0.9800, 'strategy_label_proxy', 'Russell Midcap Value ETF proxy.'),
    ('Materials Equity', 'XLB', 'equity', 0.9800, 'strategy_label_proxy', 'Materials sector ETF proxy.'),
    ('Mortgage-Backed Securities', 'MBB', 'fixed_income', 0.9800, 'strategy_label_proxy', 'MBS ETF proxy.'),
    ('Multi-Asset', 'AOR', 'multi_asset', 0.9500, 'strategy_label_proxy', '60/40 allocation ETF proxy.'),
    ('Municipal Bond', 'MUB', 'fixed_income', 0.9800, 'strategy_label_proxy', 'National municipal bond ETF proxy.'),
    ('Natural Resources Equity', 'GUNR', 'equity', 0.9000, 'strategy_label_proxy', 'Global natural-resources equity ETF proxy.'),
    ('Precious Metals', 'RING', 'alternatives', 0.9000, 'strategy_label_proxy', 'Gold miners ETF proxy.'),
    ('Private Credit', 'BIZD', 'fixed_income', 0.9000, 'strategy_label_proxy', 'BDC income ETF proxy.'),
    ('Preferred Securities', 'PFF', 'fixed_income', 0.9500, 'strategy_label_proxy', 'Preferred and hybrid income securities ETF proxy.'),
    ('Real Estate', 'VNQ', 'alternatives', 0.9800, 'strategy_label_proxy', 'US REIT ETF proxy.'),
    ('Sector Equity', 'IVV', 'equity', 0.7000, 'strategy_label_proxy', 'Neutral broad-equity fallback for heterogeneous sector labels.'),
    ('Sector Rotation Equity', 'EQL', 'equity', 0.8500, 'strategy_label_proxy', 'Equal-sector ETF proxy for sector-rotation or sector-neutral products.'),
    ('Size-Focused Equity', 'SIZE', 'equity', 0.9000, 'strategy_label_proxy', 'US size factor ETF proxy.'),
    ('Small Blend', 'IWM', 'equity', 1.0000, 'strategy_label_proxy', 'Russell 2000 ETF proxy; IWM self-resolves.'),
    ('Small Growth', 'IWO', 'equity', 1.0000, 'strategy_label_proxy', 'Russell 2000 Growth ETF proxy.'),
    ('Small Value', 'IWN', 'equity', 1.0000, 'strategy_label_proxy', 'Russell 2000 Value ETF proxy.'),
    ('Structured Credit', 'PAAA', 'fixed_income', 0.9500, 'strategy_label_proxy', 'AAA CLO ETF proxy.'),
    ('Target Date', 'AOR', 'multi_asset', 0.7000, 'strategy_label_proxy', 'Generic 60/40 allocation proxy until target-date vintages are modeled.'),
    ('Technology', 'XLK', 'equity', 0.9800, 'strategy_label_proxy', 'Technology sector ETF proxy.'),
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

WITH composite_seed AS (
    SELECT
        '60/40 S&P 500 / Bloomberg US Aggregate'::text AS benchmark_name_canonical,
        ARRAY[
            '60/40 S&P 500 / Bloomberg US Aggregate',
            '60%/40% S&P 500 Index/Bloomberg U.S. Aggregate Index',
            '60% S&P 500 Index / 40% Bloomberg U.S. Aggregate Index',
            '60SPX40LBUSTRUU'
        ]::text[] AS benchmark_name_aliases,
        'AOR'::text AS proxy_etf_ticker,
        'S000023587'::text AS proxy_etf_series_id,
        'other'::benchmark_asset_class AS asset_class,
        0.9500::numeric AS fit_quality_score,
        'manual_seed'::text AS source,
        'Composite 60/40 equity/bond benchmark proxy used for N-PORT designated-index mappings.'::text AS notes
),
inserted AS (
    INSERT INTO benchmark_etf_canonical_map (
        id,
        benchmark_name_canonical,
        benchmark_name_aliases,
        proxy_etf_ticker,
        proxy_etf_series_id,
        asset_class,
        fit_quality_score,
        source,
        notes
    )
    SELECT
        (SELECT coalesce(max(id), 0) + 1 FROM benchmark_etf_canonical_map),
        benchmark_name_canonical,
        benchmark_name_aliases,
        proxy_etf_ticker,
        proxy_etf_series_id,
        asset_class,
        fit_quality_score,
        source,
        notes
    FROM composite_seed
    WHERE NOT EXISTS (
        SELECT 1
        FROM benchmark_etf_canonical_map existing
        WHERE existing.benchmark_name_canonical = composite_seed.benchmark_name_canonical
    )
    RETURNING id
)
UPDATE benchmark_etf_canonical_map existing
SET
    benchmark_name_aliases = (
        SELECT array_agg(DISTINCT alias ORDER BY alias)
        FROM unnest(existing.benchmark_name_aliases || composite_seed.benchmark_name_aliases) AS x(alias)
    ),
    proxy_etf_ticker = composite_seed.proxy_etf_ticker,
    proxy_etf_series_id = composite_seed.proxy_etf_series_id,
    asset_class = composite_seed.asset_class,
    fit_quality_score = composite_seed.fit_quality_score,
    source = composite_seed.source,
    notes = composite_seed.notes,
    updated_at = now()
FROM composite_seed
WHERE existing.benchmark_name_canonical = composite_seed.benchmark_name_canonical;

CREATE OR REPLACE VIEW fund_benchmark_candidates_v AS
WITH nport_declared_sources AS (
    SELECT
        series_id,
        benchmark_name,
        'nport_designated_index'::text AS resolution_method,
        0 AS source_rank
    FROM (
        SELECT DISTINCT ON (series_id)
            NULLIF(btrim(series_id), '') AS series_id,
            NULLIF(btrim(designated_index_name), '') AS benchmark_name,
            report_date,
            filing_date,
            accession_number
        FROM sec_nport_fund_var_info
        WHERE NULLIF(btrim(series_id), '') IS NOT NULL
          AND NULLIF(btrim(designated_index_name), '') IS NOT NULL
          AND designated_index_quality = 'declared_index'
        ORDER BY series_id, report_date DESC NULLS LAST, filing_date DESC NULLS LAST, accession_number DESC
    ) latest
),
direct_sources AS (
    SELECT
        NULLIF(btrim(series_id), '') AS series_id,
        NULLIF(btrim(primary_benchmark), '') AS benchmark_name,
        'direct_series'::text AS resolution_method,
        1 AS source_rank
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
        'class_name_exact'::text AS resolution_method,
        2 AS source_rank
    FROM missing_series_sources s
    JOIN class_names c
      ON c.normalized_name = s.normalized_name
     AND s.normalized_name <> ''
    UNION
    SELECT
        u.series_id,
        s.benchmark_name,
        'universe_name_exact'::text AS resolution_method,
        3 AS source_rank
    FROM missing_series_sources s
    JOIN universe_names u
      ON u.normalized_name = s.normalized_name
     AND s.normalized_name <> ''
),
all_sources AS (
    SELECT * FROM nport_declared_sources
    UNION
    SELECT * FROM direct_sources
    UNION
    SELECT * FROM crosswalk_sources
),
source_counts AS (
    SELECT
        series_id,
        count(DISTINCT benchmark_name) AS benchmark_name_count
    FROM all_sources
    WHERE series_id IS NOT NULL
      AND benchmark_name IS NOT NULL
    GROUP BY series_id
),
ranked_sources AS (
    SELECT
        series_id,
        benchmark_name,
        resolution_method,
        source_rank,
        row_number() OVER (
            PARTITION BY series_id
            ORDER BY source_rank, benchmark_name
        ) AS rn
    FROM all_sources
    WHERE series_id IS NOT NULL
      AND benchmark_name IS NOT NULL
),
per_series AS (
    SELECT
        r.series_id,
        r.benchmark_name,
        c.benchmark_name_count,
        r.resolution_method AS benchmark_resolution_method
    FROM ranked_sources r
    JOIN source_counts c
      ON c.series_id = r.series_id
    WHERE r.rn = 1
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
active_strategy_map AS (
    SELECT
        strategy_label,
        upper(proxy_etf_ticker) AS proxy_etf_ticker,
        proxy_asset_class,
        fit_quality_score
    FROM fund_strategy_benchmark_proxy_map
    WHERE current_date BETWEEN effective_from AND effective_to
),
fund_series AS (
    SELECT
        series_id,
        min(strategy_label) AS strategy_label
    FROM funds_v
    WHERE series_id IS NOT NULL
      AND NULLIF(btrim(strategy_label), '') IS NOT NULL
    GROUP BY series_id
),
proxy_instruments AS (
    SELECT
        upper(ticker) AS proxy_etf_ticker,
        min(instrument_id::text)::uuid AS proxy_instrument_id,
        count(DISTINCT instrument_id) AS proxy_instrument_count
    FROM instruments_universe
    WHERE NULLIF(btrim(ticker), '') IS NOT NULL
      AND is_active
    GROUP BY upper(ticker)
),
map_matches AS (
    SELECT
        p.series_id,
        p.benchmark_name,
        p.benchmark_name_count,
        p.benchmark_resolution_method,
        m.benchmark_name_canonical,
        upper(m.proxy_etf_ticker) AS proxy_etf_ticker,
        m.proxy_asset_class,
        m.fit_quality_score,
        pi.proxy_instrument_id,
        pi.proxy_instrument_count
    FROM per_series p
    LEFT JOIN active_map m
      ON p.benchmark_name = m.benchmark_name_canonical
      OR p.benchmark_name = ANY(m.benchmark_name_aliases)
    LEFT JOIN proxy_instruments pi
      ON upper(m.proxy_etf_ticker) = pi.proxy_etf_ticker
),
declared_resolved AS (
    SELECT
        series_id,
        benchmark_name,
        benchmark_resolution_method,
        benchmark_name_count,
        count(DISTINCT proxy_etf_ticker) FILTER (WHERE proxy_etf_ticker IS NOT NULL) AS proxy_count,
        max(coalesce(proxy_instrument_count, 0)) AS proxy_instrument_count,
        array_remove(array_agg(DISTINCT proxy_etf_ticker ORDER BY proxy_etf_ticker), NULL) AS proxy_candidates,
        array_remove(array_agg(DISTINCT benchmark_name_canonical ORDER BY benchmark_name_canonical), NULL) AS canonical_name_matches,
        min(proxy_etf_ticker) AS proxy_etf_ticker,
        min(proxy_instrument_id::text)::uuid AS proxy_instrument_id,
        max(proxy_asset_class) AS proxy_asset_class,
        max(fit_quality_score) AS fit_quality_score
    FROM map_matches
    GROUP BY series_id, benchmark_name, benchmark_resolution_method, benchmark_name_count
),
strategy_resolved AS (
    SELECT
        fs.series_id,
        fs.strategy_label AS benchmark_name,
        fs.strategy_label IN ('Leveraged', 'Inverse / Hedge') AS strategy_overrides_declared,
        sm.proxy_etf_ticker,
        sm.proxy_asset_class,
        sm.fit_quality_score,
        pi.proxy_instrument_id,
        pi.proxy_instrument_count
    FROM fund_series fs
    JOIN active_strategy_map sm
      ON sm.strategy_label = fs.strategy_label
    LEFT JOIN proxy_instruments pi
      ON sm.proxy_etf_ticker = pi.proxy_etf_ticker
),
chosen AS (
    SELECT
        coalesce(d.series_id, s.series_id) AS series_id,
        coalesce(
            CASE WHEN s.strategy_overrides_declared THEN s.benchmark_name END,
            d.benchmark_name,
            s.benchmark_name
        ) AS benchmark_name,
        CASE
            WHEN s.strategy_overrides_declared THEN s.proxy_etf_ticker
            WHEN d.proxy_count = 1 AND d.proxy_instrument_count = 1 THEN d.proxy_etf_ticker
            WHEN s.series_id IS NOT NULL THEN s.proxy_etf_ticker
            ELSE CASE WHEN d.proxy_count = 1 THEN d.proxy_etf_ticker END
        END AS benchmark_proxy_ticker,
        CASE
            WHEN s.strategy_overrides_declared THEN s.fit_quality_score
            WHEN d.proxy_count = 1 AND d.proxy_instrument_count = 1 THEN d.fit_quality_score
            WHEN s.series_id IS NOT NULL THEN s.fit_quality_score
            ELSE CASE WHEN d.proxy_count = 1 THEN d.fit_quality_score END
        END AS benchmark_proxy_fit_quality_score,
        CASE
            WHEN s.strategy_overrides_declared THEN s.proxy_asset_class
            WHEN d.proxy_count = 1 AND d.proxy_instrument_count = 1 THEN d.proxy_asset_class
            WHEN s.series_id IS NOT NULL THEN s.proxy_asset_class
            ELSE CASE WHEN d.proxy_count = 1 THEN d.proxy_asset_class END
        END AS benchmark_proxy_asset_class,
        CASE
            WHEN s.strategy_overrides_declared AND d.series_id IS NOT NULL THEN d.benchmark_resolution_method || '_strategy_override'
            WHEN s.strategy_overrides_declared THEN 'strategy_label_proxy'::text
            WHEN d.proxy_count = 1 AND d.proxy_instrument_count = 1 THEN d.benchmark_resolution_method
            WHEN d.series_id IS NOT NULL AND s.series_id IS NOT NULL THEN d.benchmark_resolution_method || '_strategy_proxy'
            WHEN s.series_id IS NOT NULL THEN 'strategy_label_proxy'::text
            ELSE d.benchmark_resolution_method
        END AS benchmark_resolution_method,
        CASE
            WHEN s.strategy_overrides_declared THEN d.series_id IS NOT NULL
            WHEN d.proxy_count = 1 AND d.proxy_instrument_count = 1 THEN (d.benchmark_name_count > 1 OR d.proxy_count > 1)
            WHEN d.series_id IS NOT NULL AND s.series_id IS NOT NULL THEN true
            WHEN s.series_id IS NOT NULL THEN false
            ELSE (d.benchmark_name_count > 1 OR d.proxy_count > 1)
        END AS benchmark_resolution_conflict,
        CASE
            WHEN s.strategy_overrides_declared AND d.series_id IS NOT NULL THEN
                array_remove(coalesce(d.proxy_candidates, ARRAY[]::text[]) || ARRAY[s.proxy_etf_ticker]::text[], NULL)
            WHEN s.strategy_overrides_declared THEN ARRAY[s.proxy_etf_ticker]::text[]
            WHEN d.proxy_count = 1 AND d.proxy_instrument_count = 1 THEN coalesce(d.proxy_candidates, ARRAY[]::text[])
            WHEN d.series_id IS NOT NULL AND s.series_id IS NOT NULL THEN
                array_remove(coalesce(d.proxy_candidates, ARRAY[]::text[]) || ARRAY[s.proxy_etf_ticker]::text[], NULL)
            WHEN s.series_id IS NOT NULL THEN ARRAY[s.proxy_etf_ticker]::text[]
            ELSE coalesce(d.proxy_candidates, ARRAY[]::text[])
        END AS benchmark_proxy_candidates,
        CASE
            WHEN s.strategy_overrides_declared AND d.series_id IS NOT NULL THEN
                coalesce(d.canonical_name_matches, ARRAY[]::text[])
                || ARRAY['declared_overridden:' || d.benchmark_name, 'strategy_label:' || s.benchmark_name]::text[]
            WHEN s.strategy_overrides_declared THEN ARRAY['strategy_label:' || s.benchmark_name]::text[]
            WHEN d.proxy_count = 1 AND d.proxy_instrument_count = 1 THEN coalesce(d.canonical_name_matches, ARRAY[]::text[])
            WHEN d.series_id IS NOT NULL AND s.series_id IS NOT NULL THEN
                coalesce(d.canonical_name_matches, ARRAY[]::text[])
                || ARRAY['unmapped_declared:' || d.benchmark_name, 'strategy_label:' || s.benchmark_name]::text[]
            WHEN s.series_id IS NOT NULL THEN ARRAY['strategy_label:' || s.benchmark_name]::text[]
            ELSE coalesce(d.canonical_name_matches, ARRAY[]::text[])
        END AS benchmark_canonical_name_matches,
        CASE
            WHEN s.strategy_overrides_declared AND s.proxy_instrument_count = 1 THEN s.proxy_instrument_id
            WHEN d.proxy_count = 1 AND d.proxy_instrument_count = 1 THEN d.proxy_instrument_id
            WHEN s.series_id IS NOT NULL AND s.proxy_instrument_count = 1 THEN s.proxy_instrument_id
            ELSE NULL::uuid
        END AS benchmark_proxy_instrument_id
    FROM declared_resolved d
    FULL JOIN strategy_resolved s
      ON s.series_id = d.series_id
)
SELECT
    series_id,
    benchmark_name,
    benchmark_proxy_ticker,
    benchmark_proxy_fit_quality_score,
    benchmark_proxy_asset_class,
    benchmark_resolution_method,
    benchmark_resolution_conflict,
    coalesce(benchmark_proxy_candidates, ARRAY[]::text[]) AS benchmark_proxy_candidates,
    coalesce(benchmark_canonical_name_matches, ARRAY[]::text[]) AS benchmark_canonical_name_matches,
    benchmark_proxy_instrument_id
FROM chosen
WHERE series_id IS NOT NULL;
