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
    ClassBandOut,
    GateBlockOut,
    MacroQuadrantOut,
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
from app.services import macro_regime, macro_scorecards, taa_bands

router = APIRouter(tags=["macro"])

DETECTOR_NAME = "vote2of3"

# Asset-class display order for the per-class regime bands (matches taa_bands).
_BAND_CLASS_ORDER = taa_bands.ASSET_CLASSES


def _distance_pct(ratio: float | None, p20_5y: float | None) -> float | None:
    return 100.0 * (ratio - p20_5y) / p20_5y if p20_5y and ratio is not None else None


def _score_state(score: float | None) -> str | None:
    """``"up"``/``"down"`` from a score sign; ``None`` when the score is ``None``."""
    if score is None:
        return None
    return "up" if score > 0.0 else "down"


async def _build_macro_quadrant(datalake: AsyncSession) -> MacroQuadrantOut:
    """Assemble the ADDITIVE COMBO macro block (gate + quadrant + bands + haven).

    Decision A (spec §9): the quadrant + growth/inflation scores are READ from
    ``regime_gate_daily`` via ``taa_bands.fetch_gate_regime`` (worker-materialized;
    no proxy compute here). The gate's risk-off dominates the band state; SLOWDOWN
    routes to the goldfix ``haven_tilt`` (then ``bands`` is empty). Best-effort:
    when the gate row is missing, ``gate``/``quadrant`` degrade to ``None`` and the
    combined regime falls back to RISK_ON with the 4 default class bands.
    """
    gate = await taa_bands.fetch_gate_regime(datalake)
    gate_state = gate.state if gate else None
    quadrant = gate.quadrant if gate else None
    growth_score = gate.growth_score if gate else None
    inflation_score = gate.inflation_score if gate else None

    regime = taa_bands.combined_regime(gate_state, quadrant)

    if regime == "STAG_GOLD":
        # SLOWDOWN haven: the conviction goldfix target (realized tilt depends on
        # the builder universe). Pass the full name set so all legs show.
        bands: list[ClassBandOut] = []
        haven_tilt = taa_bands.goldfix_target({"GLD", "VOOV", "QAI", "GCC", "BIL"})
    else:
        band_map, _smoothed = taa_bands.effective_class_bands(regime)
        bands = [
            ClassBandOut(asset_class=ac, min_weight=lo, max_weight=hi)
            for ac in _BAND_CLASS_ORDER
            for (lo, hi) in (band_map[ac],)
        ]
        haven_tilt = None

    gate_block = (
        GateBlockOut(
            as_of=gate.as_of,
            state=gate.state,
            trend_vote=gate.trend_vote,
            credit_vote=gate.credit_vote,
            drawdown_vote=gate.drawdown_vote,
            vote_count=gate.vote_count,
            dwell_days=gate.dwell_days,
        )
        if gate
        else None
    )

    return MacroQuadrantOut(
        as_of=gate.as_of if gate else None,
        quadrant=quadrant,
        growth_state=_score_state(growth_score),
        inflation_state=_score_state(inflation_score),
        growth_score=growth_score,
        inflation_score=inflation_score,
        combined_regime=regime,
        bands=bands,
        haven_tilt=haven_tilt,
        gate=gate_block,
    )


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
    # ADDITIVE COMBO block (Sprint 4): gate + quadrant + bands + haven tilt.
    # Best-effort — degrades to gate/quadrant None when regime_gate_daily is empty.
    macro_quadrant = await _build_macro_quadrant(datalake)

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
        macro_quadrant=macro_quadrant,
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
