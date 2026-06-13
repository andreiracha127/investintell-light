"""Macro regime consumption service (Frente B re-escopada).

Lê ``credit_regime_daily`` — materializada no TimescaleDB Cloud pelo worker
``credit_regime`` (detector binário de stress de crédito HYG/IEF < p20 móvel
5 anos, replica do backtest validado: Sharpe 0,481 / DD 25,7%). O composite
legado (``macro_regime_snapshot``) foi REFUTADO pelo backtest como gatilho e
NÃO é consumido em lugar nenhum do Light.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RECENT_FLIPS = 6


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


_LATEST_SQL = text("""
    SELECT regime_date, state, ratio, p20_5y, hyg_close, ief_close, n_window
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
