"""Tests for the drift / class / overlap evaluation logic (Sprint C, Task 2).

The pure helpers (``inception_target_weights``, ``compute_class_breaches``) are
tested directly. The async helpers (``compute_overlap_breaches``,
``evaluate_portfolio_drift``) stub their data loaders the same way the
rebalance / overview / lookthrough tests do — fake async functions monkeypatched
onto the module, plus ``SimpleNamespace`` stand-ins for ORM rows. No live cloud,
no live DB.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from app.services import portfolio_drift as pd
from app.services.portfolio_constraints import ClassLimit, ConstraintSet
from app.services.portfolio_crud import PositionTaxonomy

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-00000000000a")
_FUND_ID_2 = uuid.UUID("00000000-0000-0000-0000-00000000000b")


def _txn(ticker: str, quantity: float, price: float) -> SimpleNamespace:
    return SimpleNamespace(ticker=ticker, quantity=quantity, price=price)


# ---------------------------------------------------------------------------
# inception_target_weights
# ---------------------------------------------------------------------------


def test_inception_target_weights_normalizes_by_qty_times_price():
    txns = [_txn("AAPL", 10.0, 100.0), _txn("MSFT", 20.0, 50.0)]
    # AAPL notional 1000, MSFT notional 1000 -> 50/50.
    weights = pd.inception_target_weights(txns)
    assert weights["AAPL"] == pytest.approx(0.5)
    assert weights["MSFT"] == pytest.approx(0.5)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_inception_target_weights_aggregates_duplicate_tickers():
    txns = [_txn("AAPL", 10.0, 100.0), _txn("AAPL", 10.0, 100.0), _txn("MSFT", 10.0, 100.0)]
    weights = pd.inception_target_weights(txns)
    # AAPL 2000, MSFT 1000 -> 2/3, 1/3.
    assert weights["AAPL"] == pytest.approx(2 / 3)
    assert weights["MSFT"] == pytest.approx(1 / 3)


def test_inception_target_weights_empty_is_empty():
    assert pd.inception_target_weights([]) == {}


# ---------------------------------------------------------------------------
# compute_class_breaches
# ---------------------------------------------------------------------------


def _cs(class_limits):
    return ConstraintSet(
        portfolio_id=1, cap=None, min_weight=None, overlap_cap=None,
        class_limits=class_limits,
    )


def test_compute_class_breaches_below_min():
    cs = _cs([ClassLimit("equity", min_weight=0.40, max_weight=None)])
    breaches = pd.compute_class_breaches({"equity": 0.30}, cs)
    assert len(breaches) == 1
    b = breaches[0]
    assert b.asset_class == "equity"
    assert b.kind == "below_min"
    assert b.current_weight == pytest.approx(0.30)
    assert b.min_weight == pytest.approx(0.40)


def test_compute_class_breaches_above_max():
    cs = _cs([ClassLimit("equity", min_weight=None, max_weight=0.60)])
    breaches = pd.compute_class_breaches({"equity": 0.75}, cs)
    assert len(breaches) == 1
    assert breaches[0].kind == "above_max"
    assert breaches[0].max_weight == pytest.approx(0.60)


def test_compute_class_breaches_within_bounds_is_empty():
    cs = _cs([ClassLimit("equity", min_weight=0.40, max_weight=0.60)])
    assert pd.compute_class_breaches({"equity": 0.50}, cs) == []


def test_compute_class_breaches_missing_class_treated_as_zero():
    # A class with a min but no current weight -> 0 < min -> below_min.
    cs = _cs([ClassLimit("fixed_income", min_weight=0.20, max_weight=None)])
    breaches = pd.compute_class_breaches({"equity": 1.0}, cs)
    assert len(breaches) == 1
    assert breaches[0].asset_class == "fixed_income"
    assert breaches[0].kind == "below_min"
    assert breaches[0].current_weight == pytest.approx(0.0)


def test_compute_class_breaches_none_constraints_is_empty():
    assert pd.compute_class_breaches({"equity": 1.0}, None) == []


def test_compute_class_breaches_no_class_limits_is_empty():
    assert pd.compute_class_breaches({"equity": 1.0}, _cs([])) == []


# ---------------------------------------------------------------------------
# compute_overlap_breaches
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compute_overlap_breaches_aggregates_and_thresholds(monkeypatch):
    # Two funds each hold a shared equity AAPL plus a unique one.
    async def fake_exposure(session, datalake, fund_ids):
        return {
            _FUND_ID: {"AAPL": 0.50, "TSLA": 0.50},
            _FUND_ID_2: {"AAPL": 0.40, "MSFT": 0.60},
        }

    monkeypatch.setattr(pd, "fund_equity_exposure", fake_exposure)

    # 60% in fund A, 40% in fund B.
    fund_weights = {_FUND_ID: 0.60, _FUND_ID_2: 0.40}
    # AAPL exposure = 0.6*0.5 + 0.4*0.4 = 0.30 + 0.16 = 0.46
    # TSLA = 0.6*0.5 = 0.30 ; MSFT = 0.4*0.6 = 0.24
    breaches = await pd.compute_overlap_breaches(
        SimpleNamespace(), SimpleNamespace(), fund_weights,
        overlap_cap=0.40, fund_ids=[_FUND_ID, _FUND_ID_2],
    )
    by_key = {b.security_key: b for b in breaches}
    # Only AAPL (0.46) breaches the 0.40 cap.
    assert set(by_key) == {"AAPL"}
    assert by_key["AAPL"].exposure == pytest.approx(0.46)
    assert by_key["AAPL"].overlap_cap == pytest.approx(0.40)


@pytest.mark.anyio
async def test_compute_overlap_breaches_none_cap_is_empty(monkeypatch):
    called = False

    async def fake_exposure(session, datalake, fund_ids):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(pd, "fund_equity_exposure", fake_exposure)
    breaches = await pd.compute_overlap_breaches(
        SimpleNamespace(), SimpleNamespace(), {_FUND_ID: 1.0},
        overlap_cap=None, fund_ids=[_FUND_ID],
    )
    assert breaches == []
    assert called is False  # short-circuits without touching the datalake


# ---------------------------------------------------------------------------
# evaluate_portfolio_drift orchestration
# ---------------------------------------------------------------------------


def _position(ticker: str, quantity: float) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker, quantity=quantity, acq_price=None, basis="reference",
        commission=None, trade_date=None,
    )


def _stub_current_weights(monkeypatch, *, fund_ids, closes, navs, taxonomy):
    async def fake_fund_ids(session, tickers):
        return dict(fund_ids)

    async def fake_closes(session, tickers):
        return dict(closes)

    async def fake_navs(session, tickers):
        return dict(navs)

    async def fake_taxonomy(session, tickers):
        return dict(taxonomy)

    monkeypatch.setattr(pd, "fund_instrument_ids_by_ticker", fake_fund_ids)
    monkeypatch.setattr(pd, "select_last_two_closes", fake_closes)
    monkeypatch.setattr(pd, "select_last_two_navs", fake_navs)
    monkeypatch.setattr(pd, "resolve_position_taxonomy", fake_taxonomy)


def _stub_inception(monkeypatch, txns):
    async def fake_inception_txns(session, portfolio):
        return list(txns)

    monkeypatch.setattr(pd, "load_inception_transactions", fake_inception_txns)


@pytest.mark.anyio
async def test_evaluate_no_inception_skips_drift_but_evaluates_class_and_overlap(
    monkeypatch,
):
    portfolio = SimpleNamespace(
        id=7, name="P", cash=0.0, inception_date=None,
        positions=[_position("AAPL", 10.0), _position("MSFT", 10.0)],
    )
    _stub_current_weights(
        monkeypatch,
        fund_ids={},
        closes={
            "AAPL": [(dt.date(2026, 6, 11), 70.0)],
            "MSFT": [(dt.date(2026, 6, 11), 30.0)],
        },
        navs={},
        taxonomy={
            "AAPL": PositionTaxonomy("equity", None, None),
            "MSFT": PositionTaxonomy("equity", None, None),
        },
    )
    _stub_inception(monkeypatch, [])  # no inception -> no target

    async def fake_constraints(session, portfolio_id):
        return _cs([ClassLimit("fixed_income", min_weight=0.20, max_weight=None)])

    monkeypatch.setattr(pd, "get_constraints", fake_constraints)

    async def fake_report_date(session, datalake, fund_ids):
        return None  # no funds -> no N-PORT report

    monkeypatch.setattr(pd, "latest_nport_report_date", fake_report_date)

    worst, breaches = await pd.evaluate_portfolio_drift(
        SimpleNamespace(), SimpleNamespace(), portfolio,
        policy=None, previous=None, as_of=dt.date(2026, 6, 20),
    )
    # No inception target -> drift skipped (empty list).
    assert breaches["position_drifts"] == []
    # fixed_income min 0.20 with 0 weight -> class breach -> at least maintenance.
    assert len(breaches["class_breaches"]) == 1
    assert breaches["class_breaches"][0]["asset_class"] == "fixed_income"
    assert worst == "maintenance"


@pytest.mark.anyio
async def test_evaluate_worst_status_urgent_from_drift(monkeypatch):
    portfolio = SimpleNamespace(
        id=8, name="P", cash=0.0, inception_date=dt.date(2026, 1, 2),
        positions=[_position("AAPL", 10.0), _position("MSFT", 10.0)],
    )
    # Current: AAPL 80%, MSFT 20% (price 80/20 on 10 shares each).
    _stub_current_weights(
        monkeypatch,
        fund_ids={},
        closes={
            "AAPL": [(dt.date(2026, 6, 11), 80.0)],
            "MSFT": [(dt.date(2026, 6, 11), 20.0)],
        },
        navs={},
        taxonomy={
            "AAPL": PositionTaxonomy("equity", None, None),
            "MSFT": PositionTaxonomy("equity", None, None),
        },
    )
    # Inception target 50/50 -> AAPL drift 0.30 -> urgent (> 2*0.05=0.10).
    _stub_inception(
        monkeypatch,
        [_txn("AAPL", 10.0, 50.0), _txn("MSFT", 10.0, 50.0)],
    )

    async def fake_constraints(session, portfolio_id):
        return None

    monkeypatch.setattr(pd, "get_constraints", fake_constraints)

    async def fake_report_date(session, datalake, fund_ids):
        return None

    monkeypatch.setattr(pd, "latest_nport_report_date", fake_report_date)

    worst, breaches = await pd.evaluate_portfolio_drift(
        SimpleNamespace(), SimpleNamespace(), portfolio,
        policy=None, previous=None, as_of=dt.date(2026, 6, 20),
    )
    drifts = {d["ticker"]: d for d in breaches["position_drifts"]}
    assert drifts["AAPL"]["status"] == "urgent"
    assert worst == "urgent"


@pytest.mark.anyio
async def test_evaluate_reuses_previous_overlap_when_report_date_unchanged(
    monkeypatch,
):
    portfolio = SimpleNamespace(
        id=9, name="P", cash=0.0, inception_date=dt.date(2026, 1, 2),
        positions=[_position("FUNDX", 10.0), _position("FUNDY", 10.0)],
    )
    _stub_current_weights(
        monkeypatch,
        fund_ids={"FUNDX": _FUND_ID, "FUNDY": _FUND_ID_2},
        closes={},
        navs={
            "FUNDX": [(dt.date(2026, 6, 11), 50.0)],
            "FUNDY": [(dt.date(2026, 6, 11), 50.0)],
        },
        taxonomy={
            "FUNDX": PositionTaxonomy("equity", None, _FUND_ID),
            "FUNDY": PositionTaxonomy("equity", None, _FUND_ID_2),
        },
    )
    _stub_inception(
        monkeypatch,
        [_txn("FUNDX", 10.0, 50.0), _txn("FUNDY", 10.0, 50.0)],
    )

    async def fake_constraints(session, portfolio_id):
        return ConstraintSet(
            portfolio_id=9, cap=None, min_weight=None, overlap_cap=0.40,
            class_limits=[],
        )

    monkeypatch.setattr(pd, "get_constraints", fake_constraints)

    stale_report = dt.date(2026, 1, 31)

    async def fake_report_date(session, datalake, fund_ids):
        return stale_report

    monkeypatch.setattr(pd, "latest_nport_report_date", fake_report_date)

    overlap_called = False

    async def fake_overlap(session, datalake, fund_weights, overlap_cap, fund_ids):
        nonlocal overlap_called
        overlap_called = True
        return []

    monkeypatch.setattr(pd, "compute_overlap_breaches", fake_overlap)

    previous = pd.DriftStatus(
        portfolio_id=9,
        evaluated_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        worst_status="maintenance",
        breaches={
            "overlap_report_date": stale_report.isoformat(),
            "overlap_breaches": [
                {"security_key": "AAPL", "exposure": 0.46, "overlap_cap": 0.40}
            ],
        },
    )

    worst, breaches = await pd.evaluate_portfolio_drift(
        SimpleNamespace(), SimpleNamespace(), portfolio,
        policy=None, previous=previous, as_of=dt.date(2026, 6, 20),
    )
    # report_date unchanged -> recompute SKIPPED, previous reused.
    assert overlap_called is False
    assert breaches["overlap_report_date"] == stale_report.isoformat()
    assert breaches["overlap_breaches"] == [
        {"security_key": "AAPL", "exposure": 0.46, "overlap_cap": 0.40}
    ]
    # A reused overlap breach still escalates worst_status.
    assert worst == "maintenance"


@pytest.mark.anyio
async def test_evaluate_recomputes_overlap_when_report_date_newer(monkeypatch):
    portfolio = SimpleNamespace(
        id=10, name="P", cash=0.0, inception_date=dt.date(2026, 1, 2),
        positions=[_position("FUNDX", 10.0), _position("FUNDY", 10.0)],
    )
    _stub_current_weights(
        monkeypatch,
        fund_ids={"FUNDX": _FUND_ID, "FUNDY": _FUND_ID_2},
        closes={},
        navs={
            "FUNDX": [(dt.date(2026, 6, 11), 50.0)],
            "FUNDY": [(dt.date(2026, 6, 11), 50.0)],
        },
        taxonomy={
            "FUNDX": PositionTaxonomy("equity", None, _FUND_ID),
            "FUNDY": PositionTaxonomy("equity", None, _FUND_ID_2),
        },
    )
    _stub_inception(
        monkeypatch,
        [_txn("FUNDX", 10.0, 50.0), _txn("FUNDY", 10.0, 50.0)],
    )

    async def fake_constraints(session, portfolio_id):
        return ConstraintSet(
            portfolio_id=10, cap=None, min_weight=None, overlap_cap=0.40,
            class_limits=[],
        )

    monkeypatch.setattr(pd, "get_constraints", fake_constraints)

    new_report = dt.date(2026, 4, 30)

    async def fake_report_date(session, datalake, fund_ids):
        return new_report

    monkeypatch.setattr(pd, "latest_nport_report_date", fake_report_date)

    overlap_called = False

    async def fake_overlap(session, datalake, fund_weights, overlap_cap, fund_ids):
        nonlocal overlap_called
        overlap_called = True
        return [
            pd.OverlapBreach(security_key="AAPL", exposure=0.46, overlap_cap=0.40)
        ]

    monkeypatch.setattr(pd, "compute_overlap_breaches", fake_overlap)

    previous = pd.DriftStatus(
        portfolio_id=10,
        evaluated_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        worst_status="ok",
        breaches={
            "overlap_report_date": dt.date(2026, 1, 31).isoformat(),
            "overlap_breaches": [],
        },
    )

    worst, breaches = await pd.evaluate_portfolio_drift(
        SimpleNamespace(), SimpleNamespace(), portfolio,
        policy=None, previous=previous, as_of=dt.date(2026, 6, 20),
    )
    # Newer report_date -> overlap recomputed.
    assert overlap_called is True
    assert breaches["overlap_report_date"] == new_report.isoformat()
    assert breaches["overlap_breaches"] == [
        {"security_key": "AAPL", "exposure": 0.46, "overlap_cap": 0.40}
    ]
    assert worst == "maintenance"
