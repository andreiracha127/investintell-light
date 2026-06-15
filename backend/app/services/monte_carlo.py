"""Assembly + orchestration for POST /monte-carlo/projection.

assemble_monte_carlo is a pure adapter (numpy return array -> response schema,
no I/O). run_monte_carlo is the async orchestrator: warm EOD, read the DB,
build the daily-return array, call assemble. Mirrors the assemble_* / run_*
split and the underscore-aliased read-helper imports used by
app.services.statistics.

Scale contract: drawdown/return percentiles are decimal fractions; sharpe is
unitless. The analytics layer's hard ValueError guards are re-raised as
InsufficientDataError so the route maps them to HTTP 422.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.monte_carlo import block_bootstrap_monte_carlo
from app.analytics.returns import simple_returns
from app.api._shared import ensure_eod_or_http_error
from app.ingestion.service import HISTORY_FLOOR
from app.schemas.analysis import RangeKey
from app.schemas.monte_carlo import (
    ConfidenceBar,
    MonteCarloParams,
    MonteCarloResponse,
    Statistic,
)
from app.services._series import (
    RANGE_DAYS,
)
from app.services._series import (
    select_adj_close_rows as _select_adj_close_rows,
)
from app.services._series import (
    select_date_bounds as _select_date_bounds,
)
from app.services.stock_analysis import (
    InsufficientDataError,
    build_adj_close_series,
)
from app.tiingo.client import TiingoClient

_MIN_RETURNS = 42


def assemble_monte_carlo(
    daily_returns: np.ndarray,
    *,
    ticker: str,
    statistic: Statistic,
    range_key: RangeKey,
    n_simulations: int,
    horizons: list[int] | None,
    risk_free_rate: float,
    seed: int | None,
) -> MonteCarloResponse:
    """Build the projection payload from a daily-return array (pure, no I/O).

    Raises:
        InsufficientDataError: if the analytics layer rejects the input
            (too little history, or history too short for the horizon).
    """
    try:
        result = block_bootstrap_monte_carlo(
            daily_returns,
            n_simulations=n_simulations,
            horizons=horizons,
            statistic=statistic,
            risk_free_rate=risk_free_rate,
            seed=seed,
        )
    except ValueError as exc:
        # "Unknown statistic" cannot occur (the schema constrains the literal);
        # the remaining ValueErrors are the history/horizon guards.
        raise InsufficientDataError(str(exc)) from exc

    return MonteCarloResponse(
        params=MonteCarloParams(
            ticker=ticker,
            statistic=statistic,
            range=range_key,
            n_simulations=n_simulations,
            risk_free_rate=risk_free_rate,
            seed=seed,
        ),
        percentiles=result.percentiles,
        mean=result.mean,
        median=result.median,
        std=result.std,
        historical_value=result.historical_value,
        historical_horizon_days=result.historical_horizon_days,
        historical_percentile_rank=result.historical_percentile_rank,
        confidence_bars=[ConfidenceBar(**bar) for bar in result.confidence_bars],
        degraded=result.degraded,
        degraded_reason=result.degraded_reason,
    )


async def run_monte_carlo(
    session: AsyncSession,
    client: TiingoClient,
    *,
    ticker: str,
    statistic: Statistic,
    range_key: RangeKey,
    n_simulations: int,
    horizons: list[int] | None,
    risk_free_rate: float,
    seed: int | None,
) -> MonteCarloResponse:
    """Warm EOD, read adjusted closes, build the return array, then assemble.

    Raises:
        InsufficientDataError: no price rows, fewer than 2 closes, or the
            analytics layer rejects the return array.
    """
    today = dt.date.today()
    ensure_start = (
        HISTORY_FLOOR
        if range_key == "MAX"
        else today - dt.timedelta(days=RANGE_DAYS[range_key])
    )
    await ensure_eod_or_http_error(session, client, [ticker], ensure_start, today)

    first, last = await _select_date_bounds(session, ticker)
    if first is None or last is None:
        raise InsufficientDataError(f"No price data available for {ticker}.")
    end = last
    start = (
        first if range_key == "MAX" else end - dt.timedelta(days=RANGE_DAYS[range_key])
    )

    rows = await _select_adj_close_rows(session, ticker, start, end)
    closes = build_adj_close_series(rows)
    if len(closes) < 2:
        raise InsufficientDataError(
            f"Only {len(closes)} price rows for {ticker} — not enough to compute returns."
        )

    returns = simple_returns(closes).to_numpy(dtype=float)
    if len(returns) < _MIN_RETURNS:
        raise InsufficientDataError(
            f"Only {len(returns)} daily returns for {ticker} — at least {_MIN_RETURNS} "
            "are required for a block-bootstrap projection. Use a wider range."
        )

    return assemble_monte_carlo(
        returns,
        ticker=ticker,
        statistic=statistic,
        range_key=range_key,
        n_simulations=n_simulations,
        horizons=horizons,
        risk_free_rate=risk_free_rate,
        seed=seed,
    )
