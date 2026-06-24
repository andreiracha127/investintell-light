"""COMBO S4b — two-level regime_aware allocator (proxy -> fund equal-weight).

S4b.1 here: the category-proxy returns loader (``_load_proxy_returns``). Later
sub-sprints add the Level-1 / Level-2 / integration tests. The loader mirrors
``_load_spy_signal``: one indexed eod_prices read per proxy, reindexed onto the
scenario frame; degrade-safe (no session / short history -> omitted)."""

import asyncio
import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_optional_datalake_session
from app.core.db import get_session
from app.main import create_app
from app.optimizer import data as optimizer_data
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
    QUADRANT_POLICIES band (the orthogonal regime envelope is honoured)."""
    from app.services import quadrant_policy as qp

    returns = _proxy_matrix(seed=1)
    wcat = pb._solve_regime_level1(
        _L1_PROXIES, returns, _L1_GROUPS, "moderate", "recovery",
        gamma=4.75, cvar_cap=0.022, gate_state="risk_on",
    )
    assert abs(sum(wcat.values()) - 1.0) < 1e-6
    bands = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["recovery"])
    for proxy, group in zip(_L1_PROXIES, _L1_GROUPS, strict=True):
        lo, hi = bands[group]
        assert wcat.get(proxy, 0.0) <= hi + 1e-6
        assert wcat.get(proxy, 0.0) >= lo - 1e-6


# All 7 sleeves for the momentum tests, so the tight QUADRANT_POLICIES bands have
# genuine slack to tilt (a 5-sleeve subset pins every band at its edge → no slack).
_L1_PROXIES_FULL = ["BIL", "IVV", "GOVT", "XLK", "QAI", "GLD", "FTLS"]
_L1_GROUPS_FULL = [
    "cash", "equity", "fixed_income", "thematic", "alternatives", "gold", "long_short",
]


def test_level1_momentum_tilts_the_winner() -> None:
    """With >=4 risk sleeves the momentum view fires: a sleeve with strong 12-1
    momentum gets MORE weight than the same sleeve with weak momentum (the only
    difference is the trailing trend, not the covariance). view_confidence=1.0
    (risk_on) keeps the view at full strength."""
    base = _proxy_matrix(seed=2, n_cols=7)
    thematic = 3  # the non-saturating risk sleeve under test
    winner = base.copy()
    winner[:, thematic] += 0.003   # strong uptrend -> top of the cross-section
    loser = base.copy()
    loser[:, thematic] -= 0.003    # downtrend -> bottom of the cross-section
    w_win = pb._solve_regime_level1(
        _L1_PROXIES_FULL, winner, _L1_GROUPS_FULL, "aggressive", "expansion",
        gamma=1.90, cvar_cap=0.030, gate_state="risk_on", view_confidence_multiplier=1.0,
    )
    w_lose = pb._solve_regime_level1(
        _L1_PROXIES_FULL, loser, _L1_GROUPS_FULL, "aggressive", "expansion",
        gamma=1.90, cvar_cap=0.030, gate_state="risk_on", view_confidence_multiplier=1.0,
    )
    assert w_win.get("XLK", 0.0) > w_lose.get("XLK", 0.0) + 1e-3


def test_level1_gate_riskoff_zeros_the_view() -> None:
    """The momentum tilt is subordinate to the gate: in risk_off the gate sets
    view_confidence_multiplier=0.0 (mu = equilibrium), so the winner's tilt
    shrinks vs the full-confidence risk_on call."""
    base = _proxy_matrix(seed=2, n_cols=7)
    base[:, 3] += 0.003  # thematic is the momentum winner
    w_on = pb._solve_regime_level1(
        _L1_PROXIES_FULL, base, _L1_GROUPS_FULL, "aggressive", "expansion",
        gamma=1.90, cvar_cap=0.030, gate_state="risk_on", view_confidence_multiplier=1.0,
    )
    w_off = pb._solve_regime_level1(
        _L1_PROXIES_FULL, base, _L1_GROUPS_FULL, "aggressive", "expansion",
        gamma=1.90, cvar_cap=0.030, gate_state="risk_off", view_confidence_multiplier=0.0,
    )
    assert w_on.get("XLK", 0.0) > w_off.get("XLK", 0.0) + 1e-3


def test_level1_falls_back_to_min_cvar(monkeypatch: Any) -> None:
    """If the BL-utility solve is infeasible, Level-1 still returns valid weights
    inside the sleeve bands via the min-CVaR fallback."""
    from app.services import quadrant_policy as qp

    def boom(*_a: Any, **_k: Any):
        raise pb.engine.OptimizerError("forced infeasible")

    monkeypatch.setattr(pb.engine, "solve_bl_utility_cvar", boom)
    returns = _proxy_matrix(seed=3)
    wcat = pb._solve_regime_level1(
        _L1_PROXIES, returns, _L1_GROUPS, "moderate", "recovery",
        gamma=4.75, cvar_cap=0.022, gate_state="risk_on",
    )
    assert abs(sum(wcat.values()) - 1.0) < 1e-6
    bands = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["recovery"])
    for proxy, group in zip(_L1_PROXIES, _L1_GROUPS, strict=True):
        lo, hi = bands[group]
        assert wcat.get(proxy, 0.0) <= hi + 1e-6
        assert wcat.get(proxy, 0.0) >= lo - 1e-6


# ── S4b.3: Level-2 (funds equal-weight per sleeve; proxy-only -> holding) ─────


def test_level2_distributes_category_weight_equal_weight() -> None:
    """Each sleeve's category weight is split EQUALLY across its selected funds —
    no re-optimization, no conviction tilt."""
    wcat = {"IVV": 0.6, "GOVT": 0.4}
    proxy_to_sleeve = {"IVV": "equity", "GOVT": "fixed_income"}
    funds_by_sleeve = {"equity": [0, 1], "fixed_income": [2]}
    fund_w, proxy_holdings = pb._solve_regime_level2(
        wcat, proxy_to_sleeve, funds_by_sleeve, n_assets=4
    )
    assert proxy_holdings == {}
    assert fund_w == pytest.approx([0.3, 0.3, 0.4, 0.0])


def test_level2_three_funds_split_in_thirds() -> None:
    """A sleeve with three funds splits its weight in equal thirds."""
    wcat = {"IVV": 0.9}
    fund_w, proxy_holdings = pb._solve_regime_level2(
        wcat, {"IVV": "equity"}, {"equity": [0, 1, 2]}, n_assets=3
    )
    assert fund_w == pytest.approx([0.3, 0.3, 0.3])
    assert proxy_holdings == {}


def test_level2_proxy_only_sleeve_becomes_a_holding() -> None:
    """A floored sleeve with no fund (gold via GLD) keeps the proxy as a holding,
    not folded into the funds."""
    wcat = {"IVV": 0.7, "GLD": 0.3}
    proxy_to_sleeve = {"IVV": "equity", "GLD": "gold"}
    funds_by_sleeve = {"equity": [0, 1]}  # no gold fund
    fund_w, proxy_holdings = pb._solve_regime_level2(
        wcat, proxy_to_sleeve, funds_by_sleeve, n_assets=2
    )
    assert fund_w == pytest.approx([0.35, 0.35])
    assert proxy_holdings == {"GLD": pytest.approx(0.3)}


def test_level2_total_weight_is_conserved() -> None:
    """Funds + proxy-only holdings together sum to the Level-1 total (1.0)."""
    wcat = {"IVV": 0.5, "GOVT": 0.2, "GLD": 0.2, "FTLS": 0.1}
    proxy_to_sleeve = {
        "IVV": "equity", "GOVT": "fixed_income", "GLD": "gold", "FTLS": "long_short"
    }
    funds_by_sleeve = {"equity": [0], "fixed_income": [1]}  # gold/long_short proxy-only
    fund_w, proxy_holdings = pb._solve_regime_level2(
        wcat, proxy_to_sleeve, funds_by_sleeve, n_assets=2
    )
    total = float(fund_w.sum()) + sum(proxy_holdings.values())
    assert total == pytest.approx(1.0)
    assert proxy_holdings == {"GLD": pytest.approx(0.2), "FTLS": pytest.approx(0.1)}


# ── S4b.4: two-level integration via the optimize route ──────────────────────

# 5 funds: two equity (test equal-weight) + thematic + fixed_income + alternatives
# (>=4 risk sleeves so the momentum view fires; gold/long_short are proxy-only).
_TL_IDS = [uuid.UUID(f"00000000-0000-0000-0000-0000000002{i:02d}") for i in range(5)]
_TL_STRATEGY = {
    _TL_IDS[0]: "Large Blend", _TL_IDS[1]: "Large Growth",       # equity, equity
    _TL_IDS[2]: "Technology",                                    # thematic
    _TL_IDS[3]: "Government Bond",                               # fixed_income
    _TL_IDS[4]: "Real Estate",                                  # alternatives
}
_TL_CLASS = {
    _TL_IDS[0]: "equity", _TL_IDS[1]: "equity", _TL_IDS[2]: "equity",
    _TL_IDS[3]: "fixed_income", _TL_IDS[4]: "alternatives",
}


def _gate(*, state: str = "risk_on", quadrant: str | None = None) -> tb.GateRegimeSnapshot:
    return tb.GateRegimeSnapshot(
        as_of=dt.date(2026, 6, 20), state=state,
        vote_count=2 if state == "risk_off" else 0,
        trend_vote=state == "risk_off", credit_vote=state == "risk_off",
        drawdown_vote=False, dwell_days=30, last_flip=None,
        growth_score=None, inflation_score=None, quadrant=quadrant,
    )


def _async(value: Any):
    async def _f(*_a: Any, **_k: Any) -> Any:
        return value
    return _f


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_optional_datalake_session] = lambda: object()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _stub_two_level_world(
    monkeypatch: Any, *, state: str = "risk_on", quadrant: str = "recovery"
) -> None:
    """Wire the 5-fund universe: aligned returns, taxonomy, gate, and a proxy
    returns loader that serves every requested proxy (so the two-level activates).

    The gate now carries a consumable QUADRANT (orthogonal model, Task 7): a None
    quadrant fails loud (422), so every two-level fixture supplies one."""

    async def fake_load(
        session: Any, assets: list[Any], window_days: int = 730, today: Any = None
    ) -> pd.DataFrame:
        rng = np.random.default_rng(7)
        index = pd.bdate_range("2024-01-02", periods=500)
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.01, 500) for ref in assets}, index=index
        )

    async def fake_strategy(session: Any, fund_ids: list[uuid.UUID]) -> dict:
        return {fid: _TL_STRATEGY.get(fid) for fid in fund_ids}

    async def fake_class(session: Any, fund_ids: list[uuid.UUID]) -> dict:
        return {fid: _TL_CLASS.get(fid) for fid in fund_ids}

    async def fake_proxies(session: Any, tickers: list[str], frame_index: Any, **_k: Any) -> dict:
        rng = np.random.default_rng(13)
        return {t: rng.normal(0.0003, 0.01, len(frame_index)) for t in tickers}

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(pb, "_load_proxy_returns", fake_proxies)
    monkeypatch.setattr(
        tb, "fetch_gate_regime", _async(_gate(state=state, quadrant=quadrant))
    )


def _tl_payload(mandate: str = "moderate") -> dict[str, Any]:
    return {
        "assets": [{"kind": "fund", "id": str(fid)} for fid in _TL_IDS],
        "objective": "regime_aware",
        "mandate": mandate,
        "constraints": {"cap": 1.0},
    }


async def test_two_level_activates_and_exposes_category_weights(monkeypatch: Any) -> None:
    """With live proxies the two-level runs: category_weights (book B) is exposed
    and the class_bands surface the 7-sleeve envelope (gold present)."""
    _stub_two_level_world(monkeypatch)
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 200, resp.text
    diag = resp.json()["diagnostics"]
    assert diag["category_weights"] is not None
    # 7-sleeve envelope (not the 4-class one) -> gold/thematic appear.
    assert "gold" in diag["class_bands"]
    assert "thematic" in diag["class_bands"]


async def test_two_level_injects_gold_proxy_holding(monkeypatch: Any) -> None:
    """gold has no fund (no label maps to GLD) -> the two-level injects GLD as a
    proxy-only holding with positive weight; the book sums to 1."""
    _stub_two_level_world(monkeypatch)
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    tickers = {w["asset"].get("ticker") for w in body["weights"]}
    assert "GLD" in tickers
    gld_w = next(w["weight"] for w in body["weights"] if w["asset"].get("ticker") == "GLD")
    assert gld_w > 0.0
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6


async def test_two_level_funds_in_same_sleeve_are_equal_weight(monkeypatch: Any) -> None:
    """The two equity funds split the equity sleeve weight equally (Level-2 is
    equal-weight, no re-optimization)."""
    _stub_two_level_world(monkeypatch)
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    w0 = next(w["weight"] for w in body["weights"] if w["asset"].get("id") == str(_TL_IDS[0]))
    w1 = next(w["weight"] for w in body["weights"] if w["asset"].get("id") == str(_TL_IDS[1]))
    assert w0 == pytest.approx(w1)
    assert w0 > 0.0


async def test_two_level_without_proxies_fails_loud(monkeypatch: Any) -> None:
    """No live proxies (loader returns {}) -> the two-level can't be built. The
    orthogonal model RETIRES the S4a single-level fallback (Task 7): regime_aware
    that can't be produced is a structured 422 no-trade, never weights."""
    _stub_two_level_world(monkeypatch)
    monkeypatch.setattr(pb, "_load_proxy_returns", _async({}))  # no proxies
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 422, resp.text
    assert "two-level solve could not be built" in resp.text


async def test_two_level_band_state_comes_from_quadrant_not_gate(monkeypatch: Any) -> None:
    """The two-level sleeve bands key off the QUADRANT (the gate only tightens
    CVaR): a risk_off gate with an EXPANSION quadrant uses the EXPANSION sleeve
    bands. The quadrant + gate_state are surfaced orthogonally (combined_regime
    retired)."""
    from app.services import quadrant_policy as qp

    _stub_two_level_world(monkeypatch)
    monkeypatch.setattr(
        tb, "fetch_gate_regime", _async(_gate(state="risk_off", quadrant="expansion"))
    )
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload("moderate"))
    assert resp.status_code == 200, resp.text
    diag = resp.json()["diagnostics"]
    assert diag["quadrant"] == "expansion"          # the quadrant drives the bands
    assert diag["regime_state"] == "risk_off"       # the gate is surfaced separately
    assert diag["combined_regime"] is None          # combined_regime retired (Task 7)
    assert diag["category_weights"] is not None     # the two-level still ran
    expected = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["expansion"])
    assert diag["class_bands"]["equity"] == pytest.approx(list(expected["equity"]))


async def test_two_level_exposes_beta_cap_not_enforced(monkeypatch: Any) -> None:
    """The EffectiveRegimePolicy aggregate portfolio-beta cap is EXPOSED in the
    diagnostics for telemetry — but it is NOT compiled into a constraint (RELEASE
    GATE; Plan C). We assert it is surfaced and equals the per-profile/gate value,
    NOT that the realized portfolio beta is bounded by it."""
    from app.optimizer import gate_overlay as go

    _stub_two_level_world(monkeypatch, state="risk_on", quadrant="recovery")
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload("moderate"))
    assert resp.status_code == 200, resp.text
    diag = resp.json()["diagnostics"]
    # risk_on → identity overlay → beta_cap == the base per-profile cap (moderate).
    assert diag["beta_cap"] == pytest.approx(go.PROFILE_PORTFOLIO_BETA_CAPS["moderate"])


async def test_regime_aware_no_quadrant_fails_loud(monkeypatch: Any) -> None:
    """A gate with NO consumable quadrant fails loud (422 structured error) — the
    orthogonal model NEVER returns weights-with-warnings (spec §31)."""
    _stub_two_level_world(monkeypatch)
    monkeypatch.setattr(
        tb, "fetch_gate_regime", _async(_gate(state="risk_on", quadrant=None))
    )
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 422, resp.text
    assert "QUADRANT_UNAVAILABLE" in resp.text


def test_load_proxy_returns_handles_object_date_index(monkeypatch: Any) -> None:
    """The real datalake frame indexes on datetime.date (object dtype), not
    Timestamp. The loader must not choke on .date() (P0 regression — the
    pd.bdate_range fixtures masked this AttributeError)."""
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(300)]
    index = pd.Index(dates)  # object dtype, exactly like load_aligned_returns
    assert index.dtype == object
    levels = _ascending_levels(len(index))

    seen: list[tuple[Any, Any]] = []

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        seen.append((start, end))
        return [(d, float(p)) for d, p in zip(dates, levels, strict=True)]

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    out = asyncio.run(pb._load_proxy_returns(object(), ["IVV"], index))
    assert set(out) == {"IVV"}
    assert np.isfinite(out["IVV"]).all()
    # Assert the date contract OUTSIDE the loader's try/except, so a regression
    # fails loudly here instead of being swallowed into an empty result.
    assert seen, "loader never queried the DB"
    for start, end in seen:
        assert isinstance(start, dt.date) and not isinstance(start, dt.datetime)
        assert isinstance(end, dt.date) and not isinstance(end, dt.datetime)


def test_load_spy_signal_handles_object_date_index(monkeypatch: Any) -> None:
    """Same P0 regression for the S4a SPY-signal loader."""
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(300)]
    index = pd.Index(dates)
    assert index.dtype == object
    levels = _ascending_levels(len(index))

    seen: list[tuple[Any, Any]] = []

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        seen.append((start, end))
        return [(d, float(p)) for d, p in zip(dates, levels, strict=True)]

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    closes_desc, rets = asyncio.run(pb._load_spy_signal(object(), index))
    assert len(closes_desc) == len(index)
    assert rets is not None and np.isfinite(rets).all()
    assert seen, "loader never queried the DB"
    for start, end in seen:
        assert isinstance(start, dt.date) and not isinstance(start, dt.datetime)
        assert isinstance(end, dt.date) and not isinstance(end, dt.datetime)


async def test_two_level_reached_with_production_object_date_index(monkeypatch: Any) -> None:
    """P0 acceptance: with the REAL session shape (session != None) and the
    REAL index type (datetime.date / object dtype), the dispatch reaches the
    two-level solve instead of dying in _load_proxy_returns. Stubs only the DB
    edge (select_adj_close_rows) and the fund taxonomy."""
    from app.schemas.builder import FundRefIn, OptimizeRequest

    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(500)]
    index = pd.Index(dates)
    assert index.dtype == object

    assets = [FundRefIn(kind="fund", id=fid) for fid in _TL_IDS]
    labels = [pb._ref_key(a) for a in assets]  # derive, never hardcode the format

    def _ticker_levels(ticker: str) -> list[float]:
        # Distinct price path per ticker -> well-conditioned proxy covariance.
        # Identical series would make sigma_ledoit_wolf rank-deficient and the
        # Level-1 solve degenerate. Deterministic seed (no PYTHONHASHSEED dep).
        rng = np.random.default_rng(sum(ord(c) for c in ticker))
        lvl, out = 100.0, []
        for r in rng.normal(0.0003, 0.01, len(index)):
            lvl *= 1.0 + r
            out.append(lvl)
        return out

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        # Type contract is covered by Task 2; here we only prove the dispatch
        # reaches the solve, so no isinstance assertion inside the loader.
        return [(d, float(p)) for d, p in zip(dates, _ticker_levels(ticker), strict=True)]

    async def fake_strategy(session: Any, fund_ids: list) -> dict:
        return {fid: _TL_STRATEGY.get(fid) for fid in fund_ids}

    async def fake_class(session: Any, fund_ids: list) -> dict:
        return {fid: _TL_CLASS.get(fid) for fid in fund_ids}

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)

    payload = OptimizeRequest(
        assets=assets, objective="regime_aware", mandate="moderate"
    )
    result = await pb._solve_regime_two_level(
        object(), assets, labels, index, "expansion", "risk_on", payload
    )
    assert result is not None  # would be None (or raise) before the P0 fix
    total = float(result.fund_weights.sum()) + sum(result.proxy_holdings.values())
    assert abs(total - 1.0) < 1e-6


# ── Task 7: orthogonalize — consume EffectiveRegimePolicy (combined_regime gone) ──

from app.services import quadrant_policy as qp  # noqa: E402


def test_resolve_quadrant_policy_returns_policy_for_known_quadrant() -> None:
    pol = pb._resolve_quadrant_policy("moderate", "recovery")
    assert pol is qp.QUADRANT_POLICIES["moderate"]["recovery"]


def test_resolve_quadrant_policy_raises_on_none_quadrant() -> None:
    with pytest.raises(pb.QuadrantUnavailableError):
        pb._resolve_quadrant_policy("moderate", None)


def test_resolve_quadrant_policy_raises_on_unknown_quadrant() -> None:
    with pytest.raises(pb.QuadrantUnavailableError):
        pb._resolve_quadrant_policy("moderate", "stagflation")


def test_two_level_uses_quadrant_policy_bands(monkeypatch: Any) -> None:
    """The two-level solve must derive its sleeve bands from QUADRANT_POLICIES,
    not band_state_from_quadrant (removed from the builder path). Bands for
    recovery/moderate match policy_bands of that policy."""
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(500)]
    index = pd.Index(dates)
    assets = [pb.FundRefIn(kind="fund", id=fid) for fid in _TL_IDS]
    labels = [pb._ref_key(a) for a in assets]

    def _levels(ticker: str) -> list[float]:
        rng = np.random.default_rng(sum(ord(c) for c in ticker))
        lvl, out = 100.0, []
        for r in rng.normal(0.0003, 0.01, len(index)):
            lvl *= 1.0 + r
            out.append(lvl)
        return out

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        return [(d, float(p)) for d, p in zip(dates, _levels(ticker), strict=True)]

    async def fake_strategy(session: Any, fund_ids: list) -> dict:
        return {fid: _TL_STRATEGY.get(fid) for fid in fund_ids}

    async def fake_class(session: Any, fund_ids: list) -> dict:
        return {fid: _TL_CLASS.get(fid) for fid in fund_ids}

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)

    from app.schemas.builder import OptimizeRequest

    payload = OptimizeRequest(assets=assets, objective="regime_aware", mandate="moderate")
    result = asyncio.run(
        pb._solve_regime_two_level(
            object(), assets, labels, index, "recovery", "risk_on", payload
        )
    )
    assert result is not None
    expected = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["recovery"])
    for sleeve, (lo, hi) in result.sleeve_bands.items():
        assert (lo, hi) == pytest.approx(expected[sleeve])


def test_combined_regime_removed_from_builder_solve_path() -> None:
    """The regime_aware SOLVE path (two-level + Level-1) no longer reads
    combined_regime/band_state_from_quadrant (Task 7) — it consumes
    EffectiveRegimePolicy / QUADRANT_POLICIES instead.

    NOTE: ``_resolve_regime_block_budgets`` (the S4a single-level envelope) and
    ``taa_bands.combined_regime`` itself still exist — their retirement, plus the
    macro route + macro schema that consume combined_regime, is scoped to Task
    8/9. So we assert against the two-level SOLVE source, not the taa_bands
    module (which the macro route still depends on)."""
    import inspect

    src = inspect.getsource(pb._solve_regime_two_level)
    src += inspect.getsource(pb._solve_regime_level1)
    # Assert no CALL into the legacy machinery (docstrings may still name the
    # retired symbols to explain the migration — only code usage is forbidden).
    assert "taa_bands.combined_regime" not in src
    assert "band_state_from_quadrant(" not in src
    assert "profile_sleeve_bands(" not in src

