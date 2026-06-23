"""Cache-first read for the Tier C institutional reveal.

The artifact cache (fund_institutional_reveal_latest_mv) is best-effort: a hit
deserializes the stored payload back into the response model; a miss, a missing
table, or a payload that no longer matches the current schema all fall through
to an on-the-fly recompute. These tests exercise that contract with fakes (no DB).
"""

import datetime as dt
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.fund_analysis import (
    FundInstitutionalRevealResponse,
    HolderNetwork,
    HolderNetworkNode,
    InstitutionalHolder,
    InstitutionalOverlapSecurity,
)
from app.services import fund_dossier_tier_b as tier_b

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


def _sample_response(series_id: str = "S1") -> FundInstitutionalRevealResponse:
    return FundInstitutionalRevealResponse(
        instrument_id=_FUND_ID,
        series_id=series_id,
        fund_name="Test Fund",
        holdings_report_date=dt.date(2026, 3, 31),
        period=dt.date(2026, 3, 31),
        top_holders=[
            InstitutionalHolder(
                cik="0001", manager_name="Manager One", value_usd=1000.0,
                shares=10.0, holding_count=2, period=dt.date(2026, 3, 31),
                report_date=dt.date(2026, 3, 31),
            )
        ],
        overlap=[
            InstitutionalOverlapSecurity(
                cusip="037833100", name="Apple", fund_pct_of_nav=0.1,
                institutional_value_usd=5000.0, institution_count=3,
                top_managers=["Manager One", "Manager Two"],
            )
        ],
        holder_network=HolderNetwork(
            nodes=[HolderNetworkNode(id="fund:1", label="TST", type="fund")],
            edges=[],
        ),
        empty_state=None,
    )


class _FakeResult:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[Any, ...] | None:
        return self._row


class _FakeDatalake:
    """Returns a canned (payload,) row for the cache SELECT."""

    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row
        self.calls = 0

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        self.calls += 1
        return _FakeResult(self._row)


async def test_read_cached_reveal_roundtrip_dict() -> None:
    resp = _sample_response()
    payload = resp.model_dump(mode="json")
    out = await tier_b._read_cached_reveal(_FakeDatalake((payload,)), "S1")
    assert out == resp


async def test_read_cached_reveal_roundtrip_json_string() -> None:
    # asyncpg often returns jsonb as a raw string — must json.loads it.
    resp = _sample_response()
    payload_str = json.dumps(resp.model_dump(mode="json"))
    out = await tier_b._read_cached_reveal(_FakeDatalake((payload_str,)), "S1")
    assert out == resp


async def test_read_cached_reveal_miss_returns_none() -> None:
    out = await tier_b._read_cached_reveal(_FakeDatalake(None), "S1")
    assert out is None


async def test_read_cached_reveal_schema_mismatch_returns_none() -> None:
    # extra="forbid" → an unexpected key must fall through to recompute.
    payload = _sample_response().model_dump(mode="json")
    payload["unexpected_key"] = 1
    out = await tier_b._read_cached_reveal(_FakeDatalake((payload,)), "S1")
    assert out is None


async def test_fetch_uses_cache_and_skips_compute(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _sample_response("S9")
    payload = resp.model_dump(mode="json")

    fund = SimpleNamespace(instrument_id=_FUND_ID, series_id="S9", name="TST", ticker="TST")

    async def fake_fund_or_none(session: Any, instrument_id: uuid.UUID) -> Any:
        return fund

    async def boom_compute(*a: Any, **k: Any) -> Any:
        raise AssertionError("compute must not run on a cache hit")

    monkeypatch.setattr(tier_b, "_fund_or_none", fake_fund_or_none)
    monkeypatch.setattr(tier_b, "_compute_fund_institutional_reveal", boom_compute)

    out = await tier_b.fetch_fund_institutional_reveal(
        session=None, datalake=_FakeDatalake((payload,)), instrument_id=_FUND_ID
    )
    assert out == resp


async def test_fetch_falls_through_to_compute_on_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    fund = SimpleNamespace(instrument_id=_FUND_ID, series_id="S9", name="TST", ticker="TST")
    computed = _sample_response("S9")

    async def fake_fund_or_none(session: Any, instrument_id: uuid.UUID) -> Any:
        return fund

    async def fake_compute(session: Any, datalake: Any, fund_arg: Any) -> Any:
        return computed

    monkeypatch.setattr(tier_b, "_fund_or_none", fake_fund_or_none)
    monkeypatch.setattr(tier_b, "_compute_fund_institutional_reveal", fake_compute)

    out = await tier_b.fetch_fund_institutional_reveal(
        session=None, datalake=_FakeDatalake(None), instrument_id=_FUND_ID
    )
    assert out is computed
