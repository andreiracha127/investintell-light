"""Tests for TiingoClient — no real network, no real sleeps."""

import datetime
import json
from unittest.mock import patch

import httpx
import pytest

from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import (
    TiingoAuthError,
    TiingoBadResponseError,
    TiingoNotFoundError,
    TiingoRateLimitError,
)
from app.tiingo.rate_limiter import TokenBucketLimiter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_EOD_PAYLOAD = [
    {
        "date": "2024-01-02T00:00:00+00:00",
        "open": 185.0,
        "high": 188.0,
        "low": 184.5,
        "close": 186.0,
        "volume": 1000000,
        "adjOpen": 185.0,
        "adjHigh": 188.0,
        "adjLow": 184.5,
        "adjClose": 186.0,
        "adjVolume": 1000000,
        "divCash": 0.0,
        "splitFactor": 1.0,
    },
    {
        "date": "2024-01-03T00:00:00+00:00",
        "open": 186.0,
        "high": 190.0,
        "low": 185.0,
        "close": 189.0,
        "volume": 1200000,
        "adjOpen": 186.0,
        "adjHigh": 190.0,
        "adjLow": 185.0,
        "adjClose": 189.0,
        "adjVolume": 1200000,
        "divCash": 0.0,
        "splitFactor": 1.0,
    },
]

_META_PAYLOAD = {
    "ticker": "aapl",
    "name": "Apple Inc",
    "exchangeCode": "NASDAQ",
    "description": "Apple designs and sells consumer electronics.",
    "startDate": "1980-12-12",
    "endDate": "2024-01-03",
}


def make_limiter() -> TokenBucketLimiter:
    """Return a limiter with enormous caps for client tests (rate-limiting is tested separately)."""
    return TokenBucketLimiter(
        rate_per_sec=1000.0,
        burst=1000,
        hourly_cap=9000,
        daily_cap=90000,
    )


def make_response(status_code: int, body: str | bytes | dict | list) -> httpx.Response:
    """Build a minimal httpx.Response for MockTransport use."""
    if isinstance(body, (dict, list)):
        content = json.dumps(body).encode()
        headers = {"content-type": "application/json"}
    elif isinstance(body, str):
        content = body.encode()
        headers = {"content-type": "text/plain"}
    else:
        content = body
        headers = {"content-type": "text/plain"}
    return httpx.Response(status_code, content=content, headers=headers)


def single_response_transport(response: httpx.Response) -> httpx.MockTransport:
    """Return a MockTransport that always returns *response*."""

    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return httpx.MockTransport(handler)


def response_sequence_transport(responses: list[httpx.Response]) -> httpx.MockTransport:
    """Return a MockTransport that returns responses in sequence."""
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return next(it)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Construction guard
# ---------------------------------------------------------------------------


def test_empty_token_raises_auth_error_at_construction() -> None:
    limiter = make_limiter()
    with pytest.raises(TiingoAuthError):
        TiingoClient(token=None, limiter=limiter)


def test_empty_string_token_raises_auth_error_at_construction() -> None:
    limiter = make_limiter()
    with pytest.raises(TiingoAuthError):
        TiingoClient(token="", limiter=limiter)


# ---------------------------------------------------------------------------
# Happy path: EOD prices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_eod_prices_happy_path() -> None:
    """200 JSON with 2 rows → list of TiingoEodRow with correct fields."""
    transport = single_response_transport(make_response(200, _EOD_PAYLOAD))
    http = httpx.AsyncClient(transport=transport)

    async def no_sleep(_: float) -> None:
        pass

    with patch("asyncio.sleep", side_effect=no_sleep):
        client = TiingoClient(token="testtoken", limiter=make_limiter(), http_client=http)
        rows = await client.get_eod_prices(
            "AAPL",
            datetime.date(2024, 1, 2),
            datetime.date(2024, 1, 3),
        )

    assert len(rows) == 2
    assert rows[0].ticker == "AAPL"
    assert rows[0].date == datetime.date(2024, 1, 2)
    assert rows[0].close == 186.0
    assert rows[0].volume == 1_000_000
    assert rows[1].date == datetime.date(2024, 1, 3)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_404_raises_not_found() -> None:
    transport = single_response_transport(make_response(404, "Not found"))
    http = httpx.AsyncClient(transport=transport)

    async def no_sleep(_: float) -> None:
        pass

    with patch("asyncio.sleep", side_effect=no_sleep):
        client = TiingoClient(token="testtoken", limiter=make_limiter(), http_client=http)
        with pytest.raises(TiingoNotFoundError):
            await client.get_eod_prices(
                "XXXX", datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)
            )


@pytest.mark.asyncio
async def test_401_raises_auth_error() -> None:
    transport = single_response_transport(make_response(401, "Unauthorized"))
    http = httpx.AsyncClient(transport=transport)

    async def no_sleep(_: float) -> None:
        pass

    with patch("asyncio.sleep", side_effect=no_sleep):
        client = TiingoClient(token="testtoken", limiter=make_limiter(), http_client=http)
        with pytest.raises(TiingoAuthError):
            await client.get_eod_prices(
                "AAPL", datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)
            )


@pytest.mark.asyncio
async def test_disguised_rate_limit_200_raises_rate_limit_error() -> None:
    """200 with plain-text 'You have run over ...' → TiingoRateLimitError."""
    body = "You have run over your 500 symbol look up limit for the month."
    transport = single_response_transport(make_response(200, body))
    http = httpx.AsyncClient(transport=transport)

    async def no_sleep(_: float) -> None:
        pass

    with patch("asyncio.sleep", side_effect=no_sleep):
        client = TiingoClient(token="testtoken", limiter=make_limiter(), http_client=http)
        with pytest.raises(TiingoRateLimitError):
            await client.get_eod_prices(
                "AAPL", datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)
            )


@pytest.mark.asyncio
async def test_non_json_200_raises_bad_response_error() -> None:
    """200 with arbitrary HTML that is NOT rate-limit wording → TiingoBadResponseError."""
    body = "<html><body>Oops, something went wrong.</body></html>"
    transport = single_response_transport(make_response(200, body))
    http = httpx.AsyncClient(transport=transport)

    async def no_sleep(_: float) -> None:
        pass

    with patch("asyncio.sleep", side_effect=no_sleep):
        client = TiingoClient(token="testtoken", limiter=make_limiter(), http_client=http)
        with pytest.raises(TiingoBadResponseError):
            await client.get_eod_prices(
                "AAPL", datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)
            )


@pytest.mark.asyncio
async def test_503_then_200_succeeds_after_retry() -> None:
    """503 on first attempt, 200 JSON on second → success; backoff sleep was called."""
    responses = [
        make_response(503, "Service Unavailable"),
        make_response(200, _EOD_PAYLOAD),
    ]
    transport = response_sequence_transport(responses)
    http = httpx.AsyncClient(transport=transport)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with patch("asyncio.sleep", side_effect=fake_sleep):
        client = TiingoClient(
            token="testtoken",
            limiter=make_limiter(),
            http_client=http,
            max_retries=3,
        )
        rows = await client.get_eod_prices(
            "AAPL",
            datetime.date(2024, 1, 2),
            datetime.date(2024, 1, 3),
        )

    assert len(rows) == 2
    # At least one sleep call from the backoff.
    assert len(sleep_calls) >= 1
    assert sleep_calls[0] >= 0.5  # first back-off: 0.5 * 2^0 = 0.5s (+jitter)


# ---------------------------------------------------------------------------
# Ticker meta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ticker_meta_happy_path() -> None:
    transport = single_response_transport(make_response(200, _META_PAYLOAD))
    http = httpx.AsyncClient(transport=transport)

    async def no_sleep(_: float) -> None:
        pass

    with patch("asyncio.sleep", side_effect=no_sleep):
        client = TiingoClient(token="testtoken", limiter=make_limiter(), http_client=http)
        meta = await client.get_ticker_meta("AAPL")

    assert meta.ticker == "AAPL"
    assert meta.name == "Apple Inc"
    assert meta.exchange_code == "NASDAQ"
    assert meta.start_date == datetime.date(1980, 12, 12)


# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------


def test_settings_tiingo_fields_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tiingo fields are present in Settings and have correct defaults/types."""
    # Isolate from any real .env files.
    monkeypatch.setenv("TIINGO_TOKEN", "dummy_token_for_test")
    monkeypatch.setenv("TIINGO_BASE_URL", "https://api.tiingo.com")
    monkeypatch.setenv("TIINGO_RATE_PER_SEC", "2.0")
    monkeypatch.setenv("TIINGO_BURST", "10")
    monkeypatch.setenv("TIINGO_HOURLY_CAP", "9000")
    monkeypatch.setenv("TIINGO_DAILY_CAP", "90000")
    monkeypatch.setenv("TIINGO_TIMEOUT_SECONDS", "15.0")
    monkeypatch.setenv("TIINGO_MAX_RETRIES", "3")

    # Import fresh — bypass lru_cache by instantiating directly.
    from app.core.config import Settings

    s = Settings()
    assert s.tiingo_token == "dummy_token_for_test"
    assert s.tiingo_base_url == "https://api.tiingo.com"
    assert s.tiingo_rate_per_sec == 2.0
    assert s.tiingo_burst == 10
    assert s.tiingo_hourly_cap == 9000
    assert s.tiingo_daily_cap == 90000
    assert s.tiingo_timeout_seconds == 15.0
    assert s.tiingo_max_retries == 3
