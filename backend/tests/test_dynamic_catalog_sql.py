from pathlib import Path

DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-13_dynamic_catalog.sql"
)
BENCHMARK_DDL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "ddl"
    / "2026-06-20_fund_benchmark_candidates.sql"
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
    assert "coalesce(d.benchmark_name, s.benchmark_name) AS benchmark_name" in sql
