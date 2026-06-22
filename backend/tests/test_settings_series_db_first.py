from app.core.config import get_settings


def test_series_db_first_defaults_off():
    get_settings.cache_clear()
    assert get_settings().use_series_db_first is False
