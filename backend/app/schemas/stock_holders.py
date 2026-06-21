"""Schemas for the Stocks → Holders tab (13F institutional holders of a stock).

Reverse view of Tier C: given a stock (ticker → CUSIP), list every 13F filer
holding it in the latest reported period. Unlike the curated reverse-lookup,
this is the FULL >$5bn-universe set materialized into sec_13f_holdings.

Scale contract: `market_value` is full USD; `shares` is a share/principal count;
`position_return` (step 2) is a decimal fraction (0.05 = 5%).
"""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.fund_analysis import EmptyState


class StockHolder(BaseModel):
    """One institutional (13F) holder of the stock in the latest period."""

    model_config = ConfigDict(extra="forbid")

    cik: str
    manager_name: str
    shares: float | None = None
    market_value: float | None = None
    # Holder's stake as a fraction of shares outstanding (0.079 = 7.9% owned).
    pct_outstanding: float | None = None
    # Price return of the stock from the holder's entry quarter to today
    # (decimal fraction); entry_date is the earliest 13F report in the history.
    position_return: float | None = None
    entry_date: dt.date | None = None


class FundHolder(BaseModel):
    """One registered fund (N-PORT series) holding the stock."""

    model_config = ConfigDict(extra="forbid")

    series_id: str
    fund_name: str
    # Light-catalog instrument id for the fund dossier link (null if uncatalogued).
    instrument_id: uuid.UUID | None = None
    quantity: float | None = None
    market_value: float | None = None
    # Fraction of the fund's NAV in this stock (percent points, e.g. 15.6).
    # `pct_of_nav` is the latest quarter (Q0); the trail is the three prior
    # quarters [Q-1, Q-2, Q-3] — together the last 4 quarters of exposure.
    pct_of_nav: float | None = None
    pct_nav_q1: float | None = None
    pct_nav_q2: float | None = None
    pct_nav_q3: float | None = None


class FundFamily(BaseModel):
    """A registrant/trust grouping its funds that hold the stock (tree parent)."""

    model_config = ConfigDict(extra="forbid")

    registrant_cik: str
    family: str
    market_value: float | None = None
    fund_count: int = 0
    funds: list[FundHolder] = Field(default_factory=list)


class StockFundHoldersResponse(BaseModel):
    """Render-ready payload for the Holders "by fund" (N-PORT) tree view."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    cusip: str | None = None
    security_name: str | None = None
    period: dt.date | None = Field(default=None, description="Latest N-PORT report_date.")
    family_count: int = 0
    fund_count: int = 0
    total_market_value: float | None = None
    families: list[FundFamily] = Field(default_factory=list)
    empty_state: EmptyState | None = None


class StockHoldersResponse(BaseModel):
    """Render-ready payload for the Holders tab."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    cusip: str | None = Field(default=None, description="Resolved CUSIP for the ticker.")
    security_name: str | None = None
    period: dt.date | None = Field(default=None, description="Latest 13F report_date.")
    holder_count: int = 0
    total_market_value: float | None = None
    shares_outstanding: float | None = Field(
        default=None, description="Latest shares outstanding (for ownership %)."
    )
    holders: list[StockHolder] = Field(default_factory=list)
    empty_state: EmptyState | None = None
