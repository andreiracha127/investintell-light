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


class MacroRegimeResponse(BaseModel):
    """Estado do detector vote2of3 (worker regime_composite) + breakdown dos votos.

    risk_off ⇔ ≥2 votos entre credit/trend/nfci. Estados binários — o composite
    por score ponderado (legado) foi refutado. O credit_regime segue materializado
    (é 1 dos votos); o composite é o detector promovido (Sharpe 0,549 / DD 25,3%).
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
