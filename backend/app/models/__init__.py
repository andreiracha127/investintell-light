"""
Models package — re-exports Base and all ORM models so that:
  - Alembic env.py can `from app.models import Base` and get a fully-populated metadata.
  - Application code can do `from app.models import Instrument, EodPrice, NewsItem`.

All models must be imported here (even if not re-exported by name) so that
SQLAlchemy's metadata is populated before Alembic introspects it.
"""

from app.models.base import Base
from app.models.eod_price import EodPrice
from app.models.fund import Fund, FundHolding, FundNav, FundRiskLatest
from app.models.instrument import Instrument
from app.models.news_item import NewsItem
from app.models.portfolio import Portfolio, Position
from app.models.screen import Screen, ScreenFilter
from app.models.screener_metrics import ScreenerMetrics
from app.models.universe import FundamentalsSnapshot, UniverseConstituent

__all__ = [
    "Base",
    "EodPrice",
    "Fund",
    "FundHolding",
    "FundNav",
    "FundRiskLatest",
    "FundamentalsSnapshot",
    "Instrument",
    "NewsItem",
    "Portfolio",
    "Position",
    "Screen",
    "ScreenFilter",
    "ScreenerMetrics",
    "UniverseConstituent",
]
