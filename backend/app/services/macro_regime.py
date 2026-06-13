"""Macro regime consumption service (Frente B re-escopada).

Lê ``credit_regime_daily`` — materializada no TimescaleDB Cloud pelo worker
``credit_regime`` (detector binário de stress de crédito HYG/IEF < p20 móvel
5 anos, replica do backtest validado: Sharpe 0,481 / DD 25,7%). O composite
legado (``macro_regime_snapshot``) foi REFUTADO pelo backtest como gatilho e
NÃO é consumido em lugar nenhum do Light.
"""

import datetime as dt
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RECENT_FLIPS = 6


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


# Modo low-drawdown (score graduado) — configurável por env, SEM deploy. Default
# = binário (detector validado). As bandas mapeiam o stress_score 0–100 do worker
# em estados intermediários (espelham o '≥50 crisis / ≥25 risk_off' do legado sem
# amplificação, perfil Sharpe 0,555 / Max DD 20,9%). Override por requisição via
# ``GET /macro/regime?low_drawdown_mode=true``.
LOW_DRAWDOWN_MODE_DEFAULT = _env_flag("MACRO_REGIME_LOW_DRAWDOWN_MODE", False)
CAUTION_SCORE = _env_float("MACRO_REGIME_CAUTION_SCORE", 25.0)
RISK_OFF_SCORE = _env_float("MACRO_REGIME_RISK_OFF_SCORE", 50.0)


@dataclass(frozen=True)
class RegimeFlip:
    date: dt.date
    state: str


@dataclass(frozen=True)
class CreditRegimeSnapshot:
    as_of: dt.date
    state: str
    ratio: float
    p20_5y: float | None
    hyg_close: float | None
    ief_close: float | None
    n_window: int
    days_in_state: int
    last_flip: dt.date | None
    recent_flips: list[RegimeFlip]
    stress_score: float | None = None
    p_exit_5y: float | None = None


def graded_state(
    stress_score: float | None,
    *,
    caution_score: float = CAUTION_SCORE,
    risk_off_score: float = RISK_OFF_SCORE,
) -> str:
    """Estado graduado (modo low-drawdown) por bandas do stress_score 0–100.

    Em vez do flip seco risk_on↔risk_off, classifica a PROXIMIDADE do ratio aos
    limites de percentil em estados intermediários (espelha o 'caution' do
    composite): score ≥ risk_off_score → risk_off; ≥ caution_score → caution;
    senão risk_on. None (warmup) → risk_on.
    """
    if stress_score is None:
        return "risk_on"
    if stress_score >= risk_off_score:
        return "risk_off"
    if stress_score >= caution_score:
        return "caution"
    return "risk_on"


_LATEST_SQL = text("""
    SELECT regime_date, state, ratio, p20_5y, p_exit_5y, stress_score,
           hyg_close, ief_close, n_window
    FROM credit_regime_daily
    ORDER BY regime_date DESC
    LIMIT 1
""")

_FLIPS_SQL = text("""
    SELECT regime_date, state
    FROM credit_regime_daily
    WHERE flip
    ORDER BY regime_date DESC
    LIMIT :limit
""")

_DAYS_IN_STATE_SQL = text("""
    SELECT count(*)
    FROM credit_regime_daily
    WHERE regime_date > COALESCE(
        (SELECT max(regime_date) FROM credit_regime_daily
         WHERE flip AND regime_date <= :as_of),
        '1900-01-01'::date
    ) AND regime_date <= :as_of
""")


async def fetch_credit_regime(
    datalake: AsyncSession,
) -> CreditRegimeSnapshot | None:
    """Estado atual do detector + explicabilidade, ou None se não materializado."""
    latest = (await datalake.execute(_LATEST_SQL)).first()
    if latest is None:
        return None
    flips = (
        await datalake.execute(_FLIPS_SQL, {"limit": RECENT_FLIPS})
    ).all()
    days_in_state = (
        await datalake.execute(
            _DAYS_IN_STATE_SQL, {"as_of": latest.regime_date}
        )
    ).scalar_one()

    def f(value: Any) -> float | None:
        return float(value) if value is not None else None

    return CreditRegimeSnapshot(
        as_of=latest.regime_date,
        state=latest.state,
        ratio=float(latest.ratio),
        p20_5y=f(latest.p20_5y),
        p_exit_5y=f(latest.p_exit_5y),
        stress_score=f(latest.stress_score),
        hyg_close=f(latest.hyg_close),
        ief_close=f(latest.ief_close),
        n_window=latest.n_window,
        # O dia do flip conta como o 1º dia no estado novo (regime_date > flip
        # exclui... o COUNT acima conta dias APÓS o último flip; o próprio dia
        # do flip pertence ao estado novo, então soma 1 quando houve flip).
        days_in_state=days_in_state + (1 if flips else 0),
        last_flip=flips[0].regime_date if flips else None,
        recent_flips=[
            RegimeFlip(date=row.regime_date, state=row.state) for row in flips
        ],
    )
