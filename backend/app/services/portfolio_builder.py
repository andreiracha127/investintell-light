"""Portfolio builder service (F8.3/F8.4): optimize weights over a mixed
fund/equity universe, optionally tilted by Black-Litterman views.

Flow (dispatch F8 §3, research doc 2026-06-11):
1. load aligned daily returns (funds: fund_nav; equities: eod_prices);
2. Σ = annualized Ledoit-Wolf shrinkage;
3. with views (or ``bl_utility``): w_mkt from real AUM → π = δΣw_mkt →
   (P, Q, Ω-Idzorek) → posterior (μ_BL, Σ_BL);
4. objective:
   - ``min_cvar`` (product default): raw scenarios; with views, scenarios are
     re-centered on μ_BL and the equilibrium return π·w_mkt becomes the floor;
   - ``bl_utility``: max μᵀw − (δ/2)wᵀΣw with μ = μ_BL (or π with zero views);
   - μ-free objectives (equal_weight/min_vol/erc/max_diversification) ignore
     views in the OBJECTIVE but still report μ_BL diagnostics when given.
5. response: weights + in-sample expectations + diagnostics.

In-sample CVaR of the proposal is computed from the RAW scenarios (never the
re-centered ones) with the EXACT Rockafellar–Uryasev estimator
(``app.analytics.realized_cvar``, alpha=0.95) — the same objective
``engine.solve_min_cvar`` minimizes — so the reported figure is consistent
with how the weights were chosen.

Error contract: every domain failure raises ``BuilderError`` (→ 422 with the
message verbatim); solver failures (``OptimizerError``) bubble as 422 too.

AUM rule (fail-loud, dispatch F8.4): views/bl_utility require a known positive
AUM for EVERY asset in the universe. Equities have no market cap in the
builder yet → any equity in a views request is rejected; funds with NULL AUM
are rejected with the explicit list. The caller decides what to exclude.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import realized_cvar
from app.optimizer import black_litterman as bl
from app.optimizer import data as optimizer_data
from app.optimizer import engine, momentum_view, sleeves
from app.optimizer import selection as optimizer_selection
from app.optimizer.dates import coerce_date
from app.optimizer.mandate import (
    normalise_mandate,
    resolve_cvar_limit,
    resolve_delta,
    resolve_gamma,
)
from app.schemas.builder import (
    AbsoluteViewIn,
    AssetRefIn,
    BlockBudgetIn,
    DiagnosticsOut,
    EquityRefIn,
    ExcludedFundOut,
    ExpectedOut,
    FundRefIn,
    OptimizeRequest,
    OptimizeResponse,
    SelectionDiagnosticsOut,
    UniverseSpecIn,
    ViewConsistencyOut,
    ViewIn,
    WeightOut,
)
from app.services import (
    effective_policy,
    funds_catalog,
    lookthrough_exposure,
    quadrant_policy,
    quadrant_reader,
    taa_bands,
)
from app.services._series import select_adj_close_rows

# The macro-quadrant model the A2 worker materializes into ``regime_quadrant_snapshot``
# (worker ``MODEL_VERSION_MACRO``). The §6 consumable read filters on this version, so
# regime_aware only ever consumes the OFFICIAL quadrant model (freeze §6/§8).
QUADRANT_MODEL_VERSION = "macro_quadrant_us_v1"

# Test seam: when set, overrides the regime state read (bypasses the data-lake).
_OVERRIDE_REGIME_STATE: str | None = None


class BuilderError(ValueError):
    """Domain failure in the builder — mapped verbatim to HTTP 422."""


# Display labels (ticker, name) for a fund label key — only the universe path
# resolves them; the explicit-list path leaves them None (the client knows).
_LabelMap = dict[str, tuple[str | None, str]]


def humanize_error(detail: str) -> str:
    """Prepend an actionable hint for known-technical optimizer failures.

    Fail-loud is preserved: the original message is always kept verbatim (in
    parentheses) so nothing is masked. Messages that are already actionable
    (insufficient history, missing AUM, view errors) pass through unchanged.
    """
    low = detail.lower()
    if "infeasible" in low or "unbounded" in low:
        # Covers BOTH the pre-solve feasibility checks (cap×n<1, min_weight×n>1)
        # and a non-'optimal' CVXPY status. Remedies are phrased for both paths
        # (in universe mode the user did not hand-pick the assets).
        return (
            "No allocation satisfies these constraints — raise the cap per "
            "asset, lower any minimum weight, or widen the asset set (more "
            f"tickers, or a larger universe / higher max funds) ({detail})"
        )
    if "nan/inf" in low or "weights sum to" in low:
        return (
            "The optimizer could not converge on a stable allocation — some "
            "assets may have degenerate history in this window; widen the "
            f"window or drop the affected assets ({detail})"
        )
    return detail


# Default tightening applied to the CVaR limit when the credit regime is
# risk_off (halve the tolerated tail loss). Surfaced as a constant so the
# route/tests can inspect it.
DEFAULT_RISK_OFF_CVAR_FACTOR = 0.5


def regime_cvar_multiplier(state: str | None, *, risk_off_factor: float) -> float:
    """Multiplier applied to the CVaR limit given the credit-regime state.

    ``risk_off`` -> ``risk_off_factor`` (must be in (0, 1] to TIGHTEN the cap);
    any other state (risk_on / None / unknown) -> 1.0 (no change). Pure."""
    if not 0 < risk_off_factor <= 1:
        raise ValueError(f"risk_off_factor must be in (0, 1], got {risk_off_factor}")
    return risk_off_factor if state == "risk_off" else 1.0


def apply_regime_cvar_limit(
    base_limit: float, state: str | None, *, risk_off_factor: float
) -> float:
    """Effective CVaR limit = base × regime multiplier."""
    return base_limit * regime_cvar_multiplier(state, risk_off_factor=risk_off_factor)


# ── Structured regime_aware errors (spec §31) — all map to HTTP 422 ──────────
# The orthogonal builder consumes ``EffectiveRegimePolicy`` (decision B): a
# regime_aware request that cannot produce a consumable quadrant/gate/policy
# fails LOUD as one of these (no weights-with-warnings, no None→default).


class QuadrantUnavailableError(BuilderError):
    """regime_aware requested but no consumable quadrant (spec §31)."""


class GateUnavailableError(BuilderError):
    """regime_aware requested but no consumable gate (spec §31)."""


class PolicyNotFoundError(BuilderError):
    """No QuadrantPolicy for this profile×quadrant (spec §31)."""


def _as_builder_error(exc: effective_policy.EffectivePolicyError) -> BuilderError:
    """Map a policy-core ``EffectivePolicyError`` to the matching structured
    ``BuilderError`` (→ 422) by message prefix (spec §31).

    ``QUADRANT_UNAVAILABLE``/``UNKNOWN_PROFILE`` → ``QuadrantUnavailableError`` (the
    default); ``GATE_UNAVAILABLE`` → ``GateUnavailableError``; ``POLICY_NOT_FOUND``
    → ``PolicyNotFoundError``. The original message (with its structured prefix) is
    preserved verbatim so nothing is masked.
    """
    msg = str(exc)
    if msg.startswith("GATE_UNAVAILABLE"):
        return GateUnavailableError(msg)
    if msg.startswith("POLICY_NOT_FOUND"):
        return PolicyNotFoundError(msg)
    return QuadrantUnavailableError(msg)


def _resolve_quadrant_policy(
    profile: str, quadrant: str | None
) -> quadrant_policy.QuadrantPolicy:
    """Load the ``QuadrantPolicy`` for a profile×quadrant, fail-loud (spec §31).

    A None/unknown quadrant is QUADRANT_UNAVAILABLE (never falls back to a default
    quadrant — spec §1.2). A missing policy for a valid quadrant is POLICY_NOT_FOUND.
    Kept as a thin helper for ``_solve_regime_level1`` (called standalone); the
    dispatch path prefers ``effective_policy.build_effective_policy``.
    """
    if quadrant is None or quadrant not in quadrant_policy.QUADRANTS:
        raise QuadrantUnavailableError(
            f"regime_aware: no consumable quadrant (got {quadrant!r})"
        )
    by_quadrant = quadrant_policy.QUADRANT_POLICIES.get(profile)
    if by_quadrant is None or quadrant not in by_quadrant:
        raise PolicyNotFoundError(
            f"regime_aware: no policy for profile {profile!r} quadrant {quadrant!r}"
        )
    return by_quadrant[quadrant]


def _to_data_ref(ref: FundRefIn | EquityRefIn) -> optimizer_data.AssetRef:
    if isinstance(ref, FundRefIn):
        return optimizer_data.FundAssetRef(id=ref.id)
    return optimizer_data.EquityAssetRef(ticker=ref.ticker.upper())


def _ref_key(ref: FundRefIn | EquityRefIn) -> str:
    return _to_data_ref(ref).label


# Minimum SPY closes for a usable market-stress signal: ``market_stress`` reads
# a 63-day trailing high, so anything below 64 closes scores a flat 0.0 (no
# stress). Below this we degrade to the in-universe proxy / flat cap.
_MIN_SPY_SIGNAL_OBS = 64


async def _load_spy_signal(
    session: AsyncSession | None,
    frame_index: "pd.Index",
) -> tuple[list[float], np.ndarray | None]:
    """Load SPY as a SIGNAL series from ``eod_prices`` over the opt window.

    Returns ``(spy_closes_desc, spy_returns_aligned)`` where ``spy_closes_desc``
    is the NEWEST-FIRST SPY adjusted-close level series (for
    ``taa_bands.market_stress``) and ``spy_returns_aligned`` is the SPY daily
    return vector REINDEXED onto ``frame_index`` (row-aligned with the scenario
    matrix, for ``taa_bands.asset_betas``).

    SPY's full history lives in ``eod_prices`` (1993→) independent of the traded
    universe, so this activates the vol/beta overlays for ANY universe. One
    indexed read over the window — a local DB read on the request path, NOT the
    Tiingo external-API latency concern. Degrade-safe: returns ``([], None)``
    when the session is absent (test seam / no DB), the read fails, or fewer
    than ``_MIN_SPY_SIGNAL_OBS`` closes come back — the caller then falls back to
    the in-universe proxy / flat cap. Never raises.
    """
    if session is None or len(frame_index) == 0:
        return [], None
    start = coerce_date(frame_index.min())
    end = coerce_date(frame_index.max())
    try:
        rows = await select_adj_close_rows(session, "SPY", start, end)
    except Exception:
        return [], None
    if len(rows) < _MIN_SPY_SIGNAL_OBS:
        return [], None
    spy = pd.Series(
        [float(c) for _d, c in rows],
        index=pd.DatetimeIndex([pd.Timestamp(d) for d, _c in rows]),
    ).sort_index()
    # Newest-first close levels for market_stress (63d-drawdown).
    closes_desc = [float(x) for x in spy.to_numpy(dtype=float)[::-1]]
    # SPY daily returns reindexed onto the scenario rows so betas align with the
    # asset return columns. Reindex to the frame's trading days; the rare missing
    # SPY day is bridged so the vector length matches the scenario rows exactly.
    spy_ret = spy.pct_change().reindex(frame_index).ffill().bfill()
    returns_aligned = spy_ret.to_numpy(dtype=float)
    if not np.isfinite(returns_aligned).all():
        return closes_desc, None
    return closes_desc, returns_aligned


# A proxy must cover at least ~1y so the 12-1 momentum signal (252d lookback) is
# meaningful; below this the proxy is omitted (the sleeve falls back / drops out).
_MIN_PROXY_OBS = 252


async def _load_proxy_returns(
    session: AsyncSession | None,
    tickers: list[str],
    frame_index: "pd.Index",
    *,
    min_obs: int = _MIN_PROXY_OBS,
) -> dict[str, np.ndarray]:
    """Load each category-proxy ETF's daily returns from ``eod_prices``, reindexed
    onto ``frame_index`` (row-aligned with the scenario matrix) — the Level-1
    instrument for the ``regime_aware`` two-level allocator.

    Generalizes ``_load_spy_signal`` to N proxies: one indexed read per ticker
    over the optimization window. Returns ``{ticker: returns_vector}`` (length ==
    ``len(frame_index)``); a proxy is OMITTED when the session is absent, the read
    fails, fewer than ``min_obs`` closes come back, or the reindexed returns are
    non-finite. Degrade-safe (never raises): an empty result tells the caller to
    fall back to the single-level S4a path.
    """
    if session is None or len(frame_index) == 0:
        return {}
    start = coerce_date(frame_index.min())
    end = coerce_date(frame_index.max())
    out: dict[str, np.ndarray] = {}
    for ticker in tickers:
        try:
            rows = await select_adj_close_rows(session, ticker, start, end)
        except Exception:
            continue
        if len(rows) < min_obs:
            continue
        series = pd.Series(
            [float(c) for _d, c in rows],
            index=pd.DatetimeIndex([pd.Timestamp(d) for d, _c in rows]),
        ).sort_index()
        rets = series.pct_change().reindex(frame_index).ffill().bfill()
        vec = rets.to_numpy(dtype=float)
        if vec.shape[0] == len(frame_index) and np.isfinite(vec).all():
            out[ticker] = vec
    return out


def _build_views(
    views: list[ViewIn], index_of: dict[str, int]
) -> list[bl.View]:
    """Translate request views into index-based engine views.

    A view referencing an asset outside the request universe is a domain
    error (422), not a silent drop.
    """
    out: list[bl.View] = []
    for i, view in enumerate(views):
        if isinstance(view, AbsoluteViewIn):
            refs = {"asset": view.asset}
        else:
            refs = {"long": view.long, "short": view.short}
        indices: dict[str, int] = {}
        for role, ref in refs.items():
            key = _ref_key(ref)
            if key not in index_of:
                raise BuilderError(
                    f"view {i}: asset {key} ({role}) is not in the request universe"
                )
            indices[role] = index_of[key]
        if isinstance(view, AbsoluteViewIn):
            out.append(
                bl.AbsoluteView(asset=indices["asset"], q=view.q, confidence=view.confidence)
            )
        else:
            out.append(
                bl.RelativeView(
                    long=indices["long"],
                    short=indices["short"],
                    q=view.q,
                    confidence=view.confidence,
                )
            )
    return out


async def _market_weights_for(
    session: AsyncSession, assets: list[AssetRefIn], labels: list[str]
) -> np.ndarray:
    """w_mkt from real sizes: AUM for funds, market cap for equities.

    Sizes are assembled in the same order as ``assets``/``labels`` so the
    weight vector aligns with Sigma. Unknown or non-positive sizes fail loud via
    ``bl.market_weights``.
    """
    fund_ids: list[uuid.UUID] = [
        ref.id for ref in assets if isinstance(ref, FundRefIn)
    ]
    tickers: list[str] = [ref.ticker for ref in assets if isinstance(ref, EquityRefIn)]
    aum_by_id = await optimizer_data.load_fund_aum(session, fund_ids)
    mcap_by_ticker = await optimizer_data.load_equity_market_cap(session, tickers)
    sizes: list[float | None] = []
    for ref in assets:
        if isinstance(ref, FundRefIn):
            sizes.append(aum_by_id.get(ref.id))
        else:
            sizes.append(mcap_by_ticker.get(ref.ticker))
    try:
        return bl.market_weights(sizes, labels)
    except ValueError as exc:
        raise BuilderError(str(exc)) from exc


def _solve_mu_free(
    objective: str,
    sigma: np.ndarray,
    scenarios: np.ndarray,
    cap: float | None,
    min_weight: float | None,
    linear: list[engine.LinearConstraint] | None = None,
    blocks: list[engine.BlockBudget] | None = None,
) -> tuple[np.ndarray, str]:
    if objective == "equal_weight":
        return engine.solve_equal_weight(
            sigma.shape[0], cap=cap, min_weight=min_weight, blocks=blocks, linear=linear
        )
    if objective == "min_vol":
        return engine.solve_min_vol(
            sigma, cap=cap, min_weight=min_weight, blocks=blocks, linear=linear
        )
    if objective == "erc":
        return engine.solve_erc(
            sigma, cap=cap, min_weight=min_weight, blocks=blocks, linear=linear
        )
    if objective == "max_diversification":
        return engine.solve_max_diversification(
            sigma, cap=cap, min_weight=min_weight, blocks=blocks, linear=linear
        )
    if objective == "min_cvar":
        return engine.solve_min_cvar(
            scenarios, cap=cap, min_weight=min_weight, blocks=blocks, linear=linear
        )
    raise BuilderError(f"unknown objective: {objective}")  # pragma: no cover - Literal-guarded


async def _resolve_block_budgets(
    session: AsyncSession,
    assets: list[AssetRefIn],
    labels: list[str],
    block_budgets: list[BlockBudgetIn] | None,
) -> list[engine.BlockBudget] | None:
    """Map asset-class block budgets onto engine column-index groups.

    Equities have no asset_class in the builder catalog → any equity makes a
    block-budget request fail loud (mirrors the AUM rule in
    ``_market_weights_for``).
    """
    if not block_budgets:
        return None
    equity_labels = [_ref_key(ref) for ref in assets if isinstance(ref, EquityRefIn)]
    if equity_labels:
        raise BuilderError(
            "block budgets require an asset_class for every asset; equities have "
            f"none in the builder: {', '.join(equity_labels)}"
        )
    fund_ids = [ref.id for ref in assets if isinstance(ref, FundRefIn)]
    class_by_id = await optimizer_data.load_fund_asset_class(session, fund_ids)
    # Fund.asset_class is nullable: a fund with an unknown class matches no block
    # and would be silently left unconstrained. Fail loud instead (mirrors the
    # equity guard above) so a requested risk budget is never quietly bypassed.
    missing_class = [
        _ref_key(ref)
        for ref in assets
        if isinstance(ref, FundRefIn) and class_by_id.get(ref.id) is None
    ]
    if missing_class:
        raise BuilderError(
            "block budgets require a known asset_class for every fund; missing "
            f"for: {', '.join(missing_class)}"
        )
    index_of = {label: i for i, label in enumerate(labels)}
    out: list[engine.BlockBudget] = []
    for budget in block_budgets:
        idxs = [
            index_of[_ref_key(ref)]
            for ref in assets
            if isinstance(ref, FundRefIn)
            and class_by_id.get(ref.id) == budget.asset_class
        ]
        if not idxs:
            raise BuilderError(
                f"block budget for asset_class '{budget.asset_class}' matches no "
                "asset in the resolved universe"
            )
        out.append(engine.BlockBudget(indices=idxs, lo=budget.lo, hi=budget.hi))
    return out


# Fixed group prior for the regime_aware equilibrium (harness GROUP_PRIOR). The
# strategic anchor is a FIXED mix (not market-cap weights) — the regime bands do
# the regime work; this prior is just the BL equilibrium/momentum anchor. Pure +
# DB-free (faithful to the calibrated _category_prior, and keeps the regime path
# independent of the AUM loader).
_REGIME_GROUP_PRIOR: dict[str, float] = {
    "cash": 0.04, "equity": 0.45, "fixed_income": 0.22, "thematic": 0.06,
    "alternatives": 0.08, "gold": 0.07, "long_short": 0.05,
}


def _regime_prior(groups: list[str]) -> np.ndarray:
    """Per-asset equilibrium prior (sum 1) from the fixed group prior, split EVENLY
    across each group's members (so a group's total = its prior regardless of how
    many assets it holds — fixes a count-driven tilt). Unknown-group assets (raw
    equities / unclassified) are treated as equity-like; a fully degenerate prior
    falls back to equal-weight."""
    eff = [g if g in _REGIME_GROUP_PRIOR else "equity" for g in groups]
    counts: dict[str, int] = {}
    for g in eff:
        counts[g] = counts.get(g, 0) + 1
    raw = np.array([_REGIME_GROUP_PRIOR[g] / counts[g] for g in eff], dtype=float)
    s = float(raw.sum())
    if s <= 0:
        n = len(groups)
        return np.full(n, 1.0 / n) if n else np.zeros(0, dtype=float)
    return raw / s


def _solve_regime_level1(
    proxies: list[str],
    proxy_returns: np.ndarray,
    proxy_groups: list[str],
    profile: str,
    quadrant: str,
    gamma: float,
    cvar_cap: float,
    gate_state: str | None,
    view_confidence_multiplier: float = 1.0,
) -> dict[str, float]:
    """COMBO S4b Level-1: per-sleeve CATEGORY weights over the canonical proxies.

    BL max-utility + hard CVaR inside the ``QUADRANT_POLICIES[profile][quadrant]``
    sleeve envelope (decision B; ``band_state_from_quadrant`` retired): μ =
    equilibrium π (DELTA_MARKET) + the 12-1 momentum view (fires with ≥4 risk
    sleeves, scaled by ``view_confidence_multiplier`` — the gate sets it to 0.0 in
    risk_off, μ = π); ``gamma``/``cvar_cap`` are the per-mandate ladder (the caller
    already tightened ``cvar_cap`` via the gate overlay). One annualized Ledoit-Wolf
    Σ feeds both the equilibrium and the utility penalty (harness parity);
    ``proxy_returns`` are the daily scenarios for the CVaR cap. On ``OptimizerError``
    falls back to min-CVaR inside the same bands (the structural envelope is never
    silently relaxed). Returns ``{proxy: weight}`` (sum 1; proxies at ~0 dropped).
    Raises ``OptimizerError`` if even the fallback is infeasible.
    """
    sigma = engine.sigma_ledoit_wolf(proxy_returns)
    prior = _regime_prior(proxy_groups)
    mu = momentum_view.category_momentum_mu(
        proxy_returns, proxy_groups, prior, gate_state, sigma=sigma,
        view_confidence_multiplier=view_confidence_multiplier,
    )
    bands = quadrant_policy.policy_bands(_resolve_quadrant_policy(profile, quadrant))
    blocks: list[engine.BlockBudget] = []
    for g in sleeves.SLEEVE_GROUPS:
        idx = [k for k, gg in enumerate(proxy_groups) if gg == g]
        if idx:
            lo, hi = bands[g]
            blocks.append(engine.BlockBudget(indices=idx, lo=lo, hi=min(hi, 1.0)))
    bounds = engine.BoundsBundle(blocks=blocks or None)
    try:
        wcat, _status = engine.solve_bl_utility_cvar(
            mu, sigma, proxy_returns, gamma, cvar_cap, bounds=bounds,
        )
    except engine.OptimizerError:
        wcat, _status = engine.solve_min_cvar(
            proxy_returns, bounds=bounds, cvar_limit=cvar_cap,
        )
    return {proxies[k]: float(wcat[k]) for k in range(len(proxies)) if wcat[k] > 1e-9}


def _solve_regime_level2(
    wcat: dict[str, float],
    proxy_to_sleeve: dict[str, str],
    funds_by_sleeve: dict[str, list[int]],
    n_assets: int,
) -> tuple[np.ndarray, dict[str, float]]:
    """COMBO S4b Level-2: implement each sleeve's Level-1 category weight with its
    SELECTED FUNDS EQUAL-WEIGHT (track the proxy, do NOT re-optimize — no low-vol
    or conviction tilt; the IC overlay was rejected). A floored sleeve with no fund
    (an authorized proxy fill — gold via GLD, long_short via FTLS) keeps the proxy
    itself as a holding. Returns ``(fund_weights[n_assets], proxy_holdings{ticker:
    weight})``; together they sum to ``sum(wcat)`` (= 1)."""
    fund_w = np.zeros(n_assets, dtype=float)
    proxy_holdings: dict[str, float] = {}
    for proxy, w in wcat.items():
        sleeve = proxy_to_sleeve[proxy]
        cols = funds_by_sleeve.get(sleeve, [])
        if cols:
            share = w / len(cols)
            for c in cols:
                fund_w[c] += share
        else:
            proxy_holdings[proxy] = proxy_holdings.get(proxy, 0.0) + w
    return fund_w, proxy_holdings


@dataclass
class _RegimeTwoLevel:
    """Result of the COMBO S4b two-level ``regime_aware`` solve."""

    fund_weights: np.ndarray              # length len(labels): the universe funds
    proxy_holdings: dict[str, float]      # proxy-only sleeves (gold/long_short): ticker→w
    proxy_returns: dict[str, np.ndarray]  # frame-aligned returns for those holdings
    category_weights: dict[str, float]    # sleeve → Level-1 weight (book B; A−B base)
    sleeve_bands: dict[str, list[float]]  # sleeve → [lo, hi] enforced (diagnostics)
    cvar_limit: float                     # gate-tightened CVaR cap actually applied
    # AGGREGATE portfolio-beta cap target (β_portfolio ≤ beta_cap). EXPOSED for
    # telemetry ONLY — NOT compiled into a LinearConstraint here (RELEASE GATE; the
    # aggregate-beta constraint is Plan C). Never claim portfolio beta is enforced.
    beta_cap: float


# Mandate label → one of the 3 QUADRANT_POLICIES profiles for the sleeve bands.
_REGIME_PROFILES = {
    "conservative": "conservative", "defensive": "conservative",
    "moderate_conservative": "conservative",
    "moderate": "moderate", "balanced": "moderate",
    "moderate_aggressive": "aggressive", "aggressive": "aggressive", "growth": "aggressive",
}


def _regime_profile(mandate: str | None) -> str:
    """Resolve a mandate to one of {aggressive, moderate, conservative} (default
    moderate) — the per-profile sleeve-band selector for the two-level allocator."""
    if mandate:
        key = normalise_mandate(mandate)
        if key in _REGIME_PROFILES:
            return _REGIME_PROFILES[key]
    return "moderate"


async def _solve_regime_two_level(
    session: AsyncSession,
    assets: list[AssetRefIn],
    labels: list[str],
    frame_index: "pd.Index",
    eff_policy: effective_policy.EffectiveRegimePolicy,
    payload: "OptimizeRequest",
) -> "_RegimeTwoLevel | None":
    """COMBO S4b: two-level ``regime_aware`` solve (proxy → fund equal-weight).

    Maps each fund to a 7-sleeve via ``strategy_label`` (``asset_class`` fallback),
    optimizes per-sleeve CATEGORY weights over the canonical ``GROUP_BENCHMARK``
    proxies inside the per-profile band envelope (Level-1, BL max-utility + CVaR +
    momentum), then implements each sleeve with its selected funds EQUAL-WEIGHT
    (Level-2); a floored sleeve with no fund (gold via GLD, long_short via FTLS)
    keeps its authorized proxy as a holding.

    The cohesive ``eff_policy`` is built ONCE by the caller (the dispatch) from the
    §6 consumable quadrant + the live gate; this solve READS its sleeve bands and the
    gate-tightened CVaR/beta/view-confidence off it (no second
    ``build_effective_policy`` here — exactly one build per request). Returns ``None``
    ONLY for a feasibility shortfall the caller treats as no-trade (no fund maps to a
    base sleeve, <2 live proxies, or the Level-1 solve is infeasible even after its
    min-CVaR fallback). Degrade-safe: the proxy-returns loader returns ``{}`` without
    a DB session.
    """
    profile = eff_policy.profile
    gate_state = eff_policy.gate_state
    bands = {s: (b.lo, b.hi) for s, b in eff_policy.sleeve_budgets.items()}

    # 1. fund → sleeve (strategy_label finest; asset_class fallback; raw equities
    # via the proxy ticker, else equity). 'hedge' (SH) is excluded from the book.
    fund_ids = [ref.id for ref in assets if isinstance(ref, FundRefIn)]
    strat = await optimizer_data.load_fund_strategy_label(session, fund_ids)
    cls = await optimizer_data.load_fund_asset_class(session, fund_ids)
    index_of = {label: i for i, label in enumerate(labels)}
    funds_by_sleeve: dict[str, list[int]] = {}
    for ref in assets:
        col = index_of.get(_ref_key(ref))
        if col is None:
            continue
        if isinstance(ref, FundRefIn):
            sleeve = sleeves.fund_sleeve_group(strat.get(ref.id), cls.get(ref.id))
        else:
            sleeve = sleeves.PROXY_TO_GROUP.get(ref.ticker.upper(), "equity")
        if sleeve in sleeves.SLEEVE_GROUPS:
            funds_by_sleeve.setdefault(sleeve, []).append(col)
    if not funds_by_sleeve:
        return None

    # 2. live proxies = one canonical benchmark per present sleeve, plus authorized
    # fills for a FLOORED sleeve with no fund (gold/long_short).
    proxy_to_sleeve: dict[str, str] = {
        sleeves.GROUP_BENCHMARK[g]: g for g in funds_by_sleeve
    }
    for g in sleeves.SLEEVE_GROUPS:
        if bands[g][0] > 0 and g not in funds_by_sleeve:
            for px in sleeves.GROUP_PROXY_FILL.get(g, []):
                proxy_to_sleeve[px] = g
    proxy_rets = await _load_proxy_returns(session, list(proxy_to_sleeve), frame_index)
    proxies_live = [p for p in proxy_to_sleeve if p in proxy_rets]
    if len(proxies_live) < 2:
        return None
    proxy_to_sleeve = {p: proxy_to_sleeve[p] for p in proxies_live}
    proxy_groups = [proxy_to_sleeve[p] for p in proxies_live]
    proxy_returns = np.column_stack([proxy_rets[p] for p in proxies_live])

    # 3. per-mandate dials: gamma decoupled from the equilibrium delta; the CVaR cap
    # and BL view-confidence are the FINAL gate-tightened numbers from eff_policy (the
    # overlay was applied inside build_effective_policy — no second tighten here).
    gamma = resolve_gamma(None, payload.mandate)
    cvar_cap = eff_policy.cvar_limit
    view_mult = eff_policy.bl_view_confidence_multiplier

    # 4. Level-1: category weights over the proxies, keyed off the eff_policy quadrant.
    try:
        wcat = _solve_regime_level1(
            proxies_live, proxy_returns, proxy_groups, profile, eff_policy.quadrant,
            gamma, cvar_cap, gate_state, view_mult,
        )
    except engine.OptimizerError:
        return None

    # 5. Level-2: funds equal-weight; a proxy-only sleeve keeps its proxy holding.
    fund_weights, proxy_holdings = _solve_regime_level2(
        wcat, proxy_to_sleeve, funds_by_sleeve, len(labels)
    )
    category_weights = {proxy_to_sleeve[p]: w for p, w in wcat.items()}
    present = set(funds_by_sleeve) | set(category_weights)
    sleeve_bands = {
        g: [bands[g][0], bands[g][1]] for g in sleeves.SLEEVE_GROUPS if g in present
    }
    return _RegimeTwoLevel(
        fund_weights=fund_weights,
        proxy_holdings=proxy_holdings,
        proxy_returns={t: proxy_rets[t] for t in proxy_holdings},
        category_weights=category_weights,
        sleeve_bands=sleeve_bands,
        cvar_limit=eff_policy.cvar_limit,
        beta_cap=eff_policy.beta_cap,
    )


def _filters_from_spec(spec: UniverseSpecIn) -> funds_catalog.FundFilters:
    """Map a UniverseSpecIn onto the catalog's FundFilters (search left off)."""
    return funds_catalog.FundFilters(
        search=None,
        fund_type=spec.fund_type,
        strategy_label=spec.strategy_label,
        asset_class=spec.asset_class,
        expense_ratio_max=spec.expense_ratio_max,
        aum_min=spec.aum_min,
        sharpe_1y_min=spec.sharpe_1y_min,
        volatility_1y_max=spec.volatility_1y_max,
        return_1y_min=spec.return_1y_min,
        max_drawdown_1y_min=spec.max_drawdown_1y_min,
    )


async def _resolve_assets(
    session: AsyncSession, payload: OptimizeRequest
) -> tuple[list[AssetRefIn], _LabelMap]:
    """Concrete asset list + fund label map for either request shape.

    Explicit ``assets`` pass through with an empty label map (the client owns
    the labels). A ``universe`` spec is resolved to ranked fund candidates that
    EACH have enough NAV history (and a positive AUM when the objective needs
    Black-Litterman market weights), failing loud when fewer than two qualify.
    The cross-asset date overlap (MIN_COMMON_OBS) is still enforced downstream
    by ``load_aligned_returns`` on the resolved set.
    """
    if payload.assets is not None:
        return list(payload.assets), {}

    assert payload.universe is not None  # the schema validator guarantees one
    spec = payload.universe
    needs_bl = bool(payload.views) or payload.objective in ("bl_utility", "max_return_cvar")
    # Broad-universe mode removes the ranking LIMIT (Stage-1 selects later);
    # the ranked mode keeps the user's top-``max_assets`` cap.
    try:
        candidates = await optimizer_data.select_universe_funds(
            session,
            _filters_from_spec(spec),
            rank_by=spec.rank_by,
            rank_dir=spec.rank_dir,
            max_assets=None if spec.broad_universe else spec.max_assets,
            require_aum=needs_bl,
            include_ids=spec.include_instrument_ids,
            window_days=payload.window_days,
        )
    except ValueError as exc:
        # Fail-loud data-layer guards (e.g. the broad-universe >2000 ceiling)
        # must surface as 422, not a raw 500 — a 500 also drops the CORS headers
        # and the browser then reports a misleading CORS error.
        raise BuilderError(str(exc)) from exc
    if len(candidates) < 2:
        raise BuilderError(
            f"universe selection matched {len(candidates)} optimizable fund(s) — "
            "relax the filters, lower the metric thresholds, or widen the window "
            "(at least 2 funds with enough overlapping history are required)"
        )
    assets: list[AssetRefIn] = [FundRefIn(kind="fund", id=c.id) for c in candidates]
    label_map: _LabelMap = {f"fund:{c.id}": (c.ticker, c.name) for c in candidates}
    return assets, label_map


async def _resolve_overlap_constraints(
    session: AsyncSession,
    datalake: AsyncSession | None,
    assets: list[AssetRefIn],
    labels: list[str],
    overlap_cap: float | None,
) -> list[engine.LinearConstraint]:
    """Build the pruned per-equity look-through overlap constraints.

    For each equity security ``s`` held (via look-through) by ≥1 fund in the
    FINAL asset set, the aggregate indirect exposure is
    ``Σ_i coef_s[i]·w_i`` with ``coef_s[i] = h_{fund_i, s}`` (the fund's
    look-through fraction in ``s``; funds absent from the exposure dict
    contribute 0). The constraint is ``coef_s·w ≤ overlap_cap``.

    Exact pruning: weights are long-only and sum to 1, so exposure to ``s`` is a
    convex combination of the per-fund ``h_{i,s}`` and therefore
    ``≤ max_i coef_s[i]``. A constraint for ``s`` can only ever bind when
    ``max_i coef_s[i] > overlap_cap``; below that it is vacuous. So we emit a
    ``LinearConstraint`` ONLY for those securities — keeping the cvxpy problem
    small while remaining exact. If none qualify, returns ``[]`` (no-op).

    Direct-holding handling (v1 limitation): exposure is FUND-MEDIATED only.
    Funds dominate the builder universe; a portfolio asset that is itself a
    stock is not aggregated into ``s`` because resolving ticker→CUSIP cheaply
    is not available here. Funds without N-PORT look-through simply contribute
    0 (best-effort), matching ``fund_equity_exposure``'s absence semantics.
    """
    if overlap_cap is None:
        return []
    index_of = {label: i for i, label in enumerate(labels)}
    # Map each FUND asset's column index by its label key, so we can place the
    # fund's per-security exposures into the coef vector. Non-fund assets (none
    # in v1) and funds absent from the exposure dict contribute 0.
    fund_col: dict[uuid.UUID, int] = {}
    for ref in assets:
        if isinstance(ref, FundRefIn):
            key = _ref_key(ref)
            if key in index_of:
                fund_col[ref.id] = index_of[key]
    if not fund_col:
        return []
    # Look-through exposure needs the data-lake (N-PORT lives there). Off the
    # request path (broad background job) it may be absent — fall back to the
    # primary session so the call is structurally valid; a missing data-lake
    # then yields no exposures (best-effort) rather than crashing the optimize.
    exposure_session = datalake if datalake is not None else session
    exposures = await lookthrough_exposure.fund_equity_exposure(
        session, exposure_session, list(fund_col.keys())
    )
    # Pivot fund→{security→frac} into security→coef-vector over the final assets.
    n = len(labels)
    coef_by_security: dict[str, np.ndarray] = {}
    max_by_security: dict[str, float] = {}
    for fund_id, holdings in exposures.items():
        col = fund_col.get(fund_id)
        if col is None:
            continue
        for security_key, frac in holdings.items():
            vec = coef_by_security.get(security_key)
            if vec is None:
                vec = np.zeros(n, dtype=float)
                coef_by_security[security_key] = vec
            vec[col] += frac
            prev = max_by_security.get(security_key, 0.0)
            if vec[col] > prev:
                max_by_security[security_key] = vec[col]
    out: list[engine.LinearConstraint] = []
    for security_key, vec in coef_by_security.items():
        # Exact pruning: only securities whose single largest per-fund exposure
        # exceeds the cap can ever bind.
        if max_by_security[security_key] > overlap_cap:
            out.append(
                engine.LinearConstraint(
                    coef=vec, lo=None, hi=overlap_cap, label=f"overlap:{security_key}"
                )
            )
    return out


async def run_optimize(
    session: AsyncSession,
    payload: OptimizeRequest,
    datalake: AsyncSession | None = None,
) -> OptimizeResponse:
    assets, label_map = await _resolve_assets(session, payload)

    broad = payload.universe is not None and payload.universe.broad_universe
    selection_diag: SelectionDiagnosticsOut | None = None
    if broad:
        assert payload.universe is not None
        spec = payload.universe
        # Stage-1 selects on PRE-COMPUTED per-fund risk features (no raw NAV): one
        # query to the risk MV, cluster the candidates in standardized risk-factor
        # space, and pick one representative per cluster by quality score. The raw
        # NAV history is loaded only for the K chosen funds (Stage-2 below).
        candidate_assets = assets
        candidate_fund_ids = [
            ref.id for ref in candidate_assets if isinstance(ref, FundRefIn)
        ]
        features_by_id = await optimizer_data.load_fund_risk_features(
            session, candidate_fund_ids
        )
        # Keep funds with at least one usable risk metric; the rest can't be placed
        # in the risk-structure space and are excluded (surfaced in diagnostics).
        kept: list[int] = []
        excluded: dict[int, str] = {}
        for i, ref in enumerate(candidate_assets):
            feats = features_by_id.get(ref.id) if isinstance(ref, FundRefIn) else None
            if feats is not None and any(v is not None for v in feats.values()):
                kept.append(i)
            else:
                excluded[i] = "no pre-computed risk metrics — excluded from selection"
        if len(kept) < 2:
            raise BuilderError(
                "broad-universe selection found fewer than 2 funds with risk "
                "metrics — relax the filters"
            )
        kept_assets = [candidate_assets[i] for i in kept]
        fund_ids = [ref.id for ref in kept_assets if isinstance(ref, FundRefIn)]
        quality_by_id = await optimizer_data.load_fund_quality_metrics(session, fund_ids)
        neutral: dict[str, float | None] = {
            "sharpe_1y": None,
            "expense_ratio": None,
            "aum_usd": None,
        }
        quality = [
            quality_by_id.get(ref.id, neutral) if isinstance(ref, FundRefIn) else neutral
            for ref in kept_assets
        ]
        scores = optimizer_selection.quality_score(quality)
        feature_rows = [
            features_by_id[ref.id]
            for ref in kept_assets
            if isinstance(ref, FundRefIn)
        ]
        feature_matrix = optimizer_selection.build_feature_matrix(
            feature_rows, optimizer_data.RISK_FEATURE_KEYS
        )
        result = optimizer_selection.select_diversified_features(
            feature_matrix, scores, k=spec.max_positions
        )
        chosen_assets = [kept_assets[i] for i in result.selected]
        if len(chosen_assets) < 2:
            raise BuilderError(
                "broad-universe selection produced fewer than 2 funds — relax "
                "the filters"
            )
        excluded_out = [
            ExcludedFundOut(fund=_ref_key(candidate_assets[orig]), reason=reason)
            for orig, reason in excluded.items()
        ]
        # ``result.cluster_of`` is keyed by the SELECTED index value (position in
        # the kept set), which is exactly ``result.selected[pos]``.
        clusters = {
            _ref_key(chosen_assets[pos]): result.cluster_of[sel_idx]
            for pos, sel_idx in enumerate(result.selected)
        }
        selection_diag = SelectionDiagnosticsOut(
            n_candidates=len(candidate_assets),
            n_selected=len(chosen_assets),
            excluded=excluded_out,
            clusters=clusters,
        )
        assets = chosen_assets

    refs = [_to_data_ref(ref) for ref in assets]
    frame: pd.DataFrame
    # Broad mode + a covariance-based objective (min_vol / erc /
    # max_diversification / equal_weight) tolerates funds with disjoint inception
    # via a PAIRWISE covariance over the union-index (NaN-preserving) matrix — no
    # global dropna to a common window, which on the diverse broad universe
    # collapses to <400 shared days and fails loud. Scenario-based objectives
    # (min_cvar / max_return_cvar) need joint scenario rows, so they keep the
    # common-window loader.
    pairwise_cov_path = broad and payload.objective not in (
        "min_cvar",
        "max_return_cvar",
        "regime_aware",
    )
    if pairwise_cov_path:
        assert payload.universe is not None
        try:
            union = await optimizer_data.load_returns_matrix(
                session, refs, window_days=payload.window_days
            )
        except ValueError as exc:
            raise BuilderError(str(exc)) from exc
        try:
            sigma, kept_idx, cov_excluded = engine.sigma_robust_pairwise(
                union.to_numpy(dtype=float),
                min_pair_overlap=payload.universe.min_pair_overlap,
            )
        except engine.OptimizerError as exc:
            raise BuilderError(str(exc)) from exc
        # Drop funds the pairwise estimator excluded (median overlap too low);
        # surface them in the selection diagnostics alongside the Stage-1 cuts.
        union_assets = list(assets)
        kept_labels = [str(union.columns[i]) for i in kept_idx]
        assets = [union_assets[i] for i in kept_idx]
        refs = [refs[i] for i in kept_idx]
        # In-sample CVaR is reported over the common-history rows of the
        # SURVIVING funds; allocation itself used the pairwise sigma, not these.
        frame = union[kept_labels].dropna()
        if cov_excluded and selection_diag is not None:
            extra_excluded = [
                ExcludedFundOut(fund=_ref_key(union_assets[i]), reason=reason)
                for i, reason in cov_excluded.items()
            ]
            selection_diag = selection_diag.model_copy(
                update={
                    "excluded": [*selection_diag.excluded, *extra_excluded],
                    "n_selected": len(assets),
                }
            )
    else:
        try:
            frame = await optimizer_data.load_aligned_returns(
                session, refs, window_days=payload.window_days
            )
        except ValueError as exc:
            raise BuilderError(str(exc)) from exc
        try:
            sigma = (
                engine.sigma_robust(frame.to_numpy(dtype=float))
                if broad
                else engine.sigma_ledoit_wolf(frame.to_numpy(dtype=float))
            )
        except engine.OptimizerError as exc:
            raise BuilderError(str(exc)) from exc

    labels = list(frame.columns)
    index_of = {label: i for i, label in enumerate(labels)}
    scenarios = frame.to_numpy(dtype=float)
    current_vec: np.ndarray | None = None
    if payload.turnover_lambda > 0 and payload.current_weights:
        try:
            current_vec = np.array(
                [payload.current_weights[label] for label in labels], dtype=float
            )
        except KeyError as exc:
            raise BuilderError(
                f"current_weights is missing an entry for asset {exc.args[0]} — it must "
                "cover every asset in the request universe"
            ) from exc

    cap = payload.constraints.cap
    min_weight = payload.constraints.min_weight
    # Broad-universe mode yields a LEAN portfolio (K ≈ max_positions): with few
    # final assets a per-asset cap can be mathematically infeasible (cap·K < 1),
    # since long-only weights must still sum to 1. We auto-relax this ONLY when
    # the cap is the framework default (user did not set it) — silently raising
    # a cap the user EXPLICITLY chose would violate least-surprise. An explicit
    # infeasible cap fails loud; a feasible cap (cap·K ≥ 1) is always left as-is.
    if broad and cap is not None and cap * len(assets) < 1.0:
        n = len(assets)
        min_feasible_cap = 1.0 / n
        cap_was_explicit = "cap" in payload.constraints.model_fields_set
        if cap_was_explicit:
            raise BuilderError(
                f"per-asset cap {cap:.2%} is infeasible for a {n}-position "
                f"broad-universe portfolio (needs cap ≥ {min_feasible_cap:.2%}); "
                "raise the cap or increase max_positions"
            )
        # Default (unset) cap: relax it to 1/K so K positions can sum to 1.
        cap = min_feasible_cap
    has_views = bool(payload.views)
    needs_bl = has_views or payload.objective in ("bl_utility", "max_return_cvar")
    # Effective risk-aversion: explicit bl.delta override beats the mandate
    # ladder; both feed equilibrium (pi = delta*Sigma*w_mkt) and bl_utility.
    delta = resolve_delta(payload.bl.delta, payload.mandate)

    mu_equilibrium: np.ndarray | None = None
    mu_posterior: np.ndarray | None = None
    view_consistency: ViewConsistencyOut | None = None
    cvar_limit_effective: float | None = None
    regime_state: str | None = None
    # Regime-Aware diagnostics (research codename COMBO): populated only on the
    # ``regime_aware`` path. ``combined_regime``/``haven_tilt`` retired (orthogonal
    # quadrant/gate model — Task 7); ``regime_beta_cap`` is the AGGREGATE
    # portfolio-beta cap EXPOSED for telemetry only, NOT enforced (RELEASE GATE).
    regime_quadrant: str | None = None
    regime_beta_cap: float | None = None
    regime_class_bands: dict[str, list[float]] | None = None
    # COMBO S4b two-level diagnostics + proxy-only holdings (gold/long_short).
    regime_category_weights: dict[str, float] | None = None
    regime_proxy_holdings: dict[str, float] = {}
    regime_proxy_returns: dict[str, np.ndarray] = {}
    w_mkt: np.ndarray | None = None
    if needs_bl:
        w_mkt = await _market_weights_for(session, assets, labels)
        mu_equilibrium = bl.equilibrium(sigma, w_mkt, delta=delta)
        if has_views and payload.views is not None:
            try:
                p, q = bl.build_view_matrices(
                    _build_views(payload.views, index_of), len(labels)
                )
                confidences = [view.confidence for view in payload.views]
                omega = bl.omega_idzorek(p, sigma, confidences, tau=payload.bl.tau)
                mu_posterior, _sigma_bl = bl.posterior(
                    sigma, mu_equilibrium, p, q, omega, tau=payload.bl.tau
                )
                vc = bl.view_consistency_he_litterman(
                    p, q, mu_equilibrium, omega, sigma, tau=payload.bl.tau
                )
                view_consistency = ViewConsistencyOut(
                    inconsistent=bool(vc["inconsistent"]),
                    n_flagged=int(cast(int, vc["n_flagged"])),
                    max_z=float(cast(float, vc["max_z"])),
                    threshold_sigma=float(cast(float, vc["threshold_sigma"])),
                )
            except ValueError as exc:
                raise BuilderError(str(exc)) from exc

    blocks = await _resolve_block_budgets(
        session, assets, labels, payload.constraints.block_budgets
    )
    # Per-equity look-through overlap cap (Task 4): pruned set of HARD linear
    # constraints over the FINAL assets (broad mode: the selected
    # representatives). Empty when overlap_cap is unset or no security's max
    # per-fund exposure exceeds the cap — a no-op that leaves the solve
    # unchanged. Passed as ``linear=`` to whichever solver is invoked.
    overlap_linear = await _resolve_overlap_constraints(
        session, datalake, assets, labels, payload.constraints.overlap_cap
    )
    linear = overlap_linear or None
    # Block budgets are honoured by ALL objectives. The scenario-based solvers
    # (min_cvar / max_return_cvar) consume them via a BoundsBundle (which REPLACES
    # the scalar (cap, min_weight) block in the CVaR solver), so the active scalars
    # must be promoted to per-asset vectors here — otherwise the default cap (0.25)
    # would be silently dropped the moment a block budget is supplied. The mu-free
    # solvers and bl_utility take ``blocks=`` directly (passed through below). Both
    # the views and no-views min_cvar paths reuse the bundle so a user-requested
    # risk constraint is never silently dropped.
    n = len(labels)
    cvar_bounds = (
        engine.BoundsBundle(
            cap_vec=np.full(n, cap) if cap is not None else None,
            min_vec=np.full(n, min_weight) if min_weight is not None else None,
            blocks=blocks,
        )
        if blocks
        else None
    )

    try:
        if payload.objective == "regime_aware":
            # Regime-Aware allocator (research codename COMBO): ORTHOGONAL model
            # (decision B, Task 7). Build ONE EffectiveRegimePolicy from TWO separate
            # reads — the gate state from ``fetch_gate_regime`` and the quadrant from
            # the §6 CONSUMABLE read ``quadrant_reader.fetch_quadrant_snapshot``
            # (status/confidence/point-in-time/staleness filtered) — then route
            # directly to the two-level proxy→fund solve. The gate-proxy quadrant
            # (the last-non-null ``regime_gate_daily.quadrant``) is GONE: a stale /
            # low-confidence / future-leaked quadrant on the gate row can no longer
            # drive sleeve bands; a non-consumable quadrant fails loud as
            # QUADRANT_UNAVAILABLE (freeze §6/§8/§36). The payload's ``block_budgets``
            # are IGNORED here — bands derive from the policy.
            _profile = _regime_profile(payload.mandate)
            gate_state = _OVERRIDE_REGIME_STATE
            gate_snap = (
                await taa_bands.fetch_gate_regime(datalake)
                if datalake is not None else None
            )
            if gate_state is None:
                gate_state = gate_snap.state if gate_snap is not None else None
            # §6 consumable quadrant read (production decision time = now). A None
            # row means NO consumable snapshot → build_effective_policy raises
            # QUADRANT_UNAVAILABLE below. ``datalake is None`` (test seam) likewise
            # yields None and fails loud rather than guessing.
            quadrant_row = (
                await quadrant_reader.fetch_quadrant_snapshot(
                    datalake,
                    model_version=QUADRANT_MODEL_VERSION,
                    decision_time=dt.datetime.now(dt.UTC),
                )
                if datalake is not None else None
            )
            # ONE policy build from the REAL quadrant + REAL gate (fail-loud on a
            # non-consumable quadrant/gate → structured BuilderError → 422).
            try:
                eff_policy = effective_policy.build_effective_policy(
                    quadrant_row, gate_snap, _profile,
                    base_cvar_limit=resolve_cvar_limit(
                        payload.cvar_limit, payload.mandate
                    ),
                )
            except effective_policy.EffectivePolicyError as exc:
                raise _as_builder_error(exc) from exc
            regime_quadrant = eff_policy.quadrant
            regime_state = eff_policy.gate_state
            cvar_limit_effective = eff_policy.cvar_limit
            # eff_policy.beta_cap is the AGGREGATE portfolio-beta cap — EXPOSED for
            # telemetry ONLY, NOT compiled into a constraint (RELEASE GATE; Plan C).
            regime_beta_cap = eff_policy.beta_cap
            two_level = await _solve_regime_two_level(
                session, assets, labels, frame.index, eff_policy, payload,
            )
            if two_level is None:
                # Fail-loud: regime_aware that can't be produced is a no-trade
                # structured error, NEVER weights-with-warnings (spec §31).
                raise QuadrantUnavailableError(
                    "regime_aware: two-level solve could not be built for this "
                    "universe (need >=2 live sleeves with proxies)"
                )
            weights = two_level.fund_weights
            status = "regime_two_level"
            regime_proxy_holdings = two_level.proxy_holdings
            regime_proxy_returns = two_level.proxy_returns
            regime_category_weights = two_level.category_weights
            regime_class_bands = two_level.sleeve_bands
        elif payload.objective == "bl_utility":
            assert mu_equilibrium is not None  # needs_bl guarantees it
            mu_for_utility = mu_posterior if mu_posterior is not None else mu_equilibrium
            weights, status = bl.solve_bl_utility(
                mu_for_utility,
                sigma,
                delta=delta,
                cap=cap,
                min_weight=min_weight,
                blocks=blocks,
                linear=linear,
            )
        elif payload.objective == "max_return_cvar":
            assert payload.cvar_limit is not None  # schema validator guarantees it
            assert mu_equilibrium is not None  # needs_bl computes it for this objective
            # Gate G5-safe mu: the BL posterior when views exist, otherwise the
            # equilibrium return pi = delta*Sigma*w_mkt. Never the historical mean.
            mu = mu_posterior if mu_posterior is not None else mu_equilibrium
            # CVaR-scaling regime read (Sprint 3, decision §3.3): the LIVE gate
            # (debounced 2-of-3 cross-asset vote) REPLACES the credit-only read —
            # its lowercase ``state`` ('risk_on'/'risk_off') is compatible with
            # ``regime_cvar_multiplier``. The ``_OVERRIDE_REGIME_STATE`` seam
            # still short-circuits the DB read.
            state = _OVERRIDE_REGIME_STATE
            if state is None and datalake is not None:
                snap = await taa_bands.fetch_gate_regime(datalake)
                state = snap.state if snap is not None else None
            limit = apply_regime_cvar_limit(
                payload.cvar_limit, state, risk_off_factor=DEFAULT_RISK_OFF_CVAR_FACTOR
            )
            regime_state = state
            cvar_limit_effective = limit
            # Reuse cvar_bounds (already built above with the same promotion
            # logic) — the max_return_cvar engine path is structurally identical
            # to min_cvar: BoundsBundle replaces the scalar (cap, min_weight)
            # block, so no duplicate construction is needed.
            weights, status = engine.solve_max_return_cvar_capped(
                scenarios,
                mu=mu,
                cvar_limit=limit,
                cap=cap,
                min_weight=min_weight,
                bounds=cvar_bounds,
                linear=linear,
            )
        elif payload.objective == "min_cvar" and mu_posterior is not None:
            # Product default with views: re-centered scenarios + equilibrium
            # return floor (dispatch §5: piso = π·w_mkt). Block budgets (when
            # given) ride along via bounds — engine builds cons from bounds, then
            # appends the ret_floor row independently.
            assert mu_equilibrium is not None and w_mkt is not None
            mu_hist = bl.historical_mean_ann(scenarios)
            recentered = bl.recenter_scenarios(scenarios, mu_hist, mu_posterior)
            ret_floor = float(mu_equilibrium @ w_mkt)
            weights, status = engine.solve_min_cvar(
                recentered,
                cap=cap,
                min_weight=min_weight,
                bounds=cvar_bounds,
                ret_floor=ret_floor,
                mu=mu_posterior,
                current_weights=current_vec,
                turnover_lambda=payload.turnover_lambda,
                linear=linear,
            )
        else:
            if payload.objective == "min_cvar":
                weights, status = engine.solve_min_cvar(
                    scenarios,
                    cap=cap,
                    min_weight=min_weight,
                    bounds=cvar_bounds,
                    current_weights=current_vec,
                    turnover_lambda=payload.turnover_lambda,
                    linear=linear,
                )
            else:
                weights, status = _solve_mu_free(
                    payload.objective,
                    sigma,
                    scenarios,
                    cap,
                    min_weight,
                    linear=linear,
                    blocks=blocks,
                )
    except engine.OptimizerError as exc:
        raise BuilderError(str(exc)) from exc

    # COMBO S4b: the two-level solve may hold a sleeve via its authorized PROXY
    # (gold→GLD, long_short→FTLS) that the client never listed. Splice those
    # proxy-only holdings into the universe AFTER the solve — as equity refs with
    # their frame-aligned returns — so the response, the vol/CVaR figures, and the
    # weight vector all account for them (the book sums to 1 over funds+proxies).
    if regime_proxy_holdings:
        n_add = len(regime_proxy_holdings)
        for ticker, w in regime_proxy_holdings.items():
            ref = EquityRefIn(kind="equity", ticker=ticker)
            key = _ref_key(ref)
            if key in index_of:  # already in the universe → just add the weight
                weights[index_of[key]] += w
                continue
            assets.append(ref)
            labels.append(key)
            label_map[key] = (ticker, ticker)
            scenarios = np.column_stack([scenarios, regime_proxy_returns[ticker]])
            weights = np.append(weights, w)
        index_of = {label: i for i, label in enumerate(labels)}
        # Recompute Σ over the extended universe for the reported vol (telemetry —
        # the two-level solve used its own per-category Σ, not this one).
        sigma = engine.sigma_ledoit_wolf(scenarios)
        if mu_equilibrium is not None:
            mu_equilibrium = np.append(mu_equilibrium, np.zeros(n_add))
        if mu_posterior is not None:
            mu_posterior = np.append(mu_posterior, np.zeros(n_add))

    vol_ann = float(np.sqrt(weights @ sigma @ weights))
    # In-sample CVaR on RAW scenarios using the EXACT Rockafellar–Uryasev
    # estimator (app.analytics.realized_cvar) — the same objective the
    # min-CVaR optimizer minimizes — so the reported figure is consistent
    # with how the weights were chosen (T1C). alpha=0.95 matches
    # engine.DEFAULT_CVAR_ALPHA.
    portfolio_daily = pd.Series(scenarios @ weights, index=frame.index)
    try:
        cvar_95 = realized_cvar(portfolio_daily, confidence=0.95)
    except ValueError as exc:
        raise BuilderError(f"in-sample CVaR undefined: {exc}") from exc
    return_ann_bl = float(mu_posterior @ weights) if mu_posterior is not None else None

    result_fund_ids = [ref.id for ref in assets if isinstance(ref, FundRefIn)]
    asset_class_of = await optimizer_data.load_fund_asset_class(session, result_fund_ids)
    strategy_of = await optimizer_data.load_fund_strategy_label(session, result_fund_ids)

    return OptimizeResponse(
        weights=[
            WeightOut(
                asset=ref,
                weight=float(weights[index_of[_ref_key(ref)]]),
                ticker=label_map.get(_ref_key(ref), (None, ""))[0],
                name=label_map.get(_ref_key(ref), (None, None))[1] or None,
                asset_class=(
                    asset_class_of.get(ref.id) if isinstance(ref, FundRefIn) else None
                ),
                strategy_label=(
                    strategy_of.get(ref.id) if isinstance(ref, FundRefIn) else None
                ),
            )
            for ref in assets
        ],
        expected=ExpectedOut(
            vol_ann=vol_ann, cvar_95_in_sample=cvar_95, return_ann_bl=return_ann_bl
        ),
        diagnostics=DiagnosticsOut(
            n_obs=len(frame),
            status=status,
            mu_equilibrium=(
                [float(x) for x in mu_equilibrium] if mu_equilibrium is not None else None
            ),
            mu_posterior=(
                [float(x) for x in mu_posterior] if mu_posterior is not None else None
            ),
            view_consistency=view_consistency,
            selection=selection_diag,
            cvar_limit_effective=cvar_limit_effective,
            regime_state=regime_state,
            quadrant=regime_quadrant,
            class_bands=regime_class_bands,
            # AGGREGATE portfolio-beta cap TARGET — EXPOSED for telemetry only, NOT
            # enforced until Plan C compiles the aggregate-beta LinearConstraint
            # (RELEASE GATE). Never claim the portfolio beta is guaranteed.
            beta_cap=regime_beta_cap,
            category_weights=regime_category_weights,
        ),
    )
