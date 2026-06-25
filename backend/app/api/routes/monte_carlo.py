"""Monte Carlo endpoint: POST /monte-carlo/projection (single instrument).

DB-first contract (same as the stock/portfolio/statistics routes): never calls
Tiingo for historical EOD data on the request path. The route stays thin:
validate -> run -> map
InsufficientDataError/StockAnalysisError to 404/422.

Error mapping (fail loud):
- request validation (ticker/statistic/n_simulations/horizons)  -> 422 (Pydantic)
- unknown ticker / no price rows                                 -> 404
- insufficient history for the projection                       -> 422
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.result_cache import result_cache, result_cache_key
from app.schemas.jobs import JobEnqueuedResponse
from app.schemas.monte_carlo import (
    MonteCarloRequest,
    MonteCarloResponse,
    PortfolioMonteCarloRequest,
    PortfolioMonteCarloResponse,
)
from app.services import jobs as jobs_service
from app.services.monte_carlo import run_monte_carlo, run_portfolio_monte_carlo
from app.services.stock_analysis import InsufficientDataError, StockAnalysisError

router = APIRouter(prefix="/monte-carlo", tags=["monte-carlo"])


@router.post("/projection", response_model=MonteCarloResponse)
async def project_monte_carlo(
    payload: MonteCarloRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MonteCarloResponse:
    """Block-bootstrap Monte Carlo projection for one instrument — single call.

    Returns the percentile distribution of the chosen statistic at the longest
    horizon, a per-horizon confidence fan, and the historical value with its
    bootstrap percentile rank. All drawdown/return fields are decimal fractions
    (0.05 = 5%); sharpe is unitless.
    """
    settings = get_settings()
    cache_key = (
        result_cache_key("monte_carlo", payload)
        if settings.use_result_cache and payload.seed is not None
        else None
    )
    if cache_key is not None:
        hit = await result_cache.get(cache_key)
        if hit is not None:
            return MonteCarloResponse.model_validate_json(hit)
    try:
        result = await run_monte_carlo(
            session,
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
    if cache_key is not None:
        await result_cache.set(
            cache_key,
            result.model_dump_json().encode("utf-8"),
            float(settings.result_cache_ttl_seconds),
        )
    return result


@router.post(
    "/portfolio",
    response_model=PortfolioMonteCarloResponse,
    responses={status.HTTP_202_ACCEPTED: {"model": JobEnqueuedResponse}},
)
async def project_portfolio_monte_carlo(
    payload: PortfolioMonteCarloRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PortfolioMonteCarloResponse | JSONResponse:
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

    When ``use_async_jobs`` is on and ``n_simulations`` is large, the run is
    enqueued as a job (HTTP 202 + job id), served via GET /jobs/{id}.
    """
    if jobs_service.should_run_async(n_simulations=payload.n_simulations):
        async def _runner(job_session: AsyncSession) -> PortfolioMonteCarloResponse:
            return await run_portfolio_monte_carlo(job_session, payload)

        job = await jobs_service.enqueue_job(
            session,
            kind=jobs_service.JOB_KIND_PORTFOLIO_MC,
            params_hash=jobs_service.params_hash(
                jobs_service.JOB_KIND_PORTFOLIO_MC, payload
            ),
            portfolio_id=None,
            runner=_runner,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=JobEnqueuedResponse(
                job_id=job.id, status=job.status, kind=job.kind
            ).model_dump(mode="json"),
        )
    settings = get_settings()
    cache_key = (
        result_cache_key("portfolio_mc", payload)
        if settings.use_result_cache and payload.seed is not None
        else None
    )
    if cache_key is not None:
        hit = await result_cache.get(cache_key)
        if hit is not None:
            return PortfolioMonteCarloResponse.model_validate_json(hit)
    try:
        result = await run_portfolio_monte_carlo(session, payload)
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if cache_key is not None:
        await result_cache.set(
            cache_key,
            result.model_dump_json().encode("utf-8"),
            float(settings.result_cache_ttl_seconds),
        )
    return result
