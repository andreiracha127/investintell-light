# backend/tests/test_fund_analytics_db_first_models.py
from app.core.config import get_settings
from app.models.fund_analytics_db_first import (
    FundActiveShareRow,
    FundFactorExposureLatest,
    FundInstitutionalRevealLatest,
    FundStyleBiasRow,
    FundStyleDriftRow,
    FundTopHoldingRow,
)


def test_flag_defaults_false():
    assert get_settings().use_fund_analytics_db_first is False


def test_style_drift_row_maps_mv():
    assert FundStyleDriftRow.__tablename__ == "fund_style_drift_mv"
    cols = set(FundStyleDriftRow.__table__.columns.keys())
    assert {"series_id", "report_date", "sector", "weight"} <= cols


def test_top_holding_row_maps_mv():
    assert FundTopHoldingRow.__tablename__ == "fund_top_holdings_mv"
    cols = set(FundTopHoldingRow.__table__.columns.keys())
    assert {"series_id", "report_date", "rank", "issuer_name", "cusip", "pct_of_nav"} <= cols


def test_active_share_row_maps_mv():
    assert FundActiveShareRow.__tablename__ == "fund_active_share_mv"
    cols = set(FundActiveShareRow.__table__.columns.keys())
    assert {"series_id", "benchmark_series_id", "active_share", "overlap", "as_of"} <= cols
    assert "series_id" in FundActiveShareRow.__table__.primary_key.columns.keys()


def test_style_bias_row_maps_view():
    assert FundStyleBiasRow.__tablename__ == "fund_style_bias_v"
    cols = set(FundStyleBiasRow.__table__.columns.keys())
    assert {"instrument_id", "as_of", "factor", "value", "z_score"} <= cols


def test_factor_exposure_latest_maps_mv():
    assert FundFactorExposureLatest.__tablename__ == "fund_factor_exposures_latest_mv"
    cols = set(FundFactorExposureLatest.__table__.columns.keys())
    assert {"instrument_id", "factor", "beta", "t_stat", "significance", "as_of"} <= cols


def test_institutional_reveal_latest_maps_mv():
    assert FundInstitutionalRevealLatest.__tablename__ == "fund_institutional_reveal_latest_mv"
    cols = set(FundInstitutionalRevealLatest.__table__.columns.keys())
    assert {"series_id", "as_of", "schema_version", "payload"} <= cols
