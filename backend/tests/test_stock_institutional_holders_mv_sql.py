from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_stock_institutional_holders_mv.sql"
)


def test_schema_defines_b1_mv_with_unique_index_and_name_resolution():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS stock_institutional_holders_mv" in sql
    # CONCURRENTLY exige índice UNIQUE.
    assert "CREATE UNIQUE INDEX IF NOT EXISTS stock_institutional_holders_mv_pk" in sql
    # Populate inicial não-concorrente.
    assert "REFRESH MATERIALIZED VIEW stock_institutional_holders_mv;" in sql
    # Resolução de nome de gestor em 3 níveis, CIK lpad a 10 dígitos.
    assert "lpad(h.cik, 10, '0')" in sql
    assert "COALESCE(fn.filer_name, mgr.firm_name, 'CIK ' || h.cik)" in sql
    assert "sec_13f_filer_name" in sql
    assert "ORDER BY m.aum_total DESC NULLS LAST" in sql
    # entry_date vem da MV sec_13f_entry.
    assert "sec_13f_entry" in sql
    # entry_price/current_price ficam em eod_prices (price_latest_mv NÃO serve).
    assert "FROM eod_prices p" in sql
    assert "p.date >= " in sql  # primeiro adj_close em/após entry_date
    # shares_outstanding de fundamentals_snapshot.
    assert "fundamentals_snapshot" in sql
    # índice por cusip de sec_13f_holdings (latest report_date global).
    assert "max(report_date) AS period FROM sec_13f_holdings" in sql
