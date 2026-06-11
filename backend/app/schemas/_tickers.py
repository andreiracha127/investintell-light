"""Shared ticker normalization/validation — the single canonical home.

Extracted from ``app.schemas.portfolio_analysis`` (the F3.2 pattern) so the
persisted-portfolio schemas can reuse it without crossing private-underscore
boundaries.
"""

import re

TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


def normalize_ticker(value: str, label: str = "ticker") -> str:
    """Strip + uppercase *value*; raise ValueError when it fails the pattern."""
    symbol = value.strip().upper()
    if not TICKER_RE.fullmatch(symbol):
        raise ValueError(
            f"Invalid {label} {value!r}: expected 1-10 characters from A-Z, 0-9, '.', '-'."
        )
    return symbol
