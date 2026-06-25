from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_holding_reverse_lookup_mv.sql"
)


def test_schema_defines_b3_mv_with_2tier_name_and_unique_index():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS holding_reverse_lookup_mv" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS holding_reverse_lookup_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW holding_reverse_lookup_mv;" in sql
    # Lado institucional: sec_13f_holdings + sec_managers (LATERAL highest-AUM).
    assert "FROM sec_13f_holdings h" in sql
    assert "ORDER BY m.aum_total DESC NULLS LAST" in sql
    # COALESCE de 2 níveis (sem sec_13f_filer_name, sem lpad — paridade com o SQL atual).
    assert "COALESCE(mgr.firm_name, 'CIK ' || h.cik)" in sql
    assert "lpad" not in sql
    assert "sec_13f_filer_name" not in sql
    # latest report_date por cusip.
    assert "max(report_date) AS period" in sql
