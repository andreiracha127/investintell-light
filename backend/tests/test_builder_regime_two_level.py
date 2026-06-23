"""COMBO S4b — two-level regime_aware allocator (proxy -> fund equal-weight).

S4b.1 here: the category-proxy returns loader (``_load_proxy_returns``). Later
sub-sprints add the Level-1 / Level-2 / integration tests. The loader mirrors
``_load_spy_signal``: one indexed eod_prices read per proxy, reindexed onto the
scenario frame; degrade-safe (no session / short history -> omitted)."""

import asyncio
from typing import Any

import numpy as np
import pandas as pd

from app.services import portfolio_builder as pb


def _ascending_levels(n: int, start: float = 100.0, drift: float = 0.05) -> list[float]:
    """A gently rising price path (n points)."""
    return [start * (1.0 + drift) ** (k / n) for k in range(n)]


def test_load_proxy_returns_degrades_without_session() -> None:
    """No DB session (test seam) -> empty dict, never raises."""
    index = pd.bdate_range("2024-01-02", periods=300)
    out = asyncio.run(pb._load_proxy_returns(None, ["IVV", "GOVT"], index))
    assert out == {}


def test_load_proxy_returns_empty_index() -> None:
    """An empty frame index -> empty dict."""
    out = asyncio.run(pb._load_proxy_returns(object(), ["IVV"], pd.Index([])))  # type: ignore[arg-type]
    assert out == {}


def test_load_proxy_returns_aligns_each_proxy_to_frame(monkeypatch: Any) -> None:
    """Each proxy's daily returns are reindexed onto the frame -> one row per
    scenario, finite, keyed by ticker."""
    index = pd.bdate_range("2024-01-02", periods=300)
    levels = _ascending_levels(len(index))
    by_ticker = {
        "IVV": [(d.date(), float(p)) for d, p in zip(index, levels, strict=True)],
        "GOVT": [(d.date(), float(p)) for d, p in zip(index, levels, strict=True)],
    }

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        return by_ticker.get(ticker, [])

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    out = asyncio.run(pb._load_proxy_returns(object(), ["IVV", "GOVT"], index))
    assert set(out) == {"IVV", "GOVT"}
    for vec in out.values():
        assert len(vec) == len(index)
        assert np.isfinite(vec).all()


def test_load_proxy_returns_omits_short_history(monkeypatch: Any) -> None:
    """A proxy with too few observations is omitted (not extrapolated)."""
    index = pd.bdate_range("2024-01-02", periods=300)
    full = _ascending_levels(len(index))

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        if ticker == "GOVT":
            # only 10 closes -> well below the minimum coverage
            return [(d.date(), float(p)) for d, p in zip(index[:10], full[:10], strict=True)]
        return [(d.date(), float(p)) for d, p in zip(index, full, strict=True)]

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    out = asyncio.run(pb._load_proxy_returns(object(), ["IVV", "GOVT"], index))
    assert set(out) == {"IVV"}  # GOVT dropped for short history


def test_load_proxy_returns_skips_failed_read(monkeypatch: Any) -> None:
    """A read that raises for one proxy is skipped; others still load."""
    index = pd.bdate_range("2024-01-02", periods=300)
    full = _ascending_levels(len(index))

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        if ticker == "BAD":
            raise RuntimeError("db boom")
        return [(d.date(), float(p)) for d, p in zip(index, full, strict=True)]

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    out = asyncio.run(pb._load_proxy_returns(object(), ["IVV", "BAD"], index))
    assert set(out) == {"IVV"}
