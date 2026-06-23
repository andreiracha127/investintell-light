"""Unit tests for app/optimizer/data.py with a faked AsyncSession (no DB).

Covers: return_1d preference with log-NAV fallback, date intersection,
the >= 400 common observations guard, unknown assets and duplicates.
"""

import datetime as dt
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


class _FakeSession:
    """Maps each asset to canned (date, ...) rows, keyed by the WHERE literal."""

    def __init__(self, fund_rows: dict[uuid.UUID, list[tuple[Any, ...]]]) -> None:
        self._fund_rows = fund_rows

    async def execute(self, stmt: Any) -> _FakeResult:
        params = stmt.compile().params
        for fund_id, rows in self._fund_rows.items():
            if fund_id in params.values():
                return _FakeResult(rows)
        return _FakeResult([])


def _nav_rows(
    n: int, start: dt.date, nav0: float = 100.0, with_return_1d: bool = True
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
        rows.append((day, nav, r if with_return_1d else None))
        day += dt.timedelta(days=1)
    return rows


def test_fund_return_series_prefers_return_1d_falls_back_to_log_nav() -> None:
    rows = [
        (dt.date(2026, 1, 5), 100.0, 0.001),
        (dt.date(2026, 1, 6), 101.0, None),  # fallback: log(101/100)
        (dt.date(2026, 1, 7), 102.0, 0.0099),
        (dt.date(2026, 1, 8), None, None),  # neither — dropped
    ]
    series = optimizer_data._fund_return_series(rows)
    assert list(series.index) == [dt.date(2026, 1, 5), dt.date(2026, 1, 6), dt.date(2026, 1, 7)]
    assert series.iloc[1] == pytest.approx(float(np.log(101.0 / 100.0)))


async def test_load_aligned_returns_intersects_dates() -> None:
    start = dt.date(2024, 7, 1)
    rows_a = _nav_rows(450, start)
    rows_b = _nav_rows(450, start, with_return_1d=False)[10:]  # shorter, shifted
    session = _FakeSession({_FUND_A: rows_a, _FUND_B: rows_b})
    frame = await optimizer_data.load_aligned_returns(
        session,  # type: ignore[arg-type]
        [optimizer_data.FundAssetRef(id=_FUND_A), optimizer_data.FundAssetRef(id=_FUND_B)],
        today=_TODAY,
    )
    assert list(frame.columns) == [f"fund:{_FUND_A}", f"fund:{_FUND_B}"]
    # B has no return_1d: first row needs a previous NAV, so one extra is lost.
    assert len(frame) >= optimizer_data.MIN_COMMON_OBS
    assert frame.notna().all().all()


async def test_load_aligned_returns_under_400_common_obs_raises() -> None:
    start = dt.date(2025, 9, 1)
    session = _FakeSession(
        {_FUND_A: _nav_rows(200, start), _FUND_B: _nav_rows(200, start)}
    )
    with pytest.raises(ValueError, match="insufficient common history"):
        await optimizer_data.load_aligned_returns(
            session,  # type: ignore[arg-type]
            [
                optimizer_data.FundAssetRef(id=_FUND_A),
                optimizer_data.FundAssetRef(id=_FUND_B),
            ],
            today=_TODAY,
        )


async def test_load_aligned_returns_unknown_asset_raises() -> None:
    session = _FakeSession({_FUND_A: _nav_rows(450, dt.date(2024, 7, 1))})
    with pytest.raises(ValueError, match="unknown asset"):
        await optimizer_data.load_aligned_returns(
            session,  # type: ignore[arg-type]
            [
                optimizer_data.FundAssetRef(id=_FUND_A),
                optimizer_data.FundAssetRef(id=_FUND_B),
            ],
            today=_TODAY,
        )


async def test_load_aligned_returns_duplicate_assets_raise() -> None:
    session = _FakeSession({})
    with pytest.raises(ValueError, match="duplicate assets"):
        await optimizer_data.load_aligned_returns(
            session,  # type: ignore[arg-type]
            [
                optimizer_data.FundAssetRef(id=_FUND_A),
                optimizer_data.FundAssetRef(id=_FUND_A),
            ],
            today=_TODAY,
        )


# ── select_universe_funds (candidate resolution) ─────────────────────────────


class _CaptureSession:
    """Returns canned rows and records the compiled SQL of the statement."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.sql: str = ""
        self.bound_params: dict[str, Any] = {}

    async def execute(self, stmt: Any) -> _FakeResult:
        self.sql = str(stmt).lower()
        self.bound_params = dict(stmt.compile().params)
        return _FakeResult(self._rows)


async def test_select_universe_funds_maps_rows_and_joins_history() -> None:
    from app.services import funds_catalog

    rows = [(_FUND_A, "AAA", "Alpha Fund"), (_FUND_B, "BBB", "Beta Fund")]
    session = _CaptureSession(rows)
    # rank_by != aum_usd so the discriminating assertion below cannot be
    # satisfied by the ORDER BY clause alone.
    out = await optimizer_data.select_universe_funds(
        session,  # type: ignore[arg-type]
        funds_catalog.FundFilters(fund_type="etf"),
        rank_by="sharpe_1y",
        rank_dir="desc",
        max_assets=5,
        require_aum=True,
        window_days=730,
        today=_TODAY,
    )
    assert [u.id for u in out] == [_FUND_A, _FUND_B]
    assert out[0].ticker == "AAA"
    assert out[0].name == "Alpha Fund"
    # The history guard joins nav_timeseries (FundNav repointed, Task 4.3);
    # require_aum adds the positive-AUM guard. (">" renders as a bound param, so
    # match the column-comparison prefix.)
    assert "nav_timeseries" in session.sql
    assert "aum_usd is not null" in session.sql
    assert "aum_usd >" in session.sql


async def test_select_universe_funds_always_applies_quality_gates() -> None:
    from app.services import funds_catalog

    session = _CaptureSession([(_FUND_A, "AAA", "Alpha Fund")])
    await optimizer_data.select_universe_funds(
        session,  # type: ignore[arg-type]
        funds_catalog.FundFilters(),
        rank_by="sharpe_1y",
        rank_dir="asc",
        max_assets=5,
        require_aum=False,
        today=_TODAY,
    )
    # The AUM floor and the 3y NAV track-record gate apply UNCONDITIONALLY
    # (they are universe quality gates, not the BL-only require_aum guard).
    assert "aum_usd is not null" in session.sql
    assert "aum_usd >=" in session.sql
    assert optimizer_data.MIN_UNIVERSE_AUM_USD in session.bound_params.values()
    assert "min(nav_timeseries.nav_date)" in session.sql
    cutoff = _TODAY - dt.timedelta(days=optimizer_data.MIN_UNIVERSE_HISTORY_DAYS)
    assert cutoff in session.bound_params.values()
    # 'Unclassified' funds (unknown strategy → no definite asset class) are left
    # out of the optimizable universe, mirroring funds_list_mv's exclusion.
    assert "strategy_label !=" in session.sql
    assert "Unclassified" in session.bound_params.values()
    # 'Unclassified' funds (unknown strategy → no definite asset class) are
    # excluded from the optimizable universe, mirroring funds_list_mv.
    assert "strategy_label !=" in session.sql
    assert "Unclassified" in session.bound_params.values()


async def test_select_universe_funds_applies_nav_quality_gate_fail_open() -> None:
    from app.services import funds_catalog

    session = _CaptureSession([(_FUND_A, "AAA", "Alpha Fund")])
    await optimizer_data.select_universe_funds(
        session,  # type: ignore[arg-type]
        funds_catalog.FundFilters(),
        rank_by="sharpe_1y",
        rank_dir="asc",
        max_assets=5,
        today=_TODAY,
    )
    # NAV data-quality gate (Bug 2): fail-open — a NULL (unscored) fund is KEPT,
    # only an explicit False is excluded.
    assert "nav_quality_ok is null" in session.sql
    assert "nav_quality_ok is true" in session.sql


async def test_select_universe_funds_include_ids_restricts_candidates() -> None:
    from app.services import funds_catalog

    # The session returns only the two requested funds; the discriminating
    # assertion is that the statement carries an instrument_id IN (...) guard
    # bound to exactly those two ids (so a broader filter match is pruned).
    rows = [(_FUND_A, "AAA", "Alpha Fund"), (_FUND_B, "BBB", "Beta Fund")]
    session = _CaptureSession(rows)
    out = await optimizer_data.select_universe_funds(
        session,  # type: ignore[arg-type]
        funds_catalog.FundFilters(fund_type="etf"),
        rank_by="sharpe_1y",
        rank_dir="desc",
        max_assets=50,
        include_ids=[str(_FUND_A), str(_FUND_B)],
        today=_TODAY,
    )
    assert [u.id for u in out] == [_FUND_A, _FUND_B]
    # The IN guard restricts to the pruned set (renders as an IN clause).
    assert "instrument_id in" in session.sql
    assert str(_FUND_A) in str(session.bound_params)
    assert str(_FUND_B) in str(session.bound_params)


async def test_select_universe_funds_without_include_ids_omits_in_guard() -> None:
    from app.services import funds_catalog

    session = _CaptureSession([(_FUND_A, "AAA", "Alpha Fund")])
    await optimizer_data.select_universe_funds(
        session,  # type: ignore[arg-type]
        funds_catalog.FundFilters(),
        rank_by="sharpe_1y",
        rank_dir="asc",
        max_assets=5,
        today=_TODAY,
    )
    # Negative pairing: no pruning list → no instrument_id IN guard.
    assert "instrument_id in" not in session.sql


async def test_select_universe_funds_unknown_rank_column_raises() -> None:
    from app.services import funds_catalog

    session = _CaptureSession([])
    with pytest.raises(funds_catalog.UnknownSortColumnError):
        await optimizer_data.select_universe_funds(
            session,  # type: ignore[arg-type]
            funds_catalog.FundFilters(),
            rank_by="; DROP TABLE funds;--",
            rank_dir="desc",
            max_assets=5,
            today=_TODAY,
        )


# ── window gate removal: default uses the FULL nav_timeseries history ─────────


class _CaptureFundSession:
    """Returns canned rows per fund and records EVERY compiled SQL string."""

    def __init__(self, fund_rows: dict[uuid.UUID, list[tuple[Any, ...]]]) -> None:
        self._fund_rows = fund_rows
        self.sqls: list[str] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.sqls.append(str(stmt).lower())
        params = stmt.compile().params
        for fund_id, rows in self._fund_rows.items():
            if fund_id in params.values():
                return _FakeResult(rows)
        return _FakeResult([])


async def test_load_aligned_returns_default_loads_full_history() -> None:
    """Default (no window_days) loads ALL history — emits no nav_date floor."""
    start = dt.date(2010, 1, 1)
    session = _CaptureFundSession(
        {_FUND_A: _nav_rows(450, start), _FUND_B: _nav_rows(450, start)}
    )
    await optimizer_data.load_aligned_returns(
        session,  # type: ignore[arg-type]
        [optimizer_data.FundAssetRef(id=_FUND_A), optimizer_data.FundAssetRef(id=_FUND_B)],
        today=_TODAY,
    )
    assert session.sqls
    assert all("nav_date >=" not in s for s in session.sqls)


async def test_load_aligned_returns_explicit_window_applies_date_floor() -> None:
    """An explicit window_days still floors nav_date (opt-in narrowing)."""
    start = dt.date(2024, 7, 1)
    session = _CaptureFundSession(
        {_FUND_A: _nav_rows(450, start), _FUND_B: _nav_rows(450, start)}
    )
    await optimizer_data.load_aligned_returns(
        session,  # type: ignore[arg-type]
        [optimizer_data.FundAssetRef(id=_FUND_A), optimizer_data.FundAssetRef(id=_FUND_B)],
        window_days=730,
        today=_TODAY,
    )
    assert any("nav_date >=" in s for s in session.sqls)


async def test_select_universe_funds_default_counts_full_history() -> None:
    from app.services import funds_catalog

    session = _CaptureSession([(_FUND_A, "AAA", "Alpha Fund")])
    await optimizer_data.select_universe_funds(
        session,  # type: ignore[arg-type]
        funds_catalog.FundFilters(),
        rank_by="sharpe_1y",
        rank_dir="desc",
        max_assets=5,
        today=_TODAY,
    )
    # default = full history → the per-fund NAV coverage count has no date floor
    assert "nav_date >=" not in session.sql
