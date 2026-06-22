"""Correlation-regime / contagion endpoint (T3F): POST /correlation-regime.

Thin route over ``app.services.correlation_regime``: resolve the request asset
refs (explicit list OR universe spec, reusing the builder's fund selection),
run the service over the optimizer's aligned (T,N) matrix, and map any domain
ValueError (insufficient history, unknown asset, NaN) to HTTP 422.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.result_cache import result_cache, result_cache_key
from app.optimizer import data as optimizer_data
from app.schemas.builder import EquityRefIn, FundRefIn
from app.schemas.correlation_regime import CorrelationRegimeOut, CorrelationRegimeRequest
from app.services import correlation_regime as cr_service
from app.services import portfolio_builder

router = APIRouter(tags=["correlation-regime"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _to_data_ref(ref: FundRefIn | EquityRefIn) -> optimizer_data.AssetRef:
    if isinstance(ref, FundRefIn):
        return optimizer_data.FundAssetRef(id=ref.id)
    return optimizer_data.EquityAssetRef(ticker=ref.ticker.upper())


@router.post("/correlation-regime", response_model=CorrelationRegimeOut)
async def correlation_regime(
    payload: CorrelationRegimeRequest, session: SessionDep
) -> CorrelationRegimeOut:
    """Correlation-regime + contagion analysis over an explicit asset list or a
    resolved fund universe. Decimal-fraction scale. Domain failures → 422.
    """
    try:
        cache_key = (
            result_cache_key("correlation_regime", payload)
            if get_settings().use_result_cache
            else None
        )
        if cache_key is not None:
            hit = await result_cache.get(cache_key)
            if hit is not None:
                return CorrelationRegimeOut.model_validate_json(hit)
        if payload.assets is not None:
            refs = [_to_data_ref(ref) for ref in payload.assets]
        else:
            assert payload.universe is not None  # validator guarantees one
            spec = payload.universe
            candidates = await optimizer_data.select_universe_funds(
                session,
                portfolio_builder._filters_from_spec(spec),
                rank_by=spec.rank_by,
                rank_dir=spec.rank_dir,
                max_assets=spec.max_assets,
                require_aum=False,
                include_ids=spec.include_instrument_ids,
                window_days=payload.window_days,
            )
            if len(candidates) < 2:
                raise ValueError(
                    f"universe selection matched {len(candidates)} fund(s) — relax the "
                    "filters or widen the window (at least 2 are required)"
                )
            refs = [optimizer_data.FundAssetRef(id=c.id) for c in candidates]
        result = await cr_service.run_correlation_regime(
            session, refs, window_days=payload.window_days
        )
        if cache_key is not None:
            await result_cache.set(
                cache_key,
                result.model_dump_json().encode("utf-8"),
                float(get_settings().result_cache_ttl_seconds),
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
