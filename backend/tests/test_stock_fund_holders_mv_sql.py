from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_stock_fund_holders_mv.sql"
)


def test_schema_defines_b2_mv_with_family_resolution_and_4q_trail():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS stock_fund_holders_mv" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS stock_fund_holders_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW stock_fund_holders_mv;" in sql
    # Fonte = MV nport_holdings_history (não a hypertable crua).
    assert "FROM nport_holdings_history" in sql
    # Família em 3 níveis.
    assert "COALESCE(fam.entity_name, sc.entity_name, 'CIK ' || n.cik)" in sql
    assert "COALESCE(sc.series_name, n.series_id)" in sql
    assert "sec_investment_company_series_class" in sql
    # instrument_id do mapa pré-materializado, não funds_v.
    assert "fund_instrument_map" in sql
    # Trilha de 4 trimestres.
    assert "pct_nav_0" in sql
    assert "pct_nav_1" in sql
    assert "pct_nav_2" in sql
    assert "pct_nav_3" in sql
    # Filtro de recência preservado.
    assert "interval '130 days'" in sql
