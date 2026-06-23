import datetime as dt
import uuid
from typing import Any

import numpy as np
import pytest

from app.optimizer import data as optimizer_data
from app.optimizer.data import _fund_simple_return_series


def _d(n):
    return dt.date(2020, 1, 1) + dt.timedelta(days=n)


def test_simple_series_expm1s_log_return_1d():
    rows = [(_d(0), 10.0, None, "log"), (_d(1), 10.0, 0.01, "log")]
    s = _fund_simple_return_series(rows)
    np.testing.assert_allclose(s.to_numpy(), [np.expm1(0.01)])


def test_simple_series_honors_arithmetic():
    rows = [(_d(0), 10.0, None, "arithmetic"), (_d(1), 10.1, 0.01, "arithmetic")]
    s = _fund_simple_return_series(rows)
    np.testing.assert_allclose(s.to_numpy(), [0.01])


def test_simple_series_guards_glitch_pair():
    # 19.66 -> 0.02 -> 19.68 : two impossible log prints, both zeroed
    rows = [
        (_d(0), 19.66, None, "log"),
        (_d(1), 0.02, -6.89060912, "log"),
        (_d(2), 19.68, 6.891625897, "log"),
    ]
    s = _fund_simple_return_series(rows)
    np.testing.assert_allclose(s.to_numpy(), [0.0, 0.0], atol=1e-12)


def test_simple_series_log_fallback_when_return_1d_null():
    rows = [(_d(0), 10.0, None, "log"), (_d(1), 10.1, None, "log")]
    s = _fund_simple_return_series(rows)
    # fallback computes log(10.1/10.0), then expm1 -> simple 0.01
    np.testing.assert_allclose(s.to_numpy(), [0.1 / 10.0], atol=1e-9)


# --- loader-level equivalence: simple frame == expm1(log frame) on clean data ---

_FUND_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_FUND_B = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
_TODAY = dt.date(2026, 6, 11)


def _clean_log_rows(n: int, start: dt.date, seed: int) -> list[tuple[dt.date, float, float]]:
    """Clean (date, nav, log return_1d) business-day rows, all |r| << 0.40."""
    rng = np.random.default_rng(seed)
    rows: list[tuple[dt.date, float, float]] = []
    nav = 100.0
    day = start
    for _ in range(n):
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        r = float(rng.normal(0.0003, 0.006))
        nav *= float(np.exp(r))
        rows.append((day, nav, r))
        day += dt.timedelta(days=1)
    return rows


class _ConvFakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _ConvFakeSession:
    """Returns canned rows per fund, trimmed to the SELECT arity.

    Stores canonical 4-tuples (date, nav, return_1d, return_type). When the
    compiled query selects ``return_type`` (convention='simple') it returns the
    4-tuples; otherwise (convention='log') it drops the type column.
    """

    def __init__(self, fund_rows: dict[uuid.UUID, list[tuple[Any, ...]]]) -> None:
        self._fund_rows = fund_rows

    async def execute(self, stmt: Any) -> _ConvFakeResult:
        compiled = stmt.compile()
        wants_type = "return_type" in compiled.string
        for fund_id, rows in self._fund_rows.items():
            if fund_id in compiled.params.values():
                if wants_type:
                    return _ConvFakeResult(rows)
                return _ConvFakeResult([r[:3] for r in rows])
        return _ConvFakeResult([])


async def test_simple_frame_is_expm1_of_log_frame() -> None:
    start = dt.date(2024, 7, 1)
    rows_a = [(d, nav, r, "log") for d, nav, r in _clean_log_rows(450, start, 1)]
    rows_b = [(d, nav, r, "log") for d, nav, r in _clean_log_rows(450, start, 2)]
    session = _ConvFakeSession({_FUND_A: rows_a, _FUND_B: rows_b})
    assets = [
        optimizer_data.FundAssetRef(id=_FUND_A),
        optimizer_data.FundAssetRef(id=_FUND_B),
    ]
    log_frame = await optimizer_data.load_aligned_returns(
        session, assets, today=_TODAY, convention="log"  # type: ignore[arg-type]
    )
    simple_frame = await optimizer_data.load_aligned_returns(
        session, assets, today=_TODAY, convention="simple"  # type: ignore[arg-type]
    )
    assert list(simple_frame.columns) == list(log_frame.columns)
    assert list(simple_frame.index) == list(log_frame.index)
    np.testing.assert_allclose(
        simple_frame.to_numpy(), np.expm1(log_frame.to_numpy()), rtol=1e-9
    )
