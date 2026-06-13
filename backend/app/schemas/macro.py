"""Response schemas for GET /macro/regime (Frente B re-escopada)."""

import datetime as dt

from pydantic import BaseModel


class RegimeSignalOut(BaseModel):
    """Explicabilidade do detector: ratio vs thresholds + proveniência."""

    ratio: float
    p20_5y: float | None
    # Banda de saída da histerese (p25 default; == p20_5y se exit == entry).
    p_exit_5y: float | None = None
    # Distância percentual do ratio ao threshold de entrada (positivo = acima
    # do p20, i.e. folga até disparar; negativo = abaixo, em stress).
    distance_pct: float | None
    hyg_close: float | None
    ief_close: float | None
    n_window: int


class RegimeBandsOut(BaseModel):
    """Bandas de score do modo low-drawdown (graduado)."""

    caution_score: float  # ≥ → caution
    risk_off_score: float  # ≥ → risk_off


class RegimeFlipOut(BaseModel):
    date: dt.date
    state: str


class MacroRegimeResponse(BaseModel):
    """Estado do detector de stress de crédito (worker credit_regime).

    Default = ``mode='binary'`` (detector validado, risk_on|risk_off). Com
    ``?low_drawdown_mode=true`` (ou env) o ``state`` passa a ser o graduado
    (risk_on|caution|risk_off) derivado do ``stress_score`` 0–100, priorizando
    a suavização da curva de capital. O composite legado (macro_regime_snapshot)
    segue refutado e não alimenta nenhum gatilho de rebalanceamento.
    """

    detector: str  # 'credit_stress_hyg_ief_p20_5y'
    mode: str  # 'binary' | 'low_drawdown'
    state: str  # 'risk_on' | 'caution' | 'risk_off' (caution só no low_drawdown)
    binary_state: str  # estado binário do worker (sempre, p/ referência)
    graded_state: str  # classificação graduada do stress_score (sempre, informativa)
    stress_score: float | None  # 0–100; None no warmup
    bands: RegimeBandsOut
    as_of: dt.date
    days_in_state: int
    last_flip: dt.date | None
    signal: RegimeSignalOut
    recent_flips: list[RegimeFlipOut]
