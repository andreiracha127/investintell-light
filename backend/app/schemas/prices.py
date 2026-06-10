"""Response schemas for the price-series endpoint.

Payload is deliberately lean: adj_open/adj_high/adj_low and adj_volume are
stored in the DB (analytics read the table directly) but NOT returned here.
"""

import datetime as dt

from pydantic import BaseModel


class PricePoint(BaseModel):
    """One EOD bar in a price series response."""

    model_config = {"from_attributes": True}

    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: float
    div_cash: float
    split_factor: float


class PriceSeriesResponse(BaseModel):
    """EOD price series for one ticker over [start_date, end_date]."""

    ticker: str
    start_date: dt.date
    end_date: dt.date
    count: int
    prices: list[PricePoint]
