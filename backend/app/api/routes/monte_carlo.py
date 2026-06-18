"""Monte Carlo endpoint: POST /monte-carlo/projection (single instrument).

DB-first contract (same as the stock/portfolio/statistics routes): never talks
to Tiingo directly — the service warms EOD via the shared error-mapping helper,
then serves from eod_prices. The route stays thin: validate -> run -> map
InsufficientDataError/StockAnalysisError to 404/422.

Error mapping (fail loud):
- request validation (ticker/statistic/n_simulations/horizons)  -> 422 (Pydantic)
- unknown ticker / no price rows                                 -> 404
- Tiingo rate limited / auth / server error                     -> 503/502 (warm helper)
- insufficient history for the projection                       -> 422
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.schemas.monte_carlo import (
    MonteCarloRequest,
    MonteCarloResponse,
    PortfolioMonteCarloRequest,
    PortfolioMonteCarloResponse,
)
from app.services.monte_carlo import run_monte_carlo, run_portfolio_monte_carlo
from app.services.stock_analysis import InsufficientDataError, StockAnalysisError
from app.tiingo.client import TiingoClient

router = APIRouter(prefix="/monte-carlo", tags=["monte-carlo"])


@router.post("/projection", response_model=MonteCarloResponse)
async def project_monte_carlo(
    payload: MonteCarloRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
) -> MonteCarloResponse:
    """Block-bootstrap Monte Carlo projection for one instrument — single call.

    Returns the percentile distribution of the chosen statistic at the longest
    horizon, a per-horizon confidence fan, and the historical value with its
    bootstrap percentile rank. All drawdown/return fields are decimal fractions
    (0.05 = 5%); sharpe is unitless.
    """
    try:
        return await run_monte_carlo(
            session,
            client,
            ticker=payload.ticker,
            statistic=payload.statistic,
            range_key=payload.range,
            n_simulations=payload.n_simulations,
            horizons=payload.horizons,
            risk_free_rate=payload.risk_free_rate,
            seed=payload.seed,
        )
    except InsufficientDataError as exc:
        message = str(exc)
        if message.startswith("No price data available"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/portfolio", response_model=PortfolioMonteCarloResponse)
async def project_portfolio_monte_carlo(
    payload: PortfolioMonteCarloRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PortfolioMonteCarloResponse:
    """Block-bootstrap Monte Carlo over a synthetic portfolio NAV.

    Builds the portfolio return series from the positions' common-history
    aligned returns (target weights held = implicit rebalancing) and runs the
    same block-bootstrap core as the single-instrument projection. Drawdown/
    return fields are decimal fractions (0.05 = 5%); sharpe is unitless.

    Error mapping (fail loud):
    - request shape / weight bounds / position count -> 422 (Pydantic)
    - unknown asset / no history in window           -> 422
    - insufficient common observations               -> 422
    - history too short for the requested horizon    -> 422
    """
    try:
        return await run_portfolio_monte_carlo(session, payload)
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
