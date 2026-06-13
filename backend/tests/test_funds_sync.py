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
    CLASSES_SQL,
    ELIGIBLE_FUNDS_SQL,
    HOLDINGS_SQL,
    NAV_SQL,
    RISK_CALC_CUTOFF,
    RISK_LATEST_SQL,
    RISK_METRIC_COLUMNS,
    UNCLASSIFIED_LABEL,
    build_class_rows,
    build_classes_upsert,
    build_fund_row,
    build_funds_upsert,
    build_holdings_upsert,
    build_nav_upsert,
    build_risk_upsert,
    cascade_strategy_label,
    derive_expense_ratio,
    derive_fund_type,
    eligibility_params,
    index_instruments_by_series,
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


def test_expense_ratio_prospectus_beats_management_fee_but_not_ncen_net() -> None:
    registered = {"net_operating_expenses": None, "management_fee": Decimal("0.75")}
    assert (
        derive_expense_ratio(registered, None, prospectus_fee=Decimal("0.0069"))
        == Decimal("0.0069")
    )
    registered_net = {"net_operating_expenses": Decimal("0.0050"), "management_fee": None}
    assert (
        derive_expense_ratio(registered_net, None, prospectus_fee=Decimal("0.0069"))
        == Decimal("0.0050")
    )


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
    # Staleness markers (synced_at / source_calc_date / source_nav_max_date) are
    # no longer emitted — Fund is the funds_v VIEW (Task 2.3), which has none.
    assert "synced_at" not in row
    assert "source_calc_date" not in row
    assert "source_nav_max_date" not in row


def test_build_fund_row_etp_ticker_classifies_as_etf() -> None:
    """ETFs fora da sec_etfs (IVV/QQQ/AGG...) são reconhecidos pelo ticker
    listado como ETP no sec_cusip_ticker_map — nunca 'mutual_fund'."""
    row = build_fund_row(
        _identity(), None, None, None, None, _NOW,
        etp_tickers=frozenset({"FNDX"}),  # _identity() usa ticker FNDX
    )
    assert row["fund_type"] == "etf"

    # Ticker fora do set ETP: cai no default mutual_fund.
    row = build_fund_row(
        _identity(), None, None, None, None, _NOW,
        etp_tickers=frozenset({"IVV"}),
    )
    assert row["fund_type"] == "mutual_fund"


def test_build_fund_row_nport_aum_is_last_resort() -> None:
    """nport_aum só vence quando monthly_avg_net_assets (registered/etf) e
    classes_aum estão ausentes — e nunca sobrepõe uma fonte primária."""
    row = build_fund_row(
        _identity(), None, None, None, None, _NOW,
        nport_aum=Decimal("19550772563"),
    )
    assert row["aum_usd"] == Decimal("19550772563")

    registered = {"fund_name": "Reg Fund", "monthly_avg_net_assets": Decimal(5)}
    row = build_fund_row(
        _identity(), None, registered, None, None, _NOW,
        classes_aum=Decimal(7),
        nport_aum=Decimal(9),
    )
    assert row["aum_usd"] == Decimal(5)  # fonte primária vence

    row = build_fund_row(
        _identity(), None, None, None, None, _NOW,
        classes_aum=Decimal(7),
        nport_aum=Decimal(9),
    )
    assert row["aum_usd"] == Decimal(7)  # classes antes do N-PORT


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
    for sql in (ELIGIBLE_FUNDS_SQL, RISK_LATEST_SQL, NAV_SQL, HOLDINGS_SQL, CLASSES_SQL):
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
    assert all("is_top50_truncated" not in r for r in ranked)


def test_rank_holdings_keeps_all_rows_no_truncation() -> None:
    # Frente C: o gate top-50 foi aposentado — todos os holdings são mantidos.
    rows = [
        _holding(cusip=f"C{i:03d}", pct_of_nav=Decimal(i)) for i in range(60)
    ]
    ranked = rank_holdings(rows)
    assert len(ranked) == 60
    assert ranked[0]["cusip"] == "C059"  # highest pct first
    assert [r["rank"] for r in ranked] == list(range(1, 61))


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
# fund_classes (F8.6b)
# ---------------------------------------------------------------------------


def test_classes_sql_latest_filing_per_class_with_ticker() -> None:
    assert "DISTINCT ON (class_id)" in CLASSES_SQL
    assert "FROM sec_fund_classes" in CLASSES_SQL
    assert "ticker IS NOT NULL" in CLASSES_SQL
    assert "series_id = ANY($1::text[])" in CLASSES_SQL
    assert "ORDER BY class_id, xbrl_period_end DESC NULLS LAST" in CLASSES_SQL


def _class_record(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "class_id": "C000007", "series_id": "S000001234", "class_name": "Class R-6",
        "ticker": "rgagx", "expense_ratio_pct": Decimal("0.0030"),
        "xbrl_period_end": dt.date(2025, 12, 31),
    }
    row.update(overrides)
    return row


def test_build_class_rows_maps_series_and_uppercases_ticker() -> None:
    rows = build_class_rows(
        [_class_record()], {"S000001234": _IID}, _NOW
    )
    (row,) = rows
    assert row == {
        "class_id": "C000007",
        "instrument_id": _IID,
        "series_id": "S000001234",
        "class_name": "Class R-6",
        "ticker": "RGAGX",  # uppercased to the position-ticker convention
        "expense_ratio": Decimal("0.0030"),  # already a fraction in the source
        "source_period_end": dt.date(2025, 12, 31),
        "synced_at": _NOW,
    }


def test_build_class_rows_drops_unknown_series_and_blank_tickers() -> None:
    rows = build_class_rows(
        [
            _class_record(series_id="S_UNKNOWN"),
            _class_record(class_id="C000008", ticker="  "),
            _class_record(class_id="C000009", series_id=None),
        ],
        {"S000001234": _IID},
        _NOW,
    )
    assert rows == []


def test_index_instruments_by_series_lowest_uuid_wins() -> None:
    other = uuid.UUID("00000000-0000-0000-0000-000000000002")
    eligible = [
        {"sec_series_id": "S1", "instrument_id": other},
        {"sec_series_id": "S1", "instrument_id": _IID},
        {"sec_series_id": "S2", "instrument_id": other},
    ]
    assert index_instruments_by_series(eligible) == {"S1": _IID, "S2": other}


def test_classes_upsert_is_idempotent_on_class_id() -> None:
    rows = build_class_rows([_class_record()], {"S000001234": _IID}, _NOW)
    sql = _compiled(build_classes_upsert(rows))
    assert "INSERT INTO fund_classes" in sql
    assert "ON CONFLICT (class_id) DO UPDATE" in sql
    assert "ticker = excluded.ticker" in sql
    assert "expense_ratio = excluded.expense_ratio" in sql
    assert "synced_at = excluded.synced_at" in sql


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
    # Fund now maps the funds_v VIEW (Task 2.3); the upsert builder still
    # compiles (sync is retired in Task 4) and no longer touches staleness.
    assert "INSERT INTO funds_v" in sql
    assert "ON CONFLICT (instrument_id) DO UPDATE" in sql
    assert "strategy_label = excluded.strategy_label" in sql
    assert "synced_at" not in sql


def test_risk_upsert_updates_every_metric() -> None:
    row: dict[str, Any] = {
        "instrument_id": _IID,
        "calc_date": dt.date(2026, 6, 9),
        **{col: None for col in RISK_METRIC_COLUMNS},
    }
    sql = _compiled(build_risk_upsert([row]))
    assert "INSERT INTO fund_risk_latest_mv" in sql
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
    # `funds` is now the dynamic VIEW funds_v (Task 2.3); fund_risk_latest_mv is
    # the MV (Task 2.2). The remaining three are still physical tables for now.
    for name in (
        "funds_v", "fund_risk_latest_mv", "fund_nav", "fund_holdings", "fund_classes"
    ):
        assert name in Base.metadata.tables


def test_fund_classes_pk_fk_and_columns() -> None:
    """FundClass model lockstep. Fund is now the funds_v VIEW (Task 2.3) — a
    view cannot be a FK target, so instrument_id is a plain indexed column with
    NO ForeignKey to funds."""
    table = _table("fund_classes")
    assert [c.name for c in table.primary_key.columns] == ["class_id"]
    assert not table.foreign_keys
    assert table.c["ticker"].nullable is False
    assert table.c["synced_at"].nullable is False
    assert table.c["synced_at"].type.timezone is True
    for col in ("series_id", "class_name", "expense_ratio", "source_period_end"):
        assert table.c[col].nullable is True, col
    indexed = {c.name for idx in table.indexes for c in idx.columns}
    assert {"ticker", "instrument_id"} <= indexed


def test_positions_execution_columns() -> None:
    """Migration 0007: positions.basis/commission/trade_date + checks."""
    table = _table("positions")
    basis = table.c["basis"]
    assert basis.nullable is False
    assert basis.server_default is not None
    assert basis.server_default.arg == "reference"
    assert table.c["commission"].nullable is True
    assert table.c["trade_date"].nullable is True
    from sqlalchemy import CheckConstraint

    checks = {
        c.name for c in table.constraints if isinstance(c, CheckConstraint)
    }
    assert {"ck_positions_basis", "ck_positions_commission_non_negative"} <= checks


def test_portfolios_origin_column() -> None:
    """Migration 0007: portfolios.origin with the manual|builder check."""
    table = _table("portfolios")
    origin = table.c["origin"]
    assert origin.nullable is False
    assert origin.server_default is not None
    assert origin.server_default.arg == "manual"
    from sqlalchemy import CheckConstraint

    checks = {
        c.name for c in table.constraints if isinstance(c, CheckConstraint)
    }
    assert "ck_portfolios_origin" in checks


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


def test_fund_risk_latest_pk_and_metric_lockstep() -> None:
    # Now MV-backed (fund_risk_latest_mv): a materialized view is not a FK
    # target, so instrument_id is a plain PK with NO ForeignKey to funds.
    table = _table("fund_risk_latest_mv")
    assert [c.name for c in table.primary_key.columns] == ["instrument_id"]
    assert not table.foreign_keys
    # Model columns == PK + calc_date + RISK_METRIC_COLUMNS, exactly.
    assert {c.name for c in table.c} == {"instrument_id", "calc_date", *RISK_METRIC_COLUMNS}
    assert table.c["calc_date"].nullable is False
    for col in RISK_METRIC_COLUMNS:
        assert table.c[col].nullable is True, col


def test_fund_nav_composite_pk_and_no_fk() -> None:
    # Fund is now the funds_v VIEW (Task 2.3): a view cannot be a FK target, so
    # fund_nav.instrument_id is a plain composite-PK column with NO ForeignKey.
    table = _table("fund_nav")
    assert [c.name for c in table.primary_key.columns] == ["instrument_id", "nav_date"]
    assert not table.foreign_keys


def test_fund_holdings_composite_pk_and_no_truncation_flag() -> None:
    table = _table("fund_holdings")
    assert [c.name for c in table.primary_key.columns] == [
        "series_id", "report_date", "rank",
    ]
    # Frente C: o flag is_top50_truncated foi aposentado (migration 0008).
    assert "is_top50_truncated" not in table.c
