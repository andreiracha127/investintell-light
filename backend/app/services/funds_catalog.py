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
import json
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy import ColumnElement, Select, case, column, func, or_, select, table, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models.fund import (
    Fund,
    FundBenchmarkCandidate,
    FundClass,
    FundHolding,
    FundListRow,
    FundRiskLatest,
)

# Canonical strategy label for funds the mother-DB cascade could not classify.
# (Was sourced from the now-retired app.sync.funds; this service is its sole
# runtime consumer — used by the strategy filter below.)
UNCLASSIFIED_LABEL = "Unclassified"

# Hard cap on the CSV export — bounded output, no pagination (screener parity).
CSV_HARD_CAP = 5000

# NAV embedded in GET /funds/{id} is intentionally a bounded profile preview.
# Chart-depth consumers must use /funds/{id}/timeseries?range=... instead
# (P3), where MAX reads the full available NAV history through the CAGGs.
NAV_WINDOW_DAYS = 365 * 2
NAV_TARGET_POINTS = 260

# Top-50 cap of the N-PORT source (defense in depth — the sync stores <= 50).
HOLDINGS_CAP = 50

# Catalog display guard: NAV glitches can surface absurd annual returns while
# deeper source repair is pending. Keep extreme but plausible leveraged funds
# (e.g. < 10x) and suppress impossible values from ranking/list payloads.
MAX_CATALOG_RETURN_1Y_ABS = 10.0


# Investment-adviser crosswalk (no ORM models in the Light; referenced ad-hoc).
# ``sec_fund_adviser`` is the N-CEN-sourced map series_id -> PRIMARY adviser
# (name + CRD), populated by scripts/ncen_adviser_ingest.py. ``sec_managers``
# carries the canonical Form ADV firm name, joined on the adviser CRD. Both live
# in the same database as funds_list_mv.
_fund_adviser_tbl = table(
    "sec_fund_adviser",
    column("series_id"),
    column("adviser_name"),
    column("adviser_crd"),
)
_managers_tbl = table(
    "sec_managers", column("crd_number"), column("firm_name")
)


def _build_manager_name_expr() -> ColumnElement[Any]:
    """Correlated scalar subquery resolving a fund's INVESTMENT ADVISER name.

    Resolves the fund's primary adviser from ``sec_fund_adviser`` (the N-CEN
    crosswalk, keyed by ``series_id``) and prefers the canonical Form ADV firm
    name from ``sec_managers`` (joined on the adviser CRD), falling back to the
    N-CEN adviser name. Returns NULL when no adviser is resolved (front-end shows
    an em dash) — NEVER the registrant/trust name, which was the bug this
    replaced (e.g. "iSHARES TRUST" instead of "BLACKROCK FUND ADVISORS").

    Selectable for display AND usable in ORDER BY, so the Manager column sorts
    server-side like the rest (series_id and crd are indexed).
    """
    return (
        select(
            func.coalesce(
                _managers_tbl.c.firm_name, _fund_adviser_tbl.c.adviser_name
            )
        )
        .select_from(
            # Equi-join on the (numeric) adviser CRD: synthetic registrant rows
            # in sec_managers (crd_number like 'cik_%') never match, so the
            # registrant/trust name can no longer leak into the Manager column.
            _fund_adviser_tbl.outerjoin(
                _managers_tbl,
                _managers_tbl.c.crd_number == _fund_adviser_tbl.c.adviser_crd,
            )
        )
        .where(_fund_adviser_tbl.c.series_id == FundListRow.series_id)
        .limit(1)
        .correlate(FundListRow)
        .scalar_subquery()
        .label("manager_name")
    )


_MANAGER_NAME: ColumnElement[Any] = _build_manager_name_expr()

_CATALOG_RETURN_1Y: ColumnElement[Any] = case(
    (
        or_(
            FundListRow.return_1y.is_(None),
            func.abs(FundListRow.return_1y) > MAX_CATALOG_RETURN_1Y_ABS,
        ),
        None,
    ),
    else_=FundListRow.return_1y,
).label("return_1y")


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
LIST_SORT_WHITELIST: dict[str, ColumnElement[Any]] = {
    **{name: getattr(FundListRow, name) for name in _FUND_SORT_FIELDS},
    # The funds_list_mv materialized view does not (yet) carry the Tier-3 EVT /
    # GARCH risk columns added to FundRiskLatest, so restrict the list sort to
    # the risk fields the MV actually materializes. When the MV is extended to
    # populate those columns, they become list-sortable automatically.
    **{
        name: getattr(FundListRow, name)
        for name in _RISK_SORT_FIELDS
        if hasattr(FundListRow, name)
    },
    "return_1y": _CATALOG_RETURN_1Y,
    # Resolved per query (correlated subquery, not a stored column) — sortable
    # all the same, so the Manager column behaves like the rest.
    "manager_name": _MANAGER_NAME,
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


def _list_sort_column(code: str) -> ColumnElement[Any]:
    """Resolve a list sort code against the materialized /funds projection."""
    column = LIST_SORT_WHITELIST.get(code)
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

    Funds without a stored AUM are excluded from catalog-style universes
    UNCONDITIONALLY. Missing AUM is a quality hole in the upstream NAV/risk
    lineage and can make return metrics explode.

    'Unclassified' funds are excluded from the listing UNCONDITIONALLY
    (decisão do dono, 2026-06-12): the residual ~1% the reclassification
    pipeline could not label has no strategy/peer context and pollutes the
    screen. Their profile pages stay reachable by direct id (the profile
    fetch does not go through these conditions).
    """
    conditions: list[ColumnElement[bool]] = [
        Fund.strategy_label.is_distinct_from(UNCLASSIFIED_LABEL),
        Fund.aum_usd.is_not(None),
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


def _list_filter_conditions(filters: FundFilters) -> list[ColumnElement[bool]]:
    """SQL predicates for GET /funds over the materialized list projection."""
    conditions: list[ColumnElement[bool]] = [
        FundListRow.strategy_label.is_distinct_from(UNCLASSIFIED_LABEL),
        FundListRow.aum_usd.is_not(None),
    ]
    if filters.search:
        pattern = f"%{_escape_like(filters.search)}%"
        conditions.append(
            or_(
                FundListRow.ticker.ilike(pattern, escape="\\"),
                FundListRow.name.ilike(pattern, escape="\\"),
            )
        )
    if filters.fund_type is not None:
        conditions.append(FundListRow.fund_type == filters.fund_type)
    if filters.strategy_label is not None:
        strategy_pattern = f"%{_escape_like(filters.strategy_label)}%"
        conditions.append(
            FundListRow.strategy_label.ilike(strategy_pattern, escape="\\")
        )
    if filters.asset_class is not None:
        conditions.append(FundListRow.asset_class == filters.asset_class)
    if filters.expense_ratio_max is not None:
        conditions.append(FundListRow.expense_ratio <= filters.expense_ratio_max)
    if filters.aum_min is not None:
        conditions.append(FundListRow.aum_usd >= filters.aum_min)
    if filters.sharpe_1y_min is not None:
        conditions.append(FundListRow.sharpe_1y >= filters.sharpe_1y_min)
    if filters.volatility_1y_max is not None:
        conditions.append(FundListRow.volatility_1y <= filters.volatility_1y_max)
    if filters.return_1y_min is not None:
        conditions.append(_CATALOG_RETURN_1Y >= filters.return_1y_min)
    if filters.max_drawdown_1y_min is not None:
        conditions.append(FundListRow.max_drawdown_1y >= filters.max_drawdown_1y_min)
    return conditions


# Item columns served on every list row (funds identity + headline metrics).
# `manager_name` is a correlated subquery (not a stored MV column) — see
# `_build_manager_name_expr` above.
_ITEM_COLUMNS: tuple[
    tuple[str, ColumnElement[Any] | InstrumentedAttribute[Any]], ...
] = (
    ("instrument_id", FundListRow.instrument_id),
    ("series_id", FundListRow.series_id),
    ("ticker", FundListRow.ticker),
    ("name", FundListRow.name),
    ("fund_type", FundListRow.fund_type),
    ("strategy_label", FundListRow.strategy_label),
    ("asset_class", FundListRow.asset_class),
    ("is_index", FundListRow.is_index),
    ("expense_ratio", FundListRow.expense_ratio),
    ("aum_usd", FundListRow.aum_usd),
    ("return_1y", _CATALOG_RETURN_1Y),
    ("volatility_1y", FundListRow.volatility_1y),
    ("sharpe_1y", FundListRow.sharpe_1y),
    ("max_drawdown_1y", FundListRow.max_drawdown_1y),
    ("peer_sharpe_pctl", FundListRow.peer_sharpe_pctl),
    ("manager_score", FundListRow.manager_score),
    ("elite_flag", FundListRow.elite_flag),
    ("manager_name", _MANAGER_NAME),
)


def _base_select(*columns: Any) -> Select[Any]:
    """SELECT *columns* over the materialized /funds list projection."""
    return select(*columns).select_from(FundListRow)


def build_funds_select(
    filters: FundFilters,
    *,
    sort: str,
    direction: str,
    limit: int,
    offset: int,
) -> Select[Any]:
    """The materialized, whitelisted funds list SELECT (pure — unit-tested)."""
    column = _list_sort_column(sort)
    order = column.desc() if direction == "desc" else column.asc()
    return (
        _base_select(*(col for _name, col in _ITEM_COLUMNS))
        .where(*_list_filter_conditions(filters))
        .order_by(
            order.nulls_last(),
            FundListRow.ticker.nulls_last(),
            FundListRow.instrument_id,
        )
        .limit(limit)
        .offset(offset)
    )


def build_count_select(filters: FundFilters) -> Select[Any]:
    """COUNT over the same filtered set as the list SELECT."""
    return _base_select(func.count()).where(*_list_filter_conditions(filters))


# ---------------------------------------------------------------------------
# List + staleness reads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Staleness:
    """Global max of the per-fund staleness markers (None on an empty table)."""

    synced_at: dt.datetime | None
    source_calc_date: dt.date | None
    source_nav_max_date: dt.date | None


_STALENESS_CACHE_TTL_SECONDS = 300.0
_staleness_cache: tuple[float, Staleness] | None = None


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
        ).add_columns(func.count().over().label("_total"))
    )
    names = [name for name, _col in _ITEM_COLUMNS]
    records = result.all()
    rows = [dict(zip(names, tuple(record)[:-1], strict=True)) for record in records]
    total = (
        int(tuple(records[0])[-1])
        if records
        else int(await session.scalar(build_count_select(filters)) or 0)
    )
    return rows, total


async def fetch_strategies(session: AsyncSession) -> list[str]:
    """Distinct, alphabetically sorted strategy labels across the universe.

    Backs the Strategy filter dropdown — the whole closed set, not just the
    labels on the loaded page.
    """
    result = await session.execute(
        select(FundListRow.strategy_label)
        .where(*_list_filter_conditions(FundFilters()))
        .distinct()
        .order_by(FundListRow.strategy_label)
    )
    return [row[0] for row in result.all() if row[0]]


async def fetch_staleness(session: AsyncSession) -> Staleness:
    """Global data-freshness markers, derived from the dynamic sources.

    The /funds list path reads the materialized projection, which already
    carries the global NAV max date. Cache this tiny aggregate briefly so each
    page/filter miss does not re-read catalog metadata.
    """
    global _staleness_cache

    now = time.monotonic()
    if _staleness_cache is not None:
        expires_at, cached = _staleness_cache
        if now < expires_at:
            return cached

    fund_count, source_calc_date, source_nav_max_date = (
        await session.execute(
            select(
                func.count(),
                func.max(FundListRow.calc_date),
                func.max(FundListRow.source_nav_max_date),
            ).select_from(FundListRow)
        )
    ).one()
    fund_count = int(fund_count or 0)
    has_universe = fund_count > 0 and (
        source_calc_date is not None or source_nav_max_date is not None
    )
    staleness = Staleness(
        synced_at=dt.datetime.now(dt.UTC) if has_universe else None,
        source_calc_date=cast("dt.date | None", source_calc_date),
        source_nav_max_date=cast("dt.date | None", source_nav_max_date),
    )
    _staleness_cache = (now + _STALENESS_CACHE_TTL_SECONDS, staleness)
    return staleness


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
    ("manager_score", "Score", "float"),
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
    benchmark: FundBenchmarkCandidate | None
    risk: FundRiskLatest | None
    nav: list[tuple[dt.date, float | None]]
    holdings: list[FundHolding]
    holdings_report_date: dt.date | None
    holdings_pct_of_nav_total: float | None
    # Share classes (F8.6b), expense_ratio asc NULLS LAST. NOTE: any class
    # is priced with the SERIES NAV as a proxy (the source prices only the
    # representative class).
    classes: list[FundClass] = field(default_factory=list)


def _decode_json_value(value: Any) -> Any:
    """Return JSON/JSONB values as Python objects across DB drivers."""
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


def _as_namespace(value: Any) -> SimpleNamespace | None:
    decoded = _decode_json_value(value)
    if decoded is None:
        return None
    return SimpleNamespace(**decoded)


def _profile_nav_points(value: Any) -> list[tuple[dt.date, float | None]]:
    decoded = _decode_json_value(value) or []
    points: list[tuple[dt.date, float | None]] = []
    for item in decoded:
        raw_date = item["date"]
        nav_date = (
            dt.date.fromisoformat(raw_date)
            if isinstance(raw_date, str)
            else cast(dt.date, raw_date)
        )
        raw_nav = item.get("nav")
        points.append((nav_date, float(raw_nav) if raw_nav is not None else None))
    return points


async def fetch_fund_profile(
    session: AsyncSession, instrument_id: uuid.UUID
) -> FundProfile | None:
    """Fund + full risk snapshot + bounded preview NAV + latest holdings.

    The NAV list is for lightweight profile context only. Long-history charts
    use the range-aware timeseries route so profile payload size stays bounded.
    Returns None when the instrument is not in the local universe.
    """
    row = (
        await session.execute(
            text(
                """
                WITH fund AS MATERIALIZED (
                    SELECT *
                    FROM funds_profile_mv
                    WHERE instrument_id = :instrument_id
                ),
                risk AS MATERIALIZED (
                    SELECT *
                    FROM fund_risk_latest_mv
                    WHERE instrument_id = :instrument_id
                ),
                max_nav AS MATERIALIZED (
                    SELECT max(nav_date) AS max_nav_date
                    FROM nav_timeseries
                    WHERE instrument_id = :instrument_id
                ),
                nav_rows AS (
                    SELECT n.nav_date, n.nav
                    FROM nav_timeseries n
                    CROSS JOIN max_nav m
                    WHERE n.instrument_id = :instrument_id
                      AND m.max_nav_date IS NOT NULL
                      AND n.nav_date >= m.max_nav_date - (:nav_window_days * INTERVAL '1 day')
                    ORDER BY n.nav_date
                )
                SELECT
                    (SELECT to_jsonb(f) FROM fund f) AS fund,
                    (
                        SELECT to_jsonb(b)
                        FROM fund_benchmark_candidates_mv b
                        JOIN fund f ON f.series_id = b.series_id
                        LIMIT 1
                    ) AS benchmark,
                    (SELECT to_jsonb(r) FROM risk r) AS risk,
                    (SELECT max_nav_date FROM max_nav) AS max_nav_date,
                    (
                        SELECT jsonb_agg(
                            jsonb_build_object('date', nav_date, 'nav', nav)
                            ORDER BY nav_date
                        )
                        FROM nav_rows
                    ) AS nav
                """
            ),
            {
                "instrument_id": str(instrument_id),
                "nav_window_days": NAV_WINDOW_DAYS,
            },
        )
    ).mappings().one()

    fund = _as_namespace(row["fund"])
    if fund is None:
        return None
    benchmark = _as_namespace(row["benchmark"])
    risk = _as_namespace(row["risk"])
    nav = decimate_nav(_profile_nav_points(row["nav"]))

    details = (
        await session.execute(
            text(
                """
                WITH holdings_limited AS MATERIALIZED (
                    SELECT h.*
                    FROM fund_top_holdings_mv h
                    WHERE h.series_id = :series_id
                      AND h.rank <= :holdings_cap
                    ORDER BY h.rank
                ),
                class_rows AS (
                    SELECT c.*
                    FROM fund_classes_latest_mv c
                    WHERE c.series_id = :series_id
                    ORDER BY c.expense_ratio ASC NULLS LAST, c.ticker
                )
                SELECT
                    (SELECT max(report_date) FROM holdings_limited) AS holdings_report_date,
                    (
                        SELECT jsonb_agg(to_jsonb(h) ORDER BY h.rank)
                        FROM holdings_limited h
                    ) AS holdings,
                    (
                        SELECT sum(h.pct_of_nav)
                        FROM holdings_limited h
                        WHERE h.pct_of_nav IS NOT NULL
                    ) AS holdings_pct_of_nav_total,
                    (
                        SELECT jsonb_agg(
                            to_jsonb(c)
                            ORDER BY c.expense_ratio ASC NULLS LAST, c.ticker
                        )
                        FROM class_rows c
                    ) AS classes
                """
            ),
            {
                "series_id": fund.series_id,
                "holdings_cap": HOLDINGS_CAP,
            },
        )
    ).mappings().one()

    latest_report = cast("dt.date | None", details["holdings_report_date"])
    holdings = _decode_json_value(details["holdings"]) or []
    pct_total = (
        float(details["holdings_pct_of_nav_total"])
        if details["holdings_pct_of_nav_total"] is not None
        else None
    )
    classes = _decode_json_value(details["classes"]) or []

    # funds_profile_mv has no sync markers; derive per-fund staleness from
    # dynamic sources (risk MV calc_date + latest NAV date).
    # Attached on the instance so the route serializes them unchanged (Task 2.4
    # finalizes the staleness source).
    fund.synced_at = dt.datetime.now(dt.UTC)
    fund.source_calc_date = risk.calc_date if risk is not None else None
    fund.source_nav_max_date = row["max_nav_date"]

    return FundProfile(
        fund=cast(Fund, fund),
        benchmark=cast("FundBenchmarkCandidate | None", benchmark),
        risk=cast("FundRiskLatest | None", risk),
        nav=nav,
        holdings=cast("list[FundHolding]", holdings),
        holdings_report_date=latest_report,
        holdings_pct_of_nav_total=pct_total,
        classes=cast("list[FundClass]", classes),
    )


# Defense in depth: the FundFilters fields ARE the route's query params —
# keep them in sync (test asserts this) so a new filter cannot be forgotten.
FILTER_FIELD_NAMES = tuple(field.name for field in fields(FundFilters))
