> SUPERSEDED by docs/superpowers/plans/2026-06-21-combo-*.md (see 2026-06-21 spec)

# COMBO Componente 1 — Worker `macro_factor_daily` (data-lake) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`).

**Goal:** Persistir DIARIAMENTE o quadrante macro growth×inflation (e seus estados/escores) numa tabela `macro_factor_daily` no data-lake, análogo a `regime_composite_daily`, computado a partir de proxies negociáveis (SPY p/ growth, TIP/IEF breakeven p/ inflação).

**Architecture:** Novo worker `src/workers/macro_factor_daily.py` no repo SEPARADO `E:/investintell-datalake-workers`, no mesmo formato do `regime_composite`: motor PURO (sem I/O) que computa growth/inflation/quadrant; camada de I/O que busca preços (Tiingo) e faz upsert; entrypoint `run(dsn, *, calc_date=None, limit=None) -> dict` com advisory lock. DDL idempotente em `schemas/macro_factor_daily.sql`. Agendado via serviço Railway diário.

**Tech Stack:** Python 3.12, psycopg3, numpy, httpx (via `_tiingo.TiingoClient`), pytest. Repo de workers (NÃO o backend do light).

## Global Constraints
- Repo alvo: `E:/investintell-datalake-workers`. NÃO tocar o backend do light neste componente.
- Contrato do worker: `run(dsn: str, *, calc_date: str | None = None, limit: int | None = None) -> dict` (igual a `src/workers/regime_composite.py:239`).
- Sinais (do spec §2, fiéis a `lean-research/TaaCvarSuite/main.py:503-526`):
  - growth = sinal do retorno de SPY em `g_look=126` pregões; `>0` ⇒ growth up.
  - inflation-surprise = sinal de `(retorno TIP 126d − retorno IEF 126d)`; `>0` ⇒ inflation up. `i_look=126`.
  - quadrant: growth_up & ¬infl_up → RECOVERY; growth_up & infl_up → EXPANSION; ¬growth_up & infl_up → SLOWDOWN; ¬growth_up & ¬infl_up → CONTRACTION.
- Preços: `eod_prices` (Tiger `t83f4np6x4`) tem SPY desde 1993 mas NÃO tem TIP/IEF (verificado). Portanto o worker busca SPY, TIP e IEF via Tiingo (`fetch_daily_prices`), como `regime_composite._fetch_spy`. Ver O1 do spec (não persistir TIP/IEF em `eod_prices` agora).
- Tabela `macro_factor_daily`: PK `factor_date`; colunas `growth_state text`, `inflation_state text`, `growth_score numeric`, `inflation_score numeric`, `quadrant text`, provenance + `computed_at`.
- `quadrant ∈ {RECOVERY, EXPANSION, SLOWDOWN, CONTRACTION}`; `growth_state ∈ {up, down}`; `inflation_state ∈ {up, down}` (CHECK constraints).
- Advisory lock novo em `src/db.py` (banda `900_2xx`, próximo livre `900_207`).
- TDD. Motor PURO testado sem DB/API; teste de integração marcado e dependente de env (`DATABASE_URL`, `TIINGO_API_KEY`), seguindo `tests/test_regime_composite.py`.
- Comandos: `cd /e/investintell-datalake-workers && python -m pytest tests/test_macro_factor_daily.py -v`.

---

### Task 1: Motor puro — growth/inflation/quadrant (sem I/O)

**Files:**
- Create: `src/workers/macro_factor_daily.py` (apenas o motor puro nesta task)
- Test: `tests/test_macro_factor_daily.py`

**Interfaces:**
- Produces (funções puras, testáveis sem I/O):
  - `def pct_return(series: list[float], look: int) -> float | None` — retorno `series[-1]/series[-1-look] - 1.0`; `None` se histórico insuficiente ou base ≤ 0. (Espelha `_macro_quadrant.ret_k`, `main.py:507`.)
  - `def classify_quadrant(spy_closes: list[float], tip_closes: list[float], ief_closes: list[float], *, g_look: int = 126, i_look: int = 126) -> dict | None` — retorna `{"growth_state","inflation_state","growth_score","inflation_score","quadrant"}` ou `None` se algum retorno é `None`. `growth_score = pct_return(spy, g_look)`; `inflation_score = pct_return(tip, i_look) - pct_return(ief, i_look)` (breakeven momentum); `growth_state = "up" if growth_score>0 else "down"`; `inflation_state = "up" if inflation_score>0 else "down"`; mapeamento do quadrante conforme Global Constraints.
  - `def build_rows(dates: list[date], spy: list[float], tip: list[float], ief: list[float], *, g_look=126, i_look=126) -> list[dict]` — para cada índice `t` com histórico suficiente, aplica `classify_quadrant` sobre os closes até `t` (inclusive) e emite uma linha `{"factor_date": dates[t], **quadrant_fields}`. Séries assumidas alinhadas por data (mesma grade); a alinhamento de datas é responsabilidade do chamador de I/O (Task 3).
- Constantes do módulo: `G_LOOK_DEFAULT = 126`, `I_LOOK_DEFAULT = 126`, `SPY_TICKER="SPY"`, `TIP_TICKER="TIP"`, `IEF_TICKER="IEF"`, `HISTORY_START = date(2003, 1, 1)`, `INSERT_CHUNK = 1000`, `LOCK_MACRO_FACTOR_DAILY` importado de `src.db`.

- [ ] **Step 1: Testes falhando** — escrever em `tests/test_macro_factor_daily.py`:

```python
import datetime as _dt
from src.workers import macro_factor_daily as mf


def test_pct_return_insufficient_history_is_none():
    assert mf.pct_return([1.0, 2.0], look=126) is None


def test_pct_return_basic():
    s = [100.0] * 126 + [110.0]  # len 127, look 126
    assert abs(mf.pct_return(s, 126) - 0.10) < 1e-9


def test_quadrant_recovery_growth_up_inflation_down():
    # SPY rising (growth up); TIP underperforms IEF (breakeven down => inflation down)
    spy = [100.0] * 126 + [110.0]
    tip = [100.0] * 126 + [100.0]   # 0%
    ief = [100.0] * 126 + [105.0]   # +5%  => tip-ief = -5% < 0 => inflation down
    q = mf.classify_quadrant(spy, tip, ief)
    assert q["growth_state"] == "up"
    assert q["inflation_state"] == "down"
    assert q["quadrant"] == "RECOVERY"


def test_quadrant_expansion_growth_up_inflation_up():
    spy = [100.0] * 126 + [110.0]
    tip = [100.0] * 126 + [108.0]   # +8%
    ief = [100.0] * 126 + [102.0]   # +2%  => +6% > 0 => inflation up
    q = mf.classify_quadrant(spy, tip, ief)
    assert q["quadrant"] == "EXPANSION"


def test_quadrant_slowdown_growth_down_inflation_up():
    spy = [100.0] * 126 + [90.0]    # -10% growth down
    tip = [100.0] * 126 + [108.0]
    ief = [100.0] * 126 + [102.0]   # inflation up
    q = mf.classify_quadrant(spy, tip, ief)
    assert q["quadrant"] == "SLOWDOWN"


def test_quadrant_contraction_growth_down_inflation_down():
    spy = [100.0] * 126 + [90.0]
    tip = [100.0] * 126 + [100.0]
    ief = [100.0] * 126 + [105.0]
    q = mf.classify_quadrant(spy, tip, ief)
    assert q["quadrant"] == "CONTRACTION"


def test_quadrant_none_when_insufficient():
    assert mf.classify_quadrant([1.0], [1.0], [1.0]) is None


def test_build_rows_emits_one_row_per_ready_date():
    n = 130
    dates = [_dt.date(2020, 1, 1) + _dt.timedelta(days=i) for i in range(n)]
    spy = [100.0 + i for i in range(n)]   # rising
    tip = [100.0] * n
    ief = [100.0] * n
    rows = mf.build_rows(dates, spy, tip, ief, g_look=126, i_look=126)
    # ready only for indices with >=127 history => indices 126..129 => 4 rows
    assert len(rows) == 4
    assert rows[0]["factor_date"] == dates[126]
    assert set(rows[0]) >= {"factor_date", "growth_state", "inflation_state",
                            "growth_score", "inflation_score", "quadrant"}
```

- [ ] **Step 2: Rodar e ver falhar** — `cd /e/investintell-datalake-workers && python -m pytest tests/test_macro_factor_daily.py -v` → ImportError/AttributeError (módulo/funções inexistentes).
- [ ] **Step 3: Implementar** o motor puro em `src/workers/macro_factor_daily.py` (docstring de contrato no topo no estilo do `regime_composite`; constantes; `pct_return`, `classify_quadrant`, `build_rows`). NÃO adicionar I/O ainda. `LOCK_MACRO_FACTOR_DAILY` será adicionado ao `src/db.py` na Task 2 — por ora importar de `src.db` com fallback de import dentro do `run` (que ainda não existe); para esta task não importar o lock no topo (evita ImportError). Apenas o motor puro.
- [ ] **Step 4: Rodar e ver passar** — mesma linha de comando → verde.
- [ ] **Step 5: Commit** — `git add src/workers/macro_factor_daily.py tests/test_macro_factor_daily.py && git commit -m "Add macro_factor_daily pure engine (growth/inflation quadrant)"`.

---

### Task 2: DDL + advisory lock

**Files:**
- Create: `schemas/macro_factor_daily.sql`
- Modify: `src/db.py` (registrar `LOCK_MACRO_FACTOR_DAILY = 900_207` junto aos demais `LOCK_*`, ~`src/db.py:47-62`)
- Test: `tests/test_macro_factor_daily.py` (adicionar verificação de leitura do SQL)

**Interfaces:**
- Produces: arquivo SQL idempotente com:

```sql
CREATE TABLE IF NOT EXISTS macro_factor_daily (
    factor_date      date           NOT NULL,
    growth_state     text           NOT NULL,           -- 'up' | 'down'
    inflation_state  text           NOT NULL,           -- 'up' | 'down'
    growth_score     numeric(14,8),                     -- SPY g_look return
    inflation_score  numeric(14,8),                     -- (TIP - IEF) i_look breakeven momentum
    quadrant         text           NOT NULL,           -- RECOVERY|EXPANSION|SLOWDOWN|CONTRACTION
    g_look           smallint       NOT NULL DEFAULT 126,
    i_look           smallint       NOT NULL DEFAULT 126,
    computed_at      timestamptz    NOT NULL DEFAULT now(),

    CONSTRAINT macro_factor_daily_pkey PRIMARY KEY (factor_date),
    CONSTRAINT ck_macro_factor_growth CHECK (growth_state IN ('up','down')),
    CONSTRAINT ck_macro_factor_inflation CHECK (inflation_state IN ('up','down')),
    CONSTRAINT ck_macro_factor_quadrant
        CHECK (quadrant IN ('RECOVERY','EXPANSION','SLOWDOWN','CONTRACTION'))
);
```

- Produces: `LOCK_MACRO_FACTOR_DAILY = 900_207` em `src/db.py` (próximo livre após `LOCK_REGIME_COMPOSITE = 900_206`).

- [ ] **Step 1: Teste falhando** — adicionar:

```python
import pathlib


def test_ddl_file_exists_and_has_table():
    sql = (pathlib.Path(__file__).resolve().parents[1]
           / "schemas" / "macro_factor_daily.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS macro_factor_daily" in sql
    assert "macro_factor_daily_pkey PRIMARY KEY (factor_date)" in sql


def test_lock_id_registered():
    from src import db
    assert db.LOCK_MACRO_FACTOR_DAILY == 900_207
```

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_macro_factor_daily.py -k "ddl or lock" -v`.
- [ ] **Step 3: Implementar** — criar `schemas/macro_factor_daily.sql` (conteúdo acima) e adicionar a linha `LOCK_MACRO_FACTOR_DAILY = 900_207` em `src/db.py` no bloco de constantes de lock.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add schemas/macro_factor_daily.sql src/db.py tests/test_macro_factor_daily.py && git commit -m "Add macro_factor_daily DDL and advisory lock"`.

---

### Task 3: Camada de I/O + entrypoint `run`

**Files:**
- Modify: `src/workers/macro_factor_daily.py` (adicionar I/O e `run`)
- Test: `tests/test_macro_factor_daily.py` (teste de upsert com fakes + teste de integração marcado)

**Interfaces:**
- Consumes: `src.db.connect`, `src.db.advisory_lock`, `src.db.LOCK_MACRO_FACTOR_DAILY` (Task 2); `src.workers._tiingo.TiingoClient.fetch_daily_prices` (retorna `list[tuple[date, float|None]]`, ver `regime_composite.py:175`); motor puro (Task 1).
- Produces:
  - `def ensure_schema(conn) -> None` — lê `schemas/macro_factor_daily.sql` e executa (padrão de `regime_composite.ensure_schema`).
  - `def _fetch_prices(calc_date: date | None) -> tuple[list[date], list[float], list[float], list[float]]` — busca SPY/TIP/IEF via `TiingoClient`, alinha pelas datas COMUNS aos três (interseção ordenada), devolve `(dates, spy, tip, ief)` alinhados. Levanta `RuntimeError` se algum vier vazio.
  - `def _upsert(conn, rows: list[dict]) -> int` — `INSERT ... ON CONFLICT (factor_date) DO UPDATE SET ...` em chunks de `INSERT_CHUNK` (padrão de `regime_composite._upsert`); retorna nº de linhas.
  - `def run(dsn: str, *, calc_date: str | None = None, limit: int | None = None) -> dict` — `connect(dsn)` + `advisory_lock(conn, LOCK_MACRO_FACTOR_DAILY)`; se não obtiver lock retorna `{"days":0,"upserted":0,"skipped":"lock_busy"}`; `ensure_schema`; `_fetch_prices`; `build_rows`; `_upsert`; `conn.commit()`; retorna `{"days":len(rows),"upserted":n,"quadrant":rows[-1]["quadrant"] if rows else None,"calc_date":rows[-1]["factor_date"].isoformat() if rows else None}`. `limit` aceito por contrato e ignorado (série única).

- [ ] **Step 1: Testes falhando** — upsert com fake de conexão (sem DB real) e integração marcada:

```python
import os
import pytest


class _FakeCursor:
    def __init__(self, sink): self.sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def executemany(self, sql, params): self.sink.extend(params)
    def execute(self, sql, params=None): pass


class _FakeConn:
    def __init__(self): self.sink = []
    def cursor(self): return _FakeCursor(self.sink)
    def execute(self, *a, **k): pass
    def commit(self): pass


def test_upsert_chunks_all_rows():
    conn = _FakeConn()
    rows = [{"factor_date": _dt.date(2020, 1, 1) + _dt.timedelta(days=i),
             "growth_state": "up", "inflation_state": "down",
             "growth_score": 0.1, "inflation_score": -0.02,
             "quadrant": "RECOVERY"} for i in range(2500)]
    n = mf._upsert(conn, rows)
    assert n == 2500
    assert len(conn.sink) == 2500


@pytest.mark.skipif(
    not (os.getenv("DATABASE_URL") and os.getenv("TIINGO_API_KEY")),
    reason="needs cloud DSN + Tiingo key",
)
def test_run_real_history():
    stats = mf.run(os.environ["DATABASE_URL"])
    assert stats["days"] > 3_000          # ~2003->today daily, post warmup
    assert stats["quadrant"] in {"RECOVERY", "EXPANSION", "SLOWDOWN", "CONTRACTION"}
    stats2 = mf.run(os.environ["DATABASE_URL"])  # idempotent
    assert stats2["days"] == stats["days"]
```

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_macro_factor_daily.py -k upsert -v` (o teste de integração fica `skipped` sem env).
- [ ] **Step 3: Implementar** `ensure_schema`, `_fetch_prices` (alinhamento por interseção de datas), `_upsert` (com a lista de colunas e o SQL `ON CONFLICT`), e `run` (com o `advisory_lock`). Import do lock dentro do módulo agora é seguro (Task 2 o criou).
- [ ] **Step 4: Rodar e ver passar** — `python -m pytest tests/test_macro_factor_daily.py -v` (unit verdes; integração skipped ou verde se env presente).
- [ ] **Step 5: Commit** — `git add src/workers/macro_factor_daily.py tests/test_macro_factor_daily.py && git commit -m "Add macro_factor_daily I/O layer and run entrypoint"`.

---

### Task 4: Registro de agendamento (Railway) — docs/config

**Files:**
- Modify: `railway.toml` (adicionar `macro_factor_daily` ao comentário de agendamento, ~`railway.toml:1-20`)

**Interfaces:**
- Produces: linha de comentário documentando `macro_factor_daily -> daily ~06:50 UTC (needs TIINGO_API_KEY)` no bloco de comentários, alinhada às demais. (O serviço real é criado no dashboard/CLI da Railway com `WORKER=macro_factor_daily` e `cronSchedule`; este passo apenas documenta a intenção no repo, como os demais workers.)

- [ ] **Step 1:** Editar o comentário em `railway.toml` adicionando a linha do `macro_factor_daily` (após `regime_composite`), indicando cron diário ~06:50 UTC e a necessidade de `TIINGO_API_KEY`.
- [ ] **Step 2: Commit** — `git add railway.toml && git commit -m "Document macro_factor_daily cron in railway.toml"`.
- [ ] **Step 3 (handoff, fora do código):** Anotar no PR que o owner deve criar o serviço Railway `macro-factor-daily` (`WORKER=macro_factor_daily`, `DATABASE_URL`, `TIINGO_API_KEY`, `cronSchedule="0 6 * * *"` ou `"50 6 * * *"`) e rodar `python -m src.run macro_factor_daily` uma vez para o backfill inicial.

---

## Self-Review (cobertura do spec §4.1 / §5 componente 1)
- Motor puro growth/inflation/quadrant fiel a `main.py:503-526` → Task 1.
- Persistência diária análoga a `regime_composite_daily` (DDL + lock) → Task 2.
- I/O via Tiingo (TIP/IEF ausentes de `eod_prices`, verificado) + `run` com advisory lock + upsert idempotente → Task 3.
- Agendamento diário (Railway) → Task 4.
- Caveat O1 (Tiingo-fetch vs ingest em `eod_prices`) registrado nos Global Constraints e no spec §6.
