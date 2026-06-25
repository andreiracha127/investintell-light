# A1 — Macro Vintage Infra (point-in-time) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Dar ao quadrante macro v1 uma base point-in-time: um source registry enxuto, uma tabela de vintages reconstruída via ALFRED, ingestão vintage-aware, e a leitura "o que se sabia em `decision_time`" — sem tocar a `macro_data` atual (que segue como série latest-revision).

**Architecture:** Tabela nova `macro_observation_vintage` (uma linha por *revisão real* — vintages com valor inalterado são comprimidos). O worker `macro_vintage` busca cada série da cesta via ALFRED `output_type=2` (todos os vintages numa chamada), comprime, e faz upsert idempotente (`ON CONFLICT DO NOTHING` — vintages são imutáveis). A leitura PIT (`src/macro_pit.py`) devolve, por (série, período), o último valor com `available_at <= decision_time`. Reusa `TokenBucket` e o padrão `run/ensure_schema/advisory_lock` do worker existente.

**Tech Stack:** Python 3.13, psycopg, httpx, pytest. Repo worker `E:/investintell-datalake-workers-combo`.

## Global Constraints

- Worktree/branch do código: `E:/investintell-datalake-workers-combo` @ `feat/combo-regime-gate`. Paths abaixo são relativos à raiz desse repo.
- Rodar testes com o venv do worker: `.venv/Scripts/python -m pytest ...` do diretório raiz do repo worker (Windows). Se não houver `.venv` aí, usar `python -m pytest`.
- NÃO alterar `macro_data`, `macro_ingestion.py`, nem o worker `regime_gate`. Esta é infra nova, isolada.
- ALFRED = FRED archival: mesma `FRED_API_KEY` (vive em `E:/investintell-datalake-workers/.env`), endpoint `https://api.stlouisfed.org/fred/series/observations` com `output_type=2` + `realtime_start=1776-07-04&realtime_end=9999-12-31`. A rede ao `api.stlouisfed.org` exige sandbox desligado neste ambiente; o smoke é env-gated por `FRED_API_KEY`.
- `revision_policy="vintage"` para fontes macro; o mesmo `MacroSourceSpec` também descreve fontes diárias de mercado (`revision_policy="none"`) — mas A1 só implementa a cesta macro.
- Cesta seed (provisória, a calibrar em A3) — NÃO é parâmetro final: growth = INDPRO/PCEC96/PAYEMS/ACOGNO; inflation = CPILFESL/PPIFIS/AHETPI/MICH.
- Vintage `output_type=2` retorna colunas `SERIES_YYYYMMDD`; o sufixo `YYYYMMDD` é a vintage/release date ≈ `available_at`. Valores `"."` são missing.

---

### Task 1: Schema `macro_observation_vintage` + LOCK id

**Files:**
- Create: `schemas/macro_observation_vintage.sql`
- Modify: `src/db.py` (registrar `LOCK_MACRO_VINTAGE`)
- Test: `tests/test_macro_vintage.py`

**Interfaces:**
- Produces: tabela `macro_observation_vintage(series_id, observation_period, vintage_date, value, available_at, revision_number, source, source_spec_version, ingested_at)`, PK `(series_id, observation_period, vintage_date)`; `LOCK_MACRO_VINTAGE = 900_321`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_macro_vintage.py
import pathlib

from src import db


def test_ddl_file_exists_and_declares_table() -> None:
    sql = pathlib.Path("schemas/macro_observation_vintage.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS macro_observation_vintage" in sql
    for col in ("series_id", "observation_period", "vintage_date", "value",
                "available_at", "revision_number", "source", "source_spec_version", "ingested_at"):
        assert col in sql, f"missing column {col}"
    assert "PRIMARY KEY (series_id, observation_period, vintage_date)" in sql
    assert "create_hypertable" in sql


def test_lock_id_registered_and_unique() -> None:
    assert db.LOCK_MACRO_VINTAGE == 900_321
    ids = [v for k, v in vars(db).items() if k.startswith("LOCK_") and isinstance(v, int)]
    assert ids.count(900_321) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_macro_vintage.py -v`
Expected: FAIL — `FileNotFoundError` (no .sql) and `AttributeError: LOCK_MACRO_VINTAGE`.

- [ ] **Step 3: Create the schema + register the lock**

`schemas/macro_observation_vintage.sql`:

```sql
-- macro_vintage worker — point-in-time vintage store for the macro quadrant.
-- One row per REAL revision: vintages whose value did not change are compressed
-- away upstream. Coexists with macro_data (latest-revision); never overwrites.
CREATE TABLE IF NOT EXISTS macro_observation_vintage (
    series_id           VARCHAR(30)   NOT NULL,
    observation_period  DATE          NOT NULL,   -- the economic date (obs date)
    vintage_date        DATE          NOT NULL,   -- ALFRED realtime date the value first appeared
    value               NUMERIC(24,6) NOT NULL,
    available_at        TIMESTAMPTZ   NOT NULL,   -- when the value became knowable (vintage_date 00:00 UTC)
    revision_number     INTEGER       NOT NULL,   -- 0 = first print, 1,2,... per (series_id, observation_period)
    source              VARCHAR(30)   NOT NULL DEFAULT 'alfred',
    source_spec_version VARCHAR(40)   NOT NULL,
    ingested_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (series_id, observation_period, vintage_date)
);

SELECT create_hypertable('macro_observation_vintage', 'observation_period',
                         chunk_time_interval => INTERVAL '1 year',
                         if_not_exists => TRUE);

-- Point-in-time read: per series, walk back from a decision time over available_at.
CREATE INDEX IF NOT EXISTS idx_mov_pit
    ON macro_observation_vintage (series_id, available_at DESC, observation_period DESC);
```

In `src/db.py`, add after `LOCK_MACRO_INGESTION = 900_320`:

```python
LOCK_MACRO_VINTAGE = 900_321
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_macro_vintage.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add schemas/macro_observation_vintage.sql src/db.py tests/test_macro_vintage.py
git commit -m "feat(macro): point-in-time vintage table schema + lock id"
```

---

### Task 2: `MacroSourceSpec` registry + cesta seed

**Files:**
- Create: `src/macro_sources.py`
- Test: `tests/test_macro_sources.py`

**Interfaces:**
- Produces: `MacroSourceSpec` (frozen dataclass), `SEED_SOURCES: tuple[MacroSourceSpec, ...]`, `axis_weights(axis) -> dict[str, float]` (pesos normalizados por eixo), `SOURCE_SPEC_VERSION: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_macro_sources.py
from src.macro_sources import SEED_SOURCES, SOURCE_SPEC_VERSION, axis_weights


def test_seed_has_both_axes_with_3_to_5_families_each() -> None:
    for axis in ("growth", "inflation"):
        specs = [s for s in SEED_SOURCES if s.axis == axis]
        families = {s.family for s in specs}
        assert 3 <= len(families) <= 5, f"{axis}: {families}"


def test_weights_normalize_to_one_per_axis() -> None:
    for axis in ("growth", "inflation"):
        w = axis_weights(axis)
        assert abs(sum(w.values()) - 1.0) < 1e-9


def test_macro_sources_are_vintage_policy_and_versioned() -> None:
    assert SOURCE_SPEC_VERSION
    for s in SEED_SOURCES:
        assert s.revision_policy == "vintage"
        assert s.direction in (-1, 1)
        assert s.cadence in ("daily", "weekly", "monthly", "quarterly")
        assert s.source_spec_version == SOURCE_SPEC_VERSION


def test_series_ids_unique() -> None:
    ids = [s.series_id for s in SEED_SOURCES]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_macro_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.macro_sources'`

- [ ] **Step 3: Create the registry**

```python
# src/macro_sources.py
"""Macro source registry for the macro quadrant (model_version macro_quadrant_us_v1).

A LEAN, auditable basket: 3-5 families per axis, point-in-time reconstructible via
ALFRED. Weights/direction/transform here are SEEDS to be calibrated in A3 (against
abstention/flip/vintage-stability — never against return), not final parameters.
The same dataclass also describes daily market sources (revision_policy='none'),
but A1 only populates the macro basket.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

SOURCE_SPEC_VERSION = "macro_quadrant_us_v1.0"


@dataclass(frozen=True)
class MacroSourceSpec:
    source_id: str
    series_id: str
    axis: Literal["growth", "inflation"]
    family: str
    transform_id: str
    direction: Literal[-1, 1]
    weight: float
    cadence: Literal["daily", "weekly", "monthly", "quarterly"]
    release_calendar_id: str | None
    revision_policy: Literal["none", "vintage"]
    grace_period: timedelta
    hard_max_age: timedelta
    critical: bool
    minimum_history: int
    source_spec_version: str = SOURCE_SPEC_VERSION


def _macro(series_id, axis, family, weight, *, direction=1, transform="yoy",
           cadence="monthly", critical=True):
    return MacroSourceSpec(
        source_id=f"alfred:{series_id}", series_id=series_id, axis=axis, family=family,
        transform_id=transform, direction=direction, weight=weight, cadence=cadence,
        release_calendar_id=None, revision_policy="vintage",
        grace_period=timedelta(days=7), hard_max_age=timedelta(days=45),
        critical=critical, minimum_history=24,
    )


SEED_SOURCES: tuple[MacroSourceSpec, ...] = (
    # growth axis (4 families)
    _macro("INDPRO", "growth", "activity_production", 0.25),
    _macro("PCEC96", "growth", "real_consumption", 0.25),
    _macro("PAYEMS", "growth", "labor", 0.25),
    _macro("ACOGNO", "growth", "new_orders_leading", 0.25),
    # inflation axis (4 families)
    _macro("CPILFESL", "inflation", "core_inflation", 0.30),
    _macro("PPIFIS", "inflation", "upstream_prices", 0.25),
    _macro("AHETPI", "inflation", "wages", 0.25),
    _macro("MICH", "inflation", "inflation_expectations", 0.20),
)


def axis_weights(axis: str) -> dict[str, float]:
    """Per-axis weights normalized to sum 1 (over series_id)."""
    specs = [s for s in SEED_SOURCES if s.axis == axis]
    total = sum(abs(s.weight) for s in specs)
    if total <= 0:
        raise ValueError(f"axis {axis}: non-positive weight total")
    return {s.series_id: s.weight / total for s in specs}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_macro_sources.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/macro_sources.py tests/test_macro_sources.py
git commit -m "feat(macro): MacroSourceSpec registry + seed basket (4 families/axis)"
```

---

### Task 3: ALFRED vintage parser (compress to real revisions)

**Files:**
- Create: `src/workers/macro_vintage.py` (parser only this task)
- Test: `tests/test_macro_vintage.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_alfred_vintages(series_id: str, payload: dict) -> list[dict]` — each dict `{series_id, observation_period: date, vintage_date: date, value: float, revision_number: int}`, ordered, only when the value changes across vintages.

- [ ] **Step 1: Write the failing test (real ALFRED fixture, captured 2026-06-23)**

Append to `tests/test_macro_vintage.py`:

```python
import datetime as _dt

from src.workers import macro_vintage as mv

# Real ALFRED output_type=2 for PAYEMS 2010-03 (trimmed to the transitions):
# 129750 (1st print 2010-04-02) -> 129871 -> 129849 (held) -> 129438 (benchmark 2011-02).
_ALFRED_PAYEMS = {
    "observations": [
        {
            "date": "2010-03-01",
            "PAYEMS_20100402": "129750",
            "PAYEMS_20100507": "129871",
            "PAYEMS_20100604": "129849",
            "PAYEMS_20100702": "129849",
            "PAYEMS_20110107": "129849",
            "PAYEMS_20110204": "129438",
            "PAYEMS_20111231": "129438",
        }
    ]
}


def test_parse_alfred_compresses_to_real_revisions() -> None:
    rows = mv.parse_alfred_vintages("PAYEMS", _ALFRED_PAYEMS)
    # 7 vintages collapse to 4 distinct-value revisions
    assert [(r["vintage_date"], r["value"], r["revision_number"]) for r in rows] == [
        (_dt.date(2010, 4, 2), 129750.0, 0),
        (_dt.date(2010, 5, 7), 129871.0, 1),
        (_dt.date(2010, 6, 4), 129849.0, 2),
        (_dt.date(2011, 2, 4), 129438.0, 3),
    ]
    assert all(r["observation_period"] == _dt.date(2010, 3, 1) for r in rows)
    assert all(r["series_id"] == "PAYEMS" for r in rows)


def test_parse_alfred_drops_missing_markers() -> None:
    payload = {"observations": [{"date": "2020-01-01", "X_20200115": ".", "X_20200215": "5.0"}]}
    rows = mv.parse_alfred_vintages("X", payload)
    assert [r["value"] for r in rows] == [5.0]
    assert rows[0]["revision_number"] == 0  # missing print does not consume a revision number


def test_parse_alfred_ignores_non_vintage_columns() -> None:
    payload = {"observations": [{"date": "2020-01-01", "realtime_start": "2020-01-01", "X_20200115": "3.0"}]}
    rows = mv.parse_alfred_vintages("X", payload)
    assert len(rows) == 1 and rows[0]["value"] == 3.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_macro_vintage.py -k parse_alfred -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.workers.macro_vintage'`

- [ ] **Step 3: Write the parser**

```python
# src/workers/macro_vintage.py
"""macro_vintage worker — point-in-time vintage ingestion for the macro quadrant.

Fetches each basket series from ALFRED (output_type=2 = all vintages in one call),
compresses to real revisions (a new row only when the value changes across vintage
dates), and upserts idempotently into macro_observation_vintage (vintages are
immutable -> ON CONFLICT DO NOTHING). Reuses the FRED TokenBucket. The latest-
revision macro_data table is untouched.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any

_VINTAGE_COL = re.compile(r"_(\d{8})$")
_MISSING = frozenset((".", "#N/A", "", "NaN", "nan", "null", "None"))


def parse_alfred_vintages(series_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """ALFRED output_type=2 JSON -> compressed vintage rows (one per real revision).

    Columns named ``<SERIES>_YYYYMMDD`` carry the value as known on that vintage
    date; non-vintage columns (e.g. ``date``) and missing markers are skipped.
    Within each observation period, vintages are sorted by date and a row is
    emitted only when the value differs from the previous kept value.
    """
    by_period: dict[_dt.date, list[tuple[_dt.date, float]]] = {}
    for obs in payload.get("observations", []):
        try:
            period = _dt.date.fromisoformat(obs["date"])
        except (KeyError, ValueError):
            continue
        for col, raw in obs.items():
            m = _VINTAGE_COL.search(col)
            if not m:
                continue
            s = str(raw).strip()
            if s in _MISSING:
                continue
            try:
                v = float(s)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(v):
                continue
            vd = _dt.datetime.strptime(m.group(1), "%Y%m%d").date()
            by_period.setdefault(period, []).append((vd, v))

    rows: list[dict[str, Any]] = []
    for period in sorted(by_period):
        last_val: float | None = None
        rev = 0
        for vd, v in sorted(by_period[period], key=lambda t: t[0]):
            if last_val is None or v != last_val:
                rows.append({
                    "series_id": series_id, "observation_period": period,
                    "vintage_date": vd, "value": v, "revision_number": rev,
                })
                last_val = v
                rev += 1
    return rows
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_macro_vintage.py -k parse_alfred -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/workers/macro_vintage.py tests/test_macro_vintage.py
git commit -m "feat(macro): ALFRED output_type=2 vintage parser (compress to revisions)"
```

---

### Task 4: Fetch (ALFRED) + vintage-aware upsert + `run`

**Files:**
- Modify: `src/workers/macro_vintage.py`
- Modify: `src/run_worker.py` (add `macro_vintage` to the valid-worker message)
- Test: `tests/test_macro_vintage.py` (append)

**Interfaces:**
- Consumes: `parse_alfred_vintages` (Task 3); `SEED_SOURCES`, `SOURCE_SPEC_VERSION` (Task 2); `db.connect`, `db.advisory_lock`, `db.LOCK_MACRO_VINTAGE`; `TokenBucket` from `macro_ingestion`.
- Produces: `rows_to_records(rows, source_spec_version) -> list[tuple]`; `upsert_vintages(conn, records) -> int`; `ensure_schema(conn) -> None`; `run(dsn, *, limit=None) -> dict`; `fetch_vintages(client, api_key, series_id, bucket) -> dict`.

- [ ] **Step 1: Write the failing tests (fakes; no real DB / no network)**

Append to `tests/test_macro_vintage.py`:

```python
class _FakeCur:
    def __init__(self, store): self.store = store
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None):
        self._last = (sql, params)
        if params is not None and "pg_try_advisory_lock" in sql:
            self.store["lock"] = True
    def executemany(self, sql, seq):
        self.store.setdefault("rows", []).extend(seq)
    def fetchone(self): return (True,)


class _FakeConn:
    def __init__(self, store): self.store = store
    def cursor(self): return _FakeCur(self.store)
    def commit(self): self.store["committed"] = True


def test_rows_to_records_sets_available_at_and_version() -> None:
    rows = mv.parse_alfred_vintages("PAYEMS", _ALFRED_PAYEMS)
    recs = mv.rows_to_records(rows, "macro_quadrant_us_v1.0")
    # record tuple: (series_id, observation_period, vintage_date, value, available_at, revision_number, source, source_spec_version)
    first = recs[0]
    assert first[0] == "PAYEMS"
    assert first[2] == _dt.date(2010, 4, 2)           # vintage_date
    assert first[4] == _dt.datetime(2010, 4, 2, tzinfo=_dt.timezone.utc)  # available_at = vintage 00:00 UTC
    assert first[5] == 0                               # revision_number
    assert first[6] == "alfred" and first[7] == "macro_quadrant_us_v1.0"


def test_upsert_vintages_sends_all_records() -> None:
    store: dict = {}
    recs = mv.rows_to_records(mv.parse_alfred_vintages("PAYEMS", _ALFRED_PAYEMS), "v")
    n = mv.upsert_vintages(_FakeConn(store), recs)
    assert n == len(recs) == 4
    assert "ON CONFLICT" in store_last_sql(store)


def test_run_returns_lock_busy_sentinel(monkeypatch) -> None:
    import contextlib

    @contextlib.contextmanager
    def _busy(conn, lock_id):
        yield False
    monkeypatch.setattr(mv, "connect", lambda dsn, **k: _FakeConn({}))
    monkeypatch.setattr(mv, "advisory_lock", _busy)
    monkeypatch.setattr(mv, "ensure_schema", lambda conn: None)
    out = mv.run("postg://x")
    assert out["status"] == "lock_busy"
```

Add this helper at the top of the test file (after imports):

```python
def store_last_sql(store: dict) -> str:
    return store.get("last_sql", "")
```

And make `upsert_vintages` record `store["last_sql"]` via the fake by having the fake cursor capture it — adjust `_FakeCur.executemany` to also set `self.store["last_sql"] = sql`.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_macro_vintage.py -k "records or upsert or lock_busy" -v`
Expected: FAIL — `AttributeError` (functions not defined yet).

- [ ] **Step 3: Implement fetch + records + upsert + run**

Append to `src/workers/macro_vintage.py`:

```python
import os

from src.db import LOCK_MACRO_VINTAGE, advisory_lock, connect
from src.macro_sources import SEED_SOURCES, SOURCE_SPEC_VERSION
from src.workers.macro_ingestion import FRED_BASE_URL, TokenBucket

_REALTIME_ALL = {"realtime_start": "1776-07-04", "realtime_end": "9999-12-31"}
_SCHEMA = "schemas/macro_observation_vintage.sql"


def ensure_schema(conn) -> None:
    import pathlib
    sql = pathlib.Path(_SCHEMA).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def fetch_vintages(client, api_key: str, series_id: str, bucket: TokenBucket) -> dict:
    """ALFRED all-vintages fetch (output_type=2) for one series. Retries on 5xx/429;
    a 400 (discontinued/no-vintage series) returns an empty payload, never fails."""
    import time
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json",
              "output_type": 2, **_REALTIME_ALL}
    for attempt in range(3):
        bucket.acquire()
        resp = client.get(f"{FRED_BASE_URL}/series/observations", params=params)
        if resp.status_code in (429, 503) or resp.status_code >= 500:
            time.sleep(min(30.0, 2.0 * (2 ** attempt)))
            continue
        if resp.status_code == 400:
            return {"observations": []}
        resp.raise_for_status()
        return resp.json()
    return {"observations": []}


def rows_to_records(rows: list[dict], source_spec_version: str) -> list[tuple]:
    """Parsed rows -> DB tuples; available_at = vintage_date at 00:00 UTC."""
    out = []
    for r in rows:
        vd = r["vintage_date"]
        available_at = _dt.datetime(vd.year, vd.month, vd.day, tzinfo=_dt.timezone.utc)
        out.append((r["series_id"], r["observation_period"], vd, r["value"],
                    available_at, r["revision_number"], "alfred", source_spec_version))
    return out


def upsert_vintages(conn, records: list[tuple]) -> int:
    """Idempotent insert — vintages are immutable, so ON CONFLICT DO NOTHING."""
    if not records:
        return 0
    sql = (
        "INSERT INTO macro_observation_vintage "
        "(series_id, observation_period, vintage_date, value, available_at, "
        " revision_number, source, source_spec_version) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (series_id, observation_period, vintage_date) DO NOTHING"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()
    return len(records)


def run(dsn: str, *, limit: int | None = None) -> dict:
    """Backfill + refresh all basket vintages. Idempotent (DO NOTHING). Re-runs
    only add newly-published vintages. ``limit`` caps series count (smoke runs)."""
    api_key = os.environ["FRED_API_KEY"]
    specs = list(SEED_SOURCES)[: limit or len(SEED_SOURCES)]
    conn = connect(dsn)
    try:
        ensure_schema(conn)
        with advisory_lock(conn, LOCK_MACRO_VINTAGE) as got:
            if not got:
                return {"status": "lock_busy"}
            import httpx
            bucket = TokenBucket()
            upserted = 0
            with httpx.Client(timeout=30.0) as client:
                for spec in specs:
                    payload = fetch_vintages(client, api_key, spec.series_id, bucket)
                    rows = parse_alfred_vintages(spec.series_id, payload)
                    upserted += upsert_vintages(conn, rows_to_records(rows, SOURCE_SPEC_VERSION))
            return {"status": "ok", "series": len(specs), "upserted": upserted}
    finally:
        conn.close()
```

In `src/run_worker.py`, add `macro_vintage` to the valid-worker list in the error message (line ~22, cosmetic — `importlib` already dispatches it).

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_macro_vintage.py -v`
Expected: PASS (all)

- [ ] **Step 5: Smoke (env-gated — real ALFRED, run by the owner / this session with the key)**

Append an env-gated integration test:

```python
import os as _os

import pytest


@pytest.mark.skipif(not _os.getenv("FRED_API_KEY"), reason="needs FRED_API_KEY")
def test_smoke_fetch_real_payems_has_vintages() -> None:
    import httpx
    with httpx.Client(timeout=30.0) as client:
        payload = mv.fetch_vintages(client, _os.environ["FRED_API_KEY"], "PAYEMS", mv.TokenBucket())
    rows = mv.parse_alfred_vintages("PAYEMS", payload)
    assert len(rows) > 50  # decades of monthly revisions
    assert all(r["revision_number"] >= 0 for r in rows)
```

Run (this session, with the key, sandbox off): `FRED_API_KEY=... python -m pytest tests/test_macro_vintage.py -k smoke -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/workers/macro_vintage.py src/run_worker.py tests/test_macro_vintage.py
git commit -m "feat(macro): ALFRED vintage fetch + idempotent upsert + run worker"
```

---

### Task 5: Point-in-time read library

**Files:**
- Create: `src/macro_pit.py`
- Test: `tests/test_macro_pit.py`

**Interfaces:**
- Consumes: `macro_observation_vintage` table.
- Produces: `latest_vintage_as_of(conn, series_ids: list[str], decision_time: datetime) -> dict[str, dict[date, float]]` — per series, the value of each observation period as known at `decision_time` (latest vintage with `available_at <= decision_time`).

- [ ] **Step 1: Write the failing test (fake cursor returning rows)**

```python
# tests/test_macro_pit.py
import datetime as dt

from src import macro_pit


class _Cur:
    def __init__(self, rows): self._rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self._sql, self._params = sql, params
    def fetchall(self): return self._rows


class _Conn:
    def __init__(self, rows): self._rows = rows
    def cursor(self): return _Cur(self._rows)


def test_latest_vintage_as_of_picks_value_known_at_decision_time() -> None:
    # DB returns DISTINCT ON (series, period) latest available_at<=cutoff, already filtered.
    rows = [
        ("PAYEMS", dt.date(2010, 3, 1), 129871.0),
        ("PAYEMS", dt.date(2010, 4, 1), 130161.0),
    ]
    conn = _Conn(rows)
    out = macro_pit.latest_vintage_as_of(
        conn, ["PAYEMS"], dt.datetime(2010, 6, 1, tzinfo=dt.timezone.utc)
    )
    assert out == {"PAYEMS": {dt.date(2010, 3, 1): 129871.0, dt.date(2010, 4, 1): 130161.0}}


def test_latest_vintage_as_of_passes_cutoff_and_series() -> None:
    conn = _Conn([])
    cur_holder = {}
    orig = _Conn.cursor

    def _spy(self):
        c = orig(self)
        cur_holder["c"] = c
        return c
    _Conn.cursor = _spy
    cutoff = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    macro_pit.latest_vintage_as_of(conn, ["A", "B"], cutoff)
    _Conn.cursor = orig
    assert "available_at <= " in cur_holder["c"]._sql
    assert cur_holder["c"]._params[0] == ["A", "B"]
    assert cur_holder["c"]._params[1] == cutoff
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_macro_pit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.macro_pit'`

- [ ] **Step 3: Implement the PIT read**

```python
# src/macro_pit.py
"""Point-in-time reads over macro_observation_vintage.

Answers "what did the system know at decision_time?" — for each series and
observation period, the value from the latest vintage whose available_at is at or
before decision_time. This is the contract A2's classifier consumes; it never
forward-fills beyond what was actually published.
"""
from __future__ import annotations

import datetime as _dt

_PIT_SQL = (
    "SELECT DISTINCT ON (series_id, observation_period) "
    "       series_id, observation_period, value "
    "FROM macro_observation_vintage "
    "WHERE series_id = ANY(%s) AND available_at <= %s "
    "ORDER BY series_id, observation_period, available_at DESC"
)


def latest_vintage_as_of(
    conn, series_ids: list[str], decision_time: _dt.datetime
) -> dict[str, dict[_dt.date, float]]:
    """Per series, {observation_period: value-as-known-at-decision_time}."""
    out: dict[str, dict[_dt.date, float]] = {sid: {} for sid in series_ids}
    with conn.cursor() as cur:
        cur.execute(_PIT_SQL, (list(series_ids), decision_time))
        for series_id, period, value in cur.fetchall():
            out.setdefault(series_id, {})[period] = float(value)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_macro_pit.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/macro_pit.py tests/test_macro_pit.py
git commit -m "feat(macro): point-in-time read (latest vintage as-of decision_time)"
```

---

## Self-Review

**Spec coverage** (adendo §4/§5/§7 do escopo macro): tabela de vintage com `release_at/available_at/vintage_id(→vintage_date)/revision_number` → Task 1; `MacroSourceSpec` registry + cesta pequena → Task 2; reconstrução via ALFRED `output_type=2` → Tasks 3-4; ingestão vintage-aware idempotente (append, nunca sobrescreve) → Task 4; consulta `latest vintage available_at <= decision_time` → Task 5. Compressão a revisões reais evita explosão de linhas. NÃO coberto aqui (fora do escopo A1, vão para A2/A3): cálculo do score por eixo, hysteresis, confidence, o `QuadrantSnapshot` em si — A1 é só a base de dados PIT.

**Placeholder scan:** sem TBD; todo passo tem código/comando reais; o fixture ALFRED é dado real capturado.

**Type consistency:** `parse_alfred_vintages -> list[dict]` (Task 3) consumido por `rows_to_records` (Task 4); `available_at` é `vintage_date` 00:00 UTC em ambos schema (Task 1) e records (Task 4); `latest_vintage_as_of` (Task 5) lê as colunas que Task 1 cria. `LOCK_MACRO_VINTAGE=900_321` usado em Task 4 = definido em Task 1.

**Deferred to owner's environment:** o backfill em massa (8 séries × histórico completo) e o cron Railway do worker `macro_vintage` — operações de A2/deploy, não A1. O smoke (Task 4 Step 5) é env-gated e rodável nesta sessão com a key.
