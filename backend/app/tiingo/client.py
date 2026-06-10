"""Tiingo API client — the ONLY path to api.tiingo.com in this codebase.

Usage::

    async with TiingoClient(token=settings.tiingo_token, limiter=limiter) as client:
        rows = await client.get_eod_prices("AAPL", date(2024,1,1), date(2024,12,31))
"""

import asyncio
import datetime
import random
from typing import Any

import httpx
from pydantic import ValidationError

from app.tiingo.exceptions import (
    TiingoAuthError,
    TiingoBadResponseError,
    TiingoNotFoundError,
    TiingoRateLimitError,
    TiingoServerError,
)
from app.tiingo.models import TiingoEodRow, TiingoNewsItem, TiingoTickerMeta
from app.tiingo.rate_limiter import TokenBucketLimiter

# Plain-text body wording that Tiingo uses for disguised rate-limit responses.
_RATE_LIMIT_KEYWORDS = ("run over", "limit")
_BODY_SNIPPET_LEN = 200


def _is_rate_limit_body(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _RATE_LIMIT_KEYWORDS)


class TiingoClient:
    """Async HTTP client for the Tiingo REST API.

    Args:
        token: Tiingo API token.  Empty/None raises ``TiingoAuthError`` immediately.
        limiter: Token-bucket limiter shared across all requests.
        base_url: API base URL (override in tests or for staging).
        timeout: Per-request timeout in seconds.
        max_retries: Maximum retry attempts for 429 / 5xx / transport errors.
        http_client: Optional pre-built ``httpx.AsyncClient``.  If provided the
            caller owns it and ``TiingoClient`` will NOT close it.  If omitted,
            one is created and owned by this instance.
    """

    def __init__(
        self,
        token: str | None,
        limiter: TokenBucketLimiter,
        base_url: str = "https://api.tiingo.com",
        timeout: float = 15.0,
        max_retries: int = 3,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise TiingoAuthError(
                "Tiingo token is empty or None — set TIINGO_TOKEN in your environment."
            )
        self._token = token
        self._limiter = limiter
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._owns_client = http_client is None
        self._http: httpx.AsyncClient = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout)
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> "TiingoClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Private request machinery
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Single request path: acquire token, send, handle errors, parse JSON.

        Retries 429 / 5xx / transport errors with exponential back-off.
        """
        await self._limiter.acquire()

        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Token {self._token}"}

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._http.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await self._backoff(attempt)
                    continue
                raise TiingoServerError(
                    f"Transport/timeout error after {self._max_retries} retries: {exc}"
                ) from exc

            status = response.status_code

            if status in (401, 403):
                raise TiingoAuthError(
                    f"Tiingo auth error (HTTP {status}): {response.text[:_BODY_SNIPPET_LEN]}"
                )

            if status == 404:
                raise TiingoNotFoundError(
                    f"Ticker not found (HTTP 404) at {path}"
                )

            if status == 429:
                last_exc = TiingoRateLimitError(f"HTTP 429 from Tiingo (attempt {attempt})")
                if attempt < self._max_retries:
                    await self._backoff(attempt)
                    continue
                raise TiingoRateLimitError(
                    f"HTTP 429 from Tiingo after {self._max_retries} retries."
                )

            if status >= 500:
                last_exc = TiingoServerError(f"HTTP {status} from Tiingo (attempt {attempt})")
                if attempt < self._max_retries:
                    await self._backoff(attempt)
                    continue
                raise TiingoServerError(
                    f"HTTP {status} from Tiingo after {self._max_retries} retries: "
                    f"{response.text[:_BODY_SNIPPET_LEN]}"
                )

            # HTTP 200 (or other 2xx) — try JSON parse.
            try:
                return response.json()
            except Exception as parse_exc:
                body = response.text
                if _is_rate_limit_body(body):
                    raise TiingoRateLimitError(
                        f"Tiingo disguised rate-limit response (HTTP {status}): "
                        f"{body[:_BODY_SNIPPET_LEN]}"
                    ) from parse_exc
                raise TiingoBadResponseError(
                    f"Non-JSON HTTP {status} response from Tiingo: "
                    f"{body[:_BODY_SNIPPET_LEN]!r}"
                ) from parse_exc

        # Should not be reached, but satisfies the type checker.
        raise TiingoServerError(f"Request failed after retries. Last error: {last_exc}")

    async def _backoff(self, attempt: int) -> None:
        """Exponential back-off with small random jitter."""
        delay = 0.5 * (2**attempt) + random.uniform(0.0, 0.1)
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_eod_prices(
        self,
        ticker: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> list[TiingoEodRow]:
        """Fetch end-of-day prices for *ticker* between *start_date* and *end_date*.

        GET /tiingo/daily/{ticker}/prices
        """
        normalized = ticker.lower()
        path = f"/tiingo/daily/{normalized}/prices"
        params: dict[str, Any] = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        }
        raw = await self._get(path, params)

        if not isinstance(raw, list):
            snippet = str(raw)[:_BODY_SNIPPET_LEN]
            raise TiingoBadResponseError(
                f"Expected list from {path}, got {type(raw).__name__}: {snippet}"
            )

        upper = ticker.upper()
        try:
            return [TiingoEodRow(ticker=upper, **row) for row in raw]
        except (ValidationError, TypeError) as exc:
            raise TiingoBadResponseError(
                f"EOD price schema mismatch for {ticker}: {exc}"
            ) from exc

    async def get_ticker_meta(self, ticker: str) -> TiingoTickerMeta:
        """Fetch metadata for *ticker*.

        GET /tiingo/daily/{ticker}
        """
        normalized = ticker.lower()
        path = f"/tiingo/daily/{normalized}"
        raw = await self._get(path)

        if not isinstance(raw, dict):
            snippet = str(raw)[:_BODY_SNIPPET_LEN]
            raise TiingoBadResponseError(
                f"Expected dict from {path}, got {type(raw).__name__}: {snippet}"
            )

        # Tiingo echoes the ticker in the response; override to ensure consistent casing.
        raw = dict(raw)
        raw["ticker"] = ticker.upper()
        try:
            return TiingoTickerMeta(**raw)
        except (ValidationError, TypeError) as exc:
            raise TiingoBadResponseError(
                f"Ticker meta schema mismatch for {ticker}: {exc}"
            ) from exc

    async def get_news(
        self,
        tickers: list[str],
        limit: int = 50,
    ) -> list[TiingoNewsItem]:
        """Fetch news articles for the given tickers.

        GET /tiingo/news
        """
        effective_limit = min(limit, 100)
        params: dict[str, Any] = {
            "tickers": ",".join(t.lower() for t in tickers),
            "limit": effective_limit,
        }
        raw = await self._get("/tiingo/news", params)

        if not isinstance(raw, list):
            raise TiingoBadResponseError(
                f"Expected list from /tiingo/news, got {type(raw).__name__}: "
                f"{str(raw)[:_BODY_SNIPPET_LEN]}"
            )

        try:
            return [TiingoNewsItem(**item) for item in raw]
        except (ValidationError, TypeError) as exc:
            raise TiingoBadResponseError(
                f"News item schema mismatch: {exc}"
            ) from exc
