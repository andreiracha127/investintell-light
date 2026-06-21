> SUPERSEDED by docs/superpowers/plans/2026-06-21-combo-*.md (see 2026-06-21 spec)

# COMBO Componente 2 — Service `taa_bands` (regime → bandas por classe) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`).

**Goal:** Um módulo PURO no backend do light que mapeia (composite risk-on/off + quadrante macro) → bandas `(min, max)` por classe de ativo, com `hw_scale=1.5`, suavização EMA dos centros e clamp aos limites duros (IPS), portando fielmente a lógica validada de `lean-research/TaaCvarSuite/main.py`; mais um reader do `macro_factor_daily` análogo ao reader do composite.

**Architecture:** Novo `backend/app/services/taa_bands.py` com: (a) a tabela `DEFAULT_TAA_BANDS` e os helpers `compute_effective_band`/`smooth_regime_centers` (puros, port verbatim); (b) `combined_regime(composite_state, quadrant)` (gate composite + overlay do quadrante); (c) `effective_class_bands(regime)` → `dict[class -> (min,max)]` com `hw_scale=1.5` e clamp IPS. Um reader `fetch_macro_quadrant(datalake)` em `taa_bands` (ou em `macro_regime.py`) lê `macro_factor_daily` no data-lake exatamente como `macro_regime.fetch_composite_regime` lê `regime_composite_daily`.

**Tech Stack:** Python 3.12, SQLAlchemy async (data-lake session), Pydantic v2, pytest (`asyncio_mode=auto`).

## Global Constraints
- Repo: `E:/investintell-light/backend`. Módulo puro: SEM dependência de cvxpy/engine aqui (só math + tipos).
- Tabela de bandas verbatim do spec §2 / `main.py:70-103` (`DEFAULT_TAA_BANDS`). COMBO usa só `RISK_ON / RISK_OFF / INFLATION` (nunca `CRISIS`).
- `IPS_CLASS_BOUNDS`: equity (0,1), fixed_income (0,1), alternatives (0,0.40), cash (0,1) (`main.py:121`).
- `HW_SCALE = 1.5` (achado validado, spec §3); `EMA_HALFLIFE_DAYS = 5`; `MAX_DAILY_SHIFT = 0.03` (`main.py:97-101`).
- Overlay do quadrante (`_combined_regime`, `main.py:528`): composite RISK_OFF domina → RISK_OFF; senão RECOVERY/None→RISK_ON; EXPANSION→INFLATION (use_infl_bands=yes); SLOWDOWN→RISK_OFF; CONTRACTION→RISK_OFF (defensive_on=growth_down).
- Vocabulário de classes do produto: `equity|fixed_income|cash|alternatives|multi_asset` (`backend/app/schemas/builder.py:84`). A tabela de bandas cobre as 4 primeiras; `multi_asset` NÃO recebe banda (spec O3).
- Reader do quadrante segue o padrão de `macro_regime.fetch_composite_regime` (`backend/app/services/macro_regime.py:187`) e usa a sessão de data-lake (`app/core/datalake.py`).
- TDD; comando: `cd backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -v`.

---

### Task 1: Helpers puros — `compute_effective_band` + `smooth_regime_centers`

**Files:**
- Create: `backend/app/services/taa_bands.py`
- Test: `backend/tests/test_taa_bands.py`

**Interfaces:**
- Produces (port verbatim de `main.py:216` e `main.py:234`):
  - `def compute_effective_band(ips_min: float, ips_max: float, regime_center: float, regime_half_width: float) -> tuple[float, float]`.
  - `def smooth_regime_centers(current_centers: dict[str, float], previous_smoothed: dict[str, float] | None, *, halflife_days: int = 5, max_daily_shift: float = 0.03) -> dict[str, float]`.
- Constantes: `DEFAULT_TAA_BANDS` (dict verbatim), `IPS_CLASS_BOUNDS`, `ASSET_CLASSES = ["equity","fixed_income","alternatives","cash"]`, `HW_SCALE = 1.5`, `EMA_HALFLIFE_DAYS = 5`, `MAX_DAILY_SHIFT = 0.03`.

- [ ] **Step 1: Testes falhando**:

```python
from app.services import taa_bands as tb


def test_effective_band_clamps_to_ips():
    # center 0.52 hw 0.12 (=0.08*1.5) => [0.40, 0.64], ips (0,1) keeps it
    lo, hi = tb.compute_effective_band(0.0, 1.0, 0.52, 0.12)
    assert abs(lo - 0.40) < 1e-9 and abs(hi - 0.64) < 1e-9


def test_effective_band_center_above_ips_max():
    # alternatives ips max 0.40; center 0.50 hw 0.06 -> regime [0.44,0.56] infeasible
    lo, hi = tb.compute_effective_band(0.0, 0.40, 0.50, 0.06)
    assert hi == 0.40
    assert lo == max(0.40 - 2 * 0.06, 0.0)  # 0.28


def test_smooth_first_pass_returns_copy():
    cur = {"equity": 0.52, "cash": 0.06}
    out = tb.smooth_regime_centers(cur, None)
    assert out == cur and out is not cur


def test_smooth_respects_max_daily_shift():
    prev = {"equity": 0.30}
    out = tb.smooth_regime_centers({"equity": 0.52}, prev,
                                   halflife_days=5, max_daily_shift=0.03)
    assert abs(out["equity"] - 0.33) < 1e-9  # clamped +0.03


def test_default_bands_table_values():
    rb = tb.DEFAULT_TAA_BANDS["regime_bands"]
    assert rb["RISK_ON"]["equity"]["center"] == 0.52
    assert rb["RISK_OFF"]["cash"]["half_width"] == 0.05
    assert rb["INFLATION"]["alternatives"]["center"] == 0.22
```

- [ ] **Step 2: Rodar e ver falhar** — `cd backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -v`.
- [ ] **Step 3: Implementar** o módulo com as constantes e os dois helpers (copiar `compute_effective_band`/`smooth_regime_centers` de `main.py:216-249`, trocando `math` import conforme necessário).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add backend/app/services/taa_bands.py backend/tests/test_taa_bands.py && git commit -m "Add taa_bands: effective-band clamp and EMA center smoothing"`.

---

### Task 2: `combined_regime` (gate composite + overlay quadrante)

**Files:**
- Modify: `backend/app/services/taa_bands.py`
- Test: `backend/tests/test_taa_bands.py`

**Interfaces:**
- Produces: `def combined_regime(composite_state: str | None, quadrant: str | None, *, defensive_on: str = "growth_down", use_infl_bands: bool = True) -> str` retornando `"RISK_ON" | "RISK_OFF" | "INFLATION"`. Port de `_combined_regime` (`main.py:528`). `composite_state` aceita as formas do produto (`"risk_off"`/`"RISK_OFF"`) — normalizar para maiúsculas antes de comparar com `"RISK_OFF"`. `quadrant` aceita `RECOVERY/EXPANSION/SLOWDOWN/CONTRACTION` ou `None`.

Regras (verbatim):
- composite normalizado == `RISK_OFF` → `RISK_OFF`.
- senão `quadrant` é `None` ou `RECOVERY` → `RISK_ON`.
- `EXPANSION` → `INFLATION` se `use_infl_bands` senão `RISK_ON`.
- `SLOWDOWN` → `RISK_OFF`.
- `CONTRACTION` → `RISK_OFF` se `defensive_on=="growth_down"` senão `RISK_ON`.

- [ ] **Step 1: Testes falhando**:

```python
def test_combined_composite_riskoff_dominates():
    assert tb.combined_regime("risk_off", "EXPANSION") == "RISK_OFF"
    assert tb.combined_regime("RISK_OFF", "RECOVERY") == "RISK_OFF"


def test_combined_recovery_is_riskon():
    assert tb.combined_regime("risk_on", "RECOVERY") == "RISK_ON"
    assert tb.combined_regime("risk_on", None) == "RISK_ON"


def test_combined_expansion_uses_inflation_bands():
    assert tb.combined_regime("risk_on", "EXPANSION") == "INFLATION"
    assert tb.combined_regime("risk_on", "EXPANSION", use_infl_bands=False) == "RISK_ON"


def test_combined_slowdown_and_contraction_defensive():
    assert tb.combined_regime("risk_on", "SLOWDOWN") == "RISK_OFF"
    assert tb.combined_regime("risk_on", "CONTRACTION") == "RISK_OFF"
    assert tb.combined_regime("risk_on", "CONTRACTION",
                              defensive_on="stagflation") == "RISK_ON"
```

- [ ] **Step 2: Rodar e ver falhar** — `... pytest tests/test_taa_bands.py -k combined -v`.
- [ ] **Step 3: Implementar** `combined_regime` (com normalização de caixa do `composite_state`).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add backend/app/services/taa_bands.py backend/tests/test_taa_bands.py && git commit -m "Add taa_bands.combined_regime (composite gate + quadrant overlay)"`.

---

### Task 3: `effective_class_bands` (regime → bandas por classe, hw_scale=1.5, clamp)

**Files:**
- Modify: `backend/app/services/taa_bands.py`
- Test: `backend/tests/test_taa_bands.py`

**Interfaces:**
- Consumes: `compute_effective_band`, `smooth_regime_centers`, `DEFAULT_TAA_BANDS`, `IPS_CLASS_BOUNDS`, `HW_SCALE` (Task 1).
- Produces: `def effective_class_bands(regime: str, *, previous_smoothed: dict[str, float] | None = None, hw_scale: float = HW_SCALE) -> tuple[dict[str, tuple[float, float]], dict[str, float]]` — retorna `(bands_por_classe, smoothed_centers)`; port de `_effective_class_bands` (`main.py:574`) SEM estado de instância (centros suavizados passados/retornados explicitamente — no builder point-in-time `previous_smoothed=None`, o que reproduz centros não suavizados = centros crus, fiel ao primeiro passo do reference). `bands` cobre só `ASSET_CLASSES` (4 classes). Half-widths = `half_width * hw_scale`.

- [ ] **Step 1: Testes falhando**:

```python
def test_effective_class_bands_risk_on_wide():
    bands, _ = tb.effective_class_bands("RISK_ON")  # hw_scale 1.5
    lo, hi = bands["equity"]                          # center .52, hw .08*1.5=.12
    assert abs(lo - 0.40) < 1e-9 and abs(hi - 0.64) < 1e-9
    a_lo, a_hi = bands["alternatives"]               # center .12 hw .06 -> [.06,.18], ips (0,.40)
    assert abs(a_lo - 0.06) < 1e-9 and abs(a_hi - 0.18) < 1e-9


def test_effective_class_bands_inflation_alt_tilt():
    bands, _ = tb.effective_class_bands("INFLATION")
    a_lo, a_hi = bands["alternatives"]               # center .22 hw .06*1.5=.09 -> [.13,.31]
    assert abs(a_lo - 0.13) < 1e-9 and abs(a_hi - 0.31) < 1e-9


def test_effective_class_bands_covers_four_classes_only():
    bands, _ = tb.effective_class_bands("RISK_OFF")
    assert set(bands) == {"equity", "fixed_income", "alternatives", "cash"}


def test_effective_class_bands_tight_when_scale_small():
    bands, _ = tb.effective_class_bands("RISK_ON", hw_scale=0.5)
    lo, hi = bands["equity"]                          # hw .08*.5=.04 -> [.48,.56]
    assert abs(lo - 0.48) < 1e-9 and abs(hi - 0.56) < 1e-9
```

- [ ] **Step 2: Rodar e ver falhar** — `... pytest tests/test_taa_bands.py -k effective_class -v`.
- [ ] **Step 3: Implementar** `effective_class_bands` (aplica `hw_scale`, suaviza centros via `smooth_regime_centers`, clampa via `compute_effective_band`).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add backend/app/services/taa_bands.py backend/tests/test_taa_bands.py && git commit -m "Add taa_bands.effective_class_bands (hw_scale + IPS clamp)"`.

---

### Task 4: Reader do `macro_factor_daily` no data-lake

**Files:**
- Modify: `backend/app/services/taa_bands.py` (reader) — OU `backend/app/services/macro_regime.py` se o owner preferir centralizar leituras de data-lake lá; default: em `taa_bands.py`.
- Test: `backend/tests/test_taa_bands_reader.py`

**Interfaces:**
- Consumes: sessão de data-lake (`AsyncSession`), tabela `macro_factor_daily` (criada no Componente 1).
- Produces:
  - `@dataclass(frozen=True) class MacroQuadrantSnapshot: as_of: date; quadrant: str; growth_state: str; inflation_state: str; growth_score: float | None; inflation_score: float | None`.
  - `async def fetch_macro_quadrant(datalake: AsyncSession) -> MacroQuadrantSnapshot | None` — SELECT da última linha por `factor_date DESC LIMIT 1` (espelhar `_COMPOSITE_LATEST_SQL` em `macro_regime.py:147`). `None` se tabela vazia/ausente.

**Investigação obrigatória (implementer):** ler `macro_regime.py:117-238` para copiar EXATAMENTE o padrão de query crua + mapeamento para dataclass (uso de `text()`/`session.execute`, conversão de tipos, tratamento de `None`). Reusar o mesmo estilo de SQL e o mesmo tratamento de tabela inexistente (se o composite reader trata erro de relação ausente, replicar).

- [ ] **Step 1: Teste falhando** — com uma sessão fake que devolve uma linha canônica, `fetch_macro_quadrant` retorna o snapshot tipado; com resultado vazio retorna `None`:

```python
import datetime as dt
import pytest
from app.services import taa_bands as tb


class _Result:
    def __init__(self, row): self._row = row
    def first(self): return self._row
    def mappings(self):  # if the impl uses .mappings().first()
        class _M:
            def __init__(self, r): self._r = r
            def first(self): return self._r
        return _M(self._row)


class _FakeSession:
    def __init__(self, row): self._row = row
    async def execute(self, *a, **k): return _Result(self._row)


@pytest.mark.asyncio
async def test_fetch_macro_quadrant_maps_row():
    row = {"factor_date": dt.date(2026, 6, 18), "quadrant": "EXPANSION",
           "growth_state": "up", "inflation_state": "up",
           "growth_score": 0.07, "inflation_score": 0.02}
    snap = await tb.fetch_macro_quadrant(_FakeSession(row))
    assert snap.quadrant == "EXPANSION"
    assert snap.as_of == dt.date(2026, 6, 18)


@pytest.mark.asyncio
async def test_fetch_macro_quadrant_empty_is_none():
    snap = await tb.fetch_macro_quadrant(_FakeSession(None))
    assert snap is None
```

- [ ] **Step 2: Rodar e ver falhar** — `... pytest tests/test_taa_bands_reader.py -v`. (Ajustar o fake ao mecanismo real de `macro_regime` — `.first()` vs `.mappings().first()` — durante a implementação; manter o teste alinhado ao que a impl usa.)
- [ ] **Step 3: Implementar** `MacroQuadrantSnapshot` + `fetch_macro_quadrant`, espelhando `fetch_composite_regime`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add backend/app/services/taa_bands.py backend/tests/test_taa_bands_reader.py && git commit -m "Add macro_factor_daily reader (fetch_macro_quadrant)"`.

---

## Self-Review (cobertura do spec §4.2 / §5 componente 2)
- `compute_effective_band` + `smooth_regime_centers` (port verbatim) → Task 1.
- `combined_regime` (gate + overlay) → Task 2.
- `effective_class_bands` (hw_scale=1.5 + clamp IPS) → Task 3.
- Reader do `macro_factor_daily` → Task 4.
- `multi_asset` sem banda (O3) documentado nos Global Constraints; consumido no Componente 3.
- Consistência de tipos: `effective_class_bands` retorna `dict[class -> (min,max)]` consumido pelo Componente 3 como `BlockBudget`.
