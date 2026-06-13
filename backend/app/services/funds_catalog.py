"""Funds catalog service (F8.2): list/profile/CSV reads over the local
fund-universe snapshot (synced read-only from the mother DB by F8.1).

Routes own HTTP mapping; this module owns SQL plus the pure helpers
(filter predicates, sort whitelist, NAV decimation, CSV columns). Fail-loud
contract:

- a sort column outside the whitelist raises ``UnknownSortColumnError``
  (routes -> 422) — user input NEVER reaches SQL text;
- "fund not found" is signalled by ``None`` (routes -> 404).

The Light NEVER recomputes metrics: every numeric in the responses is the
mother-DB value copied by the sync, served with the global staleness markers.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from typing import Any, cast

from sqlalchemy import ColumnElement, Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models.fund import Fund, FundClass, FundHolding, FundRiskLatest

# Canonical strategy label for funds the mother-DB cascade could not classify.
# (Was sourced from the now-retired app.sync.funds; this service is its sole
# runtime consumer — used by the strategy filter below.)
UNCLASSIFIED_LABEL = "Unclassified"

# Hard cap on the CSV export — bounded output, no pagination (screener parity).
CSV_HARD_CAP = 5000

# NAV series window and decimation target for the profile chart.
NAV_WINDOW_DAYS = 365 * 2
NAV_TARGET_POINTS = 260

# Top-50 cap of the N-PORT source (defense in depth — the sync stores <= 50).
HOLDINGS_CAP = 50


class UnknownSortColumnError(Exception):
    """Raised when a sort column is outside the whitelist (routes -> 422)."""


# ---------------------------------------------------------------------------
# Sort whitelist (pure — unit-tested)
# ---------------------------------------------------------------------------

_FUND_SORT_FIELDS = (
    "ticker",
    "name",
    "fund_type",
    "strategy_label",
    "asset_class",
    "expense_ratio",
    "aum_usd",
    "inception_date",
)

# Every fund_risk_latest column except the PK join key is sortable — the
# mapping is built from the model so it can never drift from the table.
_RISK_SORT_FIELDS = tuple(
    column.key
    for column in FundRiskLatest.__table__.columns
    if column.key != "instrument_id"
)

SORT_WHITELIST: dict[str, InstrumentedAttribute[Any]] = {
    **{name: getattr(Fund, name) for name in _FUND_SORT_FIELDS},
    **{name: getattr(FundRiskLatest, name) for name in _RISK_SORT_FIELDS},
}

DEFAULT_SORT = "aum_usd"
DEFAULT_DIRECTION = "desc"


def sort_column(code: str) -> InstrumentedAttribute[Any]:
    """Resolve a sort code through the whitelist — THE injection gate."""
    column = SORT_WHITELIST.get(code)
    if column is None:
        raise UnknownSortColumnError(
            f"Cannot sort by {code!r}: not a whitelisted funds column."
        )
    return column


# ---------------------------------------------------------------------------
# Filters (pure — unit-tested)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FundFilters:
    """The /funds query filters; None = not applied."""

    search: str | None = None
    fund_type: str | None = None
    strategy_label: str | None = None
    asset_class: str | None = None
    expense_ratio_max: float | None = None
    aum_min: float | None = None
    sharpe_1y_min: float | None = None
    volatility_1y_max: float | None = None
    return_1y_min: float | None = None
    # Drawdowns are negative fractions: "min" keeps funds whose worst 1y
    # drawdown is no deeper than the bound (e.g. -0.2 keeps dd >= -20%).
    max_drawdown_1y_min: float | None = None


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards in user search input (backslash escape char)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def filter_conditions(filters: FundFilters) -> list[ColumnElement[bool]]:
    """SQL predicates for ALL active filters.

    Risk-metric bounds compare against fund_risk_latest columns — SQL NULL
    comparisons are falsy, so funds without that metric drop out by
    definition (a fund that cannot be ranked never matches a bound on it).

    'Unclassified' funds are excluded from the listing UNCONDITIONALLY
    (decisão do dono, 2026-06-12): the residual ~1% the reclassification
    pipeline could not label has no strategy/peer context and pollutes the
    screen. Their profile pages stay reachable by direct id (the profile
    fetch does not go through these conditions).
    """
    conditions: list[ColumnElement[bool]] = [
        Fund.strategy_label.is_distinct_from(UNCLASSIFIED_LABEL)
    ]
    if filters.search:
        pattern = f"%{_escape_like(filters.search)}%"
        conditions.append(
            or_(
                Fund.ticker.ilike(pattern, escape="\\"),
                Fund.name.ilike(pattern, escape="\\"),
            )
        )
    if filters.fund_type is not None:
        conditions.append(Fund.fund_type == filters.fund_type)
    if filters.strategy_label is not None:
        # Free-text strategy filter (the UI offers no canonical select):
        # case-insensitive substring match.
        strategy_pattern = f"%{_escape_like(filters.strategy_label)}%"
        conditions.append(Fund.strategy_label.ilike(strategy_pattern, escape="\\"))
    if filters.asset_class is not None:
        conditions.append(Fund.asset_class == filters.asset_class)
    if filters.expense_ratio_max is not None:
        conditions.append(Fund.expense_ratio <= filters.expense_ratio_max)
    if filters.aum_min is not None:
        conditions.append(Fund.aum_usd >= filters.aum_min)
    if filters.sharpe_1y_min is not None:
        conditions.append(FundRiskLatest.sharpe_1y >= filters.sharpe_1y_min)
    if filters.volatility_1y_max is not None:
        conditions.append(FundRiskLatest.volatility_1y <= filters.volatility_1y_max)
    if filters.return_1y_min is not None:
        conditions.append(FundRiskLatest.return_1y >= filters.return_1y_min)
    if filters.max_drawdown_1y_min is not None:
        conditions.append(
            FundRiskLatest.max_drawdown_1y >= filters.max_drawdown_1y_min
        )
    return conditions


# Item columns served on every list row (funds identity + headline metrics).
_ITEM_COLUMNS: tuple[tuple[str, InstrumentedAttribute[Any]], ...] = (
    ("instrument_id", Fund.instrument_id),
    ("series_id", Fund.series_id),
    ("ticker", Fund.ticker),
    ("name", Fund.name),
    ("fund_type", Fund.fund_type),
    ("strategy_label", Fund.strategy_label),
    ("asset_class", Fund.asset_class),
    ("is_index", Fund.is_index),
    ("expense_ratio", Fund.expense_ratio),
    ("aum_usd", Fund.aum_usd),
    ("return_1y", FundRiskLatest.return_1y),
    ("volatility_1y", FundRiskLatest.volatility_1y),
    ("sharpe_1y", FundRiskLatest.sharpe_1y),
    ("max_drawdown_1y", FundRiskLatest.max_drawdown_1y),
    ("peer_sharpe_pctl", FundRiskLatest.peer_sharpe_pctl),
    ("elite_flag", FundRiskLatest.elite_flag),
)


def _base_select(*columns: Any) -> Select[Any]:
    """SELECT *columns* over funds LEFT JOIN fund_risk_latest."""
    return (
        select(*columns)
        .select_from(Fund)
        .outerjoin(FundRiskLatest, FundRiskLatest.instrument_id == Fund.instrument_id)
    )


def build_funds_select(
    filters: FundFilters,
    *,
    sort: str,
    direction: str,
    limit: int,
    offset: int,
) -> Select[Any]:
    """The dynamic-but-whitelisted funds list SELECT (pure — unit-tested)."""
    column = sort_column(sort)
    order = column.desc() if direction == "desc" else column.asc()
    return (
        _base_select(*(col for _name, col in _ITEM_COLUMNS))
        .where(*filter_conditions(filters))
        .order_by(order.nulls_last(), Fund.ticker.nulls_last(), Fund.instrument_id)
        .limit(limit)
        .offset(offset)
    )


def build_count_select(filters: FundFilters) -> Select[Any]:
    """COUNT over the same filtered set as the list SELECT."""
    return _base_select(func.count()).where(*filter_conditions(filters))


# ---------------------------------------------------------------------------
# List + staleness reads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Staleness:
    """Global max of the per-fund staleness markers (None on an empty table)."""

    synced_at: dt.datetime | None
    source_calc_date: dt.date | None
    source_nav_max_date: dt.date | None


async def fetch_funds(
    session: AsyncSession,
    filters: FundFilters,
    *,
    sort: str,
    direction: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """One list page as row dicts (keyed by item column name) + total count."""
    result = await session.execute(
        build_funds_select(
            filters, sort=sort, direction=direction, limit=limit, offset=offset
        )
    )
    names = [name for name, _col in _ITEM_COLUMNS]
    rows = [dict(zip(names, row, strict=True)) for row in result.all()]
    total = int(await session.scalar(build_count_select(filters)) or 0)
    return rows, total


async def fetch_staleness(session: AsyncSession) -> Staleness:
    """Global data-freshness markers, derived from the dynamic sources.

    The retired sync snapshot carried per-row synced_at/source_calc_date/
    source_nav_max_date; the funds_v VIEW has none, so staleness is read live:
    - source_calc_date  = MAX(fund_risk_latest_mv.calc_date)
    - source_nav_max_date = MAX(nav_timeseries.nav_date)  (raw hypertable, 2.4)
    - synced_at         = the view is "as fresh as the read" → query time, but
      only when the universe is non-empty (None on an empty catalog, matching
      the previous empty-table contract).
    """
    source_calc_date = await session.scalar(select(func.max(FundRiskLatest.calc_date)))
    source_nav_max_date = cast(
        "dt.date | None",
        await session.scalar(text("SELECT max(nav_date) FROM nav_timeseries")),
    )
    fund_count = int(
        await session.scalar(select(func.count()).select_from(Fund)) or 0
    )
    has_universe = fund_count > 0 and (
        source_calc_date is not None or source_nav_max_date is not None
    )
    return Staleness(
        synced_at=dt.datetime.now(dt.UTC) if has_universe else None,
        source_calc_date=source_calc_date,
        source_nav_max_date=source_nav_max_date,
    )


# ---------------------------------------------------------------------------
# CSV (reuses the screener's stable cell formatting)
# ---------------------------------------------------------------------------

# (code, header, data_type) — data_type drives the stable numeric formatting
# of app.services.screener._csv_cell via render_csv.
CSV_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("ticker", "Ticker", "string"),
    ("name", "Name", "string"),
    ("fund_type", "Type", "string"),
    ("strategy_label", "Strategy", "string"),
    ("asset_class", "Asset class", "string"),
    ("aum_usd", "AUM (USD)", "currency"),
    ("expense_ratio", "Expense ratio", "percent"),
    ("return_1y", "Return 1Y", "percent"),
    ("volatility_1y", "Volatility 1Y", "percent"),
    ("sharpe_1y", "Sharpe 1Y", "float"),
    ("max_drawdown_1y", "Max drawdown 1Y", "percent"),
    ("peer_sharpe_pctl", "Peer Sharpe pctl", "float"),
    ("elite_flag", "Elite", "string"),
)


def csv_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, str | float | None]]:
    """Project list-row dicts onto the CSV columns (pure — unit-tested).

    Decimals become floats; elite_flag becomes "true"/"false"; None stays
    None (rendered as an empty cell).
    """
    out: list[dict[str, str | float | None]] = []
    for row in rows:
        record: dict[str, str | float | None] = {}
        for code, _header, data_type in CSV_COLUMNS:
            value = row.get(code)
            if value is None:
                record[code] = None
            elif code == "elite_flag":
                record[code] = "true" if value else "false"
            elif data_type == "string":
                record[code] = str(value)
            else:
                record[code] = float(value)
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# NAV series read (raw nav_timeseries hypertable) + decimation (pure)
# ---------------------------------------------------------------------------


def build_nav_series_select(instrument_id: uuid.UUID, start: dt.date) -> Select[Any]:
    """NAV (nav_date, nav) for one fund from the raw nav_timeseries hypertable.

    Reads the timeseries directly (Task 2.4) instead of the retired fund_nav
    snapshot. Bound params (no user input reaches SQL text); date-sorted; NULL
    NAVs dropped so the chart shows real prints only.
    """
    return (
        select(text("nav_date"), text("nav"))
        .select_from(text("nav_timeseries"))
        .where(
            text("instrument_id = :iid"),
            text("nav_date >= :start"),
            text("nav IS NOT NULL"),
        )
        .order_by(text("nav_date"))
        .params(iid=str(instrument_id), start=start)
    )


def decimate_nav(
    points: Sequence[tuple[dt.date, float | None]],
    target: int = NAV_TARGET_POINTS,
) -> list[tuple[dt.date, float | None]]:
    """Evenly subsample a date-sorted NAV series down to ~``target`` points.

    Always keeps the first and the last observation; a series at or under
    the target is returned unchanged. Pure index arithmetic — no value
    interpolation (the chart shows real NAV prints only).
    """
    if target < 2:
        raise ValueError(f"decimation target must be >= 2, got {target}.")
    n = len(points)
    if n <= target:
        return list(points)
    step = (n - 1) / (target - 1)
    indices = sorted({round(i * step) for i in range(target)} | {n - 1})
    return [points[i] for i in indices]


# ---------------------------------------------------------------------------
# Profile read
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FundProfile:
    """Everything the profile endpoint needs, fetched in one service call."""

    fund: Fund
    risk: FundRiskLatest | None
    nav: list[tuple[dt.date, float | None]]
    holdings: list[FundHolding]
    holdings_report_date: dt.date | None
    holdings_pct_of_nav_total: float | None
    # Share classes (F8.6b), expense_ratio asc NULLS LAST. NOTE: any class
    # is priced with the SERIES NAV as a proxy (the source prices only the
    # representative class).
    classes: list[FundClass] = field(default_factory=list)


async def fetch_fund_profile(
    session: AsyncSession, instrument_id: uuid.UUID
) -> FundProfile | None:
    """Fund + full risk snapshot + decimated 2y NAV + latest holdings.

    Returns None when the instrument is not in the local universe.
    """
    fund = await session.get(Fund, instrument_id)
    if fund is None:
        return None
    risk = await session.get(FundRiskLatest, instrument_id)

    max_nav_date = cast(
        "dt.date | None",
        await session.scalar(
            text("SELECT max(nav_date) FROM nav_timeseries WHERE instrument_id = :iid"),
            {"iid": str(instrument_id)},
        ),
    )
    nav: list[tuple[dt.date, float | None]] = []
    if max_nav_date is not None:
        window_start = max_nav_date - dt.timedelta(days=NAV_WINDOW_DAYS)
        result = await session.execute(
            build_nav_series_select(instrument_id, window_start)
        )
        raw = [
            (cast("dt.date", nav_date), float(value) if value is not None else None)
            for nav_date, value in result.all()
        ]
        nav = decimate_nav(raw)

    latest_report = await session.scalar(
        select(func.max(FundHolding.report_date)).where(
            FundHolding.series_id == fund.series_id
        )
    )
    holdings: list[FundHolding] = []
    pct_total: float | None = None
    if latest_report is not None:
        # HOLDINGS_CAP is a DISPLAY cap for the profile widget (top holdings
        # by rank) — the full exposure lives in /funds/{id}/lookthrough.
        holdings = list(
            (
                await session.execute(
                    select(FundHolding)
                    .where(
                        FundHolding.series_id == fund.series_id,
                        FundHolding.report_date == latest_report,
                    )
                    .order_by(FundHolding.rank)
                    .limit(HOLDINGS_CAP)
                )
            ).scalars()
        )
        reported = [float(h.pct_of_nav) for h in holdings if h.pct_of_nav is not None]
        pct_total = sum(reported) if reported else None

    # FundClass (fund_classes_v) is keyed by series_id — a class links to a
    # fund via the series, not the instrument. Resolve through the loaded fund.
    classes = list(
        (
            await session.execute(
                select(FundClass)
                .where(FundClass.series_id == fund.series_id)
                .order_by(
                    FundClass.expense_ratio.asc().nulls_last(), FundClass.ticker
                )
            )
        ).scalars()
    )

    # funds_v has no sync markers; derive the per-fund staleness the route
    # exposes from the dynamic sources (risk MV calc_date + latest NAV date).
    # Attached on the instance so the route serializes them unchanged (Task 2.4
    # finalizes the staleness source).
    fund.synced_at = dt.datetime.now(dt.UTC)  # type: ignore[attr-defined]
    fund.source_calc_date = risk.calc_date if risk is not None else None  # type: ignore[attr-defined]
    fund.source_nav_max_date = max_nav_date  # type: ignore[attr-defined]

    return FundProfile(
        fund=fund,
        risk=risk,
        nav=nav,
        holdings=holdings,
        holdings_report_date=latest_report,
        holdings_pct_of_nav_total=pct_total,
        classes=classes,
    )


# Defense in depth: the FundFilters fields ARE the route's query params —
# keep them in sync (test asserts this) so a new filter cannot be forgotten.
FILTER_FIELD_NAMES = tuple(field.name for field in fields(FundFilters))
