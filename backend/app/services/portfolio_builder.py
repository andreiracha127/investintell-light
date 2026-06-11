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
    DiagnosticsOut,
    EquityRefIn,
    ExpectedOut,
    FundRefIn,
    OptimizeRequest,
    OptimizeResponse,
    ViewIn,
    WeightOut,
)


class BuilderError(ValueError):
    """Domain failure in the builder — mapped verbatim to HTTP 422."""


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
    session: AsyncSession, payload: OptimizeRequest, labels: list[str]
) -> np.ndarray:
    """w_mkt from real AUM. Fail-loud on equities and on funds without AUM."""
    equity_labels = [
        _ref_key(ref) for ref in payload.assets if isinstance(ref, EquityRefIn)
    ]
    if equity_labels:
        raise BuilderError(
            "views requerem AUM para todos os ativos; equities ainda sem market cap "
            f"no builder: {', '.join(equity_labels)} — remova-as ou otimize sem views"
        )
    fund_ids: list[uuid.UUID] = [
        ref.id for ref in payload.assets if isinstance(ref, FundRefIn)
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


async def run_optimize(session: AsyncSession, payload: OptimizeRequest) -> OptimizeResponse:
    refs = [_to_data_ref(ref) for ref in payload.assets]
    try:
        frame: pd.DataFrame = await optimizer_data.load_aligned_returns(
            session, refs, window_days=payload.window_days
        )
    except ValueError as exc:
        raise BuilderError(str(exc)) from exc

    labels = list(frame.columns)
    index_of = {label: i for i, label in enumerate(labels)}
    scenarios = frame.to_numpy(dtype=float)
    try:
        sigma = engine.sigma_ledoit_wolf(scenarios)
    except engine.OptimizerError as exc:
        raise BuilderError(str(exc)) from exc

    cap = payload.constraints.cap
    min_weight = payload.constraints.min_weight
    has_views = bool(payload.views)
    needs_bl = has_views or payload.objective == "bl_utility"

    mu_equilibrium: np.ndarray | None = None
    mu_posterior: np.ndarray | None = None
    w_mkt: np.ndarray | None = None
    if needs_bl:
        w_mkt = await _market_weights_for(session, payload, labels)
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

    try:
        if payload.objective == "bl_utility":
            assert mu_equilibrium is not None  # needs_bl guarantees it
            mu_for_utility = mu_posterior if mu_posterior is not None else mu_equilibrium
            weights, status = bl.solve_bl_utility(
                mu_for_utility, sigma, delta=payload.bl.delta, cap=cap, min_weight=min_weight
            )
        elif payload.objective == "min_cvar" and mu_posterior is not None:
            # Product default with views: re-centered scenarios + equilibrium
            # return floor (dispatch §5: piso = π·w_mkt).
            assert mu_equilibrium is not None and w_mkt is not None
            mu_hist = bl.historical_mean_ann(scenarios)
            recentered = bl.recenter_scenarios(scenarios, mu_hist, mu_posterior)
            ret_floor = float(mu_equilibrium @ w_mkt)
            weights, status = engine.solve_min_cvar(
                recentered,
                cap=cap,
                min_weight=min_weight,
                ret_floor=ret_floor,
                mu=mu_posterior,
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
            WeightOut(asset=ref, weight=float(weights[index_of[_ref_key(ref)]]))
            for ref in payload.assets
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
