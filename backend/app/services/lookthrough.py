"""Look-through consumption service (Frente C, ADENDO §6 do doc de research).

The recursive look-through is computed by the ``nport_lookthrough`` worker in
the datalake repo and materialized in the TimescaleDB Cloud
(``nport_lookthrough_exposures`` + ``nport_lookthrough_summary``). This module
only READS those tables and does portfolio-level weighted consolidation —
pure arithmetic over materialized rows, never expansion.

Semantics inherited from the worker (do not reinterpret here):
- pct values are percentage points of the SERIES NAV, sign preserved;
  Σpct > 100 (derivatives/leverage) is legitimate and never renormalized.
- ``oldest_report_date`` is the chain staleness (oldest N-PORT report used).
- residual buckets (nondecomposable funds, derivatives gross/net,
  unidentified synthetic keys) are explicit in the summary.
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fund import Fund

DIMENSIONS = ("issuer", "asset_class", "sector", "currency")


@dataclass(frozen=True)
class ExposureRow:
    dimension: str
    key: str
    label: str | None
    direct_pct: float
    indirect_pct: float

    @property
    def total_pct(self) -> float:
        return self.direct_pct + self.indirect_pct


@dataclass(frozen=True)
class LookthroughSummary:
    sum_pct_total: float | None
    direct_pct: float | None
    indirect_pct: float | None
    expanded_fund_pct: float | None
    nondecomposable_fund_pct: float | None
    derivatives_gross_pct: float | None
    derivatives_net_pct: float | None
    unidentified_pct: float | None
    coverage_pct: float | None
    n_holdings: int | None
    n_children_expanded: int | None
    oldest_report_date: dt.date | None


@dataclass(frozen=True)
class SeriesLookthrough:
    series_id: str
    report_date: dt.date
    exposures: list[ExposureRow]
    summary: LookthroughSummary


@dataclass(frozen=True)
class PortfolioAggregates:
    """Consolidated portfolio-level totals (percent points of total value)."""

    expanded_weight_pct: float
    sum_pct_total: float
    oldest_report_date: dt.date | None


# ---------------------------------------------------------------------------
# Local-DB lookups (funds table)
# ---------------------------------------------------------------------------


async def get_fund_series(
    session: AsyncSession, instrument_id: uuid.UUID
) -> str | None:
    """series_id of a local fund, or None when the instrument is unknown."""
    fund = await session.get(Fund, instrument_id)
    return fund.series_id if fund is not None else None


async def get_fund_series_by_ticker(
    session: AsyncSession, tickers: list[str]
) -> dict[str, str]:
    """ticker → series_id for the tickers that are funds in the local universe."""
    if not tickers:
        return {}
    result = await session.execute(
        select(Fund.ticker, Fund.series_id).where(Fund.ticker.in_(tickers))
    )
    return {ticker: series_id for ticker, series_id in result.all()}


# ---------------------------------------------------------------------------
# Data-lake reads (materialized tables — read-only)
# ---------------------------------------------------------------------------

_SUMMARY_SQL = text("""
    SELECT DISTINCT ON (series_id)
           series_id, report_date, sum_pct_total, direct_pct, indirect_pct,
           expanded_fund_pct, nondecomposable_fund_pct, derivatives_gross_pct,
           derivatives_net_pct, unidentified_pct, coverage_pct, n_holdings,
           n_children_expanded, oldest_report_date
    FROM nport_lookthrough_summary
    WHERE series_id = ANY(:series_ids)
    ORDER BY series_id, report_date DESC
""")

_EXPOSURES_SQL = text("""
    SELECT series_id, dimension, key, label, direct_pct, indirect_pct
    FROM nport_lookthrough_exposures
    WHERE series_id = ANY(:series_ids)
      AND report_date = :report_date
      -- CAST: asyncpg cannot infer the type of a bare "$n IS NULL" parameter
      AND (CAST(:dimension AS text) IS NULL OR dimension = CAST(:dimension AS text))
""")


def _summary_from_row(row) -> LookthroughSummary:
    def f(value) -> float | None:
        return float(value) if value is not None else None

    return LookthroughSummary(
        sum_pct_total=f(row.sum_pct_total),
        direct_pct=f(row.direct_pct),
        indirect_pct=f(row.indirect_pct),
        expanded_fund_pct=f(row.expanded_fund_pct),
        nondecomposable_fund_pct=f(row.nondecomposable_fund_pct),
        derivatives_gross_pct=f(row.derivatives_gross_pct),
        derivatives_net_pct=f(row.derivatives_net_pct),
        unidentified_pct=f(row.unidentified_pct),
        coverage_pct=f(row.coverage_pct),
        n_holdings=row.n_holdings,
        n_children_expanded=row.n_children_expanded,
        oldest_report_date=row.oldest_report_date,
    )


async def fetch_series_lookthrough(
    datalake: AsyncSession, series_id: str, dimension: str | None = None
) -> SeriesLookthrough | None:
    """Latest materialized look-through for one series, or None."""
    result = await fetch_many_lookthroughs(
        datalake, [series_id], dimension=dimension
    )
    return result.get(series_id)


async def fetch_many_lookthroughs(
    datalake: AsyncSession, series_ids: list[str], dimension: str | None = None
) -> dict[str, SeriesLookthrough]:
    """Latest materialized look-through per series (missing series omitted)."""
    if not series_ids:
        return {}
    summaries = (
        await datalake.execute(_SUMMARY_SQL, {"series_ids": series_ids})
    ).all()
    out: dict[str, SeriesLookthrough] = {}
    for row in summaries:
        exposures = (
            await datalake.execute(
                _EXPOSURES_SQL,
                {
                    "series_ids": [row.series_id],
                    "report_date": row.report_date,
                    "dimension": dimension,
                },
            )
        ).all()
        out[row.series_id] = SeriesLookthrough(
            series_id=row.series_id,
            report_date=row.report_date,
            exposures=[
                ExposureRow(
                    dimension=e.dimension,
                    key=e.key,
                    label=e.label,
                    direct_pct=float(e.direct_pct),
                    indirect_pct=float(e.indirect_pct),
                )
                for e in exposures
            ],
            summary=_summary_from_row(row),
        )
    return out


# ---------------------------------------------------------------------------
# Portfolio consolidation — pure math (unit-tested directly)
# ---------------------------------------------------------------------------


def consolidate_portfolio(
    weighted: list[tuple[float, SeriesLookthrough]],
) -> tuple[list[ExposureRow], PortfolioAggregates]:
    """Weighted merge of fund look-throughs into portfolio exposures.

    ``weighted`` carries (weight_fraction, lookthrough) per expanded fund
    position; weight is the position's share of TOTAL portfolio value (0.40 =
    40%). Outputs are percent points of portfolio value: a 40% position in a
    fund 80% exposed to an issuer contributes 32 points. The direct/indirect
    split of each fund is preserved through the weighting. Never renormalizes.
    """
    cells: dict[tuple[str, str], dict] = {}
    expanded_weight = 0.0
    sum_pct_total = 0.0
    oldest: dt.date | None = None

    for weight, data in weighted:
        expanded_weight += weight
        if data.summary.sum_pct_total is not None:
            sum_pct_total += weight * data.summary.sum_pct_total
        candidates = [data.report_date, data.summary.oldest_report_date]
        for candidate in candidates:
            if candidate is not None and (oldest is None or candidate < oldest):
                oldest = candidate
        for row in data.exposures:
            cell = cells.setdefault(
                (row.dimension, row.key),
                {"label": row.label, "direct_pct": 0.0, "indirect_pct": 0.0},
            )
            cell["direct_pct"] += weight * row.direct_pct
            cell["indirect_pct"] += weight * row.indirect_pct
            if row.label and not cell["label"]:
                cell["label"] = row.label

    rows = [
        ExposureRow(
            dimension=dimension,
            key=key,
            label=cell["label"],
            direct_pct=cell["direct_pct"],
            indirect_pct=cell["indirect_pct"],
        )
        for (dimension, key), cell in sorted(
            cells.items(),
            key=lambda item: (
                item[0][0],
                -(item[1]["direct_pct"] + item[1]["indirect_pct"]),
            ),
        )
    ]
    aggregates = PortfolioAggregates(
        expanded_weight_pct=100.0 * expanded_weight,
        sum_pct_total=sum_pct_total,
        oldest_report_date=oldest,
    )
    return rows, aggregates
