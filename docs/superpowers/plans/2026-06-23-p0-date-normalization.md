# P0 — Date Normalization Boundary (regime_aware unblock) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar o `AttributeError` determinístico que derruba **todo** `regime_aware` em sessão real, normalizando os endpoints do índice de datas numa fronteira canônica antes de qualquer query de range.

**Architecture:** O índice do return-frame produzido por `app.optimizer.data` é um `pd.Index(list[datetime.date])` — dtype **object**, não `DatetimeIndex`. Logo `frame.index.min()` devolve um `datetime.date` puro, sem `.date()`. Os dois loaders de regime (`_load_spy_signal`, `_load_proxy_returns`) chamam `frame_index.min().date()` / `.max().date()` fora de qualquer `try`, então o `AttributeError` sobe como 500 não-tratado. A correção é uma função única `coerce_date` (novo módulo `app/optimizer/dates.py`) aplicada nos 4 call sites — **sem** condicionais locais e **sem** mexer no produtor do índice (o `reindex` Timestamp↔date já casa por valor, verificado empiricamente, então normalizar a fonte mudaria o tipo para todos os consumidores sem necessidade).

**Tech Stack:** Python 3.13, pandas, pytest, SQLAlchemy async. Tudo no repo `E:/investintell-light-combo/backend`.

## Global Constraints

- Worktree/branch: `E:/investintell-light-combo` @ `feat/combo-regime-allocator`. Todo path abaixo é relativo a `backend/`.
- Rodar testes do diretório `backend/` com o venv do projeto: `.venv/Scripts/python -m pytest ...` (Windows). Os exemplos usam `python -m pytest` assumindo o venv ativo.
- `coerce_date` checa `isinstance(datetime)` ANTES de `isinstance(date)` — `datetime` (e `pd.Timestamp`) são subclasses de `date`; inverter a ordem devolveria o `datetime` inteiro.
- Nenhuma mudança em `app/optimizer/data.py` (a fonte do índice object-date fica como está — decisão de escopo).
- Este plano é mergeável isoladamente (não depende dos Planos A–D da rearquitetura).

---

### Task 1: Fronteira `coerce_date`

**Files:**
- Create: `app/optimizer/dates.py`
- Test: `tests/test_optimizer_dates.py`

**Interfaces:**
- Produces: `coerce_date(value: Any) -> datetime.date` — aceita `datetime` (incl. `pd.Timestamp`), `date`, objetos com `to_pydatetime`, e `str` ISO; levanta `TypeError` em qualquer outro tipo.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_optimizer_dates.py
import datetime as dt

import pandas as pd
import pytest

from app.optimizer.dates import coerce_date


def test_coerce_date_passes_through_plain_date() -> None:
    d = dt.date(2024, 3, 5)
    out = coerce_date(d)
    assert out == d
    assert type(out) is dt.date


def test_coerce_date_narrows_datetime_to_date() -> None:
    assert coerce_date(dt.datetime(2024, 3, 5, 14, 30)) == dt.date(2024, 3, 5)


def test_coerce_date_handles_pandas_timestamp() -> None:
    # pd.Timestamp is a datetime subclass -> first branch
    assert coerce_date(pd.Timestamp("2024-03-05 09:00")) == dt.date(2024, 3, 5)


def test_coerce_date_parses_iso_string() -> None:
    assert coerce_date("2024-03-05T00:00:00") == dt.date(2024, 3, 5)


def test_coerce_date_rejects_unsupported_type() -> None:
    with pytest.raises(TypeError):
        coerce_date(12345)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_optimizer_dates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.optimizer.dates'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/optimizer/dates.py
"""Canonical date-normalization boundary for the optimizer data contract.

The return-frame index produced by ``app.optimizer.data`` is an OBJECT index of
``datetime.date`` (``pd.Index(list[date])``), NOT a ``DatetimeIndex`` — so
``frame.index.min()`` returns a plain ``datetime.date`` with no ``.date()``
method. Loaders that need a ``datetime.date`` for a range query must pass the
index endpoints through ``coerce_date`` instead of calling ``.date()`` (which
raises ``AttributeError`` on the real session; ``pd.bdate_range`` test fixtures —
being ``datetime64`` — silently hid this).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def coerce_date(value: Any) -> date:
    """Normalize a date-like value to a plain ``datetime.date``.

    Order matters: ``datetime`` (and ``pd.Timestamp``, a ``datetime`` subclass)
    is checked before ``date`` because ``datetime`` is itself a ``date``
    subclass. ``to_pydatetime`` covers pandas/numpy scalars; an ISO ``str`` is
    parsed from its first 10 chars. Anything else fails loud (``TypeError``) —
    the boundary never guesses.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    to_python = getattr(value, "to_pydatetime", None)
    if callable(to_python):
        converted = to_python()
        return converted.date() if isinstance(converted, datetime) else converted
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Unsupported date type: {type(value).__name__}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_optimizer_dates.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/optimizer/dates.py tests/test_optimizer_dates.py
git commit -m "feat(optimizer): add coerce_date date-normalization boundary"
```

---

### Task 2: Aplicar `coerce_date` nos loaders + regressão do índice object-date

**Files:**
- Modify: `app/services/portfolio_builder.py` (import + linhas 209-210 e 258-259)
- Test: `tests/test_builder_regime_two_level.py` (acrescentar 2 testes)

**Interfaces:**
- Consumes: `coerce_date` (Task 1).
- Behaviour preserved: `_load_spy_signal(session, frame_index)` e `_load_proxy_returns(session, tickers, frame_index)` mantêm assinatura; só os endpoints de data passam a ser normalizados.

- [ ] **Step 1: Write the failing tests**

Acrescente ao fim de `tests/test_builder_regime_two_level.py` (os imports `asyncio, dt, np, pd, pb` já existem no arquivo):

```python
def test_load_proxy_returns_handles_object_date_index(monkeypatch: Any) -> None:
    """The real datalake frame indexes on datetime.date (object dtype), not
    Timestamp. The loader must not choke on .date() (P0 regression — the
    pd.bdate_range fixtures masked this AttributeError)."""
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(300)]
    index = pd.Index(dates)  # object dtype, exactly like load_aligned_returns
    assert index.dtype == object
    levels = _ascending_levels(len(index))

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        # the loader must hand the DB layer a plain datetime.date, not a datetime
        assert isinstance(start, dt.date) and not isinstance(start, dt.datetime)
        assert isinstance(end, dt.date) and not isinstance(end, dt.datetime)
        return [(d, float(p)) for d, p in zip(dates, levels, strict=True)]

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    out = asyncio.run(pb._load_proxy_returns(object(), ["IVV"], index))
    assert set(out) == {"IVV"}
    assert np.isfinite(out["IVV"]).all()


def test_load_spy_signal_handles_object_date_index(monkeypatch: Any) -> None:
    """Same P0 regression for the S4a SPY-signal loader."""
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(300)]
    index = pd.Index(dates)
    assert index.dtype == object
    levels = _ascending_levels(len(index))

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        assert isinstance(start, dt.date) and not isinstance(start, dt.datetime)
        return [(d, float(p)) for d, p in zip(dates, levels, strict=True)]

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    closes_desc, rets = asyncio.run(pb._load_spy_signal(object(), index))
    assert len(closes_desc) == len(index)
    assert rets is not None and np.isfinite(rets).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_builder_regime_two_level.py -k object_date_index -v`
Expected: FAIL — `AttributeError: 'datetime.date' object has no attribute 'date'` (raised at `portfolio_builder.py:209`/`:258`)

- [ ] **Step 3: Apply the fix**

Add the import alongside the other `app.optimizer` imports (`portfolio_builder.py:43` area):

```python
from app.optimizer.dates import coerce_date
```

In `_load_spy_signal` replace lines 209-210:

```python
    start = coerce_date(frame_index.min())
    end = coerce_date(frame_index.max())
```

In `_load_proxy_returns` replace lines 258-259 (identical change):

```python
    start = coerce_date(frame_index.min())
    end = coerce_date(frame_index.max())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_builder_regime_two_level.py -k "object_date_index or load_proxy_returns or load_spy" -v`
Expected: PASS (the new 2 + the pre-existing `_load_proxy_returns` tests still green)

- [ ] **Step 5: Commit**

```bash
git add app/services/portfolio_builder.py tests/test_builder_regime_two_level.py
git commit -m "fix(builder): normalize regime loader date endpoints via coerce_date

The datalake return-frame indexes on datetime.date (object dtype), so
frame.index.min().date() raised AttributeError on every real-session
regime_aware request. bdate_range fixtures (datetime64) masked it."
```

---

### Task 3: Teste de aceitação — o dispatch alcança o solve com o índice real

**Files:**
- Test: `tests/test_builder_regime_two_level.py` (acrescentar 1 teste)

**Interfaces:**
- Consumes: `_solve_regime_two_level(session, assets, labels, frame_index, quadrant, gate_state, payload) -> _RegimeTwoLevel | None` e `_ref_key` (já no módulo `pb`), `FundRefIn`/`OptimizeRequest` (schemas).
- Verifies: com `session` NÃO-None e o índice object-date de produção, o caminho real de `_load_proxy_returns` roda e o solve de duas camadas é alcançado (retorno não-None, livro soma 1).

- [ ] **Step 1: Write the failing test**

Acrescente ao fim de `tests/test_builder_regime_two_level.py`:

```python
async def test_two_level_reached_with_production_object_date_index(monkeypatch: Any) -> None:
    """P0 acceptance: with the REAL session shape (session != None) and the
    REAL index type (datetime.date / object dtype), the dispatch reaches the
    two-level solve instead of dying in _load_proxy_returns. Stubs only the DB
    edge (select_adj_close_rows) and the fund taxonomy."""
    from app.schemas.builder import FundRefIn, OptimizeRequest

    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(500)]
    index = pd.Index(dates)
    assert index.dtype == object

    assets = [FundRefIn(kind="fund", id=fid) for fid in _TL_IDS]
    labels = [pb._ref_key(a) for a in assets]  # derive, never hardcode the format

    def _ticker_levels(ticker: str) -> list[float]:
        # Distinct price path per ticker -> well-conditioned proxy covariance.
        # Identical series would make sigma_ledoit_wolf rank-deficient and the
        # Level-1 solve degenerate. Deterministic seed (no PYTHONHASHSEED dep).
        rng = np.random.default_rng(sum(ord(c) for c in ticker))
        lvl, out = 100.0, []
        for r in rng.normal(0.0003, 0.01, len(index)):
            lvl *= 1.0 + r
            out.append(lvl)
        return out

    async def fake_rows(session: Any, ticker: str, start: Any, end: Any) -> list[tuple]:
        # Type contract is covered by Task 2; here we only prove the dispatch
        # reaches the solve, so no isinstance assertion inside the loader.
        return [(d, float(p)) for d, p in zip(dates, _ticker_levels(ticker), strict=True)]

    async def fake_strategy(session: Any, fund_ids: list) -> dict:
        return {fid: _TL_STRATEGY.get(fid) for fid in fund_ids}

    async def fake_class(session: Any, fund_ids: list) -> dict:
        return {fid: _TL_CLASS.get(fid) for fid in fund_ids}

    monkeypatch.setattr(pb, "select_adj_close_rows", fake_rows)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)

    payload = OptimizeRequest(
        assets=assets, objective="regime_aware", mandate="moderate"
    )
    result = await pb._solve_regime_two_level(
        object(), assets, labels, index, "expansion", "risk_on", payload
    )
    assert result is not None  # would be None (or raise) before the P0 fix
    total = float(result.fund_weights.sum()) + sum(result.proxy_holdings.values())
    assert abs(total - 1.0) < 1e-6
```

- [ ] **Step 2: Run test to verify it passes (post-fix)**

Run: `python -m pytest "tests/test_builder_regime_two_level.py::test_two_level_reached_with_production_object_date_index" -v`
Expected: PASS. (Sanity: revertendo a Task 2, este teste levanta `AttributeError` — confirma que ele cobre o P0.)

- [ ] **Step 3: Run the full regime + optimizer suites (no regressions)**

Run: `python -m pytest tests/test_builder_regime_two_level.py tests/test_optimizer_dates.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_builder_regime_two_level.py
git commit -m "test(builder): acceptance test — regime_aware reaches solve with production date index"
```

---

## Self-Review

**Spec coverage:** P0 (normalização de data na fronteira) → Tasks 1–2; critério de aceitação "integration test com o tipo real da sessão" → Task 3; "5 casos de coerce" (date/datetime/Timestamp/str/inválido) → Task 1; "nunca HTTP 500" → o AttributeError-→500 deixa de ocorrer (Task 2). Coberto.

**Placeholder scan:** sem TBD/“handle edge cases”; todo passo traz código/comando reais.

**Type consistency:** `coerce_date(value: Any) -> date` usado idêntico em Task 2; `_ref_key`/`_solve_regime_two_level`/`_RegimeTwoLevel.fund_weights`/`.proxy_holdings` batem com as assinaturas reais de `portfolio_builder.py`.
