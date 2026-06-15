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
re-centered ones) with the SAME F3 estimator (``app.analytics.historical_cvar``)
so it is directly comparable with portfolio-analysis numbers (gate G3).

Error contract: every domain failure raises ``BuilderError`` (→ 422 with the
message verbatim); solver failures (``OptimizerError``) bubble as 422 too.

AUM rule (fail-loud, dispatch F8.4): views/bl_utility require a known positive
AUM for EVERY asset in the universe. Equities have no market cap in the
builder yet → any equity in a views request is rejected; funds with NULL AUM
are rejected with the explicit list. The caller decides what to exclude.
"""

import uuid

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import historical_cvar
from app.optimizer import black_litterman as bl
from app.optimizer import data as optimizer_data
from app.optimizer import engine
from app.schemas.builder import (
    AbsoluteViewIn,
    AssetRefIn,
    BlockBudgetIn,
    DiagnosticsOut,
    EquityRefIn,
    ExpectedOut,
    FundRefIn,
    OptimizeRequest,
    OptimizeResponse,
    UniverseSpecIn,
    ViewIn,
    WeightOut,
)
from app.services import funds_catalog


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
    """w_mkt from real AUM. Fail-loud on equities and on funds without AUM."""
    equity_labels = [
        _ref_key(ref) for ref in assets if isinstance(ref, EquityRefIn)
    ]
    if equity_labels:
        raise BuilderError(
            "views requerem AUM para todos os ativos; equities ainda sem market cap "
            f"no builder: {', '.join(equity_labels)} — remova-as ou otimize sem views"
        )
    fund_ids: list[uuid.UUID] = [
        ref.id for ref in assets if isinstance(ref, FundRefIn)
    ]
    aum_by_id = await optimizer_data.load_fund_aum(session, fund_ids)
    aums: list[float | None] = [aum_by_id.get(fund_id) for fund_id in fund_ids]
    try:
        return bl.market_weights(aums, labels)
    except ValueError as exc:
        raise BuilderError(str(exc)) from exc


def _solve_mu_free(
    objective: str,
    sigma: np.ndarray,
    scenarios: np.ndarray,
    cap: float | None,
    min_weight: float | None,
) -> tuple[np.ndarray, str]:
    if objective == "equal_weight":
        return engine.solve_equal_weight(sigma.shape[0], cap=cap, min_weight=min_weight)
    if objective == "min_vol":
        return engine.solve_min_vol(sigma, cap=cap, min_weight=min_weight)
    if objective == "erc":
        return engine.solve_erc(sigma, cap=cap, min_weight=min_weight)
    if objective == "max_diversification":
        return engine.solve_max_diversification(sigma, cap=cap, min_weight=min_weight)
    if objective == "min_cvar":
        return engine.solve_min_cvar(scenarios, cap=cap, min_weight=min_weight)
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
    candidates = await optimizer_data.select_universe_funds(
        session,
        _filters_from_spec(spec),
        rank_by=spec.rank_by,
        rank_dir=spec.rank_dir,
        max_assets=spec.max_assets,
        require_aum=needs_bl,
        include_ids=spec.include_instrument_ids,
        window_days=payload.window_days,
    )
    if len(candidates) < 2:
        raise BuilderError(
            f"universe selection matched {len(candidates)} optimizable fund(s) — "
            "relax the filters, lower the metric thresholds, or widen the window "
            "(at least 2 funds with enough overlapping history are required)"
        )
    assets: list[AssetRefIn] = [FundRefIn(kind="fund", id=c.id) for c in candidates]
    label_map: _LabelMap = {f"fund:{c.id}": (c.ticker, c.name) for c in candidates}
    return assets, label_map


async def run_optimize(session: AsyncSession, payload: OptimizeRequest) -> OptimizeResponse:
    assets, label_map = await _resolve_assets(session, payload)
    refs = [_to_data_ref(ref) for ref in assets]
    try:
        frame: pd.DataFrame = await optimizer_data.load_aligned_returns(
            session, refs, window_days=payload.window_days
        )
    except ValueError as exc:
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
    try:
        sigma = engine.sigma_ledoit_wolf(scenarios)
    except engine.OptimizerError as exc:
        raise BuilderError(str(exc)) from exc

    cap = payload.constraints.cap
    min_weight = payload.constraints.min_weight
    has_views = bool(payload.views)
    needs_bl = has_views or payload.objective in ("bl_utility", "max_return_cvar")

    mu_equilibrium: np.ndarray | None = None
    mu_posterior: np.ndarray | None = None
    w_mkt: np.ndarray | None = None
    if needs_bl:
        w_mkt = await _market_weights_for(session, assets, labels)
        mu_equilibrium = bl.equilibrium(sigma, w_mkt, delta=payload.bl.delta)
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
            except ValueError as exc:
                raise BuilderError(str(exc)) from exc

    blocks = await _resolve_block_budgets(
        session, assets, labels, payload.constraints.block_budgets
    )
    # Block budgets are honoured ONLY by min_cvar (ConstraintsIn docstring). The
    # bundle replaces the scalar (cap, min_weight) block in the CVaR solver; it
    # is reused by BOTH the views and no-views min_cvar paths so a user-requested
    # risk constraint is never silently dropped. Because the bundle path REPLACES
    # the scalar (cap, min_weight) constraints in bounds_constraints, the active
    # scalars must be promoted to per-asset vectors here — otherwise the default
    # cap (0.25) would be silently dropped the moment a block budget is supplied.
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
        if payload.objective == "bl_utility":
            assert mu_equilibrium is not None  # needs_bl guarantees it
            mu_for_utility = mu_posterior if mu_posterior is not None else mu_equilibrium
            weights, status = bl.solve_bl_utility(
                mu_for_utility, sigma, delta=payload.bl.delta, cap=cap, min_weight=min_weight
            )
        elif payload.objective == "max_return_cvar":
            assert payload.cvar_limit is not None  # schema validator guarantees it
            if mu_posterior is None:
                raise BuilderError(
                    "max_return_cvar needs expected returns — provide views so the "
                    "Black-Litterman posterior exists (gate G5)"
                )
            limit = apply_regime_cvar_limit(
                payload.cvar_limit, None, risk_off_factor=DEFAULT_RISK_OFF_CVAR_FACTOR
            )
            # Reuse cvar_bounds (already built above with the same promotion
            # logic) — the max_return_cvar engine path is structurally identical
            # to min_cvar: BoundsBundle replaces the scalar (cap, min_weight)
            # block, so no duplicate construction is needed.
            weights, status = engine.solve_max_return_cvar_capped(
                scenarios,
                mu=mu_posterior,
                cvar_limit=limit,
                cap=cap,
                min_weight=min_weight,
                bounds=cvar_bounds,
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
                )
            else:
                weights, status = _solve_mu_free(
                    payload.objective, sigma, scenarios, cap, min_weight
                )
    except engine.OptimizerError as exc:
        raise BuilderError(str(exc)) from exc

    vol_ann = float(np.sqrt(weights @ sigma @ weights))
    # In-sample CVaR on RAW scenarios, F3 estimator (gate G3 comparability).
    portfolio_daily = pd.Series(scenarios @ weights, index=frame.index)
    try:
        cvar_95 = historical_cvar(portfolio_daily, confidence=0.95)
    except ValueError as exc:
        raise BuilderError(f"in-sample CVaR undefined: {exc}") from exc
    return_ann_bl = float(mu_posterior @ weights) if mu_posterior is not None else None

    return OptimizeResponse(
        weights=[
            WeightOut(
                asset=ref,
                weight=float(weights[index_of[_ref_key(ref)]]),
                ticker=label_map.get(_ref_key(ref), (None, ""))[0],
                name=label_map.get(_ref_key(ref), (None, None))[1] or None,
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
        ),
    )
