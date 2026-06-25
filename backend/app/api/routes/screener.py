"""Screener endpoints (F6.4): metric catalog, persisted screens CRUD, the
Build payload (universe distribution + headline count) and the results table
with CSV export.

DB-only contract: every read is served from the local
`screener_equity_snapshot_mv` active-equity snapshot — these routes NEVER talk
to Tiingo.
Routes are thin: SQL and the histogram/CSV helpers live in
``app.services.screener``; the metric catalog in ``app.screener.catalog``.

Error mapping (fail loud, never silently empty):
- unknown screen / unknown filter row                  -> 404
- duplicate screen name (create/rename)                -> 409
- metric_code outside the catalog (incl. injection
  attempts) / min > max / bad sort column              -> 422
- metric column with zero non-NULL rows (build)        -> 422
  ("metrics snapshot not computed yet — run compute_screener_metrics");
  on the filter upsert/delete response the same condition degrades to
  ``distribution: null`` because the WRITE itself succeeded.
- empty screener snapshot on /results                  -> 200 with total=0
  (a legitimately empty cross-section, not an error).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_session
from app.models.screen import Screen
from app.schemas.screener import (
    BuildAllResponse,
    BuildResponse,
    DistributionOut,
    FilterBody,
    FilterReorder,
    FilterUpdateResponse,
    MetricBuildOut,
    MetricDefOut,
    ResultsColumnOut,
    ScreenCreate,
    ScreenListItem,
    ScreenOut,
    ScreenPatch,
    ScreenResultsResponse,
)
from app.screener.catalog import CATALOG, MetricDef, get_metric
from app.services import screener as screener_service

# Public catalog: metric definitions are not user data.
public_router = APIRouter(prefix="/screener", tags=["screener"])

# Saved screens are user data.
router = APIRouter(
    prefix="/screener",
    tags=["screener"],
    dependencies=[Depends(get_current_user)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def _metric_or_422(metric_code: str) -> MetricDef:
    """Resolve a user-supplied metric code through the catalog whitelist."""
    metric = get_metric(metric_code)
    if metric is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown metric code {metric_code!r}: not in the screener catalog.",
        )
    return metric


async def _screen_or_404(
    session: AsyncSession, screen_id: int, owner_sub: str
) -> Screen:
    screen = await screener_service.get_screen(session, screen_id, owner_sub)
    if screen is None:
        raise HTTPException(status_code=404, detail=f"Screen {screen_id} not found.")
    return screen


async def _build_payload(
    session: AsyncSession, screen: Screen, metric: MetricDef
) -> tuple[DistributionOut | None, int, int]:
    """Distribution (null when the snapshot has no data), headline count, available count."""
    available_count = await screener_service.count_metric_available(session, metric.code)
    try:
        distribution = await screener_service.compute_distribution(session, metric)
        distribution_out = DistributionOut.model_validate(distribution)
    except screener_service.MetricDataUnavailableError:
        distribution_out = None
    headline_count = await screener_service.count_matching(session, screen.filters)
    return distribution_out, headline_count, available_count


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@public_router.get("/metrics", response_model=list[MetricDefOut])
async def get_metric_catalog() -> list[MetricDefOut]:
    """The static metric catalog (categories + preset bands) — drives Select Metrics."""
    return [MetricDefOut.model_validate(metric) for metric in CATALOG]


# ---------------------------------------------------------------------------
# Screen CRUD
# ---------------------------------------------------------------------------


@router.post("/screens", response_model=ScreenOut, status_code=201)
async def create_screen(
    payload: ScreenCreate, session: SessionDep, user: UserDep
) -> ScreenOut:
    """Create an empty screen (filters are added via PUT .../filters/{code})."""
    try:
        screen = await screener_service.create_screen(
            session, payload.name, user.sub, user.org_id
        )
    except screener_service.DuplicateScreenNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ScreenOut.model_validate(screen)


@router.get("/screens", response_model=list[ScreenListItem])
async def list_screens(session: SessionDep, user: UserDep) -> list[ScreenListItem]:
    """List screens (id order), hard-capped at the service's LIST_HARD_CAP."""
    rows = await screener_service.list_screens(session, user.sub)
    return [ScreenListItem.model_validate(row) for row in rows]


@router.get("/screens/{screen_id}", response_model=ScreenOut)
async def get_screen(screen_id: int, session: SessionDep, user: UserDep) -> ScreenOut:
    """One screen with its filters (position order)."""
    return ScreenOut.model_validate(await _screen_or_404(session, screen_id, user.sub))


@router.patch("/screens/{screen_id}", response_model=ScreenOut)
async def patch_screen(
    screen_id: int, payload: ScreenPatch, session: SessionDep, user: UserDep
) -> ScreenOut:
    """Rename a screen."""
    try:
        screen = await screener_service.rename_screen(
            session, screen_id, user.sub, payload.name
        )
    except screener_service.DuplicateScreenNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if screen is None:
        raise HTTPException(status_code=404, detail=f"Screen {screen_id} not found.")
    return ScreenOut.model_validate(screen)


@router.delete("/screens/{screen_id}", status_code=204)
async def delete_screen(screen_id: int, session: SessionDep, user: UserDep) -> None:
    """Delete a screen; its filters cascade away at the DB level."""
    deleted = await screener_service.delete_screen(session, screen_id, user.sub)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Screen {screen_id} not found.")


# ---------------------------------------------------------------------------
# Filter upsert / delete (one round-trip powers the Build UI)
# ---------------------------------------------------------------------------


@router.put(
    "/screens/{screen_id}/filters/{metric_code}", response_model=FilterUpdateResponse
)
async def put_filter(
    screen_id: int,
    metric_code: str,
    payload: FilterBody,
    session: SessionDep,
    user: UserDep,
) -> FilterUpdateResponse:
    """Upsert one filter (bounds null = unbounded; both null = metric selected).

    Responds with the updated screen, the metric's universe distribution
    (null when the snapshot has no data for it) and the new headline count.
    """
    metric = _metric_or_422(metric_code)
    await _screen_or_404(session, screen_id, user.sub)
    await screener_service.upsert_filter(
        session, screen_id, metric.code, payload.min_value, payload.max_value
    )
    screen = await _screen_or_404(session, screen_id, user.sub)
    distribution, headline_count, available_count = await _build_payload(session, screen, metric)
    return FilterUpdateResponse(
        screen=ScreenOut.model_validate(screen),
        distribution=distribution,
        headline_count=headline_count,
        available_count=available_count,
    )


@router.delete(
    "/screens/{screen_id}/filters/{metric_code}", response_model=FilterUpdateResponse
)
async def delete_filter(
    screen_id: int, metric_code: str, session: SessionDep, user: UserDep
) -> FilterUpdateResponse:
    """Remove one filter; same Build payload as the upsert (count updates live)."""
    metric = _metric_or_422(metric_code)
    await _screen_or_404(session, screen_id, user.sub)
    deleted = await screener_service.delete_filter(session, screen_id, metric.code)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Filter {metric.code!r} not found in screen {screen_id}.",
        )
    screen = await _screen_or_404(session, screen_id, user.sub)
    distribution, headline_count, available_count = await _build_payload(session, screen, metric)
    return FilterUpdateResponse(
        screen=ScreenOut.model_validate(screen),
        distribution=distribution,
        headline_count=headline_count,
        available_count=available_count,
    )


@router.patch("/screens/{screen_id}/filters/reorder", response_model=ScreenOut)
async def reorder_filters(
    screen_id: int, payload: FilterReorder, session: SessionDep, user: UserDep
) -> ScreenOut:
    """Reorder a screen's filters; position drives the Results column order."""
    screen = await _screen_or_404(session, screen_id, user.sub)
    requested = list(payload.metric_codes)
    existing = {f.metric_code for f in screen.filters}
    if len(requested) != len(set(requested)):
        raise HTTPException(
            status_code=422, detail="Duplicate metric codes in reorder payload."
        )
    if set(requested) != existing:
        raise HTTPException(
            status_code=422,
            detail="Reorder payload must list exactly the screen's current filter codes.",
        )
    await screener_service.reorder_filters(session, screen_id, requested)
    return ScreenOut.model_validate(await _screen_or_404(session, screen_id, user.sub))


# ---------------------------------------------------------------------------
# Build: distribution + headline count
# ---------------------------------------------------------------------------


@router.get(
    "/screens/{screen_id}/build/{metric_code}", response_model=BuildResponse
)
async def build_metric(
    screen_id: int, metric_code: str, session: SessionDep, user: UserDep
) -> BuildResponse:
    """Histogram of one metric over the WHOLE active universe + headline count.

    The histogram ignores the screen's filters (it is the slider backdrop);
    the headline count honors ALL of them. counts_normalized is 0..1 —
    never pixel heights.
    """
    metric = _metric_or_422(metric_code)
    screen = await _screen_or_404(session, screen_id, user.sub)
    available_count = await screener_service.count_metric_available(session, metric.code)
    try:
        distribution = await screener_service.compute_distribution(session, metric)
    except screener_service.MetricDataUnavailableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    headline_count = await screener_service.count_matching(session, screen.filters)
    return BuildResponse(
        distribution=DistributionOut.model_validate(distribution),
        headline_count=headline_count,
        available_count=available_count,
    )


@router.get("/screens/{screen_id}/build", response_model=BuildAllResponse)
async def build_all(
    screen_id: int, session: SessionDep, user: UserDep
) -> BuildAllResponse:
    """Every filter's universe distribution + the live headline count, one round-trip.

    Feeds the Build panel's per-row sparklines and the active-row distribution
    in a single request (vs. one GET /build/{metric_code} per filter).
    """
    screen = await _screen_or_404(session, screen_id, user.sub)
    headline_count = await screener_service.count_matching(session, screen.filters)
    metrics: list[MetricBuildOut] = []
    for item in sorted(screen.filters, key=lambda f: f.position):
        metric = _metric_or_422(item.metric_code)
        available = await screener_service.count_metric_available(session, metric.code)
        try:
            distribution: DistributionOut | None = DistributionOut.model_validate(
                await screener_service.compute_distribution(session, metric)
            )
        except screener_service.MetricDataUnavailableError:
            distribution = None
        metrics.append(
            MetricBuildOut(
                metric_code=metric.code, distribution=distribution, available_count=available
            )
        )
    return BuildAllResponse(headline_count=headline_count, metrics=metrics)


# ---------------------------------------------------------------------------
# Results (+ CSV export)
# ---------------------------------------------------------------------------


def _results_query_parts(
    screen: Screen, sort: str
) -> list[tuple[str, str, str]]:
    """Validate the sort column against the screen's columns; return columns."""
    columns = screener_service.result_columns(screen.filters)
    if sort not in {code for code, _name, _data_type in columns}:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot sort by {sort!r}: not a column of this screen.",
        )
    return columns


@router.get("/screens/{screen_id}/results", response_model=ScreenResultsResponse)
async def get_results(
    screen_id: int,
    session: SessionDep,
    user: UserDep,
    sort: Annotated[str, Query(description="Column code to sort by.")] = "ticker",
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "asc",
    search: Annotated[
        str | None, Query(max_length=40, description="Ticker/name prefix match.")
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ScreenResultsResponse:
    """Matching tickers with the screen's columns (filter position order).

    An empty metrics snapshot is a legitimate 200 with total=0.
    """
    screen = await _screen_or_404(session, screen_id, user.sub)
    columns = _results_query_parts(screen, sort)
    rows, total = await screener_service.fetch_results(
        session,
        screen.filters,
        sort=sort,
        direction=direction,
        search=search,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ScreenResultsResponse(
        columns=[
            ResultsColumnOut(code=code, name=name, data_type=data_type)
            for code, name, data_type in columns
        ],
        rows=rows,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/screens/{screen_id}/results.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def get_results_csv(
    screen_id: int,
    session: SessionDep,
    user: UserDep,
    sort: Annotated[str, Query(description="Column code to sort by.")] = "ticker",
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "asc",
    search: Annotated[
        str | None, Query(max_length=40, description="Ticker/name prefix match.")
    ] = None,
) -> Response:
    """The same result set as /results, unpaginated, hard-capped at 5 000 rows."""
    screen = await _screen_or_404(session, screen_id, user.sub)
    columns = _results_query_parts(screen, sort)
    rows, _total = await screener_service.fetch_results(
        session,
        screen.filters,
        sort=sort,
        direction=direction,
        search=search,
        limit=screener_service.CSV_HARD_CAP,
        offset=0,
    )
    body = screener_service.render_csv(columns, rows)
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="screen_{screen_id}_results.csv"'
            )
        },
    )
