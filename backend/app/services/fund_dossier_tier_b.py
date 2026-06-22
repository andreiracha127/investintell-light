"""P5 Tier B services for the fund dossier.

The route layer owns HTTP mapping; this module keeps DB reads explicit and all
analytics deterministic. The Light backend remains DB-first: no synthetic panel
data is fabricated when a source table is empty.
"""

import datetime as dt
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import numpy as np
import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import simple_returns
from app.core.config import get_settings
from app.models.fund import Fund, FundHolding, FundListRow, FundRiskLatest
from app.models.stock_holders_mv import HoldingReverseLookupRow
from app.schemas.analysis import SeriesPoint
from app.schemas.fund_analysis import (
    EmptyState,
    FundActiveShareResponse,
    FundCaptureRatios,
    FundDrawdownAnalysis,
    FundDrawdownPeriod,
    FundEntityAnalyticsResponse,
    FundFactorsResponse,
    FundInstitutionalRevealResponse,
    FundMarketSensitivity,
    FundRegimeBand,
    FundReturnDistribution,
    FundReturnStatistics,
    FundRiskStatistics,
    FundRiskTimeseriesResponse,
    FundRollingReturns,
    FundSourceMetadata,
    FundStyleBias,
    FundStyleDriftPeriod,
    FundStyleDriftResponse,
    FundStyleSectorWeight,
    FundTailRiskMetrics,
    HolderNetwork,
    HolderNetworkEdge,
    HolderNetworkNode,
    HoldingReverseLookupResponse,
    InsiderData,
    InsiderQuarterSentiment,
    InstitutionalHolder,
    InstitutionalOverlapSecurity,
    ReverseLookupFundExposure,
    ReverseLookupInstitution,
)
from app.core.config import get_settings
from app.services import series_sql
from app.services.fund_analysis import (
    FundAnalysisError,
    InsufficientFundDataError,
    build_nav_series,
    select_nav_date_bounds,
    select_nav_rows,
)
from app.services.stock_analysis import lookback_pad_days

WindowKey = Literal["3M", "6M", "1Y", "3Y", "5Y"]

WINDOW_DAYS: dict[WindowKey, int] = {
    "3M": 63,
    "6M": 126,
    "1Y": 252,
    "3Y": 756,
    "5Y": 1260,
}

_RF = 0.04
_TRADING_DAYS = 252
_STYLE_FACTORS = (
    ("size", "size_log_mkt_cap"),
    ("book_to_market", "book_to_market"),
    ("momentum", "mom_12_1"),
    ("quality", "quality_roa"),
    ("investment", "investment_growth"),
    ("profitability", "profitability_gross"),
)
_CUSIP_RE = re.compile(r"^[A-Z0-9]{6,12}$")
_TIER_C_HOLDING_LIMIT = 100
_TIER_C_13F_ROW_LIMIT = 500


class InvalidBenchmarkError(FundAnalysisError):
    """Benchmark id is syntactically valid but cannot be used for this endpoint."""


class TierBSourceError(FundAnalysisError):
    """A required Tier B source relation is unavailable or unreadable."""


@dataclass(frozen=True)
class HoldingsWeights:
    weights: dict[str, float]
    as_of: dt.date | None


@dataclass(frozen=True)
class BenchmarkHoldingsTarget:
    name: str | None
    series_ids: list[str]


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _series_points(series: pd.Series) -> list[SeriesPoint]:
    clean = series.dropna()
    return [
        (cast(pd.Timestamp, idx).date(), float(value)) for idx, value in clean.items()
    ]


def _significance(t_stat: float | None) -> str | None:
    if t_stat is None:
        return None
    level = abs(t_stat)
    if level >= 2.58:
        return "***"
    if level >= 1.96:
        return "**"
    if level >= 1.65:
        return "*"
    return None


def _empty(reason: str, source: str | None = None) -> EmptyState:
    return EmptyState(reason=reason, source=source)


def _source_error(source: str, exc: SQLAlchemyError) -> TierBSourceError:
    return TierBSourceError(f"{source} unavailable: {exc.__class__.__name__}")


def _is_missing_relation(exc: SQLAlchemyError) -> bool:
    text_value = str(getattr(exc, "orig", exc)).lower()
    return "undefinedtable" in text_value or "does not exist" in text_value


def _normalize_cusip(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    return normalized if _CUSIP_RE.match(normalized) else None


def _empty_network(fund: Fund) -> HolderNetwork:
    return HolderNetwork(
        nodes=[
            HolderNetworkNode(
                id=f"fund:{fund.instrument_id}",
                label=fund.ticker or fund.name,
                type="fund",
            )
        ],
        edges=[],
    )


def _sentiment_score(buy_value: float, sell_value: float) -> float | None:
    total = buy_value + sell_value
    if total <= 0:
        return None
    return max(-1.0, min(1.0, (buy_value - sell_value) / total))


async def _fund_or_none(session: AsyncSession, instrument_id: uuid.UUID) -> Fund | None:
    return await session.get(Fund, instrument_id)


async def _fund_or_missing(session: AsyncSession, instrument_id: uuid.UUID) -> Fund:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        raise LookupError(f"Fund {instrument_id} not found.")
    return fund


async def _latest_fund_holdings(
    session: AsyncSession,
    series_id: str,
    *,
    limit: int | None = _TIER_C_HOLDING_LIMIT,
) -> tuple[dt.date | None, list[FundHolding]]:
    latest_report = await session.scalar(
        select(func.max(FundHolding.report_date)).where(FundHolding.series_id == series_id)
    )
    if latest_report is None:
        return None, []
    stmt = (
        select(FundHolding)
        .where(
            FundHolding.series_id == series_id,
            FundHolding.report_date == latest_report,
            FundHolding.cusip.is_not(None),
        )
        .order_by(FundHolding.rank)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    holdings = list((await session.execute(stmt)).scalars())
    return latest_report, holdings


def _holding_cusips(holdings: list[FundHolding]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for holding in holdings:
        cusip = _normalize_cusip(holding.cusip)
        if cusip and cusip not in seen:
            seen.add(cusip)
            out.append(cusip)
    return out


def _factor_frame(factor_returns: Mapping[str, Any]) -> pd.DataFrame:
    dates = factor_returns.get("dates")
    values = factor_returns.get("values")
    if not isinstance(dates, list) or not isinstance(values, list) or not values:
        return pd.DataFrame()
    index = pd.to_datetime(dates)
    columns = [f"Factor {idx + 1}" for idx in range(len(values))]
    data = {
        name: pd.Series(raw, index=index, dtype=float)
        for name, raw in zip(columns, values, strict=False)
        if isinstance(raw, list) and len(raw) == len(index)
    }
    return pd.DataFrame(data).sort_index()


def _ols_market_sensitivities(
    fund_returns: pd.Series,
    factors: pd.DataFrame,
) -> list[FundMarketSensitivity]:
    joined = pd.concat([fund_returns.rename("fund"), factors], axis=1, join="inner").dropna()
    if joined.shape[0] < max(10, joined.shape[1] + 2) or factors.empty:
        return []

    y = joined["fund"].to_numpy(dtype=float)
    x = joined.drop(columns=["fund"]).to_numpy(dtype=float)
    x_design = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x_design, y, rcond=None)
    residuals = y - x_design @ beta
    dof = len(y) - x_design.shape[1]
    if dof <= 0:
        t_stats = np.full(beta.shape, np.nan)
    else:
        sigma2 = float((residuals @ residuals) / dof)
        cov = sigma2 * np.linalg.pinv(x_design.T @ x_design)
        se = np.sqrt(np.diag(cov))
        t_stats = np.divide(beta, se, out=np.full(beta.shape, np.nan), where=se > 0)

    sensitivities: list[FundMarketSensitivity] = []
    for idx, name in enumerate(joined.drop(columns=["fund"]).columns, start=1):
        t_stat = float(t_stats[idx]) if not math.isnan(float(t_stats[idx])) else None
        sensitivities.append(
            FundMarketSensitivity(
                factor=name,
                beta=float(beta[idx]),
                t_stat=t_stat,
                significance=_significance(t_stat),
            )
        )
    return sensitivities


async def _latest_factor_fit(datalake: AsyncSession) -> tuple[dt.date | None, pd.DataFrame]:
    try:
        row = (
            await datalake.execute(
                text(
                    """
                    SELECT fit_date, factor_returns
                    FROM factor_model_fits
                    WHERE engine = 'ipca'
                    ORDER BY fit_date DESC, created_at DESC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()
    except SQLAlchemyError as exc:
        raise _source_error("factor_model_fits", exc) from exc
    if row is None:
        return None, pd.DataFrame()
    payload = row["factor_returns"]
    if not isinstance(payload, Mapping):
        return row["fit_date"], pd.DataFrame()
    return row["fit_date"], _factor_frame(payload)


async def _style_bias(
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
) -> tuple[dt.date | None, list[FundStyleBias], EmptyState | None]:
    select_cols = ", ".join(
        f"target.{column} AS target_{column}, stats.avg_{column}, stats.std_{column}"
        for _label, column in _STYLE_FACTORS
    )
    avg_cols = ", ".join(
        f"AVG({column}) AS avg_{column}, STDDEV_SAMP({column}) AS std_{column}"
        for _label, column in _STYLE_FACTORS
    )
    try:
        row = (
            await datalake.execute(
                text(
                    f"""
                    WITH latest AS (
                        SELECT max(as_of) AS as_of
                        FROM equity_characteristics_monthly
                        WHERE instrument_id = :iid
                    ),
                    stats AS (
                        SELECT as_of, {avg_cols}
                        FROM equity_characteristics_monthly
                        WHERE as_of = (SELECT as_of FROM latest)
                        GROUP BY as_of
                    )
                    SELECT target.as_of, {select_cols}
                    FROM equity_characteristics_monthly target
                    JOIN stats ON stats.as_of = target.as_of
                    WHERE target.instrument_id = :iid
                    LIMIT 1
                    """
                ),
                {"iid": str(instrument_id)},
            )
        ).mappings().first()
    except SQLAlchemyError as exc:
        raise _source_error("equity_characteristics_monthly", exc) from exc
    if row is None:
        return (
            None,
            [],
            _empty(
                "No equity_characteristics_monthly row for this fund.",
                "equity_characteristics_monthly",
            ),
        )
    biases: list[FundStyleBias] = []
    for label, column in _STYLE_FACTORS:
        value = _float(row[f"target_{column}"])
        avg = _float(row[f"avg_{column}"])
        std = _float(row[f"std_{column}"])
        z_score = (value - avg) / std if value is not None and avg is not None and std else None
        biases.append(
            FundStyleBias(
                factor=label,
                value=value,
                z_score=z_score,
                as_of=row["as_of"],
            )
        )
    return row["as_of"], biases, None


async def _style_bias_db_first(
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
) -> tuple[dt.date | None, list[FundStyleBias], EmptyState | None]:
    """Style-bias z-scores lidos de fund_style_bias_v (latest as_of do fundo).

    Mesmo shape de _style_bias; o cálculo z = (value−avg)/stddev já vive na view.
    """
    try:
        rows = (
            await datalake.execute(
                text(
                    """
                    WITH latest AS (
                        SELECT max(as_of) AS as_of
                        FROM fund_style_bias_v
                        WHERE instrument_id = :iid
                    )
                    SELECT as_of, factor, value, z_score
                    FROM fund_style_bias_v
                    WHERE instrument_id = :iid
                      AND as_of = (SELECT as_of FROM latest)
                    """
                ),
                {"iid": str(instrument_id)},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise _source_error("fund_style_bias_v", exc) from exc
    if not rows:
        return (
            None,
            [],
            _empty(
                "No equity_characteristics_monthly row for this fund.",
                "fund_style_bias_v",
            ),
        )
    as_of = rows[0]["as_of"]
    biases = [
        FundStyleBias(
            factor=row["factor"],
            value=_float(row["value"]),
            z_score=_float(row["z_score"]),
            as_of=row["as_of"],
        )
        for row in rows
    ]
    return as_of, biases, None


async def fetch_fund_factors(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    use_db_first: bool | None = None,
) -> FundFactorsResponse | None:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first

    if use_db_first:
        rows = (
            await datalake.execute(
                text(
                    """
                    SELECT factor, beta, t_stat, significance, as_of
                    FROM fund_factor_exposures_latest_mv
                    WHERE instrument_id = :iid
                    ORDER BY factor
                    """
                ),
                {"iid": str(instrument_id)},
            )
        ).mappings().all()
        sensitivities = [
            FundMarketSensitivity(
                factor=r["factor"], beta=_float(r["beta"]),
                t_stat=_float(r["t_stat"]), significance=r["significance"],
            )
            for r in rows
        ]
        factor_as_of = rows[0]["as_of"] if rows else None
        style_as_of, style_bias, style_empty = await _style_bias_db_first(datalake, instrument_id)
    else:
        first_date, last_date = await select_nav_date_bounds(session, instrument_id)
        nav = pd.Series(dtype=float)
        if first_date is not None and last_date is not None:
            nav = build_nav_series(await select_nav_rows(session, instrument_id, first_date, last_date))
        monthly_returns = (
            nav.resample("ME").last().pct_change().dropna() if len(nav) else pd.Series(dtype=float)
        )
        factor_as_of, factors = await _latest_factor_fit(datalake)
        sensitivities = _ols_market_sensitivities(monthly_returns, factors)
        style_as_of, style_bias, style_empty = await _style_bias(datalake, instrument_id)

    metadata = [
        FundSourceMetadata(
            source="factor_model_fits",
            as_of=factor_as_of,
            empty_state=(
                _empty("No usable factor_model_fits payload for OLS.", "factor_model_fits")
                if not sensitivities
                else None
            ),
        ),
        FundSourceMetadata(
            source="equity_characteristics_monthly",
            as_of=style_as_of,
            empty_state=style_empty,
        ),
    ]
    return FundFactorsResponse(
        instrument_id=instrument_id,
        market_sensitivities=sensitivities,
        style_bias=style_bias,
        source_metadata=metadata,
    )


async def fetch_fund_style_drift(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    quarters: int,
    use_db_first: bool | None = None,
) -> FundStyleDriftResponse | None:
    """Historical N-PORT sector drift. DB-first lê de fund_style_drift_mv
    (mesma agregação, weight em percent-points → /100 aqui); fallback ao legado.
    """
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first
    if not use_db_first:
        return await _fetch_fund_style_drift_legacy(
            session, datalake, instrument_id, quarters=quarters
        )

    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    try:
        rows = (
            await datalake.execute(
                text(
                    """
                    WITH q AS (
                        SELECT DISTINCT report_date
                        FROM fund_style_drift_mv
                        WHERE series_id = :series_id
                        ORDER BY report_date DESC
                        LIMIT :quarters
                    )
                    SELECT m.report_date, m.sector, m.weight
                    FROM fund_style_drift_mv m
                    JOIN q ON q.report_date = m.report_date
                    WHERE m.series_id = :series_id
                    ORDER BY m.report_date ASC, m.weight DESC NULLS LAST
                    """
                ),
                {"series_id": fund.series_id, "quarters": quarters},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise _source_error("fund_style_drift_mv", exc) from exc

    periods: list[FundStyleDriftPeriod] = []
    current_date: dt.date | None = None
    current_weights: list[FundStyleSectorWeight] = []
    for row in rows:
        report_date = row["report_date"]
        if report_date != current_date:
            if current_date is not None:
                periods.append(
                    FundStyleDriftPeriod(
                        report_date=current_date,
                        quarter=f"{current_date.year}Q{((current_date.month - 1) // 3) + 1}",
                        sectors=current_weights,
                    )
                )
            current_date = report_date
            current_weights = []
        current_weights.append(
            FundStyleSectorWeight(
                sector=row["sector"],
                weight=(
                    (_float(row["weight"]) or 0.0) / 100.0
                    if row["weight"] is not None
                    else None
                ),
            )
        )
    if current_date is not None:
        periods.append(
            FundStyleDriftPeriod(
                report_date=current_date,
                quarter=f"{current_date.year}Q{((current_date.month - 1) // 3) + 1}",
                sectors=current_weights,
            )
        )

    return FundStyleDriftResponse(
        instrument_id=instrument_id,
        series_id=fund.series_id,
        periods=periods,
        empty_state=(
            None
            if periods
            else _empty("No historical N-PORT holdings for this fund series.", "fund_style_drift_mv")
        ),
    )


async def _fetch_fund_style_drift_legacy(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    quarters: int,
) -> FundStyleDriftResponse | None:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    try:
        rows = (
            await datalake.execute(
                text(
                    """
                    WITH q AS (
                        SELECT DISTINCT report_date
                        FROM sec_nport_holdings
                        WHERE series_id = :series_id
                        ORDER BY report_date DESC
                        LIMIT :quarters
                    ),
                    resolved AS (
                        SELECT h.report_date,
                               COALESCE(
                                   -- equities: real GICS sector by CUSIP
                                   NULLIF(btrim(m.gics_sector), ''),
                                   -- fixed income / other: friendly N-PORT issuer label
                                   CASE upper(btrim(h.sector))
                                       WHEN 'CORP' THEN 'Corporate'
                                       WHEN 'UST'  THEN 'U.S. Treasury'
                                       WHEN 'GOVT' THEN 'Government'
                                       WHEN 'USGA' THEN 'U.S. Gov Agency'
                                       WHEN 'MUNI' THEN 'Municipal'
                                       WHEN 'MUN'  THEN 'Municipal'
                                       WHEN 'MBS'  THEN 'Mortgage-Backed'
                                       WHEN 'ABS'  THEN 'Asset-Backed'
                                       WHEN 'CMO'  THEN 'Collateralized Mortgage'
                                       WHEN 'SUPRA' THEN 'Supranational'
                                       WHEN 'NUSS' THEN 'Non-U.S. Sovereign'
                                       WHEN 'RF'   THEN 'Registered Fund'
                                       ELSE NULLIF(btrim(h.sector), '')
                                   END,
                                   'Unknown'
                               ) AS sector,
                               h.pct_of_nav
                        FROM sec_nport_holdings h
                        JOIN q ON q.report_date = h.report_date
                        LEFT JOIN LATERAL (
                            SELECT gics_sector
                            FROM sec_cusip_ticker_map
                            WHERE cusip = h.cusip
                              AND NULLIF(btrim(gics_sector), '') IS NOT NULL
                            LIMIT 1
                        ) m ON TRUE
                        WHERE h.series_id = :series_id
                    )
                    SELECT report_date, sector, SUM(pct_of_nav) AS weight
                    FROM resolved
                    GROUP BY report_date, sector
                    ORDER BY report_date ASC, weight DESC NULLS LAST
                    """
                ),
                {"series_id": fund.series_id, "quarters": quarters},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise _source_error("sec_nport_holdings", exc) from exc

    periods: list[FundStyleDriftPeriod] = []
    current_date: dt.date | None = None
    current_weights: list[FundStyleSectorWeight] = []
    for row in rows:
        report_date = row["report_date"]
        if report_date != current_date:
            if current_date is not None:
                periods.append(
                    FundStyleDriftPeriod(
                        report_date=current_date,
                        quarter=f"{current_date.year}Q{((current_date.month - 1) // 3) + 1}",
                        sectors=current_weights,
                    )
                )
            current_date = report_date
            current_weights = []
        current_weights.append(
            FundStyleSectorWeight(
                sector=row["sector"],
                weight=(
                    (_float(row["weight"]) or 0.0) / 100.0
                    if row["weight"] is not None
                    else None
                ),
            )
        )
    if current_date is not None:
        periods.append(
            FundStyleDriftPeriod(
                report_date=current_date,
                quarter=f"{current_date.year}Q{((current_date.month - 1) // 3) + 1}",
                sectors=current_weights,
            )
        )

    return FundStyleDriftResponse(
        instrument_id=instrument_id,
        series_id=fund.series_id,
        periods=periods,
        empty_state=(
            None
            if periods
            else _empty("No historical N-PORT holdings for this fund series.", "sec_nport_holdings")
        ),
    )


def _window_nav(nav: pd.Series, window: WindowKey) -> pd.Series:
    days = WINDOW_DAYS[window]
    if len(nav) <= days:
        return nav
    return nav.iloc[-days:]


def _annualized_return(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    compounded = float(cast(float, (1.0 + returns).prod()))
    return float(compounded ** (_TRADING_DAYS / len(returns)) - 1.0)


def _annualized_vol(returns: pd.Series) -> float | None:
    if len(returns) < 2:
        return None
    return float(returns.std(ddof=1)) * math.sqrt(_TRADING_DAYS)


def _sortino(returns: pd.Series) -> float | None:
    if len(returns) < 2:
        return None
    downside = returns[returns < 0]
    if downside.empty:
        return None
    downside_dev = float(np.sqrt(np.mean(np.square(downside.to_numpy(dtype=float))))) * math.sqrt(
        _TRADING_DAYS
    )
    ann = _annualized_return(returns)
    return (ann - _RF) / downside_dev if ann is not None and downside_dev else None


def _max_drawdown_series(nav: pd.Series) -> pd.Series:
    return nav / nav.cummax() - 1.0


def _drawdown_periods(nav: pd.Series) -> list[FundDrawdownPeriod]:
    drawdowns = _max_drawdown_series(nav)
    periods: list[FundDrawdownPeriod] = []
    in_period = False
    start: pd.Timestamp | None = None
    trough: pd.Timestamp | None = None
    trough_depth = 0.0
    for raw_idx, depth in drawdowns.items():
        idx = cast(pd.Timestamp, raw_idx)
        value = float(depth)
        if value < 0 and not in_period:
            in_period = True
            start = idx
            trough = idx
            trough_depth = value
        elif value < 0 and in_period:
            if value < trough_depth:
                trough = idx
                trough_depth = value
        elif value >= 0 and in_period and start is not None and trough is not None:
            periods.append(
                FundDrawdownPeriod(
                    start_date=start.date(),
                    trough_date=trough.date(),
                    end_date=idx.date(),
                    depth=trough_depth,
                    duration_days=(trough.date() - start.date()).days,
                    recovery_days=(idx.date() - trough.date()).days,
                )
            )
            in_period = False
    if in_period and start is not None and trough is not None:
        last = drawdowns.index[-1]
        periods.append(
            FundDrawdownPeriod(
                start_date=start.date(),
                trough_date=trough.date(),
                end_date=None,
                depth=trough_depth,
                duration_days=(last.date() - start.date()).days,
                recovery_days=None,
            )
        )
    return sorted(periods, key=lambda p: p.depth)[:5]


def _risk_statistics(
    returns: pd.Series,
    drawdown: pd.Series,
    benchmark_returns: pd.Series | None,
) -> FundRiskStatistics:
    ann_return = _annualized_return(returns)
    ann_vol = _annualized_vol(returns)
    max_dd = float(drawdown.min()) if len(drawdown) else None
    sharpe = (ann_return - _RF) / ann_vol if ann_return is not None and ann_vol else None
    calmar = ann_return / abs(max_dd) if ann_return is not None and max_dd else None
    alpha = beta = tracking_error = information_ratio = None
    if benchmark_returns is not None:
        joined = pd.concat(
            [returns.rename("fund"), benchmark_returns.rename("bench")],
            axis=1,
        ).dropna()
        if len(joined) >= 10 and float(joined["bench"].var(ddof=1)) > 0:
            cov = float(np.cov(joined["fund"], joined["bench"], ddof=1)[0, 1])
            beta = cov / float(joined["bench"].var(ddof=1))
            alpha = (_annualized_return(joined["fund"]) or 0.0) - beta * (
                _annualized_return(joined["bench"]) or 0.0
            )
            excess = joined["fund"] - joined["bench"]
            tracking_error = _annualized_vol(excess)
            excess_ann = _annualized_return(excess)
            information_ratio = (
                excess_ann / tracking_error if excess_ann is not None and tracking_error else None
            )
    return FundRiskStatistics(
        annualized_return=ann_return,
        annualized_volatility=ann_vol,
        sharpe_ratio=sharpe,
        sortino_ratio=_sortino(returns),
        calmar_ratio=calmar,
        max_drawdown=max_dd,
        alpha=alpha,
        beta=beta,
        tracking_error=tracking_error,
        information_ratio=information_ratio,
        n_observations=len(returns),
    )


def _monthly_returns(returns: pd.Series) -> pd.Series:
    if returns.empty:
        return pd.Series(dtype=float)
    return returns.add(1.0).resample("ME").prod().sub(1.0).dropna()


def _capture(
    returns: pd.Series,
    benchmark_returns: pd.Series | None,
    benchmark_id: uuid.UUID | None,
    benchmark_label: str | None,
) -> FundCaptureRatios:
    if benchmark_returns is None:
        return FundCaptureRatios(
            benchmark_id=benchmark_id,
            benchmark_label=benchmark_label,
            empty_state=_empty(
                "No benchmark_id supplied or benchmark returns unavailable.",
                "nav_timeseries",
            ),
        )
    joined = pd.concat(
        [returns.rename("fund"), benchmark_returns.rename("bench")],
        axis=1,
    ).dropna()
    monthly = pd.concat(
        [
            _monthly_returns(joined["fund"]).rename("fund"),
            _monthly_returns(joined["bench"]).rename("bench"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if len(monthly) < 3:
        return FundCaptureRatios(
            benchmark_id=benchmark_id,
            benchmark_label=benchmark_label,
            empty_state=_empty("Fewer than 3 aligned benchmark months.", "nav_timeseries"),
        )
    up = monthly[monthly["bench"] > 0]
    down = monthly[monthly["bench"] < 0]
    up_capture = (
        float(up["fund"].mean() / up["bench"].mean() * 100.0)
        if len(up) and abs(float(up["bench"].mean())) > 1e-12
        else None
    )
    down_capture = (
        float(down["fund"].mean() / down["bench"].mean() * 100.0)
        if len(down) and abs(float(down["bench"].mean())) > 1e-12
        else None
    )
    return FundCaptureRatios(
        up_capture=up_capture,
        down_capture=down_capture,
        up_periods=len(up),
        down_periods=len(down),
        benchmark_id=benchmark_id,
        benchmark_label=benchmark_label,
    )


def _rolling_returns(returns: pd.Series) -> FundRollingReturns:
    windows: dict[Literal["1M", "3M", "6M", "1Y"], int] = {
        "1M": 21,
        "3M": 63,
        "6M": 126,
        "1Y": 252,
    }
    out: dict[Literal["1M", "3M", "6M", "1Y"], list[SeriesPoint]] = {
        "1M": [],
        "3M": [],
        "6M": [],
        "1Y": [],
    }
    compounded = returns.add(1.0)
    for label, window in windows.items():
        if len(returns) >= window:
            out[label] = _series_points(
                compounded.rolling(window).apply(np.prod, raw=True).sub(1.0)
            )
    return FundRollingReturns(series=out)


def _distribution(returns: pd.Series) -> FundReturnDistribution:
    values = returns.dropna().to_numpy(dtype=float)
    if len(values) < 10:
        return FundReturnDistribution(bin_edges=[], bin_counts=[])
    counts, edges = np.histogram(values, bins="fd")
    q05 = float(np.quantile(values, 0.05))
    tail = values[values <= q05]
    return FundReturnDistribution(
        bin_edges=[float(v) for v in edges],
        bin_counts=[int(v) for v in counts],
        skewness=float(cast(float, pd.Series(values).skew())),
        kurtosis=float(cast(float, pd.Series(values).kurt())),
        var_95=-q05,
        cvar_95=-float(tail.mean()) if len(tail) else None,
    )


def _return_statistics(returns: pd.Series) -> FundReturnStatistics:
    monthly = _monthly_returns(returns)
    if monthly.empty:
        return FundReturnStatistics()
    gains = monthly[monthly > 0]
    losses = monthly[monthly < 0]
    arithmetic = float(monthly.mean())
    geometric = float(
        cast(float, (1.0 + monthly).prod()) ** (1.0 / len(monthly)) - 1.0
    )
    avg_gain = float(gains.mean()) if len(gains) else None
    avg_loss = float(losses.mean()) if len(losses) else None
    downside = returns[returns < 0]
    upside_sum = float(returns[returns > 0].sum())
    downside_sum = abs(float(downside.sum()))
    return FundReturnStatistics(
        arithmetic_mean_monthly=arithmetic,
        geometric_mean_monthly=geometric,
        avg_monthly_gain=avg_gain,
        avg_monthly_loss=avg_loss,
        gain_loss_ratio=(avg_gain / abs(avg_loss) if avg_gain is not None and avg_loss else None),
        downside_deviation=(
            float(np.sqrt(np.mean(np.square(downside.to_numpy(dtype=float)))))
            if len(downside)
            else None
        ),
        semi_deviation=(
            float(np.sqrt(np.mean(np.square((returns - returns.mean()).clip(upper=0)))))
            if len(returns)
            else None
        ),
        omega_ratio=(upside_sum / downside_sum if downside_sum else None),
        up_percentage_ratio=float(len(gains) / len(monthly) * 100.0),
        down_percentage_ratio=float(len(losses) / len(monthly) * 100.0),
    )


def _normal_var(returns: pd.Series, confidence: float) -> float | None:
    if len(returns) < 10:
        return None
    z_map = {0.90: 1.2815515655446004, 0.95: 1.6448536269514722, 0.99: 2.3263478740408408}
    z = z_map[confidence]
    mean = float(returns.mean())
    std = float(returns.std(ddof=1))
    return z * std - mean


def _modified_var(returns: pd.Series, confidence: float) -> float | None:
    if len(returns) < 30:
        return None
    z_map = {0.95: 1.6448536269514722, 0.99: 2.3263478740408408}
    z = z_map[confidence]
    skew = float(cast(float, returns.skew()))
    kurt = float(cast(float, returns.kurt()))
    z_cf = (
        z
        + ((z**2 - 1.0) * skew / 6.0)
        + ((z**3 - 3.0 * z) * kurt / 24.0)
        - ((2.0 * z**3 - 5.0 * z) * (skew**2) / 36.0)
    )
    return z_cf * float(returns.std(ddof=1)) - float(returns.mean())


def _tail_risk(returns: pd.Series) -> FundTailRiskMetrics:
    clean = returns.dropna()
    if len(clean) < 10:
        return FundTailRiskMetrics()
    values = clean.to_numpy(dtype=float)
    q05 = float(np.quantile(values, 0.05))
    q95 = float(np.quantile(values, 0.95))
    loss_tail = values[values <= q05]
    gain_tail = values[values >= q95]
    etl_95 = -float(loss_tail.mean()) if len(loss_tail) else None
    etr_95 = float(gain_tail.mean()) if len(gain_tail) else None
    ann_return = _annualized_return(clean)
    starr = (
        (ann_return - _RF) / (etl_95 * math.sqrt(_TRADING_DAYS))
        if ann_return is not None and etl_95
        else None
    )
    rachev = (etr_95 / etl_95) if etr_95 is not None and etl_95 else None
    skew = float(cast(float, clean.skew()))
    kurt = float(cast(float, clean.kurt()))
    jb = len(clean) / 6.0 * (skew**2 + (kurt**2) / 4.0)
    return FundTailRiskMetrics(
        var_parametric_90=_normal_var(clean, 0.90),
        var_parametric_95=_normal_var(clean, 0.95),
        var_parametric_99=_normal_var(clean, 0.99),
        var_modified_95=_modified_var(clean, 0.95),
        var_modified_99=_modified_var(clean, 0.99),
        etl_95=etl_95,
        starr=starr,
        rachev=rachev,
        jarque_bera=jb,
        jarque_bera_pvalue=math.exp(-jb / 2.0),
    )


def _insider_empty(reason: str, source: str | None = "sec_insider_transactions") -> InsiderData:
    return InsiderData(empty_state=_empty(reason, source))


# The deployed insider data is the raw Form 345 feed `sec_insider_transactions`
# (issuer_cik / trans_date / trans_code / trans_value); there is NO pre-aggregated
# `sec_insider_sentiment` table. Aggregate buy/sell sentiment on the fly from the
# open-market transaction codes (P = purchase, S = sale) per calendar quarter.
_INSIDER_SENTIMENT_SQL = """
                    WITH issuer_map AS (
                        SELECT DISTINCT
                            upper(m.cusip) AS cusip,
                            m.issuer_cik::text AS cik
                        FROM sec_cusip_ticker_map m
                        WHERE upper(m.cusip) = ANY(:cusips)
                          AND m.issuer_cik IS NOT NULL
                    ),
                    matched_ciks AS (
                        SELECT DISTINCT cik FROM issuer_map
                    ),
                    tx AS (
                        SELECT
                            date_trunc('quarter', t.trans_date)::date AS quarter,
                            t.issuer_cik::text AS cik,
                            t.trans_code,
                            t.trans_value
                        FROM sec_insider_transactions t
                        WHERE t.issuer_cik::text IN (SELECT cik FROM matched_ciks)
                          AND t.trans_code IN ('P', 'S')
                          AND t.trans_value IS NOT NULL
                    ),
                    quarterly AS (
                        SELECT
                            quarter,
                            SUM(
                                CASE WHEN trans_code = 'P' THEN trans_value ELSE 0 END
                            ) AS buy_value,
                            SUM(
                                CASE WHEN trans_code = 'S' THEN trans_value ELSE 0 END
                            ) AS sell_value,
                            COUNT(*) FILTER (WHERE trans_code = 'P') AS buy_count,
                            COUNT(*) FILTER (WHERE trans_code = 'S') AS sell_count,
                            array_agg(DISTINCT cik) AS issuer_ciks
                        FROM tx
                        GROUP BY quarter
                    )
                    SELECT
                        q.quarter,
                        q.buy_value,
                        q.sell_value,
                        q.buy_value - q.sell_value AS net_value,
                        q.buy_count,
                        q.sell_count,
                        q.issuer_ciks,
                        (
                            SELECT array_agg(DISTINCT im.cusip)
                            FROM issuer_map im
                            WHERE im.cik = ANY(q.issuer_ciks)
                        ) AS matched_cusips
                    FROM quarterly q
                    ORDER BY q.quarter DESC
                    LIMIT 8
                    """


async def fetch_fund_insider_data(
    session: AsyncSession,
    datalake: AsyncSession,
    fund: Fund,
) -> InsiderData:
    """Map fund holdings CUSIPs to issuer CIKs and aggregate Form 4 sentiment."""
    _, holdings = await _latest_fund_holdings(session, fund.series_id)
    cusips = _holding_cusips(holdings)
    if not cusips:
        return _insider_empty(
            "No CUSIP-bearing holdings are available for insider mapping.",
            "fund_holdings",
        )
    try:
        rows = (
            await datalake.execute(
                text(_INSIDER_SENTIMENT_SQL),
                {"cusips": cusips},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        if _is_missing_relation(exc):
            return _insider_empty("SEC insider transactions table is not deployed yet.")
        raise _source_error("sec_insider_transactions", exc) from exc

    if not rows:
        return _insider_empty("No Form 4 insider sentiment matched this fund's holdings.")

    quarters = [
        InsiderQuarterSentiment(
            quarter=row["quarter"],
            buy_value=_float(row["buy_value"]) or 0.0,
            sell_value=_float(row["sell_value"]) or 0.0,
            net_value=_float(row["net_value"]) or 0.0,
            buy_count=int(row["buy_count"] or 0),
            sell_count=int(row["sell_count"] or 0),
        )
        for row in rows
    ]
    total_buy = sum(item.buy_value for item in quarters)
    total_sell = sum(item.sell_value for item in quarters)
    issuer_ciks = sorted({cik for row in rows for cik in (row["issuer_ciks"] or [])})
    matched_cusips = sorted({cusip for row in rows for cusip in (row["matched_cusips"] or [])})
    return InsiderData(
        issuer_ciks=issuer_ciks,
        matched_cusips=matched_cusips,
        quarters=quarters,
        total_buy_value=total_buy,
        total_sell_value=total_sell,
        net_value=total_buy - total_sell,
        sentiment_score=_sentiment_score(total_buy, total_sell),
        as_of=max(item.quarter for item in quarters),
    )


def assemble_entity_analytics(
    nav: pd.Series,
    *,
    fund: Fund,
    window: WindowKey,
    benchmark_nav: pd.Series | None = None,
    benchmark_id: uuid.UUID | None = None,
    benchmark_label: str | None = None,
    insider_data: InsiderData | None = None,
) -> FundEntityAnalyticsResponse:
    visible_nav = _window_nav(nav.dropna(), window)
    if len(visible_nav) < 10:
        raise InsufficientFundDataError(
            f"Only {len(visible_nav)} NAV rows available for fund {fund.instrument_id}."
        )
    returns = simple_returns(visible_nav)
    benchmark_returns = (
        simple_returns(_window_nav(benchmark_nav.dropna(), window))
        if benchmark_nav is not None and len(benchmark_nav) >= 2
        else None
    )
    drawdown_series = _max_drawdown_series(visible_nav)
    return FundEntityAnalyticsResponse(
        instrument_id=fund.instrument_id,
        name=fund.name,
        as_of_date=visible_nav.index[-1].date(),
        window=window,
        risk_statistics=_risk_statistics(returns, drawdown_series, benchmark_returns),
        drawdown=FundDrawdownAnalysis(
            dates=[idx.date() for idx in drawdown_series.index],
            values=[float(value) for value in drawdown_series],
            max_drawdown=float(drawdown_series.min()),
            current_drawdown=float(drawdown_series.iloc[-1]),
            worst_periods=_drawdown_periods(visible_nav),
        ),
        capture=_capture(returns, benchmark_returns, benchmark_id, benchmark_label),
        rolling_returns=_rolling_returns(returns),
        distribution=_distribution(returns),
        return_statistics=_return_statistics(returns),
        tail_risk=_tail_risk(returns),
        insider_data=insider_data,
    )


async def assemble_entity_analytics_sql(
    session: AsyncSession,
    nav: pd.Series,
    *,
    fund: Fund,
    window: WindowKey,
    benchmark_nav: pd.Series | None = None,
    benchmark_id: uuid.UUID | None = None,
    benchmark_label: str | None = None,
    insider_data: InsiderData | None = None,
) -> FundEntityAnalyticsResponse:
    """Series-only DB-first: drawdown SERIES (fn_drawdown) and distribution
    var/cvar (fn_var_cvar) come from SQL; rolling_returns, FD histogram edges/
    counts, skew/kurt and ALL scalars stay in Python (not in the §8 set).

    The drawdown-PERIOD episode detection (_drawdown_periods) and the scalar
    min/current drawdown stay pandas (episode extraction, not a series). The
    distribution FD bins + skew/kurt also stay pandas; only var_95/cvar_95 are
    replaced by the SQL fn_var_cvar over the exact visible window.
    """
    visible_nav = _window_nav(nav.dropna(), window)
    if len(visible_nav) < 10:
        raise InsufficientFundDataError(
            f"Only {len(visible_nav)} NAV rows available for fund {fund.instrument_id}."
        )
    returns = simple_returns(visible_nav)
    benchmark_returns = (
        simple_returns(_window_nav(benchmark_nav.dropna(), window))
        if benchmark_nav is not None and len(benchmark_nav) >= 2
        else None
    )
    w_start = visible_nav.index[0].date()
    w_end = visible_nav.index[-1].date()

    dd_pts = await series_sql.drawdown_points(
        session, instrument_id=fund.instrument_id, start=w_start, end=w_end
    )
    # legacy still needed for scalar min/current + drawdown-period episodes;
    # reuse the SQL points for the emitted dates/values (parity-checked).
    drawdown_series = _max_drawdown_series(visible_nav)  # for min/current/episodes

    # Distribution: keep FD bins + skew/kurt in Python; replace var/cvar with SQL.
    # When the legacy distribution early-returns empty (fewer than 10 in-window
    # returns), keep it empty for parity rather than injecting SQL var/cvar.
    base_dist = _distribution(returns)
    if base_dist.bin_edges:
        var_95, cvar_95 = await series_sql.var_cvar(
            session, instrument_id=fund.instrument_id, level=0.95, start=w_start, end=w_end
        )
        distribution = base_dist.model_copy(update={"var_95": var_95, "cvar_95": cvar_95})
    else:
        distribution = base_dist

    return FundEntityAnalyticsResponse(
        instrument_id=fund.instrument_id,
        name=fund.name,
        as_of_date=w_end,
        window=window,
        risk_statistics=_risk_statistics(returns, drawdown_series, benchmark_returns),
        drawdown=FundDrawdownAnalysis(
            dates=[d for d, _ in dd_pts],
            values=[v for _, v in dd_pts],
            max_drawdown=float(drawdown_series.min()),
            current_drawdown=float(drawdown_series.iloc[-1]),
            worst_periods=_drawdown_periods(visible_nav),
        ),
        capture=_capture(returns, benchmark_returns, benchmark_id, benchmark_label),
        rolling_returns=_rolling_returns(returns),
        distribution=distribution,
        return_statistics=_return_statistics(returns),
        tail_risk=_tail_risk(returns),
        insider_data=insider_data,
    )


async def _nav_for_window(
    session: AsyncSession,
    instrument_id: uuid.UUID,
    window: WindowKey,
) -> pd.Series:
    first_date, last_date = await select_nav_date_bounds(session, instrument_id)
    if first_date is None or last_date is None:
        raise InsufficientFundDataError(f"No NAV history for fund {instrument_id}.")
    start = last_date - dt.timedelta(days=int(WINDOW_DAYS[window] * 1.6) + lookback_pad_days(21))
    rows = await select_nav_rows(session, instrument_id, max(first_date, start), last_date)
    return build_nav_series(rows)


async def _instrument_ticker_label(
    session: AsyncSession,
    instrument_id: uuid.UUID,
) -> tuple[str | None, str | None] | None:
    result = await session.execute(
        text(
            """
            SELECT ticker, name
            FROM instruments_universe
            WHERE instrument_id = :instrument_id
            LIMIT 1
            """
        ),
        {"instrument_id": instrument_id},
    )
    row = result.first()
    if row is None:
        return None
    ticker, name = row
    return ticker, name


async def _eod_close_for_window(
    session: AsyncSession,
    ticker: str,
    window: WindowKey,
) -> pd.Series:
    bounds = await session.execute(
        text(
            """
            SELECT min(date) AS first_date, max(date) AS last_date
            FROM eod_prices
            WHERE ticker = :ticker
              AND adj_close IS NOT NULL
            """
        ),
        {"ticker": ticker},
    )
    first_date, last_date = bounds.one()
    if first_date is None or last_date is None:
        raise InsufficientFundDataError(f"No EOD history for benchmark {ticker}.")
    start = last_date - dt.timedelta(days=int(WINDOW_DAYS[window] * 1.6) + lookback_pad_days(21))
    rows = await session.execute(
        text(
            """
            SELECT date, adj_close
            FROM eod_prices
            WHERE ticker = :ticker
              AND date >= :start
              AND date <= :last_date
              AND adj_close IS NOT NULL
            ORDER BY date
            """
        ),
        {"ticker": ticker, "start": max(first_date, start), "last_date": last_date},
    )
    return build_nav_series((date, close) for date, close in rows.all())


async def _benchmark_nav_for_window(
    session: AsyncSession,
    benchmark_id: uuid.UUID,
    window: WindowKey,
) -> tuple[pd.Series, str | None]:
    benchmark = await _fund_or_none(session, benchmark_id)
    if benchmark is not None:
        return (
            await _nav_for_window(session, benchmark_id, window),
            benchmark.ticker or benchmark.name,
        )

    instrument = await _instrument_ticker_label(session, benchmark_id)
    if instrument is None:
        raise InvalidBenchmarkError(f"Benchmark instrument {benchmark_id} not found.")
    ticker, name = instrument
    if not ticker:
        raise InvalidBenchmarkError(f"Benchmark instrument {benchmark_id} has no ticker.")
    return await _eod_close_for_window(session, ticker.upper(), window), ticker or name


async def fetch_fund_entity_analytics(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    window: WindowKey,
    benchmark_id: uuid.UUID | None,
) -> FundEntityAnalyticsResponse | None:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    nav = await _nav_for_window(session, instrument_id, window)
    benchmark_nav = None
    benchmark_label = None
    if benchmark_id is not None:
        benchmark_nav, benchmark_label = await _benchmark_nav_for_window(
            session, benchmark_id, window
        )
    insider_data = await fetch_fund_insider_data(session, datalake, fund)
    if get_settings().use_series_db_first:
        return await assemble_entity_analytics_sql(
            session,
            nav,
            fund=fund,
            window=window,
            benchmark_nav=benchmark_nav,
            benchmark_id=benchmark_id,
            benchmark_label=benchmark_label,
            insider_data=insider_data,
        )
    return assemble_entity_analytics(
        nav,
        fund=fund,
        window=window,
        benchmark_nav=benchmark_nav,
        benchmark_id=benchmark_id,
        benchmark_label=benchmark_label,
        insider_data=insider_data,
    )


def _build_holder_network(
    fund: Fund,
    holders: list[InstitutionalHolder],
    overlap: list[InstitutionalOverlapSecurity],
    rows: Sequence[Mapping[str, Any]],
) -> HolderNetwork:
    nodes: list[HolderNetworkNode] = [
        HolderNetworkNode(
            id=f"fund:{fund.instrument_id}",
            label=fund.ticker or fund.name,
            type="fund",
        )
    ]
    edges: list[HolderNetworkEdge] = []
    top_holders = holders[:8]
    top_cusips = {item.cusip for item in overlap[:12]}
    for item in overlap[:12]:
        nodes.append(
            HolderNetworkNode(
                id=f"security:{item.cusip}",
                label=item.name or item.cusip,
                type="security",
                value=item.institutional_value_usd,
            )
        )
        edges.append(
            HolderNetworkEdge(
                source=f"fund:{fund.instrument_id}",
                target=f"security:{item.cusip}",
                weight=item.fund_pct_of_nav,
                label="fund holding",
            )
        )
    for holder in top_holders:
        nodes.append(
            HolderNetworkNode(
                id=f"institution:{holder.cik}",
                label=holder.manager_name,
                type="institution",
                value=holder.value_usd,
            )
        )
    top_holder_ciks = {holder.cik for holder in top_holders}
    for row in rows:
        if row["cik"] not in top_holder_ciks or row["cusip"] not in top_cusips:
            continue
        edges.append(
            HolderNetworkEdge(
                source=f"institution:{row['cik']}",
                target=f"security:{row['cusip']}",
                weight=_float(row["value_usd"]),
                label="13F value",
            )
        )
    return HolderNetwork(nodes=nodes, edges=edges)


def _institutional_payload(
    fund: Fund,
    holdings_report_date: dt.date | None,
    holdings: list[FundHolding],
    rows: Sequence[Mapping[str, Any]],
    *,
    empty_state: EmptyState | None = None,
) -> FundInstitutionalRevealResponse:
    if not rows:
        return FundInstitutionalRevealResponse(
            instrument_id=fund.instrument_id,
            series_id=fund.series_id,
            fund_name=fund.name,
            holdings_report_date=holdings_report_date,
            period=None,
            top_holders=[],
            overlap=[],
            holder_network=_empty_network(fund),
            empty_state=empty_state,
        )

    holder_map: dict[str, dict[str, Any]] = {}
    overlap_map: dict[str, dict[str, Any]] = {}
    holding_by_cusip = {
        cusip: holding
        for holding in holdings
        if (cusip := _normalize_cusip(holding.cusip))
    }
    for row in rows:
        holder = holder_map.setdefault(
            row["cik"],
            {
                "manager_name": row["manager_name"],
                "value_usd": 0.0,
                "shares": 0.0,
                "holding_count": 0,
                "period": row["period"],
                "report_date": row["report_date"],
            },
        )
        holder["value_usd"] += _float(row["value_usd"]) or 0.0
        holder["shares"] += _float(row["shares"]) or 0.0
        holder["holding_count"] += 1

        overlap_entry = overlap_map.setdefault(
            row["cusip"],
            {
                "name": row["name"],
                "value_usd": 0.0,
                "institutions": set(),
                "managers": [],
            },
        )
        overlap_entry["value_usd"] += _float(row["value_usd"]) or 0.0
        overlap_entry["institutions"].add(row["cik"])
        if row["manager_name"] not in overlap_entry["managers"]:
            overlap_entry["managers"].append(row["manager_name"])

    holders = sorted(
        [
            InstitutionalHolder(
                cik=cik,
                manager_name=data["manager_name"],
                value_usd=data["value_usd"],
                shares=data["shares"],
                holding_count=data["holding_count"],
                period=data["period"],
                report_date=data["report_date"],
            )
            for cik, data in holder_map.items()
        ],
        key=lambda item: item.value_usd or 0.0,
        reverse=True,
    )
    overlap = sorted(
        [
            InstitutionalOverlapSecurity(
                cusip=cusip,
                name=data["name"] or getattr(holding_by_cusip.get(cusip), "issuer_name", None),
                fund_pct_of_nav=_float(getattr(holding_by_cusip.get(cusip), "pct_of_nav", None)),
                institutional_value_usd=data["value_usd"],
                institution_count=len(data["institutions"]),
                top_managers=data["managers"][:5],
            )
            for cusip, data in overlap_map.items()
        ],
        key=lambda item: item.institutional_value_usd or 0.0,
        reverse=True,
    )
    period = max(row["period"] for row in rows if row["period"] is not None)
    return FundInstitutionalRevealResponse(
        instrument_id=fund.instrument_id,
        series_id=fund.series_id,
        fund_name=fund.name,
        holdings_report_date=holdings_report_date,
        period=period,
        top_holders=holders[:20],
        overlap=overlap[:50],
        holder_network=_build_holder_network(fund, holders, overlap, rows),
        empty_state=None,
    )


# --- SEC 13F Tier C queries -------------------------------------------------
# The deployed `sec_13f_holdings` (replicated from the monolith) stores
# cik / report_date / cusip / issuer_name / market_value / shares — it has NO
# manager_name / period / name / value_usd columns. Manager identity comes from
# `sec_managers.firm_name` (cik is not unique there, so pick the highest-AUM row
# via LATERAL). Output aliases keep the payload-builder row keys stable.
_INSTITUTIONAL_REVEAL_SQL = """
                    WITH matched AS (
                        SELECT
                            h.cik,
                            COALESCE(mgr.firm_name, 'CIK ' || h.cik) AS manager_name,
                            h.report_date AS period,
                            h.report_date,
                            upper(h.cusip) AS cusip,
                            h.issuer_name AS name,
                            h.market_value AS value_usd,
                            h.shares
                        FROM sec_13f_holdings h
                        LEFT JOIN LATERAL (
                            SELECT m.firm_name
                            FROM sec_managers m
                            WHERE m.cik = h.cik AND m.firm_name IS NOT NULL
                            ORDER BY m.aum_total DESC NULLS LAST
                            LIMIT 1
                        ) mgr ON true
                        WHERE upper(h.cusip) = ANY(:cusips)
                    ),
                    latest AS (
                        SELECT max(period) AS period FROM matched
                    )
                    SELECT matched.*
                    FROM matched
                    JOIN latest ON latest.period = matched.period
                    ORDER BY value_usd DESC NULLS LAST
                    LIMIT :limit
                    """

_REVERSE_LOOKUP_SQL = """
                    WITH latest AS (
                        SELECT max(report_date) AS period
                        FROM sec_13f_holdings
                        WHERE upper(cusip) = :cusip
                    )
                    SELECT
                        h.cik,
                        COALESCE(mgr.firm_name, 'CIK ' || h.cik) AS manager_name,
                        h.report_date AS period,
                        h.report_date,
                        upper(h.cusip) AS cusip,
                        h.issuer_name AS name,
                        h.market_value AS value_usd,
                        h.shares
                    FROM sec_13f_holdings h
                    LEFT JOIN LATERAL (
                        SELECT m.firm_name
                        FROM sec_managers m
                        WHERE m.cik = h.cik AND m.firm_name IS NOT NULL
                        ORDER BY m.aum_total DESC NULLS LAST
                        LIMIT 1
                    ) mgr ON true
                    WHERE upper(h.cusip) = :cusip
                      AND h.report_date = (SELECT period FROM latest)
                    ORDER BY value_usd DESC NULLS LAST
                    LIMIT 100
                    """


def _date_or_none(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value[:10]) if value else None


async def fetch_fund_institutional_reveal(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    use_db_first: bool | None = None,
) -> FundInstitutionalRevealResponse | None:
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first
    if not use_db_first:
        return await _fetch_fund_institutional_reveal_legacy(
            session, datalake, instrument_id
        )

    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    row = (
        await datalake.execute(
            text(
                """
                SELECT as_of, payload
                FROM fund_institutional_reveal_latest_mv
                WHERE series_id = :series_id
                """
            ),
            {"series_id": fund.series_id},
        )
    ).mappings().first()
    if row is None:
        return FundInstitutionalRevealResponse(
            instrument_id=fund.instrument_id,
            series_id=fund.series_id,
            fund_name=fund.name,
            holdings_report_date=None,
            period=None,
            top_holders=[],
            overlap=[],
            holder_network=_empty_network(fund),
            empty_state=_empty(
                "No institutional-reveal artifact for this fund series.",
                "fund_institutional_reveal_latest_mv",
            ),
        )
    payload = row["payload"]
    network = payload["holder_network"]
    return FundInstitutionalRevealResponse(
        instrument_id=fund.instrument_id,
        series_id=fund.series_id,
        fund_name=fund.name,
        holdings_report_date=row["as_of"],
        period=_date_or_none(payload.get("period")),
        top_holders=[InstitutionalHolder(**h) for h in payload["top_holders"]],
        overlap=[InstitutionalOverlapSecurity(**o) for o in payload["overlap"]],
        holder_network=HolderNetwork(
            nodes=[HolderNetworkNode(**n) for n in network["nodes"]],
            edges=[HolderNetworkEdge(**e) for e in network["edges"]],
        ),
        empty_state=None,
    )


async def _fetch_fund_institutional_reveal_legacy(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
) -> FundInstitutionalRevealResponse | None:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    holdings_report_date, holdings = await _latest_fund_holdings(session, fund.series_id)
    cusips = _holding_cusips(holdings)
    if not cusips:
        return _institutional_payload(
            fund,
            holdings_report_date,
            holdings,
            [],
            empty_state=_empty(
                "No CUSIP-bearing holdings are available for 13F matching.",
                "fund_holdings",
            ),
        )
    try:
        rows = (
            await datalake.execute(
                text(_INSTITUTIONAL_REVEAL_SQL),
                {"cusips": cusips, "limit": _TIER_C_13F_ROW_LIMIT},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        if _is_missing_relation(exc):
            return _institutional_payload(
                fund,
                holdings_report_date,
                holdings,
                [],
                empty_state=_empty(
                    "SEC 13F holdings tables are not deployed yet.",
                    "sec_13f_holdings",
                ),
            )
        raise _source_error("sec_13f_holdings", exc) from exc
    if not rows:
        return _institutional_payload(
            fund,
            holdings_report_date,
            holdings,
            [],
            empty_state=_empty(
                "No 13F institutional holdings matched this fund's CUSIPs.",
                "sec_13f_holdings",
            ),
        )
    return _institutional_payload(
        fund,
        holdings_report_date,
        holdings,
        cast(Sequence[Mapping[str, Any]], rows),
    )


async def _fund_exposures_for_cusip(
    session: AsyncSession,
    cusip: str,
) -> list[ReverseLookupFundExposure]:
    rows = (
        await session.execute(
            text(
                """
                WITH latest AS (
                    SELECT series_id, max(report_date) AS report_date
                    FROM fund_holdings
                    WHERE upper(cusip) = :cusip
                    GROUP BY series_id
                )
                SELECT
                    f.instrument_id, f.series_id, f.ticker, f.name,
                    h.issuer_name, h.pct_of_nav, h.market_value, h.report_date
                FROM fund_holdings h
                JOIN latest l
                  ON l.series_id = h.series_id AND l.report_date = h.report_date
                JOIN funds_v f ON f.series_id = h.series_id
                WHERE upper(h.cusip) = :cusip
                ORDER BY h.pct_of_nav DESC NULLS LAST, f.name
                LIMIT 50
                """
            ),
            {"cusip": cusip},
        )
    ).mappings().all()
    return [
        ReverseLookupFundExposure(
            instrument_id=row["instrument_id"],
            series_id=row["series_id"],
            ticker=row["ticker"],
            name=row["name"],
            issuer_name=row["issuer_name"],
            pct_of_nav=_float(row["pct_of_nav"]),
            market_value=_float(row["market_value"]),
            report_date=row["report_date"],
        )
        for row in rows
    ]


def _build_reverse_lookup_response(
    normalized: str,
    institution_rows: Sequence[Mapping[str, Any]],
    fund_exposures: list[ReverseLookupFundExposure],
    source_empty_state: EmptyState | None,
) -> HoldingReverseLookupResponse:
    institutions = [
        ReverseLookupInstitution(
            cik=row["cik"],
            manager_name=row["manager_name"],
            value_usd=_float(row["value_usd"]),
            shares=_float(row["shares"]),
            period=row["period"],
            report_date=row["report_date"],
        )
        for row in institution_rows
    ]
    security_name = (
        institution_rows[0]["name"]
        if institution_rows
        else (fund_exposures[0].issuer_name if fund_exposures else None)
    )
    period = institution_rows[0]["period"] if institution_rows else None
    empty_state = source_empty_state
    if empty_state is None and not institutions:
        empty_state = _empty(
            "No 13F institutional holders matched this CUSIP.", "sec_13f_holdings"
        )
    if not institutions and not fund_exposures:
        empty_state = _empty(
            "No fund exposure or 13F institutional holder matched this CUSIP."
        )
    return HoldingReverseLookupResponse(
        cusip=normalized,
        security_name=security_name,
        period=period,
        institutions=institutions,
        fund_exposures=fund_exposures,
        empty_state=empty_state,
    )


async def _reverse_lookup_institutions_legacy(
    datalake: AsyncSession, normalized: str
) -> tuple[list[Mapping[str, Any]], EmptyState | None]:
    try:
        rows = (
            await datalake.execute(text(_REVERSE_LOOKUP_SQL), {"cusip": normalized})
        ).mappings().all()
    except SQLAlchemyError as exc:
        if _is_missing_relation(exc):
            return [], _empty(
                "SEC 13F holdings tables are not deployed yet.", "sec_13f_holdings"
            )
        raise _source_error("sec_13f_holdings", exc) from exc
    return list(rows), None


async def fetch_holding_reverse_lookup(
    session: AsyncSession,
    datalake: AsyncSession,
    cusip: str,
    *,
    use_db_first: bool | None = None,
) -> HoldingReverseLookupResponse:
    """Institutional + fund holders of a CUSIP (reverse lookup).

    SPLIT: the fund-exposure side (fund_holdings/funds_v) is ALWAYS read
    on-demand from the app DB — it is an org-scoped dynamic catalogue not
    materialized in this migration. The 13F institutional side reads from
    holding_reverse_lookup_mv (datalake) when use_holders_db_first is on, with a
    fallback to the legacy hypertable SQL for CUSIPs absent from the MV (covers
    refresh lag and the MV not yet being deployed). The MV is refreshed on a cron
    by the matview_refresh worker, so a freshly-ingested 13F holding surfaces
    only after the next refresh; the institution reshape is the same helper for
    both paths, so payloads are identical. Freshness is exposed to the frontend
    via the response period/report_date fields.
    """
    normalized = _normalize_cusip(cusip)
    if normalized is None:
        raise ValueError(f"Invalid CUSIP {cusip!r}.")
    if use_db_first is None:
        use_db_first = get_settings().use_holders_db_first

    # Lado de exposições de fundo: SEMPRE on-demand no app DB (catálogo dinâmico,
    # não materializado nesta migração — split documentado no plano/spec §7 B3).
    fund_exposures = await _fund_exposures_for_cusip(session, normalized)

    # Lado institucional: MV quando habilitado, com fallback ao SQL legado.
    institution_rows: list[Mapping[str, Any]] = []
    source_empty_state: EmptyState | None = None
    if use_db_first:
        try:
            rows = (
                await datalake.execute(
                    select(
                        HoldingReverseLookupRow.cik,
                        HoldingReverseLookupRow.manager_name,
                        HoldingReverseLookupRow.period,
                        HoldingReverseLookupRow.report_date,
                        HoldingReverseLookupRow.name,
                        HoldingReverseLookupRow.value_usd,
                        HoldingReverseLookupRow.shares,
                    )
                    .where(HoldingReverseLookupRow.cusip == normalized)
                    .order_by(HoldingReverseLookupRow.value_usd.desc().nullslast())
                    .limit(100)
                )
            ).mappings().all()
        except SQLAlchemyError as exc:
            if _is_missing_relation(exc):
                rows = []
            else:
                raise _source_error("sec_13f_holdings", exc) from exc
        if rows:
            institution_rows = list(rows)
        else:
            # MV vazio/ausente → fallback ao SQL legado.
            institution_rows, source_empty_state = (
                await _reverse_lookup_institutions_legacy(datalake, normalized)
            )
    else:
        institution_rows, source_empty_state = (
            await _reverse_lookup_institutions_legacy(datalake, normalized)
        )

    return _build_reverse_lookup_response(
        normalized, institution_rows, fund_exposures, source_empty_state
    )


def _conditional_volatility(
    returns: pd.Series,
) -> tuple[list[SeriesPoint], Literal["garch", "ewma"]]:
    clean = returns.dropna()
    if len(clean) < 10:
        return [], "ewma"
    try:
        from arch import arch_model  # type: ignore[import-not-found]

        model = arch_model(
            clean.to_numpy(dtype=float) * 100.0,
            vol="Garch",
            p=1,
            q=1,
            rescale=False,
        )
        fit = model.fit(disp="off")
        vol = pd.Series(
            fit.conditional_volatility / 100.0 * math.sqrt(_TRADING_DAYS) * 100.0,
            index=clean.index,
        )
        return _series_points(vol), "garch"
    except Exception:
        variance = float(clean.iloc[0] ** 2)
        values: list[float] = []
        for ret in clean:
            variance = 0.94 * variance + 0.06 * float(ret) ** 2
            values.append(math.sqrt(variance * _TRADING_DAYS) * 100.0)
        return _series_points(pd.Series(values, index=clean.index)), "ewma"


def _regime_label(raw: str | None) -> tuple[float, Literal["Expansion", "Cautious", "Stress"]]:
    value = (raw or "").lower()
    if value in {"risk_off", "stress", "crisis", "high_vol"}:
        return 1.0, "Stress"
    if value in {"neutral", "cautious"}:
        return 0.5, "Cautious"
    return 0.0, "Expansion"


async def _regime_bands(
    datalake: AsyncSession,
    start: dt.date,
    end: dt.date,
) -> tuple[list[FundRegimeBand], EmptyState | None]:
    try:
        rows = (
            await datalake.execute(
                text(
                    """
                    SELECT regime_date, state
                    FROM regime_composite_daily
                    WHERE regime_date >= :start AND regime_date <= :end
                    ORDER BY regime_date
                    """
                ),
                {"start": start, "end": end},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise _source_error("regime_composite_daily", exc) from exc
    bands: list[FundRegimeBand] = []
    for row in rows:
        value, label = _regime_label(row["state"])
        bands.append(FundRegimeBand(time=row["regime_date"], value=value, regime=label))
    return (
        bands,
        None
        if bands
        else _empty(
            "No regime_composite_daily rows in the requested window.",
            "regime_composite_daily",
        ),
    )


async def fetch_fund_risk_timeseries(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    from_date: dt.date | None,
    to_date: dt.date | None,
) -> FundRiskTimeseriesResponse | None:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    first_date, last_date = await select_nav_date_bounds(session, instrument_id)
    if first_date is None or last_date is None:
        raise InsufficientFundDataError(f"No NAV history for fund {instrument_id}.")
    start = from_date or (last_date - dt.timedelta(days=365))
    end = to_date or last_date
    if start > end:
        raise FundAnalysisError("from date must be on or before to date.")
    rows = await select_nav_rows(session, instrument_id, max(first_date, start), end)
    nav = build_nav_series(rows)
    if len(nav) < 10:
        raise InsufficientFundDataError(
            f"Only {len(nav)} NAV rows available in risk-timeseries window."
        )
    returns = simple_returns(nav)
    vol, model = _conditional_volatility(returns)
    regimes, regime_empty = await _regime_bands(datalake, nav.index[0].date(), nav.index[-1].date())

    if get_settings().use_series_db_first:
        dd_pts = await series_sql.drawdown_points(
            session, instrument_id=instrument_id,
            start=nav.index[0].date(), end=nav.index[-1].date(),
        )
        drawdown_points_out = [(d, v * 100.0) for d, v in dd_pts]
    else:
        drawdown_points_out = _series_points(_max_drawdown_series(nav) * 100.0)

    return FundRiskTimeseriesResponse(
        instrument_id=instrument_id,
        drawdown=drawdown_points_out,
        conditional_volatility=vol,
        volatility_model=model,
        regime_bands=regimes,
        empty_state=regime_empty,
    )


async def _holdings_weights(datalake: AsyncSession, series_id: str) -> HoldingsWeights:
    try:
        latest = (
            await datalake.execute(
                text(
                    """
                    SELECT max(report_date) AS report_date
                    FROM sec_nport_holdings
                    WHERE series_id = :series_id
                    """
                ),
                {"series_id": series_id},
            )
        ).mappings().first()
        as_of = latest["report_date"] if latest else None
        if as_of is None:
            return HoldingsWeights({}, None)
        rows = (
            await datalake.execute(
                text(
                    """
                    SELECT cusip, SUM(pct_of_nav) AS weight
                    FROM sec_nport_holdings
                    WHERE series_id = :series_id
                      AND report_date = :as_of
                      AND cusip IS NOT NULL
                      AND pct_of_nav IS NOT NULL
                    GROUP BY cusip
                    """
                ),
                {"series_id": series_id, "as_of": as_of},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise _source_error("sec_nport_holdings", exc) from exc
    weights = {
        str(row["cusip"]): float(row["weight"]) / 100.0
        for row in rows
        if row["weight"] is not None
    }
    return HoldingsWeights(weights, as_of)


def _cik_nport_series_id(cik: str | None) -> str | None:
    if not cik:
        return None
    digits = re.sub(r"\D", "", cik)
    if not digits:
        return None
    return f"CIK:{digits.zfill(10)}"


def _append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)


async def _benchmark_holdings_target(
    session: AsyncSession,
    benchmark_id: uuid.UUID,
) -> BenchmarkHoldingsTarget | None:
    benchmark = await _fund_or_none(session, benchmark_id)
    if benchmark is not None:
        return BenchmarkHoldingsTarget(benchmark.name, [benchmark.series_id])

    result = await session.execute(
        text(
            """
            SELECT iu.ticker,
                   iu.name,
                   ii.sec_series_id,
                   ii.cik_padded,
                   ii.cik_unpadded
            FROM instruments_universe iu
            LEFT JOIN instrument_identity ii ON ii.instrument_id = iu.instrument_id
            WHERE iu.instrument_id = :instrument_id
            LIMIT 1
            """
        ),
        {"instrument_id": benchmark_id},
    )
    row = result.mappings().first()
    if row is None:
        return None

    ticker = str(row["ticker"]).upper() if row["ticker"] else None
    series_ids: list[str] = []
    _append_unique(series_ids, row["sec_series_id"])
    _append_unique(series_ids, _cik_nport_series_id(row["cik_padded"]))
    _append_unique(series_ids, _cik_nport_series_id(row["cik_unpadded"]))

    if ticker:
        sec_rows = (
            await session.execute(
                text(
                    """
                    SELECT series_id, cik
                    FROM sec_etfs
                    WHERE upper(ticker) = :ticker
                    UNION ALL
                    SELECT series_id, NULL::text AS cik
                    FROM sec_fund_classes
                    WHERE upper(ticker) = :ticker
                    """
                ),
                {"ticker": ticker},
            )
        ).mappings().all()
        for sec_row in sec_rows:
            # Some ETF N-PORT rows are materialized under CIK:<cik> rather than
            # the SEC ETF row's raw series_id. Prefer that candidate first.
            _append_unique(series_ids, _cik_nport_series_id(sec_row["cik"]))
            _append_unique(series_ids, sec_row["series_id"])

    name = cast(str | None, row["name"] or ticker)
    return BenchmarkHoldingsTarget(name, series_ids)


def active_share_from_weights(
    portfolio: Mapping[str, float],
    benchmark: Mapping[str, float],
) -> tuple[float, float, int]:
    keys = set(portfolio) | set(benchmark)
    active_share = 0.5 * sum(abs(portfolio.get(key, 0.0) - benchmark.get(key, 0.0)) for key in keys)
    common = set(portfolio) & set(benchmark)
    overlap = sum(min(portfolio[key], benchmark[key]) for key in common)
    return active_share, overlap, len(common)


async def fetch_fund_active_share(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    use_db_first: bool | None = None,
) -> FundActiveShareResponse | None:
    """Active share vs the fund's PRIMARY benchmark (spec §6 A5 — benchmark_id
    removido). DB-first lê as colunas active-share de fund_risk_latest_mv (não
    há mais fund_active_share_mv standalone). Com a flag off, cai ao corpo
    legado (benchmark_id=None → empty-state), preservado só para a transição.
    """
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first
    if not use_db_first:
        return await _fetch_fund_active_share_legacy(
            session, datalake, instrument_id, benchmark_id=None
        )

    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    try:
        risk = await session.get(FundRiskLatest, instrument_id)
        if risk is None or risk.active_share_normalized is None:
            return FundActiveShareResponse(
                instrument_id=instrument_id,
                empty_state=_empty(
                    "No active-share computed for this fund.",
                    "fund_risk_latest_mv",
                ),
            )
        benchmark_name = await _resolve_benchmark_name(
            session,
            series_id=risk.active_share_benchmark_series_id,
            instrument_id=risk.active_share_benchmark_instrument_id,
        )
    except SQLAlchemyError:
        return await _fetch_fund_active_share_legacy(
            session, datalake, instrument_id, benchmark_id=None
        )
    return FundActiveShareResponse(
        instrument_id=instrument_id,
        benchmark_name=benchmark_name,
        benchmark_series_id=risk.active_share_benchmark_series_id,
        active_share=_float(risk.active_share_normalized),
        overlap=_float(risk.overlap_normalized),
        n_portfolio_positions=risk.n_fund_holdings or 0,
        n_benchmark_positions=risk.n_benchmark_holdings or 0,
        n_common_positions=risk.n_common_holdings or 0,
        as_of_date=risk.active_share_fund_report_date,
    )


async def _resolve_benchmark_name(
    session: AsyncSession,
    *,
    series_id: str | None,
    instrument_id: uuid.UUID | None,
) -> str | None:
    """Human label for the benchmark proxy: prefer the fund name from
    funds_list_mv (by series_id), then the proxy ETF ticker from
    instruments_universe (by instrument_id), else the raw series_id."""
    if series_id is not None:
        name = (
            await session.execute(
                select(FundListRow.name).where(FundListRow.series_id == series_id)
            )
        ).scalar_one_or_none()
        if name:
            return name
    if instrument_id is not None:
        ticker = (
            await session.execute(
                text(
                    "SELECT ticker FROM instruments_universe "
                    "WHERE instrument_id = :iid LIMIT 1"
                ),
                {"iid": instrument_id},
            )
        ).scalar()
        if ticker:
            return str(ticker)
    return series_id


async def _fetch_fund_active_share_legacy(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    benchmark_id: uuid.UUID | None,
) -> FundActiveShareResponse | None:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    if benchmark_id is None:
        return FundActiveShareResponse(
            instrument_id=instrument_id,
            empty_state=_empty(
                "benchmark_id is required to compute active share.",
                "sec_nport_holdings",
            ),
        )
    benchmark_target = await _benchmark_holdings_target(session, benchmark_id)
    if benchmark_target is None or not benchmark_target.series_ids:
        return FundActiveShareResponse(
            instrument_id=instrument_id,
            benchmark_name=benchmark_target.name if benchmark_target else None,
            empty_state=_empty(
                "Benchmark instrument could not be resolved to N-PORT holdings.",
                "sec_nport_holdings",
            ),
        )
    portfolio = await _holdings_weights(datalake, fund.series_id)
    benchmark_weights = HoldingsWeights({}, None)
    for benchmark_series_id in benchmark_target.series_ids:
        benchmark_weights = await _holdings_weights(datalake, benchmark_series_id)
        if benchmark_weights.weights:
            break
    if not portfolio.weights:
        return FundActiveShareResponse(
            instrument_id=instrument_id,
            benchmark_name=benchmark_target.name,
            as_of_date=portfolio.as_of,
            empty_state=_empty("Portfolio fund has no N-PORT holdings.", "sec_nport_holdings"),
        )
    if not benchmark_weights.weights:
        return FundActiveShareResponse(
            instrument_id=instrument_id,
            benchmark_name=benchmark_target.name,
            n_portfolio_positions=len(portfolio.weights),
            as_of_date=portfolio.as_of,
            empty_state=_empty("Benchmark fund has no N-PORT holdings.", "sec_nport_holdings"),
        )
    active_share, overlap, n_common = active_share_from_weights(
        portfolio.weights, benchmark_weights.weights
    )
    as_of = min(
        d for d in [portfolio.as_of, benchmark_weights.as_of] if d is not None
    )
    return FundActiveShareResponse(
        instrument_id=instrument_id,
        benchmark_name=benchmark_target.name,
        active_share=active_share,
        overlap=overlap,
        n_portfolio_positions=len(portfolio.weights),
        n_benchmark_positions=len(benchmark_weights.weights),
        n_common_positions=n_common,
        as_of_date=as_of,
    )
