"""Macro regime endpoint — detector vote2of3 (Frente B, evolução do detector).

Endpoint FINO: lê ``regime_composite_daily`` materializada pelo worker
``regime_composite`` no data-lake (DB-first, nenhum cálculo aqui) e expõe o
estado + o breakdown dos 3 votos (credit/trend/nfci). O vote2of3 é o detector
PROMOVIDO (bate o credit-only em todas as métricas; neutro em 2022); o composite
legado por score foi refutado e não é consumido.
"""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datalake import get_datalake_session
from app.schemas.macro import (
    MacroRegimeResponse,
    RegimeFlipOut,
    RegimeHistoryOut,
    RegimeSignalOut,
    RegimeVotesOut,
)
from app.schemas.macro_scorecards import (
    DataFreshnessOut,
    DimensionOut,
    GlobalIndicatorsResponse,
    MacroRegionalResponse,
    RegionScorecardOut,
)
from app.services import macro_regime
from app.services import macro_scorecards

router = APIRouter(tags=["macro"])

DETECTOR_NAME = "vote2of3"


def _distance_pct(ratio: float | None, p20_5y: float | None) -> float | None:
    return 100.0 * (ratio - p20_5y) / p20_5y if p20_5y and ratio is not None else None


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
            distance_pct=_distance_pct(snapshot.ratio, snapshot.p20_5y),
            nfci=snapshot.nfci,
        ),
        recent_flips=[
            RegimeFlipOut(date=flip.date, state=flip.state)
            for flip in snapshot.recent_flips
        ],
        history=[
            RegimeHistoryOut(
                date=point.date,
                state=point.state,
                vote_count=point.vote_count,
                votes=RegimeVotesOut(
                    credit=point.credit_vote,
                    trend=point.trend_vote,
                    nfci=point.nfci_vote,
                ),
                signal=RegimeSignalOut(
                    ratio=point.ratio,
                    p20_5y=point.p20_5y,
                    distance_pct=_distance_pct(point.ratio, point.p20_5y),
                    nfci=point.nfci,
                ),
            )
            for point in snapshot.history
        ],
    )


_NOT_MATERIALIZED = (
    "Macro scorecards not materialized — the macro_ingestion worker has not "
    "populated macro_regional_snapshots yet."
)


@router.get("/macro/regional", response_model=MacroRegionalResponse)
async def get_macro_regional(
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
) -> MacroRegionalResponse:
    """Latest regional macro scorecards (composite + dimensions + freshness)."""
    snap = await macro_scorecards.fetch_macro_scorecards(datalake)
    if snap is None:
        raise HTTPException(status_code=404, detail=_NOT_MATERIALIZED)
    return MacroRegionalResponse(
        as_of_date=snap.as_of_date,
        regions={
            name: RegionScorecardOut(
                region=r.region,
                composite_score=r.composite_score,
                coverage=r.coverage,
                dimensions={
                    dim: DimensionOut(
                        score=d.score,
                        n_indicators=d.n_indicators,
                        indicators=d.indicators,
                    )
                    for dim, d in r.dimensions.items()
                },
                data_freshness={
                    sid: DataFreshnessOut(
                        last_date=f.last_date,
                        days_stale=f.days_stale,
                        weight=f.weight,
                        status=cast(Literal["fresh", "decaying", "stale"], f.status),
                    )
                    for sid, f in r.data_freshness.items()
                },
            )
            for name, r in snap.regions.items()
        },
    )


@router.get("/macro/global-indicators", response_model=GlobalIndicatorsResponse)
async def get_macro_global_indicators(
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
) -> GlobalIndicatorsResponse:
    """Latest global macro risk indicators (geopolitical/energy/commodity/USD)."""
    snap = await macro_scorecards.fetch_macro_scorecards(datalake)
    if snap is None:
        raise HTTPException(status_code=404, detail=_NOT_MATERIALIZED)
    g = snap.global_indicators
    return GlobalIndicatorsResponse(
        as_of_date=snap.as_of_date,
        geopolitical_risk_score=g.geopolitical_risk_score,
        energy_stress=g.energy_stress,
        commodity_stress=g.commodity_stress,
        usd_strength=g.usd_strength,
    )
