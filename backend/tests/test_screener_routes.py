"""Tests for the screener routes (app/api/routes/screener.py).

The persistence/read service is stubbed at its canonical module
(``app.services.screener``); the pure histogram pipeline stays LIVE in the
build tests (only the SQL read ``select_metric_values`` is stubbed) so the
linear/log-edge behavior is exercised through the route. No live network,
no live DB.
"""

import datetime as dt
import math
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.screener.catalog import CATALOG
from app.services import screener as screener_service

_CREATED = dt.datetime(2026, 6, 11, 12, 0, tzinfo=dt.UTC)

_INJECTION_CODE = "pe_ratio; DROP TABLE screener_metrics;--"


def _filter(
    metric_code: str = "pe_ratio",
    min_value: float | None = 10.0,
    max_value: float | None = 15.0,
    position: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        metric_code=metric_code, min_value=min_value, max_value=max_value, position=position
    )


def _screen(
    sid: int = 1,
    name: str = "My screen",
    filters: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=sid,
        name=name,
        created_at=_CREATED,
        updated_at=_CREATED,
        filters=filters or [],
    )


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _stub_get_screen(
    monkeypatch: pytest.MonkeyPatch, screen: SimpleNamespace | None
) -> None:
    async def fake_get(session: Any, screen_id: int) -> SimpleNamespace | None:
        return screen

    monkeypatch.setattr(screener_service, "get_screen", fake_get)


def _stub_count(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    async def fake_count(session: Any, filters: Any) -> int:
        return count

    monkeypatch.setattr(screener_service, "count_matching", fake_count)


def _stub_available_count(monkeypatch: pytest.MonkeyPatch, count: int = 10) -> None:
    async def fake_available(session: Any, code: str) -> int:
        return count

    monkeypatch.setattr(screener_service, "count_metric_available", fake_available)


def _stub_metric_values(monkeypatch: pytest.MonkeyPatch, values: list[float]) -> None:
    """Stub ONLY the SQL read — the histogram pipeline stays live."""

    async def fake_values(session: Any, code: str) -> list[float]:
        return values

    monkeypatch.setattr(screener_service, "select_metric_values", fake_values)


# ---------------------------------------------------------------------------
# GET /screener/metrics (catalog)
# ---------------------------------------------------------------------------


async def test_metric_catalog_serializes_every_metric() -> None:
    async with _client() as ac:
        response = await ac.get("/screener/metrics")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(CATALOG)
    pe = next(m for m in body if m["code"] == "pe_ratio")
    assert pe["name"] == "Price / Earnings (TTM)"
    assert pe["category"] == "Fundamentals: Valuation"
    assert pe["data_type"] == "float"
    custom = [p for p in pe["presets"] if p["name"] == "Custom"]
    assert custom == [{"name": "Custom", "min_value": None, "max_value": None}]
    banded = pe["presets"][2]
    assert banded == {"name": "10 to 15", "min_value": 10.0, "max_value": 15.0}


# ---------------------------------------------------------------------------
# Screen CRUD
# ---------------------------------------------------------------------------


async def test_create_screen_201(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[str] = []

    async def fake_create(session: Any, name: str) -> SimpleNamespace:
        received.append(name)
        return _screen(name=name)

    monkeypatch.setattr(screener_service, "create_screen", fake_create)
    async with _client() as ac:
        response = await ac.post("/screener/screens", json={"name": "  My screen  "})

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "My screen"
    assert body["filters"] == []
    assert received == ["My screen"]  # trimmed BEFORE the service sees it


async def test_create_screen_duplicate_name_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create(session: Any, name: str) -> SimpleNamespace:
        raise screener_service.DuplicateScreenNameError("A screen named 'X' already exists.")

    monkeypatch.setattr(screener_service, "create_screen", fake_create)
    async with _client() as ac:
        response = await ac.post("/screener/screens", json={"name": "X"})

    assert response.status_code == 409


async def test_create_screen_blank_name_422() -> None:
    async with _client() as ac:
        response = await ac.post("/screener/screens", json={"name": "   "})

    assert response.status_code == 422


async def test_list_screens(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list(session: Any) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                id=1, name="A", filter_count=2, created_at=_CREATED, updated_at=_CREATED
            )
        ]

    monkeypatch.setattr(screener_service, "list_screens", fake_list)
    async with _client() as ac:
        response = await ac.get("/screener/screens")

    assert response.status_code == 200
    assert response.json()[0]["filter_count"] == 2


async def test_get_screen_includes_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_screen(monkeypatch, _screen(filters=[_filter()]))
    async with _client() as ac:
        response = await ac.get("/screener/screens/1")

    assert response.status_code == 200
    assert response.json()["filters"] == [
        {"metric_code": "pe_ratio", "min_value": 10.0, "max_value": 15.0, "position": 0}
    ]


async def test_get_screen_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_screen(monkeypatch, None)
    async with _client() as ac:
        response = await ac.get("/screener/screens/99")

    assert response.status_code == 404


async def test_patch_screen_renames(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_rename(session: Any, screen_id: int, name: str) -> SimpleNamespace:
        return _screen(name=name)

    monkeypatch.setattr(screener_service, "rename_screen", fake_rename)
    async with _client() as ac:
        response = await ac.patch("/screener/screens/1", json={"name": "Renamed"})

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


async def test_patch_screen_404_and_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_missing(session: Any, screen_id: int, name: str) -> None:
        return None

    monkeypatch.setattr(screener_service, "rename_screen", fake_missing)
    async with _client() as ac:
        assert (await ac.patch("/screener/screens/9", json={"name": "N"})).status_code == 404

    async def fake_dup(session: Any, screen_id: int, name: str) -> SimpleNamespace:
        raise screener_service.DuplicateScreenNameError("dup")

    monkeypatch.setattr(screener_service, "rename_screen", fake_dup)
    async with _client() as ac:
        assert (await ac.patch("/screener/screens/1", json={"name": "N"})).status_code == 409


async def test_delete_screen_204_and_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delete(session: Any, screen_id: int) -> bool:
        return screen_id == 1

    monkeypatch.setattr(screener_service, "delete_screen", fake_delete)
    async with _client() as ac:
        assert (await ac.delete("/screener/screens/1")).status_code == 204
        assert (await ac.delete("/screener/screens/2")).status_code == 404


# ---------------------------------------------------------------------------
# PUT/DELETE filter
# ---------------------------------------------------------------------------


async def test_put_filter_unknown_metric_422_without_touching_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("service must not be reached")

    monkeypatch.setattr(screener_service, "upsert_filter", explode)
    monkeypatch.setattr(screener_service, "get_screen", explode)
    async with _client() as ac:
        response = await ac.put(
            "/screener/screens/1/filters/not_a_metric", json={"min_value": 1}
        )

    assert response.status_code == 422
    assert "not in the screener catalog" in response.json()["detail"]


async def test_put_filter_sql_injection_code_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("service must not be reached")

    monkeypatch.setattr(screener_service, "upsert_filter", explode)
    async with _client() as ac:
        response = await ac.put(
            f"/screener/screens/1/filters/{_INJECTION_CODE}", json={}
        )

    assert response.status_code == 422


async def test_put_filter_min_greater_than_max_422() -> None:
    async with _client() as ac:
        response = await ac.put(
            "/screener/screens/1/filters/pe_ratio",
            json={"min_value": 15, "max_value": 10},
        )

    assert response.status_code == 422


async def test_put_filter_upserts_and_returns_build_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upserts: list[tuple[int, str, float | None, float | None]] = []

    async def fake_upsert(
        session: Any, screen_id: int, code: str, lo: float | None, hi: float | None
    ) -> None:
        upserts.append((screen_id, code, lo, hi))

    monkeypatch.setattr(screener_service, "upsert_filter", fake_upsert)
    _stub_get_screen(monkeypatch, _screen(filters=[_filter()]))
    _stub_metric_values(monkeypatch, [5.0, 12.0, 14.0, 30.0])
    _stub_count(monkeypatch, 2)
    _stub_available_count(monkeypatch, 4)

    async with _client() as ac:
        response = await ac.put(
            "/screener/screens/1/filters/pe_ratio",
            json={"min_value": 10, "max_value": 15},
        )

    assert response.status_code == 200
    body = response.json()
    assert upserts == [(1, "pe_ratio", 10.0, 15.0)]
    assert body["screen"]["filters"][0]["metric_code"] == "pe_ratio"
    assert body["headline_count"] == 2
    assert body["available_count"] == 4
    assert len(body["distribution"]["bin_edges"]) == 41
    assert sum(body["distribution"]["counts"]) == 4
    assert max(body["distribution"]["counts_normalized"]) == 1.0


async def test_put_filter_sparse_snapshot_returns_null_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The WRITE succeeded — a data-less metric degrades to distribution: null."""

    async def fake_upsert(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(screener_service, "upsert_filter", fake_upsert)
    _stub_get_screen(monkeypatch, _screen(filters=[_filter()]))
    _stub_metric_values(monkeypatch, [])
    _stub_count(monkeypatch, 0)
    _stub_available_count(monkeypatch, 0)

    async with _client() as ac:
        response = await ac.put("/screener/screens/1/filters/pe_ratio", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["distribution"] is None
    assert body["headline_count"] == 0
    assert body["available_count"] == 0


async def test_put_filter_screen_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_screen(monkeypatch, None)
    async with _client() as ac:
        response = await ac.put("/screener/screens/9/filters/pe_ratio", json={})

    assert response.status_code == 404


async def test_delete_filter_returns_build_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_delete(session: Any, screen_id: int, code: str) -> bool:
        return True

    monkeypatch.setattr(screener_service, "delete_filter", fake_delete)
    _stub_get_screen(monkeypatch, _screen(filters=[]))
    _stub_metric_values(monkeypatch, [1.0, 2.0])
    _stub_count(monkeypatch, 3)
    _stub_available_count(monkeypatch, 2)

    async with _client() as ac:
        response = await ac.delete("/screener/screens/1/filters/pe_ratio")

    assert response.status_code == 200
    body = response.json()
    assert body["screen"]["filters"] == []
    assert body["headline_count"] == 3
    assert body["available_count"] == 2
    assert body["distribution"] is not None


async def test_delete_filter_missing_row_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delete(session: Any, screen_id: int, code: str) -> bool:
        return False

    monkeypatch.setattr(screener_service, "delete_filter", fake_delete)
    _stub_get_screen(monkeypatch, _screen())
    async with _client() as ac:
        response = await ac.delete("/screener/screens/1/filters/pe_ratio")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH filters/reorder
# ---------------------------------------------------------------------------


def _three_filter_screen() -> SimpleNamespace:
    return _screen(
        filters=[
            _filter("pe_ratio", 10.0, 15.0, position=0),
            _filter("market_cap", None, None, position=1),
            _filter("roe", 0.1, None, position=2),
        ]
    )


def _reorder(filters: list[SimpleNamespace], codes: list[str]) -> SimpleNamespace:
    """Return a screen whose filters are *filters* rewritten into *codes* order."""
    by_code = {f.metric_code: f for f in filters}
    reordered = [
        _filter(code, by_code[code].min_value, by_code[code].max_value, position=i)
        for i, code in enumerate(codes)
    ]
    return _screen(filters=reordered)


async def test_reorder_filters_rewrites_position_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # seeded screen has filters added in order: pe_ratio (0), market_cap (1), roe (2)
    original = _three_filter_screen()
    new_order = ["roe", "pe_ratio", "market_cap"]
    captured: list[list[str]] = []

    async def fake_reorder(session: Any, screen_id: int, codes: Any) -> None:
        captured.append(list(codes))

    # First get_screen → validation (original order); second → post-reorder response.
    screens = iter([original, _reorder(original.filters, new_order)])

    async def fake_get(session: Any, screen_id: int) -> SimpleNamespace:
        return next(screens)

    monkeypatch.setattr(screener_service, "reorder_filters", fake_reorder)
    monkeypatch.setattr(screener_service, "get_screen", fake_get)

    async with _client() as ac:
        resp = await ac.patch(
            "/screener/screens/1/filters/reorder",
            json={"metric_codes": new_order},
        )

    assert resp.status_code == 200
    assert captured == [new_order]
    codes = [f["metric_code"] for f in resp.json()["filters"]]
    assert codes == ["roe", "pe_ratio", "market_cap"]
    positions = [f["position"] for f in resp.json()["filters"]]
    assert positions == [0, 1, 2]


async def test_reorder_filters_rejects_mismatched_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("service must not be reached")

    monkeypatch.setattr(screener_service, "reorder_filters", explode)
    _stub_get_screen(monkeypatch, _three_filter_screen())

    async with _client() as ac:
        resp = await ac.patch(
            "/screener/screens/1/filters/reorder",
            json={"metric_codes": ["roe", "pe_ratio"]},  # missing market_cap
        )

    assert resp.status_code == 422


async def test_reorder_filters_unknown_screen_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("service must not be reached")

    monkeypatch.setattr(screener_service, "reorder_filters", explode)
    _stub_get_screen(monkeypatch, None)

    async with _client() as ac:
        resp = await ac.patch(
            "/screener/screens/999999/filters/reorder", json={"metric_codes": []}
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET build/{metric_code}
# ---------------------------------------------------------------------------


async def test_build_linear_distribution_and_headline_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_screen(monkeypatch, _screen(filters=[_filter()]))
    _stub_metric_values(monkeypatch, [float(v) / 100 for v in range(-20, 21)])
    _stub_count(monkeypatch, 7)
    _stub_available_count(monkeypatch, 41)

    async with _client() as ac:
        response = await ac.get("/screener/screens/1/build/ret_1y")

    assert response.status_code == 200
    body = response.json()
    edges = body["distribution"]["bin_edges"]
    assert len(edges) == 41
    steps = [b - a for a, b in zip(edges, edges[1:], strict=False)]
    assert all(math.isclose(s, steps[0], abs_tol=1e-12) for s in steps)
    assert body["headline_count"] == 7
    assert body["available_count"] == 41


async def test_build_market_cap_uses_log_spaced_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_screen(monkeypatch, _screen())
    _stub_metric_values(monkeypatch, [10.0**exp for exp in range(7, 13)])
    _stub_count(monkeypatch, 0)
    _stub_available_count(monkeypatch, 6)

    async with _client() as ac:
        response = await ac.get("/screener/screens/1/build/market_cap")

    assert response.status_code == 200
    edges = response.json()["distribution"]["bin_edges"]
    ratios = [b / a for a, b in zip(edges, edges[1:], strict=False)]
    assert all(math.isclose(r, ratios[0], rel_tol=1e-9) for r in ratios)


async def test_build_empty_column_422_with_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_screen(monkeypatch, _screen())
    _stub_metric_values(monkeypatch, [])
    _stub_available_count(monkeypatch, 0)

    async with _client() as ac:
        response = await ac.get("/screener/screens/1/build/pe_ratio")

    assert response.status_code == 422
    assert "compute_screener_metrics" in response.json()["detail"]


async def test_build_unknown_and_injection_codes_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_screen(monkeypatch, _screen())
    async with _client() as ac:
        assert (await ac.get("/screener/screens/1/build/nope")).status_code == 422
        assert (
            await ac.get(f"/screener/screens/1/build/{_INJECTION_CODE}")
        ).status_code == 422


async def test_build_screen_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_screen(monkeypatch, None)
    async with _client() as ac:
        response = await ac.get("/screener/screens/9/build/pe_ratio")

    assert response.status_code == 404


async def test_build_all_returns_every_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_screen(
        monkeypatch,
        _screen(filters=[_filter("pe_ratio", position=0), _filter("market_cap", position=1)]),
    )
    _stub_metric_values(monkeypatch, [float(v) for v in range(1, 30)])
    _stub_count(monkeypatch, 7)
    _stub_available_count(monkeypatch, 29)

    async with _client() as ac:
        response = await ac.get("/screener/screens/1/build")

    assert response.status_code == 200
    body = response.json()
    assert body["headline_count"] == 7
    codes = [m["metric_code"] for m in body["metrics"]]
    assert codes == ["pe_ratio", "market_cap"]  # position order
    for metric in body["metrics"]:
        assert metric["available_count"] == 29
        assert metric["distribution"] is not None


async def test_build_all_empty_screen_has_no_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_screen(monkeypatch, _screen(filters=[]))
    _stub_count(monkeypatch, 0)

    async with _client() as ac:
        response = await ac.get("/screener/screens/1/build")

    assert response.status_code == 200
    body = response.json()
    assert body["headline_count"] == 0
    assert body["metrics"] == []


async def test_build_all_screen_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_screen(monkeypatch, None)
    async with _client() as ac:
        response = await ac.get("/screener/screens/9/build")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET results (+ CSV)
# ---------------------------------------------------------------------------


_RESULT_ROWS: list[dict[str, str | float | None]] = [
    {"ticker": "AAPL", "name": "Apple Inc", "pe_ratio": 12.0, "market_cap": 3e12},
    {"ticker": "MSFT", "name": "Microsoft", "pe_ratio": 14.0, "market_cap": None},
]


def _stub_fetch(monkeypatch: pytest.MonkeyPatch, total: int = 2) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_fetch(
        session: Any, filters: Any, **kwargs: Any
    ) -> tuple[list[dict[str, str | float | None]], int]:
        calls.append(kwargs)
        return _RESULT_ROWS, total

    monkeypatch.setattr(screener_service, "fetch_results", fake_fetch)
    return calls


def _two_filter_screen() -> SimpleNamespace:
    return _screen(
        filters=[
            _filter("pe_ratio", 10.0, 15.0, position=0),
            _filter("market_cap", None, None, position=1),
        ]
    )


async def test_results_columns_rows_and_paging_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_screen(monkeypatch, _two_filter_screen())
    calls = _stub_fetch(monkeypatch, total=42)

    async with _client() as ac:
        response = await ac.get("/screener/screens/1/results")

    assert response.status_code == 200
    body = response.json()
    assert [c["code"] for c in body["columns"]] == ["ticker", "name", "pe_ratio", "market_cap"]
    assert body["columns"][3]["data_type"] == "currency"
    assert body["rows"] == _RESULT_ROWS
    assert body["total"] == 42
    assert body["page"] == 1
    assert body["page_size"] == 25
    assert calls == [
        {"sort": "ticker", "direction": "asc", "search": None, "limit": 25, "offset": 0}
    ]


async def test_results_sort_search_and_pagination_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_screen(monkeypatch, _two_filter_screen())
    calls = _stub_fetch(monkeypatch)

    async with _client() as ac:
        response = await ac.get(
            "/screener/screens/1/results",
            params={
                "sort": "market_cap",
                "dir": "desc",
                "search": "AA",
                "page": 3,
                "page_size": 50,
            },
        )

    assert response.status_code == 200
    assert calls == [
        {"sort": "market_cap", "direction": "desc", "search": "AA", "limit": 50, "offset": 100}
    ]


async def test_results_rejects_sort_outside_screen_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_screen(monkeypatch, _two_filter_screen())
    _stub_fetch(monkeypatch)

    async with _client() as ac:
        # vol_1y IS a catalog metric — but not one of this screen's columns.
        response = await ac.get("/screener/screens/1/results", params={"sort": "vol_1y"})
        injection = await ac.get(
            "/screener/screens/1/results", params={"sort": _INJECTION_CODE}
        )

    assert response.status_code == 422
    assert injection.status_code == 422


async def test_results_query_param_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_screen(monkeypatch, _two_filter_screen())
    _stub_fetch(monkeypatch)

    async with _client() as ac:
        too_big = await ac.get("/screener/screens/1/results", params={"page_size": 101})
        bad_dir = await ac.get("/screener/screens/1/results", params={"dir": "down"})
        bad_page = await ac.get("/screener/screens/1/results", params={"page": 0})

    assert too_big.status_code == 422
    assert bad_dir.status_code == 422
    assert bad_page.status_code == 422


async def test_results_screen_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_screen(monkeypatch, None)
    async with _client() as ac:
        response = await ac.get("/screener/screens/9/results")

    assert response.status_code == 404


async def test_results_csv_shape_headers_and_hard_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_screen(monkeypatch, _two_filter_screen())
    calls = _stub_fetch(monkeypatch)

    async with _client() as ac:
        response = await ac.get("/screener/screens/1/results.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="screen_1_results.csv"'
    )
    lines = response.text.strip().split("\n")
    assert lines[0] == "ticker,name,pe_ratio,market_cap"
    # pe_ratio is "float" → 6 d.p.; market_cap is "currency" → 2 d.p.
    assert lines[1] == "AAPL,Apple Inc,12.000000,3000000000000.00"
    assert lines[2] == "MSFT,Microsoft,14.000000,"  # NULL → empty cell
    # Unpaginated but bounded: the CSV export reads at most CSV_HARD_CAP rows.
    assert calls == [
        {
            "sort": "ticker",
            "direction": "asc",
            "search": None,
            "limit": screener_service.CSV_HARD_CAP,
            "offset": 0,
        }
    ]
