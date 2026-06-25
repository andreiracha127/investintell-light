# backend/tests/test_fund_style_drift_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_style_drift_mv.sql"
)


def test_style_drift_mv_shape_and_index():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_style_drift_mv" in sql
    assert "FROM sec_nport_holdings" in sql
    assert "sec_cusip_ticker_map" in sql          # GICS por CUSIP
    assert "SUM(pct_of_nav)" in sql               # agregação por setor
    assert "GROUP BY" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_style_drift_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_style_drift_mv;" in sql
    # case-map de N-PORT sector (amostra)
    assert "'U.S. Treasury'" in sql
    assert "'Corporate'" in sql
