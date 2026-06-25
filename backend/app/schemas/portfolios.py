"""Request/response schemas for the persisted-portfolio endpoints (F4).

Scale contract (project-wide): every fractional quantity in these payloads
(``change_pct``, ``pnl_pct``, ``total_pnl_pct``) is a decimal fraction
(0.05 = 5%), never 0-100. Currency fields are plain currency units.

Validation is fail-loud with actionable messages: blank/oversized names,
malformed tickers, non-positive quantities/prices and duplicate tickers are
rejected with 422, never silently normalized away.
"""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.portfolio_constraint import ASSET_CLASSES
from app.schemas._tickers import normalize_ticker
from app.schemas.news import NewsArticle

AssetClass = Literal["equity", "fixed_income", "cash", "alternatives", "multi_asset"]
PositionPriceSource = Literal["eod", "nav"]

MAX_POSITIONS = 50
MAX_NAME_LENGTH = 80


def validate_portfolio_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= MAX_NAME_LENGTH:
        raise ValueError(
            f"Portfolio name must be 1..{MAX_NAME_LENGTH} characters after trimming; "
            f"got {len(name)}."
        )
    return name


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


PositionBasis = Literal["reference", "executed"]
TransactionSide = Literal["buy", "sell"]


class PositionBody(BaseModel):
    """Quantity/acquisition-price payload for the position upsert (PUT).

    F8.6b fill fields are optional: omitting them keeps the pre-F8.6b
    behavior (on UPDATE the stored basis/commission/trade_date are left
    untouched; on INSERT basis defaults to 'reference').
    """

    quantity: float = Field(gt=0, allow_inf_nan=False, description="Shares/units held; > 0.")
    acq_price: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        description="Acquisition price per share/unit; null = unknown (P&L renders null). "
        "With basis='executed' this is the effective cost basis incl. commissions.",
    )
    basis: PositionBasis | None = Field(
        default=None,
        description="'reference' (spot/NAV for analysis) or 'executed' (real fill "
        "incl. commissions). Omitted: insert defaults to 'reference', update keeps "
        "the stored value.",
    )
    commission: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
        description="Total commission paid on the fill, currency units (>= 0).",
    )
    trade_date: dt.date | None = Field(
        default=None, description="Execution date of the fill."
    )


class PositionCreate(PositionBody):
    """One position in the create-portfolio payload."""

    ticker: str = Field(description="Instrument ticker (normalized to uppercase).")

    @field_validator("ticker")
    @classmethod
    def _check_ticker(cls, value: str) -> str:
        return normalize_ticker(value, "ticker")


class PortfolioCreate(BaseModel):
    """Body for POST /portfolios."""

    name: str = Field(
        description=f"Portfolio name; 1..{MAX_NAME_LENGTH} characters after trimming, "
        "unique across the installation."
    )
    cash: float = Field(
        default=0.0, allow_inf_nan=False, description="Uninvested cash, currency units."
    )
    inception_date: dt.date | None = Field(
        default=None,
        description="User-declared portfolio inception date for NAV/performance.",
    )
    positions: list[PositionCreate] = Field(
        default_factory=list,
        max_length=MAX_POSITIONS,
        description=f"Initial positions (at most {MAX_POSITIONS}); tickers must be unique.",
    )

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return validate_portfolio_name(value)

    @model_validator(mode="after")
    def _check_duplicate_tickers(self) -> "PortfolioCreate":
        tickers = [p.ticker for p in self.positions]
        duplicates = sorted({t for t in tickers if tickers.count(t) > 1})
        if duplicates:
            raise ValueError(
                f"Duplicate tickers are not allowed: {', '.join(duplicates)}. "
                "Merge duplicate positions into one."
            )
        return self


class PortfolioPatch(BaseModel):
    """Body for PATCH /portfolios/{id} — at least one field must be present."""

    name: str | None = Field(
        default=None, description="New portfolio name (same rules as on create)."
    )
    cash: float | None = Field(
        default=None, allow_inf_nan=False, description="New cash balance, currency units."
    )
    inception_date: dt.date | None = Field(
        default=None,
        description="Portfolio inception date; null clears it.",
    )

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        return None if value is None else validate_portfolio_name(value)

    @model_validator(mode="after")
    def _check_not_empty(self) -> "PortfolioPatch":
        if (
            self.name is None
            and self.cash is None
            and "inception_date" not in self.model_fields_set
        ):
            raise ValueError(
                "PATCH requires at least one of 'name', 'cash' or 'inception_date'."
            )
        return self


# ---------------------------------------------------------------------------
# CRUD responses
# ---------------------------------------------------------------------------


class PositionOut(BaseModel):
    """One persisted position."""

    model_config = {"from_attributes": True}

    ticker: str
    quantity: float
    acq_price: float | None
    basis: PositionBasis
    commission: float | None
    trade_date: dt.date | None


class PortfolioOut(BaseModel):
    """One persisted portfolio with its positions (sorted by ticker)."""

    model_config = {"from_attributes": True}

    id: int
    name: str
    cash: float
    inception_date: dt.date | None
    created_at: dt.datetime
    updated_at: dt.datetime
    positions: list[PositionOut]


class PortfolioListItem(BaseModel):
    """One row of GET /portfolios (positions omitted, count only)."""

    model_config = {"from_attributes": True}

    id: int
    name: str
    cash: float
    position_count: int
    inception_date: dt.date | None
    created_at: dt.datetime


class PortfolioTransactionCreate(BaseModel):
    """One immutable buy/sell event in the portfolio ledger."""

    ticker: str = Field(description="Instrument ticker (normalized to uppercase).")
    side: TransactionSide = Field(description="'buy' or 'sell'.")
    quantity: float = Field(gt=0, allow_inf_nan=False)
    price: float = Field(gt=0, allow_inf_nan=False)
    commission: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    trade_date: dt.date = Field(description="Execution date.")

    @field_validator("ticker")
    @classmethod
    def _check_ticker(cls, value: str) -> str:
        return normalize_ticker(value, "ticker")


class PortfolioTransactionOut(BaseModel):
    """One persisted ledger transaction."""

    model_config = {"from_attributes": True}

    id: int
    portfolio_id: int
    ticker: str
    side: TransactionSide
    quantity: float
    price: float
    commission: float
    trade_date: dt.date
    created_at: dt.datetime


class PortfolioNavPoint(BaseModel):
    """Transaction-aware NAV index point.

    ``nav`` is a rebased index value, not raw dollars. ``market_value`` is the
    post-trade value of open holdings on that date.
    """

    date: dt.date
    nav: float
    market_value: float
    cash: float
    total_value: float


class PortfolioNavResponse(BaseModel):
    """Transaction-aware portfolio NAV series."""

    portfolio_id: int
    inception_date: dt.date | None
    base_nav: float = 100.0
    points: list[PortfolioNavPoint]


# ---------------------------------------------------------------------------
# Overview (render-ready table — D6: column-header aggregates pattern)
# ---------------------------------------------------------------------------


class PositionOverview(BaseModel):
    """One render-ready overview row; the backend computes ALL finance."""

    ticker: str
    name: str | None = Field(description="Display name from the instruments cache.")
    asset_class: str | None = Field(
        default=None,
        description="Fund asset_class for the grouped allocation view; None for "
        "direct equities / non-fund tickers.",
    )
    strategy_label: str | None = Field(
        default=None,
        description="Fund strategy_label for the grouped allocation view; None "
        "for direct equities.",
    )
    instrument_id: uuid.UUID | None = Field(
        default=None,
        description="Fund instrument_id (for the dossier link); None for "
        "non-fund holdings.",
    )
    fund_type: str | None = Field(
        default=None,
        description="Fund type from the fund catalog, e.g. etf/mutual_fund/mmf; "
        "None for direct stock/non-fund holdings.",
    )
    price_source: PositionPriceSource = Field(
        description="Baseline price source used for the backend overview: "
        "eod for traded closes, nav for fund NAV snapshots."
    )
    live_price_eligible: bool = Field(
        description="True when the frontend may overlay real-time ticks on top "
        "of the EOD baseline. Stocks and ETFs are eligible; NAV-priced funds "
        "remain EOD."
    )
    quantity: float
    acq_price: float | None = Field(
        description="Acquisition price per share/unit; null = unknown. With "
        "basis='executed' this is the effective cost basis incl. commissions."
    )
    basis: PositionBasis = Field(
        description="'reference' (spot/NAV cost basis, analysis-grade) or "
        "'executed' (real fill incl. commissions)."
    )
    commission: float | None = Field(
        description="Total commission paid on the fill, currency units; null "
        "when unknown or basis='reference'."
    )
    trade_date: dt.date | None = Field(
        description="Execution date of the fill; null when unknown or "
        "basis='reference'."
    )
    last_close: float = Field(description="Most recent EOD close, currency units.")
    prev_close: float | None = Field(
        description="Second-most-recent EOD close; null when only one row exists."
    )
    change: float | None = Field(
        description="last_close - prev_close, currency units; null without prev_close."
    )
    change_pct: float | None = Field(
        description="change / prev_close as a decimal fraction (0.05 = 5%), never "
        "0-100; null without prev_close."
    )
    market_value: float = Field(description="quantity * last_close, currency units.")
    cost_basis: float | None = Field(
        description="quantity * acq_price, currency units; null when acq_price is unknown."
    )
    pnl: float | None = Field(
        description="market_value - cost_basis, currency units; null when acq_price "
        "is unknown."
    )
    pnl_pct: float | None = Field(
        description="pnl / cost_basis as a decimal fraction (0.10 = 10%), never 0-100; "
        "null when acq_price is unknown."
    )
    as_of: dt.date = Field(description="Date of last_close.")


class OverviewAggregates(BaseModel):
    """Portfolio-level aggregates rendered in the table column headers (D6)."""

    total_market_value: float = Field(
        description="Sum of position market values, currency units (0 when empty)."
    )
    total_cost_basis: float | None = Field(
        description="Sum over positions with a known acq_price; null when ALL are unknown."
    )
    total_pnl: float | None = Field(
        description="Sum of pnl over positions with a known acq_price; null when no "
        "position has a cost basis."
    )
    total_pnl_pct: float | None = Field(
        description="total_pnl / total_cost_basis as a decimal fraction, never 0-100; "
        "null when no position has a cost basis."
    )
    cash: float = Field(description="Uninvested cash balance, currency units.")
    total_value: float = Field(
        description="total_market_value + cash, currency units."
    )
    as_of: dt.date | None = Field(
        description="Max as_of across positions; null for an empty portfolio."
    )


class PortfolioOverviewResponse(BaseModel):
    """Render-ready overview for GET /portfolios/{id}/overview."""

    id: int
    name: str
    positions: list[PositionOverview]
    aggregates: OverviewAggregates


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


class PortfolioNewsResponse(BaseModel):
    """Aggregated news across all portfolio tickers, newest first.

    ``stale`` is True when the Tiingo refresh failed but cached articles were
    served — a declared degradation, never a silent fallback (same contract
    as GET /stocks/{ticker}/news).
    """

    portfolio_id: int
    tickers: list[str] = Field(description="Portfolio tickers the articles were matched on.")
    count: int
    stale: bool = False
    items: list[NewsArticle]


# ---------------------------------------------------------------------------
# Construction constraints (Sprint B) — header limits + per-class bounds
# ---------------------------------------------------------------------------


class ClassLimitItem(BaseModel):
    """One per-asset-class min/max weight bound.

    Both bounds are decimal fractions in [0, 1] and nullable (absent = no
    bound of that side). When both are present ``min_weight <= max_weight``.
    """

    asset_class: AssetClass = Field(
        description=f"One of: {', '.join(ASSET_CLASSES)}."
    )
    min_weight: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False,
        description="Lower weight bound, decimal fraction in [0, 1]; null = none.",
    )
    max_weight: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False,
        description="Upper weight bound, decimal fraction in [0, 1]; null = none.",
    )

    @model_validator(mode="after")
    def _check_min_le_max(self) -> "ClassLimitItem":
        if (
            self.min_weight is not None
            and self.max_weight is not None
            and self.min_weight > self.max_weight
        ):
            raise ValueError(
                f"class limit for {self.asset_class!r}: min_weight "
                f"({self.min_weight}) must be <= max_weight ({self.max_weight})."
            )
        return self


class ConstraintsPut(BaseModel):
    """Body for PUT /portfolios/{id}/constraints.

    Header limits are each nullable (absent/null = no limit of that kind):
    ``cap`` and ``overlap_cap`` are in (0, 1]; ``min_weight`` is in [0, 1].
    ``class_limits`` is a (possibly empty) list of per-asset-class bounds; the
    whole set is replaced wholesale on upsert.
    """

    cap: float | None = Field(
        default=None, gt=0.0, le=1.0, allow_inf_nan=False,
        description="Max per-position weight, decimal fraction in (0, 1]; null = none.",
    )
    min_weight: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False,
        description="Min per-position weight, decimal fraction in [0, 1]; null = none.",
    )
    overlap_cap: float | None = Field(
        default=None, gt=0.0, le=1.0, allow_inf_nan=False,
        description="Max pairwise overlap, decimal fraction in (0, 1]; null = none.",
    )
    class_limits: list[ClassLimitItem] = Field(
        default_factory=list,
        description="Per-asset-class min/max weight bounds (replaced wholesale).",
    )


class ConstraintsView(ConstraintsPut):
    """Response for GET /portfolios/{id}/constraints — the persisted set.

    Same shape as the PUT body plus the owning ``portfolio_id``. A portfolio
    with no persisted constraints renders as nulls + an empty ``class_limits``.
    """

    portfolio_id: int


# ---------------------------------------------------------------------------
# Drift alerts (Sprint C) — the latest persisted drift evaluation
# ---------------------------------------------------------------------------


class BreachesView(BaseModel):
    """The breach payload of the latest drift evaluation.

    The three breach families are typed loosely as lists of objects (the
    drift/evaluation service owns the exact item shapes); ``overlap_report_date``
    is the N-PORT report date the overlap breaches were computed at (ISO string
    or null when no look-through has run).
    """

    position_drifts: list[dict] = Field(default_factory=list)
    class_breaches: list[dict] = Field(default_factory=list)
    overlap_breaches: list[dict] = Field(default_factory=list)
    overlap_report_date: str | None = None


class AlertsView(BaseModel):
    """Response for GET /portfolios/{id}/alerts — the latest drift status.

    A portfolio that exists but has never been evaluated renders as
    ``worst_status="ok"``, ``evaluated_at=null`` and empty breach lists (a
    legitimate 200), not a 404.
    """

    evaluated_at: dt.datetime | None = None
    worst_status: str = "ok"
    breaches: BreachesView = Field(default_factory=BreachesView)
