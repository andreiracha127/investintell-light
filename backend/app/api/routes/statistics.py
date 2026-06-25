"""Statistics-group endpoints (F5): scenario replay, beta scatter, rolling
correlation, holdings correlation matrix.

DB-first contract, same as everywhere: routes never call Tiingo for historical
EOD data. Service orchestrators read from eod_prices. Routes are thin:
validate (Pydantic) → run the service → map
``StockAnalysisError`` to 422.

Replay semantics: a persisted portfolio (the scenario subject, or a
``kind='portfolio'`` pseudo-asset) is replayed at its CURRENT quantities held
fixed over the window — buy-and-hold historical replay, not a reconstruction
of past trades. See ``app.services.statistics``.

Error mapping (fail loud, never silently empty):
- request validation (dates/window/AssetRef shape)  -> 422 (Pydantic)
- unknown portfolio / missing local price history    -> 404/422
- empty portfolio / insufficient history /
  undefined statistic / oversized window            -> 422
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.result_cache import portfolio_version_hash
from app.models.portfolio import Portfolio
from app.schemas.statistics import (
    BetaRequest,
    BetaResponse,
    CorrelationRequest,
    CorrelationResponse,
    ScenarioRequest,
    ScenarioResponse,
    StockCorrelationRequest,
    StockCorrelationResponse,
)
from app.services import statistics as statistics_service
from app.services.statistics import (
    _run_scenario_cached,
    _run_stock_correlation_cached,
    _VersionedScenario,
    _VersionedStockCorrelation,
)
from app.services.stock_analysis import StockAnalysisError

router = APIRouter(
    prefix="/statistics",
    tags=["statistics"],
    dependencies=[Depends(get_current_user)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/scenario", response_model=ScenarioResponse)
async def scenario(
    payload: ScenarioRequest,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ScenarioResponse:
    """Historical replay of a persisted portfolio over an explicit window.

    Stacked value/weight/performance series plus a typed statistics rail —
    render-ready in one call. All fractional fields are decimal fractions
    (0.05 = 5%).
    """
    try:
        settings = get_settings()
        if settings.use_result_cache:
            pf = (
                await session.execute(
                    select(Portfolio)
                    .where(
                        Portfolio.id == payload.portfolio_id,
                        Portfolio.owner_sub == user.sub,
                    )
                    .options(selectinload(Portfolio.positions))
                )
            ).scalar_one_or_none()
            if pf is not None:
                versioned = _VersionedScenario(
                    request=payload,
                    portfolio_version=portfolio_version_hash(pf),
                    owner_sub=user.sub,
                )
                return await _run_scenario_cached(
                    session, versioned, max_points=settings.price_series_max_points
                )
        return await statistics_service.run_scenario(
            session,
            payload,
            max_points=settings.price_series_max_points,
            owner_sub=user.sub,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/beta", response_model=BetaResponse)
async def beta_scatter(
    payload: BetaRequest,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> BetaResponse:
    """Daily-return scatter + OLS regression of two pseudo-assets (y on x)."""
    try:
        return await statistics_service.run_beta(
            session,
            payload,
            max_points=get_settings().price_series_max_points,
            owner_sub=user.sub,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/correlation", response_model=CorrelationResponse)
async def rolling_correlation(
    payload: CorrelationRequest,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CorrelationResponse:
    """Rolling correlation of two pseudo-assets, warm from the window start."""
    try:
        return await statistics_service.run_rolling_correlation(
            session,
            payload,
            max_points=get_settings().price_series_max_points,
            owner_sub=user.sub,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/stock-correlation", response_model=StockCorrelationResponse)
async def stock_correlation(
    payload: StockCorrelationRequest,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> StockCorrelationResponse:
    """Pairwise correlation matrix of a portfolio's holdings (trailing window)."""
    try:
        if get_settings().use_result_cache:
            pf = (
                await session.execute(
                    select(Portfolio)
                    .where(
                        Portfolio.id == payload.portfolio_id,
                        Portfolio.owner_sub == user.sub,
                    )
                    .options(selectinload(Portfolio.positions))
                )
            ).scalar_one_or_none()
            if pf is not None:
                versioned = _VersionedStockCorrelation(
                    request=payload,
                    portfolio_version=portfolio_version_hash(pf),
                    owner_sub=user.sub,
                )
                return await _run_stock_correlation_cached(session, versioned)
        return await statistics_service.run_stock_correlation(
            session, payload, owner_sub=user.sub
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
