"""P5 Tier B services for the fund dossier.

The route layer owns HTTP mapping; this module keeps DB reads explicit and all
analytics deterministic. The Light backend remains DB-first: no synthetic panel
data is fabricated when a source table is empty.
"""

import datetime as dt
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import simple_returns
from app.models.fund import Fund
from app.schemas.analysis import SeriesPoint
from app.schemas.fund_analysis import (
    EmptyState,
    FundActiveShareResponse,
    FundCaptureRatios,
    FundDrawdownAnalysis,
    FundDrawdownPeriod,
    FundEntityAnalyticsResponse,
    FundFactorsResponse,
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
)
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


class InvalidBenchmarkError(FundAnalysisError):
    """Benchmark id is syntactically valid but cannot be used for this endpoint."""


class TierBSourceError(FundAnalysisError):
    """A required Tier B source relation is unavailable or unreadable."""


@dataclass(frozen=True)
class HoldingsWeights:
    weights: dict[str, float]
    as_of: dt.date | None


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _series_points(series: pd.Series) -> list[SeriesPoint]:
    clean = series.dropna()
    return [(idx.date(), float(value)) for idx, value in clean.items()]


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


async def _fund_or_none(session: AsyncSession, instrument_id: uuid.UUID) -> Fund | None:
    return await session.get(Fund, instrument_id)


async def _fund_or_missing(session: AsyncSession, instrument_id: uuid.UUID) -> Fund:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        raise LookupError(f"Fund {instrument_id} not found.")
    return fund


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


async def fetch_fund_factors(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
) -> FundFactorsResponse | None:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None

    first_date, last_date = await select_nav_date_bounds(session, instrument_id)
    nav = pd.Series(dtype=float)
    if first_date is not None and last_date is not None:
        nav = build_nav_series(await select_nav_rows(session, instrument_id, first_date, last_date))
    monthly_returns = (
        nav.resample("ME").last().pct_change().dropna()
        if len(nav)
        else pd.Series(dtype=float)
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
                    )
                    SELECT h.report_date,
                           COALESCE(h.sector, 'Unknown') AS sector,
                           SUM(h.pct_of_nav) AS weight
                    FROM sec_nport_holdings h
                    JOIN q ON q.report_date = h.report_date
                    WHERE h.series_id = :series_id
                    GROUP BY h.report_date, COALESCE(h.sector, 'Unknown')
                    ORDER BY h.report_date ASC, weight DESC NULLS LAST
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
    compounded = float((1.0 + returns).prod())
    return compounded ** (_TRADING_DAYS / len(returns)) - 1.0


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
    for idx, depth in drawdowns.items():
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
        skewness=float(pd.Series(values).skew()),
        kurtosis=float(pd.Series(values).kurt()),
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
    geometric = float((1.0 + monthly).prod() ** (1.0 / len(monthly)) - 1.0)
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
    skew = float(returns.skew())
    kurt = float(returns.kurt())
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
    skew = float(clean.skew())
    kurt = float(clean.kurt())
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


def assemble_entity_analytics(
    nav: pd.Series,
    *,
    fund: Fund,
    window: WindowKey,
    benchmark_nav: pd.Series | None = None,
    benchmark_id: uuid.UUID | None = None,
    benchmark_label: str | None = None,
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
        insider_data=None,
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


async def fetch_fund_entity_analytics(
    session: AsyncSession,
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
        benchmark = await _fund_or_none(session, benchmark_id)
        if benchmark is None:
            raise InvalidBenchmarkError(f"Benchmark fund {benchmark_id} not found.")
        benchmark_nav = await _nav_for_window(session, benchmark_id, window)
        benchmark_label = benchmark.ticker or benchmark.name
    return assemble_entity_analytics(
        nav,
        fund=fund,
        window=window,
        benchmark_nav=benchmark_nav,
        benchmark_id=benchmark_id,
        benchmark_label=benchmark_label,
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
    drawdown = _max_drawdown_series(nav) * 100.0
    returns = simple_returns(nav)
    vol, model = _conditional_volatility(returns)
    regimes, regime_empty = await _regime_bands(datalake, nav.index[0].date(), nav.index[-1].date())
    return FundRiskTimeseriesResponse(
        instrument_id=instrument_id,
        drawdown=_series_points(drawdown),
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
    benchmark = await _fund_or_none(session, benchmark_id)
    if benchmark is None:
        raise InvalidBenchmarkError(f"Benchmark fund {benchmark_id} not found.")
    portfolio = await _holdings_weights(datalake, fund.series_id)
    benchmark_weights = await _holdings_weights(datalake, benchmark.series_id)
    if not portfolio.weights:
        return FundActiveShareResponse(
            instrument_id=instrument_id,
            benchmark_id=benchmark_id,
            benchmark_name=benchmark.name,
            as_of_date=portfolio.as_of,
            empty_state=_empty("Portfolio fund has no N-PORT holdings.", "sec_nport_holdings"),
        )
    if not benchmark_weights.weights:
        return FundActiveShareResponse(
            instrument_id=instrument_id,
            benchmark_id=benchmark_id,
            benchmark_name=benchmark.name,
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
        benchmark_id=benchmark_id,
        benchmark_name=benchmark.name,
        active_share=active_share,
        overlap=overlap,
        n_portfolio_positions=len(portfolio.weights),
        n_benchmark_positions=len(benchmark_weights.weights),
        n_common_positions=n_common,
        as_of_date=as_of,
    )
