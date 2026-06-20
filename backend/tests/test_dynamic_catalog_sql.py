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
    assert "'direct_series'::text" in sql
    assert "'class_name_exact'::text" in sql
    assert "'universe_name_exact'::text" in sql
    assert "sec_fund_classes" in sql
    assert "instruments_universe" in sql
    assert "benchmark_etf_canonical_map" in sql
    assert "benchmark_proxy_instrument_id" in sql
    assert "proxy_instruments" in sql
    assert "max(coalesce(proxy_instrument_count, 0))" in sql


def test_fund_benchmark_candidates_sql_marks_proxy_conflicts() -> None:
    sql = BENCHMARK_DDL_PATH.read_text(encoding="utf-8")

    assert "count(DISTINCT proxy_etf_ticker)" in sql
    assert "CASE WHEN proxy_count = 1 THEN proxy_etf_ticker END" in sql
    assert "CASE WHEN proxy_count = 1 AND proxy_instrument_count = 1" in sql
    assert "(benchmark_name_count > 1 OR proxy_count > 1)" in sql
    assert "benchmark_proxy_candidates" in sql
