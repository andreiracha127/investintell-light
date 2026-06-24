"""Regime-Aware (research codename COMBO) — Sprint 5 SPY-signal loader unit tests.

Task 8 deleted the S4a single-level / goldfix / overlay dispatch tests: the code
path they exercised was retired by Task 7 (orthogonal two-level model only) and the
helpers (``_resolve_regime_block_budgets`` / ``_solve_regime_motor`` /
``taa_bands.combined_regime`` / ``effective_class_bands`` / ``goldfix_target``) were
removed in Task 8. The orthogonal ``regime_aware`` path routes EXCLUSIVELY to the
two-level solve, covered by ``test_builder_regime_two_level.py``.

What survives here: the ``_load_spy_signal`` loader unit tests. The per-instrument
``taa_bands.vol_graduated_caps`` / ``beta_graduated_caps`` throttles those feed are
KEPT for Plan C; only their (now-removed) S4a call-site went away.
"""

from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.services import portfolio_builder as pb
from app.services import taa_bands as tb


def test_load_spy_signal_reads_eod_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit: ``_load_spy_signal`` builds a stress-bearing newest-first close
    series and a frame-aligned SPY return vector from the eod_prices read —
    independent of the traded universe."""
    import asyncio

    index = pd.bdate_range("2024-01-02", periods=120)
    # A SPY price path with a drawdown into the latest dates (ascending by date).
    levels = np.concatenate(
        [np.linspace(100.0, 180.0, 90), np.linspace(180.0, 140.0, 30)]
    )
    rows = [(d.date(), float(p)) for d, p in zip(index, levels, strict=True)]

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        assert ticker == "SPY"
        return rows

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    closes_desc, spy_rets = asyncio.run(pb._load_spy_signal(object(), index))  # type: ignore[arg-type]
    # Newest-first; stressed (latest below the trailing-63d high).
    assert len(closes_desc) == 120
    assert tb.market_stress(closes_desc) > 0.0
    # Returns reindexed onto the frame => one per scenario row, finite.
    assert spy_rets is not None
    assert len(spy_rets) == len(index)
    assert np.isfinite(spy_rets).all()


def test_load_spy_signal_degrades_without_session() -> None:
    """No DB session (test seam / no datalake) => empty signal, no crash."""
    import asyncio

    index = pd.bdate_range("2024-01-02", periods=120)
    closes_desc, spy_rets = asyncio.run(pb._load_spy_signal(None, index))
    assert closes_desc == [] and spy_rets is None


def test_load_spy_signal_degrades_on_short_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fewer than the stress window of closes => degrade (flat-cap fallback)."""
    import asyncio

    index = pd.bdate_range("2024-01-02", periods=120)
    rows = [(d.date(), 100.0 + i) for i, d in enumerate(index[:10])]

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        return rows

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    closes_desc, spy_rets = asyncio.run(pb._load_spy_signal(object(), index))  # type: ignore[arg-type]
    assert closes_desc == [] and spy_rets is None
