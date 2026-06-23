"""Return-matrix loading for the optimizer (F8.3) — DB → aligned daily returns.

Mixed universes: funds by ``instrument_id`` (fund_nav: ``return_1d``, falling
back to the log-diff of ``nav`` where ``return_1d`` is NULL) and equities by
``ticker`` (log returns of ``eod_prices.adj_close``). Series are aligned on
the intersection of dates; fewer than ``MIN_COMMON_OBS`` common observations
raises a ValueError (the route maps it to 422).

This module performs I/O only — all math lives in ``engine`` /
``black_litterman``.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eod_price import EodPrice
from app.models.fund import Fund, FundNav, FundRiskLatest
from app.models.universe import FundamentalsSnapshot
from app.services import funds_catalog

# None = use the FULL nav_timeseries history (the 2-year window gate is removed;
# nav_timeseries spans decades). Pass an explicit int to opt into a narrower
# estimation window.
DEFAULT_WINDOW_DAYS: int | None = None
MIN_COMMON_OBS = 400
# Hard ceiling for the on-demand broad-universe path (design §8). Above this the
# pipeline fails loud (a worker pre-compute path is phase 2, not built here).
MAX_UNIVERSE_CANDIDATES = 5000
# Universe quality gates (applied in select_universe_funds): a fund must clear a
# minimum AUM and carry a minimum NAV track record to enter the optimizable set.
MIN_UNIVERSE_AUM_USD = 200_000_000
MIN_UNIVERSE_HISTORY_DAYS = 3 * 365


@dataclass(frozen=True)
class FundAssetRef:
    id: uuid.UUID

    @property
    def label(self) -> str:
        return f"fund:{self.id}"


@dataclass(frozen=True)
class EquityAssetRef:
    ticker: str

    @property
    def label(self) -> str:
        return f"equity:{self.ticker}"


AssetRef = FundAssetRef | EquityAssetRef


def _fund_return_series(rows: list[tuple[dt.date, float | None, float | None]]) -> pd.Series:
    """Daily returns from (nav_date, nav, return_1d) rows, ordered by date.

    Prefers the precomputed ``return_1d``; where it is NULL, falls back to
    log(navₜ/navₜ₋₁) when both NAVs are present and positive. Days with
    neither are dropped (the date-intersection step handles alignment).
    """
    dates: list[dt.date] = []
    values: list[float] = []
    prev_nav: float | None = None
    for nav_date, nav, return_1d in rows:
        if return_1d is not None:
            dates.append(nav_date)
            values.append(float(return_1d))
        elif nav is not None and nav > 0 and prev_nav is not None and prev_nav > 0:
            dates.append(nav_date)
            values.append(float(np.log(nav / prev_nav)))
        if nav is not None and nav > 0:
            prev_nav = float(nav)
    return pd.Series(values, index=pd.Index(dates), dtype=float)


def _fund_simple_return_series(
    rows: list[tuple[dt.date, float | None, float | None, str | None]],
) -> pd.Series:
    """SIMPLE daily returns from (nav_date, nav, return_1d, return_type) rows.

    Builds the per-fund series honoring ``return_type`` and the glitch guard via
    ``to_simple_returns`` (PERFORMANCE path). Where ``return_1d`` is NULL, falls
    back to ``log(navₜ/navₜ₋₁)`` (then converted to simple). The COVARIANCE path
    keeps log and uses ``_fund_return_series`` instead.
    """
    from app.analytics.return_convention import to_simple_returns

    dates: list[dt.date] = []
    log_values: list[float] = []
    types: list[str] = []
    prev_nav: float | None = None
    for nav_date, nav, return_1d, return_type in rows:
        if return_1d is not None:
            dates.append(nav_date)
            log_values.append(float(return_1d))
            types.append(return_type or "log")
        elif nav is not None and nav > 0 and prev_nav is not None and prev_nav > 0:
            dates.append(nav_date)
            log_values.append(float(np.log(nav / prev_nav)))
            types.append("log")
        if nav is not None and nav > 0:
            prev_nav = float(nav)
    simple = to_simple_returns(np.asarray(log_values, dtype=float), types)
    return pd.Series(simple, index=pd.Index(dates), dtype=float)


async def _load_fund_returns(
    session: AsyncSession,
    ref: FundAssetRef,
    since: dt.date | None,
    *,
    convention: Literal["log", "simple"] = "log",
) -> pd.Series:
    cols = [FundNav.nav_date, FundNav.nav, FundNav.return_1d]
    if convention == "simple":
        cols.append(FundNav.return_type)
    stmt = select(*cols).where(FundNav.instrument_id == ref.id)
    if since is not None:
        stmt = stmt.where(FundNav.nav_date >= since)
    result = await session.execute(stmt.order_by(FundNav.nav_date))
    raw = result.all()
    if not raw:
        raise ValueError(f"unknown asset or no NAV history in window: {ref.label}")
    if convention == "simple":
        rows = [
            (
                nav_date,
                float(nav) if nav is not None else None,
                float(r1d) if r1d is not None else None,
                rtype,
            )
            for nav_date, nav, r1d, rtype in raw
        ]
        return _fund_simple_return_series(rows)
    rows3 = [
        (nav_date, float(nav) if nav is not None else None, float(r1d) if r1d is not None else None)
        for nav_date, nav, r1d in raw
    ]
    return _fund_return_series(rows3)


async def _load_fund_returns_batch(
    session: AsyncSession,
    fund_refs: list[FundAssetRef],
    since: dt.date | None,
    *,
    convention: Literal["log", "simple"] = "log",
) -> dict[str, pd.Series]:
    """Daily-return Series per fund, loaded in ONE query (no N+1).

    The broad-universe Stage-1 resolves hundreds of candidate funds; loading them
    with one query per fund serialized hundreds of round-trips. This fetches every
    fund's NAV history in a single ``instrument_id IN (...)`` scan (the
    ``(instrument_id, nav_date)`` index serves it), groups the rows per fund in
    date order, and reuses ``_fund_return_series`` so the output is identical to
    the per-fund loader. A fund with no NAV rows in the window raises ValueError
    (matching ``_load_fund_returns``); the candidate set is pre-filtered to funds
    with history, so that is an edge.
    """
    if not fund_refs:
        return {}
    ids = [ref.id for ref in fund_refs]
    cols = [FundNav.instrument_id, FundNav.nav_date, FundNav.nav, FundNav.return_1d]
    if convention == "simple":
        cols.append(FundNav.return_type)
    stmt = select(*cols).where(FundNav.instrument_id.in_(ids))
    if since is not None:
        stmt = stmt.where(FundNav.nav_date >= since)
    result = await session.execute(
        stmt.order_by(FundNav.instrument_id, FundNav.nav_date)
    )
    if convention == "simple":
        rows_by_id_s: dict[
            uuid.UUID, list[tuple[dt.date, float | None, float | None, str | None]]
        ] = {}
        for iid, nav_date, nav, r1d, rtype in result.all():
            rows_by_id_s.setdefault(iid, []).append(
                (
                    nav_date,
                    float(nav) if nav is not None else None,
                    float(r1d) if r1d is not None else None,
                    rtype,
                )
            )
        out: dict[str, pd.Series] = {}
        for ref in fund_refs:
            rows_s = rows_by_id_s.get(ref.id)
            if not rows_s:
                raise ValueError(
                    f"unknown asset or no NAV history in window: {ref.label}"
                )
            out[ref.label] = _fund_simple_return_series(rows_s)
        return out
    rows_by_id: dict[uuid.UUID, list[tuple[dt.date, float | None, float | None]]] = {}
    for iid, nav_date, nav, r1d in result.all():
        rows_by_id.setdefault(iid, []).append(
            (
                nav_date,
                float(nav) if nav is not None else None,
                float(r1d) if r1d is not None else None,
            )
        )
    out = {}
    for ref in fund_refs:
        rows = rows_by_id.get(ref.id)
        if not rows:
            raise ValueError(
                f"unknown asset or no NAV history in window: {ref.label}"
            )
        out[ref.label] = _fund_return_series(rows)
    return out


async def _load_equity_returns(
    session: AsyncSession,
    ref: EquityAssetRef,
    since: dt.date | None,
    *,
    convention: Literal["log", "simple"] = "log",
) -> pd.Series:
    stmt = select(EodPrice.date, EodPrice.adj_close).where(EodPrice.ticker == ref.ticker)
    if since is not None:
        stmt = stmt.where(EodPrice.date >= since)
    result = await session.execute(stmt.order_by(EodPrice.date))
    rows = result.all()
    if not rows:
        raise ValueError(f"unknown asset or no price history in window: {ref.label}")
    prices = pd.Series(
        [float(close) for _date, close in rows],
        index=pd.Index([row_date for row_date, _close in rows]),
        dtype=float,
    )
    prices = prices[prices > 0]
    log_prices = pd.Series(np.log(prices.to_numpy()), index=prices.index, dtype=float)
    log_returns = log_prices.diff().dropna()
    if convention == "simple":
        from app.analytics.return_convention import to_simple_returns

        return to_simple_returns(log_returns)
    return log_returns


async def load_aligned_returns(
    session: AsyncSession,
    assets: list[AssetRef],
    window_days: int | None = DEFAULT_WINDOW_DAYS,
    today: dt.date | None = None,
    *,
    convention: Literal["log", "simple"] = "log",
) -> pd.DataFrame:
    """T×n daily-return frame (columns = asset labels, index = common dates).

    ``convention="log"`` (default) is byte-identical to the legacy behavior and
    feeds the covariance path. ``convention="simple"`` returns ``expm1`` of the
    log returns honoring ``return_type`` and the glitch guard — the PERFORMANCE
    frame for the backtest OOS curve and the portfolio Monte-Carlo.

    Raises ValueError (→ 422 at the route) on: duplicate assets, an unknown
    asset / empty window, or fewer than ``MIN_COMMON_OBS`` common dates.
    """
    if len(assets) < 2:
        raise ValueError("at least 2 assets are required to optimize")
    labels = [ref.label for ref in assets]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"duplicate assets in request: {', '.join(duplicates)}")
    if window_days is not None and window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    today = today or dt.date.today()
    since = None if window_days is None else today - dt.timedelta(days=window_days)

    series: dict[str, pd.Series] = {}
    for ref in assets:
        if isinstance(ref, FundAssetRef):
            series[ref.label] = await _load_fund_returns(
                session, ref, since, convention=convention
            )
        else:
            series[ref.label] = await _load_equity_returns(
                session, ref, since, convention=convention
            )

    frame = pd.DataFrame(series).dropna()
    if len(frame) < MIN_COMMON_OBS:
        window_desc = "the full history" if window_days is None else f"the last {window_days} days"
        raise ValueError(
            f"insufficient common history: {len(frame)} overlapping observations across the "
            f"{len(assets)} assets in {window_desc} "
            f"(minimum {MIN_COMMON_OBS}) — widen the window or drop the short-history assets"
        )
    return frame


async def load_returns_matrix(
    session: AsyncSession,
    assets: list[AssetRef],
    window_days: int | None = DEFAULT_WINDOW_DAYS,
    today: dt.date | None = None,
    *,
    convention: Literal["log", "simple"] = "log",
) -> pd.DataFrame:
    """T×N daily-return frame over the UNION of dates — NaN preserved.

    Stage-1 loader for the broad-universe optimizer: unlike
    ``load_aligned_returns`` (which ``dropna`` to the common-history window),
    this keeps every asset's full series and aligns on the UNION index, so a
    young fund contributes NaN before its inception instead of truncating the
    whole panel. Pairwise covariance (``app.analytics.pairwise_cov``) consumes
    the NaN directly.

    Raises ValueError (→ 422) on: fewer than 2 assets, duplicate assets, an
    unknown asset / empty window.
    """
    if len(assets) < 2:
        raise ValueError("at least 2 assets are required to optimize")
    labels = [ref.label for ref in assets]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"duplicate assets in request: {', '.join(duplicates)}")
    if window_days is not None and window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    today = today or dt.date.today()
    since = None if window_days is None else today - dt.timedelta(days=window_days)

    # Funds are loaded in ONE batched query (avoids the N+1 that dominated the
    # broad-universe Stage-1 latency); the rare equity in this path stays per-ref.
    # Column order MUST follow ``assets`` — the broad orchestrator maps kept
    # indices back to assets by column position.
    fund_series = await _load_fund_returns_batch(
        session,
        [ref for ref in assets if isinstance(ref, FundAssetRef)],
        since,
        convention=convention,
    )
    series: dict[str, pd.Series] = {}
    for ref in assets:
        if isinstance(ref, FundAssetRef):
            series[ref.label] = fund_series[ref.label]
        else:
            series[ref.label] = await _load_equity_returns(
                session, ref, since, convention=convention
            )

    # Union index, NO dropna — the pairwise estimator handles the NaN mask.
    frame = pd.DataFrame(series)
    return frame


async def load_fund_aum(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float | None]:
    """AUM (funds.aum_usd) per instrument — None where the source has no AUM."""
    if not fund_ids:
        return {}
    result = await session.execute(
        select(Fund.instrument_id, Fund.aum_usd).where(Fund.instrument_id.in_(fund_ids))
    )
    found = {row[0]: (float(row[1]) if row[1] is not None else None) for row in result.all()}
    return {fund_id: found.get(fund_id) for fund_id in fund_ids}


async def load_equity_market_cap(
    session: AsyncSession, tickers: list[str]
) -> dict[str, float | None]:
    """Market cap per equity ticker = shares_outstanding * latest adj_close.

    ``shares_outstanding`` comes from ``fundamentals_snapshot``; price comes
    from the most recent ``eod_prices`` row. None means either input is missing
    or non-positive. The caller decides whether that should fail loud.
    """
    if not tickers:
        return {}
    shares_result = await session.execute(
        select(
            FundamentalsSnapshot.ticker,
            FundamentalsSnapshot.shares_outstanding,
        ).where(FundamentalsSnapshot.ticker.in_(tickers))
    )
    shares = {row[0]: row[1] for row in shares_result.all()}
    price_result = await session.execute(
        select(EodPrice.ticker, EodPrice.adj_close)
        .distinct(EodPrice.ticker)
        .where(EodPrice.ticker.in_(tickers))
        .order_by(EodPrice.ticker, EodPrice.date.desc())
    )
    prices = {row[0]: row[1] for row in price_result.all()}
    out: dict[str, float | None] = {}
    for ticker in tickers:
        s = shares.get(ticker)
        p = prices.get(ticker)
        out[ticker] = (
            float(s) * float(p)
            if s is not None and s > 0 and p is not None and p > 0
            else None
        )
    return out


async def load_fund_asset_class(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """asset_class (funds.asset_class) per instrument — None where unknown."""
    if not fund_ids:
        return {}
    result = await session.execute(
        select(Fund.instrument_id, Fund.asset_class).where(
            Fund.instrument_id.in_(fund_ids)
        )
    )
    found = {row[0]: row[1] for row in result.all()}
    return {fund_id: found.get(fund_id) for fund_id in fund_ids}


async def load_fund_strategy_label(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """strategy_label (funds.strategy_label) per instrument — None where unknown."""
    if not fund_ids:
        return {}
    result = await session.execute(
        select(Fund.instrument_id, Fund.strategy_label).where(
            Fund.instrument_id.in_(fund_ids)
        )
    )
    found = {row[0]: row[1] for row in result.all()}
    return {fund_id: found.get(fund_id) for fund_id in fund_ids}


async def load_fund_quality_metrics(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, float | None]]:
    """Per-fund quality signals for the Stage-1 score (G5-safe).

    Returns ``{instrument_id: {"sharpe_1y": .., "expense_ratio": .., "aum_usd":
    ..}}`` — each value ``None`` where the source lacks it. ``sharpe_1y`` comes
    from ``FundRiskLatest``; ``expense_ratio`` / ``aum_usd`` from ``Fund``. NO
    expected-return field is read (gate G5).
    """
    if not fund_ids:
        return {}
    result = await session.execute(
        select(
            Fund.instrument_id,
            Fund.expense_ratio,
            Fund.aum_usd,
            FundRiskLatest.sharpe_1y,
        )
        .select_from(Fund)
        .outerjoin(FundRiskLatest, FundRiskLatest.instrument_id == Fund.instrument_id)
        .where(Fund.instrument_id.in_(fund_ids))
    )
    found: dict[uuid.UUID, dict[str, float | None]] = {}
    for iid, expense, aum, sharpe in result.all():
        found[iid] = {
            "sharpe_1y": float(sharpe) if sharpe is not None else None,
            "expense_ratio": float(expense) if expense is not None else None,
            "aum_usd": float(aum) if aum is not None else None,
        }
    default = {"sharpe_1y": None, "expense_ratio": None, "aum_usd": None}
    return {fid: found.get(fid, dict(default)) for fid in fund_ids}


# Pre-computed per-fund risk features for the broad-universe Stage-1 clustering.
# They span equity exposure (beta, equity correlation), risk level (vol,
# drawdown), tail (CVaR/EVT), asymmetry (capture) and fixed-income style
# (empirical duration vs Δ rates, credit beta vs Δ spread). G5-safe: NONE is an
# expected-return forecast (raw returns are deliberately excluded).
RISK_FEATURE_KEYS: tuple[str, ...] = (
    "volatility_1y",
    "max_drawdown_1y",
    "beta_1y",
    "equity_correlation_252d",
    "cvar_95_12m",
    "cvar_99_evt",
    "downside_capture_1y",
    "upside_capture_1y",
    "empirical_duration",
    "credit_beta",
    "inflation_beta",
    "crisis_alpha_score",
)


async def load_fund_risk_features(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, float | None]]:
    """Pre-computed per-fund risk features for Stage-1 clustering (G5-safe).

    Returns ``{instrument_id: {key: float|None}}`` over ``RISK_FEATURE_KEYS`` from
    ``FundRiskLatest`` (the ``fund_risk_latest_mv`` read-model, which now projects
    the FI factors ``empirical_duration``/``credit_beta``) — the broad-universe
    selection clusters funds in this standardized factor space WITHOUT loading any
    raw NAV history. Every requested id is present (all-None default).
    """
    if not fund_ids:
        return {}
    cols = [getattr(FundRiskLatest, key) for key in RISK_FEATURE_KEYS]
    result = await session.execute(
        select(FundRiskLatest.instrument_id, *cols).where(
            FundRiskLatest.instrument_id.in_(fund_ids)
        )
    )
    found: dict[uuid.UUID, dict[str, float | None]] = {}
    for row in result.all():
        found[row[0]] = {
            key: (float(val) if val is not None else None)
            for key, val in zip(RISK_FEATURE_KEYS, row[1:], strict=True)
        }
    default = {key: None for key in RISK_FEATURE_KEYS}
    return {fid: found.get(fid, dict(default)) for fid in fund_ids}


@dataclass(frozen=True)
class UniverseFund:
    """A fund selected by a universe spec — id plus display labels."""

    id: uuid.UUID
    ticker: str | None
    name: str


async def select_universe_funds(
    session: AsyncSession,
    filters: funds_catalog.FundFilters,
    *,
    rank_by: str,
    rank_dir: str,
    max_assets: int | None,
    require_aum: bool = False,
    include_ids: Sequence[str] | None = None,
    window_days: int | None = DEFAULT_WINDOW_DAYS,
    min_obs: int = MIN_COMMON_OBS,
    today: dt.date | None = None,
) -> list[UniverseFund]:
    """Resolve a universe spec to ranked fund candidates.

    When ``max_assets`` is an int, returns up to that many top-ranked candidates
    (hard ``LIMIT`` in SQL). When ``max_assets`` is ``None`` (broad-universe
    mode), returns ALL matching funds up to the hard ceiling
    ``MAX_UNIVERSE_CANDIDATES``; if the DB returns more than that, raises
    ``ValueError`` (fail-loud — a pre-computed worker path is planned for
    larger universes).

    Reuses the GET /funds filter predicates and sort whitelist. Quality gates
    applied to EVERY candidate: AUM ≥ ``MIN_UNIVERSE_AUM_USD`` ($200M; NULL AUM
    is excluded), a NAV track record ≥ ``MIN_UNIVERSE_HISTORY_DAYS`` (3y, over
    full history), and at least ``min_obs`` non-null NAV observations in the
    window — screening out small and short-history funds.
    It does NOT by itself guarantee the cross-fund date intersection clears
    ``MIN_COMMON_OBS``; ``load_aligned_returns`` still enforces that on the
    resolved set (a fail-loud 422 if the overlap falls short). ``require_aum``
    (BL paths) additionally drops funds without a positive AUM, so market
    weights are always computable on the result.
    """
    today = today or dt.date.today()
    since = None if window_days is None else today - dt.timedelta(days=window_days)

    nav_count_where: list[ColumnElement[bool]] = [FundNav.nav.is_not(None)]
    if since is not None:
        nav_count_where.append(FundNav.nav_date >= since)
    nav_counts = (
        select(FundNav.instrument_id, func.count().label("n"))
        .where(*nav_count_where)
        .group_by(FundNav.instrument_id)
        .subquery()
    )
    # Track-record gate: earliest NAV on/before the cutoff = the fund has carried
    # at least MIN_UNIVERSE_HISTORY_DAYS of history. Computed over FULL history
    # (independent of the analysis window) so a narrow window_days never spuriously
    # disqualifies a long-lived fund.
    history_cutoff = today - dt.timedelta(days=MIN_UNIVERSE_HISTORY_DAYS)
    nav_span = (
        select(
            FundNav.instrument_id,
            func.min(FundNav.nav_date).label("first_nav"),
        )
        .where(FundNav.nav.is_not(None))
        .group_by(FundNav.instrument_id)
        .subquery()
    )

    order_col = funds_catalog.sort_column(rank_by)
    order = order_col.desc() if rank_dir == "desc" else order_col.asc()

    conditions = list(funds_catalog.filter_conditions(filters))
    # Quality gate: a minimum AUM (NULL AUM = unconfirmed → excluded). This is a
    # hard floor; a stricter user-supplied aum_min in `filters` narrows further.
    conditions.append(Fund.aum_usd.is_not(None))
    conditions.append(Fund.aum_usd >= MIN_UNIVERSE_AUM_USD)
    # 'Unclassified' funds have no definite strategy/asset class — leave them out
    # of the optimizable universe (too few to reclassify), mirroring the same
    # exclusion baked into funds_list_mv.
    conditions.append(Fund.strategy_label != "Unclassified")
    if require_aum:
        conditions.append(Fund.aum_usd > 0)
    if include_ids:
        conditions.append(Fund.instrument_id.in_(list(include_ids)))

    stmt = (
        select(Fund.instrument_id, Fund.ticker, Fund.name)
        .select_from(Fund)
        .outerjoin(FundRiskLatest, FundRiskLatest.instrument_id == Fund.instrument_id)
        .join(nav_counts, nav_counts.c.instrument_id == Fund.instrument_id)
        .join(nav_span, nav_span.c.instrument_id == Fund.instrument_id)
        .where(
            *conditions,
            nav_counts.c.n >= min_obs,
            nav_span.c.first_nav <= history_cutoff,
        )
        .order_by(order.nulls_last(), Fund.ticker.nulls_last(), Fund.instrument_id)
    )
    if max_assets is not None:
        stmt = stmt.limit(max_assets)
    else:
        # Broad-universe path: no LIMIT, but cap at the hard ceiling + 1 so we
        # can detect (and fail loud on) an over-large universe without scanning
        # the whole table.
        stmt = stmt.limit(MAX_UNIVERSE_CANDIDATES + 1)
    result = await session.execute(stmt)
    funds = [
        UniverseFund(id=iid, ticker=ticker, name=name)
        for iid, ticker, name in result.all()
    ]
    if max_assets is None and len(funds) > MAX_UNIVERSE_CANDIDATES:
        raise ValueError(
            f"universe matched more than {MAX_UNIVERSE_CANDIDATES} funds — "
            "narrow the filters (this on-demand path is capped; a pre-computed "
            "worker path is planned for larger universes)"
        )
    return funds
