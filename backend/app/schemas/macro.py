"""Response schemas for GET /macro/regime (Frente B re-escopada)."""

import datetime as dt

from pydantic import BaseModel


class RegimeSignalOut(BaseModel):
    """Explicabilidade do detector: ratio vs threshold + proveniência."""

    ratio: float
    p20_5y: float | None
    # Distância percentual do ratio ao threshold (positivo = acima do p20,
    # i.e. folga até disparar; negativo = abaixo, em stress).
    distance_pct: float | None
    hyg_close: float | None
    ief_close: float | None
    n_window: int


class RegimeFlipOut(BaseModel):
    date: dt.date
    state: str


class MacroRegimeResponse(BaseModel):
    """Estado do detector binário de stress de crédito (worker credit_regime).

    O composite legado (macro_regime_snapshot) foi refutado pelo backtest e
    não alimenta esta resposta nem qualquer gatilho de rebalanceamento.
    """

    detector: str  # 'credit_stress_hyg_ief_p20_5y'
    state: str  # 'risk_on' | 'risk_off'
    as_of: dt.date
    days_in_state: int
    last_flip: dt.date | None
    signal: RegimeSignalOut
    recent_flips: list[RegimeFlipOut]
