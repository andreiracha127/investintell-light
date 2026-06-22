"""Backend Tier A services for the fund dossier endpoints.

The route layer owns HTTP status mapping; this module owns DB reads and pure
assembly. Fund analytics are computed from ``nav_timeseries`` and catalog
metrics are read from ``funds_v`` / ``fund_risk_latest_mv`` / ``fund_holdings_v``.
"""

import datetime as dt
import logging
import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import (
    MIN_IN_RANGE_RETURNS,
    annualized_volatility,
    best_worst_day,
    historical_cvar,
    historical_var,
    max_drawdown,
    return_histogram,
    rolling_volatility,
    simple_returns,
    total_return,
)
from app.analytics._validation import to_date
from app.core.config import get_settings
from app.models.fund import Fund, FundHolding, FundNav, FundRiskLatest
from app.schemas.analysis import DatedValue, DrawdownOut, HistogramOut, RangeKey
from app.schemas.fund_analysis import (
    FundAnalysisHeader,
    FundAnalysisParams,
    FundAnalysisResponse,
    FundAnalysisStats,
    FundHoldingsTopResponse,
    FundPeerItem,
    FundPeersResponse,
    FundScatterResponse,
    FundSectorExposure,
    FundTopHolding,
)
from app.services import lookthrough
from app.services._series import RANGE_DAYS, resample_weekly, series_points
from app.services.funds_catalog import UNCLASSIFIED_LABEL
from app.services.stock_analysis import lookback_pad_days

logger = logging.getLogger(__name__)

_HISTOGRAM_BINS = 20

# Display ranges whose growth/drawdown/rolling line series are weekly-downsampled
# to bound the payload (mirrors timeseries._INTERVAL_BY_RANGE: 5Y and MAX →
# weekly). Statistics are ALWAYS computed on the daily base and are unaffected.
_WEEKLY_DISPLAY_RANGES = frozenset({"5Y", "MAX"})


class FundAnalysisError(Exception):
    """Base for fund-analysis assembly failures mapped to HTTP 422."""


class InsufficientFundDataError(FundAnalysisError):
    """Not enough NAV history to build a complete analysis payload."""


class FundPayloadTooLargeError(FundAnalysisError):
    """The requested payload would exceed the configured point budget."""


@dataclass(frozen=True)
class FundIdentity:
    instrument_id: uuid.UUID
    ticker: str | None
    name: str


NavRow = tuple[dt.date, float]


def build_nav_series(records: Iterable[NavRow]) -> pd.Series:
    """Build a sorted positive-NAV series indexed by date."""
    frame = pd.DataFrame(list(records), columns=["date", "nav"])
    if frame.empty:
        return pd.Series(dtype=float)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["nav"] = frame["nav"].astype(float)
    series = frame.set_index("date")["nav"].sort_index()
    return series[series > 0]


def _rolling_sharpe(returns: pd.Series, window: int) -> pd.Series:
    if window < 2:
        raise ValueError(f"rolling_sharpe requires window >= 2, got {window}")
    if len(returns) < window:
        raise ValueError(
            f"rolling_sharpe requires at least window={window} points, got {len(returns)}"
        )
    mean = returns.rolling(window, min_periods=window).mean()
    std = returns.rolling(window, min_periods=window).std(ddof=1).replace(0.0, np.nan)
    return (mean / std) * math.sqrt(252)


def _visible_line(series: pd.Series, range_key: RangeKey) -> list[tuple[dt.date, float]]:
    """Emit a daily line, or a weekly-bounded 5Y/MAX line preserving the first point."""
    clean = series.dropna()
    if range_key not in _WEEKLY_DISPLAY_RANGES:
        return series_points(clean)
    weekly = resample_weekly(clean)
    if len(clean) and (weekly.empty or weekly.index[0] != clean.index[0]):
        weekly = pd.concat([clean.iloc[:1], weekly]).sort_index()
        weekly = weekly[~weekly.index.duplicated(keep="first")]
    return series_points(weekly)


def _sliced_rolling_line(
    series: pd.Series, *, start: dt.date, range_key: RangeKey
) -> list[tuple[dt.date, float]]:
    daily = series[series.index > pd.Timestamp(start)].dropna()
    weekly_display = range_key in _WEEKLY_DISPLAY_RANGES
    return series_points(resample_weekly(daily) if weekly_display else daily)


def _monthly_return_points(nav: pd.Series) -> list[tuple[dt.date, float]]:
    if len(nav) < 2:
        return []
    month_end = nav.resample("ME").last().dropna()
    returns = month_end.pct_change().dropna()
    return series_points(returns)


def _assert_series_budget(
    max_points: int, named_series: Sequence[tuple[str, Sequence[Any]]]
) -> None:
    longest_name, longest = max(
        ((name, len(series)) for name, series in named_series), key=lambda item: item[1]
    )
    if longest > max_points:
        raise FundPayloadTooLargeError(
            f"Fund analysis series {longest_name} has {longest} points, exceeding "
            f"the maximum of {max_points}."
        )


def assemble_fund_analysis(
    nav: pd.Series,
    *,
    fund: FundIdentity,
    range_key: RangeKey,
    window: int,
    start: dt.date,
    end: dt.date,
    max_points: int,
) -> FundAnalysisResponse:
    """Assemble the fund Performance payload from padded daily NAV history."""
    if len(nav) < 2:
        raise InsufficientFundDataError(
            f"Only {len(nav)} NAV rows available for fund {fund.instrument_id}."
        )

    start_ts = pd.Timestamp(start)
    visible = nav[nav.index >= start_ts]
    if len(visible) < 2:
        raise InsufficientFundDataError(
            f"Only {len(visible)} in-range NAV rows for fund {fund.instrument_id} "
            f"over range {range_key}."
        )

    returns = simple_returns(nav)
    in_range_returns = returns[returns.index > start_ts]
    if len(in_range_returns) < MIN_IN_RANGE_RETURNS:
        raise InsufficientFundDataError(
            f"Only {len(in_range_returns)} in-range daily returns for fund "
            f"{fund.instrument_id} over range {range_key}; at least "
            f"{MIN_IN_RANGE_RETURNS} are required."
        )
    if len(returns) < window:
        raise InsufficientFundDataError(
            f"Rolling window of {window} NAV days exceeds available padded history "
            f"({len(returns)} returns)."
        )

    last_nav = float(nav.iloc[-1])
    prev_nav = float(nav.iloc[-2])
    growth_daily = (visible / float(visible.iloc[0])) * 100.0
    drawdown_daily = visible / visible.cummax() - 1.0

    growth = _visible_line(growth_daily, range_key)
    drawdown_points = _visible_line(drawdown_daily, range_key)
    monthly_returns = _monthly_return_points(visible)
    rolling_vol = _sliced_rolling_line(
        rolling_volatility(returns, window), start=start, range_key=range_key
    )
    rolling_sharpe = _sliced_rolling_line(
        _rolling_sharpe(returns, window), start=start, range_key=range_key
    )

    _assert_series_budget(
        max_points,
        [
            ("growth_of_100", growth),
            ("drawdown", drawdown_points),
            ("monthly_returns", monthly_returns),
            ("rolling_volatility", rolling_vol),
            ("rolling_sharpe", rolling_sharpe),
        ],
    )

    histogram = return_histogram(in_range_returns, bins=_HISTOGRAM_BINS)
    drawdown = max_drawdown(visible)
    best_worst = best_worst_day(in_range_returns)

    return FundAnalysisResponse(
        params=FundAnalysisParams(
            range=range_key,
            window=window,
            start_date=start,
            end_date=end,
        ),
        header=FundAnalysisHeader(
            instrument_id=fund.instrument_id,
            ticker=fund.ticker,
            name=fund.name,
            last_nav=last_nav,
            prev_nav=prev_nav,
            change=last_nav - prev_nav,
            change_pct=(last_nav - prev_nav) / prev_nav,
            as_of=to_date(nav.index[-1]),
        ),
        growth_of_100=growth,
        monthly_returns=monthly_returns,
        rolling_volatility=rolling_vol,
        rolling_sharpe=rolling_sharpe,
        drawdown=drawdown_points,
        histogram=HistogramOut(
            bin_edges=histogram.bin_edges,
            counts=histogram.counts,
            counts_normalized=histogram.counts_normalized,
        ),
        stats=FundAnalysisStats(
            annualized_volatility=annualized_volatility(in_range_returns),
            var_95=historical_var(in_range_returns, confidence=0.95),
            cvar_95=historical_cvar(in_range_returns, confidence=0.95),
            total_return=total_return(in_range_returns),
            max_drawdown=DrawdownOut(
                depth=drawdown.depth,
                peak_date=drawdown.peak_date,
                trough_date=drawdown.trough_date,
            ),
            best_day=DatedValue(date=best_worst.best_date, value=best_worst.best_return),
            worst_day=DatedValue(date=best_worst.worst_date, value=best_worst.worst_return),
        ),
    )


async def select_nav_date_bounds(
    session: AsyncSession, instrument_id: uuid.UUID
) -> tuple[dt.date | None, dt.date | None]:
    result = await session.execute(
        select(func.min(FundNav.nav_date), func.max(FundNav.nav_date)).where(
            FundNav.instrument_id == instrument_id,
            FundNav.nav.is_not(None),
        )
    )
    first, last = result.one()
    return first, last


async def select_nav_rows(
    session: AsyncSession,
    instrument_id: uuid.UUID,
    start: dt.date,
    end: dt.date,
) -> list[NavRow]:
    result = await session.execute(
        select(FundNav.nav_date, FundNav.nav)
        .where(
            FundNav.instrument_id == instrument_id,
            FundNav.nav_date >= start,
            FundNav.nav_date <= end,
            FundNav.nav.is_not(None),
        )
        .order_by(FundNav.nav_date)
    )
    return [(nav_date, float(nav)) for nav_date, nav in result.all()]


async def fetch_fund_analysis(
    session: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    range_key: RangeKey,
    window: int,
    max_points: int,
) -> FundAnalysisResponse | None:
    fund = await session.get(Fund, instrument_id)
    if fund is None:
        return None
    first_date, last_date = await select_nav_date_bounds(session, instrument_id)
    if first_date is None or last_date is None:
        raise InsufficientFundDataError(f"No NAV history for fund {instrument_id}.")

    end = last_date
    start = first_date if range_key == "MAX" else end - dt.timedelta(days=RANGE_DAYS[range_key])
    query_start = start - dt.timedelta(days=lookback_pad_days(window))
    nav = build_nav_series(await select_nav_rows(session, instrument_id, query_start, end))
    return assemble_fund_analysis(
        nav,
        fund=FundIdentity(fund.instrument_id, fund.ticker, fund.name),
        range_key=range_key,
        window=window,
        start=start,
        end=end,
        max_points=max_points,
    )


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _sector_label(holding: FundHolding) -> str | None:
    return holding.gics_sector or holding.sector or holding.asset_class


def _sector_breakdown_from_holdings(holdings: Sequence[FundHolding]) -> list[FundSectorExposure]:
    buckets: dict[str, float] = {}
    labels: dict[str, str] = {}
    for holding in holdings:
        pct = _float(holding.pct_of_nav)
        label = _sector_label(holding)
        if pct is None or label is None:
            continue
        buckets[label] = buckets.get(label, 0.0) + pct
        labels[label] = label
    return [
        FundSectorExposure(
            key=key,
            label=labels[key],
            direct_pct=value,
            indirect_pct=0.0,
            total_pct=value,
            source="holdings",
        )
        for key, value in sorted(buckets.items(), key=lambda item: -abs(item[1]))
    ]


async def _sector_breakdown_from_lookthrough(
    datalake: AsyncSession | None, series_id: str
) -> list[FundSectorExposure]:
    if datalake is None:
        return []
    try:
        data = await lookthrough.fetch_series_lookthrough(
            datalake, series_id, dimension="sector"
        )
    except SQLAlchemyError as exc:
        logger.warning("Fund holdings sector look-through degraded for %s: %s", series_id, exc)
        return []
    if data is None:
        return []
    return [
        FundSectorExposure(
            key=row.key,
            label=row.label or row.key,
            direct_pct=row.direct_pct,
            indirect_pct=row.indirect_pct,
            total_pct=row.total_pct,
            source="lookthrough",
        )
        for row in sorted(data.exposures, key=lambda r: -abs(r.total_pct))
        if row.dimension == "sector"
    ]


async def _gics_sector_by_cusip(
    datalake: AsyncSession | None, holdings: Sequence[FundHolding]
) -> dict[str, str]:
    """Map CUSIP -> GICS sector from the datalake (same source as the breakdown).

    App-DB holdings only carry the raw N-PORT asset category; the GICS sector
    lives in sec_cusip_ticker_map keyed by CUSIP.
    """
    if datalake is None:
        return {}
    cusips = [h.cusip for h in holdings if h.cusip]
    if not cusips:
        return {}
    try:
        rows = (
            await datalake.execute(
                text(
                    """
                    SELECT DISTINCT ON (cusip) cusip, gics_sector
                    FROM sec_cusip_ticker_map
                    WHERE cusip = ANY(:cusips)
                      AND NULLIF(btrim(gics_sector), '') IS NOT NULL
                    ORDER BY cusip
                    """
                ),
                {"cusips": cusips},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        logger.warning("Fund holdings GICS-by-cusip resolution degraded: %s", exc)
        return {}
    return {row["cusip"]: row["gics_sector"] for row in rows}


async def fetch_fund_holdings_top(
    session: AsyncSession,
    datalake: AsyncSession | None,
    instrument_id: uuid.UUID,
    *,
    limit: int,
    use_db_first: bool | None = None,
) -> FundHoldingsTopResponse | None:
    """Top holdings + sector breakdown. DB-first lê top holdings de
    fund_top_holdings_mv (GICS já resolvido); sector breakdown continua de
    nport_lookthrough_exposures. Fallback ao legado quando a flag está off.
    """
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first
    if not use_db_first:
        return await _fetch_fund_holdings_top_legacy(
            session, datalake, instrument_id, limit=limit
        )

    fund = await session.get(Fund, instrument_id)
    if fund is None:
        return None
    rows = (
        await session.execute(
            text(
                """
                SELECT report_date, rank, issuer_name, cusip, isin,
                       asset_class, sector, gics_sector, market_value, pct_of_nav
                FROM fund_top_holdings_mv
                WHERE series_id = :series_id
                  AND rank <= :limit
                ORDER BY rank
                """
            ),
            {"series_id": fund.series_id, "limit": limit},
        )
    ).mappings().all()

    report_date = rows[0]["report_date"] if rows else None
    sector_breakdown = await _sector_breakdown_from_lookthrough(datalake, fund.series_id)
    reported = [float(r["pct_of_nav"]) for r in rows if r["pct_of_nav"] is not None]
    return FundHoldingsTopResponse(
        instrument_id=instrument_id,
        series_id=fund.series_id,
        report_date=report_date,
        top_holdings=[
            FundTopHolding(
                rank=r["rank"],
                issuer_name=r["issuer_name"],
                cusip=r["cusip"],
                isin=r["isin"],
                asset_class=r["asset_class"],
                sector=r["sector"],
                gics_sector=r["gics_sector"],
                sector_label=r["gics_sector"] or r["sector"],
                market_value=_float(r["market_value"]),
                pct_of_nav=_float(r["pct_of_nav"]),
            )
            for r in rows
        ],
        sector_breakdown=sector_breakdown,
        pct_of_nav_total=sum(reported) if reported else None,
    )


async def _fetch_fund_holdings_top_legacy(
    session: AsyncSession,
    datalake: AsyncSession | None,
    instrument_id: uuid.UUID,
    *,
    limit: int,
) -> FundHoldingsTopResponse | None:
    fund = await session.get(Fund, instrument_id)
    if fund is None:
        return None
    latest_report = await session.scalar(
        select(func.max(FundHolding.report_date)).where(FundHolding.series_id == fund.series_id)
    )
    holdings: list[FundHolding] = []
    if latest_report is not None:
        holdings = list(
            (
                await session.execute(
                    select(FundHolding)
                    .where(
                        FundHolding.series_id == fund.series_id,
                        FundHolding.report_date == latest_report,
                    )
                    .order_by(FundHolding.rank)
                    .limit(limit)
                )
            ).scalars()
        )

    sector_breakdown = await _sector_breakdown_from_lookthrough(datalake, fund.series_id)
    if not sector_breakdown:
        sector_breakdown = _sector_breakdown_from_holdings(holdings)

    # The app-DB holdings carry the raw N-PORT asset category (e.g. "CORP"), not
    # the GICS sector. Resolve the GICS sector per holding by CUSIP from the same
    # datalake map the sector_breakdown uses, so the table and the chart agree.
    cusip_gics = await _gics_sector_by_cusip(datalake, holdings)

    reported = [float(h.pct_of_nav) for h in holdings if h.pct_of_nav is not None]
    return FundHoldingsTopResponse(
        instrument_id=instrument_id,
        series_id=fund.series_id,
        report_date=latest_report,
        top_holdings=[
            FundTopHolding(
                rank=h.rank,
                issuer_name=h.issuer_name,
                cusip=h.cusip,
                isin=h.isin,
                asset_class=h.asset_class,
                sector=h.sector,
                gics_sector=cusip_gics.get(h.cusip or "") or h.gics_sector,
                sector_label=cusip_gics.get(h.cusip or "") or _sector_label(h),
                market_value=_float(h.market_value),
                pct_of_nav=_float(h.pct_of_nav),
            )
            for h in holdings
        ],
        sector_breakdown=sector_breakdown,
        pct_of_nav_total=sum(reported) if reported else None,
    )


async def fetch_fund_peers(
    session: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    limit: int,
) -> FundPeersResponse | None:
    fund = await session.get(Fund, instrument_id)
    if fund is None:
        return None
    risk = await session.get(FundRiskLatest, instrument_id)
    cohort = (
        risk.peer_strategy_label
        if risk is not None and risk.peer_strategy_label
        else fund.strategy_label
    )
    result = await session.execute(
        select(Fund, FundRiskLatest)
        .select_from(Fund)
        .outerjoin(FundRiskLatest, FundRiskLatest.instrument_id == Fund.instrument_id)
        .where(
            or_(
                FundRiskLatest.peer_strategy_label == cohort,
                Fund.strategy_label == cohort,
            )
        )
        .order_by(
            FundRiskLatest.sharpe_1y.desc().nulls_last(),
            Fund.aum_usd.desc().nulls_last(),
            Fund.ticker.nulls_last(),
            Fund.instrument_id,
        )
        .limit(limit)
    )
    items: list[FundPeerItem] = []
    for peer, peer_risk in result.all():
        items.append(
            FundPeerItem(
                instrument_id=peer.instrument_id,
                ticker=peer.ticker,
                name=peer.name,
                strategy_label=peer.strategy_label,
                expense_ratio=_float(peer.expense_ratio),
                return_1y=_float(peer_risk.return_1y) if peer_risk else None,
                volatility_1y=_float(peer_risk.volatility_1y) if peer_risk else None,
                sharpe_1y=_float(peer_risk.sharpe_1y) if peer_risk else None,
                max_drawdown_1y=_float(peer_risk.max_drawdown_1y) if peer_risk else None,
                cvar_95_12m=_float(peer_risk.cvar_95_12m) if peer_risk else None,
                is_target=peer.instrument_id == instrument_id,
            )
        )
    return FundPeersResponse(
        instrument_id=instrument_id,
        cohort_label=cohort,
        count=len(items),
        items=items,
    )


async def fetch_funds_scatter(session: AsyncSession, *, limit: int) -> FundScatterResponse:
    result = await session.execute(
        select(
            Fund.instrument_id,
            Fund.name,
            Fund.ticker,
            Fund.strategy_label,
            FundRiskLatest.return_1y,
            FundRiskLatest.volatility_1y,
            FundRiskLatest.cvar_95_12m,
        )
        .select_from(Fund)
        .join(FundRiskLatest, FundRiskLatest.instrument_id == Fund.instrument_id)
        .where(
            Fund.strategy_label.is_distinct_from(UNCLASSIFIED_LABEL),
            FundRiskLatest.return_1y.is_not(None),
            FundRiskLatest.volatility_1y.is_not(None),
            FundRiskLatest.cvar_95_12m.is_not(None),
        )
        .order_by(Fund.aum_usd.desc().nulls_last(), Fund.instrument_id)
        .limit(limit)
    )
    rows = result.all()
    return FundScatterResponse(
        count=len(rows),
        instrument_ids=[row.instrument_id for row in rows],
        names=[row.name for row in rows],
        tickers=[row.ticker for row in rows],
        strategies=[row.strategy_label for row in rows],
        expected_returns=[float(row.return_1y) for row in rows],
        volatilities=[float(row.volatility_1y) for row in rows],
        tail_risks=[float(row.cvar_95_12m) for row in rows],
    )
