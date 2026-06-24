"""Response schemas for GET /macro/regime (detector vote2of3 — Frente B)."""

import datetime as dt

from pydantic import BaseModel


class RegimeVotesOut(BaseModel):
    """Breakdown dos 3 votos do ensemble (explicabilidade: qual sinal está ativo)."""

    credit: bool  # HYG/IEF < p20 móvel 5y
    trend: bool  # SPY fechamento mensal < SMA 10 meses
    nfci: bool  # Chicago Fed NFCI > 0 (histerese)


class RegimeSignalOut(BaseModel):
    """Proveniência/explicabilidade do voto de crédito + valor do NFCI."""

    ratio: float | None  # HYG/IEF
    p20_5y: float | None  # gatilho do voto de crédito
    # Distância percentual do ratio ao p20 (positivo = folga até disparar o crédito).
    distance_pct: float | None
    nfci: float | None  # último valor NFCI (forward-filled)


class RegimeFlipOut(BaseModel):
    date: dt.date
    state: str


class RegimeHistoryOut(BaseModel):
    date: dt.date
    state: str
    vote_count: int
    votes: RegimeVotesOut
    signal: RegimeSignalOut


class ClassBandOut(BaseModel):
    """Per-sleeve ``(min, max)`` weight band from the quadrant policy."""

    asset_class: str  # one of quadrant_policy.STRUCTURAL_SLEEVES
    min_weight: float
    max_weight: float


class GateBlockOut(BaseModel):
    """Live debounced risk-off gate state + the 3 votes (trend/credit/drawdown)."""

    as_of: dt.date | None
    state: str  # 'risk_on' | 'risk_off'
    trend_vote: bool  # SPY < SMA200
    credit_vote: bool  # HYG/IEF < SMA60
    drawdown_vote: bool  # SPY 63d-drawdown >= 6%
    vote_count: int  # 0..3
    dwell_days: int  # days latched in the current state


class MacroQuadrantOut(BaseModel):
    """COMBO macro block: growth×inflation quadrant + gate + per-sleeve bands.

    ADDITIVE to the vote2of3 detector (decision O3 — the composite stays the
    headline). The quadrant + growth/inflation scores are READ from
    ``regime_gate_daily`` (decision A — worker-materialized; the backend lacks
    TIP/IEF). The quadrant and the gate are ORTHOGONAL (spec §12): ``bands`` are
    the per-sleeve ``policy_bands`` of ``QUADRANT_POLICIES["moderate"][quadrant]``
    (the display profile; informational, not the builder mandate), and the gate is
    reported in ``gate`` but does not fold into the bands here. ``bands`` is empty
    when the quadrant is not consumable. ``haven_tilt`` is a legacy field that is
    always ``None`` (the goldfix haven was retired with the orthogonal model).
    """

    as_of: dt.date | None
    quadrant: str | None  # recovery|expansion|slowdown|contraction|None
    growth_state: str | None  # up|down
    inflation_state: str | None  # up|down
    growth_score: float | None
    inflation_score: float | None
    bands: list[ClassBandOut]  # per-sleeve bands (empty when quadrant not consumable)
    haven_tilt: dict[str, float] | None  # legacy; always None (goldfix retired)
    gate: GateBlockOut | None  # None when regime_gate_daily empty


class MacroRegimeResponse(BaseModel):
    """Estado do detector vote2of3 (worker regime_composite) + breakdown dos votos.

    risk_off ⇔ ≥2 votos entre credit/trend/nfci. Estados binários — o composite
    por score ponderado (legado) foi refutado. O credit_regime segue materializado
    (é 1 dos votos); o composite é o detector promovido (Sharpe 0,549 / DD 25,3%).

    ``macro_quadrant`` (COMBO, Sprint 4) é um bloco ADITIVO: gate ao vivo +
    quadrante growth×inflation + bandas por classe + haven tilt (SLOWDOWN).
    """

    detector: str  # 'vote2of3'
    state: str  # 'risk_on' | 'risk_off'
    vote_count: int  # 0..3
    votes: RegimeVotesOut
    as_of: dt.date
    days_in_state: int
    last_flip: dt.date | None
    signal: RegimeSignalOut
    recent_flips: list[RegimeFlipOut]
    history: list[RegimeHistoryOut]
    macro_quadrant: MacroQuadrantOut | None = None
