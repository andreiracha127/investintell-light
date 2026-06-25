# backend/tests/test_fund_institutional_reveal_latest_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_institutional_reveal_latest_mv.sql"
)


def test_inst_reveal_latest_mv():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_institutional_reveal_latest_mv" in sql
    assert "DISTINCT ON (series_id)" in sql
    assert "FROM fund_institutional_reveal_artifacts" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_institutional_reveal_latest_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_institutional_reveal_latest_mv;" in sql
