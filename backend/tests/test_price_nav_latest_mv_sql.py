from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_price_nav_latest_mv.sql"
)


def test_schema_defines_both_mvs_with_unique_indexes():
    sql = SCHEMA.read_text(encoding="utf-8")
    # Ambos os MVs criados sem dados (populate inicial explícito depois).
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS price_latest_mv" in sql
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS nav_latest_mv" in sql
    # Índices UNIQUE são obrigatórios para REFRESH … CONCURRENTLY.
    assert "CREATE UNIQUE INDEX IF NOT EXISTS price_latest_mv_pk" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS nav_latest_mv_pk" in sql
    # Populate inicial não-concorrente (CONCURRENTLY exige MV já populado).
    assert "REFRESH MATERIALIZED VIEW price_latest_mv;" in sql
    assert "REFRESH MATERIALIZED VIEW nav_latest_mv;" in sql
    # Fonte db-first canônica: os CAGGs diários, não as tabelas cruas.
    assert "FROM cagg_eod_daily" in sql
    assert "FROM cagg_nav_daily" in sql
