"""Return-matrix loading for the optimizer (F8.3) — DB → aligned daily returns.

Mixed universes: funds by ``instrument_id`` (fund_nav: ``return_1d``, falling
back to the log-diff of ``nav`` where ``return_1d`` is NULL) and equities by
``ticker`` (log returns of ``eod_prices.adj_close``). Series are aligned on
the intersection of dates; fewer than ``MIN_COMMON_OBS`` common observations
raises a ValueError (the route maps it to 422).

This module performs I/O only — all math lives in ``engine`` /
``black_litterman``.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eod_price import EodPrice
from app.models.fund import Fund, FundNav, FundRiskLatest
from app.services import funds_catalog

DEFAULT_WINDOW_DAYS = 730
MIN_COMMON_OBS = 400


@dataclass(frozen=True)
class FundAssetRef:
    id: uuid.UUID

    @property
    def label(self) -> str:
        return f"fund:{self.id}"


@dataclass(frozen=True)
class EquityAssetRef:
    ticker: str

    @property
    def label(self) -> str:
        return f"equity:{self.ticker}"


AssetRef = FundAssetRef | EquityAssetRef


def _fund_return_series(rows: list[tuple[dt.date, float | None, float | None]]) -> pd.Series:
    """Daily returns from (nav_date, nav, return_1d) rows, ordered by date.

    Prefers the precomputed ``return_1d``; where it is NULL, falls back to
    log(navₜ/navₜ₋₁) when both NAVs are present and positive. Days with
    neither are dropped (the date-intersection step handles alignment).
    """
    dates: list[dt.date] = []
    values: list[float] = []
    prev_nav: float | None = None
    for nav_date, nav, return_1d in rows:
        if return_1d is not None:
            dates.append(nav_date)
            values.append(float(return_1d))
        elif nav is not None and nav > 0 and prev_nav is not None and prev_nav > 0:
            dates.append(nav_date)
            values.append(float(np.log(nav / prev_nav)))
        if nav is not None and nav > 0:
            prev_nav = float(nav)
    return pd.Series(values, index=pd.Index(dates), dtype=float)


async def _load_fund_returns(
    session: AsyncSession, ref: FundAssetRef, since: dt.date
) -> pd.Series:
    result = await session.execute(
        select(FundNav.nav_date, FundNav.nav, FundNav.return_1d)
        .where(FundNav.instrument_id == ref.id, FundNav.nav_date >= since)
        .order_by(FundNav.nav_date)
    )
    rows = [
        (nav_date, float(nav) if nav is not None else None, float(r1d) if r1d is not None else None)
        for nav_date, nav, r1d in result.all()
    ]
    if not rows:
        raise ValueError(f"unknown asset or no NAV history in window: {ref.label}")
    return _fund_return_series(rows)


async def _load_equity_returns(
    session: AsyncSession, ref: EquityAssetRef, since: dt.date
) -> pd.Series:
    result = await session.execute(
        select(EodPrice.date, EodPrice.adj_close)
        .where(EodPrice.ticker == ref.ticker, EodPrice.date >= since)
        .order_by(EodPrice.date)
    )
    rows = result.all()
    if not rows:
        raise ValueError(f"unknown asset or no price history in window: {ref.label}")
    prices = pd.Series(
        [float(close) for _date, close in rows],
        index=pd.Index([row_date for row_date, _close in rows]),
        dtype=float,
    )
    prices = prices[prices > 0]
    log_prices = pd.Series(np.log(prices.to_numpy()), index=prices.index, dtype=float)
    return log_prices.diff().dropna()


async def load_aligned_returns(
    session: AsyncSession,
    assets: list[AssetRef],
    window_days: int = DEFAULT_WINDOW_DAYS,
    today: dt.date | None = None,
) -> pd.DataFrame:
    """T×n daily-return frame (columns = asset labels, index = common dates).

    Raises ValueError (→ 422 at the route) on: duplicate assets, an unknown
    asset / empty window, or fewer than ``MIN_COMMON_OBS`` common dates.
    """
    if len(assets) < 2:
        raise ValueError("at least 2 assets are required to optimize")
    labels = [ref.label for ref in assets]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"duplicate assets in request: {', '.join(duplicates)}")
    if window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    today = today or dt.date.today()
    since = today - dt.timedelta(days=window_days)

    series: dict[str, pd.Series] = {}
    for ref in assets:
        if isinstance(ref, FundAssetRef):
            series[ref.label] = await _load_fund_returns(session, ref, since)
        else:
            series[ref.label] = await _load_equity_returns(session, ref, since)

    frame = pd.DataFrame(series).dropna()
    if len(frame) < MIN_COMMON_OBS:
        raise ValueError(
            f"insufficient common history: {len(frame)} overlapping observations across the "
            f"{len(assets)} assets in the last {window_days} days "
            f"(minimum {MIN_COMMON_OBS}) — widen the window or drop the short-history assets"
        )
    return frame


async def load_fund_aum(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float | None]:
    """AUM (funds.aum_usd) per instrument — None where the source has no AUM."""
    if not fund_ids:
        return {}
    result = await session.execute(
        select(Fund.instrument_id, Fund.aum_usd).where(Fund.instrument_id.in_(fund_ids))
    )
    found = {row[0]: (float(row[1]) if row[1] is not None else None) for row in result.all()}
    return {fund_id: found.get(fund_id) for fund_id in fund_ids}


@dataclass(frozen=True)
class UniverseFund:
    """A fund selected by a universe spec — id plus display labels."""

    id: uuid.UUID
    ticker: str | None
    name: str


async def select_universe_funds(
    session: AsyncSession,
    filters: funds_catalog.FundFilters,
    *,
    rank_by: str,
    rank_dir: str,
    max_assets: int,
    require_aum: bool = False,
    include_ids: Sequence[str] | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_obs: int = MIN_COMMON_OBS,
    today: dt.date | None = None,
) -> list[UniverseFund]:
    """Resolve a universe spec to ranked fund candidates (top ``max_assets``).

    Reuses the GET /funds filter predicates and sort whitelist, and only keeps
    funds that EACH have at least ``min_obs`` non-null NAV observations in the
    window — a per-fund coverage heuristic that screens out short-history funds.
    It does NOT by itself guarantee the cross-fund date intersection clears
    ``MIN_COMMON_OBS``; ``load_aligned_returns`` still enforces that on the
    resolved set (a fail-loud 422 if the overlap falls short). ``require_aum``
    (BL paths) additionally drops funds without a positive AUM, so market
    weights are always computable on the result.
    """
    today = today or dt.date.today()
    since = today - dt.timedelta(days=window_days)

    nav_counts = (
        select(FundNav.instrument_id, func.count().label("n"))
        .where(FundNav.nav_date >= since, FundNav.nav.is_not(None))
        .group_by(FundNav.instrument_id)
        .subquery()
    )

    order_col = funds_catalog.sort_column(rank_by)
    order = order_col.desc() if rank_dir == "desc" else order_col.asc()

    conditions = list(funds_catalog.filter_conditions(filters))
    if require_aum:
        conditions.append(Fund.aum_usd.is_not(None))
        conditions.append(Fund.aum_usd > 0)
    if include_ids:
        conditions.append(Fund.instrument_id.in_(list(include_ids)))

    stmt = (
        select(Fund.instrument_id, Fund.ticker, Fund.name)
        .select_from(Fund)
        .outerjoin(FundRiskLatest, FundRiskLatest.instrument_id == Fund.instrument_id)
        .join(nav_counts, nav_counts.c.instrument_id == Fund.instrument_id)
        .where(*conditions, nav_counts.c.n >= min_obs)
        .order_by(order.nulls_last(), Fund.ticker.nulls_last(), Fund.instrument_id)
        .limit(max_assets)
    )
    result = await session.execute(stmt)
    return [UniverseFund(id=iid, ticker=ticker, name=name) for iid, ticker, name in result.all()]
