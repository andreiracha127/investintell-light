"""Modelos ORM read-only sobre os read-models db-first do Grupo A.

Todos vivem no DB principal e são alimentados por MV/view SQL
(fund_style_drift_mv, fund_top_holdings_mv, fund_style_bias_v) ou pelos
workers fund_factors / fund_institutional_reveal
(via *_latest_mv). Espelham o padrão de PriceLatest/NavLatest: mapeados via
Base, lidos por chave/IN, nunca escritos pelo backend.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import JSON, Date, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FundStyleDriftRow(Base):
    __tablename__ = "fund_style_drift_mv"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    report_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    sector: Mapped[str] = mapped_column(String, primary_key=True)
    weight: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class FundTopHoldingRow(Base):
    __tablename__ = "fund_top_holdings_mv"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    report_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    cusip: Mapped[str | None] = mapped_column(String, nullable=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_class: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    gics_sector: Mapped[str | None] = mapped_column(String, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_of_nav: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class FundStyleBiasRow(Base):
    __tablename__ = "fund_style_bias_v"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    as_of: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    factor: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class FundFactorExposureLatest(Base):
    __tablename__ = "fund_factor_exposures_latest_mv"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    factor: Mapped[str] = mapped_column(String, primary_key=True)
    beta: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    t_stat: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    significance: Mapped[str | None] = mapped_column(String, nullable=True)
    as_of: Mapped[dt.date | None] = mapped_column(Date, nullable=True)


class FundInstitutionalRevealLatest(Base):
    __tablename__ = "fund_institutional_reveal_latest_mv"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
