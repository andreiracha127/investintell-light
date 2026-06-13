import datetime as dt

from app.services.timeseries import resolve_interval, to_ms_ohlc, to_ms_pairs


def test_resolve_interval_by_range() -> None:
    assert resolve_interval("1Y") == "daily"
    assert resolve_interval("5Y") == "weekly"
    assert resolve_interval("MAX") == "monthly"


def test_to_ms_pairs() -> None:
    pairs = to_ms_pairs([(dt.date(2026, 6, 11), 105.5)])
    assert pairs == [[int(dt.datetime(2026, 6, 11, tzinfo=dt.UTC).timestamp() * 1000), 105.5]]


def test_to_ms_ohlc() -> None:
    rows = [(dt.date(2026, 6, 11), 1.0, 2.0, 0.5, 1.8, 1000)]
    ohlc, vol = to_ms_ohlc(rows)
    t = int(dt.datetime(2026, 6, 11, tzinfo=dt.UTC).timestamp() * 1000)
    assert ohlc == [[t, 1.0, 2.0, 0.5, 1.8]]
    assert vol == [[t, 1000.0]]
