# backend/tests/test_fund_top_holdings_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_top_holdings_mv.sql"
)


def test_top_holdings_mv_shape_and_index():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_top_holdings_mv" in sql
    assert "FROM sec_nport_holdings" in sql
    assert "sec_cusip_ticker_map" in sql                 # GICS por CUSIP
    assert "row_number()" in sql or "rank" in sql        # top-N por rank
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_top_holdings_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_top_holdings_mv;" in sql
