"""Macro regime endpoint (Frente B re-escopada — ADENDO §6 + backtest).

Endpoint FINO: lê o detector binário de stress de crédito materializado pelo
worker ``credit_regime`` no data-lake (DB-first, nenhum cálculo aqui) e expõe
estado + explicabilidade. O composite legado (macro_regime_snapshot) foi
REFUTADO pelo backtest (Sharpe 0,353 < B&H 0,418; 2022 pior que B&H) e não é
consumido como gatilho em nenhum caminho do Light.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datalake import get_datalake_session
from app.schemas.macro import (
    MacroRegimeResponse,
    RegimeFlipOut,
    RegimeSignalOut,
)
from app.services import macro_regime

router = APIRouter(tags=["macro"])

DETECTOR_NAME = "credit_stress_hyg_ief_p20_5y"


@router.get("/macro/regime", response_model=MacroRegimeResponse)
async def get_macro_regime(
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
) -> MacroRegimeResponse:
    """Estado atual do detector de stress de crédito + explicabilidade."""
    snapshot = await macro_regime.fetch_credit_regime(datalake)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Regime not materialized — the credit_regime worker has not "
                "populated credit_regime_daily yet."
            ),
        )
    distance_pct = (
        100.0 * (snapshot.ratio - snapshot.p20_5y) / snapshot.p20_5y
        if snapshot.p20_5y
        else None
    )
    return MacroRegimeResponse(
        detector=DETECTOR_NAME,
        state=snapshot.state,
        as_of=snapshot.as_of,
        days_in_state=snapshot.days_in_state,
        last_flip=snapshot.last_flip,
        signal=RegimeSignalOut(
            ratio=snapshot.ratio,
            p20_5y=snapshot.p20_5y,
            distance_pct=distance_pct,
            hyg_close=snapshot.hyg_close,
            ief_close=snapshot.ief_close,
            n_window=snapshot.n_window,
        ),
        recent_flips=[
            RegimeFlipOut(date=flip.date, state=flip.state)
            for flip in snapshot.recent_flips
        ],
    )
