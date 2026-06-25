"""On-demand SQL-function call layer for Group C interactive series.

Each helper invokes one fn_* function (Task 1) via text() and reshapes the rows
into the exact types the legacy pandas assemblers already produced, so the route
rewrites are a source swap, not a shape change. No pandas/numpy here — that is
the whole point of Group C.

Scale contract: returns are decimal fractions (0.05 = 5%); VaR/CVaR are POSITIVE
loss magnitudes; drawdown is a NEGATIVE fraction.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.analysis import HistogramOut

SeriesPoint = tuple[dt.date, float]


def slice_strict(points: list[SeriesPoint], start: dt.date) -> list[SeriesPoint]:
    """Keep only points strictly after `start` (legacy `index > start_ts`)."""
    return [(d, v) for d, v in points if d > start]


def week_downsample(points: list[SeriesPoint]) -> list[SeriesPoint]:
    """Keep the last point of each ISO (year, week); preserve order. Mirrors the
    W-FRI last-of-week downsample for 5Y/MAX without pandas."""
    last_by_week: dict[tuple[int, int], SeriesPoint] = {}
    for d, v in points:
        iso = d.isocalendar()
        last_by_week[(iso[0], iso[1])] = (d, v)
    return sorted(last_by_week.values(), key=lambda p: p[0])


async def rolling_metrics_points(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    instrument_id: uuid.UUID | None = None,
    window: int,
    start: dt.date,
    end: dt.date,
) -> tuple[list[SeriesPoint], list[SeriesPoint]]:
    rows = (
        await session.execute(
            text(
                "SELECT d, vol, sharpe FROM fn_rolling_metrics"
                "(:ticker, :instrument, :window, :start, :end) ORDER BY d"
            ),
            {
                "ticker": ticker,
                "instrument": instrument_id,
                "window": window,
                "start": start,
                "end": end,
            },
        )
    ).all()
    vol = [(d, float(v)) for d, v, _ in rows if v is not None]
    sharpe = [(d, float(s)) for d, _, s in rows if s is not None]
    return vol, sharpe


async def rolling_beta_corr_points(
    session: AsyncSession,
    *,
    ticker: str,
    benchmark: str,
    window: int,
    start: dt.date,
    end: dt.date,
) -> tuple[list[SeriesPoint], list[SeriesPoint]]:
    rows = (
        await session.execute(
            text(
                "SELECT d, beta, corr FROM fn_rolling_beta_corr"
                "(:ticker, :bench, :window, :start, :end) ORDER BY d"
            ),
            {
                "ticker": ticker,
                "bench": benchmark,
                "window": window,
                "start": start,
                "end": end,
            },
        )
    ).all()
    beta = [(d, float(b)) for d, b, _ in rows if b is not None]
    corr = [(d, float(c)) for d, _, c in rows if c is not None]
    return beta, corr


async def drawdown_points(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    instrument_id: uuid.UUID | None = None,
    start: dt.date,
    end: dt.date,
) -> list[SeriesPoint]:
    rows = (
        await session.execute(
            text(
                "SELECT d, drawdown FROM fn_drawdown"
                "(:ticker, :instrument, :start, :end) ORDER BY d"
            ),
            {"ticker": ticker, "instrument": instrument_id, "start": start, "end": end},
        )
    ).all()
    return [(d, float(v)) for d, v in rows if v is not None]


async def histogram_out(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    instrument_id: uuid.UUID | None = None,
    bins: int,
    start: dt.date,
    end: dt.date,
) -> HistogramOut:
    rows = (
        await session.execute(
            text(
                "SELECT bin_index, bin_lo, bin_hi, cnt FROM fn_histogram"
                "(:ticker, :instrument, :bins, :start, :end) ORDER BY bin_index"
            ),
            {
                "ticker": ticker,
                "instrument": instrument_id,
                "bins": bins,
                "start": start,
                "end": end,
            },
        )
    ).all()
    los = [float(lo) for _, lo, _, _ in rows]
    his = [float(hi) for _, _, hi, _ in rows]
    counts = [int(c) for *_, c in rows]
    edges = los + ([his[-1]] if his else [])
    max_count = max(counts) if counts else 0
    normalized = [c / max_count for c in counts] if max_count else [0.0 for _ in counts]
    return HistogramOut(bin_edges=edges, counts=counts, counts_normalized=normalized)


async def var_cvar(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    instrument_id: uuid.UUID | None = None,
    level: float,
    start: dt.date,
    end: dt.date,
) -> tuple[float, float]:
    var, cvar = (
        await session.execute(
            text(
                "SELECT var, cvar FROM fn_var_cvar"
                "(:ticker, :instrument, :level, :start, :end)"
            ),
            {
                "ticker": ticker,
                "instrument": instrument_id,
                "level": level,
                "start": start,
                "end": end,
            },
        )
    ).one()
    return float(var), float(cvar)
