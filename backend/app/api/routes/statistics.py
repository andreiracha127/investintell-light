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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
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

router = APIRouter(prefix="/statistics", tags=["statistics"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/scenario", response_model=ScenarioResponse)
async def scenario(
    payload: ScenarioRequest, session: SessionDep
) -> ScenarioResponse:
    """Historical replay of a persisted portfolio over an explicit window.

    Stacked value/weight/performance series plus a typed statistics rail —
    render-ready in one call. All fractional fields are decimal fractions
    (0.05 = 5%).
    """
    try:
        return await statistics_service.run_scenario(
            session,
            payload,
            max_points=get_settings().price_series_max_points,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/beta", response_model=BetaResponse)
async def beta_scatter(
    payload: BetaRequest, session: SessionDep
) -> BetaResponse:
    """Daily-return scatter + OLS regression of two pseudo-assets (y on x)."""
    try:
        return await statistics_service.run_beta(
            session,
            payload,
            max_points=get_settings().price_series_max_points,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/correlation", response_model=CorrelationResponse)
async def rolling_correlation(
    payload: CorrelationRequest, session: SessionDep
) -> CorrelationResponse:
    """Rolling correlation of two pseudo-assets, warm from the window start."""
    try:
        return await statistics_service.run_rolling_correlation(
            session,
            payload,
            max_points=get_settings().price_series_max_points,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/stock-correlation", response_model=StockCorrelationResponse)
async def stock_correlation(
    payload: StockCorrelationRequest, session: SessionDep
) -> StockCorrelationResponse:
    """Pairwise correlation matrix of a portfolio's holdings (trailing window)."""
    try:
        return await statistics_service.run_stock_correlation(session, payload)
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
