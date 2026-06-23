"""Canonical date-normalization boundary for the optimizer data contract.

The return-frame index produced by ``app.optimizer.data`` is an OBJECT index of
``datetime.date`` (``pd.Index(list[date])``), NOT a ``DatetimeIndex`` — so
``frame.index.min()`` returns a plain ``datetime.date`` with no ``.date()``
method. Loaders that need a ``datetime.date`` for a range query must pass the
index endpoints through ``coerce_date`` instead of calling ``.date()`` (which
raises ``AttributeError`` on the real session; ``pd.bdate_range`` test fixtures —
being ``datetime64`` — silently hid this).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def coerce_date(value: Any) -> date:
    """Normalize a date-like value to a plain ``datetime.date``.

    Order matters: ``datetime`` (and ``pd.Timestamp``, a ``datetime`` subclass)
    is checked before ``date`` because ``datetime`` is itself a ``date``
    subclass. ``to_pydatetime`` covers pandas/numpy scalars; an ISO ``str`` is
    parsed from its first 10 chars. Anything else fails loud (``TypeError``) —
    the boundary never guesses.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    to_python = getattr(value, "to_pydatetime", None)
    if callable(to_python):
        converted = to_python()
        return converted.date() if isinstance(converted, datetime) else converted
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Unsupported date type: {type(value).__name__}")
