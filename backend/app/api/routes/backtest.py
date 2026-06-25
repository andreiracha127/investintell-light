"""Walk-forward backtest endpoint (Tier 2): POST /backtest/walk-forward.

Thin route over ``app.services.backtest``: validate (Pydantic) -> run the
service -> map domain/solver failures to 422 with the message verbatim.

Error mapping (fail loud):
- request shape / bounds (n_splits, cost_bps, asset count)  -> 422 (Pydantic)
- unknown asset / no history in window                      -> 422
- < MIN_COMMON_OBS common observations                      -> 422
- history too short for the requested folds                 -> 422
- bl_utility objective (no hindsight views in a backtest)   -> 422
- solver not 'optimal' / infeasible constraints             -> 422
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.backtest import WalkForwardRequest, WalkForwardResponse
from app.schemas.jobs import JobEnqueuedResponse
from app.services import backtest as backtest_service
from app.services import jobs as jobs_service
from app.services.backtest import BacktestError

router = APIRouter(prefix="/backtest", tags=["backtest"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/walk-forward",
    response_model=WalkForwardResponse,
    responses={status.HTTP_202_ACCEPTED: {"model": JobEnqueuedResponse}},
)
async def walk_forward(
    payload: WalkForwardRequest, session: SessionDep
) -> WalkForwardResponse | JSONResponse:
    """Walk-forward / out-of-sample backtest of a mu-free objective.

    Re-optimizes the objective on each expanding TimeSeriesSplit train fold and
    scores the held-out test fold (Sharpe, CVaR 95, max drawdown), folding in a
    one-way transaction cost on the L1 weight change vs the previous fold. The
    response reports per-fold metrics plus the ``positive_folds`` consistency
    count. All fractional fields are decimal fractions (0.05 = 5%).

    When ``use_async_jobs`` is on and ``n_splits`` is large, the computation is
    enqueued as a job (HTTP 202 + job id) and served via GET /jobs/{id}; the
    synchronous path (cached) is otherwise unchanged.
    """
    try:
        if jobs_service.should_run_async(n_splits=payload.n_splits):
            async def _runner(job_session: AsyncSession) -> WalkForwardResponse:
                return await backtest_service.run_walk_forward_backtest(
                    job_session, payload
                )

            job = await jobs_service.enqueue_job(
                session,
                kind=jobs_service.JOB_KIND_WALK_FORWARD,
                params_hash=jobs_service.params_hash(
                    jobs_service.JOB_KIND_WALK_FORWARD, payload
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
        return await backtest_service.run_walk_forward_backtest(session, payload)
    except BacktestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
