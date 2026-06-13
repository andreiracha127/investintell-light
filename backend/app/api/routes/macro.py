"""Macro regime endpoint (Frente B re-escopada — ADENDO §6 + backtest).

Endpoint FINO: lê o detector binário de stress de crédito materializado pelo
worker ``credit_regime`` no data-lake (DB-first, nenhum cálculo aqui) e expõe
estado + explicabilidade. O composite legado (macro_regime_snapshot) foi
REFUTADO pelo backtest (Sharpe 0,353 < B&H 0,418; 2022 pior que B&H) e não é
consumido como gatilho em nenhum caminho do Light.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datalake import get_datalake_session
from app.schemas.macro import (
    MacroRegimeResponse,
    RegimeBandsOut,
    RegimeFlipOut,
    RegimeSignalOut,
)
from app.services import macro_regime

router = APIRouter(tags=["macro"])

DETECTOR_NAME = "credit_stress_hyg_ief_p20_5y"


@router.get("/macro/regime", response_model=MacroRegimeResponse)
async def get_macro_regime(
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
    low_drawdown_mode: Annotated[
        bool | None,
        Query(
            description=(
                "Modo de cálculo do estado. None (default) usa a flag de env "
                "MACRO_REGIME_LOW_DRAWDOWN_MODE; true força o estado graduado "
                "(risk_on|caution|risk_off) do stress_score; false força binário."
            ),
        ),
    ] = None,
) -> MacroRegimeResponse:
    """Estado atual do detector de stress de crédito + explicabilidade.

    Default = binário (detector validado). Com ``low_drawdown_mode`` o ``state``
    vira o graduado, com estado intermediário ``caution`` perto dos limiares.
    """
    snapshot = await macro_regime.fetch_credit_regime(datalake)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Regime not materialized — the credit_regime worker has not "
                "populated credit_regime_daily yet."
            ),
        )
    low_drawdown = (
        macro_regime.LOW_DRAWDOWN_MODE_DEFAULT
        if low_drawdown_mode is None
        else low_drawdown_mode
    )
    graded = macro_regime.graded_state(snapshot.stress_score)
    state = graded if low_drawdown else snapshot.state
    distance_pct = (
        100.0 * (snapshot.ratio - snapshot.p20_5y) / snapshot.p20_5y
        if snapshot.p20_5y
        else None
    )
    return MacroRegimeResponse(
        detector=DETECTOR_NAME,
        mode="low_drawdown" if low_drawdown else "binary",
        state=state,
        binary_state=snapshot.state,
        graded_state=graded,
        stress_score=snapshot.stress_score,
        bands=RegimeBandsOut(
            caution_score=macro_regime.CAUTION_SCORE,
            risk_off_score=macro_regime.RISK_OFF_SCORE,
        ),
        as_of=snapshot.as_of,
        days_in_state=snapshot.days_in_state,
        last_flip=snapshot.last_flip,
        signal=RegimeSignalOut(
            ratio=snapshot.ratio,
            p20_5y=snapshot.p20_5y,
            p_exit_5y=snapshot.p_exit_5y,
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
