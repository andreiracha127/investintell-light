"""Statistics-group endpoints (F5): scenario replay, beta scatter, rolling
correlation, holdings correlation matrix.

DB-first contract, same as everywhere: routes never talk to Tiingo directly —
the service orchestrators run the EOD ensure (shared error mapping) and read
from eod_prices. Routes are thin: validate (Pydantic) → run the service → map
``StockAnalysisError`` to 422.

Replay semantics: a persisted portfolio (the scenario subject, or a
``kind='portfolio'`` pseudo-asset) is replayed at its CURRENT quantities held
fixed over the window — buy-and-hold historical replay, not a reconstruction
of past trades. See ``app.services.statistics``.

Error mapping (fail loud, never silently empty):
- request validation (dates/window/AssetRef shape)  -> 422 (Pydantic)
- unknown portfolio / unknown ticker                -> 404
- empty portfolio / insufficient history /
  undefined statistic / oversized window            -> 422
- Tiingo rate limited                               -> 503
- Tiingo auth misconfiguration / server error       -> 502
- cold-ticker cap exceeded                          -> 422
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
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
from app.services.stock_analysis import StockAnalysisError
from app.tiingo.client import TiingoClient

router = APIRouter(
    prefix="/statistics",
    tags=["statistics"],
    dependencies=[Depends(get_current_user)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientDep = Annotated[TiingoClient, Depends(get_tiingo_client)]


@router.post("/scenario", response_model=ScenarioResponse)
async def scenario(
    payload: ScenarioRequest,
    session: SessionDep,
    client: ClientDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ScenarioResponse:
    """Historical replay of a persisted portfolio over an explicit window.

    Stacked value/weight/performance series plus a typed statistics rail —
    render-ready in one call. All fractional fields are decimal fractions
    (0.05 = 5%).
    """
    try:
        return await statistics_service.run_scenario(
            session,
            client,
            payload,
            max_points=get_settings().price_series_max_points,
            owner_sub=user.sub,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/beta", response_model=BetaResponse)
async def beta_scatter(
    payload: BetaRequest,
    session: SessionDep,
    client: ClientDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> BetaResponse:
    """Daily-return scatter + OLS regression of two pseudo-assets (y on x)."""
    try:
        return await statistics_service.run_beta(
            session,
            client,
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
    client: ClientDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CorrelationResponse:
    """Rolling correlation of two pseudo-assets, warm from the window start."""
    try:
        return await statistics_service.run_rolling_correlation(
            session,
            client,
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
    client: ClientDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> StockCorrelationResponse:
    """Pairwise correlation matrix of a portfolio's holdings (trailing window)."""
    try:
        return await statistics_service.run_stock_correlation(
            session,
            client,
            payload,
            owner_sub=user.sub,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
