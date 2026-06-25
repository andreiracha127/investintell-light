# backend/tests/test_fund_factor_exposures_latest_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_factor_exposures_latest_mv.sql"
)


def test_factor_exposures_latest_mv():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_factor_exposures_latest_mv" in sql
    assert "DISTINCT ON (instrument_id, factor)" in sql
    assert "FROM fund_factor_exposures" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_factor_exposures_latest_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_factor_exposures_latest_mv;" in sql
