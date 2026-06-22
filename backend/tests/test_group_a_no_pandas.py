import pytest

from app.services import fund_analysis, fund_dossier_tier_b


@pytest.mark.asyncio
async def test_style_drift_db_first_does_not_call_pandas(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(pd, "DataFrame", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pandas used")))

    class _F: instrument_id = __import__("uuid").uuid4(); series_id = "S1"; name = "x"
    async def _fund(_s, _i): return _F()
    monkeypatch.setattr(fund_dossier_tier_b, "_fund_or_none", _fund)

    class _S:
        def mappings(self): return self
        def all(self): return []
        async def execute(self, *a, **k): return self
    out = await fund_dossier_tier_b.fetch_fund_style_drift(
        object(), _S(), _F.instrument_id, quarters=4, use_db_first=True
    )
    assert out.periods == []
