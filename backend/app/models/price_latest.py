"""Modelos ORM read-only sobre os MVs price_latest_mv / nav_latest_mv.

Ambos vivem no DB principal (mesmo banco de eod_prices / nav_timeseries) e são
refrescados pelo worker matview_refresh. Espelham o padrão de FundRiskLatest:
MV mapeado via Base, lido por chave/IN, nunca escrito.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base  # mesmo Base usado por FundRiskLatest


class PriceLatest(Base):
    __tablename__ = "price_latest_mv"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    last_close: Mapped[float] = mapped_column(Numeric, nullable=False)
    prev_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class NavLatest(Base):
    __tablename__ = "nav_latest_mv"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    last_nav: Mapped[float] = mapped_column(Numeric, nullable=False)
    prev_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    prev_nav: Mapped[float | None] = mapped_column(Numeric, nullable=True)
