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


def test_universe_constituents_status_is_indexed() -> None:
    """Backfill and metrics job both select WHERE status='active' (0004)."""
    index_names = {idx.name for idx in _table("universe_constituents").indexes}
    assert "ix_universe_constituents_status" in index_names


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
    # cik is NOT NULL since migration 0004 — the sync fetches the snapshot BY cik.
    assert _col("fundamentals_snapshot", "cik").nullable is False
    for nullable_col in (
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


# ---------------------------------------------------------------------------
# screener_metrics (F6.3)
# ---------------------------------------------------------------------------

def test_screener_metrics_registered() -> None:
    assert "screener_metrics" in Base.metadata.tables


def test_screener_metrics_pk_is_ticker() -> None:
    pk = _table("screener_metrics").primary_key
    assert pk.name == "pk_screener_metrics"
    pk_cols = list(pk.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "ticker"


def test_screener_metrics_fk_cascades_on_constituent_delete() -> None:
    fks = list(_table("screener_metrics").foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "universe_constituents"
    assert fk.column.name == "ticker"
    assert fk.ondelete == "CASCADE"


def test_screener_metrics_audit_columns_not_null() -> None:
    computed_at = _col("screener_metrics", "computed_at")
    assert computed_at.nullable is False
    assert computed_at.type.timezone is True  # type: ignore[attr-defined]
    assert _col("screener_metrics", "as_of").nullable is False


def test_screener_metrics_every_metric_column_is_nullable() -> None:
    """NULL = 'metric unavailable' is the cross-sectional contract."""
    from app.sync.metrics import METRIC_COLUMNS

    table = _table("screener_metrics")
    for col_name in METRIC_COLUMNS:
        assert table.c[col_name].nullable is True, col_name


def test_screener_metrics_model_matches_metric_columns() -> None:
    """The model's columns are exactly PK + audit + METRIC_COLUMNS — keeps the
    upsert SET clause, the model and the migration in lockstep."""
    from app.sync.metrics import METRIC_COLUMNS

    actual = {c.name for c in _table("screener_metrics").c}
    expected = {"ticker", "computed_at", "as_of", *METRIC_COLUMNS}
    assert actual == expected


# ---------------------------------------------------------------------------
# screens / screen_filters (F6.4)
# ---------------------------------------------------------------------------

def test_screens_tables_registered() -> None:
    assert "screens" in Base.metadata.tables
    assert "screen_filters" in Base.metadata.tables


def test_screens_name_unique_and_audit_columns() -> None:
    name = _col("screens", "name")
    assert name.nullable is False
    assert name.unique is True
    for col_name in ("created_at", "updated_at"):
        col = _col("screens", col_name)
        assert col.nullable is False
        assert col.type.timezone is True  # type: ignore[attr-defined]


def test_screen_filters_fk_cascades_on_screen_delete() -> None:
    fks = list(_table("screen_filters").foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "screens"
    assert fk.ondelete == "CASCADE"


def test_screen_filters_unique_per_screen_and_metric() -> None:
    uniques = [
        c for c in _table("screen_filters").constraints if isinstance(c, UniqueConstraint)
    ]
    assert any(
        {col.name for col in c.columns} == {"screen_id", "metric_code"} for c in uniques
    )


def test_screen_filters_bounds_nullable_position_not_null() -> None:
    assert _col("screen_filters", "min_value").nullable is True
    assert _col("screen_filters", "max_value").nullable is True
    position = _col("screen_filters", "position")
    assert position.nullable is False
    assert position.server_default is not None


# ---------------------------------------------------------------------------
# positions / portfolios execution columns (migration 0007)
# Ported from the retired test_funds_sync.py (Task 4.2) — these assert live
# model/migration contracts unrelated to the deleted fund sync.
# ---------------------------------------------------------------------------

def test_positions_execution_columns() -> None:
    """Migration 0007: positions.basis/commission/trade_date + checks."""
    from sqlalchemy import CheckConstraint

    table = _table("positions")
    basis = table.c["basis"]
    assert basis.nullable is False
    assert basis.server_default is not None
    assert basis.server_default.arg == "reference"  # type: ignore[union-attr]
    assert table.c["commission"].nullable is True
    assert table.c["trade_date"].nullable is True
    checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
    assert {"ck_positions_basis", "ck_positions_commission_non_negative"} <= checks


def test_portfolios_origin_column() -> None:
    """Migration 0007: portfolios.origin with the manual|builder check."""
    from sqlalchemy import CheckConstraint

    table = _table("portfolios")
    origin = table.c["origin"]
    assert origin.nullable is False
    assert origin.server_default is not None
    assert origin.server_default.arg == "manual"  # type: ignore[union-attr]
    checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
    assert "ck_portfolios_origin" in checks


# ---------------------------------------------------------------------------
# Fund universe models (Tasks 2.2-2.5, 4.3) — funds_v / fund_risk_latest_mv /
# nav_timeseries / fund_holdings_v / fund_classes_v.
# Ported from the retired test_funds_sync.py (Task 4.2): these assert the live
# ORM model contracts (Base.metadata), independent of the deleted fund sync.
# ---------------------------------------------------------------------------

def test_fund_tables_registered() -> None:
    # funds_v / fund_risk_latest_mv / fund_holdings_v / fund_classes_v are now
    # dynamic VIEWs/MVs (Tasks 2.2-2.5); fund_benchmark_candidates_v is the
    # read-only benchmark resolution view; FundNav is repointed to the live
    # nav_timeseries hypertable (Task 4.3) — the fund_nav snapshot is retired.
    for name in (
        "funds_v", "fund_risk_latest_mv", "nav_timeseries",
        "fund_holdings_v", "fund_classes_v", "fund_benchmark_candidates_v",
    ):
        assert name in Base.metadata.tables


def test_funds_pk_and_columns() -> None:
    # Fund is now the dynamic VIEW funds_v (Task 2.3): instrument_id is the PK;
    # the staleness columns (synced_at / source_calc_date / source_nav_max_date)
    # were dropped (a view has no sync markers — the catalog service derives
    # staleness from the risk MV + NAV instead).
    table = _table("funds_v")
    assert [c.name for c in table.primary_key.columns] == ["instrument_id"]
    for col in ("synced_at", "source_calc_date", "source_nav_max_date"):
        assert col not in table.c, col
    for col in ("series_id", "name", "fund_type", "strategy_label"):
        assert table.c[col].nullable is False, col


def test_funds_filter_columns_are_indexed() -> None:
    # The model still declares index=True on the filter columns; these Index
    # objects live in metadata for the funds_v-mapped class (the physical view
    # ignores them, but the ORM contract is preserved for consistency).
    indexed = {c.name for idx in _table("funds_v").indexes for c in idx.columns}
    assert {"series_id", "fund_type", "strategy_label"} <= indexed


def test_fund_benchmark_candidates_columns() -> None:
    table = _table("fund_benchmark_candidates_v")
    assert [c.name for c in table.primary_key.columns] == ["series_id"]
    for col in (
        "benchmark_name",
        "benchmark_proxy_ticker",
        "benchmark_proxy_instrument_id",
        "benchmark_proxy_fit_quality_score",
        "benchmark_proxy_asset_class",
        "benchmark_resolution_method",
    ):
        assert table.c[col].nullable is True, col
    assert table.c["benchmark_resolution_conflict"].nullable is False
    assert table.c["benchmark_proxy_candidates"].nullable is False
    assert table.c["benchmark_canonical_name_matches"].nullable is False


def test_fund_classes_pk_fk_and_columns() -> None:
    """FundClass model lockstep. Now the fund_classes_v VIEW (Task 2.5) keyed by
    series_id — the instrument_id column was DROPPED (a class links to a fund via
    series_id; readers resolve series→instrument through funds_v). A view cannot
    be a FK target, so there are no foreign keys."""
    table = _table("fund_classes_v")
    assert [c.name for c in table.primary_key.columns] == ["class_id"]
    assert not table.foreign_keys
    assert "instrument_id" not in table.c
    assert table.c["ticker"].nullable is False
    assert table.c["synced_at"].nullable is False
    assert table.c["synced_at"].type.timezone is True  # type: ignore[attr-defined]
    for col in ("series_id", "class_name", "expense_ratio", "source_period_end"):
        assert table.c[col].nullable is True, col
    indexed = {c.name for idx in table.indexes for c in idx.columns}
    assert {"ticker", "series_id"} <= indexed


def test_fund_risk_latest_pk_and_metric_lockstep() -> None:
    # Now MV-backed (fund_risk_latest_mv): a materialized view is not a FK
    # target, so instrument_id is a plain PK with NO ForeignKey to funds.
    table = _table("fund_risk_latest_mv")
    assert [c.name for c in table.primary_key.columns] == ["instrument_id"]
    assert not table.foreign_keys
    # Every metric column (model columns minus the PK + calc_date) is nullable —
    # the mother DB has per-metric gaps. (RISK_METRIC_COLUMNS lived in the
    # deleted sync module; derive the metric set from the model instead.)
    assert table.c["calc_date"].nullable is False
    metric_cols = {c.name for c in table.c} - {"instrument_id", "calc_date"}
    assert metric_cols, "fund_risk_latest_mv must declare metric columns"
    for col in metric_cols:
        assert table.c[col].nullable is True, col


def test_fund_risk_latest_surfaces_orphaned_worker_columns() -> None:
    """T2F-1: volatility_garch / vol_model / cvar_999_evt / evt_xi_shape are
    computed by the worker into fund_risk_metrics; the MV-backed ORM must carry
    them (nullable) so FundRiskOut can surface them."""
    from sqlalchemy import Numeric, String

    table = _table("fund_risk_latest_mv")
    for col in ("volatility_garch", "cvar_999_evt", "evt_xi_shape"):
        assert col in table.c, col
        assert isinstance(table.c[col].type, Numeric), col
        assert table.c[col].nullable is True, col
    assert "vol_model" in table.c
    assert isinstance(table.c["vol_model"].type, String)
    assert table.c["vol_model"].nullable is True


def test_fund_nav_composite_pk_and_no_fk() -> None:
    # FundNav is repointed to the live nav_timeseries hypertable (Task 4.3); a
    # hypertable is not a FK target, so instrument_id stays a plain composite-PK
    # column (with nav_date) and NO ForeignKey.
    table = _table("nav_timeseries")
    assert [c.name for c in table.primary_key.columns] == ["instrument_id", "nav_date"]
    assert not table.foreign_keys


def test_fund_holdings_composite_pk_and_no_truncation_flag() -> None:
    # FundHolding is now the fund_holdings_v VIEW (Task 2.5); the ORM identity
    # PK (series_id, report_date, rank) is unchanged.
    table = _table("fund_holdings_v")
    assert [c.name for c in table.primary_key.columns] == [
        "series_id", "report_date", "rank",
    ]
    # Frente C: o flag is_top50_truncated foi aposentado (migration 0008).
    assert "is_top50_truncated" not in table.c
