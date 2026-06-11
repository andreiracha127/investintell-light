"""Mother-DB fund sync (F8.1): identity + risk snapshot + NAV window + holdings.

Pipeline (one run = one `run_sync()` call, normally via scripts/sync_funds.py):

1. Materialize the eligible instrument_id list in ONE mother-DB query
   (dispatch F8 §3 F8.1-2): instrument_identity rows with a sec_series_id,
   present in the latest fund_risk_metrics calc (max(calc_date) per
   instrument >= 2026-01-01), with nav_timeseries history spanning at least
   2 years and fresh within the last 30 days.
2. Fetch classification profiles (sec_registered_funds / sec_etfs /
   sec_money_market_funds by series_id), instruments_universe
   (name/currency/asset_class) and the latest reclassification-stage label
   per instrument, and assemble `funds` rows with the strategy-label cascade
   (registered → etf → mmf → stage → specific peer label → 'Unclassified')
   and fund_type derivation (etf → mmf → mutual_fund).
3. Fetch the latest fund_risk_metrics row per instrument (exact
   (instrument_id, calc_date) pairs from step 1) → `fund_risk_latest`.
4. Fetch nav_timeseries in batches of instrument_ids with a rolling window
   (today - 2 years - 30 days) → `fund_nav`; the latest non-NULL aum_usd
   backfills funds.aum_usd where monthly_avg_net_assets was missing.
5. Fetch the latest sec_nport_holdings report per series, rank by
   pct_of_nav desc → `fund_holdings` (source is top-50 truncated).

ABSOLUTE RULES honoured here (same as app/sync/mother_db.py):
- The mother DB is READ-ONLY and accessed only by app/sync modules, never
  in any request path.
- The mother-DB DSN is NEVER logged or printed.
- All local writes are idempotent upserts (ON CONFLICT DO UPDATE); the
  holdings refresh deletes stale reports for the synced series first, in
  the same transaction.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import asyncpg
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.chunks import chunked
from app.models.fund import Fund, FundHolding, FundNav, FundRiskLatest
from app.sync.mother_db import connect_mother_db

logger = logging.getLogger(__name__)

# --- Eligibility criterion constants (dispatch F8 §3 F8.1-2) ---------------

# A fund must appear in the "latest calc" of fund_risk_metrics: its
# max(calc_date) must be on/after this date (the risk pipeline runs in 2026).
RISK_CALC_CUTOFF = dt.date(2026, 1, 1)
# Required NAV history span: first NAV at least this many days old...
NAV_MIN_HISTORY_DAYS = 730  # 2 years
# ...and last NAV at most this many days old.
NAV_MAX_STALENESS_DAYS = 30
# Local NAV window: 2 years + 30 days back from today.
NAV_WINDOW_DAYS = NAV_MIN_HISTORY_DAYS + NAV_MAX_STALENESS_DAYS

# The N-PORT source keeps at most the top-50 holdings per fund.
MAX_HOLDINGS_PER_SERIES = 50

UNCLASSIFIED_LABEL = "Unclassified"

# --- Batch / chunk sizes ----------------------------------------------------

# Mother-DB fetch batches.
RISK_FETCH_BATCH = 1000
NAV_FETCH_BATCH = 200  # per task spec: batches of instrument_ids
HOLDINGS_FETCH_BATCH = 500

# Local upsert chunks (asyncpg caps binds at 32 767 params/query):
# funds 19 params/row, risk 33, nav 5, holdings 11.
FUNDS_UPSERT_CHUNK = 1000  # 19 000 params
RISK_UPSERT_CHUNK = 900  # 29 700 params
NAV_UPSERT_CHUNK = 5000  # 25 000 params
HOLDINGS_UPSERT_CHUNK = 2000  # 22 000 params

# Hard safety valve: abort (loudly) instead of inserting an absurd NAV volume.
NAV_ROW_LIMIT = 10_000_000

# --- Mother-DB SQL (READ-ONLY SELECTs; never any other verb) ---------------

ELIGIBLE_FUNDS_SQL = """
WITH latest_risk AS (
    SELECT instrument_id, max(calc_date) AS calc_date
    FROM fund_risk_metrics
    GROUP BY instrument_id
    HAVING max(calc_date) >= $1
),
nav_span AS (
    SELECT instrument_id,
           min(nav_date) AS min_nav_date,
           max(nav_date) AS max_nav_date
    FROM nav_timeseries
    GROUP BY instrument_id
)
SELECT ii.instrument_id,
       ii.sec_series_id,
       ii.ticker,
       ii.isin,
       ii.cusip_9,
       ii.lei,
       lr.calc_date AS source_calc_date,
       ns.max_nav_date AS source_nav_max_date
FROM instrument_identity ii
JOIN latest_risk lr ON lr.instrument_id = ii.instrument_id
JOIN nav_span ns ON ns.instrument_id = ii.instrument_id
WHERE ii.sec_series_id IS NOT NULL
  AND ns.min_nav_date <= $2
  AND ns.max_nav_date >= $3
ORDER BY ii.instrument_id
"""

UNIVERSE_SQL = """
SELECT instrument_id, name, currency, asset_class
FROM instruments_universe
WHERE instrument_id = ANY($1::uuid[])
"""

# Latest proposed strategy label per instrument from the mother DB's
# reclassification pipeline (source_table='instruments_universe' keys the
# stage by instrument_id; verified coverage: 4,502/4,558 eligible funds).
STAGE_LABELS_SQL = """
SELECT DISTINCT ON (source_pk) source_pk, proposed_strategy_label
FROM strategy_reclassification_stage
WHERE source_table = 'instruments_universe'
  AND source_pk = ANY($1::text[])
  AND proposed_strategy_label IS NOT NULL
ORDER BY source_pk, classified_at DESC
"""

REGISTERED_FUNDS_SQL = """
SELECT series_id, fund_name, strategy_label, is_index, management_fee,
       net_operating_expenses, monthly_avg_net_assets, primary_benchmark,
       inception_date, domicile, currency
FROM sec_registered_funds
WHERE series_id = ANY($1::text[])
"""

ETFS_SQL = """
SELECT series_id, fund_name, strategy_label, is_index, index_tracked,
       management_fee, net_operating_expenses, monthly_avg_net_assets,
       inception_date, domicile, currency
FROM sec_etfs
WHERE series_id = ANY($1::text[])
"""

MMFS_SQL = """
SELECT series_id, fund_name, strategy_label, mmf_category, domicile, currency
FROM sec_money_market_funds
WHERE series_id = ANY($1::text[])
"""

# Expense ratio from the latest prospectus filing per series — the N-CEN
# profile tables only cover ~730 eligible series, while prospectus stats
# cover 4,532/4,558 (verified).  Within the latest filing the MINIMUM across
# share classes is kept (cheapest class; values are fractions, 0.0069=0.69%).
PROSPECTUS_FEES_SQL = """
WITH latest AS (
    SELECT series_id, max(filing_date) AS filing_date
    FROM sec_fund_prospectus_stats
    WHERE series_id = ANY($1::text[])
    GROUP BY series_id
)
SELECT s.series_id,
       min(coalesce(s.net_expense_ratio_pct, s.expense_ratio_pct,
                    s.management_fee_pct)) AS expense_ratio
FROM sec_fund_prospectus_stats s
JOIN latest l ON l.series_id = s.series_id AND l.filing_date = s.filing_date
WHERE coalesce(s.net_expense_ratio_pct, s.expense_ratio_pct,
               s.management_fee_pct) IS NOT NULL
GROUP BY s.series_id
"""

# AUM fallback from sec_fund_classes (covers 1,980/4,558 eligible series vs
# 729 with monthly_avg_net_assets).  net_assets is SERIES-level, repeated on
# every share-class row (verified: AGTHX shows $329B on all 22 classes), so
# take max at the latest reported period — never sum across classes.
CLASSES_AUM_SQL = """
WITH latest AS (
    SELECT series_id, max(xbrl_period_end) AS period_end
    FROM sec_fund_classes
    WHERE series_id = ANY($1::text[]) AND net_assets IS NOT NULL
    GROUP BY series_id
)
SELECT c.series_id, max(c.net_assets) AS aum_usd
FROM sec_fund_classes c
JOIN latest l ON l.series_id = c.series_id
            AND c.xbrl_period_end IS NOT DISTINCT FROM l.period_end
WHERE c.net_assets IS NOT NULL
GROUP BY c.series_id
"""

# Metric columns copied verbatim into fund_risk_latest (model order; the
# tests keep the model, migration and this tuple in lockstep).
RISK_METRIC_COLUMNS: tuple[str, ...] = (
    "return_1m",
    "return_3m",
    "return_1y",
    "return_3y_ann",
    "return_5y_ann",
    "volatility_1y",
    "max_drawdown_1y",
    "max_drawdown_3y",
    "sharpe_1y",
    "sharpe_3y",
    "sortino_1y",
    "calmar_ratio_3y",
    "alpha_1y",
    "beta_1y",
    "information_ratio_1y",
    "tracking_error_1y",
    "var_95_1m",
    "cvar_95_1m",
    "cvar_95_12m",
    "cvar_99_evt",
    "peer_strategy_label",
    "peer_sharpe_pctl",
    "peer_sortino_pctl",
    "peer_return_pctl",
    "peer_drawdown_pctl",
    "peer_count",
    "manager_score",
    "elite_flag",
    "downside_capture_1y",
    "upside_capture_1y",
    "equity_correlation_252d",
)

RISK_LATEST_SQL = f"""
SELECT instrument_id, calc_date, {", ".join(RISK_METRIC_COLUMNS)}
FROM fund_risk_metrics
WHERE (instrument_id, calc_date) IN (SELECT * FROM unnest($1::uuid[], $2::date[]))
"""

NAV_SQL = """
SELECT instrument_id, nav_date, nav, return_1d, aum_usd
FROM nav_timeseries
WHERE instrument_id = ANY($1::uuid[])
  AND nav_date >= $2
ORDER BY instrument_id, nav_date
"""

HOLDINGS_SQL = """
SELECT h.series_id, h.report_date, h.cusip, h.isin, h.issuer_name,
       h.asset_class, h.sector, h.market_value, h.pct_of_nav
FROM sec_nport_holdings h
JOIN (
    SELECT series_id, max(report_date) AS report_date
    FROM sec_nport_holdings
    WHERE series_id = ANY($1::text[])
    GROUP BY series_id
) latest ON latest.series_id = h.series_id
        AND latest.report_date = h.report_date
"""


@dataclass
class FundSyncReport:
    """Counts for one fund-sync run (printed by the CLI, returned to callers)."""

    eligible_funds: int = 0
    funds_upserted: int = 0
    fund_type_counts: dict[str, int] = field(default_factory=dict)
    unclassified_funds: int = 0
    risk_rows_upserted: int = 0
    risk_duplicates_merged: int = 0
    nav_rows_upserted: int = 0
    aum_filled_from_nav: int = 0
    holdings_series: int = 0
    holdings_rows_upserted: int = 0
    dry_run: bool = False

    def lines(self) -> list[str]:
        type_summary = ", ".join(
            f"{name}={count}" for name, count in sorted(self.fund_type_counts.items())
        )
        return [
            f"Eligible funds (criterion F8.1-2):  {self.eligible_funds}",
            f"funds upserted:                     {self.funds_upserted}",
            f"  fund_type breakdown:              {type_summary or '-'}",
            f"  strategy 'Unclassified':          {self.unclassified_funds}",
            f"fund_risk_latest upserted:          {self.risk_rows_upserted}",
            f"  duplicate source rows merged:     {self.risk_duplicates_merged}",
            f"fund_nav rows upserted:             {self.nav_rows_upserted}",
            f"  funds aum_usd filled from NAV:    {self.aum_filled_from_nav}",
            f"fund_holdings series synced:        {self.holdings_series}",
            f"fund_holdings rows upserted:        {self.holdings_rows_upserted}",
            f"Dry run (no local writes):          {self.dry_run}",
        ]


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# ---------------------------------------------------------------------------


def eligibility_params(today: dt.date) -> tuple[dt.date, dt.date, dt.date]:
    """($1, $2, $3) for ELIGIBLE_FUNDS_SQL: risk cutoff, min-history bound,
    freshness bound."""
    return (
        RISK_CALC_CUTOFF,
        today - dt.timedelta(days=NAV_MIN_HISTORY_DAYS),
        today - dt.timedelta(days=NAV_MAX_STALENESS_DAYS),
    )


def nav_window_start(today: dt.date) -> dt.date:
    """First nav_date kept locally: today - 2 years - 30 days."""
    return today - dt.timedelta(days=NAV_WINDOW_DAYS)


def _first(*values: Any) -> Any:
    """First non-NULL, non-empty-string value (or None)."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _get(row: Mapping[str, Any] | None, key: str) -> Any:
    return None if row is None else row.get(key)


# peer_strategy_label values that are instrument-type buckets, not actual
# strategies — they must not win the cascade over 'Unclassified' visibility.
GENERIC_PEER_LABELS = frozenset({"mutual_fund", "etf", "mmf", "ucits"})


def cascade_strategy_label(
    registered: Mapping[str, Any] | None,
    etf: Mapping[str, Any] | None,
    mmf: Mapping[str, Any] | None,
    stage_label: str | None = None,
    peer_label: str | None = None,
) -> str:
    """Classification cascade (dispatch F8 §3 F8.1-2, extended after the
    source diagnosis — only 730/4,558 eligible series appear in the three
    N-CEN/N-MFP tables): sec_registered_funds → sec_etfs →
    sec_money_market_funds → reclassification stage (latest proposed label
    per instrument) → specific peer_strategy_label → 'Unclassified'.
    """
    if peer_label is not None and peer_label.strip().lower() in GENERIC_PEER_LABELS:
        peer_label = None
    label = _first(
        _get(registered, "strategy_label"),
        _get(etf, "strategy_label"),
        _get(mmf, "strategy_label"),
        stage_label,
        peer_label,
    )
    return str(label).strip() if label is not None else UNCLASSIFIED_LABEL


def derive_fund_type(*, in_registered: bool, in_etf: bool, in_mmf: bool) -> str:
    """'etf' | 'mmf' by N-CEN/N-MFP table presence, else 'mutual_fund' —
    every eligible instrument is instruments_universe.instrument_type='fund'
    (verified 4,558/4,558), so 'unknown' would only hide information."""
    if in_etf:
        return "etf"
    if in_mmf:
        return "mmf"
    return "mutual_fund"


def derive_expense_ratio(
    registered: Mapping[str, Any] | None,
    etf: Mapping[str, Any] | None,
    prospectus_fee: Decimal | None = None,
) -> Decimal | None:
    """net_operating_expenses preferred (registered → etf), then the latest
    prospectus net expense ratio (cheapest share class — the wide-coverage
    source), fallback management_fee (registered → etf)."""
    value = _first(
        _get(registered, "net_operating_expenses"),
        _get(etf, "net_operating_expenses"),
        prospectus_fee,
        _get(registered, "management_fee"),
        _get(etf, "management_fee"),
    )
    return value  # type: ignore[no-any-return]


def build_fund_row(
    identity: Mapping[str, Any],
    universe: Mapping[str, Any] | None,
    registered: Mapping[str, Any] | None,
    etf: Mapping[str, Any] | None,
    mmf: Mapping[str, Any] | None,
    synced_at: dt.datetime,
    stage_label: str | None = None,
    peer_label: str | None = None,
    prospectus_fee: Decimal | None = None,
    classes_aum: Decimal | None = None,
) -> dict[str, Any]:
    """Assemble one `funds` row from the mother-DB source rows.

    *identity* is one ELIGIBLE_FUNDS_SQL record; the profile rows may each be
    None.  aum_usd here is monthly_avg_net_assets only — the NAV fallback is
    applied later by the orchestrator (it needs the fetched NAV window).
    """
    series_id = str(identity["sec_series_id"])
    name = _first(
        _get(registered, "fund_name"),
        _get(etf, "fund_name"),
        _get(mmf, "fund_name"),
        _get(universe, "name"),
        series_id,
    )
    return {
        "instrument_id": identity["instrument_id"],
        "series_id": series_id,
        "ticker": _first(identity["ticker"], _get(registered, "ticker"), _get(etf, "ticker")),
        "isin": identity["isin"],
        "cusip": identity["cusip_9"],
        "lei": identity["lei"],
        "name": str(name),
        "fund_type": derive_fund_type(
            in_registered=registered is not None,
            in_etf=etf is not None,
            in_mmf=mmf is not None,
        ),
        "strategy_label": cascade_strategy_label(
            registered, etf, mmf, stage_label=stage_label, peer_label=peer_label
        ),
        "asset_class": _get(universe, "asset_class"),
        "is_index": _first(_get(registered, "is_index"), _get(etf, "is_index")),
        "expense_ratio": derive_expense_ratio(registered, etf, prospectus_fee),
        "aum_usd": _first(
            _get(registered, "monthly_avg_net_assets"),
            _get(etf, "monthly_avg_net_assets"),
            classes_aum,
        ),
        # ETFs without an N-CEN benchmark fall back to the tracked index.
        "primary_benchmark": _first(
            _get(registered, "primary_benchmark"), _get(etf, "index_tracked")
        ),
        "inception_date": _first(
            _get(registered, "inception_date"), _get(etf, "inception_date")
        ),
        "domicile": _first(
            _get(registered, "domicile"), _get(etf, "domicile"), _get(mmf, "domicile")
        ),
        "currency": _first(
            _get(registered, "currency"),
            _get(etf, "currency"),
            _get(mmf, "currency"),
            _get(universe, "currency"),
        ),
        "synced_at": synced_at,
        "source_calc_date": identity["source_calc_date"],
        "source_nav_max_date": identity["source_nav_max_date"],
    }


def index_profiles_by_series(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """series_id → profile row.  If the source lists several rows per series
    (per-class duplicates), prefer the first row that carries a
    strategy_label so the cascade does not lose a known classification."""
    by_series: dict[str, dict[str, Any]] = {}
    for row in rows:
        series_id = str(row["series_id"])
        existing = by_series.get(series_id)
        if existing is None or (
            existing.get("strategy_label") is None and row.get("strategy_label") is not None
        ):
            by_series[series_id] = dict(row)
    return by_series


def rank_holdings(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Turn raw latest-report holdings into ranked `fund_holdings` rows.

    Within each (series_id, report_date): order by pct_of_nav desc (NULL
    last), tie-break market_value desc (NULL last) then cusip; assign
    1-based ranks; keep at most MAX_HOLDINGS_PER_SERIES rows.
    """
    by_series: dict[tuple[str, dt.date], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (str(row["series_id"]), row["report_date"])
        by_series.setdefault(key, []).append(row)

    def sort_key(row: Mapping[str, Any]) -> tuple[int, Decimal, int, Decimal, str]:
        pct = row.get("pct_of_nav")
        mv = row.get("market_value")
        return (
            0 if pct is not None else 1,
            -Decimal(pct) if pct is not None else Decimal(0),
            0 if mv is not None else 1,
            -Decimal(mv) if mv is not None else Decimal(0),
            str(row.get("cusip") or ""),
        )

    ranked: list[dict[str, Any]] = []
    for (series_id, report_date), holdings in sorted(by_series.items()):
        ordered = sorted(holdings, key=sort_key)[:MAX_HOLDINGS_PER_SERIES]
        for rank, row in enumerate(ordered, start=1):
            ranked.append(
                {
                    "series_id": series_id,
                    "report_date": report_date,
                    "rank": rank,
                    "issuer_name": row.get("issuer_name"),
                    "cusip": row.get("cusip"),
                    "isin": row.get("isin"),
                    "asset_class": row.get("asset_class"),
                    "sector": row.get("sector"),
                    "market_value": row.get("market_value"),
                    "pct_of_nav": row.get("pct_of_nav"),
                    "is_top50_truncated": True,
                }
            )
    return ranked


def merge_risk_duplicates(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Collapse duplicate fund_risk_metrics rows per instrument_id.

    The mother table has NO primary key and the latest calc_date carries two
    rows for ~3k instruments (two pipeline passes: one peer-enriched with
    peer_*/elite_flag, one with information_ratio_1y).  Deterministic merge:
    the peer-labeled row is primary (its values win conflicts), NULL fields
    are filled from the remaining rows.  Returns (merged_rows,
    duplicate_instrument_count).
    """
    by_instrument: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        by_instrument.setdefault(row["instrument_id"], []).append(dict(row))

    merged: list[dict[str, Any]] = []
    duplicates = 0
    for variants in by_instrument.values():
        if len(variants) > 1:
            duplicates += 1
            # Peer-labeled row first; stringified row as a stable tiebreaker.
            variants.sort(
                key=lambda r: (r.get("peer_strategy_label") is None, str(sorted(r.items())))
            )
        primary = variants[0]
        for other in variants[1:]:
            for key, value in other.items():
                if primary.get(key) is None:
                    primary[key] = value
        merged.append(primary)
    return merged, duplicates


def latest_aum_by_instrument(
    nav_rows: Sequence[Mapping[str, Any]],
) -> dict[uuid.UUID, Decimal]:
    """instrument_id → aum_usd at the latest nav_date carrying a non-NULL
    aum_usd (used as the funds.aum_usd fallback)."""
    best: dict[uuid.UUID, tuple[dt.date, Decimal]] = {}
    for row in nav_rows:
        aum = row.get("aum_usd")
        if aum is None:
            continue
        instrument_id = row["instrument_id"]
        nav_date = row["nav_date"]
        current = best.get(instrument_id)
        if current is None or nav_date > current[0]:
            best[instrument_id] = (nav_date, aum)
    return {instrument_id: aum for instrument_id, (_, aum) in best.items()}


# ---------------------------------------------------------------------------
# Statement builders (compiled-SQL-tested)
# ---------------------------------------------------------------------------

_FUND_MUTABLE_COLUMNS = (
    "series_id",
    "ticker",
    "isin",
    "cusip",
    "lei",
    "name",
    "fund_type",
    "strategy_label",
    "asset_class",
    "is_index",
    "expense_ratio",
    "aum_usd",
    "primary_benchmark",
    "inception_date",
    "domicile",
    "currency",
    "synced_at",
    "source_calc_date",
    "source_nav_max_date",
)

_NAV_MUTABLE_COLUMNS = ("nav", "return_1d", "aum_usd")

_HOLDING_MUTABLE_COLUMNS = (
    "issuer_name",
    "cusip",
    "isin",
    "asset_class",
    "sector",
    "market_value",
    "pct_of_nav",
    "is_top50_truncated",
)


def _upsert(
    model: type[Fund] | type[FundRiskLatest] | type[FundNav] | type[FundHolding],
    rows: list[dict[str, Any]],
    conflict_cols: list[str],
    update_cols: tuple[str, ...],
) -> PgInsert:
    if not rows:
        raise ValueError(f"upsert for {model.__tablename__} requires at least one row")
    stmt = pg_insert(model).values(rows)
    return stmt.on_conflict_do_update(
        index_elements=conflict_cols,
        set_={col: getattr(stmt.excluded, col) for col in update_cols},
    )


def build_funds_upsert(rows: list[dict[str, Any]]) -> PgInsert:
    return _upsert(Fund, rows, ["instrument_id"], _FUND_MUTABLE_COLUMNS)


def build_risk_upsert(rows: list[dict[str, Any]]) -> PgInsert:
    return _upsert(
        FundRiskLatest, rows, ["instrument_id"], ("calc_date", *RISK_METRIC_COLUMNS)
    )


def build_nav_upsert(rows: list[dict[str, Any]]) -> PgInsert:
    return _upsert(FundNav, rows, ["instrument_id", "nav_date"], _NAV_MUTABLE_COLUMNS)


def build_holdings_upsert(rows: list[dict[str, Any]]) -> PgInsert:
    return _upsert(
        FundHolding,
        rows,
        ["series_id", "report_date", "rank"],
        _HOLDING_MUTABLE_COLUMNS,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_sync(
    *,
    limit: int | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
    connect_mother: Callable[[], Awaitable[asyncpg.Connection]] = connect_mother_db,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FundSyncReport:
    """One full fund-sync run.  See the module docstring for the pipeline.

    Idempotent and resumable: every local write is an upsert and NAV /
    holdings batches commit independently, so a re-run only refreshes.
    With dry_run=True only the eligibility list is computed (no profile /
    NAV / holdings fetches, no local writes).
    """
    report = FundSyncReport(dry_run=dry_run)
    now = dt.datetime.now(dt.UTC)
    run_date = today or now.date()

    if session_factory is None and not dry_run:
        from app.core.db import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    conn = await connect_mother()
    try:
        # Step 1 — eligible instruments (single query, dispatch F8.1-2).
        eligible = list(await conn.fetch(ELIGIBLE_FUNDS_SQL, *eligibility_params(run_date)))
        if limit is not None:
            eligible = eligible[:limit]
        report.eligible_funds = len(eligible)
        logger.info("Eligible funds: %d", report.eligible_funds)
        if dry_run or not eligible:
            return report
        assert session_factory is not None  # narrowed above

        instrument_ids: list[uuid.UUID] = [r["instrument_id"] for r in eligible]
        series_ids = sorted({str(r["sec_series_id"]) for r in eligible})

        # Step 2 — profiles + names.
        universe_by_id = {
            r["instrument_id"]: dict(r)
            for r in await conn.fetch(UNIVERSE_SQL, instrument_ids)
        }
        registered = index_profiles_by_series(
            list(await conn.fetch(REGISTERED_FUNDS_SQL, series_ids))
        )
        etfs = index_profiles_by_series(list(await conn.fetch(ETFS_SQL, series_ids)))
        mmfs = index_profiles_by_series(list(await conn.fetch(MMFS_SQL, series_ids)))
        stage_labels = {
            str(r["source_pk"]): str(r["proposed_strategy_label"])
            for r in await conn.fetch(
                STAGE_LABELS_SQL, [str(i) for i in instrument_ids]
            )
        }
        prospectus_fees = {
            str(r["series_id"]): r["expense_ratio"]
            for r in await conn.fetch(PROSPECTUS_FEES_SQL, series_ids)
        }
        classes_aum = {
            str(r["series_id"]): r["aum_usd"]
            for r in await conn.fetch(CLASSES_AUM_SQL, series_ids)
        }
        logger.info(
            "Profiles: %d registered, %d etfs, %d mmfs, %d stage labels for %d series",
            len(registered), len(etfs), len(mmfs), len(stage_labels), len(series_ids),
        )

        # Step 3 — latest risk row per instrument (exact pairs from step 1).
        # Fetched before the fund rows: the merged peer_strategy_label is the
        # last classification fallback in the cascade.
        risk_rows: list[dict[str, Any]] = []
        for batch in chunked(eligible, RISK_FETCH_BATCH):
            ids = [r["instrument_id"] for r in batch]
            dates = [r["source_calc_date"] for r in batch]
            fetched = await conn.fetch(RISK_LATEST_SQL, ids, dates)
            risk_rows.extend(dict(r) for r in fetched)
        risk_rows, report.risk_duplicates_merged = merge_risk_duplicates(risk_rows)
        logger.info(
            "Risk latest rows: %d (%d instruments had duplicate source rows merged)",
            len(risk_rows), report.risk_duplicates_merged,
        )
        peer_labels: dict[uuid.UUID, str | None] = {
            r["instrument_id"]: r.get("peer_strategy_label") for r in risk_rows
        }

        fund_rows: dict[uuid.UUID, dict[str, Any]] = {}
        for identity in eligible:
            series_id = str(identity["sec_series_id"])
            instrument_id = identity["instrument_id"]
            row = build_fund_row(
                identity,
                universe_by_id.get(instrument_id),
                registered.get(series_id),
                etfs.get(series_id),
                mmfs.get(series_id),
                now,
                stage_label=stage_labels.get(str(instrument_id)),
                peer_label=peer_labels.get(instrument_id),
                prospectus_fee=prospectus_fees.get(series_id),
                classes_aum=classes_aum.get(series_id),
            )
            fund_rows[row["instrument_id"]] = row
            ft = row["fund_type"]
            report.fund_type_counts[ft] = report.fund_type_counts.get(ft, 0) + 1
            if row["strategy_label"] == UNCLASSIFIED_LABEL:
                report.unclassified_funds += 1

        # Step 3b — upsert funds + risk (one transaction: parents first).
        async with session_factory() as session:
            for fund_chunk in chunked(list(fund_rows.values()), FUNDS_UPSERT_CHUNK):
                await session.execute(build_funds_upsert(fund_chunk))
                report.funds_upserted += len(fund_chunk)
            for risk_chunk in chunked(risk_rows, RISK_UPSERT_CHUNK):
                await session.execute(build_risk_upsert(risk_chunk))
                report.risk_rows_upserted += len(risk_chunk)
            await session.commit()
        logger.info(
            "Upserted %d funds, %d fund_risk_latest rows",
            report.funds_upserted, report.risk_rows_upserted,
        )

        # Step 4 — NAV window, batched; per-batch commit (resumable).
        window_start = nav_window_start(run_date)
        aum_fallback: dict[uuid.UUID, Decimal] = {}
        nav_batches = list(chunked(instrument_ids, NAV_FETCH_BATCH))
        for batch_no, id_batch in enumerate(nav_batches, start=1):
            nav_records = await conn.fetch(NAV_SQL, id_batch, window_start)
            report.nav_rows_upserted += len(nav_records)
            if report.nav_rows_upserted > NAV_ROW_LIMIT:
                raise RuntimeError(
                    f"NAV volume exceeded the {NAV_ROW_LIMIT} row safety valve "
                    f"({report.nav_rows_upserted} rows after batch {batch_no}/"
                    f"{len(nav_batches)}) — aborting instead of flooding the local DB."
                )
            nav_dicts: list[dict[str, Any]] = [dict(r) for r in nav_records]
            aum_fallback.update(latest_aum_by_instrument(nav_dicts))
            async with session_factory() as session:
                for nav_chunk in chunked(nav_dicts, NAV_UPSERT_CHUNK):
                    await session.execute(build_nav_upsert(nav_chunk))
                await session.commit()
            logger.info(
                "NAV batch %d/%d: %d funds, %d rows (total %d)",
                batch_no, len(nav_batches), len(id_batch), len(nav_records),
                report.nav_rows_upserted,
            )

        # Step 4b — aum_usd fallback for funds without monthly_avg_net_assets.
        fallback_rows = []
        for instrument_id, aum in aum_fallback.items():
            row = fund_rows[instrument_id]
            if row["aum_usd"] is None:
                row["aum_usd"] = aum
                fallback_rows.append(row)
        if fallback_rows:
            async with session_factory() as session:
                for fund_chunk in chunked(fallback_rows, FUNDS_UPSERT_CHUNK):
                    await session.execute(build_funds_upsert(fund_chunk))
                await session.commit()
        report.aum_filled_from_nav = len(fallback_rows)
        logger.info("funds.aum_usd filled from NAV fallback: %d", len(fallback_rows))

        # Step 5 — holdings: latest report per series, ranked; the refresh
        # deletes the series' stale reports in the same transaction.
        series_batches = list(chunked(series_ids, HOLDINGS_FETCH_BATCH))
        for batch_no, series_batch in enumerate(series_batches, start=1):
            raw: list[dict[str, Any]] = [
                dict(r) for r in await conn.fetch(HOLDINGS_SQL, series_batch)
            ]
            ranked = rank_holdings(raw)
            async with session_factory() as session:
                await session.execute(
                    delete(FundHolding).where(FundHolding.series_id.in_(series_batch))
                )
                for holding_chunk in chunked(ranked, HOLDINGS_UPSERT_CHUNK):
                    await session.execute(build_holdings_upsert(holding_chunk))
                await session.commit()
            report.holdings_rows_upserted += len(ranked)
            report.holdings_series += len({r["series_id"] for r in ranked})
            logger.info(
                "Holdings batch %d/%d: %d series queried, %d rows (total %d)",
                batch_no, len(series_batches), len(series_batch), len(ranked),
                report.holdings_rows_upserted,
            )
    finally:
        await conn.close()

    return report
