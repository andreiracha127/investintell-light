from app.models.price_latest import NavLatest, PriceLatest


def test_price_latest_maps_mv_columns():
    assert PriceLatest.__tablename__ == "price_latest_mv"
    cols = set(PriceLatest.__table__.columns.keys())
    assert {"ticker", "as_of", "last_close", "prev_date", "prev_close"} <= cols
    assert "ticker" in PriceLatest.__table__.primary_key.columns.keys()


def test_nav_latest_maps_mv_columns():
    assert NavLatest.__tablename__ == "nav_latest_mv"
    cols = set(NavLatest.__table__.columns.keys())
    assert {"instrument_id", "as_of", "last_nav", "prev_date", "prev_nav"} <= cols
    assert "instrument_id" in NavLatest.__table__.primary_key.columns.keys()
