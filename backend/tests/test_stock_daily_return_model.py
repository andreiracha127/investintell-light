from app.models.stock_daily_return import StockDailyReturn


def test_stock_daily_return_maps_table():
    assert StockDailyReturn.__tablename__ == "stock_daily_returns"
    cols = set(StockDailyReturn.__table__.columns.keys())
    assert {"ticker", "date", "return_1d", "adj_close"} <= cols
    pk = set(StockDailyReturn.__table__.primary_key.columns.keys())
    assert pk == {"ticker", "date"}
