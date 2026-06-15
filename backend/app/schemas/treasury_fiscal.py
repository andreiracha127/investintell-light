"""Response schema for GET /macro/fiscal (treasury_data, DB-first)."""

import datetime as dt
from typing import Any

from pydantic import BaseModel


class FiscalPointOut(BaseModel):
    obs_date: dt.date
    value: float
    # Auction series carry {security_type, security_term, bid_to_cover}; others null.
    metadata: dict[str, Any] | None


class FiscalSeriesOut(BaseModel):
    series_id: str
    points: list[FiscalPointOut]  # ascending by obs_date


class FiscalResponse(BaseModel):
    """Treasury fiscal series for one category (worker treasury_ingestion)."""

    category: str  # 'rates' | 'debt' | 'auctions' | 'fx' | 'interest'
    prefix: str  # the treasury_data series_id prefix the category maps to
    series: list[FiscalSeriesOut]
