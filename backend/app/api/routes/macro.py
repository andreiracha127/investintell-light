"""Macro regime endpoint — detector vote2of3 (Frente B, evolução do detector).

Endpoint FINO: lê ``regime_composite_daily`` materializada pelo worker
``regime_composite`` no data-lake (DB-first, nenhum cálculo aqui) e expõe o
estado + o breakdown dos 3 votos (credit/trend/nfci). O vote2of3 é o detector
PROMOVIDO (bate o credit-only em todas as métricas; neutro em 2022); o composite
legado por score foi refutado e não é consumido.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datalake import get_datalake_session
from app.schemas.macro import (
    MacroRegimeResponse,
    RegimeFlipOut,
    RegimeSignalOut,
    RegimeVotesOut,
)
from app.services import macro_regime

router = APIRouter(tags=["macro"])

DETECTOR_NAME = "vote2of3"


@router.get("/macro/regime", response_model=MacroRegimeResponse)
async def get_macro_regime(
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
) -> MacroRegimeResponse:
    """Estado atual do detector vote2of3 + breakdown dos votos + explicabilidade."""
    snapshot = await macro_regime.fetch_composite_regime(datalake)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Regime not materialized — the regime_composite worker has not "
                "populated regime_composite_daily yet."
            ),
        )
    distance_pct = (
        100.0 * (snapshot.ratio - snapshot.p20_5y) / snapshot.p20_5y
        if snapshot.p20_5y and snapshot.ratio is not None
        else None
    )
    return MacroRegimeResponse(
        detector=DETECTOR_NAME,
        state=snapshot.state,
        vote_count=snapshot.vote_count,
        votes=RegimeVotesOut(
            credit=snapshot.credit_vote,
            trend=snapshot.trend_vote,
            nfci=snapshot.nfci_vote,
        ),
        as_of=snapshot.as_of,
        days_in_state=snapshot.days_in_state,
        last_flip=snapshot.last_flip,
        signal=RegimeSignalOut(
            ratio=snapshot.ratio,
            p20_5y=snapshot.p20_5y,
            distance_pct=distance_pct,
            nfci=snapshot.nfci,
        ),
        recent_flips=[
            RegimeFlipOut(date=flip.date, state=flip.state)
            for flip in snapshot.recent_flips
        ],
    )
