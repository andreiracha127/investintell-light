"""Pydantic models for Tiingo API responses."""

import datetime

from pydantic import BaseModel, Field, field_validator


class TiingoEodRow(BaseModel):
    """One row of end-of-day price data from ``/tiingo/daily/{ticker}/prices``."""

    ticker: str
    date: datetime.date
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_open: float = Field(alias="adjOpen")
    adj_high: float = Field(alias="adjHigh")
    adj_low: float = Field(alias="adjLow")
    adj_close: float = Field(alias="adjClose")
    adj_volume: int = Field(alias="adjVolume")
    div_cash: float = Field(alias="divCash")
    split_factor: float = Field(alias="splitFactor")

    model_config = {"populate_by_name": True}

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> datetime.date:
        """Accept ISO datetime strings like '2024-01-02T00:00:00+00:00' or plain dates."""
        if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
            return v
        if isinstance(v, datetime.datetime):
            return v.date()
        if isinstance(v, str):
            # Tiingo returns e.g. "2024-01-02T00:00:00+00:00"
            try:
                return datetime.date.fromisoformat(v[:10])
            except ValueError:
                pass
        raise ValueError(f"Cannot parse date from {v!r}")


class TiingoTickerMeta(BaseModel):
    """Metadata for a ticker from ``/tiingo/daily/{ticker}``."""

    ticker: str
    name: str | None = None
    exchange_code: str | None = Field(None, alias="exchangeCode")
    description: str | None = None
    start_date: datetime.date | None = Field(None, alias="startDate")
    end_date: datetime.date | None = Field(None, alias="endDate")

    model_config = {"populate_by_name": True}

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def parse_nullable_date(cls, v: object) -> datetime.date | None:
        if v is None:
            return None
        if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
            return v
        if isinstance(v, datetime.datetime):
            return v.date()
        if isinstance(v, str):
            try:
                return datetime.date.fromisoformat(v[:10])
            except ValueError:
                pass
        raise ValueError(f"Cannot parse date from {v!r}")


class TiingoNewsItem(BaseModel):
    """One news article from ``/tiingo/news``."""

    id: int
    title: str
    url: str
    published_date: datetime.datetime = Field(alias="publishedDate")
    source: str
    description: str | None = None
    tickers: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
