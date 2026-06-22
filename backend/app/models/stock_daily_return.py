"""Modelo ORM read-only sobre a tabela worker-owned stock_daily_returns.

Materializada pelo worker stock_daily_returns (repo investintell-datalake-workers)
porque o retorno diário (lag(adj_close)) não é expressível em continuous aggregate.
Lido pelo helper de aligned-returns (app.analytics.aligned); nunca escrito aqui.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockDailyReturn(Base):
    __tablename__ = "stock_daily_returns"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    return_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    adj_close: Mapped[float | None] = mapped_column(Float, nullable=True)
