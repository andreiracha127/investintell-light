# backend/tests/test_fund_factors_style_bias_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_dossier_tier_b as svc

_IID = uuid.uuid4()
_AS_OF = dt.date(2026, 1, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    async def execute(self, query, params=None):
        self.executed.append(str(query))
        return _Result(self._rows)


@pytest.mark.asyncio
async def test_style_bias_db_first_reads_view():
    rows = [
        {"as_of": _AS_OF, "factor": "size", "value": 1.0, "z_score": 0.5},
        {"as_of": _AS_OF, "factor": "momentum", "value": 0.2, "z_score": -1.0},
    ]
    session = _FakeSession(rows)
    as_of, biases, empty = await svc._style_bias_db_first(session, _IID)
    assert as_of == _AS_OF
    assert {b.factor for b in biases} == {"size", "momentum"}
    by = {b.factor: b.z_score for b in biases}
    assert by["momentum"] == -1.0
    assert empty is None
    assert any("fund_style_bias_v" in q for q in session.executed)


@pytest.mark.asyncio
async def test_style_bias_db_first_empty():
    as_of, biases, empty = await svc._style_bias_db_first(_FakeSession([]), _IID)
    assert biases == []
    assert empty is not None


@pytest.mark.asyncio
async def test_factors_db_first_reads_mv_no_ols(monkeypatch):
    async def _fund(_s, _iid):
        class _F:
            instrument_id = _IID
            series_id = "S1"
        return _F()
    monkeypatch.setattr(svc, "_fund_or_none", _fund)
    # Falha se o OLS pandas for chamado no caminho db-first:
    monkeypatch.setattr(svc, "_ols_market_sensitivities", lambda *a, **k: (_ for _ in ()).throw(AssertionError("OLS ran")))  # noqa: E501

    factor_rows = [{"factor": "Factor 1", "beta": 0.3, "t_stat": 5.0, "significance": "***", "as_of": _AS_OF}]  # noqa: E501
    bias_rows = [{"as_of": _AS_OF, "factor": "size", "value": 1.0, "z_score": 0.5}]

    class _Routed:
        def __init__(self):
            self.executed = []

        async def execute(self, query, params=None):
            t = str(query)
            self.executed.append(t)
            class _R:
                def __init__(self, rows): self._rows = rows
                def mappings(self): return self
                def all(self): return self._rows
            return _R(factor_rows if "fund_factor_exposures_latest_mv" in t else bias_rows)

    out = await svc.fetch_fund_factors(object(), _Routed(), _IID, use_db_first=True)
    assert out.market_sensitivities[0].beta == 0.3
    assert {b.factor for b in out.style_bias} == {"size"}
