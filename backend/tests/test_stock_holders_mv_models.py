from app.models import (
    HoldingReverseLookupRow,
    StockFundHolderRow,
    StockInstitutionalHolder,
)


def test_b1_model_maps_columns_and_composite_pk():
    assert StockInstitutionalHolder.__tablename__ == "stock_institutional_holders_mv"
    cols = set(StockInstitutionalHolder.__table__.columns.keys())
    assert {
        "ticker", "cik", "manager_name", "report_date", "cusip", "issuer_name",
        "shares", "market_value", "entry_date", "entry_price", "current_price",
        "shares_outstanding",
    } <= cols
    pk = set(StockInstitutionalHolder.__table__.primary_key.columns.keys())
    assert pk == {"ticker", "cik", "cusip"}


def test_b2_model_maps_columns_and_composite_pk():
    assert StockFundHolderRow.__tablename__ == "stock_fund_holders_mv"
    cols = set(StockFundHolderRow.__table__.columns.keys())
    assert {
        "ticker", "registrant_cik", "family", "series_id", "fund_name",
        "instrument_id", "issuer_name", "quantity", "market_value", "pct_of_nav",
        "pct_nav_q1", "pct_nav_q2", "pct_nav_q3", "report_date", "cusip",
    } <= cols
    pk = set(StockFundHolderRow.__table__.primary_key.columns.keys())
    assert pk == {"ticker", "series_id"}


def test_b3_model_maps_columns_and_composite_pk():
    assert HoldingReverseLookupRow.__tablename__ == "holding_reverse_lookup_mv"
    cols = set(HoldingReverseLookupRow.__table__.columns.keys())
    assert {
        "cusip", "cik", "manager_name", "period", "report_date", "name",
        "value_usd", "shares",
    } <= cols
    pk = set(HoldingReverseLookupRow.__table__.primary_key.columns.keys())
    assert pk == {"cusip", "cik"}
