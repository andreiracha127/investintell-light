"""Modelos ORM read-only sobre os MVs do Grupo B (datalake DB).

Espelham FundRiskLatest / PriceLatest: MV mapeado via Base, lido por chave/IN,
nunca escrito. Refrescados pelo worker matview_refresh (passo datalake).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockInstitutionalHolder(Base):
    __tablename__ = "stock_institutional_holders_mv"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    cik: Mapped[str] = mapped_column(String, primary_key=True)
    cusip: Mapped[str] = mapped_column(String, primary_key=True)
    manager_name: Mapped[str] = mapped_column(String, nullable=False)
    report_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    shares: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    entry_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    shares_outstanding: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class StockFundHolderRow(Base):
    __tablename__ = "stock_fund_holders_mv"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    registrant_cik: Mapped[str] = mapped_column(String, nullable=False)
    family: Mapped[str] = mapped_column(String, nullable=False)
    fund_name: Mapped[str] = mapped_column(String, nullable=False)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_of_nav: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_nav_q1: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_nav_q2: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_nav_q3: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    report_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    cusip: Mapped[str | None] = mapped_column(String, nullable=True)


class HoldingReverseLookupRow(Base):
    __tablename__ = "holding_reverse_lookup_mv"

    cusip: Mapped[str] = mapped_column(String, primary_key=True)
    cik: Mapped[str] = mapped_column(String, primary_key=True)
    manager_name: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    report_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    value_usd: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    shares: Mapped[float | None] = mapped_column(Numeric, nullable=True)
