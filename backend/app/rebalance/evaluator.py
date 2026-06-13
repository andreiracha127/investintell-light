"""Rebalance evaluator (Frente A — A2/A4).

Dado portfólio + política, decide ``no_action | drift_alert | proposal`` e
computa drift por posição, pesos-alvo, diff e turnover. Desenho do doc de
research 2026-06-11 §2 (espelha a mecânica LEAN — gatilhos ortogonais):

  proposal     — gatilho calendário venceu OU gatilho macro disparou
  drift_alert  — banda de tolerância (abs OU rel) violada por alguma posição
  no_action    — nenhum gatilho

Pesos-alvo (A4): o MESMO serviço de otimização do builder
(``app.services.portfolio_builder.run_optimize``), objetivo ``min_cvar``
default, sem views — μ-free puro, como o builder sem views. Pesos correntes
e alvo são frações do VALOR INVESTIDO (caixa fora da otimização; o caixa do
portfólio é reportado à parte pelos endpoints).

Gatilho macro (B4): lê o detector binário de stress de crédito da frente B
(``credit_regime_daily`` no data-lake, worker ``credit_regime``). Dispara
quando habilitado na política E o estado é ``risk_off`` E o flip ainda não
foi processado (last_flip posterior ao last_evaluated_at). O composite
legado (macro_regime_snapshot) NÃO é consumido.

NUNCA auto-executa: o produto é advisory — proposta é apresentada, decisão é
do usuário. O job agendado (scripts/evaluate_rebalance.py) só avalia e
carimba ``last_evaluated_at``; o preview on-demand não carimba nada.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fund import Fund
from app.models.portfolio import Portfolio
from app.models.rebalance import RebalancePolicy
from app.schemas.builder import (
    ConstraintsIn,
    EquityRefIn,
    FundRefIn,
    Objective,
    OptimizeRequest,
)
from app.schemas.rebalance import Decision, Frequency
from app.services import portfolio_builder, portfolio_crud
from app.services.macro_regime import (
    CompositeRegimeSnapshot,
    fetch_composite_regime,
)

FREQUENCY_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 91}

DEFAULT_FREQUENCY: Frequency = "monthly"
DEFAULT_BAND_ABS = 0.05   # 5 p.p. (fração decimal)
DEFAULT_BAND_REL = 0.25   # 25% do peso-alvo
DEFAULT_OBJECTIVE: Objective = "min_cvar"
BUILDER_CAP = 0.25        # cap default do builder (ConstraintsIn)


class RebalanceError(ValueError):
    """Avaliação impossível (posições insuficientes, dados ausentes…)."""


@dataclass(frozen=True)
class PositionDrift:
    ticker: str
    current_weight: float
    target_weight: float
    drift_abs: float            # current − target (fração decimal, sinal)
    drift_rel: float | None     # |drift_abs| / target; None quando target = 0
    breach: bool


@dataclass(frozen=True)
class Proposal:
    weights: dict[str, float]   # ticker → peso-alvo (fração do investido)
    turnover_pct: float         # 0.5 × Σ|diff| × 100
    objective: str
    status: str


@dataclass(frozen=True)
class Evaluation:
    decision: Decision          # 'no_action' | 'drift_alert' | 'proposal'
    calendar_due: bool
    macro_triggered: bool
    drifts: list[PositionDrift]
    proposal: Proposal
    invested_value: float
    cash: float


# ---------------------------------------------------------------------------
# Pure decision core
# ---------------------------------------------------------------------------


def calendar_due(
    last_evaluated_at: dt.datetime | None, frequency: str, now: dt.datetime
) -> bool:
    """Gatilho calendário: venceu o intervalo da frequência (ou nunca avaliado)."""
    interval_days = FREQUENCY_DAYS[frequency]  # KeyError loud em freq inválida
    if last_evaluated_at is None:
        return True
    return (now - last_evaluated_at).days >= interval_days


def macro_triggered(
    enabled: bool,
    state: str | None,
    last_flip: dt.date | None,
    last_evaluated_at: dt.datetime | None,
) -> bool:
    """Gatilho macro: risk_off com flip ainda não processado pela avaliação."""
    if not enabled or state != "risk_off":
        return False
    if last_evaluated_at is None or last_flip is None:
        return True
    return last_flip > last_evaluated_at.date()


def compute_drifts(
    current: dict[str, float],
    target: dict[str, float],
    band_abs: float,
    band_rel: float,
) -> list[PositionDrift]:
    """Drift por posição contra as duas bandas (violação de QUALQUER uma)."""
    drifts: list[PositionDrift] = []
    for ticker in sorted(set(current) | set(target)):
        cur = current.get(ticker, 0.0)
        tgt = target.get(ticker, 0.0)
        drift_abs = cur - tgt
        drift_rel = abs(drift_abs) / tgt if tgt > 0 else None
        breach = abs(drift_abs) > band_abs or (
            drift_rel is not None and drift_rel > band_rel
        )
        drifts.append(
            PositionDrift(
                ticker=ticker,
                current_weight=cur,
                target_weight=tgt,
                drift_abs=drift_abs,
                drift_rel=drift_rel,
                breach=breach,
            )
        )
    return drifts


def decide(
    drifts: list[PositionDrift],
    *,
    calendar_is_due: bool,
    macro_is_triggered: bool,
) -> Decision:
    """proposal (calendário/macro) > drift_alert (banda) > no_action."""
    if calendar_is_due or macro_is_triggered:
        return "proposal"
    if any(d.breach for d in drifts):
        return "drift_alert"
    return "no_action"


def turnover_pct(drifts: list[PositionDrift]) -> float:
    """Turnover one-way: 0.5 × Σ|diff|, em % do valor investido."""
    return 50.0 * sum(abs(d.drift_abs) for d in drifts)


def viable_cap(n_assets: int) -> float:
    """Cap do builder (0.25), alargado quando n < 4 tornaria sum(w)=1 inviável."""
    if BUILDER_CAP * n_assets >= 1.0:
        return BUILDER_CAP
    return 1.0 / n_assets + 1e-9


# ---------------------------------------------------------------------------
# DB helpers (stub points for tests)
# ---------------------------------------------------------------------------


async def get_policy(
    session: AsyncSession, portfolio_id: int
) -> RebalancePolicy | None:
    return await session.get(RebalancePolicy, portfolio_id)


async def portfolio_exists(session: AsyncSession, portfolio_id: int) -> bool:
    return await portfolio_crud.portfolio_exists(session, portfolio_id)


async def upsert_policy(
    session: AsyncSession, portfolio_id: int, **fields: Any
) -> RebalancePolicy:
    stmt = (
        pg_insert(RebalancePolicy)
        .values(portfolio_id=portfolio_id, **fields)
        .on_conflict_do_update(
            index_elements=["portfolio_id"],
            set_={**fields, "updated_at": dt.datetime.now(dt.UTC)},
        )
        .returning(RebalancePolicy)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.scalar_one()


async def stamp_evaluated(
    session: AsyncSession, portfolio_id: int, when: dt.datetime
) -> None:
    policy = await session.get(RebalancePolicy, portfolio_id)
    if policy is not None:
        policy.last_evaluated_at = when
        await session.commit()


async def fund_instrument_ids_by_ticker(
    session: AsyncSession, tickers: list[str]
) -> dict[str, uuid.UUID]:
    """ticker → instrument_id para as posições que são fundos do universo."""
    if not tickers:
        return {}
    result = await session.execute(
        select(Fund.ticker, Fund.instrument_id).where(Fund.ticker.in_(tickers))
    )
    return {
        ticker: instrument_id
        for ticker, instrument_id in result.all()
        if ticker is not None
    }


async def fetch_regime_state(
    datalake: AsyncSession | None,
) -> CompositeRegimeSnapshot | None:
    """Estado do detector promovido vote2of3 (state + last_flip), para o gatilho."""
    if datalake is None:
        raise RebalanceError(
            "macro_trigger_enabled requires the data-lake connection "
            "(DATALAKE_DB_URL) — the regime_composite detector lives there."
        )
    return await fetch_composite_regime(datalake)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def evaluate_portfolio(
    session: AsyncSession,
    datalake: AsyncSession | None,
    portfolio: Portfolio,
    policy: RebalancePolicy | None,
    *,
    now: dt.datetime | None = None,
) -> Evaluation:
    """Avalia um portfólio contra a política (ou defaults quando policy=None).

    Fail loud: < 2 posições, preço local ausente ou otimização inviável
    levantam RebalanceError/BuilderError — nunca uma resposta vazia.
    """
    now = now or dt.datetime.now(dt.UTC)
    positions = list(portfolio.positions)
    if len(positions) < 2:
        raise RebalanceError(
            "rebalance evaluation requires at least 2 positions "
            f"(portfolio {portfolio.id} has {len(positions)})"
        )

    frequency = policy.frequency if policy else DEFAULT_FREQUENCY
    band_abs = policy.band_abs if policy else DEFAULT_BAND_ABS
    band_rel = policy.band_rel if policy else DEFAULT_BAND_REL
    macro_enabled = policy.macro_trigger_enabled if policy else False
    last_evaluated = policy.last_evaluated_at if policy else None

    # --- pesos correntes (preços locais; DB-first, sem ensure externo) ------
    tickers = [position.ticker for position in positions]
    fund_ids = await fund_instrument_ids_by_ticker(session, tickers)
    closes = await portfolio_crud.select_last_two_closes(session, tickers)
    nav_tickers = [t for t in fund_ids if t not in closes]
    if nav_tickers:
        closes.update(
            await portfolio_crud.select_last_two_navs(session, nav_tickers)
        )
    missing = [p.ticker for p in positions if not closes.get(p.ticker)]
    if missing:
        raise RebalanceError(
            f"no local price data for: {', '.join(sorted(missing))} — open "
            "the portfolio overview to refresh prices first."
        )
    market_values = {
        p.ticker: p.quantity * closes[p.ticker][0][1] for p in positions
    }
    invested = sum(market_values.values())
    if invested <= 0:
        raise RebalanceError("portfolio has no invested value to rebalance")
    current = {t: mv / invested for t, mv in market_values.items()}

    # --- pesos-alvo: MESMO serviço de otimização do builder (A4) ------------
    assets = [
        FundRefIn(kind="fund", id=fund_ids[t])
        if t in fund_ids
        else EquityRefIn(kind="equity", ticker=t)
        for t in tickers
    ]
    request = OptimizeRequest(
        assets=assets,
        objective=DEFAULT_OBJECTIVE,
        constraints=ConstraintsIn(cap=viable_cap(len(assets))),
    )
    response = await portfolio_builder.run_optimize(session, request)
    id_to_ticker = {str(fund_ids[t]): t for t in fund_ids}
    target: dict[str, float] = {}
    for item in response.weights:
        asset = item.asset
        key = str(asset.id) if asset.kind == "fund" else asset.ticker
        target[id_to_ticker.get(key, key)] = float(item.weight)

    # --- gatilhos ------------------------------------------------------------
    is_due = calendar_due(last_evaluated, frequency, now)
    macro_fired = False
    if macro_enabled:
        regime = await fetch_regime_state(datalake)
        if regime is None:
            raise RebalanceError(
                "regime_composite_daily not materialized — run the "
                "regime_composite worker before enabling the macro trigger."
            )
        macro_fired = macro_triggered(
            True, regime.state, regime.last_flip, last_evaluated
        )

    drifts = compute_drifts(current, target, band_abs, band_rel)
    decision = decide(
        drifts, calendar_is_due=is_due, macro_is_triggered=macro_fired
    )
    proposal = Proposal(
        weights=target,
        turnover_pct=turnover_pct(drifts),
        objective=DEFAULT_OBJECTIVE,
        status=response.diagnostics.status,
    )
    return Evaluation(
        decision=decision,
        calendar_due=is_due,
        macro_triggered=macro_fired,
        drifts=drifts,
        proposal=proposal,
        invested_value=invested,
        cash=float(portfolio.cash),
    )
