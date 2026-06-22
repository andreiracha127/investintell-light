from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_group_c_functions.sql"
)


def test_defines_all_five_functions_language_sql_stable():
    sql = SCHEMA.read_text(encoding="utf-8")
    for fn in (
        "fn_rolling_metrics",
        "fn_rolling_beta_corr",
        "fn_drawdown",
        "fn_histogram",
        "fn_var_cvar",
    ):
        assert f"CREATE OR REPLACE FUNCTION {fn}" in sql, fn
    # On-demand reads of a real-time CAGG are time-dependent -> STABLE, not IMMUTABLE.
    assert "LANGUAGE sql STABLE" in sql
    assert "IMMUTABLE" not in sql


def test_rolling_metrics_uses_sample_std_and_sqrt_252():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "stddev_samp" in sql
    assert "sqrt(252" in sql
    # Rolling frame: window-1 preceding .. current row.
    assert "ROWS BETWEEN" in sql
    assert "PRECEDING AND CURRENT ROW" in sql


def test_beta_corr_use_sample_covar_and_corr():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "covar_samp" in sql
    assert "var_samp" in sql
    assert "corr(" in sql


def test_drawdown_uses_running_max_minus_one():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "max(" in sql
    assert "UNBOUNDED PRECEDING AND CURRENT ROW" in sql
    assert "- 1.0" in sql


def test_histogram_uses_width_bucket():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "width_bucket" in sql


def test_var_cvar_use_percentile_cont_and_filter():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "percentile_cont" in sql
    assert "WITHIN GROUP (ORDER BY" in sql
    assert "FILTER (WHERE" in sql


def test_functions_read_from_canonical_caggs():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "FROM cagg_eod_daily" in sql
    assert "FROM cagg_nav_daily" in sql
