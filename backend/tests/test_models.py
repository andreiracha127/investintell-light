"""
Offline unit tests for DB model metadata.

No live database required — we inspect the SQLAlchemy metadata objects directly.
"""

from sqlalchemy import ARRAY, BigInteger, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

# Importing Base triggers __init__.py which registers all ORM models.
from app.models import Base, Portfolio, Position

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table(name: str):
    return Base.metadata.tables[name]


def _col(table_name: str, col_name: str):
    return _table(table_name).c[col_name]


# ---------------------------------------------------------------------------
# Table registration
# ---------------------------------------------------------------------------

def test_all_tables_registered() -> None:
    assert "instruments" in Base.metadata.tables
    assert "eod_prices" in Base.metadata.tables
    assert "news_items" in Base.metadata.tables
    assert "portfolios" in Base.metadata.tables
    assert "positions" in Base.metadata.tables


# ---------------------------------------------------------------------------
# instruments
# ---------------------------------------------------------------------------

def test_instruments_pk_is_ticker() -> None:
    pk_cols = list(_table("instruments").primary_key.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "ticker"


def test_instruments_audit_columns_exist() -> None:
    cols = {c.name for c in _table("instruments").c}
    assert "created_at" in cols
    assert "updated_at" in cols


# ---------------------------------------------------------------------------
# eod_prices
# ---------------------------------------------------------------------------

def test_eod_prices_pk_is_ticker_and_date() -> None:
    pk_cols = {c.name for c in _table("eod_prices").primary_key.columns}
    assert pk_cols == {"ticker", "date"}


def test_eod_prices_volume_is_biginteger() -> None:
    col = _col("eod_prices", "volume")
    assert isinstance(col.type, BigInteger)


def test_eod_prices_adj_volume_is_biginteger() -> None:
    col = _col("eod_prices", "adj_volume")
    assert isinstance(col.type, BigInteger)


def test_eod_prices_date_index_exists() -> None:
    """The cross-sectional date index must be present."""
    index_names = {idx.name for idx in _table("eod_prices").indexes}
    assert "ix_eod_prices_date" in index_names


def test_eod_prices_div_cash_has_server_default() -> None:
    col = _col("eod_prices", "div_cash")
    assert col.server_default is not None
    assert col.server_default.arg == "0", (  # type: ignore[union-attr]
        f"div_cash server_default expected '0', got {col.server_default.arg!r}"
    )


def test_eod_prices_split_factor_has_server_default() -> None:
    col = _col("eod_prices", "split_factor")
    assert col.server_default is not None
    assert col.server_default.arg == "1", (  # type: ignore[union-attr]
        f"split_factor server_default expected '1', got {col.server_default.arg!r}"
    )


def test_eod_prices_fk_to_instruments() -> None:
    fks = list(_table("eod_prices").foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "instruments"
    assert fk.column.name == "ticker"


# ---------------------------------------------------------------------------
# news_items
# ---------------------------------------------------------------------------

def test_news_items_pk_is_id() -> None:
    pk_cols = list(_table("news_items").primary_key.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "id"


def test_news_items_id_is_biginteger() -> None:
    col = _col("news_items", "id")
    assert isinstance(col.type, BigInteger)


def test_news_items_tickers_is_array() -> None:
    col = _col("news_items", "tickers")
    # SQLAlchemy may represent it as ARRAY or the dialect-specific PG_ARRAY.
    assert isinstance(col.type, (ARRAY, PG_ARRAY))


def test_news_items_tickers_gin_index_exists() -> None:
    index_names = {idx.name for idx in _table("news_items").indexes}
    assert "ix_news_items_tickers" in index_names


def test_news_items_published_at_index_exists() -> None:
    index_names = {idx.name for idx in _table("news_items").indexes}
    assert "ix_news_items_published_at" in index_names


# ---------------------------------------------------------------------------
# portfolios / positions (F4)
# ---------------------------------------------------------------------------

def test_portfolios_name_is_unique() -> None:
    name_constraints = {
        c.name
        for c in _table("portfolios").constraints
        if isinstance(c, UniqueConstraint)
    }
    assert "uq_portfolios_name" in name_constraints


def test_portfolios_cash_has_server_default() -> None:
    col = _col("portfolios", "cash")
    assert col.server_default is not None
    assert col.server_default.arg == "0"  # type: ignore[union-attr]


def test_positions_fk_cascades_on_portfolio_delete() -> None:
    fks = list(_table("positions").foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "portfolios"
    assert fk.column.name == "id"
    assert fk.ondelete == "CASCADE"


def test_positions_unique_per_portfolio_and_ticker() -> None:
    unique = next(
        c
        for c in _table("positions").constraints
        if isinstance(c, UniqueConstraint)
    )
    assert unique.name == "uq_positions_portfolio_id_ticker"
    assert [col.name for col in unique.columns] == ["portfolio_id", "ticker"]


def test_positions_portfolio_id_index_exists() -> None:
    index_names = {idx.name for idx in _table("positions").indexes}
    assert "ix_positions_portfolio_id" in index_names


def test_positions_acq_price_is_nullable_quantity_is_not() -> None:
    assert _col("positions", "acq_price").nullable is True
    assert _col("positions", "quantity").nullable is False


def test_portfolio_positions_relationship_conventions() -> None:
    """lazy='raise' (project rule), delete-orphan cascade, passive DB deletes."""
    rel = Portfolio.__mapper__.relationships["positions"]
    assert rel.lazy == "raise"
    assert rel.passive_deletes is True
    assert "delete-orphan" in rel.cascade
    back = Position.__mapper__.relationships["portfolio"]
    assert back.lazy == "raise"


# ---------------------------------------------------------------------------
# Naming convention
# ---------------------------------------------------------------------------

def test_pk_names_follow_convention() -> None:
    """All PKs must be named pk_<tablename> per naming convention."""
    for table_name in (
        "instruments",
        "eod_prices",
        "news_items",
        "portfolios",
        "positions",
        "universe_constituents",
        "fundamentals_snapshot",
    ):
        pk = _table(table_name).primary_key
        assert pk.name == f"pk_{table_name}", (
            f"PK for {table_name!r} is {pk.name!r}, expected 'pk_{table_name}'"
        )


def test_index_names_start_with_ix() -> None:
    """All explicitly-named indexes must start with 'ix_'."""
    for table_name in ("eod_prices", "news_items", "positions", "universe_constituents"):
        for idx in _table(table_name).indexes:
            if idx.name:
                assert idx.name.startswith("ix_"), (
                    f"Index {idx.name!r} on {table_name} does not start with 'ix_'"
                )


# ---------------------------------------------------------------------------
# universe_constituents / fundamentals_snapshot (F6)
# ---------------------------------------------------------------------------

def test_universe_tables_registered() -> None:
    assert "universe_constituents" in Base.metadata.tables
    assert "fundamentals_snapshot" in Base.metadata.tables


def test_universe_constituents_pk_is_ticker() -> None:
    pk_cols = list(_table("universe_constituents").primary_key.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "ticker"


def test_universe_constituents_cik_is_indexed_biginteger_not_null() -> None:
    col = _col("universe_constituents", "cik")
    assert isinstance(col.type, BigInteger)
    assert col.nullable is False
    indexed_cols = {
        c.name
        for idx in _table("universe_constituents").indexes
        for c in idx.columns
    }
    assert "cik" in indexed_cols


def test_universe_constituents_status_default_active() -> None:
    col = _col("universe_constituents", "status")
    assert col.nullable is False
    assert col.server_default is not None
    assert col.server_default.arg == "active"  # type: ignore[union-attr]


def test_universe_constituents_source_and_synced_at_not_null() -> None:
    assert _col("universe_constituents", "source").nullable is False
    synced = _col("universe_constituents", "synced_at")
    assert synced.nullable is False
    assert synced.type.timezone is True  # type: ignore[attr-defined]


def test_fundamentals_snapshot_pk_and_fk_cascade() -> None:
    pk_cols = list(_table("fundamentals_snapshot").primary_key.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "ticker"
    fks = list(_table("fundamentals_snapshot").foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "universe_constituents"
    assert fk.column.name == "ticker"
    assert fk.ondelete == "CASCADE"


def test_fundamentals_snapshot_nullability() -> None:
    assert _col("fundamentals_snapshot", "period_end").nullable is False
    assert _col("fundamentals_snapshot", "synced_at").nullable is False
    for nullable_col in (
        "cik",
        "book_equity",
        "total_assets",
        "net_income_ttm",
        "revenue",
        "gross_profit",
        "shares_outstanding",
        "quality_roa",
        "investment_growth",
        "profitability_gross",
        "source_filing_date",
    ):
        assert _col("fundamentals_snapshot", nullable_col).nullable is True, nullable_col


def test_fundamentals_snapshot_cik_is_biginteger() -> None:
    assert isinstance(_col("fundamentals_snapshot", "cik").type, BigInteger)
