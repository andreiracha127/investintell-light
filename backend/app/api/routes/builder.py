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

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.builder import (
    OptimizeRequest,
    OptimizeResponse,
    SaveRequest,
    SaveResponse,
)
from app.services import builder_save, portfolio_builder
from app.services.portfolio_builder import BuilderError

router = APIRouter(prefix="/builder", tags=["builder"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize(payload: OptimizeRequest, session: SessionDep) -> OptimizeResponse:
    """Optimize weights over a mixed fund/equity universe.

    Default objective is ``min_cvar`` (Rockafellar–Uryasev, α=0.95) on raw
    historical scenarios. With Black-Litterman ``views``, scenarios are
    re-centered on the posterior μ_BL and floored at the equilibrium return;
    ``bl_utility`` selects the explicit max-utility objective instead.
    All fractional fields are decimal fractions (0.05 = 5%).
    """
    try:
        return await portfolio_builder.run_optimize(session, payload)
    except BuilderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/save", response_model=SaveResponse, status_code=201)
async def save(payload: SaveRequest, session: SessionDep) -> SaveResponse:
    """Persist a builder proposal as a real portfolio (F8.5).

    Each weight is sized at the asset's SPOT price (equities: latest
    adj_close; funds: latest NAV, stored under the fund's ticker) against
    ``notional_usd``; the spot price becomes the position's cost basis.
    Domain failures — asset without a price, fund without a ticker, duplicate
    portfolio name, weight too small for the notional — are 422 verbatim.
    """
    try:
        return await builder_save.run_save(session, payload)
    except BuilderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
