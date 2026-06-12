"""Fund universe endpoints (F8.2): navigable list, full profile and CSV.

DB-only contract: every read is served from the local F8.1 snapshot tables
(`funds`, `fund_risk_latest`, `fund_nav`, `fund_holdings`) — these routes
NEVER talk to the mother DB or Tiingo. Routes are thin: SQL, the sort
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
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.funds import (
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
from app.services import funds_catalog as catalog
from app.services.screener import render_csv

router = APIRouter(tags=["funds"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

FundTypeParam = Literal["etf", "mmf", "mutual_fund"]
AssetClassParam = Literal["equity", "fixed_income", "cash", "alternatives"]


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
    """Whitelist gate BEFORE the service builds any SQL."""
    if sort not in catalog.SORT_WHITELIST:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot sort by {sort!r}: not a whitelisted funds column. "
                f"Expected one of {sorted(catalog.SORT_WHITELIST)}."
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


@router.get("/funds/{instrument_id}", response_model=FundProfileResponse)
async def get_fund_profile(
    instrument_id: uuid.UUID, session: SessionDep
) -> FundProfileResponse:
    """Full profile: identity + all risk metrics + 2y NAV (~260 points,
    decimated server-side) + latest top holdings (top-50-truncated source)."""
    profile = await catalog.fetch_fund_profile(session, instrument_id)
    if profile is None:
        raise HTTPException(
            status_code=404, detail=f"Fund {instrument_id} not found."
        )
    fund = profile.fund
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
        expense_ratio=float(fund.expense_ratio) if fund.expense_ratio is not None else None,
        aum_usd=float(fund.aum_usd) if fund.aum_usd is not None else None,
        primary_benchmark=fund.primary_benchmark,
        inception_date=fund.inception_date,
        domicile=fund.domicile,
        currency=fund.currency,
        synced_at=fund.synced_at,
        source_calc_date=fund.source_calc_date,
        source_nav_max_date=fund.source_nav_max_date,
        risk=FundRiskOut.model_validate(profile.risk) if profile.risk else None,
        nav=[FundNavPoint(date=d, nav=v) for d, v in profile.nav],
        holdings=FundHoldingsOut(
            report_date=profile.holdings_report_date,
            items=[FundHoldingItem.model_validate(h) for h in profile.holdings],
            pct_of_nav_total=profile.holdings_pct_of_nav_total,
            is_top50_truncated=profile.is_top50_truncated,
        ),
        # Share classes (F8.6b) — expense_ratio asc NULLS LAST; any class is
        # priced with the series NAV as a proxy.
        classes=[FundClassOut.model_validate(c) for c in profile.classes],
    )
