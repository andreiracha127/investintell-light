"""Treasury fiscal-data endpoint (Tier 1 serving layer — DB-first).

Thin endpoint over treasury_data, materialized by the treasury_ingestion worker
in the data-lake (DB-first, no computation here). The ``category`` maps to the
worker's series_id prefix; empty result → 404.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datalake import get_datalake_session
from app.schemas.treasury_fiscal import (
    FiscalPointOut,
    FiscalResponse,
    FiscalSeriesOut,
)
from app.services import treasury_fiscal

router = APIRouter(tags=["macro"])

_CATEGORY_PREFIX: dict[str, str] = {
    "rates": "RATE_",
    "debt": "DEBT_",
    "auctions": "AUCTION_",
    "fx": "FX_",
    "interest": "INTEREST_",
}

FiscalCategory = Literal["rates", "debt", "auctions", "fx", "interest"]


@router.get("/macro/fiscal", response_model=FiscalResponse)
async def get_macro_fiscal(
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
    category: Annotated[FiscalCategory, Query()] = "rates",
    lookback_days: Annotated[int, Query(ge=1, le=3650)] = 365,
) -> FiscalResponse:
    """Treasury fiscal series for one category over the lookback window."""
    prefix = _CATEGORY_PREFIX[category]
    data = await treasury_fiscal.fetch_treasury_series(
        datalake, prefix=prefix, lookback_days=lookback_days
    )
    if not data.series:
        raise HTTPException(
            status_code=404,
            detail=(
                "Treasury fiscal data not materialized — the treasury_ingestion "
                f"worker has not populated treasury_data for category '{category}'."
            ),
        )
    return FiscalResponse(
        category=category,
        prefix=prefix,
        series=[
            FiscalSeriesOut(
                series_id=s.series_id,
                points=[
                    FiscalPointOut(
                        obs_date=p.obs_date, value=p.value, metadata=p.metadata
                    )
                    for p in s.points
                ],
            )
            for s in data.series
        ],
    )
