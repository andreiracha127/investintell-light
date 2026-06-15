"""Schemas for the portfolio builder optimizer endpoint (F8.3/F8.4).

Scale contract (project-wide): weights, returns, vol and CVaR are decimal
fractions (0.05 = 5%), never 0-100. ``q`` in views is an ANNUAL return
(absolute) or annual outperformance (relative). ``confidence`` ∈ (0, 1].
"""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.portfolios import PositionBasis, validate_portfolio_name

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


class BLParamsIn(BaseModel):
    delta: Annotated[float, Field(gt=0)] = 2.5
    tau: Annotated[float, Field(gt=0)] = 0.05


Objective = Literal[
    "equal_weight", "min_vol", "erc", "max_diversification", "min_cvar",
    "bl_utility", "max_return_cvar",
]

# Candidate-universe selection vocabulary — mirrors the GET /funds filters and
# sort whitelist so a universe optimization reuses the same catalog semantics.
FundTypeFilter = Literal["etf", "mmf", "mutual_fund"]
AssetClassFilter = Literal["equity", "fixed_income", "cash", "alternatives"]
UniverseRankBy = Literal[
    "aum_usd",
    "sharpe_1y",
    "return_1y",
    "expense_ratio",
    "volatility_1y",
    "max_drawdown_1y",
]

# Hard ceiling on a resolved universe — matches the explicit-list cap so both
# paths feed the optimizer the same bounded number of assets.
MAX_UNIVERSE_ASSETS = 50
DEFAULT_UNIVERSE_ASSETS = 30


class BlockBudgetIn(BaseModel):
    """Σ of weights in an asset-class block must lie in [lo, hi] (decimal
    fractions). ``asset_class`` matches ``Fund.asset_class``."""

    asset_class: AssetClassFilter
    lo: Annotated[float, Field(ge=0, le=1)] = 0.0
    hi: Annotated[float, Field(ge=0, le=1)] = 1.0

    @model_validator(mode="after")
    def _check_order(self) -> "BlockBudgetIn":
        if self.lo > self.hi:
            raise ValueError(f"block budget lo ({self.lo}) must be <= hi ({self.hi})")
        return self


class ConstraintsIn(BaseModel):
    """Long-only and sum(w)=1 are always enforced; these are the knobs.

    ``block_budgets`` (per-asset-class Σ-weight bounds) are honoured ONLY by the
    ``min_cvar`` objective in v1; they are resolved against ``Fund.asset_class``
    server-side and IGNORED by the other objectives. Empty/None = no blocks.
    """

    cap: Annotated[float, Field(gt=0, le=1)] | None = 0.25
    min_weight: Annotated[float, Field(ge=0, le=1)] | None = None
    block_budgets: list[BlockBudgetIn] | None = None


class UniverseSpecIn(BaseModel):
    """Filter + rank a slice of the FUND universe instead of listing assets.

    The optimizer then runs over the resolved candidates (funds only, v1 —
    same rule as views: equities have no AUM/market cap in the builder yet).
    Candidates are restricted to funds that EACH have enough NAV history; the
    cross-asset overlap requirement is still enforced on the resolved set. All
    filter fields share the GET /funds vocabulary; ``rank_by``/``rank_dir``
    pick the top ``max_assets`` of the matching set.
    """

    fund_type: FundTypeFilter | None = None
    asset_class: AssetClassFilter | None = None
    strategy_label: Annotated[str, Field(max_length=80)] | None = None
    expense_ratio_max: Annotated[float, Field(ge=0)] | None = None
    aum_min: Annotated[float, Field(ge=0)] | None = None
    sharpe_1y_min: float | None = None
    volatility_1y_max: Annotated[float, Field(ge=0)] | None = None
    return_1y_min: float | None = None
    max_drawdown_1y_min: float | None = None
    rank_by: UniverseRankBy = "aum_usd"
    rank_dir: Literal["asc", "desc"] = "desc"
    max_assets: Annotated[
        int, Field(ge=2, le=MAX_UNIVERSE_ASSETS)
    ] = DEFAULT_UNIVERSE_ASSETS
    include_instrument_ids: (
        Annotated[list[str], Field(min_length=2, max_length=MAX_UNIVERSE_ASSETS)] | None
    ) = None
    """Optional explicit subset (UUID strings) of the ranked universe to keep.

    When the user prunes the previewed top-``max_assets`` candidates via
    checkboxes, the kept ids are sent here; the optimizer runs over exactly
    these (still subject to the same NAV/overlap guards). ``None`` = use the
    full top-``max_assets`` ranked set (default behaviour)."""


class OptimizeRequest(BaseModel):
    """Optimize over either an explicit ``assets`` list OR a ``universe`` spec
    (exactly one). ``universe`` resolves to fund candidates server-side.
    """

    assets: Annotated[list[AssetRefIn], Field(min_length=2, max_length=50)] | None = None
    universe: UniverseSpecIn | None = None
    objective: Objective = "min_cvar"
    constraints: ConstraintsIn = ConstraintsIn()
    # None = use the FULL nav_timeseries history (the 2-year window gate is
    # removed). An explicit int (30..3650 days) opts into a narrower window.
    window_days: Annotated[int | None, Field(ge=30, le=3650)] = None
    # Views require every asset in the universe to have a known AUM (v1:
    # funds only — equities have no market cap in the builder yet).
    views: list[ViewIn] | None = None
    bl: BLParamsIn = BLParamsIn()
    # L1 turnover penalty λ·‖w − w₀‖₁ on the min_cvar objective. Requires
    # ``current_weights`` (asset-label -> decimal fraction, label scheme
    # 'fund:<uuid>' / 'equity:<TICKER>'). v1: honoured only by min_cvar.
    turnover_lambda: Annotated[float, Field(ge=0)] = 0.0
    current_weights: dict[str, float] | None = None
    # Annual tail-loss cap for ``max_return_cvar`` (decimal fraction, e.g.
    # 0.10 = 10% CVaR_95). Required for that objective, ignored otherwise.
    cvar_limit: Annotated[float, Field(gt=0, le=1)] | None = None

    @model_validator(mode="after")
    def _check_asset_source(self) -> "OptimizeRequest":
        if (self.assets is None) == (self.universe is None):
            raise ValueError(
                "provide exactly one of 'assets' (explicit list) or 'universe' "
                "(filter+rank the fund universe)"
            )
        # Views reference specific assets by ref; in universe mode the user
        # cannot know which funds get selected, so the two are incompatible.
        if self.universe is not None and self.views:
            raise ValueError(
                "views cannot be combined with 'universe' — views reference "
                "specific assets, which a universe optimization selects for you; "
                "use an explicit 'assets' list to express views"
            )
        if self.turnover_lambda > 0 and not self.current_weights:
            raise ValueError(
                "turnover_lambda requires current_weights (a label -> fraction map "
                "of the existing allocation)"
            )
        if self.objective == "max_return_cvar":
            if self.cvar_limit is None:
                raise ValueError("max_return_cvar requires a cvar_limit (tail-loss cap)")
            if self.universe is not None:
                raise ValueError(
                    "max_return_cvar needs expected returns and so requires views on an "
                    "explicit 'assets' list — it cannot run over a 'universe'"
                )
            if not self.views:
                raise ValueError(
                    "max_return_cvar needs expected returns — supply Black-Litterman "
                    "'views' (gate G5: no sample mean is ever used as the objective)"
                )
        return self


# ── Response ─────────────────────────────────────────────────────────────────


class WeightOut(BaseModel):
    asset: AssetRefIn
    weight: float
    # Display labels resolved server-side. Populated for funds selected via a
    # ``universe`` spec (the client never saw them); null on the explicit-list
    # path, where the client already knows the labels it sent.
    ticker: str | None = None
    name: str | None = None


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


# Fixed disclaimer carried by every save response (F8.6b — proposal vs
# executed semantics, plus the fund-class NAV proxy approximation).
PRICING_NOTE = (
    "Reference prices (spot/NAV) are for analysis; executed fills with "
    "commissions define real cost basis. Fund class NAV is proxied by the "
    "series NAV."
)


class SaveWeightIn(BaseModel):
    """One proposed weight to persist. Zero/near-zero weights should be
    filtered out by the caller — a weight that rounds to quantity 0 is a 422.

    F8.6b execution fields (all optional, retro-compatible):
    - without ``fill_price`` the position is saved at the REFERENCE price
      (spot/NAV) with basis='reference';
    - with ``fill_price`` the position is EXECUTED: quantity is sized at the
      fill, and the cost basis includes the commission;
    - ``class_ticker`` (funds only) saves the position under a share-class
      ticker of the SAME fund instead of the representative one.
    """

    asset: AssetRefIn
    weight: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]
    fill_price: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = Field(
        default=None,
        description="Actual execution price per share/unit; presence flips the "
        "position to basis='executed'.",
    )
    commission: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = Field(
        default=None,
        description="Total commission paid on the fill (>= 0); requires fill_price.",
    )
    trade_date: dt.date | None = Field(
        default=None, description="Execution date of the fill; requires fill_price."
    )
    class_ticker: Annotated[str, Field(min_length=1, max_length=12)] | None = Field(
        default=None,
        description="Fund share-class ticker (fund assets only); must belong to "
        "the same fund instrument. Priced with the series NAV as a proxy.",
    )

    @model_validator(mode="after")
    def _check_execution_fields(self) -> "SaveWeightIn":
        if self.fill_price is None and self.commission is not None:
            raise ValueError(
                "commission requires fill_price — a commission on a reference "
                "(non-executed) position is ambiguous."
            )
        if self.fill_price is None and self.trade_date is not None:
            raise ValueError(
                "trade_date requires fill_price — a trade date on a reference "
                "(non-executed) position is ambiguous."
            )
        if self.class_ticker is not None and self.asset.kind != "fund":
            raise ValueError(
                f"class_ticker {self.class_ticker!r} is only valid for fund "
                "assets — equities have no share classes."
            )
        return self


class SaveRequest(BaseModel):
    """Body for POST /builder/save — persist a proposal as a real portfolio.

    ``quantity = weight * notional_usd / price`` per position (rounded to
    4 decimals), where price is the fill price when given, else the
    reference spot/NAV. The stored ``acq_price`` is the reference price for
    basis='reference', or ``(fill_price*qty + commission)/qty`` (6 decimals)
    for basis='executed'.
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
    # Price used for sizing: the fill price when executed, else the
    # reference spot/NAV.
    price: float
    # 'reference' | 'executed' (F8.6b).
    basis: PositionBasis
    # Effective per-unit cost basis persisted as acq_price — equals `price`
    # for reference positions; includes commissions when executed.
    cost_basis: float


class SaveResponse(BaseModel):
    portfolio_id: int
    name: str
    notional_usd: float
    positions: list[SavedPositionOut]
    pricing_note: str = PRICING_NOTE
