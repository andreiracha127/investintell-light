from pathlib import Path

DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-13_dynamic_catalog.sql"
)
FULL_RISK_LATEST_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-25_fund_risk_latest_full_mv.sql"
)
FUNDS_LIST_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-15_funds_list_mv.sql"
)
BENCHMARK_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-20_fund_benchmark_candidates.sql"
)
BENCHMARK_MV_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-25_fund_benchmark_candidates_mv.sql"
)
PROFILE_READ_MODELS_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-25_fund_profile_read_models_mv.sql"
)
ALTERNATIVE_OVERRIDES_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-21_alternative_strategy_overrides.sql"
)
REAL_ASSET_OVERRIDES_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-21_real_asset_strategy_overrides.sql"
)
TECHNOLOGY_OVERRIDES_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-21_technology_strategy_overrides.sql"
)
INTERNATIONAL_OVERRIDES_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-21_international_equity_strategy_overrides.sql"
)
SECTOR_CONVERTIBLE_OVERRIDES_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-21_sector_convertible_strategy_overrides.sql"
)


def test_stage_labels_sql_prefers_manual_overrides() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")
    stage_start = sql.index("-- STAGE_LABELS_SQL")
    stage_end = sql.index("-- merge_risk_duplicates", stage_start)
    stage_sql = sql[stage_start:stage_end]

    override_order = "(classification_source = 'manual_override') DESC"
    latest_order = "classified_at DESC"

    assert override_order in stage_sql
    assert stage_sql.index(override_order) < stage_sql.index(latest_order)
    assert "manual_stage AS" in stage_sql


def test_dynamic_catalog_creates_daily_nav_cagg() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")

    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_nav_daily" in sql
    assert "CALL refresh_continuous_aggregate('cagg_nav_daily'" in sql
    assert "add_continuous_aggregate_policy('cagg_nav_daily'" in sql


def test_dynamic_catalog_creates_daily_eod_cagg() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")

    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_eod_daily" in sql
    assert "FROM eod_prices" in sql
    assert "CALL refresh_continuous_aggregate('cagg_eod_daily'" in sql
    assert "add_continuous_aggregate_policy('cagg_eod_daily'" in sql


def test_fund_risk_latest_mv_projects_active_share_columns() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")

    create_start = sql.index("CREATE MATERIALIZED VIEW fund_risk_latest_mv AS")
    create_end = sql.index(
        "CREATE UNIQUE INDEX IF NOT EXISTS fund_risk_latest_mv_pk", create_start
    )
    body = sql[create_start:create_end]

    for column in (
        "active_share_normalized",
        "overlap_normalized",
        "overlap_nav_raw",
        "fund_cusip_coverage_nav",
        "benchmark_cusip_coverage_nav",
        "n_fund_holdings",
        "n_benchmark_holdings",
        "n_common_holdings",
        "n_fund_only",
        "n_benchmark_only",
        "holdings_jaccard",
        "fund_report_age_days",
        "benchmark_report_age_days",
        "report_date_gap_days",
        "active_share_benchmark_instrument_id",
        "active_share_benchmark_series_id",
        "active_share_fund_report_date",
        "active_share_benchmark_report_date",
    ):
        assert column in body, column


def test_fund_risk_latest_mv_projects_full_worker_snapshot_columns() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")
    create_start = sql.index("CREATE MATERIALIZED VIEW fund_risk_latest_mv AS")
    create_end = sql.index(
        "CREATE UNIQUE INDEX IF NOT EXISTS fund_risk_latest_mv_pk", create_start
    )
    body = sql[create_start:create_end]

    for column in (
        "organization_id",
        "cvar_95_3m",
        "cvar_95_6m",
        "var_95_12m",
        "return_6m",
        "return_10y_ann",
        "sharpe_cf",
        "fed_funds_rate_at_calc",
        "data_quality_flags",
        "score_components",
        "cvar_95_conditional",
        "elite_rank_within_strategy",
        "yield_proxy_12m",
        "duration_adj_drawdown_1y",
        "seven_day_net_yield",
        "nav_per_share_mmf",
        "pct_weekly_liquid",
        "weighted_avg_maturity_days",
        "peer_band_high",
        "nport_flow_momentum_score",
    ):
        assert column in body, column


def test_full_risk_latest_migration_uses_blue_green_swap() -> None:
    sql = FULL_RISK_LATEST_DDL_PATH.read_text(encoding="utf-8")

    assert "CREATE MATERIALIZED VIEW fund_risk_latest_mv_new AS" in sql
    assert "CREATE MATERIALIZED VIEW funds_list_mv_new AS" in sql
    assert "CREATE MATERIALIZED VIEW fund_class_resolution_mv_new AS" in sql
    assert "DROP MATERIALIZED VIEW IF EXISTS fund_class_resolution_mv;" in sql
    assert "DROP MATERIALIZED VIEW IF EXISTS funds_list_mv;" in sql
    assert "DROP MATERIALIZED VIEW IF EXISTS fund_risk_latest_mv;" in sql
    assert "ALTER MATERIALIZED VIEW fund_risk_latest_mv_new RENAME TO fund_risk_latest_mv;" in sql
    assert "ALTER MATERIALIZED VIEW funds_list_mv_new RENAME TO funds_list_mv;" in sql
    assert (
        "ALTER MATERIALIZED VIEW fund_class_resolution_mv_new "
        "RENAME TO fund_class_resolution_mv;"
    ) in sql
    assert "blended_momentum_score" in sql


def test_funds_list_mv_keeps_momentum_score_but_stays_narrow() -> None:
    sql = FUNDS_LIST_DDL_PATH.read_text(encoding="utf-8")

    assert "r.blended_momentum_score" in sql
    assert "r.score_components" not in sql
    assert "r.data_quality_flags" not in sql


def test_funds_v_manual_strategy_overrides_win_source_labels() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")

    strategy_expr = sql[sql.index("END AS fund_type,") : sql.index(") AS strategy_label,")]

    assert "NULLIF(btrim(manual_stage.label), '')" in strategy_expr
    assert "NULLIF(btrim(rf.strategy_label), '')" in strategy_expr
    assert strategy_expr.index("manual_stage.label") < strategy_expr.index("rf.strategy_label")


def test_dynamic_catalog_knows_alternative_sublabels() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")

    assert "WHEN 'Defined Outcome / Option Income' THEN 'alternatives'" in sql
    assert "WHEN 'Crypto / Digital Assets' THEN 'alternatives'" in sql
    assert "WHEN 'Leveraged' THEN 'alternatives'" in sql
    assert "WHEN 'Inverse / Hedge' THEN 'alternatives'" in sql
    assert "THEN 'Cash Equivalent'" in sql
    assert "THEN 'Defined Outcome / Option Income'" in sql
    assert "THEN 'Crypto / Digital Assets'" in sql
    assert "THEN 'Leveraged'" in sql
    assert "THEN 'Inverse / Hedge'" in sql
    assert "natural resources" in sql
    assert "THEN 'Technology'" in sql
    assert "WHEN 'Health Care Equity' THEN 'equity'" in sql
    assert "WHEN 'Financials Equity' THEN 'equity'" in sql
    assert "WHEN 'Preferred Securities' THEN 'fixed_income'" in sql
    assert "THEN 'Biotechnology Equity'" in sql
    assert "THEN 'Sector Rotation Equity'" in sql
    assert "all country asia ex japan" in sql
    assert "global ex u s" in sql
    assert "THEN 'European Equity'" in sql
    assert "THEN 'Asian Equity'" in sql


def test_alternative_override_migration_captures_reviewed_buckets() -> None:
    sql = ALTERNATIVE_OVERRIDES_DDL_PATH.read_text(encoding="utf-8")

    assert "'manual_override'" in sql
    assert "strategy_reclassification_stage" in sql
    assert "alternative_review_cash_like_fixed_income" in sql
    assert "alternative_review_defined_outcome_option_income" in sql
    assert "alternative_review_crypto_digital_assets" in sql
    assert "alternative_review_leveraged" in sql
    assert "alternative_review_inverse_hedge" in sql
    assert "alternative_review_cash_like_revert_broad_rule" in sql
    assert "THEN 'Cash Equivalent'" in sql
    assert "THEN 'Defined Outcome / Option Income'" in sql
    assert "THEN 'Crypto / Digital Assets'" in sql
    assert "THEN 'Leveraged'" in sql
    assert "THEN 'Inverse / Hedge'" in sql
    assert "'Leveraged / Inverse'" in sql
    assert "public.asset_class_from_strategy(fv.strategy_label)" in sql


def test_real_asset_override_migration_recovers_contaminated_labels() -> None:
    sql = REAL_ASSET_OVERRIDES_DDL_PATH.read_text(encoding="utf-8")

    assert "'Balanced'" in sql
    assert "'Commodities'" in sql
    assert "'Precious Metals'" in sql
    assert "'Real Estate'" in sql
    assert "real_asset_review_target_date" in sql
    assert "real_asset_review_sector_equity" in sql
    assert "real_asset_review_real_estate_explicit" in sql
    assert "real_asset_review_alternative_macro_futures" in sql
    assert "real_asset_review_balanced_allocation" in sql
    assert "real_asset_review_real_estate_fallback_large_blend" in sql
    assert "real_asset_review_precious_fallback_alternative" in sql
    assert "real_asset_review_precious_fallback_to_precious_metals" in sql
    assert "THEN 'Target Date'" in sql
    assert "THEN 'Sector Equity'" in sql
    assert "THEN 'Alternative'" in sql
    assert "THEN 'Large Blend'" in sql
    assert "public.asset_class_from_strategy(fv.strategy_label)" in sql


def test_technology_override_migration_splits_tech_from_sector_equity() -> None:
    sql = TECHNOLOGY_OVERRIDES_DDL_PATH.read_text(encoding="utf-8")

    assert "'Large Blend', 'Sector Equity', 'Technology'" in sql
    assert "technology_review_pure_technology" in sql
    assert r"\mtech\M" in sql
    assert "technology_review_biotech_sector_equity" in sql
    assert "technology_review_ex_technology_large_blend" in sql
    assert "technology_review_option_income" in sql
    assert "technology_review_inverse_hedge" in sql
    assert "THEN 'Technology'" in sql
    assert "THEN 'Sector Equity'" in sql
    assert "THEN 'Large Blend'" in sql
    assert "THEN 'Defined Outcome / Option Income'" in sql
    assert "THEN 'Inverse / Hedge'" in sql
    assert "public.asset_class_from_strategy(fv.strategy_label)" in sql


def test_international_override_migration_splits_regional_equity() -> None:
    sql = INTERNATIONAL_OVERRIDES_DDL_PATH.read_text(encoding="utf-8")

    assert "'International Equity'" in sql
    assert "'European Equity'" in sql
    assert "'Asian Equity'" in sql
    assert "'Emerging Markets Equity'" in sql
    assert "'Global Equity'" in sql
    assert "international_review_name_european" in sql
    assert "international_review_name_asian" in sql
    assert "international_review_name_emerging_markets" in sql
    assert "international_review_name_global" in sql
    assert "international_review_benchmark_international" in sql
    assert "all country asia ex japan" in sql
    assert "global ex u.s." in sql
    assert "global ex u s" in sql
    assert "THEN 'European Equity'" in sql
    assert "THEN 'Asian Equity'" in sql
    assert "THEN 'Emerging Markets Equity'" in sql
    assert "THEN 'International Equity'" in sql
    assert "THEN 'Global Equity'" in sql
    assert "public.asset_class_from_strategy(fv.strategy_label)" in sql


def test_sector_convertible_override_migration_splits_broad_buckets() -> None:
    sql = SECTOR_CONVERTIBLE_OVERRIDES_DDL_PATH.read_text(encoding="utf-8")
    benchmark_sql = BENCHMARK_DDL_PATH.read_text(encoding="utf-8")

    assert "'Sector Equity', 'Convertible Securities'" in sql
    assert "sector_convertible_review_sector_split" in sql
    assert "sector_convertible_review_convertible_cleanup" in sql
    assert "sector_convertible_review_holdings_fixed_income" in sql
    assert "THEN 'Health Care Equity'" in sql
    assert "THEN 'Financials Equity'" in sql
    assert "THEN 'Sector Rotation Equity'" in sql
    assert "THEN 'Preferred Securities'" in sql
    assert "THEN 'Convertible Securities'" in sql
    assert "public.asset_class_from_strategy(fv.strategy_label)" in sql
    assert "structured_pct >= 50" in sql
    assert "equity_pct >= 70" in sql
    assert "SELECT DISTINCT ON (source_pk)" in sql

    assert "('Health Care Equity', 'XLV'" in benchmark_sql
    assert "('Financials Equity', 'XLF'" in benchmark_sql
    assert "('Preferred Securities', 'PFF'" in benchmark_sql
    assert "('Sector Rotation Equity', 'EQL'" in benchmark_sql


def test_funds_v_name_prefers_series_name_for_trusts() -> None:
    """funds_v.name must use the N-CEN series-level name (sec_fund_classes.
    series_name) when the catalog name is a trust/umbrella registrant name.

    sec_registered_funds is trust-level and some sec_etfs rows carry the trust
    name, so the COALESCE that previously started at rf.fund_name surfaced
    "WisdomTree Digital Trust" instead of the fund "WisdomTree Siegel Longevity
    Digital Fund". The portfolio look-through sunburst labels its fund (series)
    ring from this name, so a trust name breaks the asset → series → holding
    hierarchy. The legacy catalog sourced the specific fund name from N-CEN.
    """
    sql = DDL_PATH.read_text(encoding="utf-8")

    # A dedicated CTE exposes the series-level name from N-CEN share classes.
    assert "sec_fund_classes" in sql
    assert "series_name" in sql

    # The `name` column expression of funds_v.
    name_expr = sql[sql.index("e.lei,") : sql.index(") AS name,")]
    assert "fc.series_name" in name_expr, name_expr

    # The trust repair is the first COALESCE branch: a CASE that detects a
    # trust/umbrella name (regex) and resolves to the N-CEN series_name.
    case_branch = name_expr[name_expr.index("CASE") : name_expr.index("END")]
    assert "trust" in case_branch.lower(), case_branch
    assert "~*" in case_branch, case_branch
    assert "fc.series_name" in case_branch, case_branch

    # The trust-repair CASE precedes the plain rf.fund_name fallback, otherwise
    # the trust name would still win.
    after_case = name_expr[name_expr.index("END") :]
    assert "NULLIF(btrim(rf.fund_name)" in after_case, after_case


def test_fund_benchmark_candidates_sql_uses_all_resolution_paths() -> None:
    sql = BENCHMARK_DDL_PATH.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE VIEW fund_benchmark_candidates_v" in sql
    assert "CREATE TABLE IF NOT EXISTS sec_nport_fund_var_info" in sql
    assert "'nport_designated_index'::text" in sql
    assert "'direct_series'::text" in sql
    assert "'class_name_exact'::text" in sql
    assert "'universe_name_exact'::text" in sql
    assert "sec_fund_classes" in sql
    assert "instruments_universe" in sql
    assert "benchmark_etf_canonical_map" in sql
    assert "benchmark_proxy_instrument_id" in sql
    assert "proxy_instruments" in sql
    assert "max(coalesce(proxy_instrument_count, 0))" in sql
    assert "fund_strategy_benchmark_proxy_map" in sql
    assert "'strategy_label_proxy'::text" in sql
    assert "'Defined Outcome / Option Income', 'BUFR'" in sql
    assert "'Crypto / Digital Assets', 'BITO'" in sql
    assert "'Leveraged', 'SSO'" in sql
    assert "'Inverse / Hedge', 'SH'" in sql
    assert "'Long/Short Equity', 'FTLS'" in sql
    assert "strategy_overrides_declared" in sql
    assert "declared_overridden:" in sql


def test_fund_benchmark_candidates_sql_marks_proxy_conflicts() -> None:
    sql = BENCHMARK_DDL_PATH.read_text(encoding="utf-8")

    assert "count(DISTINCT proxy_etf_ticker)" in sql
    assert "CASE WHEN d.proxy_count = 1 THEN d.proxy_etf_ticker END" in sql
    assert "WHEN d.proxy_count = 1 AND d.proxy_instrument_count = 1" in sql
    assert "(d.benchmark_name_count > 1 OR d.proxy_count > 1)" in sql
    assert "d.benchmark_resolution_method || '_strategy_proxy'" in sql
    assert "unmapped_declared:" in sql
    assert "benchmark_proxy_candidates" in sql


def test_fund_benchmark_candidates_sql_preserves_declared_composite_proxy() -> None:
    sql = BENCHMARK_DDL_PATH.read_text(encoding="utf-8")

    assert "60%/40% S&P 500 Index/Bloomberg U.S. Aggregate Index" in sql
    assert "60SPX40LBUSTRUU" in sql
    assert "'AOR'::text AS proxy_etf_ticker" in sql
    assert "CASE WHEN s.strategy_overrides_declared THEN s.benchmark_name END" in sql
    assert "d.benchmark_name" in sql


def test_fund_benchmark_candidates_mv_materializes_request_path_snapshot() -> None:
    sql = BENCHMARK_MV_DDL_PATH.read_text(encoding="utf-8")

    assert "CREATE MATERIALIZED VIEW fund_benchmark_candidates_mv AS" in sql
    assert "FROM fund_benchmark_candidates_v" in sql
    assert "fund_benchmark_candidates_mv_pk" in sql
    assert "ON fund_benchmark_candidates_mv (series_id)" in sql
    assert "REFRESH MATERIALIZED VIEW fund_benchmark_candidates_mv" in sql


def test_fund_profile_read_models_materialize_request_path_sources() -> None:
    sql = PROFILE_READ_MODELS_DDL_PATH.read_text(encoding="utf-8")

    assert "CREATE MATERIALIZED VIEW funds_profile_mv AS" in sql
    assert "FROM funds_v" in sql
    assert "CREATE UNIQUE INDEX funds_profile_mv_pk" in sql
    assert "ON funds_profile_mv (instrument_id)" in sql
    assert "CREATE MATERIALIZED VIEW fund_classes_latest_mv AS" in sql
    assert "FROM fund_classes_v" in sql
    assert "CREATE UNIQUE INDEX fund_classes_latest_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW funds_profile_mv" in sql
    assert "REFRESH MATERIALIZED VIEW fund_classes_latest_mv" in sql
