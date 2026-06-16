"""Schemas for the rebalance policy + preview endpoints (Frente A).

Bandas e pesos em frações decimais (0.05 = 5 p.p.), convenção do projeto;
turnover em % (50.0 = metade do valor investido girado one-way).
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Frequency = Literal["weekly", "monthly", "quarterly"]
Decision = Literal["no_action", "drift_alert", "proposal"]


class RebalancePolicyIn(BaseModel):
    frequency: Frequency = "monthly"
    band_abs: float = Field(default=0.05, gt=0, le=1)
    band_rel: float = Field(default=0.25, gt=0, le=1)
    macro_trigger_enabled: bool = False


class RebalancePolicyOut(BaseModel):
    portfolio_id: int
    frequency: Frequency
    band_abs: float
    band_rel: float
    macro_trigger_enabled: bool
    last_evaluated_at: dt.datetime | None
    # True quando o preview rodou com os DEFAULTS (nenhuma política salva).
    is_default: bool = False


class PositionDriftOut(BaseModel):
    ticker: str
    current_weight: float
    target_weight: float
    drift_abs: float
    drift_rel: float | None
    breach: bool
    status: Literal["ok", "maintenance", "urgent"]


class ProposalOut(BaseModel):
    """Proposta advisory — NUNCA é executada automaticamente."""

    weights: dict[str, float]
    turnover_pct: float
    objective: str
    solver_status: str


class RebalancePreviewResponse(BaseModel):
    portfolio_id: int
    decision: Decision
    calendar_due: bool
    macro_triggered: bool
    policy: RebalancePolicyOut
    drifts: list[PositionDriftOut]
    proposal: ProposalOut
    invested_value: float
    cash: float
    evaluated_at: dt.datetime
