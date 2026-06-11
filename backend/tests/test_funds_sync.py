"""Tests for the fund sync (app/sync/funds.py) and its local tables (F8.1).

No live network and no live DB — and NEVER the real mother DB: pure helpers
are tested directly, upsert statements are compiled against the PostgreSQL
dialect, the eligibility SQL is checked structurally, and the model/migration
contract is verified via SQLAlchemy metadata.
"""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.models import Base
from app.sync.funds import (
    ELIGIBLE_FUNDS_SQL,
    HOLDINGS_SQL,
    MAX_HOLDINGS_PER_SERIES,
    NAV_SQL,
    RISK_CALC_CUTOFF,
    RISK_LATEST_SQL,
    RISK_METRIC_COLUMNS,
    UNCLASSIFIED_LABEL,
    build_fund_row,
    build_funds_upsert,
    build_holdings_upsert,
    build_nav_upsert,
    build_risk_upsert,
    cascade_strategy_label,
    derive_expense_ratio,
    derive_fund_type,
    eligibility_params,
    index_profiles_by_series,
    latest_aum_by_instrument,
    merge_risk_duplicates,
    nav_window_start,
    rank_holdings,
)

_TODAY = dt.date(2026, 6, 11)
_NOW = dt.datetime(2026, 6, 11, 12, 0, tzinfo=dt.UTC)
_IID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _identity(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "instrument_id": _IID,
        "sec_series_id": "S000001234",
        "ticker": "FNDX",
        "isin": "US0000000001",
        "cusip_9": "000000001",
        "lei": "LEI000000000000000001",
        "source_calc_date": dt.date(2026, 6, 9),
        "source_nav_max_date": dt.date(2026, 6, 5),
    }
    row.update(overrides)
    return row


def _compiled(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


# ---------------------------------------------------------------------------
# Strategy-label cascade
# ---------------------------------------------------------------------------


def test_cascade_prefers_registered() -> None:
    label = cascade_strategy_label(
        {"strategy_label": "Large Blend"},
        {"strategy_label": "Index Equity"},
        {"strategy_label": "Prime MMF"},
    )
    assert label == "Large Blend"


def test_cascade_falls_through_null_and_blank() -> None:
    assert (
        cascade_strategy_label({"strategy_label": None}, {"strategy_label": "  "},
                               {"strategy_label": "Govt MMF"})
        == "Govt MMF"
    )


def test_cascade_unclassified_when_all_missing() -> None:
    assert cascade_strategy_label(None, {"strategy_label": None}, None) == UNCLASSIFIED_LABEL
    assert UNCLASSIFIED_LABEL == "Unclassified"


def test_cascade_strips_whitespace() -> None:
    assert cascade_strategy_label({"strategy_label": " Value "}, None, None) == "Value"


def test_cascade_stage_label_beats_peer_and_unclassified() -> None:
    label = cascade_strategy_label(
        None, None, None, stage_label="Emerging Markets Equity", peer_label="Large Blend"
    )
    assert label == "Emerging Markets Equity"


def test_cascade_specific_peer_label_used_as_last_resort() -> None:
    assert (
        cascade_strategy_label(None, None, None, stage_label=None, peer_label="High Yield Bond")
        == "High Yield Bond"
    )


def test_cascade_generic_peer_labels_do_not_classify() -> None:
    for generic in ("mutual_fund", "etf", "MMF", " UCITS "):
        assert (
            cascade_strategy_label(None, None, None, peer_label=generic)
            == UNCLASSIFIED_LABEL
        )


# ---------------------------------------------------------------------------
# fund_type derivation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("in_registered", "in_etf", "in_mmf", "expected"),
    [
        (True, False, False, "mutual_fund"),
        (False, True, False, "etf"),
        (False, False, True, "mmf"),
        (True, True, False, "etf"),  # ETF presence wins
        (True, False, True, "mmf"),  # MMF presence wins over registered
        # All eligible instruments are instruments_universe type 'fund', so
        # absence from the three N-CEN/N-MFP tables still means mutual fund.
        (False, False, False, "mutual_fund"),
    ],
)
def test_derive_fund_type(
    in_registered: bool, in_etf: bool, in_mmf: bool, expected: str
) -> None:
    assert (
        derive_fund_type(in_registered=in_registered, in_etf=in_etf, in_mmf=in_mmf)
        == expected
    )


# ---------------------------------------------------------------------------
# Expense ratio + fund row assembly
# ---------------------------------------------------------------------------


def test_expense_ratio_prefers_net_operating_expenses_over_management_fee() -> None:
    registered = {"net_operating_expenses": None, "management_fee": Decimal("0.50")}
    etf = {"net_operating_expenses": Decimal("0.09"), "management_fee": Decimal("0.07")}
    assert derive_expense_ratio(registered, etf) == Decimal("0.09")


def test_expense_ratio_falls_back_to_management_fee() -> None:
    registered = {"net_operating_expenses": None, "management_fee": Decimal("0.75")}
    assert derive_expense_ratio(registered, None) == Decimal("0.75")
    assert derive_expense_ratio(None, None) is None


def test_build_fund_row_full_cascade() -> None:
    registered = {
        "fund_name": "Reg Fund",
        "strategy_label": None,
        "is_index": None,
        "management_fee": Decimal("0.40"),
        "net_operating_expenses": None,
        "monthly_avg_net_assets": None,
        "primary_benchmark": None,
        "inception_date": None,
        "domicile": None,
        "currency": None,
    }
    etf = {
        "fund_name": "ETF Fund",
        "strategy_label": "Index Equity",
        "is_index": True,
        "index_tracked": "S&P 500",
        "management_fee": Decimal("0.03"),
        "net_operating_expenses": Decimal("0.05"),
        "monthly_avg_net_assets": Decimal("1000000"),
        "inception_date": dt.date(2010, 1, 4),
        "domicile": "US",
        "currency": "USD",
    }
    row = build_fund_row(_identity(), {"name": "Universe Name", "currency": "USD"},
                         registered, etf, None, _NOW)
    assert row["instrument_id"] == _IID
    assert row["series_id"] == "S000001234"
    assert row["name"] == "Reg Fund"  # registered fund_name wins
    assert row["fund_type"] == "etf"  # ETF presence wins
    assert row["strategy_label"] == "Index Equity"  # cascade past NULL registered
    assert row["is_index"] is True
    assert row["expense_ratio"] == Decimal("0.05")  # net_operating_expenses preferred
    assert row["aum_usd"] == Decimal("1000000")
    assert row["primary_benchmark"] == "S&P 500"  # etf index_tracked fallback
    assert row["inception_date"] == dt.date(2010, 1, 4)
    assert row["domicile"] == "US"
    assert row["currency"] == "USD"
    assert row["synced_at"] == _NOW
    assert row["source_calc_date"] == dt.date(2026, 6, 9)
    assert row["source_nav_max_date"] == dt.date(2026, 6, 5)


def test_build_fund_row_unknown_series_never_null_name() -> None:
    row = build_fund_row(
        _identity(ticker=None, isin=None, lei=None), None, None, None, None, _NOW
    )
    assert row["fund_type"] == "mutual_fund"
    assert row["strategy_label"] == UNCLASSIFIED_LABEL
    assert row["asset_class"] is None
    assert row["name"] == "S000001234"  # last-resort series_id, never NULL
    assert row["expense_ratio"] is None
    assert row["aum_usd"] is None


def test_build_fund_row_carries_universe_asset_class_and_stage_label() -> None:
    row = build_fund_row(
        _identity(),
        {"name": "Universe Name", "currency": "USD", "asset_class": "fixed_income"},
        None,
        None,
        None,
        _NOW,
        stage_label="Government Bond",
        peer_label="mutual_fund",  # generic — must not be the label
    )
    assert row["asset_class"] == "fixed_income"
    assert row["strategy_label"] == "Government Bond"


def test_index_profiles_prefers_labeled_duplicate() -> None:
    rows = [
        {"series_id": "S1", "strategy_label": None, "fund_name": "A"},
        {"series_id": "S1", "strategy_label": "Value", "fund_name": "B"},
        {"series_id": "S2", "strategy_label": "Growth", "fund_name": "C"},
        {"series_id": "S2", "strategy_label": "Blend", "fund_name": "D"},  # first wins
    ]
    indexed = index_profiles_by_series(rows)
    assert indexed["S1"]["strategy_label"] == "Value"
    assert indexed["S2"]["strategy_label"] == "Growth"


# ---------------------------------------------------------------------------
# Eligibility criterion (SQL structure + parameters)
# ---------------------------------------------------------------------------


def test_eligibility_params_windows() -> None:
    risk_cutoff, min_history, freshness = eligibility_params(_TODAY)
    assert risk_cutoff == RISK_CALC_CUTOFF == dt.date(2026, 1, 1)
    assert min_history == _TODAY - dt.timedelta(days=730)  # 2 years of history
    assert freshness == _TODAY - dt.timedelta(days=30)  # fresh within 30 days


def test_nav_window_start_is_two_years_plus_30_days() -> None:
    assert nav_window_start(_TODAY) == _TODAY - dt.timedelta(days=760)


def test_eligible_sql_encodes_criterion() -> None:
    assert "sec_series_id IS NOT NULL" in ELIGIBLE_FUNDS_SQL
    assert "max(calc_date) >= $1" in ELIGIBLE_FUNDS_SQL
    assert "min_nav_date <= $2" in ELIGIBLE_FUNDS_SQL
    assert "max_nav_date >= $3" in ELIGIBLE_FUNDS_SQL
    assert "FROM fund_risk_metrics" in ELIGIBLE_FUNDS_SQL
    assert "FROM nav_timeseries" in ELIGIBLE_FUNDS_SQL


def test_mother_db_queries_are_read_only() -> None:
    """Absolute rule: only SELECTs ever reach the mother DB."""
    for sql in (ELIGIBLE_FUNDS_SQL, RISK_LATEST_SQL, NAV_SQL, HOLDINGS_SQL):
        body = sql.upper()
        for verb in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE"):
            assert verb not in body, f"non-SELECT verb {verb} in mother-DB SQL"


def test_nav_sql_is_always_filtered() -> None:
    """27M-row table: must filter by instrument batch AND date window."""
    assert "instrument_id = ANY($1::uuid[])" in NAV_SQL
    assert "nav_date >= $2" in NAV_SQL


def test_risk_latest_sql_selects_every_metric_column() -> None:
    for col in RISK_METRIC_COLUMNS:
        assert col in RISK_LATEST_SQL


# ---------------------------------------------------------------------------
# Holdings ranking
# ---------------------------------------------------------------------------


def _holding(series: str = "S1", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "series_id": series,
        "report_date": dt.date(2026, 5, 31),
        "cusip": "C1",
        "isin": None,
        "issuer_name": "Issuer",
        "asset_class": "EC",
        "sector": "Tech",
        "market_value": 100,
        "pct_of_nav": Decimal("1.0"),
    }
    row.update(overrides)
    return row


def test_rank_holdings_orders_by_pct_desc_nulls_last() -> None:
    rows = [
        _holding(cusip="LOW", pct_of_nav=Decimal("1.5")),
        _holding(cusip="NONE", pct_of_nav=None),
        _holding(cusip="HIGH", pct_of_nav=Decimal("9.9")),
    ]
    ranked = rank_holdings(rows)
    assert [(r["rank"], r["cusip"]) for r in ranked] == [
        (1, "HIGH"), (2, "LOW"), (3, "NONE"),
    ]
    assert all(r["is_top50_truncated"] is True for r in ranked)


def test_rank_holdings_caps_at_50_per_series() -> None:
    rows = [
        _holding(cusip=f"C{i:03d}", pct_of_nav=Decimal(i)) for i in range(60)
    ]
    ranked = rank_holdings(rows)
    assert len(ranked) == MAX_HOLDINGS_PER_SERIES == 50
    assert ranked[0]["cusip"] == "C059"  # highest pct first
    assert [r["rank"] for r in ranked] == list(range(1, 51))


def test_rank_holdings_groups_by_series() -> None:
    rows = [
        _holding(series="S1", cusip="A", pct_of_nav=Decimal(5)),
        _holding(series="S2", cusip="B", pct_of_nav=Decimal(7)),
        _holding(series="S1", cusip="C", pct_of_nav=Decimal(9)),
    ]
    ranked = rank_holdings(rows)
    s1 = [r for r in ranked if r["series_id"] == "S1"]
    s2 = [r for r in ranked if r["series_id"] == "S2"]
    assert [(r["rank"], r["cusip"]) for r in s1] == [(1, "C"), (2, "A")]
    assert [(r["rank"], r["cusip"]) for r in s2] == [(1, "B")]


# ---------------------------------------------------------------------------
# Risk duplicate merge (the source table has no PK; the latest calc_date
# carries two pipeline passes for ~3k instruments)
# ---------------------------------------------------------------------------


def test_merge_risk_duplicates_prefers_peer_row_and_fills_nulls() -> None:
    ir_row = {
        "instrument_id": _IID,
        "calc_date": dt.date(2026, 6, 9),
        "information_ratio_1y": Decimal("1.65"),
        "peer_strategy_label": None,
        "peer_sharpe_pctl": None,
        "manager_score": Decimal("66.51"),
    }
    peer_row = {
        "instrument_id": _IID,
        "calc_date": dt.date(2026, 6, 9),
        "information_ratio_1y": None,
        "peer_strategy_label": "mutual_fund",
        "peer_sharpe_pctl": Decimal("67.15"),
        "manager_score": Decimal("66.46"),
    }
    merged, duplicates = merge_risk_duplicates([ir_row, peer_row])
    assert duplicates == 1
    (row,) = merged
    assert row["peer_strategy_label"] == "mutual_fund"  # peer row is primary
    assert row["peer_sharpe_pctl"] == Decimal("67.15")
    assert row["manager_score"] == Decimal("66.46")  # peer row wins conflicts
    assert row["information_ratio_1y"] == Decimal("1.65")  # NULL filled from other


def test_merge_risk_duplicates_is_order_independent() -> None:
    a = {"instrument_id": _IID, "peer_strategy_label": None, "sharpe_1y": Decimal(1)}
    b = {"instrument_id": _IID, "peer_strategy_label": "etf", "sharpe_1y": Decimal(2)}
    (m1,), _ = merge_risk_duplicates([a, b])
    (m2,), _ = merge_risk_duplicates([b, a])
    assert m1 == m2
    assert m1["sharpe_1y"] == Decimal(2)


def test_merge_risk_duplicates_passes_singletons_through() -> None:
    other = uuid.UUID("00000000-0000-0000-0000-000000000002")
    rows = [
        {"instrument_id": _IID, "peer_strategy_label": "x"},
        {"instrument_id": other, "peer_strategy_label": None},
    ]
    merged, duplicates = merge_risk_duplicates(rows)
    assert duplicates == 0
    assert len(merged) == 2


# ---------------------------------------------------------------------------
# NAV aum fallback
# ---------------------------------------------------------------------------


def test_latest_aum_by_instrument_takes_latest_non_null() -> None:
    other = uuid.UUID("00000000-0000-0000-0000-000000000002")
    rows = [
        {"instrument_id": _IID, "nav_date": dt.date(2026, 6, 1), "aum_usd": Decimal(100)},
        {"instrument_id": _IID, "nav_date": dt.date(2026, 6, 5), "aum_usd": None},
        {"instrument_id": _IID, "nav_date": dt.date(2026, 6, 4), "aum_usd": Decimal(120)},
        {"instrument_id": other, "nav_date": dt.date(2026, 6, 5), "aum_usd": None},
    ]
    result = latest_aum_by_instrument(rows)
    assert result == {_IID: Decimal(120)}  # latest date with non-NULL aum; other absent


# ---------------------------------------------------------------------------
# Upsert statement builders (compiled against the PostgreSQL dialect)
# ---------------------------------------------------------------------------


def test_funds_upsert_is_idempotent_on_instrument_id() -> None:
    row = build_fund_row(_identity(), None, None, None, None, _NOW)
    sql = _compiled(build_funds_upsert([row]))
    assert "INSERT INTO funds" in sql
    assert "ON CONFLICT (instrument_id) DO UPDATE" in sql
    assert "strategy_label = excluded.strategy_label" in sql
    assert "synced_at = excluded.synced_at" in sql


def test_risk_upsert_updates_every_metric() -> None:
    row: dict[str, Any] = {
        "instrument_id": _IID,
        "calc_date": dt.date(2026, 6, 9),
        **{col: None for col in RISK_METRIC_COLUMNS},
    }
    sql = _compiled(build_risk_upsert([row]))
    assert "INSERT INTO fund_risk_latest" in sql
    assert "ON CONFLICT (instrument_id) DO UPDATE" in sql
    for col in RISK_METRIC_COLUMNS:
        assert f"{col} = excluded.{col}" in sql


def test_nav_upsert_conflicts_on_composite_pk() -> None:
    row = {
        "instrument_id": _IID,
        "nav_date": dt.date(2026, 6, 5),
        "nav": Decimal("10.01"),
        "return_1d": Decimal("0.001"),
        "aum_usd": None,
    }
    sql = _compiled(build_nav_upsert([row]))
    assert "INSERT INTO fund_nav" in sql
    assert "ON CONFLICT (instrument_id, nav_date) DO UPDATE" in sql


def test_holdings_upsert_conflicts_on_series_report_rank() -> None:
    rows = rank_holdings([_holding()])
    sql = _compiled(build_holdings_upsert(rows))
    assert "INSERT INTO fund_holdings" in sql
    assert "ON CONFLICT (series_id, report_date, rank) DO UPDATE" in sql


def test_upsert_builders_reject_empty_rows() -> None:
    for builder in (
        build_funds_upsert, build_risk_upsert, build_nav_upsert, build_holdings_upsert
    ):
        with pytest.raises(ValueError):
            builder([])


# ---------------------------------------------------------------------------
# Local tables (migration 0006 ↔ model metadata)
# ---------------------------------------------------------------------------


def _table(name: str) -> Any:
    return Base.metadata.tables[name]


def test_fund_tables_registered() -> None:
    for name in ("funds", "fund_risk_latest", "fund_nav", "fund_holdings"):
        assert name in Base.metadata.tables


def test_funds_pk_and_staleness_columns() -> None:
    table = _table("funds")
    assert table.primary_key.name == "pk_funds"
    assert [c.name for c in table.primary_key.columns] == ["instrument_id"]
    for col in ("synced_at", "source_calc_date", "source_nav_max_date"):
        assert table.c[col].nullable is False, col
    assert table.c["synced_at"].type.timezone is True
    for col in ("series_id", "name", "fund_type", "strategy_label"):
        assert table.c[col].nullable is False, col


def test_funds_filter_columns_are_indexed() -> None:
    indexed = {c.name for idx in _table("funds").indexes for c in idx.columns}
    assert {"series_id", "fund_type", "strategy_label"} <= indexed


def test_fund_risk_latest_pk_fk_and_metric_lockstep() -> None:
    table = _table("fund_risk_latest")
    assert [c.name for c in table.primary_key.columns] == ["instrument_id"]
    (fk,) = table.foreign_keys
    assert fk.column.table.name == "funds"
    assert fk.ondelete == "CASCADE"
    # Model columns == PK + calc_date + RISK_METRIC_COLUMNS, exactly.
    assert {c.name for c in table.c} == {"instrument_id", "calc_date", *RISK_METRIC_COLUMNS}
    assert table.c["calc_date"].nullable is False
    for col in RISK_METRIC_COLUMNS:
        assert table.c[col].nullable is True, col


def test_fund_nav_composite_pk_and_fk_cascade() -> None:
    table = _table("fund_nav")
    assert [c.name for c in table.primary_key.columns] == ["instrument_id", "nav_date"]
    (fk,) = table.foreign_keys
    assert fk.column.table.name == "funds"
    assert fk.ondelete == "CASCADE"


def test_fund_holdings_composite_pk_and_truncation_flag() -> None:
    table = _table("fund_holdings")
    assert [c.name for c in table.primary_key.columns] == [
        "series_id", "report_date", "rank",
    ]
    flag = table.c["is_top50_truncated"]
    assert flag.nullable is False
    assert flag.server_default is not None
    assert flag.server_default.arg == "true"
