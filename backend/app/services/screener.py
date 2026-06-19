"""Screener service (F6.4): screens persistence + build/results reads.

Routes own HTTP mapping; this module owns SQL and the pure histogram/CSV
helpers. Fail-loud contract:

- duplicate screen names raise ``DuplicateScreenNameError`` (routes → 409);
- "not found" is signalled by ``None``/``False`` returns (routes → 404);
- a metric column with zero non-NULL rows raises
  ``MetricDataUnavailableError`` (build route → 422; the filter-upsert route
  degrades to ``distribution: null`` because the WRITE succeeded);
- a metric code outside the catalog raises ``UnknownMetricCodeError``
  (defense in depth — routes already 422 before calling in).

SQL-injection stance: results/build queries are dynamic per screen, but
every user-supplied metric code is resolved through the backend catalog
(``app.screener.catalog``) into a SQLAlchemy column attribute of
``ScreenerMetrics`` — user input is NEVER interpolated into SQL text.

Universe semantics: every read is over the ACTIVE universe — a LEFT JOIN
from ``universe_constituents`` (status='active') to ``screener_metrics``.
Each filter requires its column IS NOT NULL by definition (a ticker that
cannot be ranked on a metric never matches a filter on it), so constituents
without a metrics row drop out as soon as any filter exists.
"""

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

import numpy as np
from sqlalchemy import (
    ColumnElement,
    CursorResult,
    Row,
    Select,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from app.models.screen import Screen, ScreenFilter
from app.models.screener_metrics import ScreenerMetrics
from app.models.universe import UniverseConstituent
from app.screener.catalog import MetricDef, get_metric

# Hard cap on GET /screener/screens — single-tenant, a bound not pagination.
LIST_HARD_CAP = 100

# Histogram bins for the build distribution (the study's screener uses a
# fixed-bin histogram behind the range slider).
HISTOGRAM_BINS = 40

# Hard cap on the CSV export — bounded output, no pagination.
CSV_HARD_CAP = 5000

# Results columns that are not catalog metrics.
BASE_SORT_COLUMNS = ("ticker", "name")


class DuplicateScreenNameError(Exception):
    """Raised when a screen name violates the UNIQUE constraint."""


class UnknownMetricCodeError(Exception):
    """Raised when a metric code is not in the catalog (whitelist breach)."""


class MetricDataUnavailableError(Exception):
    """Raised when a metric column has zero non-NULL rows in the snapshot."""


class FilterLike(Protocol):
    """Structural view of a filter — lets tests pass plain namespaces."""

    metric_code: str
    min_value: float | None
    max_value: float | None
    position: int


@dataclass(frozen=True)
class Distribution:
    """Histogram payload; counts_normalized is 0..1 (count / max count)."""

    bin_edges: list[float]
    counts: list[int]
    counts_normalized: list[float]


# ---------------------------------------------------------------------------
# Screen CRUD
# ---------------------------------------------------------------------------


async def create_screen(
    session: AsyncSession, name: str, owner_sub: str, org_id: str | None
) -> Screen:
    """Insert a screen; raise DuplicateScreenNameError on a name conflict."""
    screen = Screen(name=name, owner_sub=owner_sub, org_id=org_id, filters=[])
    session.add(screen)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateScreenNameError(f"A screen named {name!r} already exists.") from exc
    loaded = await get_screen(session, screen.id, owner_sub)
    if loaded is None:  # pragma: no cover
        raise RuntimeError(f"Screen {screen.id} vanished after commit.")
    return loaded


async def get_screen(
    session: AsyncSession, screen_id: int, owner_sub: str
) -> Screen | None:
    """Load one screen WITH its filters (explicit selectinload — lazy='raise')."""
    result = await session.execute(
        select(Screen)
        .options(selectinload(Screen.filters))
        .where(Screen.id == screen_id, Screen.owner_sub == owner_sub)
    )
    return result.scalar_one_or_none()


async def list_screens(session: AsyncSession, owner_sub: str) -> Sequence[Row]:
    """Rows of (id, name, filter_count, created_at, updated_at), id order, capped."""
    result = await session.execute(
        select(
            Screen.id,
            Screen.name,
            func.count(ScreenFilter.id).label("filter_count"),
            Screen.created_at,
            Screen.updated_at,
        )
        .outerjoin(ScreenFilter)
        .where(Screen.owner_sub == owner_sub)
        .group_by(Screen.id)
        .order_by(Screen.id)
        .limit(LIST_HARD_CAP)
    )
    return result.all()


async def rename_screen(
    session: AsyncSession, screen_id: int, owner_sub: str, name: str
) -> Screen | None:
    """Rename a screen; None when missing; DuplicateScreenNameError on conflict."""
    screen = await get_screen(session, screen_id, owner_sub)
    if screen is None:
        return None
    screen.name = name
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateScreenNameError(f"A screen named {name!r} already exists.") from exc
    # Re-select so the DB-computed updated_at is reflected in the response.
    return await get_screen(session, screen_id, owner_sub)


async def delete_screen(
    session: AsyncSession, screen_id: int, owner_sub: str
) -> bool:
    """Delete one screen; filters go with it via ON DELETE CASCADE."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(Screen).where(
                Screen.id == screen_id, Screen.owner_sub == owner_sub
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)


# ---------------------------------------------------------------------------
# Filter upsert / delete
# ---------------------------------------------------------------------------


async def upsert_filter(
    session: AsyncSession,
    screen_id: int,
    metric_code: str,
    min_value: float | None,
    max_value: float | None,
) -> None:
    """INSERT ... ON CONFLICT (screen_id, metric_code) DO UPDATE bounds.

    On insert, position = max(position)+1 within the screen (stable add
    order); on update the original position is preserved so re-tuning a
    bound never reorders the results columns. The route validates the screen
    exists and the metric code is in the catalog BEFORE calling in.
    """
    next_position = (
        select(func.coalesce(func.max(ScreenFilter.position) + 1, 0))
        .where(ScreenFilter.screen_id == screen_id)
        .scalar_subquery()
    )
    stmt = (
        pg_insert(ScreenFilter)
        .values(
            screen_id=screen_id,
            metric_code=metric_code,
            min_value=min_value,
            max_value=max_value,
            position=next_position,
        )
        .on_conflict_do_update(
            constraint="uq_screen_filters_screen_id_metric_code",
            set_={"min_value": min_value, "max_value": max_value},
        )
    )
    await session.execute(stmt)
    await session.commit()


async def delete_filter(session: AsyncSession, screen_id: int, metric_code: str) -> bool:
    """Delete one filter; False when no row matched."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(ScreenFilter).where(
                ScreenFilter.screen_id == screen_id,
                ScreenFilter.metric_code == metric_code,
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)


async def reorder_filters(
    session: AsyncSession, screen_id: int, metric_codes: Sequence[str]
) -> None:
    """Rewrite filter positions to match metric_codes order (0-based).

    The route has validated the screen exists and that metric_codes is exactly
    the set of the screen's current filter codes (no missing/extra/duplicate).
    position has no UNIQUE constraint, so a plain per-row UPDATE is safe.
    """
    for position, code in enumerate(metric_codes):
        await session.execute(
            update(ScreenFilter)
            .where(
                ScreenFilter.screen_id == screen_id,
                ScreenFilter.metric_code == code,
            )
            .values(position=position)
        )
    await session.commit()


# ---------------------------------------------------------------------------
# Whitelisted column resolution + filter predicates (pure — unit-tested)
# ---------------------------------------------------------------------------


def metric_column(code: str) -> InstrumentedAttribute[float | None]:
    """Resolve a metric code to its ScreenerMetrics column — THE whitelist gate.

    Raises UnknownMetricCodeError for anything outside the catalog, so a
    hostile code (e.g. an SQL-injection string) can never reach query text.
    """
    if get_metric(code) is None:
        raise UnknownMetricCodeError(f"Unknown metric code: {code!r}.")
    return cast(
        "InstrumentedAttribute[float | None]", getattr(ScreenerMetrics, code)
    )


def filter_conditions(filters: Sequence[FilterLike]) -> list[ColumnElement[bool]]:
    """SQL predicates for ALL filters: IS NOT NULL always, bounds when present.

    NULLs are excluded by definition for every filtered metric — a ticker
    that cannot be ranked on a metric never matches a filter on it, even
    when both bounds are null.
    """
    conditions: list[ColumnElement[bool]] = []
    for item in filters:
        column = metric_column(item.metric_code)
        conditions.append(column.is_not(None))
        if item.min_value is not None:
            conditions.append(column >= item.min_value)
        if item.max_value is not None:
            conditions.append(column <= item.max_value)
    return conditions


def _active_universe_select(*columns: Any) -> Select[Any]:
    """SELECT *columns* over active universe LEFT JOIN screener_metrics."""
    return (
        select(*columns)
        .select_from(UniverseConstituent)
        .outerjoin(ScreenerMetrics, ScreenerMetrics.ticker == UniverseConstituent.ticker)
        .where(UniverseConstituent.status == "active")
    )


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards in user search input (backslash escape char)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_condition(search: str) -> ColumnElement[bool]:
    """Case-insensitive ticker/name PREFIX match."""
    pattern = _escape_like(search) + "%"
    return or_(
        UniverseConstituent.ticker.ilike(pattern, escape="\\"),
        UniverseConstituent.name.ilike(pattern, escape="\\"),
    )


# ---------------------------------------------------------------------------
# Build: distribution + headline count
# ---------------------------------------------------------------------------


def build_histogram(values: Sequence[float], data_type: str) -> Distribution:
    """40-bin histogram; log-spaced edges for currency/int metrics when all > 0.

    Pure (unit-tested on synthetic data). Raises MetricDataUnavailableError
    on an empty input — the caller decides whether that is a 422 (build
    endpoint) or a null distribution (filter upsert response).
    """
    if not values:
        raise MetricDataUnavailableError(
            "metrics snapshot not computed yet — run compute_screener_metrics"
        )
    array = np.asarray(values, dtype=float)
    low = float(array.min())
    high = float(array.max())
    if data_type in ("currency", "int") and low > 0 and high > low:
        # The study's market-cap pattern: equal-ratio bins across magnitudes.
        edges = np.logspace(np.log10(low), np.log10(high), HISTOGRAM_BINS + 1)
        # Clamp the float endpoints so min/max values always fall inside.
        edges[0] = min(edges[0], low)
        edges[-1] = max(edges[-1], high)
    else:
        if high == low:  # degenerate single-value column — widen symmetrically
            low, high = low - 0.5, high + 0.5
        edges = np.linspace(low, high, HISTOGRAM_BINS + 1)
    counts, edges = np.histogram(array, bins=edges)
    peak = int(counts.max())
    normalized = counts / peak if peak > 0 else np.zeros_like(counts, dtype=float)
    return Distribution(
        bin_edges=[float(edge) for edge in edges],
        counts=[int(count) for count in counts],
        counts_normalized=[float(value) for value in normalized],
    )


async def select_metric_values(session: AsyncSession, code: str) -> list[float]:
    """All non-NULL values of one metric over the active universe.

    Bounded by construction: one float column x universe size (~5 000 rows).
    """
    column = metric_column(code)
    result = await session.execute(_active_universe_select(column).where(column.is_not(None)))
    return [float(value) for (value,) in result.all()]


async def count_metric_available(session: AsyncSession, code: str) -> int:
    """COUNT of non-NULL rows for *code* over the active universe.

    Lets callers distinguish "0 matches" from "no snapshot data" without
    triggering the MetricDataUnavailableError path.
    """
    column = metric_column(code)
    stmt = _active_universe_select(func.count()).where(column.is_not(None))
    return int(await session.scalar(stmt) or 0)


async def compute_distribution(session: AsyncSession, metric: MetricDef) -> Distribution:
    """Universe-wide histogram for one catalog metric."""
    values = await select_metric_values(session, metric.code)
    return build_histogram(values, metric.data_type)


async def count_matching(session: AsyncSession, filters: Sequence[FilterLike]) -> int:
    """Headline count: active-universe rows satisfying ALL filters."""
    stmt = _active_universe_select(func.count()).where(*filter_conditions(filters))
    return int(await session.scalar(stmt) or 0)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def result_columns(filters: Sequence[FilterLike]) -> list[tuple[str, str, str]]:
    """(code, name, data_type) triples: ticker + name + metrics in position order."""
    columns = [("ticker", "Ticker", "string"), ("name", "Name", "string")]
    for item in sorted(filters, key=lambda f: f.position):
        metric = get_metric(item.metric_code)
        if metric is None:  # persisted code outside the catalog — fail loud
            raise UnknownMetricCodeError(f"Unknown metric code: {item.metric_code!r}.")
        columns.append((metric.code, metric.name, metric.data_type))
    return columns


def build_results_select(
    filters: Sequence[FilterLike],
    *,
    sort: str,
    direction: str,
    search: str | None,
    limit: int,
    offset: int,
) -> Select[Any]:
    """The dynamic-but-whitelisted results SELECT (pure — unit-tested).

    ``sort`` must be 'ticker', 'name' or one of the screen's metric codes —
    the route validates and 422s first; this re-asserts (fail loud).
    """
    metric_codes = [item.metric_code for item in sorted(filters, key=lambda f: f.position)]
    sortable = {
        "ticker": UniverseConstituent.ticker,
        "name": UniverseConstituent.name,
        **{code: metric_column(code) for code in metric_codes},
    }
    if sort not in sortable:
        raise UnknownMetricCodeError(
            f"Unsortable column {sort!r}: expected one of {sorted(sortable)}."
        )
    sort_column = sortable[sort]
    order = sort_column.desc() if direction == "desc" else sort_column.asc()
    stmt = _active_universe_select(
        UniverseConstituent.ticker,
        UniverseConstituent.name,
        *(metric_column(code) for code in metric_codes),
    ).where(*filter_conditions(filters))
    if search:
        stmt = stmt.where(_search_condition(search))
    return (
        stmt.order_by(order.nulls_last(), UniverseConstituent.ticker)
        .limit(limit)
        .offset(offset)
    )


def build_count_select(filters: Sequence[FilterLike], *, search: str | None) -> Select[Any]:
    """COUNT over the same filtered (and searched) set as the results SELECT."""
    stmt = _active_universe_select(func.count()).where(*filter_conditions(filters))
    if search:
        stmt = stmt.where(_search_condition(search))
    return stmt


async def fetch_results(
    session: AsyncSession,
    filters: Sequence[FilterLike],
    *,
    sort: str,
    direction: str,
    search: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, str | float | None]], int]:
    """One results page as row dicts (keyed by column code) + the total count."""
    metric_codes = [item.metric_code for item in sorted(filters, key=lambda f: f.position)]
    result = await session.execute(
        build_results_select(
            filters, sort=sort, direction=direction, search=search, limit=limit, offset=offset
        )
    )
    rows: list[dict[str, str | float | None]] = []
    for row in result.all():
        ticker, name, *metric_values = row
        record: dict[str, str | float | None] = {"ticker": ticker, "name": name}
        for code, value in zip(metric_codes, metric_values, strict=True):
            record[code] = float(value) if value is not None else None
        rows.append(record)
    total = int(await session.scalar(build_count_select(filters, search=search)) or 0)
    return rows, total


def _csv_cell(value: str | float | None, data_type: str) -> str:
    """Format one CSV cell — stable decimal notation, no scientific notation.

    None  → empty string (null/unavailable).
    str   → passed through (ticker, name).
    float → formatted by data_type:
        currency  → two decimal places  ("2500000000000.00")
        int       → zero decimal places ("1234567")
        percent/float/other → six decimal places ("0.000010")
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if data_type == "currency":
        return f"{value:.2f}"
    if data_type == "int":
        return f"{value:.0f}"
    # "percent", "float", or any future type: six decimal places — no scientific
    # notation for very small values (e.g. roe=1e-05 → "0.000010").
    return f"{value:.6f}"


def render_csv(
    columns: Sequence[tuple[str, str, str]],
    rows: Sequence[dict[str, str | float | None]],
) -> str:
    """Render the result set as CSV (header = column codes; None → empty cell).

    Numeric cells are formatted by data_type via ``_csv_cell`` to avoid
    scientific notation (e.g. market_cap 2.5e12 → "2500000000000.00").
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    codes_and_types = [(code, data_type) for code, _name, data_type in columns]
    writer.writerow([code for code, _dt in codes_and_types])
    for row in rows:
        writer.writerow(
            [_csv_cell(row.get(code), data_type) for code, data_type in codes_and_types]
        )
    return buffer.getvalue()
