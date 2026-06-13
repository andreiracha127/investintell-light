"""Macro regime consumption service (Frente B — evolução do detector).

Lê o data-lake (TimescaleDB Cloud), DB-first, sem cálculo aqui:
  * ``regime_composite_daily`` — detector PROMOVIDO vote2of3 (worker
    ``regime_composite``; risk_off ⇔ ≥2 votos credit/trend/nfci, Sharpe 0,549 /
    DD 25,3%). É o que ``GET /macro/regime`` serve e o gate de rebalance consome.
  * ``credit_regime_daily`` — detector binário de stress de crédito (worker
    ``credit_regime``), mantido como 1 dos votos; leitor disponível abaixo.
O composite legado por score (``macro_regime_snapshot``) segue REFUTADO.
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
    stress_score: float | None = None
    p_exit_5y: float | None = None


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


# ──────────────────────────────────────────────────────────────────────────────
# Composite vote2of3 — detector PROMOVIDO (worker regime_composite)
# ──────────────────────────────────────────────────────────────────────────────
# risk_off ⇔ ≥2 votos entre credit (HYG/IEF<p20), trend (SPY<SMA10m) e nfci. Bate o
# credit-only em todas as métricas (Sharpe 0,549 / DD 25,3% / CAGR 12,30% / 16 flips)
# e fica neutro em 2022. O credit_regime segue materializado (é 1 dos votos).
@dataclass(frozen=True)
class CompositeRegimeSnapshot:
    as_of: dt.date
    state: str
    vote_count: int
    credit_vote: bool
    trend_vote: bool
    nfci_vote: bool
    ratio: float | None
    p20_5y: float | None
    nfci: float | None
    days_in_state: int
    last_flip: dt.date | None
    recent_flips: list[RegimeFlip]


_COMPOSITE_LATEST_SQL = text("""
    SELECT regime_date, state, vote_count, credit_vote, trend_vote, nfci_vote,
           ratio, p20_5y, nfci
    FROM regime_composite_daily
    ORDER BY regime_date DESC
    LIMIT 1
""")

_COMPOSITE_FLIPS_SQL = text("""
    SELECT regime_date, state
    FROM regime_composite_daily
    WHERE flip
    ORDER BY regime_date DESC
    LIMIT :limit
""")

_COMPOSITE_DAYS_IN_STATE_SQL = text("""
    SELECT count(*)
    FROM regime_composite_daily
    WHERE regime_date > COALESCE(
        (SELECT max(regime_date) FROM regime_composite_daily
         WHERE flip AND regime_date <= :as_of),
        '1900-01-01'::date
    ) AND regime_date <= :as_of
""")


async def fetch_composite_regime(
    datalake: AsyncSession,
) -> CompositeRegimeSnapshot | None:
    """Estado do detector vote2of3 + breakdown dos votos, ou None se não materializado."""
    latest = (await datalake.execute(_COMPOSITE_LATEST_SQL)).first()
    if latest is None:
        return None
    flips = (
        await datalake.execute(_COMPOSITE_FLIPS_SQL, {"limit": RECENT_FLIPS})
    ).all()
    days_in_state = (
        await datalake.execute(
            _COMPOSITE_DAYS_IN_STATE_SQL, {"as_of": latest.regime_date}
        )
    ).scalar_one()

    def f(value: Any) -> float | None:
        return float(value) if value is not None else None

    return CompositeRegimeSnapshot(
        as_of=latest.regime_date,
        state=latest.state,
        vote_count=latest.vote_count,
        credit_vote=latest.credit_vote,
        trend_vote=latest.trend_vote,
        nfci_vote=latest.nfci_vote,
        ratio=f(latest.ratio),
        p20_5y=f(latest.p20_5y),
        nfci=f(latest.nfci),
        days_in_state=days_in_state + (1 if flips else 0),
        last_flip=flips[0].regime_date if flips else None,
        recent_flips=[
            RegimeFlip(date=row.regime_date, state=row.state) for row in flips
        ],
    )
