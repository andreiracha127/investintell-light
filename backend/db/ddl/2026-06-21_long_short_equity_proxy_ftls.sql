-- Use FTLS as the canonical Long/Short Equity benchmark proxy.
--
-- HFND is a cleaner hedge-fund-replication concept but only has history from
-- 2022. FTLS is an explicit long/short equity ETF and currently has Tiingo EOD
-- and NAV coverage from 2014, making it better for backtests.

INSERT INTO fund_strategy_benchmark_proxy_map (
    strategy_label,
    proxy_etf_ticker,
    proxy_asset_class,
    fit_quality_score,
    source,
    notes
) VALUES (
    'Long/Short Equity',
    'FTLS',
    'equity',
    0.9500,
    'strategy_label_proxy',
    'Long/short equity ETF proxy with materially longer Tiingo/NAV history than HFND.'
)
ON CONFLICT (strategy_label) DO UPDATE SET
    proxy_etf_ticker = EXCLUDED.proxy_etf_ticker,
    proxy_asset_class = EXCLUDED.proxy_asset_class,
    fit_quality_score = EXCLUDED.fit_quality_score,
    source = EXCLUDED.source,
    notes = EXCLUDED.notes,
    updated_at = now();
