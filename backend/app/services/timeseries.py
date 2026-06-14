"""Timeseries assembly: pick raw vs CAGG by range, pack into Highcharts arrays.

Granularity by visible range: <=1Y daily (raw hypertable), 1-5Y weekly CAGG,
>5Y monthly CAGG. Downsample happens in the DB (CAGG), never in Python.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Interval = Literal["daily", "weekly", "monthly"]
RangeKey = Literal["1M", "6M", "1Y", "5Y", "MAX"]

_INTERVAL_BY_RANGE: dict[str, Interval] = {
    "1M": "daily", "6M": "daily", "1Y": "daily", "5Y": "weekly", "MAX": "monthly",
}
_RANGE_DAYS: dict[str, int] = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 1826}


def resolve_interval(range_key: str) -> Interval:
    return _INTERVAL_BY_RANGE.get(range_key, "daily")


def range_start(range_key: str, last: dt.date) -> dt.date | None:
    """Start date for the visible range; None = MAX (full history)."""
    days = _RANGE_DAYS.get(range_key)
    return None if days is None else last - dt.timedelta(days=days)


def _ms(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp() * 1000)


def to_ms_pairs(rows: list[tuple[dt.date, float]]) -> list[list[float]]:
    return [[_ms(d), float(v)] for d, v in rows]


def to_ms_ohlc(
    rows: list[tuple[dt.date, float, float, float, float, float]],
) -> tuple[list[list[float]], list[list[float]]]:
    ohlc = [[_ms(d), float(o), float(h), float(lo), float(c)] for d, o, h, lo, c, _v in rows]
    vol = [[_ms(d), float(v or 0)] for d, *_rest, v in rows]
    return ohlc, vol


# --- DB reads (return ascending (date, …) tuples) -------------------------

_EOD_TABLE: dict[Interval, tuple[str, str]] = {
    "daily":   ("eod_prices",      "date"),
    "weekly":  ("cagg_eod_weekly", "bucket"),
    "monthly": ("cagg_eod_monthly","bucket"),
}


async def select_eod_ohlc(
    session: AsyncSession, ticker: str, interval: Interval, start: dt.date | None
) -> list[tuple[dt.date, float, float, float, float, float]]:
    table, tcol = _EOD_TABLE[interval]
    where = "ticker = :ticker" + ("" if start is None else f" AND {tcol} >= :start")
    sql = text(
        f"SELECT {tcol} AS d, adj_open, adj_high, adj_low, adj_close, adj_volume "
        f"FROM {table} WHERE {where} ORDER BY {tcol}"
    )
    params: dict[str, object] = {"ticker": ticker}
    if start is not None:
        params["start"] = start
    rows = (await session.execute(sql, params)).all()
    return [(d, o, h, lo, c, v) for d, o, h, lo, c, v in rows]


_NAV_TABLE: dict[Interval, tuple[str, str, str]] = {
    "daily":   ("nav_timeseries",  "nav_date", "nav"),
    "weekly":  ("cagg_nav_weekly", "bucket",   "nav_eow"),
    "monthly": ("cagg_nav_monthly","month",    "nav_eom"),
}


async def select_nav_line(
    session: AsyncSession, instrument_id: str, interval: Interval, start: dt.date | None
) -> list[tuple[dt.date, float]]:
    table, tcol, vcol = _NAV_TABLE[interval]
    where = "instrument_id = :iid" + ("" if start is None else f" AND {tcol} >= :start")
    sql = text(
        f"SELECT {tcol} AS d, {vcol} AS v FROM {table} "
        f"WHERE {where} AND {vcol} IS NOT NULL ORDER BY {tcol}"
    )
    params: dict[str, object] = {"iid": instrument_id}
    if start is not None:
        params["start"] = start
    rows = (await session.execute(sql, params)).all()
    return [(d, float(v)) for d, v in rows]
