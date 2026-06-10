from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.db import AsyncSessionLocal
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health including database connectivity.

    Returns HTTP 503 with an error detail if the database is unreachable.
    Never returns 200 with a degraded payload — fail loud.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unreachable: {exc}",
        ) from exc

    return HealthResponse(status="ok", database="ok")
