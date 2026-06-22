# backend/tests/test_fund_style_bias_v_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_style_bias_v.sql"
)


def test_style_bias_view_shape():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE VIEW fund_style_bias_v" in sql
    assert "FROM equity_characteristics_monthly" in sql
    assert "stddev_samp" in sql.lower()
    assert "avg(" in sql.lower()
    assert "OVER (PARTITION BY as_of)" in sql or "OVER (PARTITION BY ec.as_of)" in sql
    # os 6 rótulos de _STYLE_FACTORS
    for label in ("size", "book_to_market", "momentum", "quality", "investment", "profitability"):
        assert f"'{label}'" in sql
