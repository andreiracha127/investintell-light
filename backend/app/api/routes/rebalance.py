"""Rebalance endpoints (Frente A — A1/A3).

- PUT/GET /portfolios/{id}/rebalance/policy — política por portfólio (A1).
- GET /portfolios/{id}/rebalance/preview — avaliação on-demand (A2/A4):
  decisão + drift por posição + proposta (pesos-alvo do MESMO motor do
  builder, min-CVaR default) + turnover. NÃO carimba last_evaluated_at —
  isso é papel do job agendado (scripts/evaluate_rebalance.py). NUNCA
  executa ordens: produto é advisory.

Error mapping (fail loud): portfólio inexistente → 404; avaliação
impossível (<2 posições, otimização inviável) → 422; preço local ausente →
409 (mesma semântica do look-through).
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.datalake import get_optional_datalake_session
from app.core.db import get_session
from app.models.rebalance import RebalancePolicy
from app.rebalance import evaluator
from app.schemas.rebalance import (
    PositionDriftOut,
    ProposalOut,
    RebalancePolicyIn,
    RebalancePolicyOut,
    RebalancePreviewResponse,
)
from app.services import portfolio_builder, portfolio_crud

router = APIRouter(
    prefix="/portfolios",
    tags=["rebalance"],
    dependencies=[Depends(get_current_user)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
OptionalDatalakeDep = Annotated[
    AsyncSession | None, Depends(get_optional_datalake_session)
]


def _policy_out(
    policy: RebalancePolicy, *, is_default: bool
) -> RebalancePolicyOut:
    return RebalancePolicyOut(
        portfolio_id=policy.portfolio_id,
        frequency=policy.frequency,
        band_abs=policy.band_abs,
        band_rel=policy.band_rel,
        macro_trigger_enabled=policy.macro_trigger_enabled,
        last_evaluated_at=policy.last_evaluated_at,
        is_default=is_default,
    )


@router.get(
    "/{portfolio_id}/rebalance/policy", response_model=RebalancePolicyOut
)
async def get_rebalance_policy(
    portfolio_id: int, session: SessionDep
) -> RebalancePolicyOut:
    """Política salva do portfólio; 404 quando nenhuma foi configurada."""
    policy = await evaluator.get_policy(session, portfolio_id)
    if policy is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No rebalance policy for portfolio {portfolio_id} — PUT one "
                "first (the preview runs with documented defaults meanwhile)."
            ),
        )
    return _policy_out(policy, is_default=False)


@router.put(
    "/{portfolio_id}/rebalance/policy", response_model=RebalancePolicyOut
)
async def put_rebalance_policy(
    portfolio_id: int, payload: RebalancePolicyIn, session: SessionDep
) -> RebalancePolicyOut:
    """Cria/atualiza a política (upsert por portfolio_id)."""
    if not await evaluator.portfolio_exists(session, portfolio_id):
        raise HTTPException(
            status_code=404, detail=f"Portfolio {portfolio_id} not found."
        )
    policy = await evaluator.upsert_policy(
        session,
        portfolio_id,
        frequency=payload.frequency,
        band_abs=payload.band_abs,
        band_rel=payload.band_rel,
        macro_trigger_enabled=payload.macro_trigger_enabled,
    )
    return _policy_out(policy, is_default=False)


@router.get(
    "/{portfolio_id}/rebalance/preview",
    response_model=RebalancePreviewResponse,
)
async def get_rebalance_preview(
    portfolio_id: int,
    session: SessionDep,
    datalake: OptionalDatalakeDep,
) -> RebalancePreviewResponse:
    """Avaliação on-demand: decisão + drifts + proposta + turnover (advisory)."""
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id)
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail=f"Portfolio {portfolio_id} not found."
        )
    policy = await evaluator.get_policy(session, portfolio_id)
    now = dt.datetime.now(dt.UTC)
    try:
        evaluation = await evaluator.evaluate_portfolio(
            session, datalake, portfolio, policy, now=now
        )
    except evaluator.RebalanceError as exc:
        status = 409 if "no local price data" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except portfolio_builder.BuilderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if policy is not None:
        policy_out = _policy_out(policy, is_default=False)
    else:
        policy_out = RebalancePolicyOut(
            portfolio_id=portfolio_id,
            frequency=evaluator.DEFAULT_FREQUENCY,
            band_abs=evaluator.DEFAULT_BAND_ABS,
            band_rel=evaluator.DEFAULT_BAND_REL,
            macro_trigger_enabled=False,
            last_evaluated_at=None,
            is_default=True,
        )
    return RebalancePreviewResponse(
        portfolio_id=portfolio_id,
        decision=evaluation.decision,
        calendar_due=evaluation.calendar_due,
        macro_triggered=evaluation.macro_triggered,
        policy=policy_out,
        drifts=[
            PositionDriftOut(
                ticker=d.ticker,
                current_weight=d.current_weight,
                target_weight=d.target_weight,
                drift_abs=d.drift_abs,
                drift_rel=d.drift_rel,
                breach=d.breach,
            )
            for d in evaluation.drifts
        ],
        proposal=ProposalOut(
            weights=evaluation.proposal.weights,
            turnover_pct=evaluation.proposal.turnover_pct,
            objective=evaluation.proposal.objective,
            solver_status=evaluation.proposal.status,
        ),
        invested_value=evaluation.invested_value,
        cash=evaluation.cash,
        evaluated_at=now,
    )
