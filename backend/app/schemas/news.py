"""Response schemas for the per-ticker news endpoint."""

import datetime as dt

from pydantic import BaseModel


class NewsArticle(BaseModel):
    """One news article linked to the requested ticker."""

    model_config = {"from_attributes": True}

    id: int
    title: str
    url: str
    source: str | None
    description: str | None
    published_at: dt.datetime


class NewsResponse(BaseModel):
    """News articles for one ticker, newest first.

    ``stale`` is True when the Tiingo refresh failed but cached articles were
    served — a declared degradation, never a silent fallback.
    """

    ticker: str
    count: int
    stale: bool = False
    items: list[NewsArticle]
