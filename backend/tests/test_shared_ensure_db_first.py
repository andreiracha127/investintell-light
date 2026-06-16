"""``ensure_eod_or_http_error`` é a fronteira do request-path HTTP.

Sob a Estratégia B, todo caminho de request lê DB-first: stale é servido do DB
sem fetch síncrono (o worker de aquecimento mantém o universo quente); só cold
absoluto busca. Por isso o helper HTTP delega a ``ensure_eod_data`` com
``db_first=True`` por padrão — com opt-out explícito para casos futuros.
"""

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api import _shared


async def test_http_helper_is_db_first_by_default() -> None:
    with patch.object(_shared, "ensure_eod_data", new=AsyncMock()) as m:
        await _shared.ensure_eod_or_http_error(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            ["AAPL"],
            dt.date(2026, 1, 1),
            dt.date(2026, 6, 1),
        )
    assert m.await_args is not None
    assert m.await_args.kwargs.get("db_first") is True


async def test_http_helper_db_first_can_be_overridden() -> None:
    with patch.object(_shared, "ensure_eod_data", new=AsyncMock()) as m:
        await _shared.ensure_eod_or_http_error(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            ["AAPL"],
            dt.date(2026, 1, 1),
            dt.date(2026, 6, 1),
            db_first=False,
        )
    assert m.await_args is not None
    assert m.await_args.kwargs.get("db_first") is False


async def test_http_helper_times_out_slow_cold_fetch_to_503() -> None:
    """A synchronous cold fetch exceeding the deadline becomes a 503, not a hang.

    Caps the latency tail: the request never waits longer than the deadline on a
    slow/hung provider call.
    """

    async def _slow_ensure(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(0.5)

    with patch.object(_shared, "ensure_eod_data", new=_slow_ensure):
        with pytest.raises(HTTPException) as exc_info:
            await _shared.ensure_eod_or_http_error(
                object(),  # type: ignore[arg-type]
                object(),  # type: ignore[arg-type]
                ["AAPL"],
                dt.date(2026, 1, 1),
                dt.date(2026, 6, 1),
                deadline_seconds=0.01,
            )
    assert exc_info.value.status_code == 503


async def test_http_helper_fast_call_under_deadline_succeeds() -> None:
    """A fast ensure (no cold fetch) well under the deadline is unaffected."""
    with patch.object(_shared, "ensure_eod_data", new=AsyncMock()):
        await _shared.ensure_eod_or_http_error(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            ["AAPL"],
            dt.date(2026, 1, 1),
            dt.date(2026, 6, 1),
            deadline_seconds=5.0,
        )
