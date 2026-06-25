"""Screener metrics snapshot job (F6.3).

Computes ONE cross-sectional `screener_metrics` row per active universe
constituent: trailing returns / volatilities / betas / correlations / SMA
distances from local EOD prices, plus fundamentals ratios from the
`fundamentals_snapshot` RAW inputs. Run via
scripts/compute_screener_metrics.py — never from any request path.

NULL contract (deliberate contrast with the fail-loud F2/F3 analysis
endpoints): the analysis endpoints raise on insufficient data because the
user asked for THAT ticker and deserves a clear error. The screener is a
cross-section over ~5 000 tickers — a ticker with three months of history
legitimately has ret_1y = NULL and must not abort the rest of the run. Each
metric is therefore independently NULL-tolerant: NULL means "unavailable",
and the report counts NULLs per metric for sanity.

Window semantics (price-derived metrics):
- The anchor is the ticker's own ``as_of`` = its last available EOD date.
- Trailing windows (1w/1m/3m/6m/1y/2y) are CALENDAR offsets back from as_of.
- COVERAGE rule: a window metric requires the ticker's loaded history to
  reach at or before the window start, otherwise that metric is NULL.
- Return base price = last adj_close at or before the window start (spans
  the full calendar window across weekends/holidays).
- YTD/MTD base = last adj_close strictly before Jan 1 / the 1st of as_of's
  month (none → NULL: the ticker listed mid-period).
- Vol/beta/corr use daily simple returns inside the window via the F2
  analytics engine; SMA distances use TRADING-DAY windows (20/50/200 rows)
  on adj_close.

Memory bound: EOD prices are loaded in ticker batches (default 200 per
SELECT) over a ~2-year window; the five benchmark ETF return series are
loaded once. Writes are full-table-refresh upserts (ON CONFLICT (ticker)
DO UPDATE all columns), chunked under the asyncpg 32 767-parameter ceiling.
"""

import datetime as dt
import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import annualized_volatility, beta, correlation, simple_returns
from app.core.chunks import chunked
from app.core.config import get_settings
from app.ingestion.service import ingest_one_ticker, is_fresh
from app.models.eod_price import EodPrice
from app.models.instrument import Instrument
from app.models.screener_metrics import ScreenerMetrics
from app.models.universe import FundamentalsSnapshot, UniverseConstituent
from app.tiingo.client import TiingoClient

logger = logging.getLogger(__name__)

# Benchmark ETF proxies (dispatch §3.5). SPY drives the betas; all five drive
# the 1y correlations. They are ingested directly at job start when stale —
# they need no universe row (GLD/AGG/TLT/USO are funds without fundamentals).
BENCHMARK_TICKERS = ("SPY", "GLD", "AGG", "TLT", "USO")

# Calendar lookback for the price load: the longest window is 2 years
# (beta_2y_spy); the extra days guarantee a base price at or before the
# window start exists even across holidays, so coverage is never clipped by
# the load boundary itself.
LOOKBACK_DAYS = 745

# Tickers per EOD SELECT — bounds memory (~200 tickers x ~500 rows of 2y
# daily data per batch).
DEFAULT_BATCH_SIZE = 200

# asyncpg caps query parameters at 32 767. Each screener_metrics row binds
# 37 params (ticker + computed_at + as_of + 34 metric columns); 500 rows x 37
# = 18 500, safely under the ceiling.
_METRICS_UPSERT_CHUNK = 500

# Window offsets, keyed by destination column.
_RETURN_WINDOWS: dict[str, pd.DateOffset] = {
    "ret_1w": pd.DateOffset(weeks=1),
    "ret_1m": pd.DateOffset(months=1),
    "ret_3m": pd.DateOffset(months=3),
    "ret_6m": pd.DateOffset(months=6),
    "ret_1y": pd.DateOffset(years=1),
}
_VOL_WINDOWS: dict[str, pd.DateOffset] = {
    "vol_1m": pd.DateOffset(months=1),
    "vol_3m": pd.DateOffset(months=3),
    "vol_6m": pd.DateOffset(months=6),
    "vol_1y": pd.DateOffset(years=1),
}
_BETA_WINDOWS: dict[str, pd.DateOffset] = {
    "beta_3m_spy": pd.DateOffset(months=3),
    "beta_6m_spy": pd.DateOffset(months=6),
    "beta_1y_spy": pd.DateOffset(years=1),
    "beta_2y_spy": pd.DateOffset(years=2),
}
_CORR_COLUMNS: dict[str, str] = {
    "corr_spy": "SPY",
    "corr_gld": "GLD",
    "corr_agg": "AGG",
    "corr_tlt": "TLT",
    "corr_uso": "USO",
}
_CORR_WINDOW = pd.DateOffset(years=1)
_SMA_WINDOWS: dict[str, int] = {
    "pct_above_sma20": 20,
    "pct_above_sma50": 50,
    "pct_above_sma200": 200,
}

_FUNDAMENTAL_COLUMNS = (
    "market_cap",
    "pe_ratio",
    "roe",
    "roa",
    "gross_margin",
    "de_ratio",
    "investment_growth",
    "profitability_gross",
    "fundamentals_period_end",
)

# Every metric column compute_ticker_metrics emits (and the upsert updates).
METRIC_COLUMNS: tuple[str, ...] = (
    *_RETURN_WINDOWS,
    "ret_ytd",
    "ret_mtd",
    *_VOL_WINDOWS,
    *_BETA_WINDOWS,
    *_CORR_COLUMNS,
    *_SMA_WINDOWS,
    "price_close",
    "avg_volume_1m",
    *_FUNDAMENTAL_COLUMNS,
)


@dataclass
class MetricsReport:
    """Counts for one metrics run (printed by the CLI and returned to callers)."""

    total_active: int = 0
    computed: int = 0
    skipped_no_eod: int = 0
    requested_not_in_universe: list[str] = field(default_factory=list)
    null_counts: dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def lines(self) -> list[str]:
        out = [
            f"Active constituents considered: {self.total_active}",
            f"  computed:                     {self.computed}",
            f"  skipped (no EOD data at all): {self.skipped_no_eod}",
        ]
        if self.requested_not_in_universe:
            out.append(
                "  requested but not active in universe: "
                + ", ".join(self.requested_not_in_universe)
            )
        out.append("Per-metric NULL counts:")
        for col in METRIC_COLUMNS:
            out.append(f"  {col:<24} {self.null_counts.get(col, 0)}")
        out.append(f"Elapsed: {self.elapsed_seconds:.1f}s")
        return out


# ---------------------------------------------------------------------------
# Pure metric helpers (unit-tested directly on synthetic frames)
# ---------------------------------------------------------------------------


def _trailing_return(
    adj_close: pd.Series, as_of_ts: pd.Timestamp, offset: pd.DateOffset
) -> float | None:
    """Return over [as_of - offset, as_of]; NULL without coverage."""
    start = as_of_ts - offset
    if adj_close.index[0] > start:
        return None
    base = float(adj_close.loc[:start].iloc[-1])
    if base <= 0:
        return None
    return float(adj_close.iloc[-1]) / base - 1.0


def _calendar_return(adj_close: pd.Series, boundary: pd.Timestamp) -> float | None:
    """Return since the last close strictly BEFORE *boundary* (YTD/MTD base)."""
    before = adj_close.loc[adj_close.index < boundary]
    if before.empty:
        return None
    base = float(before.iloc[-1])
    if base <= 0:
        return None
    return float(adj_close.iloc[-1]) / base - 1.0


def _window_prices(
    adj_close: pd.Series, as_of_ts: pd.Timestamp, offset: pd.DateOffset
) -> pd.Series | None:
    """Prices from the window's base observation through as_of; NULL without
    coverage. Includes the base (last at-or-before start) so the first return
    spans the window boundary."""
    start = as_of_ts - offset
    if adj_close.index[0] > start:
        return None
    base_pos = int(adj_close.index.searchsorted(start, side="right")) - 1
    return adj_close.iloc[base_pos:]


def _trailing_volatility(
    adj_close: pd.Series, as_of_ts: pd.Timestamp, offset: pd.DateOffset
) -> float | None:
    window = _window_prices(adj_close, as_of_ts, offset)
    if window is None or len(window) < 3:  # engine needs >= 2 returns
        return None
    return annualized_volatility(simple_returns(window))


def _window_returns(
    returns: pd.Series, as_of_ts: pd.Timestamp, offset: pd.DateOffset
) -> pd.Series:
    """Daily returns strictly inside (as_of - offset, as_of]."""
    start = as_of_ts - offset
    return returns.loc[returns.index > start]


def _trailing_beta(
    returns: pd.Series,
    first_price_ts: pd.Timestamp,
    benchmark_returns: pd.Series | None,
    as_of_ts: pd.Timestamp,
    offset: pd.DateOffset,
) -> float | None:
    if benchmark_returns is None or first_price_ts > as_of_ts - offset:
        return None
    try:
        return beta(_window_returns(returns, as_of_ts, offset), benchmark_returns)
    except ValueError:
        # < 10 overlapping points or zero benchmark variance in the window —
        # both are "metric unavailable" conditions in a cross-section.
        return None


def _trailing_correlation(
    returns: pd.Series,
    first_price_ts: pd.Timestamp,
    benchmark_returns: pd.Series | None,
    as_of_ts: pd.Timestamp,
    offset: pd.DateOffset,
) -> float | None:
    if benchmark_returns is None or first_price_ts > as_of_ts - offset:
        return None
    try:
        return correlation(
            _window_returns(returns, as_of_ts, offset), benchmark_returns
        )
    except ValueError:
        return None


def _pct_above_sma(adj_close: pd.Series, window: int) -> float | None:
    """close / SMA(window trading days) - 1; NULL with fewer than window rows."""
    if len(adj_close) < window:
        return None
    sma = float(adj_close.iloc[-window:].mean())
    if sma <= 0:
        return None
    return float(adj_close.iloc[-1]) / sma - 1.0


def _fundamentals_metrics(
    fundamentals: Mapping[str, Any] | None, price_close: float | None
) -> dict[str, Any]:
    """Fundamentals ratios from the RAW snapshot inputs, NULL-guarded.

    Documented guards (each yields NULL, never an exception):
    - market_cap requires shares_outstanding > 0 and a price.
    - pe_ratio requires net_income_ttm > 0 — a negative-earnings P/E is
      meaningless for screening.
    - roe and de_ratio require book_equity > 0 (negative equity makes both
      ratios uninterpretable).
    - gross_margin requires revenue > 0.
    """
    out: dict[str, Any] = dict.fromkeys(_FUNDAMENTAL_COLUMNS)
    if fundamentals is None:
        return out

    shares = fundamentals.get("shares_outstanding")
    net_income = fundamentals.get("net_income_ttm")
    book_equity = fundamentals.get("book_equity")
    total_assets = fundamentals.get("total_assets")
    revenue = fundamentals.get("revenue")
    gross_profit = fundamentals.get("gross_profit")

    if shares is not None and shares > 0 and price_close is not None:
        out["market_cap"] = float(shares) * price_close
    if out["market_cap"] is not None and net_income is not None and net_income > 0:
        out["pe_ratio"] = out["market_cap"] / float(net_income)
    if book_equity is not None and book_equity > 0:
        if net_income is not None:
            out["roe"] = float(net_income) / float(book_equity)
        if total_assets is not None:
            out["de_ratio"] = (float(total_assets) - float(book_equity)) / float(
                book_equity
            )
    if revenue is not None and revenue > 0 and gross_profit is not None:
        out["gross_margin"] = float(gross_profit) / float(revenue)
    out["roa"] = fundamentals.get("quality_roa")
    out["investment_growth"] = fundamentals.get("investment_growth")
    out["profitability_gross"] = fundamentals.get("profitability_gross")
    out["fundamentals_period_end"] = fundamentals.get("period_end")
    return out


def compute_ticker_metrics(
    prices: pd.DataFrame,
    benchmark_returns_map: Mapping[str, pd.Series],
    fundamentals: Mapping[str, Any] | None,
    as_of: dt.date,
) -> dict[str, Any]:
    """One ticker's full metrics dict (every METRIC_COLUMNS key, NULLs included).

    Args:
        prices: DataFrame with a sorted ascending ``DatetimeIndex`` and columns
            ``adj_close``, ``close``, ``volume`` (at least 1 row; the last row
            is the as_of observation).
        benchmark_returns_map: daily simple-return series keyed by benchmark
            ticker (subset of ``BENCHMARK_TICKERS``; missing → those metrics NULL).
        fundamentals: the ticker's fundamentals_snapshot row as a mapping, or
            None (→ all fundamentals metrics NULL).
        as_of: the ticker's last available EOD date (anchor for all windows).

    Each metric is independently NULL-tolerant — see the module docstring's
    NULL contract and window semantics.
    """
    as_of_ts = pd.Timestamp(as_of)
    adj_close = prices["adj_close"]
    first_ts = pd.Timestamp(adj_close.index[0])
    spy_returns = benchmark_returns_map.get("SPY")

    out: dict[str, Any] = {}

    for col, offset in _RETURN_WINDOWS.items():
        out[col] = _trailing_return(adj_close, as_of_ts, offset)
    out["ret_ytd"] = _calendar_return(adj_close, pd.Timestamp(as_of.year, 1, 1))
    out["ret_mtd"] = _calendar_return(
        adj_close, pd.Timestamp(as_of.year, as_of.month, 1)
    )

    for col, offset in _VOL_WINDOWS.items():
        out[col] = _trailing_volatility(adj_close, as_of_ts, offset)

    returns = simple_returns(adj_close) if len(adj_close) >= 2 else pd.Series(dtype=float)
    for col, offset in _BETA_WINDOWS.items():
        out[col] = _trailing_beta(returns, first_ts, spy_returns, as_of_ts, offset)
    for col, bench in _CORR_COLUMNS.items():
        out[col] = _trailing_correlation(
            returns, first_ts, benchmark_returns_map.get(bench), as_of_ts, _CORR_WINDOW
        )

    for col, window in _SMA_WINDOWS.items():
        out[col] = _pct_above_sma(adj_close, window)

    price_close = float(prices["close"].iloc[-1])
    out["price_close"] = price_close
    # Mean raw volume over the trailing calendar month; not coverage-gated —
    # the as_of row always exists, and a partial month is still informative.
    month_volume = prices["volume"].loc[
        prices.index > as_of_ts - pd.DateOffset(months=1)
    ]
    mean = float(month_volume.mean())
    out["avg_volume_1m"] = None if pd.isna(mean) else mean

    out.update(_fundamentals_metrics(fundamentals, price_close))
    return out


# ---------------------------------------------------------------------------
# Statement builder (compiled-SQL-tested)
# ---------------------------------------------------------------------------


def build_metrics_upsert(records: list[dict[str, Any]]) -> PgInsert:
    """INSERT ... ON CONFLICT (ticker) DO UPDATE for screener_metrics.

    Full-refresh semantics: every non-PK column (computed_at, as_of and all
    metrics) is overwritten on conflict, so re-running the job always leaves
    the freshest snapshot.
    """
    if not records:
        raise ValueError("build_metrics_upsert requires at least one record")
    stmt = pg_insert(ScreenerMetrics).values(records)
    update_columns = ("computed_at", "as_of", *METRIC_COLUMNS)
    return stmt.on_conflict_do_update(
        index_elements=[ScreenerMetrics.ticker],
        set_={col: getattr(stmt.excluded, col) for col in update_columns},
    )


async def refresh_screener_equity_snapshot(session: AsyncSession) -> None:
    """Refresh the materialized read model when it exists in this database."""
    try:
        await session.execute(text("REFRESH MATERIALIZED VIEW screener_equity_snapshot_mv"))
        await session.commit()
    except DBAPIError as exc:
        await session.rollback()
        sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if sqlstate == "42P01":  # undefined_table: older local/test DBs
            logger.warning("screener_equity_snapshot_mv is missing; skipping refresh")
            return
        raise


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def group_price_rows(
    rows: Iterable[tuple[Any, ...]],
) -> dict[str, pd.DataFrame]:
    """Group (ticker, date, adj_close, close, volume) rows — ordered by
    (ticker, date) — into per-ticker DataFrames with a DatetimeIndex."""
    grouped: dict[str, dict[str, list[Any]]] = {}
    for ticker, date, adj_close, close, volume in rows:
        bucket = grouped.setdefault(
            ticker, {"date": [], "adj_close": [], "close": [], "volume": []}
        )
        bucket["date"].append(date)
        bucket["adj_close"].append(adj_close)
        bucket["close"].append(close)
        bucket["volume"].append(volume)
    return {
        ticker: pd.DataFrame(
            {
                "adj_close": cols["adj_close"],
                "close": cols["close"],
                "volume": cols["volume"],
            },
            index=pd.DatetimeIndex(pd.to_datetime(cols["date"])),
        )
        for ticker, cols in grouped.items()
    }


async def _load_price_frames(
    session: AsyncSession, tickers: list[str], start: dt.date
) -> dict[str, pd.DataFrame]:
    """One SELECT for a batch of tickers over [start, today] → per-ticker frames."""
    result = await session.execute(
        select(
            EodPrice.ticker,
            EodPrice.date,
            EodPrice.adj_close,
            EodPrice.close,
            EodPrice.volume,
        )
        .where(EodPrice.ticker.in_(tickers), EodPrice.date >= start)
        .order_by(EodPrice.ticker, EodPrice.date)
    )
    return group_price_rows(tuple(row) for row in result.all())


async def _load_fundamentals(
    session: AsyncSession, tickers: list[str]
) -> dict[str, dict[str, Any]]:
    result = await session.execute(
        select(
            FundamentalsSnapshot.ticker,
            FundamentalsSnapshot.period_end,
            FundamentalsSnapshot.book_equity,
            FundamentalsSnapshot.total_assets,
            FundamentalsSnapshot.net_income_ttm,
            FundamentalsSnapshot.revenue,
            FundamentalsSnapshot.gross_profit,
            FundamentalsSnapshot.shares_outstanding,
            FundamentalsSnapshot.quality_roa,
            FundamentalsSnapshot.investment_growth,
            FundamentalsSnapshot.profitability_gross,
        ).where(FundamentalsSnapshot.ticker.in_(tickers))
    )
    return {row["ticker"]: dict(row) for row in result.mappings().all()}


async def _ensure_benchmarks(
    session: AsyncSession,
    client: TiingoClient,
    staleness_hours: float,
) -> None:
    """Ingest the benchmark ETFs when stale/cold (fail loud — they are job
    infrastructure: without SPY no ticker gets a beta)."""
    today = dt.date.today()
    for ticker in BENCHMARK_TICKERS:
        instrument = await session.get(Instrument, ticker)
        now = dt.datetime.now(dt.UTC)
        if instrument is not None and is_fresh(
            instrument.eod_last_fetched_at, now, staleness_hours
        ):
            continue
        outcome = await ingest_one_ticker(session, client, ticker, today)
        logger.info(
            "Benchmark %s ingested (%s, %d rows)",
            ticker,
            outcome.action,
            outcome.rows_upserted,
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_metrics(
    session: AsyncSession,
    client: TiingoClient,
    *,
    tickers: list[str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    staleness_hours: float | None = None,
) -> MetricsReport:
    """Compute and upsert screener_metrics for all active constituents.

    Args:
        session: Async DB session (one commit per ticker batch).
        client: Shared TiingoClient — used only to ingest stale/cold
            benchmark ETFs at job start.
        tickers: Optional explicit subset (testing); names outside the active
            universe are reported, not computed (screener_metrics has an FK
            to universe_constituents).
        batch_size: Tickers per EOD SELECT (memory bound).
        staleness_hours: Benchmark freshness override; defaults to settings.
    """
    started = time.monotonic()
    if staleness_hours is None:
        staleness_hours = get_settings().eod_staleness_hours

    await _ensure_benchmarks(session, client, staleness_hours)

    # Active universe (optionally filtered to the requested subset).
    stmt = (
        select(UniverseConstituent.ticker)
        .where(UniverseConstituent.status == "active")
        .order_by(UniverseConstituent.ticker)
    )
    wanted: list[str] | None = None
    if tickers:
        wanted = [t.strip().upper() for t in tickers if t.strip()]
        stmt = stmt.where(UniverseConstituent.ticker.in_(wanted))
    result = await session.execute(stmt)
    todo: list[str] = list(result.scalars().all())

    report = MetricsReport(
        total_active=len(todo),
        null_counts=dict.fromkeys(METRIC_COLUMNS, 0),
    )
    if wanted is not None:
        report.requested_not_in_universe = sorted(set(wanted) - set(todo))
        if report.requested_not_in_universe:
            logger.warning(
                "Requested tickers not active in the universe (skipped): %s",
                ", ".join(report.requested_not_in_universe),
            )
    logger.info("Metrics: %d active constituents to process", len(todo))

    load_start = dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)

    # Benchmark return series, loaded once for the whole run.
    benchmark_frames = await _load_price_frames(
        session, list(BENCHMARK_TICKERS), load_start
    )
    benchmark_returns_map: dict[str, pd.Series] = {
        ticker: simple_returns(frame["adj_close"])
        for ticker, frame in benchmark_frames.items()
        if len(frame) >= 2
    }
    missing_benchmarks = set(BENCHMARK_TICKERS) - set(benchmark_returns_map)
    if missing_benchmarks:
        # _ensure_benchmarks just ingested them — empty here means something
        # is genuinely wrong; betas/corrs for the whole run would be NULL.
        raise RuntimeError(
            f"Benchmark series unavailable after ingest: {sorted(missing_benchmarks)}"
        )

    computed_at = dt.datetime.now(dt.UTC)

    for batch in chunked(todo, batch_size):
        frames = await _load_price_frames(session, batch, load_start)
        fundamentals = await _load_fundamentals(session, batch)

        records: list[dict[str, Any]] = []
        for ticker in batch:
            frame = frames.get(ticker)
            if frame is None or frame.empty:
                report.skipped_no_eod += 1
                continue
            as_of = pd.Timestamp(frame.index[-1]).date()
            metrics = compute_ticker_metrics(
                frame, benchmark_returns_map, fundamentals.get(ticker), as_of
            )
            for col in METRIC_COLUMNS:
                if metrics[col] is None:
                    report.null_counts[col] += 1
            records.append(
                {"ticker": ticker, "computed_at": computed_at, "as_of": as_of}
                | metrics
            )

        if records:
            for chunk in chunked(records, _METRICS_UPSERT_CHUNK):
                await session.execute(build_metrics_upsert(chunk))
            await session.commit()
        report.computed += len(records)
        logger.info(
            "Metrics: %d/%d computed (%d skipped)",
            report.computed,
            len(todo),
            report.skipped_no_eod,
        )

    if report.computed > 0:
        await refresh_screener_equity_snapshot(session)

    report.elapsed_seconds = time.monotonic() - started
    return report
