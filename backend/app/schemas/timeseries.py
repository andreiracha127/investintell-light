"""Highcharts Stock array contracts: [[t_ms, value], ...] / [[t_ms,o,h,l,c], ...]."""

from typing import Literal

from pydantic import BaseModel

Interval = Literal["daily", "weekly", "monthly"]


class LineSeriesResponse(BaseModel):
    """Single line series for Highcharts Stock: [[t_ms, value], ...]."""

    id: str
    interval: Interval
    series: list[list[float]]  # [[t_ms, value], ...]


class OhlcSeriesResponse(BaseModel):
    """OHLC + volume series for Highcharts Stock."""

    id: str
    interval: Interval
    ohlc: list[list[float]]  # [[t_ms, o, h, l, c], ...]
    volume: list[list[float]]  # [[t_ms, v], ...]
