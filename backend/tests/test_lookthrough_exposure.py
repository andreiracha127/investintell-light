"""Tests for ``fund_equity_exposure`` (Sprint B / Task 3).

Per-fund equity look-through matrix: for each fund instrument id, a map
``security_key -> pct_of_nav`` (fraction 0..1) covering ONLY equity holdings.
This feeds the per-equity overlap constraint in Task 4.

The decomposition is REUSED from ``app.services.lookthrough`` (the same
``build_portfolio_exposure_tree`` engine the portfolio drilldown uses). These
tests stub the holdings source the same way ``test_lookthrough.py`` does — a
fake datalake whose ``execute`` returns N-PORT-shaped rows — plus a stub for
the fund-id -> series-id resolution. No live cloud, no live DB.
"""

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from app.services import lookthrough_exposure as lte

_REPORT = dt.date(2026, 1, 31)

_FUND_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
_FUND_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")
_FUND_C = uuid.UUID("00000000-0000-0000-0000-00000000000c")


async def _no_taxonomy(session, series_ids):
    """Stub the catalog taxonomy: equity classification falls back to N-PORT."""
    return {}


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _holding(series_id, cusip, issuer, asset_class, pct, isin=None):
    return SimpleNamespace(
        series_id=series_id,
        report_date=_REPORT,
        cusip=cusip,
        isin=isin,
        issuer_name=issuer,
        asset_class=asset_class,
        sector="CORP",
        currency="USD",
        pct_of_nav=pct,
    )


class _FakeDatalake:
    """N-PORT-shaped holdings keyed by series, plus an empty child-series map."""

    def __init__(self, holdings_by_series):
        self._holdings_by_series = holdings_by_series

    async def execute(self, stmt, params):
        sql = str(stmt)
        if "sec_cusip_ticker_map" in sql:
            # No fund-of-fund edges in these fixtures: every leaf is final.
            return _Result([])
        rows = []
        for series_id in params["series_ids"]:
            rows.extend(self._holdings_by_series.get(series_id, []))
        return _Result(rows)


@pytest.mark.anyio
async def test_two_funds_sharing_equity_security(monkeypatch):
    """Two funds holding a common equity CUSIP each report its pct_of_nav."""
    series_by_fund = {_FUND_A: "S_A", _FUND_B: "S_B"}

    async def fake_series(session, instrument_id):
        return series_by_fund.get(instrument_id)

    monkeypatch.setattr(lte, "get_fund_series", fake_series)
    monkeypatch.setattr(lte, "get_fund_taxonomy_by_series", _no_taxonomy)

    datalake = _FakeDatalake(
        {
            # S_A: 60% Apple (shared) + 40% Tesla
            "S_A": [
                _holding("S_A", "037833100", "Apple Inc", "EC", 60.0),
                _holding("S_A", "88160R101", "Tesla Inc", "EC", 40.0),
            ],
            # S_B: 30% Apple (shared) + 70% Microsoft
            "S_B": [
                _holding("S_B", "037833100", "Apple Inc", "EC", 30.0),
                _holding("S_B", "594918104", "Microsoft", "EC", 70.0),
            ],
        }
    )

    result = await lte.fund_equity_exposure(
        SimpleNamespace(),  # local session (unused beyond get_fund_series stub)
        datalake,
        [_FUND_A, _FUND_B],
    )

    assert set(result) == {_FUND_A, _FUND_B}
    # _cusip_key returns the full CUSIP string for non-synthetic ids.
    assert result[_FUND_A]["037833100"] == pytest.approx(0.60)
    assert result[_FUND_A]["88160R101"] == pytest.approx(0.40)
    assert result[_FUND_B]["037833100"] == pytest.approx(0.30)
    assert result[_FUND_B]["594918104"] == pytest.approx(0.70)
    # Shared security present in BOTH funds' maps.
    assert "037833100" in result[_FUND_A]
    assert "037833100" in result[_FUND_B]


@pytest.mark.anyio
async def test_debt_holding_is_excluded(monkeypatch):
    """Non-equity (debt) holdings never appear in the equity exposure map."""

    async def fake_series(session, instrument_id):
        return "S_MIX"

    monkeypatch.setattr(lte, "get_fund_series", fake_series)
    monkeypatch.setattr(lte, "get_fund_taxonomy_by_series", _no_taxonomy)

    datalake = _FakeDatalake(
        {
            "S_MIX": [
                _holding("S_MIX", "037833100", "Apple Inc", "EC", 50.0),
                _holding("S_MIX", "9128285M8", "U.S. Treasury", "DBT", 50.0),
            ],
        }
    )

    result = await lte.fund_equity_exposure(SimpleNamespace(), datalake, [_FUND_A])

    assert _FUND_A in result
    assert result[_FUND_A] == {"037833100": pytest.approx(0.50)}
    # The Treasury CUSIP (debt) must be absent.
    assert "9128285M8" not in result[_FUND_A]


@pytest.mark.anyio
async def test_fund_without_lookthrough_is_absent(monkeypatch):
    """A fund with no series / no holdings does not appear in the result."""
    series_by_fund = {_FUND_A: "S_A", _FUND_C: None}

    async def fake_series(session, instrument_id):
        return series_by_fund.get(instrument_id)

    monkeypatch.setattr(lte, "get_fund_series", fake_series)
    monkeypatch.setattr(lte, "get_fund_taxonomy_by_series", _no_taxonomy)

    datalake = _FakeDatalake(
        {"S_A": [_holding("S_A", "037833100", "Apple Inc", "EC", 100.0)]}
    )

    result = await lte.fund_equity_exposure(
        SimpleNamespace(), datalake, [_FUND_A, _FUND_C]
    )

    assert _FUND_A in result
    assert _FUND_C not in result  # no series -> absent (contributes 0 downstream)


@pytest.mark.anyio
async def test_fund_with_series_but_no_holdings_is_absent(monkeypatch):
    """A fund whose series has no materialized holdings is omitted entirely."""

    async def fake_series(session, instrument_id):
        return "S_EMPTY"

    monkeypatch.setattr(lte, "get_fund_series", fake_series)
    monkeypatch.setattr(lte, "get_fund_taxonomy_by_series", _no_taxonomy)

    datalake = _FakeDatalake({})  # S_EMPTY returns no rows

    result = await lte.fund_equity_exposure(SimpleNamespace(), datalake, [_FUND_A])

    assert _FUND_A not in result
