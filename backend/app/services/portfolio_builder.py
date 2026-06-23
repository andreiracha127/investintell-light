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

import uuid
from typing import cast

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import realized_cvar
from app.optimizer import black_litterman as bl
from app.optimizer import data as optimizer_data
from app.optimizer import engine, momentum_view
from app.optimizer import selection as optimizer_selection
from app.optimizer.mandate import resolve_cvar_limit, resolve_delta, resolve_gamma
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
from app.services import funds_catalog, lookthrough_exposure, taa_bands
from app.services._series import select_adj_close_rows

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


def _to_data_ref(ref: FundRefIn | EquityRefIn) -> optimizer_data.AssetRef:
    if isinstance(ref, FundRefIn):
        return optimizer_data.FundAssetRef(id=ref.id)
    return optimizer_data.EquityAssetRef(ticker=ref.ticker.upper())


def _ref_key(ref: FundRefIn | EquityRefIn) -> str:
    return _to_data_ref(ref).label


def _available_tickers(assets: list[AssetRefIn], label_map: _LabelMap) -> dict[str, int]:
    """Map an UPPER-cased ticker → its column index, for the goldfix haven.

    Equities expose their ticker directly; funds expose it via the universe
    ``label_map`` (the explicit-list path leaves fund tickers unknown, so a fund
    only participates in the haven when its ticker is known). The index is the
    asset's position in ``assets`` (== its column once labels are built in the
    same order).
    """
    out: dict[str, int] = {}
    for i, ref in enumerate(assets):
        if isinstance(ref, EquityRefIn):
            out[ref.ticker.upper()] = i
        else:
            ticker = label_map.get(_ref_key(ref), (None, None))[0]
            if ticker:
                out[ticker.upper()] = i
    return out


def _spy_closes_from_frame(frame: "pd.DataFrame") -> list[float]:
    """Reconstruct a NEWEST-FIRST synthetic SPY close series for the vol/beta
    market-stress overlay, IF the universe contains ``equity:SPY``.

    The builder has no SPY closes loader on the request path, so the overlay is
    sourced opportunistically from the returns frame: a cumulative product of
    (1 + r) gives a price proxy whose drawdown shape (what ``market_stress``
    reads) matches SPY's. When SPY is absent the overlay degrades to the flat
    ``cap`` (``vol_graduated_caps``' no-stress branch) — documented, degrade-safe.
    """
    col = "equity:SPY"
    if col not in frame.columns:
        return []
    rets = frame[col].to_numpy(dtype=float)
    closes = np.cumprod(1.0 + rets)  # oldest→newest price proxy
    return [float(x) for x in closes[::-1]]  # newest-first for market_stress


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
    start = frame_index.min().date()
    end = frame_index.max().date()
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


# COMBO band classes (the 4-class TAA table). ``multi_asset`` is intentionally
# absent: its representatives are left UNBOUNDED by class band (decision O5).
_COMBO_BAND_CLASSES = ("equity", "fixed_income", "alternatives", "cash")


async def _fund_class_columns(
    session: AsyncSession,
    assets: list[AssetRefIn],
    labels: list[str],
) -> dict[str, list[int]]:
    """Group FUND column indices by their resolved ``asset_class``.

    Unlike ``_resolve_block_budgets`` (which fails loud), this is the lenient
    mapping the COMBO regime path needs: equities (no ``asset_class`` in the
    builder) and funds with an unknown/absent class simply contribute to no
    group — they are left UNBOUNDED by the regime bands (decision O5). Classes
    with no member fund are absent from the returned dict (skipped downstream).
    """
    index_of = {label: i for i, label in enumerate(labels)}
    fund_ids = [ref.id for ref in assets if isinstance(ref, FundRefIn)]
    class_by_id = await optimizer_data.load_fund_asset_class(session, fund_ids)
    columns: dict[str, list[int]] = {}
    for ref in assets:
        if not isinstance(ref, FundRefIn):
            continue  # equities carry no asset_class → unbounded (O5)
        cls = class_by_id.get(ref.id)
        if cls is None:
            continue  # unknown class → unbounded (not failed; combo derives bands)
        col = index_of.get(_ref_key(ref))
        if col is not None:
            columns.setdefault(cls, []).append(col)
    return columns


async def _resolve_regime_block_budgets(
    session: AsyncSession,
    datalake: AsyncSession | None,
    assets: list[AssetRefIn],
    labels: list[str],
) -> tuple[list[engine.BlockBudget], str, str | None]:
    """Derive the COMBO per-class ``BlockBudget`` envelope from the live gate.

    Reads the worker-materialized gate snapshot (state + growth/inflation
    quadrant — decision A; the quadrant is READ, never computed in the backend),
    resolves the combined band-state via ``taa_bands.combined_regime``, and maps
    ``taa_bands.effective_class_bands`` onto engine column groups for each band
    class PRESENT in the universe. ``multi_asset`` and absent classes are skipped
    (O5). The ``STAG_GOLD`` haven sentinel (SLOWDOWN) returns NO class blocks —
    the dispatch (Task 3) routes the goldfix target instead.

    Returns ``(regime_blocks, combined_regime_label, quadrant_or_none)``.
    """
    gate = await taa_bands.fetch_gate_regime(datalake) if datalake is not None else None
    # The combo gate state honours the same test seam as the CVaR-scaling read,
    # so a forced state drives the bands deterministically in tests.
    gate_state = _OVERRIDE_REGIME_STATE or (gate.state if gate else None)
    quadrant = gate.quadrant if gate else None
    regime = taa_bands.combined_regime(gate_state, quadrant)
    if regime == "STAG_GOLD":
        # Goldfix haven bypasses class bands (Task 3 routes the fixed target).
        return [], regime, quadrant
    bands, _smoothed = taa_bands.effective_class_bands(regime)
    columns = await _fund_class_columns(session, assets, labels)
    blocks: list[engine.BlockBudget] = []
    for cls in _COMBO_BAND_CLASSES:
        idxs = columns.get(cls)
        if not idxs:
            continue  # class absent from the universe → no block
        lo, hi = bands[cls]
        blocks.append(engine.BlockBudget(indices=idxs, lo=lo, hi=hi))
    return blocks, regime, quadrant


async def _regime_sleeve_groups(
    session: AsyncSession,
    assets: list[AssetRefIn],
    labels: list[str],
) -> list[str]:
    """Per-asset group label (one per ``labels`` column) for the regime_aware
    momentum view. Inverts ``_fund_class_columns`` (the lenient 4-class mapping:
    equity/fixed_income/alternatives/cash); equities and unknown-class funds get
    ``''`` (a non-risk category). NOTE: the momentum view fires only with
    ``>= MIN_RISK`` risk categories, so this 4-class granularity leaves it DORMANT
    (μ = equilibrium π); the finer 7-sleeve grouping that activates it arrives with
    the two-level proxy model (S4b).
    """
    columns = await _fund_class_columns(session, assets, labels)
    groups = ["" for _ in labels]
    for cls, idxs in columns.items():
        for j in idxs:
            if 0 <= j < len(groups):
                groups[j] = cls
    return groups


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


async def _solve_regime_motor(
    session: AsyncSession,
    assets: list[AssetRefIn],
    labels: list[str],
    scenarios: np.ndarray,
    sigma: np.ndarray,
    cvar_bounds_regime: engine.BoundsBundle,
    gate_state: str | None,
    payload: "OptimizeRequest",
    cap: float | None,
    min_weight: float | None,
    current_vec: np.ndarray | None,
    linear: "list[engine.LinearConstraint] | None",
) -> tuple[np.ndarray, str]:
    """Return-aware regime_aware solve (COMBO S4a): BL max-utility + hard CVaR with
    the per-mandate gamma and μ = equilibrium π (DELTA_MARKET) + category momentum
    view, INSIDE the same regime envelope (graduated caps + class bands carried by
    ``cvar_bounds_regime``). Replaces the return-blind min-CVaR motor.

    On ANY ``OptimizerError`` falls back to ``solve_min_cvar`` so the regime
    envelope is always honoured (worst case == the prior behaviour). gamma is
    DECOUPLED from the equilibrium delta; the CVaR safety cap is the per-mandate
    ladder, tightened in risk_off. The one sigma is reused for both the equilibrium
    μ and the utility penalty (harness parity). Turnover damping is not applied on
    the BL path (the calibrated category solve has none); only the fallback keeps it.
    """
    gamma = resolve_gamma(None, payload.mandate)
    cvar_cap = resolve_cvar_limit(payload.cvar_limit, payload.mandate)
    if (gate_state or "").lower() == "risk_off":
        cvar_cap *= DEFAULT_RISK_OFF_CVAR_FACTOR
    try:
        groups = await _regime_sleeve_groups(session, assets, labels)
        prior = _regime_prior(groups)
        mu = momentum_view.category_momentum_mu(
            scenarios, groups, prior, gate_state, sigma=sigma,
        )
        return engine.solve_bl_utility_cvar(
            mu, sigma, scenarios, gamma, cvar_cap,
            cap=cap, min_weight=min_weight, bounds=cvar_bounds_regime, linear=linear,
        )
    except engine.OptimizerError:
        return engine.solve_min_cvar(
            scenarios, cap=cap, min_weight=min_weight, bounds=cvar_bounds_regime,
            current_weights=current_vec, turnover_lambda=payload.turnover_lambda,
            linear=linear,
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
    # ``regime_aware`` path.
    regime_quadrant: str | None = None
    regime_combined: str | None = None
    regime_class_bands: dict[str, list[float]] | None = None
    regime_haven_tilt: dict[str, float] | None = None
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
            # Regime-Aware allocator (research codename COMBO, spec §3.3): the
            # gate-driven per-class band ENVELOPE + min-CVaR inside it (decision
            # B), with the SLOWDOWN goldfix haven and vol/beta graduated caps. The
            # payload's ``block_budgets`` are IGNORED here — bands derive from the
            # regime.
            regime_blocks, regime_combined, regime_quadrant = (
                await _resolve_regime_block_budgets(session, datalake, assets, labels)
            )
            # Gate state also scales the reported CVaR limit + drives diagnostics,
            # honouring the same test seam as the scaling read (Task 4).
            gate_state = _OVERRIDE_REGIME_STATE
            if gate_state is None and datalake is not None:
                gate_snap = await taa_bands.fetch_gate_regime(datalake)
                gate_state = gate_snap.state if gate_snap is not None else None
            regime_state = gate_state
            if payload.cvar_limit is not None:
                cvar_limit_effective = apply_regime_cvar_limit(
                    payload.cvar_limit, gate_state,
                    risk_off_factor=DEFAULT_RISK_OFF_CVAR_FACTOR,
                )
            if regime_combined == "STAG_GOLD":
                # Goldfix haven: IMPOSE the fixed gold-led target over available
                # names (port _haven_weights goldfix, main.py:959-972); the
                # whitelist IS the defense — skip the solver entirely.
                ticker_col = _available_tickers(assets, label_map)
                target = taa_bands.goldfix_target(set(ticker_col.keys()))
                if not target:
                    raise BuilderError(
                        "regime_aware SLOWDOWN haven needs at least one of GLD/"
                        "VOOV/QAI/GCC/BIL in the universe; none were found"
                    )
                weights = np.zeros(len(labels), dtype=float)
                for ticker, wgt in target.items():
                    weights[ticker_col[ticker]] = wgt
                status = "goldfix"
                regime_haven_tilt = dict(target)
            else:
                # Band route — min-CVaR inside the regime envelope with the vol/
                # (beta in RISK_OFF) graduated per-asset cap vector. Surface the
                # per-class (min, max) bands actually enforced for transparency
                # (only the classes PRESENT as a BlockBudget).
                present_classes = await _fund_class_columns(session, assets, labels)
                _band_map, _ = taa_bands.effective_class_bands(regime_combined)
                regime_class_bands = {
                    cls: [_band_map[cls][0], _band_map[cls][1]]
                    for cls in _COMBO_BAND_CLASSES
                    if present_classes.get(cls)
                }
                base_cap = cap if cap is not None else engine.DEFAULT_CAP
                return_cols = [scenarios[:, j] for j in range(scenarios.shape[1])]
                # SPY is loaded as a SIGNAL series from eod_prices over the
                # optimization window — decoupled from the traded universe — so
                # the vol/beta overlays activate for ANY universe (Sprint 5). The
                # in-universe synthetic proxy is the fallback when the DB read
                # yields too little history (degrade-safe: flat cap, no crash).
                spy_desc, spy_rets_aligned = await _load_spy_signal(
                    session, frame.index
                )
                if not spy_desc:
                    spy_desc = _spy_closes_from_frame(frame)
                graduated_caps = taa_bands.vol_graduated_caps(
                    base_cap, return_cols, spy_desc
                )
                if regime_combined == "RISK_OFF":
                    # Prefer the loaded SPY returns (aligned to the scenario
                    # rows); fall back to in-universe SPY if the loader was empty.
                    spy_rets = spy_rets_aligned
                    if spy_rets is None:
                        spy_col = index_of.get("equity:SPY")
                        if spy_col is not None and spy_desc:
                            spy_rets = scenarios[:, spy_col]
                    if spy_rets is not None and spy_desc:
                        betas = taa_bands.asset_betas(
                            {labels[j]: scenarios[:, j] for j in range(len(labels))},
                            spy_rets,
                        )
                        graduated_caps = taa_bands.beta_graduated_caps(
                            graduated_caps, [betas[labels[j]] for j in range(len(labels))]
                        )
                cvar_bounds_regime = engine.BoundsBundle(
                    cap_vec=graduated_caps,
                    min_vec=np.full(n, min_weight) if min_weight is not None else None,
                    blocks=regime_blocks or None,
                )
                # COMBO S4a: return-aware motor — BL max-utility + hard CVaR with
                # the per-mandate gamma and μ = equilibrium π + category momentum
                # view, inside this same regime envelope. Replaces the return-blind
                # min-CVaR; falls back to it on infeasibility (envelope preserved).
                weights, status = await _solve_regime_motor(
                    session, assets, labels, scenarios, sigma, cvar_bounds_regime,
                    gate_state, payload, cap, min_weight, current_vec, linear,
                )
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
            combined_regime=regime_combined,
            class_bands=regime_class_bands,
            haven_tilt=regime_haven_tilt,
        ),
    )
