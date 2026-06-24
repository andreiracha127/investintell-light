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
from app.optimizer import sleeves
from app.services import portfolio_builder as pb
from app.services import quadrant_reader as qr
from app.services import taa_bands as tb
from app.services.quadrant_reader import QuadrantSnapshotRow


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
    _TL_IDS[0]: "Large Blend", _TL_IDS[1]: "Index / Passive",    # same IVV category
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


def _quad_snapshot(quadrant: str | None) -> QuadrantSnapshotRow | None:
    """A consumable §6 QuadrantSnapshotRow (or None for the no-snapshot case).

    The orthogonal model (Task 7 + reader-wiring) reads the quadrant from
    ``quadrant_reader.fetch_quadrant_snapshot`` — NOT from the gate row — so the
    two-level fixtures must supply a consumable snapshot here. ``None`` models the
    'no consumable snapshot' boundary the dispatch turns into QUADRANT_UNAVAILABLE."""
    if quadrant is None:
        return None
    return QuadrantSnapshotRow(
        quadrant=quadrant, candidate_quadrant=quadrant, candidate_confidence=0.85,
        as_of=dt.date(2026, 6, 19),
        available_at=dt.datetime(2026, 6, 19, 12, tzinfo=dt.UTC),
        stale_after=dt.datetime(2026, 6, 30, tzinfo=dt.UTC),
        status_at_compute="valid", model_version=pb.QUADRANT_MODEL_VERSION,
        growth_score=0.3, inflation_score=0.3, transition_pending=False,
    )


def _async(value: Any):
    async def _f(*_a: Any, **_k: Any) -> Any:
        return value
    return _f


def _eff_policy(
    profile: str, quadrant: str, *, state: str = "risk_on", base_cvar: float = 0.025
):
    """Build the cohesive EffectiveRegimePolicy the dispatch now threads into
    ``_solve_regime_two_level`` (one build per request). Mirrors the production wiring:
    a consumable §6 quadrant snapshot + the live gate."""
    from app.services import effective_policy as ep

    return ep.build_effective_policy(
        _quad_snapshot(quadrant), _gate(state=state, quadrant=quadrant),
        profile, base_cvar_limit=base_cvar,
    )


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_optional_datalake_session] = lambda: object()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _stub_two_level_world(
    monkeypatch: Any, *, state: str = "risk_on", quadrant: str | None = "recovery"
) -> None:
    """Wire the 5-fund universe: aligned returns, taxonomy, gate, the §6 quadrant
    reader, and a proxy returns loader that serves every requested proxy (so the
    two-level activates).

    The quadrant now comes from ``quadrant_reader.fetch_quadrant_snapshot`` (the §6
    consumable read), NOT the gate row — so the fixture mocks the reader with a
    consumable snapshot for ``quadrant``. ``quadrant=None`` models 'no consumable
    snapshot' (the dispatch fails loud QUADRANT_UNAVAILABLE → 422)."""

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
    # The quadrant is sourced from the §6 consumable reader, not the gate row.
    monkeypatch.setattr(
        qr, "fetch_quadrant_snapshot", _async(_quad_snapshot(quadrant))
    )
    # N2: pin the regime_aware decision "now" right after the gate fixture's as_of
    # (2026-06-20) so the gate-freshness (max-lag) check sees a FRESH gate regardless
    # of wall-clock. Stale-gate tests override this seam with an older/younger as_of.
    monkeypatch.setattr(
        pb, "_OVERRIDE_DECISION_NOW", dt.datetime(2026, 6, 22, 12, tzinfo=dt.UTC)
    )


def _tl_payload(profile: str = "moderate") -> dict[str, Any]:
    return {
        "assets": [{"kind": "fund", "id": str(fid)} for fid in _TL_IDS],
        "objective": "regime_aware",
        "profile": profile,
        "constraints": {"cap": 1.0},
    }


async def _compile_stub_problem(
    monkeypatch: Any,
    *,
    constraints: dict[str, Any] | None = None,
    universe_policy: str = "complete_macro",
    spy_signal: Any | None = None,
):
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
    monkeypatch.setattr(pb, "_load_spy_signal", spy_signal or _async(([], None)))

    from app.schemas.builder import OptimizeRequest

    payload = OptimizeRequest(
        assets=assets,
        objective="regime_aware",
        profile="moderate",
        constraints=constraints or {},
        universe_policy=universe_policy,
    )
    return await pb._compile_regime_problem(
        object(), None, assets, labels, index,
        _eff_policy("moderate", "recovery"), payload,
    )


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


async def test_two_level_funds_in_same_category_are_equal_weight(monkeypatch: Any) -> None:
    """Two funds in the same canonical category split that category equally."""
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
    """No live proxy history for required fills is a structured 422 no-trade."""
    _stub_two_level_world(monkeypatch)
    monkeypatch.setattr(pb, "_load_proxy_returns", _async({}))  # no proxies
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 422, resp.text
    assert "POLICY_INFEASIBLE" in resp.text
    assert "missing return history for active proxy" in resp.text


async def test_two_level_band_state_comes_from_quadrant_not_gate(monkeypatch: Any) -> None:
    """The two-level sleeve bands key off the QUADRANT (the gate only tightens
    CVaR): a risk_off gate with an EXPANSION quadrant uses the EXPANSION sleeve
    bands. The quadrant comes from the §6 reader (gate quadrant is now irrelevant),
    and quadrant + gate_state are surfaced orthogonally (combined_regime retired)."""
    from app.services import quadrant_policy as qp

    # quadrant=expansion drives BOTH the reader (band source) and the gate row;
    # the risk_off state still only tightens CVaR, never the band selection.
    _stub_two_level_world(monkeypatch, state="risk_off", quadrant="expansion")
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload("moderate"))
    assert resp.status_code == 200, resp.text
    diag = resp.json()["diagnostics"]
    assert diag["quadrant"] == "expansion"          # the quadrant drives the bands
    assert diag["regime_state"] == "risk_off"       # the gate is surfaced separately
    assert "combined_regime" not in diag            # combined_regime field retired (Task 9)
    assert diag["category_weights"] is not None     # the two-level still ran
    expected = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["expansion"])
    assert diag["class_bands"]["equity"] == pytest.approx(list(expected["equity"]))


async def test_two_level_ignores_payload_block_budgets(monkeypatch: Any) -> None:
    """regime_aware DERIVES its sleeve bands from the EffectiveRegimePolicy and
    IGNORES the payload's ``block_budgets``: a payload that demands an equity band of
    [0.0, 0.05] is overridden — the realized class_bands follow the QUADRANT_POLICIES
    policy (recovery/moderate), not the payload. (Re-pins the dropped guard.)"""
    _stub_two_level_world(monkeypatch, state="risk_on", quadrant="recovery")
    payload = _tl_payload("moderate")
    # A payload block budget that would starve equity to [0, 0.05] if regime_aware
    # honoured it (it must NOT — bands come from the policy).
    payload["constraints"]["block_budgets"] = [
        {"asset_class": "equity", "lo": 0.0, "hi": 0.05}
    ]
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=payload)
    assert resp.status_code == 200, resp.text
    diag = resp.json()["diagnostics"]
    expected = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["recovery"])
    # The policy band wins (NOT the payload's [0.0, 0.05]).
    assert diag["class_bands"]["equity"] == pytest.approx(list(expected["equity"]))
    assert expected["equity"][1] > 0.05  # sanity: the policy band genuinely differs


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


async def test_regime_aware_no_consumable_snapshot_fails_loud(monkeypatch: Any) -> None:
    """No consumable §6 quadrant snapshot fails loud (422 structured error) — the
    orthogonal model NEVER returns weights-with-warnings (spec §31). The reader (not
    the gate row) is the quadrant source, so its None is the no-trade boundary."""
    _stub_two_level_world(monkeypatch)
    monkeypatch.setattr(qr, "fetch_quadrant_snapshot", _async(None))
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 422, resp.text
    assert "QUADRANT_UNAVAILABLE" in resp.text


async def test_regime_aware_stale_gate_quadrant_does_not_leak(monkeypatch: Any) -> None:
    """THE adversarial finding: a quadrant populated on the latest ``regime_gate_daily``
    row (the gate-proxy quadrant) must NOT drive sleeve bands when the §6 consumable
    read finds no snapshot. With the gate carrying a quadrant ('expansion') but the
    reader returning None (stale / low-confidence / future-leaked → non-consumable),
    the builder MUST fail loud QUADRANT_UNAVAILABLE (422) — NOT produce weights off the
    bypassed gate quadrant."""
    _stub_two_level_world(monkeypatch)
    # Gate row HAS a quadrant; the §6 read rejects it as non-consumable.
    monkeypatch.setattr(
        tb, "fetch_gate_regime", _async(_gate(state="risk_on", quadrant="expansion"))
    )
    monkeypatch.setattr(qr, "fetch_quadrant_snapshot", _async(None))
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 422, resp.text
    assert "QUADRANT_UNAVAILABLE" in resp.text


async def test_regime_aware_malformed_gate_state_fails_loud(monkeypatch: Any) -> None:
    """A gate row carrying a MALFORMED state (e.g. ``risk-off`` with a hyphen, or a
    drifted ``stale``) must fail loud as a structured 422 GATE_UNAVAILABLE — NEVER a
    silent fall-through to the risk_on identity overlay (full risk envelope). This is
    the §2/§11/§23 fail-loud boundary: the gate never silently increases risk."""
    _stub_two_level_world(monkeypatch)
    monkeypatch.setattr(
        tb, "fetch_gate_regime", _async(_gate(state="risk-off", quadrant="recovery"))
    )
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 422, resp.text
    assert "GATE_UNAVAILABLE" in resp.text


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
        assets=assets, objective="regime_aware", profile="moderate"
    )
    result = await pb._solve_regime_two_level(
        object(), assets, labels, index, _eff_policy("moderate", "expansion"), payload
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
    monkeypatch.setattr(pb, "_load_spy_signal", _async(([], None)))

    from app.schemas.builder import OptimizeRequest

    payload = OptimizeRequest(assets=assets, objective="regime_aware", profile="moderate")
    result = asyncio.run(
        pb._solve_regime_two_level(
            object(), assets, labels, index, _eff_policy("moderate", "recovery"), payload
        )
    )
    assert result is not None
    expected = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["recovery"])
    for sleeve, (lo, hi) in result.sleeve_bands.items():
        assert (lo, hi) == pytest.approx(expected[sleeve])


def test_complete_macro_adds_fixed_income_categories_for_capacity(
    monkeypatch: Any,
) -> None:
    """FI is a sleeve, not one GOVT category. With the default 25% instrument cap
    and a moderate/recovery FI floor above 25%, complete_macro must activate
    another authorized FI category proxy instead of declaring the policy
    infeasible."""
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
    monkeypatch.setattr(pb, "_load_spy_signal", _async(([], None)))

    from app.schemas.builder import OptimizeRequest

    payload = OptimizeRequest(assets=assets, objective="regime_aware", profile="moderate")
    problem, active, _ = asyncio.run(
        pb._compile_regime_problem(
            object(), None, assets, labels, index,
            _eff_policy("moderate", "recovery"), payload,
        )
    )
    fi_categories = [
        cid
        for cid, sleeve in zip(
            problem.category_ids, problem.category_sleeve_ids, strict=True
        )
        if sleeve == "fixed_income"
    ]
    assert "FIXED_INCOME_US_GOVT/GOVT" in fi_categories
    assert len(fi_categories) >= 2
    lqd_idx = next(i for i, item in enumerate(active) if item.label == "equity:LQD")
    assert problem.daily_returns.shape[1] == len(active)
    assert np.isfinite(problem.daily_returns[:, lqd_idx]).all()


def test_complete_macro_does_not_add_fi_proxy_when_capacity_is_enough(
    monkeypatch: Any,
) -> None:
    problem, active, _ = asyncio.run(
        _compile_stub_problem(monkeypatch, constraints={"cap": 1.0})
    )
    assert "FIXED_INCOME_US_GOVT/GOVT" in problem.category_ids
    assert "FIXED_INCOME_IG_CREDIT/LQD" not in problem.category_ids
    assert all(item.label != "equity:LQD" for item in active)


def test_strict_missing_required_sleeves_fails_loud(monkeypatch: Any) -> None:
    with pytest.raises(pb.MissingRequiredSleevesError, match="MISSING_REQUIRED_SLEEVES"):
        asyncio.run(
            _compile_stub_problem(
                monkeypatch, constraints={"cap": 1.0}, universe_policy="strict"
            )
        )


def test_min_weight_compiles_per_final_instrument_not_category(
    monkeypatch: Any,
) -> None:
    problem, _active, _ = asyncio.run(
        _compile_stub_problem(monkeypatch, constraints={"cap": 1.0, "min_weight": 0.02})
    )
    equity_idx = problem.category_ids.index("EQUITY_US_LARGE/IVV")
    floor_rows = [
        lc
        for lc in problem.linear_constraints
        if lc.label.startswith("instrument_floor:fund:")
        and lc.coef[equity_idx] > 0
    ]
    assert len(floor_rows) == 2
    assert [row.lo for row in floor_rows] == [0.02, 0.02]
    assert [row.coef[equity_idx] for row in floor_rows] == pytest.approx([0.5, 0.5])


def test_primary_and_fallback_receive_identical_compiled_constraints(
    monkeypatch: Any,
) -> None:
    problem, _active, _ = asyncio.run(
        _compile_stub_problem(monkeypatch, constraints={"cap": 1.0})
    )
    pb._preflight_compiled_problem(problem)
    seen: dict[str, list[str]] = {}

    def fake_primary(*_args: Any, **kwargs: Any):
        seen["primary"] = [lc.label for lc in kwargs["linear"]]
        raise pb.engine.OptimizerError("force fallback")

    def fake_fallback(*args: Any, **kwargs: Any):
        seen["fallback"] = [lc.label for lc in kwargs["linear"]]
        n = args[0].shape[1]
        return np.full(n, 1.0 / n), "optimal"

    monkeypatch.setattr(pb.engine, "solve_bl_utility_cvar", fake_primary)
    monkeypatch.setattr(pb.engine, "solve_min_cvar", fake_fallback)
    pb._solve_compiled_regime_problem(
        problem,
        gamma=4.75,
        gate_state="risk_on",
        view_confidence_multiplier=1.0,
    )
    assert seen["primary"] == seen["fallback"]
    assert problem.signature


def test_beta_cap_compiles_when_spy_signal_is_available(monkeypatch: Any) -> None:
    spy = np.linspace(-0.01, 0.01, 500)

    async def fake_spy_signal(*_args: Any, **_kwargs: Any):
        return [100.0] * 500, spy

    problem, _active, _ = asyncio.run(
        _compile_stub_problem(
            monkeypatch, constraints={"cap": 1.0}, spy_signal=fake_spy_signal
        )
    )
    beta_rows = [
        lc for lc in problem.linear_constraints if lc.label == "portfolio_beta_cap"
    ]
    assert len(beta_rows) == 1
    assert beta_rows[0].hi == pytest.approx(_eff_policy("moderate", "recovery").beta_cap)


def test_post_verify_constraint_violation_fails_loud(monkeypatch: Any) -> None:
    problem, _active, _ = asyncio.run(
        _compile_stub_problem(monkeypatch, constraints={"cap": 1.0})
    )
    with pytest.raises(pb.ConstraintViolationError, match="CONSTRAINT_VIOLATION"):
        pb._post_verify_compiled_solution(problem, np.zeros(len(problem.category_ids)))


# ── N1: enforce risk_assets_cap / defensive_floor in the Level-1 solve ───────


def _riskasset_momentum_matrix(seed: int, groups: list[str], n: int = 400) -> np.ndarray:
    """A return matrix that gives the RISK sleeves (equity/thematic) a strong
    uptrend so an unconstrained max-utility solve WANTS to load them up to the
    per-sleeve band-hi (which exceeds the risk_off overlay cap). The defensive
    sleeves drift flat. This makes the aggregate-cap breach REAL, not theoretical."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0, 0.008, (n, len(groups)))
    for k, g in enumerate(groups):
        if g in ("equity", "thematic"):
            base[:, k] += 0.0020   # strong risk-asset uptrend → solver leans in
    return base


def test_level1_enforces_risk_assets_cap_aggregate() -> None:
    """N1: in risk_off the equity+thematic per-sleeve band-his (aggressive/expansion:
    0.308 + 0.082 = 0.39) EXCEED the overlay risk_assets_cap (0.35), while the
    band-LOWS (0.29) are below it (feasible). The Level-1 solve MUST honour the
    AGGREGATE cap equity+thematic ≤ risk_assets_cap, not just the per-sleeve bands —
    even when momentum wants the risk sleeves at their highs.
    """
    from app.services import effective_policy as ep

    groups = list(qp.STRUCTURAL_SLEEVES)
    proxies = [sleeves.GROUP_BENCHMARK[g] for g in groups]
    returns = _riskasset_momentum_matrix(seed=11, groups=groups)
    eff = ep.build_effective_policy(
        _quad_snapshot("expansion"), _gate(state="risk_off", quadrant="expansion"),
        "aggressive", base_cvar_limit=0.030,
    )
    assert eff.risk_assets_cap == pytest.approx(0.35)  # 0.42 base - 0.07 risk_off
    wcat = pb._solve_regime_level1(
        proxies, returns, groups, "aggressive", "expansion",
        gamma=1.90, cvar_cap=eff.cvar_limit, gate_state="risk_off",
        view_confidence_multiplier=eff.bl_view_confidence_multiplier,
        risk_assets_cap=eff.risk_assets_cap, defensive_floor=eff.defensive_floor,
    )
    equity = wcat.get(sleeves.GROUP_BENCHMARK["equity"], 0.0)
    thematic = wcat.get(sleeves.GROUP_BENCHMARK["thematic"], 0.0)
    assert equity + thematic <= eff.risk_assets_cap + 1e-6
    defensive = sum(
        wcat.get(sleeves.GROUP_BENCHMARK[g], 0.0)
        for g in ("cash", "fixed_income", "gold", "long_short")
    )
    assert defensive >= eff.defensive_floor - 1e-6


async def test_two_level_realized_weights_honour_risk_assets_cap(monkeypatch: Any) -> None:
    """N1 end-to-end: a risk_off aggressive/expansion request returns realized
    category weights with equity+thematic ≤ risk_assets_cap (0.35), NOT the
    per-sleeve-band sum (0.39). The endpoint no longer advertises a cap it does
    not enforce."""
    _stub_two_level_world(monkeypatch, state="risk_off", quadrant="expansion")
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload("aggressive"))
    assert resp.status_code == 200, resp.text
    diag = resp.json()["diagnostics"]
    cw = diag["category_weights"]
    assert cw is not None
    risk = cw.get("equity", 0.0) + cw.get("thematic", 0.0)
    assert risk <= 0.35 + 1e-6, f"equity+thematic {risk} breached risk_assets_cap 0.35"


def test_level1_infeasible_policy_caps_fail_loud() -> None:
    """N1: if the aggregate caps are structurally unsatisfiable (a risk_assets_cap
    BELOW the sum of the risk sleeves' band-LOWS, so equity+thematic can never be
    that small), Level-1 fails loud with a POLICY_INFEASIBLE-style error — NEVER a
    silently relaxed solve (freeze §1.7/§28/§31)."""
    groups = list(qp.STRUCTURAL_SLEEVES)
    proxies = [sleeves.GROUP_BENCHMARK[g] for g in groups]
    returns = _riskasset_momentum_matrix(seed=12, groups=groups)
    # aggressive/recovery risk-sleeve band-lows: equity 0.29 + thematic 0.07 = 0.36.
    # A cap of 0.10 forces equity+thematic ≤ 0.10 < 0.36 → infeasible.
    with pytest.raises(pb.engine.OptimizerError):
        pb._solve_regime_level1(
            proxies, returns, groups, "aggressive", "recovery",
            gamma=1.90, cvar_cap=0.030, gate_state="risk_off",
            view_confidence_multiplier=0.0,
            risk_assets_cap=0.10, defensive_floor=0.28,
        )


async def test_two_level_infeasible_caps_return_422(monkeypatch: Any) -> None:
    """N1: a deliberately-infeasible eff_policy (risk_assets_cap below the risk
    sleeves' band-low sum) makes the two-level solve infeasible → structured 422
    (no weights). Monkeypatch the eff_policy cap to force the infeasibility."""
    _stub_two_level_world(monkeypatch, state="risk_off", quadrant="recovery")
    real_build = pb.effective_policy.build_effective_policy

    def _infeasible_build(*a: Any, **k: Any):
        import dataclasses
        eff = real_build(*a, **k)
        return dataclasses.replace(eff, risk_assets_cap=0.02)

    monkeypatch.setattr(
        pb.effective_policy, "build_effective_policy", _infeasible_build
    )
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload("aggressive"))
    assert resp.status_code == 422, resp.text
    assert "POLICY_INFEASIBLE" in resp.text


# ── N2: gate freshness / max-lag on the regime_aware path ────────────────────


def test_gate_business_day_lag_counts_weekdays() -> None:
    """The lag helper counts BUSINESS days (Mon–Fri) strictly after as_of up to the
    decision date; same/next-business-day → 0/1, a weekend does not inflate it, and a
    future-dated gate returns a NEGATIVE lag (no clamp) so the caller can reject it
    explicitly as GATE_UNAVAILABLE — a future snapshot is NOT available at decision
    time and must never silently read as fresh (freeze §8/§11)."""
    fri = dt.date(2026, 6, 19)   # Friday
    # same day → 0
    assert pb._gate_business_day_lag(fri, dt.datetime(2026, 6, 19, tzinfo=dt.UTC)) == 0
    # the following Monday is ONE business day later (Sat/Sun skipped)
    assert pb._gate_business_day_lag(fri, dt.datetime(2026, 6, 22, tzinfo=dt.UTC)) == 1
    # one trading week later → 5
    assert pb._gate_business_day_lag(fri, dt.datetime(2026, 6, 26, tzinfo=dt.UTC)) == 5
    # future-dated as_of → NEGATIVE lag (no clamp): decision now is the Thursday
    # BEFORE the as_of Friday, so the true business-day gap is -1.
    assert pb._gate_business_day_lag(fri, dt.datetime(2026, 6, 18, tzinfo=dt.UTC)) == -1


async def test_regime_aware_stale_gate_fails_loud(monkeypatch: Any) -> None:
    """N2 (THE finding): a gate snapshot whose ``as_of`` exceeds
    GATE_MAX_LAG_BUSINESS_DAYS of the decision time (a stalled gate worker) must fail
    loud as a structured 422 GATE_UNAVAILABLE — NEVER silently consumed as fresh
    (freeze §11). Decision now = 2026-06-22; gate as_of = 2026-05-15 is far beyond the
    5-business-day lag."""
    _stub_two_level_world(monkeypatch, state="risk_on", quadrant="recovery")
    stale = tb.GateRegimeSnapshot(
        as_of=dt.date(2026, 5, 15), state="risk_on",  # ~26 business days stale
        vote_count=0, trend_vote=False, credit_vote=False, drawdown_vote=False,
        dwell_days=30, last_flip=None, growth_score=None, inflation_score=None,
        quadrant="recovery",
    )
    monkeypatch.setattr(tb, "fetch_gate_regime", _async(stale))
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 422, resp.text
    assert "GATE_UNAVAILABLE" in resp.text
    assert "stale" in resp.text.lower()


async def test_regime_aware_future_gate_fails_loud(monkeypatch: Any) -> None:
    """N2 (adversarial fix): a gate snapshot whose ``as_of`` is dated AFTER the
    decision time (a worker date bug / bad ingest) must fail loud as a structured 422
    GATE_UNAVAILABLE — a future snapshot is NOT available at the decision time and must
    NEVER silently read as fresh (freeze §8/§11). Decision now = 2026-06-22; gate
    as_of = 2026-06-25 is three days in the future. This rejection happens BEFORE the
    stale-lag check (the future date can no longer clamp to lag 0)."""
    _stub_two_level_world(monkeypatch, state="risk_on", quadrant="recovery")
    future = tb.GateRegimeSnapshot(
        as_of=dt.date(2026, 6, 25), state="risk_on",  # +3 days vs decision now
        vote_count=0, trend_vote=False, credit_vote=False, drawdown_vote=False,
        dwell_days=30, last_flip=None, growth_score=None, inflation_score=None,
        quadrant="recovery",
    )
    monkeypatch.setattr(tb, "fetch_gate_regime", _async(future))
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 422, resp.text
    assert "GATE_UNAVAILABLE" in resp.text
    assert "future" in resp.text.lower()


async def test_regime_aware_fresh_gate_reaches_solve(monkeypatch: Any) -> None:
    """N2: a gate whose ``as_of`` is within the max-lag (here the next business day
    before the pinned decision now) is consumed normally and the two-level solve
    runs (weights returned, category_weights exposed)."""
    _stub_two_level_world(monkeypatch, state="risk_on", quadrant="recovery")
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 200, resp.text
    assert resp.json()["diagnostics"]["category_weights"] is not None


async def test_regime_aware_gate_at_max_lag_boundary_is_fresh(monkeypatch: Any) -> None:
    """N2 boundary: a gate exactly GATE_MAX_LAG_BUSINESS_DAYS old is still fresh
    (the predicate is lag <= max-lag). as_of 2026-06-15 (Mon) vs decision now
    2026-06-22 (Mon) = 5 business days = the seed limit."""
    _stub_two_level_world(monkeypatch, state="risk_on", quadrant="recovery")
    boundary = tb.GateRegimeSnapshot(
        as_of=dt.date(2026, 6, 15), state="risk_on",
        vote_count=0, trend_vote=False, credit_vote=False, drawdown_vote=False,
        dwell_days=30, last_flip=None, growth_score=None, inflation_score=None,
        quadrant="recovery",
    )
    assert pb._gate_business_day_lag(
        boundary.as_of, dt.datetime(2026, 6, 22, 12, tzinfo=dt.UTC)
    ) == pb.GATE_MAX_LAG_BUSINESS_DAYS
    monkeypatch.setattr(tb, "fetch_gate_regime", _async(boundary))
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=_tl_payload())
    assert resp.status_code == 200, resp.text


def test_combined_regime_removed_from_builder_solve_path() -> None:
    """The regime_aware SOLVE path (two-level + Level-1) no longer reads
    combined_regime/band_state_from_quadrant (Task 7) — it consumes
    EffectiveRegimePolicy / QUADRANT_POLICIES instead.

    Task 8 also RETIRED the legacy helpers themselves: ``_resolve_regime_block_budgets``
    / ``_solve_regime_motor`` from the builder and ``combined_regime`` /
    ``effective_class_bands`` / ``goldfix_target`` / ``band_state_from_quadrant`` /
    ``profile_sleeve_bands`` from ``taa_bands``. This test now asserts BOTH: no call
    in the two-level solve source AND the symbols' absence from both modules."""
    import inspect

    from app.services import taa_bands

    src = inspect.getsource(pb._solve_regime_two_level)
    src += inspect.getsource(pb._solve_regime_level1)
    # Assert no CALL into the legacy machinery (docstrings may still name the
    # retired symbols to explain the migration — only code usage is forbidden).
    assert "taa_bands.combined_regime" not in src
    assert "band_state_from_quadrant(" not in src
    assert "profile_sleeve_bands(" not in src

    # Task 8: the retired symbols no longer exist on either module.
    for name in (
        "combined_regime", "effective_class_bands", "goldfix_target",
        "band_state_from_quadrant", "profile_sleeve_bands",
        "normalized_profile_centers", "DEFAULT_TAA_BANDS", "SLEEVE_GROUPS",
    ):
        assert not hasattr(taa_bands, name), f"taa_bands.{name} should be retired"
    for name in (
        "_resolve_regime_block_budgets", "_solve_regime_motor",
        "_fund_class_columns", "_regime_sleeve_groups", "_COMBO_BAND_CLASSES",
    ):
        assert not hasattr(pb, name), f"portfolio_builder.{name} should be retired"
