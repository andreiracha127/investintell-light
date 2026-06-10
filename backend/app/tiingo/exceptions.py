"""Typed exceptions for the Tiingo API client.

All errors from this package are subclasses of TiingoError.  Callers must
handle (or propagate) these; the client never swallows them silently.
"""


class TiingoError(Exception):
    """Base exception for all Tiingo client errors."""


class TiingoRateLimitError(TiingoError):
    """Raised when a rate-limit is hit.

    Triggers:
    - HTTP 429 after all retries are exhausted.
    - HTTP 200 with a plain-text body containing rate-limit wording
      (Tiingo's disguised-429 quirk).
    - Hourly or daily hard cap reached in the local token-bucket limiter.
    """


class TiingoNotFoundError(TiingoError):
    """Raised on HTTP 404 — ticker is unknown to Tiingo."""


class TiingoAuthError(TiingoError):
    """Raised on HTTP 401/403, or when an empty token is supplied at construction."""


class TiingoServerError(TiingoError):
    """Raised on 5xx responses (or transport errors) after all retries are exhausted."""


class TiingoBadResponseError(TiingoError):
    """Raised when a 200 response cannot be parsed as JSON and is not rate-limit wording,
    or when the parsed JSON does not match the expected schema.
    """
