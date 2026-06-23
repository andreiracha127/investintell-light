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
from app.services import taa_bands as tb


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


# ── S4b.2: Level-1 (category weights over proxies) ───────────────────────────

# 5 proxies spanning cash + the 4 risk sleeves (so the momentum view can fire).
_L1_PROXIES = ["BIL", "IVV", "GOVT", "XLK", "QAI"]
_L1_GROUPS = ["cash", "equity", "fixed_income", "thematic", "alternatives"]


def _proxy_matrix(seed: int, n: int = 300, n_cols: int = 5) -> np.ndarray:
    """Plain Gaussian daily-return matrix (T×n_cols), finite, low-vol."""
    return np.random.default_rng(seed).normal(0.0002, 0.01, (n, n_cols))


def test_level1_weights_sum_to_one_within_sleeve_bands() -> None:
    """Level-1 category weights sum to 1 and each sleeve lies within its
    per-profile band (the regime envelope is honoured)."""
    returns = _proxy_matrix(seed=1)
    wcat = pb._solve_regime_level1(
        _L1_PROXIES, returns, _L1_GROUPS, "moderate", "RISK_ON",
        gamma=4.75, cvar_cap=0.022, gate_state="risk_on",
    )
    assert abs(sum(wcat.values()) - 1.0) < 1e-6
    bands = tb.profile_sleeve_bands("moderate", "RISK_ON")
    for proxy, group in zip(_L1_PROXIES, _L1_GROUPS, strict=True):
        lo, hi = bands[group]
        assert wcat.get(proxy, 0.0) <= hi + 1e-6
        assert wcat.get(proxy, 0.0) >= lo - 1e-6


def test_level1_momentum_tilts_the_winner() -> None:
    """With >=4 risk sleeves the momentum view fires: a sleeve with strong 12-1
    momentum gets MORE weight than the same sleeve with weak momentum (the only
    difference is the trailing trend, not the covariance)."""
    base = _proxy_matrix(seed=2)
    thematic = 3  # the non-saturating risk sleeve under test
    winner = base.copy()
    winner[:, thematic] += 0.003   # strong uptrend -> top of the cross-section
    loser = base.copy()
    loser[:, thematic] -= 0.003    # downtrend -> bottom of the cross-section
    w_win = pb._solve_regime_level1(
        _L1_PROXIES, winner, _L1_GROUPS, "aggressive", "RISK_ON",
        gamma=1.90, cvar_cap=0.030, gate_state="risk_on",
    )
    w_lose = pb._solve_regime_level1(
        _L1_PROXIES, loser, _L1_GROUPS, "aggressive", "RISK_ON",
        gamma=1.90, cvar_cap=0.030, gate_state="risk_on",
    )
    assert w_win.get("XLK", 0.0) > w_lose.get("XLK", 0.0) + 1e-3


def test_level1_gate_riskoff_zeros_the_view() -> None:
    """The momentum tilt is subordinate to the gate: in risk_off the view is
    zeroed (mu = equilibrium), so the winner's tilt shrinks vs risk_on."""
    base = _proxy_matrix(seed=2)
    base[:, 3] += 0.003  # thematic is the momentum winner
    w_on = pb._solve_regime_level1(
        _L1_PROXIES, base, _L1_GROUPS, "aggressive", "RISK_ON",
        gamma=1.90, cvar_cap=0.030, gate_state="risk_on",
    )
    w_off = pb._solve_regime_level1(
        _L1_PROXIES, base, _L1_GROUPS, "aggressive", "RISK_ON",
        gamma=1.90, cvar_cap=0.030, gate_state="risk_off",
    )
    assert w_on.get("XLK", 0.0) > w_off.get("XLK", 0.0) + 1e-3


def test_level1_falls_back_to_min_cvar(monkeypatch: Any) -> None:
    """If the BL-utility solve is infeasible, Level-1 still returns valid weights
    inside the sleeve bands via the min-CVaR fallback."""
    def boom(*_a: Any, **_k: Any):
        raise pb.engine.OptimizerError("forced infeasible")

    monkeypatch.setattr(pb.engine, "solve_bl_utility_cvar", boom)
    returns = _proxy_matrix(seed=3)
    wcat = pb._solve_regime_level1(
        _L1_PROXIES, returns, _L1_GROUPS, "moderate", "RISK_ON",
        gamma=4.75, cvar_cap=0.022, gate_state="risk_on",
    )
    assert abs(sum(wcat.values()) - 1.0) < 1e-6
    bands = tb.profile_sleeve_bands("moderate", "RISK_ON")
    for proxy, group in zip(_L1_PROXIES, _L1_GROUPS, strict=True):
        lo, hi = bands[group]
        assert wcat.get(proxy, 0.0) <= hi + 1e-6
        assert wcat.get(proxy, 0.0) >= lo - 1e-6

