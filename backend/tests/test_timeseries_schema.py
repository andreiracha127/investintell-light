from app.schemas.timeseries import LineSeriesResponse, OhlcSeriesResponse


def test_line_series_serializes_as_arrays() -> None:
    r = LineSeriesResponse(id="SPY", interval="daily", series=[[1700000000000, 1.5]])
    assert r.model_dump()["series"] == [[1700000000000, 1.5]]


def test_ohlc_series_serializes_as_arrays() -> None:
    r = OhlcSeriesResponse(
        id="SPY", interval="weekly",
        ohlc=[[1700000000000, 1.0, 2.0, 0.5, 1.8]],
        volume=[[1700000000000, 1000]],
    )
    dumped = r.model_dump()
    assert dumped["ohlc"][0] == [1700000000000, 1.0, 2.0, 0.5, 1.8]
    assert dumped["volume"][0] == [1700000000000, 1000]
