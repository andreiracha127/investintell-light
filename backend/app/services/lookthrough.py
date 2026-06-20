"""Look-through consumption service (Frente C, ADENDO §6 do doc de research).

The recursive look-through is computed by the ``nport_lookthrough`` worker in
the datalake repo and materialized in the TimescaleDB Cloud
(``nport_lookthrough_exposures`` + ``nport_lookthrough_summary``). This module
READS those tables and does portfolio-level weighted consolidation for the
official totals. Portfolio chart drilldown can additionally build a bounded
asset-class → fund series → final holding tree from raw N-PORT rows;
that path is capped and lazy-loaded by the frontend so it does not block the
main exposure payload.

Semantics inherited from the worker (do not reinterpret here):
- pct values are percentage points of the SERIES NAV, sign preserved;
  Σpct > 100 (derivatives/leverage) is legitimate and never renormalized.
- ``oldest_report_date`` is the chain staleness (oldest N-PORT report used).
- residual buckets (nondecomposable funds, derivatives gross/net,
  unidentified synthetic keys) are explicit in the summary.

Portfolio sunburst drilldowns are the exception: the chart is a composition of
portfolio value, so each expanded fund's visible holdings are scaled to that
fund position's portfolio weight before final holdings are accumulated.
"""

import datetime as dt
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fund import Fund, FundListRow

DIMENSIONS = ("issuer", "asset_class", "sector", "currency")
SYNTHETIC_PREFIXES = ("IS:", "LE:", "H:", "CIK:")
UNIDENTIFIED_PREFIXES = ("LE:", "H:", "CIK:")
MAX_TREE_DEPTH = 8
MAX_TREE_LEAVES = 180
MAX_TREE_HOLDINGS_PER_SERIES = 40


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


@dataclass(frozen=True)
class SeriesTaxonomy:
    """Display taxonomy for a fund series in the exposure drilldown."""

    label: str
    asset_class: str | None
    strategy_label: str | None


@dataclass(frozen=True)
class DirectHoldingInput:
    """Direct portfolio position that should appear as a final holding leaf."""

    ticker: str
    label: str | None
    weight_pct: float
    asset_class: str | None
    strategy_label: str | None


@dataclass(frozen=True)
class DirectHolding:
    """Resolved direct security leaf for portfolio exposure drilldown."""

    key: str
    label: str
    value_pct: float
    asset_class: str | None
    strategy_label: str | None
    leaf_kind: str = "security"


@dataclass(frozen=True)
class ExposureTreeNode:
    """Flat parent-linked hierarchy for portfolio look-through drilldown."""

    id: str
    parent_id: str | None
    key: str
    label: str
    kind: str
    value_pct: float


# ---------------------------------------------------------------------------
# Local-DB lookups (funds catalog)
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


async def get_fund_labels_by_series(
    session: AsyncSession, series_ids: list[str]
) -> dict[str, str]:
    """series_id → display name from the same MV-backed catalog as /funds."""
    if not series_ids:
        return {}
    result = await session.execute(
        select(FundListRow.series_id, FundListRow.name)
        .where(FundListRow.series_id.in_(series_ids))
        .order_by(
            FundListRow.series_id,
            FundListRow.aum_usd.desc().nulls_last(),
            FundListRow.instrument_id,
        )
    )
    labels: dict[str, str] = {}
    for series_id, name in result.all():
        labels.setdefault(series_id, name)
    return labels


async def get_fund_taxonomy_by_series(
    session: AsyncSession, series_ids: list[str]
) -> dict[str, SeriesTaxonomy]:
    """series_id → taxonomy from the same MV-backed catalog as /funds."""
    if not series_ids:
        return {}
    result = await session.execute(
        select(
            FundListRow.series_id,
            FundListRow.name,
            FundListRow.asset_class,
            FundListRow.strategy_label,
        )
        .where(FundListRow.series_id.in_(series_ids))
        .order_by(
            FundListRow.series_id,
            FundListRow.aum_usd.desc().nulls_last(),
            FundListRow.instrument_id,
        )
    )
    taxonomy: dict[str, SeriesTaxonomy] = {}
    for series_id, name, asset_class, strategy_label in result.all():
        taxonomy.setdefault(
            series_id,
            SeriesTaxonomy(
                label=name,
                asset_class=asset_class,
                strategy_label=strategy_label,
            ),
        )
    return taxonomy


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

_EXPOSURES_BATCH_SQL = text("""
    WITH requested AS (
        SELECT *
        FROM unnest(
            CAST(:series_ids AS text[]),
            CAST(:report_dates AS date[])
        ) AS t(series_id, report_date)
    )
    SELECT e.series_id, e.dimension, e.key, e.label, e.direct_pct, e.indirect_pct
    FROM nport_lookthrough_exposures e
    JOIN requested r
      ON r.series_id = e.series_id
     AND r.report_date = e.report_date
    WHERE (CAST(:dimension AS text) IS NULL OR e.dimension = CAST(:dimension AS text))
""")

_HOLDINGS_TREE_BATCH_SQL = text("""
    WITH requested AS (
        SELECT *
        FROM unnest(
            CAST(:series_ids AS text[]),
            CAST(:as_of_dates AS date[])
        ) AS t(series_id, as_of_date)
    )
    SELECT h.series_id, h.report_date, h.cusip, h.isin, h.issuer_name,
           h.asset_class, h.sector, h.currency, h.pct_of_nav
    FROM requested r
    JOIN LATERAL (
        SELECT report_date
        FROM sec_nport_holdings
        WHERE series_id = r.series_id
          AND report_date <= r.as_of_date
        ORDER BY report_date DESC
        LIMIT 1
    ) latest ON TRUE
    JOIN LATERAL (
        SELECT series_id, report_date, cusip, isin, issuer_name, asset_class,
               sector, currency, pct_of_nav
        FROM sec_nport_holdings
        WHERE series_id = r.series_id
          AND report_date = latest.report_date
          AND pct_of_nav IS NOT NULL
        ORDER BY abs(pct_of_nav) DESC NULLS LAST
        LIMIT CAST(:limit_rows AS integer)
    ) h ON TRUE
""")

_CHILD_SERIES_MAP_SQL = text("""
    WITH t2s AS (
        SELECT upper(ticker) AS ticker, series_id
        FROM sec_fund_classes
        WHERE ticker IS NOT NULL AND series_id IS NOT NULL
        UNION
        SELECT upper(ticker), series_id
        FROM sec_etfs
        WHERE ticker IS NOT NULL AND series_id IS NOT NULL
        UNION
        -- SEC company_tickers_mf: authoritative ticker -> series_id for funds/
        -- ETFs absent from the N-CEN sec_etfs slice (e.g. WisdomTree DTD/DEM/DXJ
        -- held inside a fund-of-funds). The CUSIP -> ticker edge already lives
        -- in sec_cusip_ticker_map; this closes CUSIP -> ticker -> series.
        SELECT upper(ticker), series_id
        FROM sec_company_tickers_mf
        WHERE ticker IS NOT NULL AND series_id IS NOT NULL
    ),
    raw AS (
        SELECT 'cusip' AS kind, m.cusip AS ident, t.series_id
        FROM sec_cusip_ticker_map m
        JOIN t2s t ON upper(m.ticker) = t.ticker
        WHERE m.cusip = ANY(CAST(:cusips AS text[]))
        UNION ALL
        SELECT 'cusip', cusip_9, sec_series_id
        FROM instrument_identity
        WHERE cusip_9 = ANY(CAST(:cusips AS text[]))
          AND sec_series_id IS NOT NULL
        UNION ALL
        SELECT 'isin', isin, sec_series_id
        FROM instrument_identity
        WHERE isin = ANY(CAST(:isins AS text[]))
          AND sec_series_id IS NOT NULL
        UNION ALL
        SELECT 'isin', isin, series_id
        FROM sec_etfs
        WHERE isin = ANY(CAST(:isins AS text[]))
          AND series_id IS NOT NULL
        UNION ALL
        SELECT 'isin', isin, attributes->>'series_id'
        FROM instruments_universe
        WHERE isin = ANY(CAST(:isins AS text[]))
          AND attributes->>'series_id' IS NOT NULL
    )
    SELECT kind, ident, min(series_id) AS series_id,
           count(DISTINCT series_id) AS series_count
    FROM raw
    WHERE ident IS NOT NULL AND series_id IS NOT NULL
    GROUP BY kind, ident
""")

_DIRECT_HOLDINGS_SQL = text("""
    WITH requested AS (
        SELECT *
        FROM unnest(
            CAST(:tickers AS text[]),
            CAST(:labels AS text[]),
            CAST(:weights AS double precision[]),
            CAST(:asset_classes AS text[]),
            CAST(:strategies AS text[])
        ) AS t(ticker, label, weight_pct, asset_class, strategy_label)
    )
    SELECT r.ticker,
           r.label,
           r.weight_pct,
           r.asset_class,
           COALESCE(NULLIF(btrim(r.strategy_label), ''),
                    NULLIF(btrim(m.gics_sector), '')) AS strategy_label,
           COALESCE(NULLIF(btrim(m.cusip), ''),
                    NULLIF(btrim(ii.cusip_9), ''),
                    r.ticker) AS holding_key
    FROM requested r
    LEFT JOIN LATERAL (
        SELECT cusip, gics_sector
        FROM sec_cusip_ticker_map
        WHERE upper(ticker) = upper(r.ticker)
        ORDER BY (cusip IS NULL), cusip
        LIMIT 1
    ) m ON TRUE
    LEFT JOIN LATERAL (
        SELECT cusip_9
        FROM instrument_identity
        WHERE upper(ticker) = upper(r.ticker)
          AND cusip_9 IS NOT NULL
        ORDER BY cusip_9
        LIMIT 1
    ) ii ON TRUE
""")


def _summary_from_row(row: Any) -> LookthroughSummary:
    def f(value: Any) -> float | None:
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


def _embedded_cusip9(isin: str | None) -> str | None:
    """US ISINs embed the 9-char CUSIP at positions 3..11."""
    if isin and len(isin) == 12 and isin.startswith("US"):
        return isin[2:11]
    return None


def _cusip_key(cusip: str | None, isin: str | None) -> str:
    cusip = (cusip or "").strip().upper()
    isin = (isin or "").strip().upper()
    if cusip.startswith("IS:"):
        isin = isin or cusip[3:]
        cusip = ""
    if cusip and not cusip.startswith(SYNTHETIC_PREFIXES):
        return cusip
    if isin:
        embedded = _embedded_cusip9(isin)
        if embedded:
            return embedded
    return "UNKNOWN"


def _title_asset_class(code: str) -> str:
    labels = {
        "cash": "Cash",
        "equity": "Equity",
        "fixed_income": "Fixed Income",
        "alternatives": "Alternatives",
    }
    return labels.get(code, "Alternatives")


def _fallback_taxonomy_from_nport(asset_class: str | None) -> tuple[str, str]:
    raw = (asset_class or "").strip().upper()
    if raw in {"EC", "EP"}:
        return "equity", "Equity"
    if raw in {"DBT", "ABS", "ABS-MBS", "ABS-O", "CMBS", "MBS", "UST", "CORP"}:
        return "fixed_income", "Fixed Income"
    if raw in {"RA", "RE"}:
        return "alternatives", "Real Assets"
    return "alternatives", "Unclassified"


def _normalize_asset_class(value: str | None) -> str | None:
    normalized = (value or "").strip().lower().replace(" ", "_")
    if normalized == "real_assets":
        return "alternatives"
    if normalized in {"cash", "equity", "fixed_income", "alternatives"}:
        return normalized
    return None


def _series_taxonomy(
    series_id: str,
    row_asset_class: str | None,
    taxonomy_by_series: dict[str, SeriesTaxonomy],
    fallback_label: str | None = None,
) -> tuple[str, str, str]:
    taxonomy = taxonomy_by_series.get(series_id)
    asset_code = (taxonomy.asset_class if taxonomy else None) or ""
    if asset_code:
        normalized = _normalize_asset_class(asset_code) or "alternatives"
        return (
            normalized,
            _title_asset_class(normalized),
            taxonomy.label if taxonomy else (fallback_label or series_id),
        )

    fallback_asset, _fallback_strategy = _fallback_taxonomy_from_nport(row_asset_class)
    return (
        fallback_asset,
        _title_asset_class(fallback_asset),
        taxonomy.label if taxonomy else (fallback_label or series_id),
    )


def _direct_taxonomy(asset_class: str | None) -> tuple[str, str]:
    normalized = _normalize_asset_class(asset_class) or "equity"
    return normalized, _title_asset_class(normalized)


def _child_lookup_key(row: Any) -> tuple[str | None, str | None]:
    """Return possible CUSIP-9 / ISIN identifiers for child-fund matching."""
    cusip = (getattr(row, "cusip", None) or "").strip().upper()
    isin = (getattr(row, "isin", None) or "").strip().upper()
    if cusip.startswith(UNIDENTIFIED_PREFIXES):
        return None, None
    if cusip.startswith("IS:"):
        isin = isin or cusip[3:]
        cusip = ""
    embedded = _embedded_cusip9(isin) if isin else None
    return (cusip or embedded), (isin or None)


def _positive_pct_of_nav(row: Any) -> float:
    pct = float(row.pct_of_nav) if row.pct_of_nav is not None else 0.0
    return max(pct, 0.0)


def _normalized_holding_pct(raw_pct: float, total_positive_pct: float) -> float:
    if total_positive_pct <= 0.0:
        return 0.0
    return 100.0 * raw_pct / total_positive_pct


def _match_child_series(
    row: Any, child_by_cusip: dict[str, str], child_by_isin: dict[str, str]
) -> str | None:
    cusip, isin = _child_lookup_key(row)
    if cusip and (series_id := child_by_cusip.get(cusip)):
        return series_id
    if isin and (series_id := child_by_isin.get(isin)):
        return series_id
    return None


def _node_id(kind: str, *parts: str) -> str:
    cleaned = [
        part.strip().replace("|", "/")
        for part in parts
        if part is not None and part.strip()
    ]
    return "|".join([kind, *cleaned])


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
    if not summaries:
        return {}

    exposures = (
        await datalake.execute(
            _EXPOSURES_BATCH_SQL,
            {
                "series_ids": [row.series_id for row in summaries],
                "report_dates": [row.report_date for row in summaries],
                "dimension": dimension,
            },
        )
    ).all()
    exposures_by_series: dict[str, list[Any]] = {}
    for row in exposures:
        exposures_by_series.setdefault(row.series_id, []).append(row)

    out: dict[str, SeriesLookthrough] = {}
    for row in summaries:
        series_exposures = exposures_by_series.get(row.series_id, [])
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
                for e in series_exposures
            ],
            summary=_summary_from_row(row),
        )
    return out


async def _fetch_tree_holdings(
    datalake: AsyncSession,
    requests: list[tuple[str, dt.date]],
    *,
    limit_rows: int = MAX_TREE_HOLDINGS_PER_SERIES,
) -> dict[tuple[str, dt.date], list[Any]]:
    if not requests:
        return {}
    unique = sorted(set(requests))
    rows = (
        await datalake.execute(
            _HOLDINGS_TREE_BATCH_SQL,
            {
                "series_ids": [series_id for series_id, _ in unique],
                "as_of_dates": [as_of_date for _, as_of_date in unique],
                "limit_rows": limit_rows,
            },
        )
    ).all()
    out: dict[tuple[str, dt.date], list[Any]] = {key: [] for key in unique}
    requested_by_series = {series_id: as_of_date for series_id, as_of_date in unique}
    for row in rows:
        as_of = requested_by_series.get(row.series_id)
        if as_of is not None:
            out.setdefault((row.series_id, as_of), []).append(row)
    return out


async def _resolve_child_series(
    datalake: AsyncSession, rows: list[Any]
) -> tuple[dict[str, str], dict[str, str]]:
    cusips: set[str] = set()
    isins: set[str] = set()
    for row in rows:
        cusip, isin = _child_lookup_key(row)
        if cusip:
            cusips.add(cusip)
        if isin:
            isins.add(isin)
    if not cusips and not isins:
        return {}, {}
    result = (
        await datalake.execute(
            _CHILD_SERIES_MAP_SQL,
            {"cusips": sorted(cusips), "isins": sorted(isins)},
        )
    ).all()
    child_by_cusip: dict[str, str] = {}
    child_by_isin: dict[str, str] = {}
    for row in result:
        # A registrant/trust identifier can fan out to many SEC series. In that
        # case it is not a held fund position and must remain a final holding.
        if int(getattr(row, "series_count", 1) or 0) != 1:
            continue
        if row.kind == "cusip":
            child_by_cusip[row.ident] = row.series_id
        elif row.kind == "isin":
            child_by_isin[row.ident] = row.series_id
    return child_by_cusip, child_by_isin


async def resolve_direct_holdings(
    datalake: AsyncSession, inputs: list[DirectHoldingInput]
) -> list[DirectHolding]:
    """Resolve direct stock positions to holding leaves, preferring CUSIP keys."""
    visible = [item for item in inputs if item.weight_pct > 0]
    if not visible:
        return []
    result = await datalake.execute(
        _DIRECT_HOLDINGS_SQL,
        {
            "tickers": [item.ticker for item in visible],
            "labels": [item.label or item.ticker for item in visible],
            "weights": [item.weight_pct for item in visible],
            "asset_classes": [item.asset_class for item in visible],
            "strategies": [item.strategy_label for item in visible],
        },
    )
    holdings: list[DirectHolding] = []
    for row in result.all():
        holding_key = (row.holding_key or row.ticker).strip().upper()
        holdings.append(
            DirectHolding(
                key=holding_key,
                label=row.label or row.ticker,
                value_pct=float(row.weight_pct),
                asset_class=row.asset_class,
                strategy_label=row.strategy_label,
            )
        )
    return holdings


def _build_tree_nodes(
    leaf_totals: dict[tuple[str, str | None, str], dict[str, Any]],
    *,
    max_leaves: int,
) -> list[ExposureTreeNode]:
    visible = sorted(
        (
            data
            for data in leaf_totals.values()
            if float(data["value_pct"]) > 0.0
        ),
        key=lambda item: -float(item["value_pct"]),
    )
    visible_leaves = visible[:max_leaves]
    omitted = visible[max_leaves:]
    if omitted:
        other_by_asset: dict[str, dict[str, Any]] = {}
        for data in omitted:
            asset_key = data["asset_key"]
            other = other_by_asset.setdefault(
                asset_key,
                {
                    "asset_key": asset_key,
                    "asset_label": data["asset_label"],
                    "series_key": None,
                    "series_label": None,
                    "leaf_key": "__OTHER__",
                    "leaf_label": "Other holdings",
                    "leaf_kind": "security",
                    "value_pct": 0.0,
                },
            )
            other["value_pct"] += float(data["value_pct"])
        visible_leaves.extend(other_by_asset.values())

    asset_totals: dict[str, float] = {}
    series_totals: dict[tuple[str, str], float] = {}
    for data in visible_leaves:
        value = float(data["value_pct"])
        asset_key = str(data["asset_key"])
        asset_totals[asset_key] = asset_totals.get(asset_key, 0.0) + value
        series_key = data.get("series_key")
        if series_key is not None:
            series_total_key = (asset_key, str(series_key))
            series_totals[series_total_key] = (
                series_totals.get(series_total_key, 0.0) + value
            )

    nodes: list[ExposureTreeNode] = []
    asset_labels = {
        data["asset_key"]: data["asset_label"] for data in visible_leaves
    }
    for asset_key, value in sorted(asset_totals.items(), key=lambda item: -item[1]):
        nodes.append(
            ExposureTreeNode(
                id=_node_id("asset", asset_key),
                parent_id=None,
                key=asset_key,
                label=asset_labels.get(asset_key) or asset_key,
                kind="asset_class",
                value_pct=value,
            )
        )

    series_labels = {
        (data["asset_key"], data["series_key"]): data["series_label"]
        for data in visible_leaves
        if data.get("series_key") is not None
    }
    for (asset_key, series_key), value in sorted(
        series_totals.items(), key=lambda item: (item[0][0], -item[1])
    ):
        nodes.append(
            ExposureTreeNode(
                id=_node_id("series", asset_key, series_key),
                parent_id=_node_id("asset", asset_key),
                key=series_key,
                label=series_labels.get((asset_key, series_key)) or series_key,
                kind="series",
                value_pct=value,
            )
        )

    for data in sorted(
        visible_leaves,
        key=lambda item: (
            item["asset_key"],
            item.get("series_key") or "",
            -float(item["value_pct"]),
        ),
    ):
        series_key = data.get("series_key")
        leaf_kind = str(data.get("leaf_kind") or "cusip")
        leaf_key = str(data["leaf_key"])
        parent_id = (
            _node_id(
                "series",
                data["asset_key"],
                series_key,
            )
            if series_key is not None
            else _node_id("asset", data["asset_key"])
        )
        node_id_parts = [data["asset_key"]]
        if series_key is not None:
            node_id_parts.append(series_key)
        node_id_parts.append(leaf_key)
        nodes.append(
            ExposureTreeNode(
                id=_node_id(leaf_kind, *node_id_parts),
                parent_id=parent_id,
                key=leaf_key,
                label=data["leaf_label"] or leaf_key,
                kind=leaf_kind,
                value_pct=float(data["value_pct"]),
            )
        )
    return nodes


async def build_portfolio_exposure_tree(
    datalake: AsyncSession,
    weighted: list[tuple[float, SeriesLookthrough]],
    *,
    series_taxonomy: dict[str, SeriesTaxonomy] | None = None,
    taxonomy_loader: (
        Callable[[list[str]], Awaitable[dict[str, SeriesTaxonomy]]] | None
    ) = None,
    direct_holdings: list[DirectHolding] | None = None,
    max_depth: int = MAX_TREE_DEPTH,
    max_leaves: int = MAX_TREE_LEAVES,
    holdings_per_series: int = MAX_TREE_HOLDINGS_PER_SERIES,
) -> list[ExposureTreeNode]:
    """Build asset-class → fund series → final holding nodes.

    Official totals still come from ``nport_lookthrough_exposures``. This tree
    is a bounded visualization aid: it uses raw N-PORT rows in batches, follows
    fund-of-fund edges when identifiable, and caps the CUSIP tail.
    """
    taxonomy_by_series = dict(series_taxonomy or {})

    async def ensure_taxonomy(series_ids: list[str]) -> None:
        missing = sorted({sid for sid in series_ids if sid not in taxonomy_by_series})
        if missing and taxonomy_loader is not None:
            taxonomy_by_series.update(await taxonomy_loader(missing))

    states: list[tuple[str, dt.date, float, frozenset[str]]] = [
        (data.series_id, data.report_date, weight, frozenset({data.series_id}))
        for weight, data in weighted
        if weight > 0
    ]
    leaf_totals: dict[tuple[str, str | None, str], dict[str, Any]] = {}

    for holding in direct_holdings or []:
        asset_key, asset_label = _direct_taxonomy(holding.asset_class)
        leaf_key = holding.key.strip().upper() or holding.label
        key: tuple[str, str | None, str] = (
            asset_key,
            None,
            leaf_key,
        )
        entry = leaf_totals.setdefault(
            key,
            {
                "asset_key": asset_key,
                "asset_label": asset_label,
                "series_key": None,
                "series_label": None,
                "leaf_key": leaf_key,
                "leaf_label": holding.label,
                "leaf_kind": holding.leaf_kind,
                "value_pct": 0.0,
            },
        )
        entry["value_pct"] += holding.value_pct

    for depth in range(max_depth + 1):
        if not states:
            break
        await ensure_taxonomy([series_id for series_id, *_ in states])
        holdings_by_series = await _fetch_tree_holdings(
            datalake,
            [(series_id, as_of) for series_id, as_of, _, _ in states],
            limit_rows=holdings_per_series,
        )
        current_rows = [
            row
            for rows in holdings_by_series.values()
            for row in rows
        ]
        child_by_cusip, child_by_isin = await _resolve_child_series(
            datalake, current_rows
        )
        next_states: list[tuple[str, dt.date, float, frozenset[str]]] = []
        for series_id, as_of, weight, ancestors in states:
            holding_rows = holdings_by_series.get((series_id, as_of), [])
            total_positive_pct = sum(_positive_pct_of_nav(row) for row in holding_rows)
            if total_positive_pct <= 0.0:
                continue
            for row in holding_rows:
                raw_pct = _positive_pct_of_nav(row)
                if raw_pct <= 0.0:
                    continue
                normalized_pct = _normalized_holding_pct(raw_pct, total_positive_pct)
                contribution = weight * normalized_pct
                child = _match_child_series(row, child_by_cusip, child_by_isin)
                if child and child not in ancestors and depth < max_depth:
                    next_states.append(
                        (
                            child,
                            row.report_date,
                            weight * normalized_pct / 100.0,
                            ancestors | {child},
                        )
                    )
                    continue

                (
                    asset_key,
                    asset_label,
                    series_label,
                ) = _series_taxonomy(
                    series_id,
                    row.asset_class,
                    taxonomy_by_series,
                )
                series_key = series_id
                cusip_key = _cusip_key(row.cusip, row.isin)
                key = (asset_key, series_key, cusip_key)
                entry = leaf_totals.setdefault(
                    key,
                    {
                        "asset_key": asset_key,
                        "asset_label": asset_label,
                        "series_key": series_key,
                        "series_label": series_label,
                        "leaf_key": cusip_key,
                        "leaf_label": row.issuer_name or cusip_key,
                        "leaf_kind": "cusip",
                        "value_pct": 0.0,
                    },
                )
                entry["value_pct"] += contribution
                if row.issuer_name and entry["leaf_label"] == entry["leaf_key"]:
                    entry["leaf_label"] = row.issuer_name
        states = next_states

    return _build_tree_nodes(leaf_totals, max_leaves=max_leaves)


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
