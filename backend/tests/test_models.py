"""
Offline unit tests for DB model metadata.

No live database required — we inspect the SQLAlchemy metadata objects directly.
"""

from sqlalchemy import ARRAY, BigInteger
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

# Importing Base triggers __init__.py which registers Instrument, EodPrice, NewsItem.
from app.models import Base

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


def test_eod_prices_split_factor_has_server_default() -> None:
    col = _col("eod_prices", "split_factor")
    assert col.server_default is not None


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
# Naming convention
# ---------------------------------------------------------------------------

def test_pk_names_follow_convention() -> None:
    """All PKs must be named pk_<tablename> per naming convention."""
    for table_name in ("instruments", "eod_prices", "news_items"):
        pk = _table(table_name).primary_key
        assert pk.name == f"pk_{table_name}", (
            f"PK for {table_name!r} is {pk.name!r}, expected 'pk_{table_name}'"
        )


def test_index_names_start_with_ix() -> None:
    """All explicitly-named indexes must start with 'ix_'."""
    for table_name in ("eod_prices", "news_items"):
        for idx in _table(table_name).indexes:
            if idx.name:
                assert idx.name.startswith("ix_"), (
                    f"Index {idx.name!r} on {table_name} does not start with 'ix_'"
                )
