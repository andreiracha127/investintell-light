"""Schemas for the portfolio builder optimizer endpoint (F8.3/F8.4).

Scale contract (project-wide): weights, returns, vol and CVaR are decimal
fractions (0.05 = 5%), never 0-100. ``q`` in views is an ANNUAL return
(absolute) or annual outperformance (relative). ``confidence`` ∈ (0, 1].
"""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.portfolios import validate_portfolio_name

# ── Asset references ─────────────────────────────────────────────────────────


class FundRefIn(BaseModel):
    kind: Literal["fund"]
    id: uuid.UUID


class EquityRefIn(BaseModel):
    kind: Literal["equity"]
    ticker: Annotated[str, Field(min_length=1, max_length=12)]


AssetRefIn = Annotated[FundRefIn | EquityRefIn, Field(discriminator="kind")]


# ── Views (Black-Litterman) ──────────────────────────────────────────────────


class AbsoluteViewIn(BaseModel):
    """'Asset returns q per year' (e.g. q=0.12 → 12% a.a.)."""

    type: Literal["absolute"]
    asset: AssetRefIn
    q: float
    confidence: Annotated[float, Field(gt=0, le=1)] = 0.5


class RelativeViewIn(BaseModel):
    """'`long` outperforms `short` by q per year'."""

    type: Literal["relative"]
    long: AssetRefIn
    short: AssetRefIn
    q: float
    confidence: Annotated[float, Field(gt=0, le=1)] = 0.5


ViewIn = Annotated[AbsoluteViewIn | RelativeViewIn, Field(discriminator="type")]


# ── Request ──────────────────────────────────────────────────────────────────


class ConstraintsIn(BaseModel):
    """Long-only and sum(w)=1 are always enforced; these are the knobs."""

    cap: Annotated[float, Field(gt=0, le=1)] | None = 0.25
    min_weight: Annotated[float, Field(ge=0, le=1)] | None = None


class BLParamsIn(BaseModel):
    delta: Annotated[float, Field(gt=0)] = 2.5
    tau: Annotated[float, Field(gt=0)] = 0.05


Objective = Literal[
    "equal_weight", "min_vol", "erc", "max_diversification", "min_cvar", "bl_utility"
]


class OptimizeRequest(BaseModel):
    assets: Annotated[list[AssetRefIn], Field(min_length=2, max_length=50)]
    objective: Objective = "min_cvar"
    constraints: ConstraintsIn = ConstraintsIn()
    window_days: Annotated[int, Field(ge=30, le=3650)] = 730
    # Views require every asset in the universe to have a known AUM (v1:
    # funds only — equities have no market cap in the builder yet).
    views: list[ViewIn] | None = None
    bl: BLParamsIn = BLParamsIn()


# ── Response ─────────────────────────────────────────────────────────────────


class WeightOut(BaseModel):
    asset: AssetRefIn
    weight: float


class ExpectedOut(BaseModel):
    vol_ann: float
    # In-sample daily CVaR 95 of the PROPOSED weights on the RAW historical
    # scenarios (not BL-re-centered) — comparable with the F3 engine numbers.
    cvar_95_in_sample: float
    # μ_BLᵀw, annualized — null when no views were supplied.
    return_ann_bl: float | None


class DiagnosticsOut(BaseModel):
    n_obs: int
    status: str
    # Present only on the BL path (views and/or bl_utility), in asset order.
    mu_equilibrium: list[float] | None = None
    mu_posterior: list[float] | None = None


class OptimizeResponse(BaseModel):
    weights: list[WeightOut]
    expected: ExpectedOut
    diagnostics: DiagnosticsOut


# ── Save as portfolio (F8.5) ─────────────────────────────────────────────────


class SaveWeightIn(BaseModel):
    """One proposed weight to persist. Zero/near-zero weights should be
    filtered out by the caller — a weight that rounds to quantity 0 is a 422."""

    asset: AssetRefIn
    weight: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]


class SaveRequest(BaseModel):
    """Body for POST /builder/save — persist a proposal as a real portfolio.

    ``quantity = weight * notional_usd / spot_price`` per position (rounded to
    4 decimals); the spot price becomes the position's cost basis.
    """

    name: str = Field(description="Portfolio name; same rules as POST /portfolios.")
    notional_usd: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 1_000_000
    weights: Annotated[list[SaveWeightIn], Field(min_length=1, max_length=50)]

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return validate_portfolio_name(value)


class SavedPositionOut(BaseModel):
    ticker: str
    quantity: float
    # Spot price used for sizing AND stored as the position's cost basis.
    price: float


class SaveResponse(BaseModel):
    portfolio_id: int
    name: str
    notional_usd: float
    positions: list[SavedPositionOut]
