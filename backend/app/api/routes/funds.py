"""Fund universe endpoints (F8.2): navigable list, full profile and CSV.

DB-only contract: every read is served from the local catalog sources
(`funds_v`, `fund_risk_latest_mv`, `nav_timeseries`, `fund_holdings`) — these
routes NEVER talk to the mother DB or Tiingo. Routes are thin: SQL, the sort
whitelist and the pure CSV/decimation helpers live in
``app.services.funds_catalog``.

Error mapping (fail loud, never silently empty):
- unknown instrument_id                         -> 404
- sort column outside the whitelist             -> 422
- an empty funds table on /funds                -> 200 with total=0 and
  null staleness (a legitimately empty universe, not an error).

Classification caveat: ``strategy_label`` mirrors the mother DB, whose
automatic classifier has known errors — every response carries the fixed
``classification_note`` disclaimer (no per-row provenance is stored).

ETF exception: GET /funds/{id}/history may reuse local stock OHLCV rows when
the ETF ticker is present in eod_prices; otherwise it degrades to the local
nav_timeseries series (mode "nav"). It does not call Tiingo on the request path.
"""

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.expense_ratio import to_decimal_fraction
from app.core.config import get_settings
from app.core.datalake import get_datalake_session
from app.core.db import get_session
from app.models.fund import Fund
from app.schemas.fund_analysis import (
    FundActiveShareResponse,
    FundAnalysisResponse,
    FundEntityAnalyticsResponse,
    FundFactorsResponse,
    FundHoldingsTopResponse,
    FundInstitutionalRevealResponse,
    FundPeersResponse,
    FundRiskTimeseriesResponse,
    FundScatterResponse,
    FundStyleDriftResponse,
    HoldingReverseLookupResponse,
)
from app.schemas.funds import (
    FundBenchmarkOut,
    FundClassOut,
    FundHoldingItem,
    FundHoldingsOut,
    FundListItem,
    FundNavPoint,
    FundProfileResponse,
    FundRiskOut,
    FundsListResponse,
    FundsStaleness,
)
from app.schemas.lookthrough import (
    FundLookthroughResponse,
    LookthroughSummaryOut,
    build_dimensions,
)
from app.schemas.market import FundHistoryResponse, HistoryBar
from app.schemas.timeseries import LineSeriesResponse
from app.services import fund_analysis, fund_dossier_tier_b, lookthrough
from app.services import funds_catalog as catalog
from app.services._series import select_adj_ohlcv_rows as _select_adj_ohlcv_rows_impl
from app.services.screener import render_csv
from app.services.timeseries import (
    FUND_NAV_INTERVAL,
    RangeKey,
    range_start,
    to_ms_pairs,
)
from app.services.timeseries import (
    select_nav_line as _select_nav_line_impl,
)

router = APIRouter(tags=["funds"])

# Module-level aliases so tests can monkeypatch them directly on this module.
_select_adj_ohlcv_rows = _select_adj_ohlcv_rows_impl
_select_nav_line = _select_nav_line_impl

SessionDep = Annotated[AsyncSession, Depends(get_session)]
DatalakeDep = Annotated[AsyncSession, Depends(get_datalake_session)]

DimensionParam = Literal["issuer", "asset_class", "sector", "currency"]

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

FundTypeParam = Literal["etf", "mmf", "mutual_fund"]
AssetClassParam = Literal[
    "equity", "fixed_income", "cash", "alternatives", "multi_asset"
]


def _filters(
    search: str | None,
    fund_type: FundTypeParam | None,
    strategy_label: str | None,
    asset_class: AssetClassParam | None,
    expense_ratio_max: float | None,
    aum_min: float | None,
    sharpe_1y_min: float | None,
    volatility_1y_max: float | None,
    return_1y_min: float | None,
    max_drawdown_1y_min: float | None,
) -> catalog.FundFilters:
    return catalog.FundFilters(
        search=search,
        fund_type=fund_type,
        strategy_label=strategy_label,
        asset_class=asset_class,
        expense_ratio_max=expense_ratio_max,
        aum_min=aum_min,
        sharpe_1y_min=sharpe_1y_min,
        volatility_1y_max=volatility_1y_max,
        return_1y_min=return_1y_min,
        max_drawdown_1y_min=max_drawdown_1y_min,
    )


def _sort_or_422(sort: str) -> str:
    """Whitelist gate BEFORE the service builds any SQL.

    Validates against the materialized list whitelist — the SAME set the
    service uses to build the ORDER BY — so the gate and the query never
    disagree (the non-materialized SORT_WHITELIST omits ``manager_name`` and
    carries Tier-3 columns the funds_list_mv does not materialize).
    """
    if sort not in catalog.LIST_SORT_WHITELIST:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot sort by {sort!r}: not a whitelisted funds column. "
                f"Expected one of {sorted(catalog.LIST_SORT_WHITELIST)}."
            ),
        )
    return sort


# Shared query-parameter annotations (list + CSV take the same filter set).
SearchQ = Annotated[
    str | None, Query(max_length=80, description="Ticker/name substring match.")
]
StrategyQ = Annotated[
    str | None,
    Query(max_length=80, description="Strategy label substring match (free text)."),
]
SortQ = Annotated[
    str,
    Query(description="Whitelisted column of funds or fund_risk_latest."),
]
DirQ = Annotated[Literal["asc", "desc"], Query(alias="dir")]


@router.get("/funds", response_model=FundsListResponse)
async def list_funds(
    session: SessionDep,
    search: SearchQ = None,
    fund_type: FundTypeParam | None = None,
    strategy_label: StrategyQ = None,
    asset_class: AssetClassParam | None = None,
    expense_ratio_max: Annotated[float | None, Query(ge=0)] = None,
    aum_min: Annotated[float | None, Query(ge=0)] = None,
    sharpe_1y_min: float | None = None,
    volatility_1y_max: Annotated[float | None, Query(ge=0)] = None,
    return_1y_min: float | None = None,
    max_drawdown_1y_min: float | None = None,
    sort: SortQ = catalog.DEFAULT_SORT,
    direction: DirQ = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> FundsListResponse:
    """One page of the fund universe with headline risk metrics.

    Risk-metric bounds drop funds lacking that metric by definition.
    """
    _sort_or_422(sort)
    filters = _filters(
        search,
        fund_type,
        strategy_label,
        asset_class,
        expense_ratio_max,
        aum_min,
        sharpe_1y_min,
        volatility_1y_max,
        return_1y_min,
        max_drawdown_1y_min,
    )
    rows, total = await catalog.fetch_funds(
        session,
        filters,
        sort=sort,
        direction=direction,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    staleness = await catalog.fetch_staleness(session)
    return FundsListResponse(
        items=[FundListItem.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        staleness=FundsStaleness(
            synced_at=staleness.synced_at,
            source_calc_date=staleness.source_calc_date,
            source_nav_max_date=staleness.source_nav_max_date,
        ),
    )


@router.get("/funds/strategies", response_model=list[str])
async def list_fund_strategies(session: SessionDep) -> list[str]:
    """Distinct strategy labels across the universe (Strategy filter dropdown)."""
    return await catalog.fetch_strategies(session)


@router.get(
    "/funds.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def list_funds_csv(
    session: SessionDep,
    search: SearchQ = None,
    fund_type: FundTypeParam | None = None,
    strategy_label: StrategyQ = None,
    asset_class: AssetClassParam | None = None,
    expense_ratio_max: Annotated[float | None, Query(ge=0)] = None,
    aum_min: Annotated[float | None, Query(ge=0)] = None,
    sharpe_1y_min: float | None = None,
    volatility_1y_max: Annotated[float | None, Query(ge=0)] = None,
    return_1y_min: float | None = None,
    max_drawdown_1y_min: float | None = None,
    sort: SortQ = catalog.DEFAULT_SORT,
    direction: DirQ = "desc",
) -> Response:
    """The same result set as /funds, unpaginated, hard-capped at 5 000 rows."""
    _sort_or_422(sort)
    filters = _filters(
        search,
        fund_type,
        strategy_label,
        asset_class,
        expense_ratio_max,
        aum_min,
        sharpe_1y_min,
        volatility_1y_max,
        return_1y_min,
        max_drawdown_1y_min,
    )
    rows, _total = await catalog.fetch_funds(
        session,
        filters,
        sort=sort,
        direction=direction,
        limit=catalog.CSV_HARD_CAP,
        offset=0,
    )
    body = render_csv(catalog.CSV_COLUMNS, catalog.csv_rows(rows))
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="funds.csv"'},
    )


@router.get("/funds/scatter", response_model=FundScatterResponse)
async def get_funds_scatter(
    session: SessionDep,
    limit: Annotated[
        int, Query(ge=1, le=500, description="Maximum funds returned.")
    ] = 250,
) -> FundScatterResponse:
    """Columnar risk/return scatter payload for the funds landing page."""
    return await fund_analysis.fetch_funds_scatter(session, limit=limit)


@router.get(
    "/funds/{instrument_id}/factors",
    response_model=FundFactorsResponse,
)
async def get_fund_factors(
    instrument_id: uuid.UUID,
    session: SessionDep,
    datalake: DatalakeDep,
) -> FundFactorsResponse:
    """Tier B factor sensitivities and style-bias snapshot."""
    try:
        payload = await fund_dossier_tier_b.fetch_fund_factors(
            session, datalake, instrument_id
        )
    except fund_dossier_tier_b.TierBSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload


@router.get(
    "/funds/{instrument_id}/style-drift",
    response_model=FundStyleDriftResponse,
)
async def get_fund_style_drift(
    instrument_id: uuid.UUID,
    session: SessionDep,
    datalake: DatalakeDep,
    quarters: Annotated[
        int, Query(ge=1, le=60, description="Historical N-PORT periods returned.")
    ] = 40,
) -> FundStyleDriftResponse:
    """Tier B historical sector drift from N-PORT reports."""
    try:
        payload = await fund_dossier_tier_b.fetch_fund_style_drift(
            session, datalake, instrument_id, quarters=quarters
        )
    except fund_dossier_tier_b.TierBSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload


@router.get(
    "/funds/{instrument_id}/entity-analytics",
    response_model=FundEntityAnalyticsResponse,
)
async def get_fund_entity_analytics(
    instrument_id: uuid.UUID,
    session: SessionDep,
    datalake: DatalakeDep,
    window: Annotated[
        fund_dossier_tier_b.WindowKey,
        Query(description="Lookback window for Deep Analysis metrics."),
    ] = "1Y",
    benchmark_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional benchmark fund UUID for capture and relative stats."),
    ] = None,
) -> FundEntityAnalyticsResponse:
    """Tier B Deep Analysis analytics for one fund."""
    try:
        payload = await fund_dossier_tier_b.fetch_fund_entity_analytics(
            session, datalake, instrument_id, window=window, benchmark_id=benchmark_id
        )
    except (
        fund_analysis.FundAnalysisError,
        fund_dossier_tier_b.InvalidBenchmarkError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload


@router.get(
    "/funds/{instrument_id}/risk-timeseries",
    response_model=FundRiskTimeseriesResponse,
)
async def get_fund_risk_timeseries(
    instrument_id: uuid.UUID,
    session: SessionDep,
    datalake: DatalakeDep,
    from_date: Annotated[
        dt.date | None,
        Query(alias="from", description="Optional inclusive start date."),
    ] = None,
    to_date: Annotated[
        dt.date | None,
        Query(alias="to", description="Optional inclusive end date."),
    ] = None,
) -> FundRiskTimeseriesResponse:
    """Tier B drawdown, conditional volatility, and regime overlay."""
    try:
        payload = await fund_dossier_tier_b.fetch_fund_risk_timeseries(
            session,
            datalake,
            instrument_id,
            from_date=from_date,
            to_date=to_date,
        )
    except (fund_analysis.FundAnalysisError, fund_dossier_tier_b.TierBSourceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload


@router.get(
    "/funds/{instrument_id}/active-share",
    response_model=FundActiveShareResponse,
)
async def get_fund_active_share(
    instrument_id: uuid.UUID,
    session: SessionDep,
    datalake: DatalakeDep,
) -> FundActiveShareResponse:
    """Tier B holdings-based active share against the fund's primary benchmark."""
    try:
        payload = await fund_dossier_tier_b.fetch_fund_active_share(
            session, datalake, instrument_id
        )
    except (
        fund_dossier_tier_b.InvalidBenchmarkError,
        fund_dossier_tier_b.TierBSourceError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload


@router.get(
    "/funds/{instrument_id}/institutional-reveal",
    response_model=FundInstitutionalRevealResponse,
)
async def get_fund_institutional_reveal(
    instrument_id: uuid.UUID,
    session: SessionDep,
    datalake: DatalakeDep,
) -> FundInstitutionalRevealResponse:
    """Tier C 13F institutional overlap and holder network."""
    try:
        payload = await fund_dossier_tier_b.fetch_fund_institutional_reveal(
            session, datalake, instrument_id
        )
    except fund_dossier_tier_b.TierBSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload


@router.get(
    "/holdings/{cusip}/reverse-lookup",
    response_model=HoldingReverseLookupResponse,
)
async def get_holding_reverse_lookup(
    cusip: str,
    session: SessionDep,
    datalake: DatalakeDep,
) -> HoldingReverseLookupResponse:
    """Tier C reverse lookup from CUSIP to institutional and fund holders."""
    try:
        return await fund_dossier_tier_b.fetch_holding_reverse_lookup(
            session, datalake, cusip
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except fund_dossier_tier_b.TierBSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/funds/{instrument_id}", response_model=FundProfileResponse)
async def get_fund_profile(
    instrument_id: uuid.UUID, session: SessionDep
) -> FundProfileResponse:
    """Full profile: identity + all risk metrics + 2y NAV (~260 points,
    decimated server-side) + latest top holdings (display-capped; the full
    consolidated exposure lives in /funds/{id}/lookthrough)."""
    profile = await catalog.fetch_fund_profile(session, instrument_id)
    if profile is None:
        raise HTTPException(
            status_code=404, detail=f"Fund {instrument_id} not found."
        )
    fund = profile.fund
    benchmark = profile.benchmark
    benchmark_name = (
        benchmark.benchmark_name
        if benchmark is not None and benchmark.benchmark_name
        else fund.primary_benchmark
    )
    return FundProfileResponse(
        instrument_id=fund.instrument_id,
        series_id=fund.series_id,
        ticker=fund.ticker,
        isin=fund.isin,
        cusip=fund.cusip,
        lei=fund.lei,
        name=fund.name,
        fund_type=fund.fund_type,
        strategy_label=fund.strategy_label,
        asset_class=fund.asset_class,
        is_index=fund.is_index,
        expense_ratio=to_decimal_fraction(fund.expense_ratio),
        aum_usd=float(fund.aum_usd) if fund.aum_usd is not None else None,
        primary_benchmark=benchmark_name,
        benchmark=(
            FundBenchmarkOut(
                name=benchmark.benchmark_name,
                proxy_ticker=benchmark.benchmark_proxy_ticker,
                proxy_instrument_id=benchmark.benchmark_proxy_instrument_id,
                proxy_fit_quality_score=(
                    float(benchmark.benchmark_proxy_fit_quality_score)
                    if benchmark.benchmark_proxy_fit_quality_score is not None
                    else None
                ),
                proxy_asset_class=benchmark.benchmark_proxy_asset_class,
                resolution_method=benchmark.benchmark_resolution_method,
                resolution_conflict=benchmark.benchmark_resolution_conflict,
                proxy_candidates=benchmark.benchmark_proxy_candidates,
                canonical_name_matches=benchmark.benchmark_canonical_name_matches,
            )
            if benchmark is not None
            else None
        ),
        inception_date=fund.inception_date,
        domicile=fund.domicile,
        currency=fund.currency,
        # funds_v (a VIEW) carries no sync markers; the catalog service derives
        # and attaches these on the fund instance (Task 2.4 finalizes staleness).
        synced_at=getattr(fund, "synced_at", None),
        source_calc_date=getattr(fund, "source_calc_date", None),
        source_nav_max_date=getattr(fund, "source_nav_max_date", None),
        risk=FundRiskOut.model_validate(profile.risk) if profile.risk else None,
        nav=[FundNavPoint(date=d, nav=v) for d, v in profile.nav],
        holdings=FundHoldingsOut(
            report_date=profile.holdings_report_date,
            items=[FundHoldingItem.model_validate(h) for h in profile.holdings],
            pct_of_nav_total=profile.holdings_pct_of_nav_total,
        ),
        # Share classes (F8.6b) — expense_ratio asc NULLS LAST; any class is
        # priced with the series NAV as a proxy.
        classes=[FundClassOut.model_validate(c) for c in profile.classes],
    )


@router.get(
    "/funds/{instrument_id}/analysis",
    response_model=FundAnalysisResponse,
)
async def get_fund_analysis(
    instrument_id: uuid.UUID,
    session: SessionDep,
    range_: Annotated[
        RangeKey,
        Query(alias="range", description="Visible-range preset; MAX = full NAV history."),
    ] = "1Y",
    window: Annotated[
        int, Query(ge=10, le=252, description="Rolling window in NAV days (10..252).")
    ] = 252,
) -> FundAnalysisResponse:
    """Render-ready analysis payload for one fund NAV series."""
    try:
        payload = await fund_analysis.fetch_fund_analysis(
            session,
            instrument_id,
            range_key=range_,
            window=window,
            max_points=get_settings().price_series_max_points,
        )
    except fund_analysis.FundAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload


@router.get(
    "/funds/{instrument_id}/holdings/top",
    response_model=FundHoldingsTopResponse,
)
async def get_fund_holdings_top(
    instrument_id: uuid.UUID,
    session: SessionDep,
    datalake: DatalakeDep,
    limit: Annotated[
        int, Query(ge=1, le=50, description="Maximum top holdings returned.")
    ] = 25,
) -> FundHoldingsTopResponse:
    """Top holdings and sector breakdown for one fund."""
    payload = await fund_analysis.fetch_fund_holdings_top(
        session, datalake, instrument_id, limit=limit
    )
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload


@router.get(
    "/funds/{instrument_id}/peers",
    response_model=FundPeersResponse,
)
async def get_fund_peers(
    instrument_id: uuid.UUID,
    session: SessionDep,
    limit: Annotated[
        int, Query(ge=1, le=50, description="Maximum peer rows returned.")
    ] = 10,
) -> FundPeersResponse:
    """Peer cohort by fund strategy/risk classification."""
    payload = await fund_analysis.fetch_fund_peers(session, instrument_id, limit=limit)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload


@router.get(
    "/funds/{instrument_id}/lookthrough",
    response_model=FundLookthroughResponse,
)
async def get_fund_lookthrough(
    instrument_id: uuid.UUID,
    session: SessionDep,
    datalake: DatalakeDep,
    dimension: DimensionParam | None = None,
) -> FundLookthroughResponse:
    """Exposições look-through materializadas do fundo (Frente C).

    DB-first: lê a materialização do worker ``nport_lookthrough`` no
    data-lake — nenhuma expansão roda aqui. 404 quando o fundo não existe no
    universo local OU quando a série ainda não foi materializada (estado
    explícito, nunca uma resposta vazia silenciosa).
    """
    series_id = await lookthrough.get_fund_series(session, instrument_id)
    if series_id is None:
        raise HTTPException(
            status_code=404, detail=f"Fund {instrument_id} not found."
        )
    data = await lookthrough.fetch_series_lookthrough(
        datalake, series_id, dimension
    )
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Look-through not materialized for series {series_id} — "
                "the nport_lookthrough worker has not covered it yet."
            ),
        )
    return FundLookthroughResponse(
        instrument_id=instrument_id,
        series_id=data.series_id,
        report_date=data.report_date,
        dimensions=build_dimensions(data.exposures, only=dimension),
        summary=LookthroughSummaryOut(
            sum_pct_total=data.summary.sum_pct_total,
            direct_pct=data.summary.direct_pct,
            indirect_pct=data.summary.indirect_pct,
            expanded_fund_pct=data.summary.expanded_fund_pct,
            nondecomposable_fund_pct=data.summary.nondecomposable_fund_pct,
            derivatives_gross_pct=data.summary.derivatives_gross_pct,
            derivatives_net_pct=data.summary.derivatives_net_pct,
            unidentified_pct=data.summary.unidentified_pct,
            coverage_pct=data.summary.coverage_pct,
            n_holdings=data.summary.n_holdings,
            n_children_expanded=data.summary.n_children_expanded,
            oldest_report_date=data.summary.oldest_report_date,
        ),
    )


# ---------------------------------------------------------------------------
# History helpers (module-level so tests can monkeypatch them individually)
# ---------------------------------------------------------------------------


async def _get_fund(session: AsyncSession, instrument_id: uuid.UUID) -> Fund | None:
    return await session.get(Fund, instrument_id)


async def _select_nav_rows(
    session: AsyncSession, instrument_id: uuid.UUID, start: dt.date, end: dt.date
) -> list[tuple[dt.date, float]]:
    """(nav_date, nav) em [start, end], ASC, NAVs nulos descartados.

    Lê a hypertable bruta ``nav_timeseries`` (Task 2.4), não o snapshot
    ``fund_nav`` aposentado; mesmo shape de retorno.
    """
    result = await session.execute(
        text(
            "SELECT nav_date, nav FROM nav_timeseries "
            "WHERE instrument_id = :iid AND nav_date >= :start "
            "AND nav_date <= :end AND nav IS NOT NULL "
            "ORDER BY nav_date"
        ),
        {"iid": str(instrument_id), "start": start, "end": end},
    )
    return [(d, float(v)) for d, v in result.all()]


def _ms(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp() * 1000)


@router.get("/funds/{instrument_id}/history", response_model=FundHistoryResponse)
async def get_fund_history(
    instrument_id: uuid.UUID,
    session: SessionDep,
    bars: Annotated[
        int, Query(ge=30, le=5000, description="Nº de barras diárias mais recentes.")
    ] = 2520,
) -> FundHistoryResponse:
    """Série do fundo no contrato do chart interativo ({t,o,h,l,c,v} + mode).

    ETF com ticker → OHLCV ajustado de eod_prices (mesmo caminho dos stocks,
    sem warm on-demand); demais fundos (ou ETF sem cobertura local) → NAV de
    nav_timeseries com o=h=l=c=nav, v=0.
    """
    fund = await _get_fund(session, instrument_id)
    if fund is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")

    today = dt.date.today()
    start = today - dt.timedelta(days=int(bars * 1.6) + 10)

    if fund.fund_type == "etf" and fund.ticker:
        symbol = fund.ticker.strip().upper()
        rows = await _select_adj_ohlcv_rows(session, symbol, start, today)
        if rows:
            rows = rows[-bars:]
            return FundHistoryResponse(
                instrument_id=instrument_id,
                ticker=symbol,
                mode="ohlcv",
                count=len(rows),
                bars=[
                    HistoryBar(t=_ms(d), o=o, h=h, l=lo, c=c, v=int(v or 0))
                    for d, o, h, lo, c, v in rows
                ],
            )

    nav_rows = await _select_nav_rows(session, instrument_id, start, today)
    if not nav_rows:
        raise HTTPException(
            status_code=404, detail=f"No price or NAV history for fund {instrument_id}."
        )
    nav_rows = nav_rows[-bars:]
    return FundHistoryResponse(
        instrument_id=instrument_id,
        ticker=fund.ticker,
        mode="nav",
        count=len(nav_rows),
        bars=[HistoryBar(t=_ms(d), o=v, h=v, l=v, c=v, v=0) for d, v in nav_rows],
    )


@router.get("/funds/{instrument_id}/timeseries", response_model=LineSeriesResponse)
async def get_fund_timeseries(
    instrument_id: uuid.UUID,
    session: SessionDep,
    range_: Annotated[
        RangeKey, Query(alias="range", description="Visible range preset.")
    ] = "1Y",
) -> LineSeriesResponse:
    """Daily fund NAV line in Highcharts arrays.

    Every range reads the same DB-first daily CAGG; the range only changes the
    date floor.
    """
    today = dt.date.today()
    start = range_start(range_, today)
    rows = await _select_nav_line(session, str(instrument_id), start)
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"No NAV history for fund {instrument_id}."
        )
    return LineSeriesResponse(
        id=str(instrument_id), interval=FUND_NAV_INTERVAL, series=to_ms_pairs(rows)
    )
