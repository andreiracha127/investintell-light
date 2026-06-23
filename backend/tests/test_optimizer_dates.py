# tests/test_optimizer_dates.py
import datetime as dt

import pandas as pd
import pytest

from app.optimizer.dates import coerce_date


def test_coerce_date_passes_through_plain_date() -> None:
    d = dt.date(2024, 3, 5)
    out = coerce_date(d)
    assert out == d
    assert type(out) is dt.date


def test_coerce_date_narrows_datetime_to_date() -> None:
    assert coerce_date(dt.datetime(2024, 3, 5, 14, 30)) == dt.date(2024, 3, 5)


def test_coerce_date_handles_pandas_timestamp() -> None:
    # pd.Timestamp is a datetime subclass -> first branch
    assert coerce_date(pd.Timestamp("2024-03-05 09:00")) == dt.date(2024, 3, 5)


def test_coerce_date_parses_iso_string() -> None:
    assert coerce_date("2024-03-05T00:00:00") == dt.date(2024, 3, 5)


def test_coerce_date_rejects_unsupported_type() -> None:
    with pytest.raises(TypeError):
        coerce_date(12345)
