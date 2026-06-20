"""Drift status persistence + evaluation (Sprint C, Tasks 1 & 2).

Task 1 (persistence) owns the one-row-per-portfolio ``portfolio_drift_status``
table. Task 2 (evaluation) adds the pure + orchestrating logic that decides, for
a portfolio, the drift-vs-inception / class-limit / equity-overlap breaches and
the resulting ``worst_status``.

Routes / the worker own HTTP mapping and the transaction boundary; this module
owns the SQL/ORM and ``flush``es (so changes are visible within the session) but
does not ``commit``.

Persistence contract:

- ``upsert_drift_status`` writes the portfolio's drift row (insert if absent,
  update in place if present), so a re-evaluation never leaves a duplicate.
- ``get_drift_status`` returns a small typed ``DriftStatus`` (the four logical
  fields), or ``None`` if the portfolio has never been evaluated.

Evaluation contract (Task 2):

- ``inception_target_weights`` — the TARGET is the inception allocation, not the
  optimal reallocation (verbatim decision). Weight per ticker = qty·price
  normalized over the inception buy transactions.
- ``compute_class_breaches`` — per asset_class min/max bound checks.
- ``compute_overlap_breaches`` — consolidates per-equity look-through exposure
  across the fund sleeves and flags any security above the overlap cap.
- ``evaluate_portfolio_drift`` — orchestrates current weights (the same DB-first
  price loaders the rebalance/overview path uses), the inception target, the
  three breach families, and the ``worst_status`` derivation. Overlap is the
  expensive call (full N-PORT look-through), so it is recomputed ONLY when the
  latest N-PORT ``report_date`` is newer than the one stamped on the previous
  evaluation; otherwise the previous overlap result is reused verbatim.

A portfolio without an inception date / inception transactions (e.g. created
outside the builder) has NO drift target — drift is skipped (empty list) but
class and overlap breaches are still evaluated (verbatim decision).

Every update stamps ``updated_at`` explicitly (the ORM ``onupdate`` hook only
fires on ORM updates; setting it here keeps the timestamp correct regardless of
how the update is emitted — same caveat as the portfolio / optimize_jobs /
constraint tables).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import Portfolio, PortfolioTransaction
from app.models.portfolio_drift_status import PortfolioDriftStatus
from app.models.rebalance import RebalancePolicy
from app.rebalance.evaluator import (
    DEFAULT_BAND_ABS,
    DEFAULT_BAND_REL,
    PositionDrift,
    compute_drifts,
    default_urgent_band,
    fund_instrument_ids_by_ticker,
)
from app.services.lookthrough import get_fund_series
from app.services.lookthrough_exposure import fund_equity_exposure
from app.services.portfolio_constraints import ConstraintSet, get_constraints
from app.services.portfolio_crud import (
    resolve_position_taxonomy,
    select_last_two_closes,
    select_last_two_navs,
)

# Re-export the loaders this module mirrors so tests can monkeypatch them on
# ``portfolio_drift`` directly (matching the rebalance/overview/lookthrough
# stubbing convention). ``compute_drifts`` / ``default_urgent_band`` are used
# as-is from the rebalance evaluator (single source of band classification).
__all__ = [
    "DriftStatus",
    "ClassBreach",
    "OverlapBreach",
    "inception_target_weights",
    "compute_class_breaches",
    "compute_overlap_breaches",
    "evaluate_portfolio_drift",
    "upsert_drift_status",
    "get_drift_status",
]

# Severity ordering for worst_status reduction.
_SEVERITY = {"ok": 0, "maintenance": 1, "urgent": 2}


@dataclass(frozen=True)
class DriftStatus:
    """The latest drift evaluation for a portfolio."""

    portfolio_id: int
    evaluated_at: dt.datetime
    worst_status: str
    breaches: dict


@dataclass(frozen=True)
class ClassBreach:
    """One asset-class limit breach (below the min or above the max bound)."""

    asset_class: str
    current_weight: float
    min_weight: float | None
    max_weight: float | None
    kind: str  # 'below_min' | 'above_max'


@dataclass(frozen=True)
class OverlapBreach:
    """One equity whose consolidated look-through exposure exceeds the cap."""

    security_key: str
    exposure: float
    overlap_cap: float


async def upsert_drift_status(
    session: AsyncSession,
    portfolio_id: int,
    *,
    evaluated_at: dt.datetime,
    worst_status: str,
    breaches: dict,
) -> None:
    """Upsert the drift status for ``portfolio_id``.

    Inserts a new row if the portfolio has no drift status yet, otherwise
    updates the existing row in place (one row per portfolio, no duplicates).
    """
    row = await session.get(PortfolioDriftStatus, portfolio_id)
    if row is None:
        row = PortfolioDriftStatus(
            portfolio_id=portfolio_id,
            evaluated_at=evaluated_at,
            worst_status=worst_status,
            breaches=breaches,
        )
        session.add(row)
    else:
        row.evaluated_at = evaluated_at
        row.worst_status = worst_status
        row.breaches = breaches
        row.updated_at = dt.datetime.now(dt.UTC)

    await session.flush()


async def get_drift_status(
    session: AsyncSession, portfolio_id: int
) -> DriftStatus | None:
    """Return the typed drift status for ``portfolio_id``, or ``None``.

    ``None`` means the portfolio has never been evaluated.
    """
    row = await session.get(PortfolioDriftStatus, portfolio_id)
    if row is None:
        return None
    return DriftStatus(
        portfolio_id=row.portfolio_id,
        evaluated_at=row.evaluated_at,
        worst_status=row.worst_status,
        breaches=row.breaches,
    )


# ---------------------------------------------------------------------------
# Pure evaluation helpers
# ---------------------------------------------------------------------------


def inception_target_weights(inception_txns: list) -> dict[str, float]:
    """Target weight per ticker from the inception buy transactions.

    ``weight_ticker = sum(qty*price)_ticker / sum_all(qty*price)``. Multiple buys
    of the same ticker on inception day aggregate. Empty input -> ``{}``. The
    target is the inception allocation (NOT the optimal reallocation) — see the
    module docstring.
    """
    notionals: dict[str, float] = {}
    for txn in inception_txns:
        notionals[txn.ticker] = (
            notionals.get(txn.ticker, 0.0) + txn.quantity * txn.price
        )
    total = sum(notionals.values())
    if total <= 0:
        return {}
    return {ticker: value / total for ticker, value in notionals.items()}


def compute_class_breaches(
    weights_by_class: dict[str, float], constraints: ConstraintSet | None
) -> list[ClassBreach]:
    """Per-asset-class min/max breaches against the saved class limits.

    For each class limit, a breach is raised when ``current < min_weight`` (when
    a min is set) or ``current > max_weight`` (when a max is set). A class named
    in the limits but absent from ``weights_by_class`` is treated as 0 weight
    (so a min bound on a class the portfolio does not hold still breaches).
    Returns ``[]`` when ``constraints`` is ``None`` or has no class limits.
    """
    if constraints is None or not constraints.class_limits:
        return []
    breaches: list[ClassBreach] = []
    for limit in constraints.class_limits:
        current = weights_by_class.get(limit.asset_class, 0.0)
        if limit.min_weight is not None and current < limit.min_weight:
            breaches.append(
                ClassBreach(
                    asset_class=limit.asset_class,
                    current_weight=current,
                    min_weight=limit.min_weight,
                    max_weight=limit.max_weight,
                    kind="below_min",
                )
            )
        elif limit.max_weight is not None and current > limit.max_weight:
            breaches.append(
                ClassBreach(
                    asset_class=limit.asset_class,
                    current_weight=current,
                    min_weight=limit.min_weight,
                    max_weight=limit.max_weight,
                    kind="above_max",
                )
            )
    return breaches


# ---------------------------------------------------------------------------
# Async evaluation helpers (data-loader stub points)
# ---------------------------------------------------------------------------


async def compute_overlap_breaches(
    session: AsyncSession,
    datalake: AsyncSession,
    fund_weights: dict[uuid.UUID, float],
    overlap_cap: float | None,
    fund_ids: list[uuid.UUID],
) -> list[OverlapBreach]:
    """Per-equity consolidated look-through exposure breaches.

    Consolidates ``exposure_s = sum_fund fund_weight*h_{fund,s}`` over the
    per-fund equity look-through matrix (``fund_equity_exposure``) and flags any
    security whose total exposure exceeds ``overlap_cap``. Returns ``[]`` (and
    skips the expensive look-through) when ``overlap_cap`` is ``None``.
    """
    if overlap_cap is None:
        return []
    matrix = await fund_equity_exposure(session, datalake, fund_ids)
    exposure: dict[str, float] = {}
    for fund_id, holdings in matrix.items():
        weight = fund_weights.get(fund_id, 0.0)
        if weight == 0.0:
            continue
        for security_key, pct in holdings.items():
            exposure[security_key] = exposure.get(security_key, 0.0) + weight * pct
    breaches = [
        OverlapBreach(security_key=key, exposure=value, overlap_cap=overlap_cap)
        for key, value in exposure.items()
        if value > overlap_cap
    ]
    breaches.sort(key=lambda b: b.security_key)
    return breaches


async def latest_nport_report_date(
    session: AsyncSession,
    datalake: AsyncSession | None,
    fund_ids: list[uuid.UUID],
) -> dt.date | None:
    """Latest N-PORT ``report_date`` across the funds' SEC series, or ``None``.

    Resolves each fund instrument to its SEC series, then takes the single
    ``MAX(report_date)`` over ``sec_nport_holdings`` for those series. This is
    the freshness key for the overlap reuse-vs-recompute decision: when it has
    not advanced since the previous evaluation, the (expensive) look-through is
    skipped and the previous overlap result is reused. ``None`` when there are no
    fund sleeves, no resolvable series, or no materialized holdings.
    """
    if not fund_ids or datalake is None:
        return None
    series_ids: list[str] = []
    for fund_id in fund_ids:
        series_id = await get_fund_series(session, fund_id)
        if series_id:
            series_ids.append(series_id)
    if not series_ids:
        return None
    result = await datalake.execute(
        text(
            "SELECT max(report_date) AS report_date "
            "FROM sec_nport_holdings "
            "WHERE series_id = ANY(CAST(:series_ids AS text[]))"
        ),
        {"series_ids": sorted(set(series_ids))},
    )
    row = result.first()
    return row[0] if row is not None else None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _worst(statuses: list[str]) -> str:
    """Reduce a list of per-component statuses to the worst severity."""
    worst = "ok"
    for status in statuses:
        if _SEVERITY[status] > _SEVERITY[worst]:
            worst = status
    return worst


async def load_inception_transactions(
    session: AsyncSession, portfolio: Portfolio
) -> list[PortfolioTransaction]:
    """Inception BUY transactions for the portfolio (the drift target source).

    Empty when the portfolio has no ``inception_date`` (created outside the
    builder) — the caller then skips drift. Stub point for tests.
    """
    if portfolio.inception_date is None:
        return []
    result = await session.execute(
        select(PortfolioTransaction).where(
            PortfolioTransaction.portfolio_id == portfolio.id,
            PortfolioTransaction.trade_date == portfolio.inception_date,
            PortfolioTransaction.side == "buy",
        )
    )
    return list(result.scalars().all())


async def evaluate_portfolio_drift(
    session: AsyncSession,
    datalake: AsyncSession | None,
    portfolio: Portfolio,
    *,
    policy: RebalancePolicy | None = None,
    previous: DriftStatus | None,
    as_of: dt.date,
) -> tuple[str, dict]:
    """Evaluate drift-vs-inception, class and overlap breaches for a portfolio.

    Returns ``(worst_status, breaches_dict)`` where ``breaches_dict`` carries
    JSON-serializable lists: ``position_drifts``, ``class_breaches``,
    ``overlap_breaches`` and the ``overlap_report_date`` they were computed at.

    - Current weights come from the same DB-first price loaders the rebalance /
      overview path uses (closes for equities, NAVs for funds).
    - The drift target is the inception allocation; a portfolio with no
      inception transactions skips drift (empty list) but still evaluates class
      and overlap breaches.
    - Overlap is recomputed only when the latest N-PORT ``report_date`` is newer
      than the one on ``previous``; otherwise the previous overlap is reused.
    """
    positions = list(portfolio.positions)
    tickers = [p.ticker for p in positions]

    # --- current weights (DB-first, mirrors evaluate_portfolio) -------------
    fund_ids_by_ticker = await fund_instrument_ids_by_ticker(session, tickers)
    closes = await select_last_two_closes(session, tickers)
    nav_tickers = [t for t in fund_ids_by_ticker if t not in closes]
    if nav_tickers:
        closes.update(await select_last_two_navs(session, nav_tickers))
    market_values = {
        p.ticker: p.quantity * closes[p.ticker][0][1]
        for p in positions
        if closes.get(p.ticker)
    }
    invested = sum(market_values.values())
    current = (
        {t: mv / invested for t, mv in market_values.items()}
        if invested > 0
        else {}
    )

    # --- taxonomy -> weights by asset_class ---------------------------------
    taxonomy = await resolve_position_taxonomy(session, tickers)
    weights_by_class: dict[str, float] = {}
    for ticker, weight in current.items():
        tax = taxonomy.get(ticker)
        asset_class = tax.asset_class if tax is not None else None
        if asset_class is None:
            continue
        weights_by_class[asset_class] = (
            weights_by_class.get(asset_class, 0.0) + weight
        )

    # --- drift vs inception target ------------------------------------------
    inception_txns = await load_inception_transactions(session, portfolio)
    target = inception_target_weights(inception_txns)
    if target:
        band_abs = policy.band_abs if policy else DEFAULT_BAND_ABS
        band_rel = policy.band_rel if policy else DEFAULT_BAND_REL
        drifts: list[PositionDrift] = compute_drifts(
            current, target, band_abs, band_rel, default_urgent_band(band_abs)
        )
    else:
        # No inception target -> drift skipped (documented); class+overlap run.
        drifts = []

    # --- class breaches -----------------------------------------------------
    constraints = await get_constraints(session, portfolio.id)
    class_breaches = compute_class_breaches(weights_by_class, constraints)

    # --- overlap breaches (reuse unless N-PORT report_date advanced) --------
    overlap_cap = constraints.overlap_cap if constraints is not None else None
    fund_ids = list({iid for iid in fund_ids_by_ticker.values()})
    report_date = await latest_nport_report_date(session, datalake, fund_ids)
    report_date_iso = report_date.isoformat() if report_date is not None else None

    prev_report_iso = (
        previous.breaches.get("overlap_report_date") if previous else None
    )
    reuse_overlap = (
        previous is not None
        and report_date_iso is not None
        and prev_report_iso == report_date_iso
        and "overlap_breaches" in previous.breaches
    )
    if reuse_overlap and previous is not None:
        overlap_breaches_json = previous.breaches["overlap_breaches"]
    elif datalake is None:
        # No data-lake -> no look-through possible; record an empty overlap set.
        overlap_breaches_json = []
    else:
        fund_weights = {
            fund_ids_by_ticker[t]: current.get(t, 0.0) for t in fund_ids_by_ticker
        }
        overlap_breaches = await compute_overlap_breaches(
            session, datalake, fund_weights, overlap_cap, fund_ids
        )
        overlap_breaches_json = [asdict(b) for b in overlap_breaches]

    # --- worst_status -------------------------------------------------------
    statuses = [d.status for d in drifts]
    if class_breaches:
        statuses.append("maintenance")
    if overlap_breaches_json:
        statuses.append("maintenance")
    worst_status = _worst(statuses)

    breaches = {
        "position_drifts": [asdict(d) for d in drifts],
        "class_breaches": [asdict(b) for b in class_breaches],
        "overlap_breaches": overlap_breaches_json,
        "overlap_report_date": report_date_iso,
    }
    return worst_status, breaches
