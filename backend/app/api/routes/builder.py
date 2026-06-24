"""Portfolio builder endpoint (F8.3/F8.4): POST /builder/optimize.

Thin route over ``app.services.portfolio_builder``: validate (Pydantic) → run
the service → map domain/solver failures to 422 with the message verbatim.

Error mapping (fail loud, never silently empty):
- request shape (assets/views/constraints bounds)      -> 422 (Pydantic)
- unknown asset / no history in window                 -> 422
- < 400 common observations                            -> 422
- views with equities or funds without AUM             -> 422
- linearly dependent views (rank-deficient P)          -> 422
- solver not 'optimal' / infeasible constraints        -> 422
"""

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import datalake as datalake_module
from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.datalake import get_optional_datalake_session
from app.core.db import AsyncSessionLocal, get_session
from app.schemas.builder import (
    OptimizeJobAccepted,
    OptimizeJobStatus,
    OptimizeRequest,
    OptimizeResponse,
    SaveRequest,
    SaveResponse,
)
from app.services import builder_save, optimize_jobs, portfolio_builder
from app.services.portfolio_builder import BuilderError

router = APIRouter(prefix="/builder", tags=["builder"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
DatalakeDep = Annotated[AsyncSession | None, Depends(get_optional_datalake_session)]


async def _run_optimize_job(job_id: uuid.UUID, payload: OptimizeRequest) -> None:
    """Background runner for a broad-universe optimize job.

    Opens its OWN AsyncSession (the request's session is already closed by the
    time this runs) and ALSO opens an optional read-only data-lake session —
    mirroring ``get_optional_datalake_session``: a session when
    ``DATALAKE_DB_URL`` is configured, else None. The data-lake backs the
    look-through holdings used by the ``overlap_cap`` constraint and the regime
    read, so passing it (rather than None) is what makes those features work in
    broad-universe mode. A missing DSN still degrades gracefully (datalake=None).

    Drives the job through running -> succeeded|failed, committing after each
    state change so a poller sees progress and a crash never leaves the job
    stuck in ``running``.
    """
    async with AsyncSessionLocal() as session:
        if get_settings().datalake_db_url:
            async with datalake_module._get_sessionmaker()() as datalake_session:
                await _drive_optimize_job(session, job_id, payload, datalake_session)
        else:
            await _drive_optimize_job(session, job_id, payload, None)


async def _drive_optimize_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    payload: OptimizeRequest,
    datalake: AsyncSession | None,
) -> None:
    """Mark running, run the optimizer with the (optional) data-lake session,
    and persist the terminal state. Split out so the data-lake session can be
    opened (or skipped) once and reused for the whole job lifecycle."""
    await optimize_jobs.mark_running(session, job_id)
    await session.commit()
    try:
        result = await portfolio_builder.run_optimize(
            session, payload, datalake=datalake
        )
    except BuilderError as exc:
        await optimize_jobs.mark_failed(
            session, job_id, portfolio_builder.humanize_error(str(exc))
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — never leave a job hung in 'running'
        await optimize_jobs.mark_failed(session, job_id, str(exc))
        await session.commit()
    else:
        await optimize_jobs.mark_succeeded(
            session, job_id, result.model_dump(mode="json")
        )
        await session.commit()


@router.post("/optimize")
async def optimize(
    payload: OptimizeRequest,
    session: SessionDep,
    datalake: DatalakeDep,
    response: Response,
) -> OptimizeResponse | OptimizeJobAccepted:
    """Optimize weights over a mixed fund/equity universe.

    Default objective is ``min_cvar`` (Rockafellar–Uryasev, α=0.95) on raw
    historical scenarios. With Black-Litterman ``views``, scenarios are
    re-centered on the posterior μ_BL and floored at the equilibrium return;
    ``bl_utility`` selects the explicit max-utility objective instead;
    ``max_return_cvar`` maximizes BL-posterior return under a CVaR cap, which
    is tightened in a risk_off credit regime when the data-lake is configured.
    All fractional fields are decimal fractions (0.05 = 5%).

    Broad-universe requests (``universe.broad_universe``) run ASYNCHRONOUSLY:
    the request is persisted as a job, a background task advances it, and the
    response is 202 + ``{job_id}`` to poll via ``GET /optimize/{job_id}``.
    Every other request shape stays synchronous (200 + OptimizeResponse).
    """
    if payload.universe is not None and payload.universe.broad_universe:
        # org-scoped column is nullable while /optimize is public + single-tenant.
        job = await optimize_jobs.create_job(
            session, None, payload.model_dump(mode="json")
        )
        await session.commit()
        # Fire-and-forget: the task opens its own session (see _run_optimize_job).
        asyncio.create_task(_run_optimize_job(job.id, payload))
        response.status_code = status.HTTP_202_ACCEPTED
        return OptimizeJobAccepted(job_id=str(job.id))

    try:
        return await portfolio_builder.run_optimize(session, payload, datalake=datalake)
    except BuilderError as exc:
        raise HTTPException(
            status_code=422, detail=portfolio_builder.humanize_error(str(exc))
        ) from exc


@router.get("/optimize/{job_id}", response_model=OptimizeJobStatus)
async def optimize_job_status(
    job_id: uuid.UUID, session: SessionDep
) -> OptimizeJobStatus:
    """Poll a broad-universe optimize job; 404 if the id is unknown.

    Returns the lifecycle ``status`` and, when terminal, the full
    ``result`` (succeeded) or the verbatim ``error`` message (failed).
    """
    job = await optimize_jobs.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="optimize job not found")
    return OptimizeJobStatus(
        status=job.status,
        result=OptimizeResponse(**job.result) if job.result is not None else None,
        error=job.error,
    )


@router.post(
    "/save",
    response_model=SaveResponse,
    status_code=201,
    dependencies=[Depends(get_current_user)],
)
async def save(
    payload: SaveRequest,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SaveResponse:
    """Persist a builder proposal as a real portfolio (F8.5 + F8.6b).

    Each weight is sized at the asset's REFERENCE price (equities: latest
    adj_close; funds: latest NAV) against ``notional_usd`` — unless it
    carries a ``fill_price``, which sizes the position and (with the
    commission) defines the real cost basis (basis='executed'). Fund weights
    may select a share class via ``class_ticker`` (same instrument; priced
    with the series NAV as a proxy). The portfolio is tagged
    origin='builder'. Domain failures — asset without a price, fund without
    a ticker, invalid class, duplicate portfolio name, weight too small for
    the notional — are 422 verbatim.
    """
    try:
        return await builder_save.run_save(session, payload, user.sub, user.org_id)
    except BuilderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
