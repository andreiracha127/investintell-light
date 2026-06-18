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
from app.optimizer import data as optimizer_data
from app.schemas.analysis import RangeKey
from app.schemas.monte_carlo import (
    ConfidenceBar,
    MonteCarloParams,
    MonteCarloResponse,
    PortfolioMonteCarloParams,
    PortfolioMonteCarloRequest,
    PortfolioMonteCarloResponse,
    Statistic,
)
from app.services.portfolio_builder import _to_data_ref
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


def assemble_portfolio_monte_carlo(
    portfolio_returns: np.ndarray,
    *,
    statistic: Statistic,
    n_assets: int,
    n_simulations: int,
    horizons: list[int] | None,
    risk_free_rate: float,
    seed: int | None,
) -> PortfolioMonteCarloResponse:
    """Build the portfolio projection payload from a 1-D return array (pure, no I/O).

    Analogous to ``assemble_monte_carlo`` but the params carry ``n_assets``
    instead of a ticker/range. Reuses the exact pure
    ``block_bootstrap_monte_carlo`` core.

    Raises:
        InsufficientDataError: if the analytics layer rejects the input (too
            little history, or history too short for the horizon).
    """
    try:
        result = block_bootstrap_monte_carlo(
            portfolio_returns,
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

    return PortfolioMonteCarloResponse(
        params=PortfolioMonteCarloParams(
            statistic=statistic,
            n_assets=n_assets,
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


async def run_portfolio_monte_carlo(
    session: AsyncSession,
    payload: PortfolioMonteCarloRequest,
) -> PortfolioMonteCarloResponse:
    """Load common-history returns, build the synthetic portfolio NAV, then assemble.

    The target weights are held constant over the horizon (implicit continuous
    rebalancing). The weight vector is aligned to ``frame.columns`` by the
    'fund:{id}' / 'equity:{TICKER}' label scheme, so column order from the
    loader never matters. Loader and Monte Carlo history guards surface as
    InsufficientDataError, which the route maps to 422.

    Raises:
        InsufficientDataError: unknown asset / empty window, fewer than common
            dates, or the analytics layer rejects the synthetic return array.
    """
    refs = [_to_data_ref(pos.asset) for pos in payload.positions]
    try:
        frame = await optimizer_data.load_aligned_returns(
            session, refs, window_days=payload.window_days
        )
    except ValueError as exc:
        raise InsufficientDataError(str(exc)) from exc

    # Align the weight vector to the loaded frame's columns by label. A position
    # whose label is absent from the frame is a fail-loud domain error; the
    # loader should return exactly the requested labels, never a silent subset.
    weight_by_label = {
        ref.label: pos.weight for ref, pos in zip(refs, payload.positions, strict=True)
    }
    try:
        w = np.array([weight_by_label[str(col)] for col in frame.columns], dtype=float)
    except KeyError as exc:
        raise InsufficientDataError(
            f"position {exc.args[0]} is missing from the loaded return frame - "
            "every position must resolve to a column in the aligned history"
        ) from exc

    portfolio_returns = frame.to_numpy(dtype=float) @ w
    return assemble_portfolio_monte_carlo(
        portfolio_returns,
        statistic=payload.statistic,
        n_assets=len(payload.positions),
        n_simulations=payload.n_simulations,
        horizons=payload.horizons,
        risk_free_rate=payload.risk_free_rate,
        seed=payload.seed,
    )
