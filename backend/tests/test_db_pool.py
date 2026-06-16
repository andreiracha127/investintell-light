"""Engine connection-pool hardening (app/core/db.py).

Latency-tail defense: ``pool_pre_ping`` is removed (it costs +1 RTT per
checkout, painful cross-region) in favour of ``pool_recycle``; explicit
``pool_size``/``max_overflow``/``pool_timeout`` bound the pool so a slow
checkout fails fast instead of hanging. Sized well under the TimescaleDB Cloud
ceiling (max_connections=200, shared with the datalake workers).
"""

from app.core.config import get_settings
from app.core.db import _make_engine


def test_engine_pool_is_hardened() -> None:
    settings = get_settings()
    engine = _make_engine()
    try:
        pool = engine.sync_engine.pool
        # pre_ping disabled: no extra round-trip per checkout.
        assert pool._pre_ping is False
        assert pool.size() == settings.db_pool_size
        assert pool._max_overflow == settings.db_max_overflow
        assert pool._timeout == settings.db_pool_timeout_seconds
        assert pool._recycle == settings.db_pool_recycle_seconds
    finally:
        engine.sync_engine.dispose()
