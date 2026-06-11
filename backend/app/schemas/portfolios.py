"""Request/response schemas for the persisted-portfolio endpoints (F4).

Scale contract (project-wide): every fractional quantity in these payloads
(``change_pct``, ``pnl_pct``, ``total_pnl_pct``) is a decimal fraction
(0.05 = 5%), never 0-100. Currency fields are plain currency units.

Validation is fail-loud with actionable messages: blank/oversized names,
malformed tickers, non-positive quantities/prices and duplicate tickers are
rejected with 422, never silently normalized away.
"""

import datetime as dt

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas._tickers import normalize_ticker
from app.schemas.news import NewsArticle

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


class PositionBody(BaseModel):
    """Quantity/acquisition-price payload for the position upsert (PUT)."""

    quantity: float = Field(gt=0, allow_inf_nan=False, description="Shares/units held; > 0.")
    acq_price: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        description="Acquisition price per share/unit; null = unknown (P&L renders null).",
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

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        return None if value is None else validate_portfolio_name(value)

    @model_validator(mode="after")
    def _check_not_empty(self) -> "PortfolioPatch":
        if self.name is None and self.cash is None:
            raise ValueError("PATCH requires at least one of 'name' or 'cash'.")
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


class PortfolioOut(BaseModel):
    """One persisted portfolio with its positions (sorted by ticker)."""

    model_config = {"from_attributes": True}

    id: int
    name: str
    cash: float
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
    created_at: dt.datetime


# ---------------------------------------------------------------------------
# Overview (render-ready table — D6: column-header aggregates pattern)
# ---------------------------------------------------------------------------


class PositionOverview(BaseModel):
    """One render-ready overview row; the backend computes ALL finance."""

    ticker: str
    name: str | None = Field(description="Display name from the instruments cache.")
    quantity: float
    acq_price: float | None = Field(
        description="Acquisition price per share/unit; null = unknown."
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
