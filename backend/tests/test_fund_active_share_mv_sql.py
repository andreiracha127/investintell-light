# backend/tests/test_fund_active_share_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_active_share_mv.sql"
)


def test_active_share_mv_shape_and_index():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_active_share_mv" in sql
    assert "fund_benchmark_candidates_v" in sql           # benchmark primário
    assert "benchmark_proxy_instrument_id" in sql
    assert "FROM sec_nport_holdings" in sql
    assert "0.5" in sql                                    # 0.5·Σ|Δw|
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_active_share_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_active_share_mv;" in sql
