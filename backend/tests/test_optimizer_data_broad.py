"""Tests for the broad-universe data seam in app/optimizer/data.py:
- load_returns_matrix: T×N WITHOUT global dropna (NaN preserved),
- select_universe_funds: cap removed (max_assets=None) + MAX_UNIVERSE_CANDIDATES,
- load_fund_quality_metrics: Sharpe/expense/AUM per fund.
"""

import datetime as dt
import decimal
import uuid
from typing import Any

import numpy as np
import pytest

from app.optimizer import data as optimizer_data

_FUND_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
_FUND_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")
_TODAY = dt.date(2026, 6, 11)


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


def _nav_rows(
    n: int, start: dt.date, nav0: float = 100.0
) -> list[tuple[dt.date, float, float | None]]:
    rng = np.random.default_rng(abs(hash(start)) % 2**32)
    rows = []
    nav = nav0
    day = start
    for _ in range(n):
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        r = float(rng.normal(0.0003, 0.006))
        nav *= float(np.exp(r))
        rows.append((day, nav, r))
        day += dt.timedelta(days=1)
    return rows


class _FakeSession:
    """Stubs the batched NAV query: one ``execute`` returns the rows for ALL
    requested fund ids, each prefixed with its instrument_id (matching the
    ``SELECT instrument_id, nav_date, nav, return_1d`` shape)."""

    def __init__(self, fund_rows: dict[uuid.UUID, list[tuple[Any, ...]]]) -> None:
        self._fund_rows = fund_rows
        self.calls = 0

    async def execute(self, stmt: Any) -> _FakeResult:
        self.calls += 1
        requested: set[Any] = set()
        for v in stmt.compile().params.values():
            if isinstance(v, (list, tuple, set)):
                requested.update(v)
            else:
                requested.add(v)
        out: list[tuple[Any, ...]] = []
        for fund_id, rows in self._fund_rows.items():
            if fund_id in requested:
                out.extend((fund_id, *row) for row in rows)
        return _FakeResult(out)


async def test_load_returns_matrix_preserves_nan_no_global_dropna() -> None:
    """Fund A: 500 obs from 2024-01; Fund B: 500 obs from 2024-06 (younger).
    The union index keeps ALL dates; the early rows for B are NaN, not dropped.
    The two funds are loaded in ONE batched query (no N+1).
    """
    rows_a = _nav_rows(500, dt.date(2024, 1, 2))
    rows_b = _nav_rows(500, dt.date(2024, 6, 3))
    session = _FakeSession({_FUND_A: rows_a, _FUND_B: rows_b})
    refs = [
        optimizer_data.FundAssetRef(id=_FUND_A),
        optimizer_data.FundAssetRef(id=_FUND_B),
    ]
    frame = await optimizer_data.load_returns_matrix(
        session, refs, window_days=None, today=_TODAY
    )
    # Union index is longer than the per-fund overlap (a dropna would shrink it).
    assert len(frame) > 500
    assert frame.isna().any().any()  # NaN preserved (B's early dates)
    assert list(frame.columns) == [r.label for r in refs]
    # Batched: a single round-trip for both funds, not one query per fund.
    assert session.calls == 1


async def test_load_returns_matrix_rejects_fewer_than_two() -> None:
    session = _FakeSession({_FUND_A: _nav_rows(500, dt.date(2024, 1, 2))})
    with pytest.raises(ValueError, match="at least 2"):
        await optimizer_data.load_returns_matrix(
            session, [optimizer_data.FundAssetRef(id=_FUND_A)],
            window_days=None, today=_TODAY,
        )


def test_max_universe_candidates_default_is_5000() -> None:
    assert optimizer_data.MAX_UNIVERSE_CANDIDATES == 5000


def test_universe_quality_gate_constants() -> None:
    assert optimizer_data.MIN_UNIVERSE_AUM_USD == 200_000_000
    assert optimizer_data.MIN_UNIVERSE_HISTORY_DAYS == 3 * 365


async def test_select_universe_funds_applies_aum_and_history_gates() -> None:
    """The universe resolver gates on AUM >= $200M and >= 3y of NAV history
    (track record). Verify both predicates are wired into the SQL."""
    captured: dict[str, str] = {}

    class _CaptureSession:
        async def execute(self, stmt: Any) -> _FakeResult:
            captured["sql"] = str(
                stmt.compile(compile_kwargs={"literal_binds": True})
            )
            return _FakeResult([])

    from app.services import funds_catalog

    today = dt.date(2026, 6, 17)
    await optimizer_data.select_universe_funds(
        _CaptureSession(),  # type: ignore[arg-type]
        funds_catalog.FundFilters(),
        rank_by="aum_usd",
        rank_dir="desc",
        max_assets=None,
        today=today,
    )
    sql = captured["sql"]
    assert "200000000" in sql  # AUM >= $200M floor
    cutoff = (
        today - dt.timedelta(days=optimizer_data.MIN_UNIVERSE_HISTORY_DAYS)
    ).isoformat()
    assert cutoff in sql  # earliest NAV on/before the 3y cutoff


_FUND_C = uuid.UUID("00000000-0000-0000-0000-00000000000c")


async def test_load_fund_quality_metrics_fills_defaults_for_missing_fund() -> None:
    """Funds present in DB get real values; a fund absent from DB gets all-None."""
    # DB rows: (instrument_id, expense_ratio, aum_usd, sharpe_1y) — matches the
    # SELECT column order in load_fund_quality_metrics.
    db_rows: list[tuple[Any, ...]] = [
        # FUND_A: fully populated, values as Decimal to exercise float cast.
        (
            _FUND_A,
            decimal.Decimal("0.0050"),   # expense_ratio
            decimal.Decimal("1_500_000_000"),  # aum_usd
            decimal.Decimal("1.23"),     # sharpe_1y
        ),
        # FUND_B: partially populated — sharpe_1y is NULL.
        (
            _FUND_B,
            decimal.Decimal("0.0075"),   # expense_ratio
            None,                        # aum_usd
            None,                        # sharpe_1y
        ),
        # FUND_C is intentionally absent from DB rows → should get all-None default.
    ]

    class _SimpleSession:
        async def execute(self, stmt: Any) -> _FakeResult:
            return _FakeResult(db_rows)

    result = await optimizer_data.load_fund_quality_metrics(
        _SimpleSession(), [_FUND_A, _FUND_B, _FUND_C]  # type: ignore[arg-type]
    )

    # Every requested id must be present.
    assert set(result.keys()) == {_FUND_A, _FUND_B, _FUND_C}

    # FUND_A: all three fields present and cast to float.
    a = result[_FUND_A]
    assert set(a.keys()) == {"sharpe_1y", "expense_ratio", "aum_usd"}
    assert isinstance(a["expense_ratio"], float)
    assert isinstance(a["aum_usd"], float)
    assert isinstance(a["sharpe_1y"], float)
    assert abs(a["expense_ratio"] - 0.005) < 1e-9
    assert abs(a["sharpe_1y"] - 1.23) < 1e-9

    # FUND_B: partial — aum_usd and sharpe_1y are None.
    b = result[_FUND_B]
    assert set(b.keys()) == {"sharpe_1y", "expense_ratio", "aum_usd"}
    assert isinstance(b["expense_ratio"], float)
    assert b["aum_usd"] is None
    assert b["sharpe_1y"] is None

    # FUND_C: not in DB → all-None default.
    c = result[_FUND_C]
    assert set(c.keys()) == {"sharpe_1y", "expense_ratio", "aum_usd"}
    assert c["sharpe_1y"] is None
    assert c["expense_ratio"] is None
    assert c["aum_usd"] is None

    # Each missing fund must get its OWN dict (not a shared mutable object).
    # Two separate missing funds must have distinct dict objects — confirm by
    # adding a second absent fund and checking identity.
    _FUND_X = uuid.UUID("00000000-0000-0000-0000-0000000000ff")
    result2 = await optimizer_data.load_fund_quality_metrics(
        _SimpleSession(), [_FUND_C, _FUND_X]  # type: ignore[arg-type]
    )
    assert result2[_FUND_C] is not result2[_FUND_X]


async def test_load_fund_risk_features_returns_all_keys_and_fills_missing() -> None:
    """Funds present in the MV get float features; an absent fund gets all-None;
    a NULL column maps to None."""
    keys = optimizer_data.RISK_FEATURE_KEYS
    # Row shape: (instrument_id, *features) in RISK_FEATURE_KEYS order.
    db_rows: list[tuple[Any, ...]] = [
        (_FUND_A, *[decimal.Decimal("0.10")] * len(keys)),
        (_FUND_B, *([decimal.Decimal("0.20")] * (len(keys) - 1) + [None])),
    ]

    class _S:
        async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
            return _FakeResult(db_rows)

    result = await optimizer_data.load_fund_risk_features(
        _S(), [_FUND_A, _FUND_B, _FUND_C]  # type: ignore[arg-type]
    )
    assert set(result.keys()) == {_FUND_A, _FUND_B, _FUND_C}
    assert set(result[_FUND_A].keys()) == set(keys)
    assert isinstance(result[_FUND_A][keys[0]], float)
    assert result[_FUND_B][keys[-1]] is None  # NULL column → None
    assert all(v is None for v in result[_FUND_C].values())  # absent → all-None


async def test_select_universe_funds_raises_when_exceeds_ceiling() -> None:
    """max_assets=None: raises ValueError (matching 'more than') when the DB
    returns more than MAX_UNIVERSE_CANDIDATES rows."""
    ceiling = optimizer_data.MAX_UNIVERSE_CANDIDATES
    # Build ceiling+1 minimal rows shaped as (instrument_id, ticker, name).
    oversized_rows: list[tuple[Any, ...]] = [
        (uuid.uuid4(), f"T{i:04d}", f"Fund {i}")
        for i in range(ceiling + 1)
    ]

    class _CeilingSession:
        async def execute(self, stmt: Any) -> _FakeResult:
            return _FakeResult(oversized_rows)

    from app.services import funds_catalog

    filters = funds_catalog.FundFilters()
    with pytest.raises(ValueError, match="more than"):
        await optimizer_data.select_universe_funds(
            _CeilingSession(),  # type: ignore[arg-type]
            filters,
            rank_by="aum_usd",
            rank_dir="desc",
            max_assets=None,
        )
