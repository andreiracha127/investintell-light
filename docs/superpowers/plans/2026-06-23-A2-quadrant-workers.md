# A2 — Quadrant Classification Workers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dois workers que emitem **exatamente o mesmo** `QuadrantSnapshot` (freeze v1 §3) — `MacroReleaseAxisModel` (oficial, consome o point-in-time `latest_vintage_as_of` de A1) e `MarketImpliedAxisModel` (challenger, dos proxies SPY/TIP-IEF que o `regime_gate.py` já calcula) — mais o reader v2 do backend que só consome snapshots `valid`/frescos/confiantes (fail-loud, sem "último não-nulo").

**Architecture:** Tabela nova versionada `regime_quadrant_snapshot` (≠ `regime_gate_daily`, que permanece o gate) + tabela de auditoria `regime_quadrant_indicator_audit` por (`snapshot_id`, indicador). Um núcleo puro compartilhado — `score por eixo` (§4: `economic_transform_id`→`standardizer_id`→`axis_weights`), `axis_hysteresis` (§5, máquina latched espelhando `build_rows` do gate), `axis_confidence` Φ(s/u*) (§6, com as três qualidades completas), `stale_after` (§9) — produz o `QuadrantSnapshot`. Os dois `*AxisModel` só diferem na FONTE dos scores por eixo (macro: PIT de vintages com `economic_transform_id` por família + `standardizer_id` `robust_z_10y_distinct_vintages_v1`, agregados por `axis_weights`; market: SPY 126d return / TIP-IEF breakeven 126d). Rodam **separados**, sem híbrido; market-implied **nunca** é fallback. O gate state-machine (votação 2-de-3 + dwell 21d em `regime_gate_daily`) NÃO muda. O backend troca `_GATE_LATEST_SQL`/`fetch_gate_regime` pela query consumível do §6 (sobre a view operacional `regime_quadrant_current_v`).

**Cadeia latched cross-run (decisão do dono, A2):** como o `snapshot_id` é `uuid5(..., previous_snapshot_id)` e a hysteresis latched depende do estado anterior, cada worker CARREGA o último snapshot da mesma `model_version` (ordenado por `as_of`/`available_at`) para obter (a) o sinal latched por eixo (`*_sign` persistido) e (b) o `previous_snapshot_id`. Isto puxa a cadeia latched para DENTRO de A2; só a CALIBRAÇÃO dos thresholds de hysteresis permanece A3.

**Tech Stack:** Python 3.13, psycopg, pytest (repo worker `E:/investintell-datalake-workers-combo`); FastAPI, SQLAlchemy async, pytest (repo backend `E:/investintell-light-combo/backend`). `Φ` via `statistics.NormalDist` (stdlib). Sem novas deps.

## Global Constraints

- **Worker code (Tasks 1–7):** repo `E:/investintell-datalake-workers-combo` @ branch `feat/combo-regime-gate`. Paths relativos à raiz desse repo. Testes: `.venv/Scripts/python -m pytest ...` do diretório raiz do repo (Windows). Se não houver `.venv`, usar `python -m pytest`.
- **Backend code (Task 8 SÓ):** repo `E:/investintell-light-combo/backend` @ branch `feat/combo-regime-allocator`. Paths da Task 8 relativos a `backend/`. Testes: `.venv/Scripts/python -m pytest ...` do diretório `backend/`. Esta task é AUTOCONTIDA; sinalize a dependência cruzada com o plano Policy Core (track B) que também toca `taa_bands.py` (ver Task 8).
- **NÃO alterar** `regime_gate.py`, `regime_gate.sql`, nem a lógica do gate (votação/dwell). O quadrante v2 é tabela/worker NOVO, isolado. Reusar SÓ os PADRÕES (`build_rows` state machine, `ensure_schema`/`run`/`advisory_lock`, `_upsert` em chunks).
- **Contrato A1 que se CONSOME / EVOLUI** (repo worker, branch `feat/combo-regime-gate`): `src/macro_pit.py::latest_vintage_as_of(conn, series_ids, decision_time) -> dict[str, dict[date, float]]` (inalterado); `src/macro_sources.py::SEED_SOURCES`, `axis_weights(axis) -> dict[series_id, float]`, `SOURCE_SPEC_VERSION="macro_quadrant_us_v1.0"`, `MacroSourceSpec`. **O `MacroSourceSpec` é EVOLUÍDO nesta plano (Task 0):** o campo único `transform_id` é DIVIDIDO em `economic_transform_id` (extrai o impulso econômico) + `standardizer_id` (torna séries comparáveis); adiciona-se `neutral_level: float | None` e `minimum_valid_observations: int`; remove-se `transform_id`. `SEED_SOURCES` é reescrito mapeando cada série à sua família/transform (Task 0). Mesmo repo/branch de A1 → o schema novo do dataclass SOBRESCREVE o de A1 (ver "Conflito com A1" abaixo).
- **Constantes congeladas (FÓRMULAS travadas agora; THRESHOLDS/FLOORS pertencem ao parameter freeze, calibrar em A3 — SÓ contra abstenção/flips/estabilidade de vintage, NUNCA contra CAGR/Sharpe):** `AXIS_ENTER = 0.25`; `AXIS_EXIT = 0.10`; `MIN_CANDIDATE_CONFIDENCE = 0.70`; `MIN_INPUT_COVERAGE = 0.80`; `MIN_SOURCE_HEALTH = 0.90`; `UNCERTAINTY_WINDOW_VINTAGES = 36`; `MIN_UNCERTAINTY_VINTAGES = 24`; `Q_DATA_FLOOR = 0.25`; `U_FLOOR_SEED = {"growth": 0.25, "inflation": 0.25}` (decisão do dono — SOBRESCREVE os antigos 12 / 0.05; calibração futura `u_floor_a = max(0.25, P10(u_raw_a no training))`, congelado em `confidence_model_version`, sem recalcular com dados futuros).
- **Standardizer universal v1:** `STANDARDIZER_ID = "robust_z_10y_distinct_vintages_v1"`: `z_{k,t} = clip( (x_{k,t} − median(x_k)) / (1.4826·MAD(x_k)), −4, 4 )` sobre janela point-in-time de até 10 anos de VINTAGES DISTINTOS (nunca linhas forward-filled). Sem fallback automático `3m3m`→`yoy`: série sem dados para o transform declarado fica INDISPONÍVEL. `economic_transform_id`/`standardizer_id`/`direction`/`neutral_level` pertencem ao `source_spec_version`; alterar qualquer um exige novo `model_version`.
- **Versões de proveniência:** `MODEL_VERSION_MACRO = "macro_quadrant_us_v1"`; `MODEL_VERSION_MARKET = "market_implied_quadrant_v0"`; `CONFIDENCE_MODEL_VERSION = "confidence_v1.0"`; `CONFIDENCE_METHOD_MACRO = "rolling_score_mad_distinct_vintages_v1"`; `CONFIDENCE_METHOD_MARKET = "rolling_score_mad_252bd_v1"`.
- **Fail-loud (freeze §1.7, §2, §6):** status ∈ {`valid`,`low_confidence`,`unavailable`,`invalid`}; só `valid` é consumível. `quadrant` (consumível) é NÃO-NULO **somente** quando `status_at_compute=="valid"`; `candidate_quadrant` (auditoria/UI) pode existir em qualquer status≠unavailable/invalid. Proibido `None→expansion`, `None→risk_on`, forward-fill do último não-nulo.
- **ORDEM DE STATUS canônica (decisão do dono — SOBRESCREVE a ordem antiga):**

  ```text
  critical structural failure   -> invalid
  coverage < 0.80               -> unavailable
  critical source expired       -> stale
  health < 0.90                 -> low_confidence
  confidence < 0.70             -> low_confidence
  transition_pending            -> low_confidence
  otherwise                     -> valid
  ```

- **Lock advisory novo:** `LOCK_REGIME_QUADRANT = 900_208` (banda métricas 900_2xx; próximo livre após `LOCK_REGIME_GATE=900_207`).
- **`snapshot_id` determinístico via `uuid5`** (decisão do dono — SOBRESCREVE o `model_version:as_of:vintage_hash[:12]` como PK): `REGIME_SNAPSHOT_NAMESPACE = uuid5(NAMESPACE_URL, "investintell/regime_quadrant_snapshot")` (constante fixa no módulo); `snapshot_id = uuid5(REGIME_SNAPSHOT_NAMESPACE, "|".join([model_version, as_of.isoformat(), source_vintage_hash, previous_snapshot_id or "GENESIS"]))`. O `previous_snapshot_id` é NECESSÁRIO porque a hysteresis latched depende do estado anterior. Os 12 primeiros chars de `source_vintage_hash` são SÓ para logs/UI, nunca PK.
- **`source_vintage_hash`** = SHA-256 sobre representação canônica ORDENADA dos campos por observação: `source_id, observation_period, value, unit, release_at, available_at, vintage_id, revision_number, source_spec_version`.
- **Hard max ages (§9):** mensal 45 dias corridos (macro: em `MacroSourceSpec.hard_max_age`); diária 3 dias úteis (market). `pipeline_stale_after = computed_at + 2 dias úteis`. "Dia útil" aproximado por contagem seg–sex (sem calendário de feriados na v1 — ponto de calibração).

- **Conflito com A1 (mesmo repo/branch `feat/combo-regime-gate`):** A1 já entregou `MacroSourceSpec` com `transform_id` único e `SEED_SOURCES` com `transform="yoy"`. A Task 0 deste plano EVOLUI esse mesmo arquivo (`src/macro_sources.py`): troca `transform_id` por `economic_transform_id`+`standardizer_id`, adiciona `neutral_level`/`minimum_valid_observations`, e reescreve `SEED_SOURCES`. O worker A1 `macro_vintage.py` NÃO referencia `transform_id` (só ingere vintages), então não quebra; `axis_weights` mantém a assinatura. Os testes de A1 que afirmarem `transform_id`/`transform="yoy"` são ATUALIZADOS na Task 0 (Step 1). `SOURCE_SPEC_VERSION` permanece `"macro_quadrant_us_v1.0"` (mesmo `model_version`, schema do spec evoluído ainda dentro da v1 pré-freeze de parâmetros).
- **NÃO INCLUIR** (escopos separados): compilador two-level / matriz M / preflight / pós-verificação (Plano C); `QuadrantPolicy`/`GateOverlay`/políticas dos 4 quadrantes (track B Policy Core). A única ponte com produção neste plano é o reader v2 (Task 8).

---

### Task 0: Evolve `MacroSourceSpec` + economic transforms + robust-z standardizer

> **REPO:** worker repo `E:/investintell-datalake-workers-combo` @ `feat/combo-regime-gate`. This evolves the A1 `src/macro_sources.py` IN PLACE (two-stage transform contract) and adds the pure, testable transform/standardizer functions the score (Task 3) consumes. It runs FIRST so every downstream task references the new `MacroSourceSpec`.

**Files:**
- Modify: `src/macro_sources.py` (split `transform_id` → `economic_transform_id`+`standardizer_id`; add `neutral_level`, `minimum_valid_observations`; rewrite `SEED_SOURCES`)
- Create: `src/macro_transforms.py` (pure economic-transform + standardizer functions)
- Modify (if present): `tests/test_macro_sources.py` (A1 tests asserting `transform_id`/`transform="yoy"`)
- Test: `tests/test_macro_transforms.py`

**Interfaces:**
- Produces (evolved dataclass — every downstream task uses THIS shape):

  ```python
  @dataclass(frozen=True)
  class MacroSourceSpec:
      source_id: str
      axis: Literal["growth", "inflation"]
      family: str
      economic_transform_id: str
      standardizer_id: str
      direction: Literal[-1, 1]
      neutral_level: float | None
      weight: float
      critical: bool
      minimum_valid_observations: int
      source_spec_version: str
  ```

  (The A1 cadence/release_calendar_id/revision_policy/grace_period/hard_max_age/minimum_history fields are dropped from the EXAMPLE above for the owner's verbatim contract, but A2 still needs `cadence`/`grace_period`/`hard_max_age`/`critical` for staleness — so KEEP those existing fields too and ADD the four new ones; the verbatim block is the delta, not a full replacement. The four MANDATORY additions/changes are: `economic_transform_id`, `standardizer_id`, `neutral_level`, `minimum_valid_observations`, and the REMOVAL of `transform_id`.)
- Produces (pure functions in `src/macro_transforms.py`): `economic_transform(transform_id: str, series: dict[date, float], *, neutral_level: float | None = None) -> dict[date, float]`; `robust_z(values: list[float]) -> float | None` and `standardize(standardizer_id: str, history_distinct: list[float], current: float) -> float | None`.
- `economic_transform_id` defaults by family (v1):

  | Família | economic_transform_id v1 | Interpretação |
  |---|---|---|
  | Atividade mensal dessaz. (produção, vendas reais, renda, payroll) | `log_3m3m_ann_v1` | ritmo recente de crescimento |
  | Atividade trimestral (PIB real) | `log_qoq_saar_v1` | crescimento trimestral anualizado |
  | Surveys/diffusion (ISM, PMI) | `mean3_gap_neutral_v1` | média 3m menos nível neutro |
  | Unemployment rate | `delta_3m_level_v1` (direction=-1) | aumento do desemprego enfraquece growth |
  | Initial claims | `log_3m3m_ann_v1` (direction=-1) | aumento de claims enfraquece growth |
  | CPI/PCE/PPI/wages dessaz. | `ann3m_minus_yoy_v1` | inflação recente vs tendência anual |
  | Price index não dessaz. | `delta_3m_yoy_v1` | aceleração/desaceleração do YoY |
  | Breakevens/expectativas de inflação | `delta_3m_level_v1` | mudança recente das expectativas |

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_macro_transforms.py
from __future__ import annotations

import datetime as dt
import math

from src.macro_transforms import economic_transform, robust_z, standardize


def _monthly(values: list[float], start=dt.date(2022, 1, 1)) -> dict[dt.date, float]:
    """Build a {month-start: value} series of len(values) consecutive months."""
    out: dict[dt.date, float] = {}
    y, m = start.year, start.month
    for v in values:
        out[dt.date(y, m, 1)] = v
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def test_log_3m3m_ann_matches_formula() -> None:
    # 3m3mAnn_t = 4*[ log(mean(x_{t-2..t})) - log(mean(x_{t-5..t-3})) ].
    series = _monthly([100, 101, 102, 103, 104, 105])  # 6 months -> last is computable
    out = economic_transform("log_3m3m_ann_v1", series)
    last = max(out)
    recent = (103 + 104 + 105) / 3
    prior = (100 + 101 + 102) / 3
    assert abs(out[last] - 4.0 * (math.log(recent) - math.log(prior))) < 1e-12
    # the first 5 months have no 6-month base -> dropped
    assert dt.date(2022, 1, 1) not in out


def test_ann3m_minus_yoy_inflation_impulse() -> None:
    # 4*(log x_t - log x_{t-3}) - (log x_t - log x_{t-12}); needs >=13 months.
    series = _monthly([100 + i for i in range(13)])
    out = economic_transform("ann3m_minus_yoy_v1", series)
    t = max(out)
    x_t = series[t]
    x_t3 = series[dt.date(2022, 10, 1)]   # 3 months before 2023-01
    x_t12 = series[dt.date(2022, 1, 1)]
    expect = 4.0 * (math.log(x_t) - math.log(x_t3)) - (math.log(x_t) - math.log(x_t12))
    assert abs(out[t] - expect) < 1e-12


def test_mean3_gap_neutral_uses_neutral_level() -> None:
    series = _monthly([48, 50, 52])  # mean3 = 50
    out = economic_transform("mean3_gap_neutral_v1", series, neutral_level=50.0)
    assert abs(out[max(out)] - 0.0) < 1e-12


def test_delta_3m_level_is_level_change() -> None:
    series = _monthly([4.0, 4.0, 4.0, 4.4])  # x_t - x_{t-3} = 0.4
    out = economic_transform("delta_3m_level_v1", series)
    assert abs(out[max(out)] - 0.4) < 1e-12


def test_unknown_transform_raises() -> None:
    try:
        economic_transform("nope_v1", _monthly([1, 2, 3]))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_robust_z_clips_at_four_sigma() -> None:
    hist = [0.0] * 11 + [1000.0]          # median 0, MAD 0 -> degenerate
    assert robust_z(hist) is None         # MAD == 0 -> undefined (caller floors elsewhere)
    spread = [float(i) for i in range(-5, 6)]  # symmetric, MAD > 0
    # an extreme current value clips to +4
    assert standardize("robust_z_10y_distinct_vintages_v1", spread, 1e6) == 4.0


def test_standardize_centers_on_median() -> None:
    hist = [1.0, 2.0, 3.0, 4.0, 5.0]
    z = standardize("robust_z_10y_distinct_vintages_v1", hist, 3.0)  # current == median
    assert abs(z - 0.0) < 1e-12
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_macro_transforms.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.macro_transforms'`

- [ ] **Step 3: Implement the two-stage transform**

```python
# src/macro_transforms.py
"""Two-stage macro transform (freeze scope §4, owner decision A): an
ECONOMIC transform per family extracts the impulse, then a single universal
STANDARDIZER ('robust_z_10y_distinct_vintages_v1') makes axes comparable.

There is NO automatic 3m3m->yoy fallback: a series without enough data for its
declared economic_transform_id stays UNAVAILABLE (Task 3 treats a None as a
missing input -> coverage penalty / abstention). Both stages belong to the
source_spec_version; changing either requires a new model_version.
"""
from __future__ import annotations

import datetime as _dt
import math
import statistics

_MAD_SCALE = 1.4826
_Z_CLIP = 4.0


def _sorted_periods(series: dict[_dt.date, float]) -> list[_dt.date]:
    return sorted(series)


def _shift_months(periods: list[_dt.date], idx: int, back: int) -> _dt.date | None:
    """The period ``back`` calendar months before periods[idx] IF it exists in the
    index (no interpolation; macro series are regular month-starts)."""
    target = periods[idx]
    y, m = target.year, target.month
    m -= back
    while m <= 0:
        m += 12
        y -= 1
    cand = _dt.date(y, m, 1)
    return cand if cand in set(periods) else None


def economic_transform(
    transform_id: str,
    series: dict[_dt.date, float],
    *,
    neutral_level: float | None = None,
) -> dict[_dt.date, float]:
    """{period: value} -> {period: economic impulse}. Periods without the required
    history are dropped (not interpolated)."""
    periods = _sorted_periods(series)
    pos = {p: i for i, p in enumerate(periods)}
    out: dict[_dt.date, float] = {}

    if transform_id == "log_3m3m_ann_v1":
        # 4 * [ log(mean(x_{t-2..t})) - log(mean(x_{t-5..t-3})) ]
        for t, i in pos.items():
            if i < 5:
                continue
            recent = [series[periods[j]] for j in (i - 2, i - 1, i)]
            prior = [series[periods[j]] for j in (i - 5, i - 4, i - 3)]
            mr, mp = statistics.fmean(recent), statistics.fmean(prior)
            if mr > 0 and mp > 0:
                out[t] = 4.0 * (math.log(mr) - math.log(mp))
        return out

    if transform_id == "log_qoq_saar_v1":
        # quarterly real GDP: 4 * (log x_t - log x_{t-1quarter==3 months})
        for t, i in pos.items():
            prev = _shift_months(periods, i, 3)
            if prev is None:
                continue
            xt, xp = series[t], series[prev]
            if xt > 0 and xp > 0:
                out[t] = 4.0 * (math.log(xt) - math.log(xp))
        return out

    if transform_id == "mean3_gap_neutral_v1":
        if neutral_level is None:
            raise ValueError("mean3_gap_neutral_v1 requires neutral_level")
        for t, i in pos.items():
            if i < 2:
                continue
            mean3 = statistics.fmean(series[periods[j]] for j in (i - 2, i - 1, i))
            out[t] = mean3 - neutral_level
        return out

    if transform_id == "delta_3m_level_v1":
        # x_t - x_{t-3}
        for t, i in pos.items():
            prev = _shift_months(periods, i, 3)
            if prev is not None:
                out[t] = series[t] - series[prev]
        return out

    if transform_id == "delta_3m_yoy_v1":
        # change in YoY: yoy_t - yoy_{t-3}, with yoy = x_t/x_{t-12} - 1
        yoy: dict[_dt.date, float] = {}
        for t, i in pos.items():
            prev12 = _shift_months(periods, i, 12)
            if prev12 is not None and series[prev12] != 0:
                yoy[t] = series[t] / series[prev12] - 1.0
        ypos = {p: i for i, p in enumerate(sorted(yoy))}
        yperiods = sorted(yoy)
        for t, i in ypos.items():
            if i >= 3:
                out[t] = yoy[t] - yoy[yperiods[i - 3]]
        return out

    if transform_id == "ann3m_minus_yoy_v1":
        # InflationImpulse: 4*(log x_t - log x_{t-3}) - (log x_t - log x_{t-12})
        for t, i in pos.items():
            p3 = _shift_months(periods, i, 3)
            p12 = _shift_months(periods, i, 12)
            if p3 is None or p12 is None:
                continue
            xt, x3, x12 = series[t], series[p3], series[p12]
            if xt > 0 and x3 > 0 and x12 > 0:
                out[t] = 4.0 * (math.log(xt) - math.log(x3)) - (
                    math.log(xt) - math.log(x12))
        return out

    raise ValueError(f"unknown economic_transform_id: {transform_id!r}")


def robust_z(values: list[float]) -> float | None:
    """Helper returning the robust scale only — None when MAD == 0 (degenerate)."""
    if len(values) < 2:
        return None
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values])
    return _MAD_SCALE * mad if mad > 0 else None


def standardize(
    standardizer_id: str, history_distinct: list[float], current: float
) -> float | None:
    """z = clip( (current - median) / (1.4826*MAD), -4, +4 ) over DISTINCT vintages.

    Returns None when the robust scale is undefined (MAD == 0 or < 2 values); the
    caller treats None as a missing standardized input.
    """
    if standardizer_id != "robust_z_10y_distinct_vintages_v1":
        raise ValueError(f"unknown standardizer_id: {standardizer_id!r}")
    distinct = sorted(set(history_distinct))
    scale = robust_z(distinct)
    if scale is None:
        return None
    median = statistics.median(distinct)
    z = (current - median) / scale
    return max(-_Z_CLIP, min(_Z_CLIP, z))
```

- [ ] **Step 4: Evolve `MacroSourceSpec` + `SEED_SOURCES`**

In `src/macro_sources.py`, change the dataclass to the two-stage contract (KEEP the A2 staleness fields `cadence`/`release_calendar_id`/`revision_policy`/`grace_period`/`hard_max_age`; ADD the four owner-mandated fields; REMOVE `transform_id`; rename `minimum_history` → `minimum_valid_observations`):

```python
@dataclass(frozen=True)
class MacroSourceSpec:
    source_id: str
    series_id: str
    axis: Literal["growth", "inflation"]
    family: str
    economic_transform_id: str
    standardizer_id: str
    direction: Literal[-1, 1]
    neutral_level: float | None
    weight: float
    cadence: Literal["daily", "weekly", "monthly", "quarterly"]
    release_calendar_id: str | None
    revision_policy: Literal["none", "vintage"]
    grace_period: timedelta
    hard_max_age: timedelta
    critical: bool
    minimum_valid_observations: int
    source_spec_version: str = SOURCE_SPEC_VERSION


_STD = "robust_z_10y_distinct_vintages_v1"


def _macro(series_id, axis, family, weight, econ_transform, *, direction=1,
           neutral_level=None, cadence="monthly", critical=True,
           min_valid_obs=24):
    return MacroSourceSpec(
        source_id=f"alfred:{series_id}", series_id=series_id, axis=axis, family=family,
        economic_transform_id=econ_transform, standardizer_id=_STD,
        direction=direction, neutral_level=neutral_level, weight=weight,
        cadence=cadence, release_calendar_id=None, revision_policy="vintage",
        grace_period=timedelta(days=7), hard_max_age=timedelta(days=45),
        critical=critical, minimum_valid_observations=min_valid_obs,
    )


SEED_SOURCES: tuple[MacroSourceSpec, ...] = (
    # growth axis — monthly seasonally-adjusted activity -> log_3m3m_ann_v1.
    _macro("INDPRO", "growth", "activity_production", 0.25, "log_3m3m_ann_v1"),
    _macro("PCEC96", "growth", "real_consumption", 0.25, "log_3m3m_ann_v1"),
    _macro("PAYEMS", "growth", "labor", 0.25, "log_3m3m_ann_v1"),
    _macro("ACOGNO", "growth", "new_orders_leading", 0.25, "log_3m3m_ann_v1"),
    # inflation axis — SA price/wage indices -> ann3m_minus_yoy_v1 (InflationImpulse);
    # expectations are a level survey -> delta_3m_level_v1.
    _macro("CPILFESL", "inflation", "core_inflation", 0.30, "ann3m_minus_yoy_v1"),
    _macro("PPIFIS", "inflation", "upstream_prices", 0.25, "ann3m_minus_yoy_v1"),
    _macro("AHETPI", "inflation", "wages", 0.25, "ann3m_minus_yoy_v1"),
    _macro("MICH", "inflation", "inflation_expectations", 0.20, "delta_3m_level_v1"),
)
```

`axis_weights` is unchanged (still reads `s.axis`/`s.weight`). Update any A1 test asserting `transform_id` or `transform="yoy"` to assert `economic_transform_id`/`standardizer_id` instead.

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_macro_transforms.py tests/test_macro_sources.py -v`
Expected: PASS (all — transform tests + the updated source-spec tests).

- [ ] **Step 6: Commit**

```bash
git add src/macro_transforms.py src/macro_sources.py tests/test_macro_transforms.py tests/test_macro_sources.py
git commit -m "feat(quadrant): two-stage macro transform (economic_transform_id + robust-z standardizer)"
```

---

### Task 1: Schema `regime_quadrant_snapshot` + auditoria + lock id

**Files:**
- Create: `schemas/regime_quadrant_snapshot.sql`
- Modify: `src/db.py` (registrar `LOCK_REGIME_QUADRANT`)
- Test: `tests/test_regime_quadrant_schema.py`

**Interfaces:**
- Produces: tabela `regime_quadrant_snapshot` com PK `(snapshot_id)` (uuid de `uuid5`), UNIQUE `(model_version, as_of, source_vintage_hash, previous_snapshot_id)`, colunas do §3 + `previous_snapshot_id` + os sinais latched persistidos (`growth_internal_sign`/`inflation_internal_sign`) e os CHECKs do §7; view operacional `regime_quadrant_current_v` (só `valid`+não-vencido); tabela `regime_quadrant_indicator_audit(snapshot_id, axis, series_id, ...)`; `db.LOCK_REGIME_QUADRANT = 900_208`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_regime_quadrant_schema.py
"""Schema + lock id for the versioned QuadrantSnapshot table (freeze v1 §3/§7/§10)."""
from __future__ import annotations

import pathlib

from src import db

_SQL = (pathlib.Path(__file__).resolve().parents[1]
        / "schemas" / "regime_quadrant_snapshot.sql").read_text(encoding="utf-8")


def test_table_declares_all_snapshot_columns() -> None:
    assert "CREATE TABLE IF NOT EXISTS regime_quadrant_snapshot" in _SQL
    for col in (
        "snapshot_id", "previous_snapshot_id",
        "quadrant", "candidate_quadrant", "candidate_confidence",
        "growth_score", "growth_sign", "growth_internal_sign",
        "growth_candidate_confidence", "growth_margin",
        "growth_uncertainty_raw", "growth_uncertainty_adjusted",
        "inflation_score", "inflation_sign", "inflation_internal_sign",
        "inflation_candidate_confidence",
        "inflation_margin", "inflation_uncertainty_raw", "inflation_uncertainty_adjusted",
        "coverage_quality", "freshness_quality", "source_health_quality",
        "transition_pending", "transition_reason",
        "as_of", "available_at", "computed_at",
        "data_stale_after", "pipeline_stale_after", "stale_after",
        "status_at_compute", "model_version", "confidence_model_version",
        "confidence_method", "source_vintage_hash",
    ):
        assert col in _SQL, f"missing column {col}"


def test_pk_is_snapshot_id_and_unique_includes_previous() -> None:
    assert "PRIMARY KEY (snapshot_id)" in _SQL
    # owner decision: the UNIQUE includes previous_snapshot_id (latched identity).
    assert "UNIQUE (model_version, as_of, source_vintage_hash, previous_snapshot_id)" in _SQL


def test_coherence_checks_present() -> None:
    # §7: valid <=> quadrant+candidate filled & confidence>=0.70 & no pending;
    #     non-valid => quadrant NULL; unavailable/invalid => candidate_confidence NULL.
    assert "status_at_compute = 'valid'" in _SQL
    assert "candidate_confidence >= 0.70" in _SQL
    assert "transition_pending = FALSE" in _SQL
    assert "quadrant IS NULL" in _SQL
    assert "stale_after <= data_stale_after" in _SQL
    assert "stale_after <= pipeline_stale_after" in _SQL
    assert "computed_at >= available_at" in _SQL
    assert "as_of <= available_at" in _SQL
    # quality fields in [0,1]
    assert "coverage_quality BETWEEN 0 AND 1" in _SQL


def test_status_domain_check() -> None:
    for s in ("valid", "low_confidence", "unavailable", "invalid"):
        assert f"'{s}'" in _SQL


def test_operational_view_filters_valid_and_unexpired() -> None:
    assert "CREATE OR REPLACE VIEW regime_quadrant_current_v" in _SQL
    assert "status_at_compute = 'valid'" in _SQL
    assert "stale_after >" in _SQL  # current view excludes expired snapshots


def test_audit_table_has_lineage_columns() -> None:
    assert "CREATE TABLE IF NOT EXISTS regime_quadrant_indicator_audit" in _SQL
    for col in ("snapshot_id", "axis", "series_id", "z_score", "weight",
                "coverage", "freshness", "source_health", "anomaly",
                "observation_period", "vintage_id", "revision_number"):
        assert col in _SQL


def test_lock_id_registered_and_unique() -> None:
    assert db.LOCK_REGIME_QUADRANT == 900_208
    ids = [v for k, v in vars(db).items() if k.startswith("LOCK_") and isinstance(v, int)]
    assert ids.count(900_208) == 1
    assert db.LOCK_REGIME_QUADRANT != db.LOCK_REGIME_GATE
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_regime_quadrant_schema.py -v`
Expected: FAIL — `FileNotFoundError` (no .sql) and `AttributeError: LOCK_REGIME_QUADRANT`.

- [ ] **Step 3: Create the schema + register the lock**

`schemas/regime_quadrant_snapshot.sql`:

```sql
-- regime_quadrant_snapshot — versioned QuadrantSnapshot (freeze v1 §3/§7/§10).
--
-- The STRATEGIC quadrant (macro, point-in-time) and the MARKET-implied challenger
-- both write here, distinguished by model_version. This is a DIFFERENT dimension
-- from regime_gate_daily (the risk gate) — they have independent SLA/staleness
-- (§1.1). PK is snapshot_id, a deterministic uuid5 over
-- (model_version | as_of | source_vintage_hash | previous_snapshot_id) — owner
-- decision: previous_snapshot_id is part of the identity because the latched
-- hysteresis result depends on the predecessor. The table is IMMUTABLE: re-running
-- the same model with the same inputs AND predecessor reproduces the same id, so the
-- daily recompute upserts in place instead of exploding rows.
--
-- status_at_compute is PERSISTED and IMMUTABLE; effective_status (stale) is
-- derived AT READ. quadrant (consumable) is non-NULL ONLY when status='valid';
-- candidate_quadrant (audit/UI) is the instantaneous classification.
-- growth_internal_sign/inflation_internal_sign persist the LATCHED memory so the
-- next run can resume the hysteresis chain (the worker reads the last row by
-- as_of/available_at). regime_quadrant_current_v exposes ONLY the consumable,
-- unexpired snapshot; the full history stays in regime_quadrant_snapshot.
--
-- Apply against the cloud: psql "$DATABASE_URL" -f schemas/regime_quadrant_snapshot.sql

CREATE TABLE IF NOT EXISTS regime_quadrant_snapshot (
    snapshot_id                     uuid          NOT NULL,        -- uuid5(namespace, model|as_of|vintage|prev)
    previous_snapshot_id            uuid,                          -- NULL at genesis; closes the latched chain
    -- consumable + candidate classification
    quadrant                        text,                          -- recovery|expansion|slowdown|contraction; NULL unless valid
    candidate_quadrant              text,                          -- instantaneous (audit/UI)
    candidate_confidence            numeric(6,4),                  -- min over axes; NULL if unavailable/invalid
    -- growth axis diagnostics (§3 AxisDiagnostics)
    growth_score                    numeric(18,8),
    growth_sign                     smallint,                      -- -1|1|NULL (post-hysteresis EFFECTIVE/consumable sign)
    growth_internal_sign            smallint,                      -- -1|1|NULL (LATCHED memory carried to next run)
    growth_candidate_confidence     numeric(6,4),
    growth_margin                   numeric(18,8),
    growth_uncertainty_raw          numeric(18,8),
    growth_uncertainty_adjusted     numeric(18,8),
    -- inflation axis diagnostics
    inflation_score                 numeric(18,8),
    inflation_sign                  smallint,
    inflation_internal_sign         smallint,
    inflation_candidate_confidence  numeric(6,4),
    inflation_margin                numeric(18,8),
    inflation_uncertainty_raw       numeric(18,8),
    inflation_uncertainty_adjusted  numeric(18,8),
    -- aggregate quality (§4) and transition
    coverage_quality                numeric(6,4)  NOT NULL,
    freshness_quality               numeric(6,4)  NOT NULL,
    source_health_quality           numeric(6,4)  NOT NULL,
    transition_pending              boolean       NOT NULL DEFAULT false,
    transition_reason               text,
    -- point-in-time + staleness (§8/§9)
    as_of                           date          NOT NULL,
    available_at                    timestamptz   NOT NULL,
    computed_at                     timestamptz   NOT NULL DEFAULT now(),
    data_stale_after                timestamptz   NOT NULL,
    pipeline_stale_after            timestamptz   NOT NULL,
    stale_after                     timestamptz   NOT NULL,
    -- status + provenance (§3/§36)
    status_at_compute               text          NOT NULL,
    model_version                   text          NOT NULL,
    confidence_model_version        text          NOT NULL,
    confidence_method               text          NOT NULL,
    source_vintage_hash             text          NOT NULL,

    CONSTRAINT regime_quadrant_snapshot_pkey PRIMARY KEY (snapshot_id),
    -- owner decision: identity includes previous_snapshot_id (the hysteresis result
    -- depends on the predecessor); re-running the same model with the same inputs AND
    -- predecessor yields the same uuid -> the daily upsert stays idempotent.
    -- NULLS NOT DISTINCT so the genesis row (previous=NULL) is also de-duplicated.
    CONSTRAINT uq_regime_quadrant_version
        UNIQUE NULLS NOT DISTINCT
        (model_version, as_of, source_vintage_hash, previous_snapshot_id),
    CONSTRAINT ck_rqs_status_domain CHECK (
        status_at_compute IN ('valid', 'low_confidence', 'unavailable', 'invalid')
    ),
    CONSTRAINT ck_rqs_quadrant_domain CHECK (
        quadrant IS NULL OR quadrant IN
        ('recovery', 'expansion', 'slowdown', 'contraction')
    ),
    CONSTRAINT ck_rqs_candidate_domain CHECK (
        candidate_quadrant IS NULL OR candidate_quadrant IN
        ('recovery', 'expansion', 'slowdown', 'contraction')
    ),
    -- §7 coherence: valid <=> fully classified, confident, no pending; else quadrant NULL.
    CONSTRAINT ck_rqs_valid_coherence CHECK (
        (status_at_compute = 'valid' AND quadrant IS NOT NULL
            AND candidate_quadrant IS NOT NULL AND candidate_confidence IS NOT NULL
            AND candidate_confidence >= 0.70 AND transition_pending = FALSE)
        OR (status_at_compute <> 'valid' AND quadrant IS NULL)
    ),
    -- §7: unavailable/invalid carry NO confidence.
    CONSTRAINT ck_rqs_unavailable_no_confidence CHECK (
        status_at_compute NOT IN ('unavailable', 'invalid')
        OR candidate_confidence IS NULL
    ),
    -- quality fields in [0,1]
    CONSTRAINT ck_rqs_coverage_range CHECK (coverage_quality BETWEEN 0 AND 1),
    CONSTRAINT ck_rqs_freshness_range CHECK (freshness_quality BETWEEN 0 AND 1),
    CONSTRAINT ck_rqs_health_range CHECK (source_health_quality BETWEEN 0 AND 1),
    -- §7/§9 temporal ordering
    CONSTRAINT ck_rqs_stale_le_data CHECK (stale_after <= data_stale_after),
    CONSTRAINT ck_rqs_stale_le_pipeline CHECK (stale_after <= pipeline_stale_after),
    CONSTRAINT ck_rqs_computed_ge_available CHECK (computed_at >= available_at),
    CONSTRAINT ck_rqs_asof_le_available CHECK (as_of <= available_at),
    -- §7 provenance non-empty
    CONSTRAINT ck_rqs_version_nonempty CHECK (
        length(model_version) > 0 AND length(source_vintage_hash) > 0
    )
);

-- §6 consumable read: filter valid + fresh + confident, newest available_at first.
CREATE INDEX IF NOT EXISTS regime_quadrant_snapshot_consume_idx
    ON regime_quadrant_snapshot (model_version, available_at DESC)
    WHERE status_at_compute = 'valid' AND quadrant IS NOT NULL;

-- Latched-chain read: newest snapshot per model_version (worker resumes hysteresis).
CREATE INDEX IF NOT EXISTS regime_quadrant_snapshot_latest_idx
    ON regime_quadrant_snapshot (model_version, as_of DESC, available_at DESC);

-- Operational view: ONLY the consumable, unexpired snapshot per model_version.
-- The backend reader selects from this view; the full audit trail lives in the base
-- table. now() at query time excludes snapshots already past stale_after.
CREATE OR REPLACE VIEW regime_quadrant_current_v AS
SELECT DISTINCT ON (model_version) *
FROM regime_quadrant_snapshot
WHERE status_at_compute = 'valid'
  AND quadrant IS NOT NULL
  AND candidate_confidence >= 0.70
  AND stale_after > now()
ORDER BY model_version, available_at DESC;

-- §10 per-indicator audit + per-observation lineage: one row per (snapshot, axis,
-- indicator). Carries the individual observation period / vintage so the audit can
-- distinguish ambiguous-macro / missing-coverage / late-source / ingestion-fault /
-- anomalous-revision / high-statistical-uncertainty (freeze §10). The snapshot row
-- itself stores only aggregates; individual observation dates live HERE, not in as_of.
CREATE TABLE IF NOT EXISTS regime_quadrant_indicator_audit (
    snapshot_id        uuid          NOT NULL,
    axis               text          NOT NULL,   -- 'growth' | 'inflation'
    series_id          text          NOT NULL,
    z_score            numeric(18,8),            -- standardized contribution z_k
    weight             numeric(18,8),            -- renormalized w_k
    coverage           numeric(6,4),
    freshness          numeric(6,4),
    source_health      numeric(6,4),
    anomaly            text,                      -- NULL = none; else a short tag
    observation_period date,                      -- the obs date that fed z_k
    vintage_id         text,                      -- vintage identity (lineage)
    revision_number    integer,                   -- revision lineage
    PRIMARY KEY (snapshot_id, axis, series_id),
    CONSTRAINT ck_rqia_axis CHECK (axis IN ('growth', 'inflation'))
);
```

In `src/db.py`, add after `LOCK_REGIME_GATE = 900_207`:

```python
LOCK_REGIME_QUADRANT = 900_208
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_regime_quadrant_schema.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Validate the DDL against Timescale via BEGIN/ROLLBACK**

`UNIQUE NULLS NOT DISTINCT` requires PostgreSQL 15+ (Tiger cloud is PG16 — OK). Apply the file inside a transaction and roll back (no persistent change). Use the Tiger MCP `db_execute_query` against service `t83f4np6x4`, or psql:

```bash
# Owner/session step — needs DATABASE_URL (cloud DSN). Sandbox off not required (no egress).
psql "$DATABASE_URL" -1 -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
\i schemas/regime_quadrant_snapshot.sql
ROLLBACK;
SQL
```

Expected: `ROLLBACK` with no error (DDL parses + all CHECK constraints accepted). If running via Tiger MCP, wrap the file contents in a single `BEGIN; ... ROLLBACK;`.

- [ ] **Step 6: Commit**

```bash
git add schemas/regime_quadrant_snapshot.sql src/db.py tests/test_regime_quadrant_schema.py
git commit -m "feat(quadrant): versioned QuadrantSnapshot schema + indicator audit + lock id"
```

---

### Task 2: `QuadrantSnapshot`/`AxisDiagnostics` dataclasses + `effective_status`

**Files:**
- Create: `src/quadrant_snapshot.py`
- Test: `tests/test_quadrant_snapshot.py`

**Interfaces:**
- Produces: frozen dataclasses `AxisDiagnostics` (fields: `score, sign, internal_sign, candidate_confidence, margin, uncertainty_raw, uncertainty_adjusted` — all `| None`; `internal_sign` is the LATCHED memory persisted as `*_internal_sign`, distinct from the consumable `sign`) and `QuadrantSnapshot` (every field of freeze §3 PLUS `previous_snapshot_id: str | None`, with `snapshot_id: str` holding the uuid as text); module-level `Quadrant`, `ComputeStatus`, `EffectiveStatus` literals; `REGIME_SNAPSHOT_NAMESPACE` (a fixed `uuid.UUID`); `make_snapshot_id(model_version: str, as_of: date, source_vintage_hash: str, previous_snapshot_id: str | None) -> str` (deterministic `uuid5`, owner decision); `effective_status(snapshot: QuadrantSnapshot, now: datetime) -> EffectiveStatus`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quadrant_snapshot.py
from __future__ import annotations

import datetime as dt
import uuid as _uuid

from src.quadrant_snapshot import (
    REGIME_SNAPSHOT_NAMESPACE,
    AxisDiagnostics,
    QuadrantSnapshot,
    effective_status,
    make_snapshot_id,
)


def _axis(sign=1) -> AxisDiagnostics:
    return AxisDiagnostics(
        score=0.3, sign=sign, internal_sign=sign, candidate_confidence=0.9, margin=0.3,
        uncertainty_raw=0.1, uncertainty_adjusted=0.1,
    )


def _valid_snapshot(stale_after: dt.datetime) -> QuadrantSnapshot:
    av = dt.datetime(2024, 3, 5, tzinfo=dt.timezone.utc)
    sid = make_snapshot_id("macro_quadrant_us_v1", dt.date(2024, 3, 4),
                           "abcdef0123456789", None)
    return QuadrantSnapshot(
        snapshot_id=sid, previous_snapshot_id=None,
        quadrant="expansion", candidate_quadrant="expansion",
        candidate_confidence=0.88, growth=_axis(1), inflation=_axis(1),
        coverage_quality=1.0, freshness_quality=1.0, source_health_quality=1.0,
        transition_pending=False, transition_reason=None,
        as_of=dt.date(2024, 3, 4), available_at=av, computed_at=av,
        data_stale_after=stale_after, pipeline_stale_after=stale_after,
        stale_after=stale_after, status_at_compute="valid",
        model_version="macro_quadrant_us_v1",
        confidence_model_version="confidence_v1.0",
        confidence_method="rolling_score_mad_distinct_vintages_v1",
        source_vintage_hash="abcdef0123456789",
    )


def test_snapshot_id_is_deterministic_uuid5() -> None:
    sid = make_snapshot_id("macro_quadrant_us_v1", dt.date(2024, 3, 4),
                           "abcdef0123456789", None)
    # uuid5 over the canonical "|"-joined key with GENESIS for a null predecessor.
    expect = str(_uuid.uuid5(
        REGIME_SNAPSHOT_NAMESPACE,
        "macro_quadrant_us_v1|2024-03-04|abcdef0123456789|GENESIS"))
    assert sid == expect
    # same inputs + same predecessor -> same id (idempotent daily recompute)
    assert sid == make_snapshot_id("macro_quadrant_us_v1", dt.date(2024, 3, 4),
                                   "abcdef0123456789", None)
    # a DIFFERENT predecessor yields a DIFFERENT id (latched chain identity)
    other = make_snapshot_id("macro_quadrant_us_v1", dt.date(2024, 3, 4),
                             "abcdef0123456789", sid)
    assert other != sid


def test_effective_status_valid_before_stale() -> None:
    far = dt.datetime(2024, 4, 1, tzinfo=dt.timezone.utc)
    snap = _valid_snapshot(far)
    now = dt.datetime(2024, 3, 10, tzinfo=dt.timezone.utc)
    assert effective_status(snap, now) == "valid"


def test_effective_status_becomes_stale_after_stale_after() -> None:
    cutoff = dt.datetime(2024, 3, 8, tzinfo=dt.timezone.utc)
    snap = _valid_snapshot(cutoff)
    now = dt.datetime(2024, 3, 8, tzinfo=dt.timezone.utc)  # now >= stale_after
    assert effective_status(snap, now) == "stale"


def test_effective_status_passthrough_when_not_valid() -> None:
    snap = _valid_snapshot(dt.datetime(2024, 4, 1, tzinfo=dt.timezone.utc))
    low = snap.__class__(**{**snap.__dict__, "status_at_compute": "low_confidence",
                            "quadrant": None})
    now = dt.datetime(2024, 5, 1, tzinfo=dt.timezone.utc)  # well past stale_after
    # non-valid statuses are never relabelled to 'stale'
    assert effective_status(low, now) == "low_confidence"


def test_axis_diagnostics_allows_all_none() -> None:
    a = AxisDiagnostics(score=None, sign=None, internal_sign=None,
                        candidate_confidence=None, margin=None,
                        uncertainty_raw=None, uncertainty_adjusted=None)
    assert a.sign is None and a.internal_sign is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_quadrant_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.quadrant_snapshot'`

- [ ] **Step 3: Implement the dataclasses + helpers**

```python
# src/quadrant_snapshot.py
"""QuadrantSnapshot / AxisDiagnostics — the EXACT contract both A2 workers emit.

Both MacroReleaseAxisModel (official) and MarketImpliedAxisModel (challenger)
build instances of QuadrantSnapshot (freeze v1 §3) — they differ ONLY in how the
per-axis scores are sourced, never in the snapshot shape. effective_status is
derived AT READ (the worker never rewrites old snapshots); status_at_compute is
persisted and immutable.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from dataclasses import dataclass
from typing import Literal

Quadrant = Literal["recovery", "expansion", "slowdown", "contraction"]
ComputeStatus = Literal["valid", "low_confidence", "unavailable", "invalid"]
EffectiveStatus = Literal["valid", "low_confidence", "stale", "unavailable", "invalid"]

# Fixed namespace for the deterministic snapshot uuid5 (owner decision). Stable
# forever — changing it would renumber every snapshot id.
REGIME_SNAPSHOT_NAMESPACE = _uuid.uuid5(
    _uuid.NAMESPACE_URL, "investintell/regime_quadrant_snapshot")


@dataclass(frozen=True)
class AxisDiagnostics:
    score: float | None
    sign: Literal[-1, 1] | None          # EFFECTIVE post-hysteresis (consumable) sign; NULL if not consumable
    internal_sign: Literal[-1, 1] | None  # LATCHED memory carried to the next run (persisted *_internal_sign)
    candidate_confidence: float | None
    margin: float | None
    uncertainty_raw: float | None
    uncertainty_adjusted: float | None


@dataclass(frozen=True)
class QuadrantSnapshot:
    snapshot_id: str                     # uuid5 as text (owner decision)
    previous_snapshot_id: str | None     # predecessor in the latched chain; None at genesis
    quadrant: Quadrant | None            # consumable; non-NULL only when status_at_compute=="valid"
    candidate_quadrant: Quadrant | None  # instantaneous classification (audit/UI)
    candidate_confidence: float | None
    growth: AxisDiagnostics
    inflation: AxisDiagnostics
    coverage_quality: float
    freshness_quality: float
    source_health_quality: float
    transition_pending: bool
    transition_reason: str | None
    as_of: _dt.date
    available_at: _dt.datetime
    computed_at: _dt.datetime
    data_stale_after: _dt.datetime
    pipeline_stale_after: _dt.datetime
    stale_after: _dt.datetime
    status_at_compute: ComputeStatus
    model_version: str
    confidence_model_version: str
    confidence_method: str
    source_vintage_hash: str


def make_snapshot_id(
    model_version: str,
    as_of: _dt.date,
    source_vintage_hash: str,
    previous_snapshot_id: str | None,
) -> str:
    """Deterministic ``uuid5`` over the canonical key (owner decision):

        model_version | as_of | source_vintage_hash | previous_snapshot_id|"GENESIS"

    The predecessor is part of the identity because the latched hysteresis result
    depends on it; re-running the same model with the same inputs AND predecessor
    reproduces the same id, so the daily upsert is idempotent. The genesis run
    (no predecessor) hashes the literal "GENESIS". Returned as text for the DB
    (the column is a real ``uuid``; psycopg adapts the text).
    """
    key = "|".join([
        model_version, as_of.isoformat(), source_vintage_hash,
        previous_snapshot_id or "GENESIS",
    ])
    return str(_uuid.uuid5(REGIME_SNAPSHOT_NAMESPACE, key))


def effective_status(snapshot: QuadrantSnapshot, now: _dt.datetime) -> EffectiveStatus:
    """Freeze §3: a valid snapshot becomes 'stale' once now >= stale_after; any
    other status passes through unchanged (never relabelled to stale)."""
    if snapshot.status_at_compute == "valid" and now >= snapshot.stale_after:
        return "stale"
    return snapshot.status_at_compute
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_quadrant_snapshot.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/quadrant_snapshot.py tests/test_quadrant_snapshot.py
git commit -m "feat(quadrant): QuadrantSnapshot/AxisDiagnostics dataclasses + effective_status"
```

---

### Task 3: Per-axis score from inputs (two-stage transform + weighted aggregation)

**Files:**
- Create: `src/quadrant_score.py`
- Test: `tests/test_quadrant_score.py`

**Interfaces:**
- Consumes: `axis_weights` from `src.macro_sources` (Task 0); `economic_transform`, `standardize` from `src.macro_transforms` (Task 0).
- Produces: `standardized_latest(spec: MacroSourceSpec, series: dict[date, float], as_of: date, *, window_years: int = 10) -> float | None` — applies the spec's `economic_transform_id` (with `neutral_level`), keeps the DISTINCT transformed values at periods ≤ `as_of` over the trailing `window_years`, and standardizes the latest one via the spec's `standardizer_id` (robust-z); returns `None` when the latest transformed period is missing OR the robust scale is undefined. `axis_score(weights: dict[str, float], z_by_series: dict[str, float | None]) -> tuple[float | None, dict[str, float]]` returning `(score, contributions)` where `score = Σ w_k·z_k` over non-None z (renormalizing weights over the available subset) and `contributions = {series_id: w_k·z_k}`; `None` score if no series available. There is NO `yoy`/`level` universal transform any more (owner decision A) — the market worker passes already-standardized window returns straight to `axis_score`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quadrant_score.py
from __future__ import annotations

import datetime as dt

from src.macro_sources import SEED_SOURCES
from src.quadrant_score import axis_score, standardized_latest

_INDPRO = next(s for s in SEED_SOURCES if s.series_id == "INDPRO")  # log_3m3m_ann_v1


def _monthly(values: list[float], start=dt.date(2020, 1, 1)) -> dict[dt.date, float]:
    out: dict[dt.date, float] = {}
    y, m = start.year, start.month
    for v in values:
        out[dt.date(y, m, 1)] = v
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def test_standardized_latest_runs_transform_then_robust_z() -> None:
    # A long, rising-then-spiking series: the latest 3m3m impulse is far above the
    # historical median -> a large positive z (clipped at +4).
    base = [100.0 + 0.1 * i for i in range(60)]          # slow drift
    base += [base[-1] * 1.5]                             # a spike in the last month
    series = _monthly(base)
    as_of = max(series)
    z = standardized_latest(_INDPRO, series, as_of)
    assert z is not None and z > 0.0


def test_standardized_latest_none_when_no_period_at_or_before_as_of() -> None:
    series = _monthly([100.0 + i for i in range(30)])
    # as_of before any computable transform period -> None.
    assert standardized_latest(_INDPRO, series, dt.date(2019, 1, 1)) is None


def test_standardized_latest_respects_as_of_cutoff() -> None:
    series = _monthly([100.0 + 0.1 * i for i in range(60)])
    full = max(series)
    cut = dt.date(2021, 6, 1)  # well before the end
    z_full = standardized_latest(_INDPRO, series, full)
    z_cut = standardized_latest(_INDPRO, series, cut)
    assert z_full is not None and z_cut is not None
    # different as_of -> different latest standardized impulse (no look-ahead).
    assert z_full != z_cut


def test_axis_score_weighted_sum_over_available() -> None:
    weights = {"A": 0.5, "B": 0.5}
    score, contrib = axis_score(weights, {"A": 1.0, "B": -1.0})
    assert abs(score - 0.0) < 1e-9
    assert abs(contrib["A"] - 0.5) < 1e-9 and abs(contrib["B"] - (-0.5)) < 1e-9


def test_axis_score_renormalizes_when_one_series_missing() -> None:
    weights = {"A": 0.5, "B": 0.5}
    # B missing -> A carries full weight (renormalized to 1.0)
    score, contrib = axis_score(weights, {"A": 2.0, "B": None})
    assert abs(score - 2.0) < 1e-9
    assert "B" not in contrib


def test_axis_score_none_when_all_missing() -> None:
    score, contrib = axis_score({"A": 1.0}, {"A": None})
    assert score is None and contrib == {}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_quadrant_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.quadrant_score'`

- [ ] **Step 3: Implement transforms + aggregation**

```python
# src/quadrant_score.py
"""Per-axis score: standardize each series (economic transform -> robust-z over
distinct point-in-time vintages), then a weighted sum across an axis's series
(freeze v1 §4 s_a = Σ w_k·z_k).

Owner decision A — TWO stages, NO universal yoy/level: the per-family
economic_transform_id extracts the impulse and the universal standardizer_id
('robust_z_10y_distinct_vintages_v1') makes axes comparable. A series without
enough data for its declared transform standardizes to None (a MISSING input);
coverage (Task 5) penalizes the gap — the score itself is never silently halved
because axis_score renormalizes the weights over the AVAILABLE subset. The
market-implied worker bypasses this module's standardizer (its 126d window return
is already comparable) and feeds axis_score directly.
"""
from __future__ import annotations

import datetime as _dt

from src.macro_sources import MacroSourceSpec
from src.macro_transforms import economic_transform, standardize


def standardized_latest(
    spec: MacroSourceSpec,
    series: dict[_dt.date, float],
    as_of: _dt.date,
    *,
    window_years: int = 10,
) -> float | None:
    """Latest standardized impulse for one macro series at/<= ``as_of``.

    1. economic_transform(spec.economic_transform_id, series, neutral_level=...).
    2. Restrict to transformed periods <= as_of within the trailing window_years.
    3. standardize(spec.standardizer_id, distinct history, latest value).

    Returns None when there is no transformed period <= as_of, or when the robust
    scale is undefined (the caller treats None as a missing input, not a zero).
    """
    transformed = economic_transform(
        spec.economic_transform_id, series, neutral_level=spec.neutral_level)
    cutoff = _dt.date(as_of.year - window_years, as_of.month, 1)
    eligible = [p for p in transformed if cutoff <= p <= as_of]
    if not eligible:
        return None
    latest_period = max(eligible)
    history = [transformed[p] for p in eligible]
    return standardize(spec.standardizer_id, history, transformed[latest_period])


def axis_score(
    weights: dict[str, float], z_by_series: dict[str, float | None]
) -> tuple[float | None, dict[str, float]]:
    """Weighted axis score over the AVAILABLE series.

    Renormalizes the supplied weights over the series with a non-None z, so a
    missing input shifts mass to its peers rather than shrinking the score.
    Returns (score, {series_id: w_k·z_k}); score is None when nothing is available.
    """
    available = {sid: z for sid, z in z_by_series.items()
                 if z is not None and sid in weights}
    total = sum(abs(weights[sid]) for sid in available)
    if total <= 0.0:
        return None, {}
    contributions: dict[str, float] = {}
    score = 0.0
    for sid, z in available.items():
        w = weights[sid] / total
        contrib = w * z
        contributions[sid] = contrib
        score += contrib
    return score, contributions
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_quadrant_score.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/quadrant_score.py tests/test_quadrant_score.py
git commit -m "feat(quadrant): per-axis two-stage standardize + weighted score (renormalized)"
```

---

### Task 4: Per-axis hysteresis state machine (freeze §5)

**Files:**
- Create: `src/quadrant_hysteresis.py`
- Test: `tests/test_quadrant_hysteresis.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces: constants `AXIS_ENTER = 0.25`, `AXIS_EXIT = 0.10`; `axis_hysteresis(prev_sign: int | None, score: float, candidate_confidence: float, *, enter=AXIS_ENTER, exit_=AXIS_EXIT, min_confidence: float) -> tuple[int | None, int | None, bool, str | None]` returning `(internal_sign, effective_sign, transition_pending, reason)` where `internal_sign` is the latched memory (preserved across deadband), `effective_sign` is the consumable sign (NULL when in transition), `transition_pending` is True in deadband/unconfirmed, `reason` names what happened. Implements §5.1 (init) and §5.2 (precedence: opposite-switch BEFORE stability).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quadrant_hysteresis.py
from __future__ import annotations

from src.quadrant_hysteresis import AXIS_ENTER, AXIS_EXIT, axis_hysteresis

MINC = 0.70


def test_constants_frozen() -> None:
    assert AXIS_ENTER == 0.25 and AXIS_EXIT == 0.10


def test_init_confirms_when_strong_and_confident() -> None:
    # §5.1: no prior, |score|>=ENTER and confidence>=min -> initialize the sign.
    internal, effective, pending, reason = axis_hysteresis(
        None, 0.30, 0.90, min_confidence=MINC)
    assert internal == 1 and effective == 1 and pending is False
    assert reason == "init"


def test_init_abstains_when_weak() -> None:
    # |score| < ENTER on init -> no sign, transition pending, no quadrant.
    internal, effective, pending, reason = axis_hysteresis(
        None, 0.20, 0.95, min_confidence=MINC)
    assert internal is None and effective is None and pending is True
    assert reason == "init_below_enter"


def test_init_abstains_when_low_confidence() -> None:
    internal, effective, pending, reason = axis_hysteresis(
        None, 0.40, 0.60, min_confidence=MINC)
    assert effective is None and pending is True and reason == "init_low_confidence"


def test_confirmed_stays_with_aligned_signal_above_exit() -> None:
    # prior +1, signed_margin = +1 * 0.15 = 0.15 >= EXIT -> keep.
    internal, effective, pending, reason = axis_hysteresis(
        1, 0.15, 0.90, min_confidence=MINC)
    assert internal == 1 and effective == 1 and pending is False and reason == "hold"


def test_opposite_switch_takes_precedence_over_stability() -> None:
    # prior +1, score strongly negative: signed_margin = +1 * -0.30 = -0.30 <= -ENTER.
    # Opposite-switch is evaluated BEFORE stability (§5.2 precedence).
    internal, effective, pending, reason = axis_hysteresis(
        1, -0.30, 0.90, min_confidence=MINC)
    assert internal == -1 and effective == -1 and pending is False and reason == "switch"


def test_opposite_strong_but_low_confidence_does_not_switch_consumably() -> None:
    # opposite evidence sufficient but confidence < min -> internal flips memory,
    # effective sign withheld, transition pending.
    internal, effective, pending, reason = axis_hysteresis(
        1, -0.30, 0.55, min_confidence=MINC)
    assert internal == -1 and effective is None and pending is True
    assert reason == "switch_low_confidence"


def test_deadband_keeps_internal_publishes_no_quadrant() -> None:
    # prior +1, signed_margin = +1 * 0.05 = 0.05 in (-ENTER, EXIT): deadband.
    internal, effective, pending, reason = axis_hysteresis(
        1, 0.05, 0.90, min_confidence=MINC)
    assert internal == 1 and effective is None and pending is True and reason == "deadband"


def test_deadband_opposite_small_keeps_old_internal() -> None:
    # prior +1, score -0.05 -> signed_margin -0.05, |.|<ENTER and < EXIT: deadband,
    # memory of +1 preserved (so tomorrow distinguishes 'was up' from 'never set').
    internal, effective, pending, _ = axis_hysteresis(1, -0.05, 0.90, min_confidence=MINC)
    assert internal == 1 and effective is None and pending is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_quadrant_hysteresis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.quadrant_hysteresis'`

- [ ] **Step 3: Implement the per-axis state machine**

```python
# src/quadrant_hysteresis.py
"""Per-axis hysteresis (freeze v1 §5) — the SAME latched-state-machine idea as the
gate's build_rows, but on the axis SIGN instead of risk_on/risk_off.

§5.1 init (no prior): set the sign only if |score| >= AXIS_ENTER AND confidence >=
min; otherwise abstain (transition pending, no quadrant).
§5.2 confirmed (prior sign h): signed_margin = h * score. MANDATORY PRECEDENCE —
evaluate the opposite-switch (signed_margin <= -AXIS_ENTER) BEFORE stability
(signed_margin >= AXIS_EXIT); else deadband. The opposite-switch case keeps the
internal memory flipped even if confidence is too low to publish (so the next day
can tell 'was up, transitioning' from 'never confirmed').

Returns (internal_sign, effective_sign, transition_pending, reason):
  internal_sign  : latched memory, preserved across deadband (persisted as *_sign)
  effective_sign : consumable sign; NULL whenever in transition / low-confidence
  transition_pending : True in init-abstain / deadband / withheld switch
  reason         : audit tag for transition_reason
"""
from __future__ import annotations

AXIS_ENTER = 0.25
AXIS_EXIT = 0.10


def axis_hysteresis(
    prev_sign: int | None,
    score: float,
    candidate_confidence: float,
    *,
    enter: float = AXIS_ENTER,
    exit_: float = AXIS_EXIT,
    min_confidence: float,
) -> tuple[int | None, int | None, bool, str | None]:
    confident = candidate_confidence >= min_confidence

    if prev_sign is None:
        # §5.1 initialization.
        if abs(score) < enter:
            return None, None, True, "init_below_enter"
        if not confident:
            return None, None, True, "init_low_confidence"
        sign = 1 if score > 0 else -1
        return sign, sign, False, "init"

    # §5.2 confirmed state — precedence: opposite-switch BEFORE stability.
    signed_margin = prev_sign * score
    if signed_margin <= -enter:
        new_sign = 1 if score > 0 else -1
        if confident:
            return new_sign, new_sign, False, "switch"
        # opposite evidence sufficient but not confident: flip memory, withhold.
        return new_sign, None, True, "switch_low_confidence"
    if signed_margin >= exit_:
        if confident:
            return prev_sign, prev_sign, False, "hold"
        return prev_sign, None, True, "hold_low_confidence"
    # deadband: keep internal memory, publish no quadrant.
    return prev_sign, None, True, "deadband"
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_quadrant_hysteresis.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/quadrant_hysteresis.py tests/test_quadrant_hysteresis.py
git commit -m "feat(quadrant): per-axis hysteresis (opposite-switch precedes stability, §5)"
```

---

### Task 5: Confidence Φ(s/u*) + the three qualities + status order (freeze §4/§6, owner decision B)

**Files:**
- Create: `src/quadrant_confidence.py`
- Test: `tests/test_quadrant_confidence.py`

**Interfaces:**
- Consumes: nothing (pure; `Φ` from `statistics.NormalDist`).
- Produces: constants `MIN_CANDIDATE_CONFIDENCE = 0.70`, `MIN_INPUT_COVERAGE = 0.80`, `MIN_SOURCE_HEALTH = 0.90`, `UNCERTAINTY_WINDOW_VINTAGES = 36`, `MIN_UNCERTAINTY_VINTAGES = 24`, `Q_DATA_FLOOR = 0.25`, `U_FLOOR_SEED = {"growth": 0.25, "inflation": 0.25}` (owner decision B — frozen in `confidence_v1.0`).
- Produces (uncertainty/confidence): `uncertainty_raw(score_history: list[float], u_floor: float) -> float | None` (`max(1.4826·MAD over distinct vintage values, u_floor)`; None if `< MIN_UNCERTAINTY_VINTAGES` distinct values); `axis_confidence(score, u_raw, q_data) -> tuple[float, float]` returning `(confidence, u_adj)` with `u_adj = max(u_raw, u_floor)/max(q_data, Q_DATA_FLOOR)` already folded by the caller (here `u_adj = u_raw/max(q_data, Q_DATA_FLOOR)` since `u_raw` is already floored), `confidence = Φ(|score|/u_adj)`.
- Produces (the three qualities, owner decision B — full formulas): `coverage_quality(items: list[tuple[float, bool, float]]) -> float` over `(abs_weight, current_value_valid, history_coverage)` triples computing `Σ|w_i|·usable_i / Σ|w_i|` with `usable_i = I(currentValueValid_i)·historyCoverage_i`; `freshness_value(now, soft_deadline, hard_deadline) -> float` (1 if `now ≤ soft`, 0 if `now ≥ hard`, linear `(hard−now)/(hard−soft)` between); `axis_freshness(items: list[tuple[float, float]]) -> float` = `|w|`-weighted mean of per-source `freshness_value`; `source_health(items: list[tuple[float, float]]) -> float` = `Σ|w_i|·health_i/Σ|w_i|` over `(abs_weight, health_i)` where `health_i = passed_weight/total_check_weight`.
- Produces (status): `resolve_status(*, critical_structural_failure: bool, coverage: float, critical_source_expired: bool, source_health: float, candidate_confidence: float, transition_pending: bool) -> ComputeStatus` applying the OWNER'S status order (decision B) verbatim.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quadrant_confidence.py
from __future__ import annotations

import datetime as dt

from src.quadrant_confidence import (
    MIN_UNCERTAINTY_VINTAGES,
    U_FLOOR_SEED,
    axis_confidence,
    axis_freshness,
    coverage_quality,
    freshness_value,
    resolve_status,
    source_health,
    uncertainty_raw,
)

UTC = dt.timezone.utc


def test_owner_constants_frozen() -> None:
    assert MIN_UNCERTAINTY_VINTAGES == 24
    assert U_FLOOR_SEED == {"growth": 0.25, "inflation": 0.25}


def test_uncertainty_raw_none_when_too_few_vintages() -> None:
    distinct = [0.001 * i for i in range(MIN_UNCERTAINTY_VINTAGES - 1)]
    assert uncertainty_raw(distinct, 0.25) is None


def test_uncertainty_raw_uses_mad_over_distinct_values() -> None:
    hist = [0.001 * i for i in range(30)]  # 30 distinct values
    u = uncertainty_raw(hist, 0.001)
    assert u is not None and u > 0.0


def test_uncertainty_raw_respects_floor() -> None:
    hist = [0.10] * 30  # one distinct value -> MAD 0 but ALSO < 24 distinct -> None
    assert uncertainty_raw(hist, 0.25) is None
    flat = [0.10 + 1e-9 * i for i in range(30)]  # ~flat but 30 distinct -> floored
    assert uncertainty_raw(flat, 0.25) == 0.25


def test_axis_confidence_strong_score_high_confidence() -> None:
    conf, u_adj = axis_confidence(0.90, 0.25, 1.0)
    assert conf > 0.99 and abs(u_adj - 0.25) < 1e-12


def test_axis_confidence_zero_score_is_half() -> None:
    conf, _ = axis_confidence(0.0, 0.25, 1.0)
    assert abs(conf - 0.50) < 1e-9


def test_axis_confidence_low_quality_inflates_uncertainty() -> None:
    # q_data below the 0.25 floor is clamped to 0.25 -> u_adj = u_raw / 0.25.
    _, u_adj = axis_confidence(0.30, 0.25, 0.10)
    assert abs(u_adj - 0.25 / 0.25) < 1e-12


def test_coverage_quality_importance_weighted() -> None:
    # (abs_weight, current_value_valid, history_coverage)
    items = [(0.5, True, 1.0), (0.5, False, 1.0)]  # second invalid -> usable 0
    assert abs(coverage_quality(items) - 0.5) < 1e-12
    # a partially-covered valid source counts its history_coverage.
    items2 = [(0.5, True, 1.0), (0.5, True, 0.6)]
    assert abs(coverage_quality(items2) - 0.8) < 1e-12


def test_freshness_value_piecewise() -> None:
    soft = dt.datetime(2024, 3, 10, tzinfo=UTC)
    hard = dt.datetime(2024, 3, 20, tzinfo=UTC)
    assert freshness_value(dt.datetime(2024, 3, 5, tzinfo=UTC), soft, hard) == 1.0
    assert freshness_value(dt.datetime(2024, 3, 25, tzinfo=UTC), soft, hard) == 0.0
    mid = freshness_value(dt.datetime(2024, 3, 15, tzinfo=UTC), soft, hard)
    assert abs(mid - 0.5) < 1e-9


def test_axis_freshness_weighted_mean() -> None:
    # (abs_weight, freshness_value)
    assert abs(axis_freshness([(0.5, 1.0), (0.5, 0.0)]) - 0.5) < 1e-12


def test_source_health_weighted_mean() -> None:
    # (abs_weight, health_i)
    assert abs(source_health([(0.5, 1.0), (0.5, 0.8)]) - 0.9) < 1e-12


def _kw(**over):
    base = dict(critical_structural_failure=False, coverage=1.0,
               critical_source_expired=False, source_health=1.0,
               candidate_confidence=0.85, transition_pending=False)
    base.update(over)
    return base


def test_resolve_status_invalid_first() -> None:
    # critical structural failure dominates even with everything else fine.
    assert resolve_status(**_kw(critical_structural_failure=True)) == "invalid"


def test_resolve_status_unavailable_when_coverage_below_min() -> None:
    assert resolve_status(**_kw(coverage=0.70)) == "unavailable"


def test_resolve_status_stale_when_critical_source_expired() -> None:
    assert resolve_status(**_kw(critical_source_expired=True)) == "stale"


def test_resolve_status_low_confidence_when_health_below_090() -> None:
    assert resolve_status(**_kw(source_health=0.85)) == "low_confidence"


def test_resolve_status_low_confidence_below_confidence_threshold() -> None:
    assert resolve_status(**_kw(candidate_confidence=0.65)) == "low_confidence"


def test_resolve_status_low_confidence_on_transition() -> None:
    assert resolve_status(**_kw(transition_pending=True)) == "low_confidence"


def test_resolve_status_order_invalid_beats_unavailable() -> None:
    # both a structural failure AND low coverage -> invalid wins (first in order).
    assert resolve_status(**_kw(critical_structural_failure=True,
                                coverage=0.10)) == "invalid"


def test_resolve_status_valid_when_all_pass() -> None:
    assert resolve_status(**_kw()) == "valid"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_quadrant_confidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.quadrant_confidence'`

- [ ] **Step 3: Implement confidence + hard gates**

```python
# src/quadrant_confidence.py
"""Confidence (freeze v1 §4/§6, owner decision B) — an OPERATIONAL abstention proxy,
not a calibrated probability. Per axis: u_raw = max(1.4826·MAD(score over DISTINCT
vintages), u_floor) [NOT /sqrt(n), NOT forward-filled]; u_adj = u_raw / max(q_data,
0.25); confidence = Φ(|score| / u_adj), so 0.50 <= confidence <= 1.
candidate_confidence = min over axes.

The three qualities (owner decision B — FULL formulas, not half-implementations):
  coverage:  historyCoverage_i = min(1, nValid_i/minimum_valid_observations_i);
             usable_i = I(currentValueValid_i)·historyCoverage_i;
             coverage_a = Σ|w_i|·usable_i / Σ|w_i|; coverageQuality = min over axes.
  freshness: soft_deadline = next_expected_release + grace_period;
             hard_deadline = min(last_available_at + hard_max_age,
                                 soft_deadline + freshness_decay_window);
             freshness_i = 1 (now<=soft), 0 (now>=hard), linear between; per axis a
             |w|-weighted mean; snapshot = min over axes. A critical source past its
             hard_deadline is a HARD gate (-> stale); the linear decay before that is
             the SOFT penalty folded into q_data.
  source_health: per-source checks (schema, expected unit, finite value, one obs per
             period/vintage, valid release_at/available_at, valid revision lineage,
             transform compatible with unit, structurally-possible range — NEVER
             invalid merely for an extreme economic move); health_i =
             passed_weight/total_check_weight; sourceHealth_a = Σ|w_i|·health_i/Σ|w_i|;
             snapshot = min over axes.

q_data = min(coverageQuality, freshnessQuality, sourceHealthQuality);
u_adj_a = max(u_raw_a, u_floor_a) / max(q_data, 0.25).

STATUS ORDER (owner decision B — verbatim; SEPARATE from confidence):
  critical structural failure  -> invalid
  coverage < 0.80              -> unavailable
  critical source expired      -> stale
  health < 0.90                -> low_confidence
  confidence < 0.70            -> low_confidence
  transition_pending           -> low_confidence
  otherwise                    -> valid

The FORMULAS are frozen now; the THRESHOLDS/FLOORS (U_FLOOR_SEED, MIN_*, window)
belong to the parameter freeze. u_floor seed 0.25 per axis (owner decision B);
future calibration u_floor_a = max(0.25, P10(u_raw_a in training)), frozen in
confidence_model_version, never recomputed with future data.
"""
from __future__ import annotations

from typing import Literal

import statistics

ComputeStatus = Literal["valid", "low_confidence", "unavailable", "invalid"]

MIN_CANDIDATE_CONFIDENCE = 0.70
MIN_INPUT_COVERAGE = 0.80
MIN_SOURCE_HEALTH = 0.90
UNCERTAINTY_WINDOW_VINTAGES = 36
MIN_UNCERTAINTY_VINTAGES = 24
Q_DATA_FLOOR = 0.25
U_FLOOR_SEED = {"growth": 0.25, "inflation": 0.25}

_NORM = statistics.NormalDist()
_MAD_SCALE = 1.4826


def uncertainty_raw(score_history: list[float], u_floor: float) -> float | None:
    """1.4826·MAD over the DISTINCT score values in the window, floored at u_floor.

    Returns None when fewer than MIN_UNCERTAINTY_VINTAGES (24) *distinct* values are
    available (§6 -> caller treats as unavailable, confidence NULL). MAD, not stdev,
    for robustness; over distinct vintages, not forward-filled rows.
    """
    distinct = sorted(set(score_history))
    if len(distinct) < MIN_UNCERTAINTY_VINTAGES:
        return None
    median = statistics.median(distinct)
    mad = statistics.median([abs(v - median) for v in distinct])
    return max(_MAD_SCALE * mad, u_floor)


def axis_confidence(score: float, u_raw: float, q_data: float) -> tuple[float, float]:
    """(confidence, u_adj) for one axis. confidence = Φ(|score| / u_adj).

    ``u_raw`` is already floored by uncertainty_raw; u_adj divides by the clamped
    q_data so the worst data quality inflates uncertainty at most 4x.
    """
    u_adj = u_raw / max(q_data, Q_DATA_FLOOR)
    if u_adj <= 0.0:
        return 1.0, u_adj
    confidence = _NORM.cdf(abs(score) / u_adj)
    return confidence, u_adj


def coverage_quality(items: list[tuple[float, bool, float]]) -> float:
    """Σ|w_i|·usable_i / Σ|w_i| over (abs_weight, current_value_valid, history_cov).

    usable_i = I(current_value_valid_i)·history_coverage_i. Empty -> 0.0.
    """
    total = sum(abs(w) for w, _, _ in items)
    if total <= 0.0:
        return 0.0
    num = sum(abs(w) * (cov if valid else 0.0) for w, valid, cov in items)
    return num / total


def freshness_value(now, soft_deadline, hard_deadline) -> float:
    """1 if now<=soft, 0 if now>=hard, linear (hard-now)/(hard-soft) between."""
    if now <= soft_deadline:
        return 1.0
    if now >= hard_deadline:
        return 0.0
    span = (hard_deadline - soft_deadline).total_seconds()
    if span <= 0:
        return 0.0
    return (hard_deadline - now).total_seconds() / span


def axis_freshness(items: list[tuple[float, float]]) -> float:
    """|w|-weighted mean of per-source freshness_value over (abs_weight, fresh_i)."""
    total = sum(abs(w) for w, _ in items)
    if total <= 0.0:
        return 0.0
    return sum(abs(w) * f for w, f in items) / total


def source_health(items: list[tuple[float, float]]) -> float:
    """Σ|w_i|·health_i / Σ|w_i| over (abs_weight, health_i)."""
    total = sum(abs(w) for w, _ in items)
    if total <= 0.0:
        return 0.0
    return sum(abs(w) * h for w, h in items) / total


def resolve_status(
    *,
    critical_structural_failure: bool,
    coverage: float,
    critical_source_expired: bool,
    source_health: float,
    candidate_confidence: float,
    transition_pending: bool,
) -> ComputeStatus:
    """Owner decision B — apply the status order verbatim and return compute status.

    ``critical_source_expired`` is the HARD freshness gate (a critical source past
    its hard_deadline). The persisted column never stores 'stale'; the worker
    (Task 7) maps this compute-time 'stale' to 'low_confidence' before INSERT, and
    the read-side effective_status is the authoritative stale path.
    """
    if critical_structural_failure:
        return "invalid"
    if coverage < MIN_INPUT_COVERAGE:
        return "unavailable"
    if critical_source_expired:
        return "stale"  # type: ignore[return-value]  # compute-time; reader derives the read-side stale
    if source_health < MIN_SOURCE_HEALTH:
        return "low_confidence"
    if candidate_confidence < MIN_CANDIDATE_CONFIDENCE:
        return "low_confidence"
    if transition_pending:
        return "low_confidence"
    return "valid"
```

> NOTE for the implementer: `resolve_status` may return `"stale"` at compute time (a critical source already past its `hard_deadline`). The PERSISTED `status_at_compute` column only allows `valid|low_confidence|unavailable|invalid` (Task 1 CHECK). The worker (Task 7) maps a compute-time `"stale"` to `"low_confidence"` before persisting (the read-side `effective_status` / the `regime_quadrant_current_v` view are the authoritative stale paths); this is asserted in Task 7's tests. Keep `resolve_status` returning the literal so the staleness branch is unit-testable here.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_quadrant_confidence.py -v`
Expected: PASS (18 passed)

- [ ] **Step 5: Commit**

```bash
git add src/quadrant_confidence.py tests/test_quadrant_confidence.py
git commit -m "feat(quadrant): confidence Phi(s/u*) + three qualities + owner status order"
```

---

### Task 6: `stale_after` + `available_at` + business-day helpers (freeze §8/§9)

**Files:**
- Create: `src/quadrant_staleness.py`
- Test: `tests/test_quadrant_staleness.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces: `add_business_days(start: datetime, n: int) -> datetime` (Mon–Fri count, no holiday calendar — v1 seed); `available_at_snapshot(computed_at: datetime, input_available_ats: list[datetime]) -> datetime` (`max(computed_at, max inputs)`, §8); `source_deadlines(last_available_at: datetime, next_expected_release: datetime, grace: timedelta, hard_max_age: timedelta, freshness_decay_window: timedelta) -> tuple[datetime, datetime]` returning `(soft_deadline, hard_deadline)` with `soft = next_expected_release + grace` and `hard = min(last_available_at + hard_max_age, soft + freshness_decay_window)` (owner decision D — the freshness soft/hard split feeding `freshness_value`); `source_expiry(...) -> datetime` retained as `= hard_deadline` (the §9 expiry that binds `data_stale_after`); `compute_stale_after(computed_at: datetime, critical_expiries: list[datetime]) -> tuple[datetime, datetime, datetime]` returning `(data_stale_after, pipeline_stale_after, stale_after)` with `pipeline_stale_after = computed_at + 2 business days`, `data_stale_after = min(critical_expiries)`, `stale_after = min(both)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quadrant_staleness.py
from __future__ import annotations

import datetime as dt

from src.quadrant_staleness import (
    add_business_days,
    available_at_snapshot,
    compute_stale_after,
    source_deadlines,
    source_expiry,
)

UTC = dt.timezone.utc


def test_add_business_days_skips_weekend() -> None:
    fri = dt.datetime(2024, 3, 1, 12, 0, tzinfo=UTC)  # Friday
    assert add_business_days(fri, 1) == dt.datetime(2024, 3, 4, 12, 0, tzinfo=UTC)  # Mon
    assert add_business_days(fri, 2) == dt.datetime(2024, 3, 5, 12, 0, tzinfo=UTC)  # Tue


def test_available_at_is_max_of_computed_and_inputs() -> None:
    computed = dt.datetime(2024, 3, 5, tzinfo=UTC)
    inputs = [dt.datetime(2024, 3, 4, tzinfo=UTC), dt.datetime(2024, 3, 6, tzinfo=UTC)]
    assert available_at_snapshot(computed, inputs) == dt.datetime(2024, 3, 6, tzinfo=UTC)


def test_available_at_falls_back_to_computed_when_no_inputs() -> None:
    computed = dt.datetime(2024, 3, 5, tzinfo=UTC)
    assert available_at_snapshot(computed, []) == computed


def test_source_deadlines_soft_and_hard() -> None:
    av = dt.datetime(2024, 3, 1, tzinfo=UTC)
    nxt = dt.datetime(2024, 3, 20, tzinfo=UTC)
    # soft = release + grace(7d) = Mar 27.
    # hard = min(available+hard_max(45d)=Apr 15, soft+decay(14d)=Apr 10) = Apr 10.
    soft, hard = source_deadlines(av, nxt, dt.timedelta(days=7),
                                  dt.timedelta(days=45), dt.timedelta(days=14))
    assert soft == dt.datetime(2024, 3, 27, tzinfo=UTC)
    assert hard == dt.datetime(2024, 4, 10, tzinfo=UTC)


def test_source_expiry_equals_hard_deadline() -> None:
    av = dt.datetime(2024, 3, 1, tzinfo=UTC)
    nxt = dt.datetime(2024, 3, 20, tzinfo=UTC)
    # source_expiry == hard_deadline of source_deadlines (binds data_stale_after).
    e = source_expiry(av, nxt, dt.timedelta(days=7), dt.timedelta(days=45),
                      dt.timedelta(days=14))
    _, hard = source_deadlines(av, nxt, dt.timedelta(days=7),
                               dt.timedelta(days=45), dt.timedelta(days=14))
    assert e == hard == dt.datetime(2024, 4, 10, tzinfo=UTC)


def test_compute_stale_after_is_min_of_data_and_pipeline() -> None:
    computed = dt.datetime(2024, 3, 1, 9, 0, tzinfo=UTC)  # Friday
    data_exp = dt.datetime(2024, 3, 20, tzinfo=UTC)       # far
    data, pipeline, stale = compute_stale_after(computed, [data_exp])
    # pipeline = computed + 2 business days = Tue Mar 5
    assert pipeline == dt.datetime(2024, 3, 5, 9, 0, tzinfo=UTC)
    assert data == data_exp
    assert stale == pipeline  # pipeline is the binding (earlier) one here
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_quadrant_staleness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.quadrant_staleness'`

- [ ] **Step 3: Implement the staleness math**

```python
# src/quadrant_staleness.py
"""available_at (§8) and stale_after (§9) + the freshness soft/hard split (owner
decision D).

available_at_snapshot = max(computed_at, max_j available_at_j) over required inputs.
Per critical source j (owner decision D):
  soft_deadline_j = next_expected_release_j + grace_j
  hard_deadline_j = min(last_available_at_j + hard_max_age_j,
                        soft_deadline_j + freshness_decay_window_j)
freshness_value (Task 5) is 1 before soft, decays linearly to 0 between soft and
hard, and is a HARD gate (-> stale) at/after hard. source_expiry_j == hard_deadline_j
binds data_stale_after = min over critical expiries.
pipeline_stale_after = computed_at + 2 business days. stale_after = min(both); the
two components are persisted SEPARATELY.

Business days = Mon-Fri count, NO holiday calendar in v1 (a documented A3
calibration point — exchange holidays would tighten the market model's 3-bd
hard_max_age; for the macro monthly basket the 45-calendar-day hard_max dominates).
"""
from __future__ import annotations

import datetime as _dt


def add_business_days(start: _dt.datetime, n: int) -> _dt.datetime:
    """``start`` plus ``n`` business days (Mon-Fri), preserving time-of-day."""
    current = start
    added = 0
    while added < n:
        current = current + _dt.timedelta(days=1)
        if current.weekday() < 5:  # 0=Mon .. 4=Fri
            added += 1
    return current


def available_at_snapshot(
    computed_at: _dt.datetime, input_available_ats: list[_dt.datetime]
) -> _dt.datetime:
    """§8: max(computed_at, max_j available_at_j). Falls back to computed_at."""
    if not input_available_ats:
        return computed_at
    return max([computed_at, *input_available_ats])


def source_deadlines(
    last_available_at: _dt.datetime,
    next_expected_release: _dt.datetime,
    grace: _dt.timedelta,
    hard_max_age: _dt.timedelta,
    freshness_decay_window: _dt.timedelta,
) -> tuple[_dt.datetime, _dt.datetime]:
    """Owner decision D — (soft_deadline, hard_deadline) for one source.

    soft = next_expected_release + grace.
    hard = min(last_available_at + hard_max_age, soft + freshness_decay_window).
    These feed freshness_value (Task 5) and bind data_stale_after (hard).
    """
    soft = next_expected_release + grace
    hard = min(last_available_at + hard_max_age, soft + freshness_decay_window)
    return soft, hard


def source_expiry(
    last_available_at: _dt.datetime,
    next_expected_release: _dt.datetime,
    grace: _dt.timedelta,
    hard_max_age: _dt.timedelta,
    freshness_decay_window: _dt.timedelta,
) -> _dt.datetime:
    """§9 expiry == the hard_deadline (owner decision D)."""
    _, hard = source_deadlines(
        last_available_at, next_expected_release, grace, hard_max_age,
        freshness_decay_window)
    return hard


def compute_stale_after(
    computed_at: _dt.datetime, critical_expiries: list[_dt.datetime]
) -> tuple[_dt.datetime, _dt.datetime, _dt.datetime]:
    """§9: (data_stale_after, pipeline_stale_after, stale_after).

    Requires at least one critical expiry. pipeline = computed_at + 2 business days.
    """
    if not critical_expiries:
        raise ValueError("at least one critical source expiry is required")
    data_stale_after = min(critical_expiries)
    pipeline_stale_after = add_business_days(computed_at, 2)
    stale_after = min(data_stale_after, pipeline_stale_after)
    return data_stale_after, pipeline_stale_after, stale_after
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_quadrant_staleness.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/quadrant_staleness.py tests/test_quadrant_staleness.py
git commit -m "feat(quadrant): available_at + stale_after + freshness soft/hard deadlines"
```

---

### Task 7: The two `*AxisModel` workers emitting the same snapshot + `run`

**Files:**
- Create: `src/workers/quadrant_macro.py` (MacroReleaseAxisModel + run)
- Create: `src/workers/quadrant_market.py` (MarketImpliedAxisModel + run)
- Create: `schemas/regime_quadrant_snapshot.sql` is reused (Task 1); no new schema.
- Modify: `src/run_worker.py` (add `quadrant_macro|quadrant_market` to the valid-worker message)
- Test: `tests/test_quadrant_macro.py`, `tests/test_quadrant_market.py`

**Interfaces:**
- Consumes: `make_snapshot_id`, `QuadrantSnapshot`, `AxisDiagnostics`, `effective_status` (Task 2); `axis_score`, `standardized_latest` (Task 3); `axis_hysteresis`, `AXIS_ENTER`, `AXIS_EXIT` (Task 4); `uncertainty_raw`, `axis_confidence`, `resolve_status`, `coverage_quality`, `axis_freshness`, `source_health`, `freshness_value`, `MIN_CANDIDATE_CONFIDENCE`, `MIN_INPUT_COVERAGE`, `MIN_SOURCE_HEALTH`, `Q_DATA_FLOOR`, `U_FLOOR_SEED` (Task 5); `available_at_snapshot`, `source_deadlines`, `source_expiry`, `compute_stale_after`, `add_business_days`, `freshness_value` (Task 6); `economic_transform`/`standardize` indirectly via Task 3; `latest_vintage_as_of` (A1 `src.macro_pit`); `SEED_SOURCES`, `axis_weights`, `SOURCE_SPEC_VERSION`, `MacroSourceSpec` (evolved, Task 0); `db.connect`, `db.advisory_lock`, `db.LOCK_REGIME_QUADRANT`; the gate worker's `_align`/`_fetch_prices` are NOT reused (no import of `regime_gate`).
- Produces (BOTH modules expose the identical contract):
  - `load_previous_snapshot(conn, model_version) -> dict | None` (the latched-chain read: latest row by `as_of`/`available_at`, returning `{previous_snapshot_id, growth_internal_sign, inflation_internal_sign}`);
  - `classify_axis(prev_sign, score, score_history, *, u_floor, coverage, freshness, source_health) -> tuple[AxisDiagnostics, bool, str | None, float]` (diagnostics carry BOTH effective `sign` and latched `internal_sign`);
  - `build_snapshot(..., previous_snapshot_id, growth_prev_sign, inflation_prev_sign, growth_u_floor, inflation_u_floor) -> QuadrantSnapshot` (the SHARED assembler — see note);
  - `ensure_schema(conn) -> None`; `quadrant_from_signs(growth_sign, inflation_sign) -> Quadrant | None`;
  - `snapshot_to_record(snapshot) -> tuple` and `audit_records(snapshot_id, contributions) -> list[tuple]`;
  - `upsert_snapshot(conn, record, audit_rows) -> None`;
  - `run(dsn, *, calc_date: str | None = None, limit: int | None = None) -> dict`.

> **SHARED ASSEMBLER:** to keep the two workers emitting EXACTLY the same snapshot, put `build_snapshot`, `quadrant_from_signs`, `classify_axis`, `load_previous_snapshot`, `snapshot_to_record`, `audit_records`, `upsert_snapshot`, and `ensure_schema` in a new shared module `src/quadrant_assemble.py`, and have both workers import them. The workers differ ONLY in: `MODEL_VERSION`, `CONFIDENCE_METHOD`, the SOURCE of `(growth_score, growth_history, growth_inputs)` / inflation, and the staleness inputs (macro: per-`MacroSourceSpec`; market: 3-bd hard_max). The LATCHED CHAIN (owner decision C) is shared: each `run` calls `load_previous_snapshot` to obtain the predecessor id and per-axis latched sign, threads them into `build_snapshot`, and the resulting `previous_snapshot_id` enters `make_snapshot_id`. This task creates `src/quadrant_assemble.py` first (Step 3a), then the two thin workers (Steps 3b/3c).

- [ ] **Step 1: Write the failing tests for the shared assembler + macro worker**

```python
# tests/test_quadrant_macro.py
from __future__ import annotations

import datetime as dt

from src import quadrant_assemble as qa
from src.workers import quadrant_macro as qm


def test_quadrant_from_signs_maps_four_quadrants() -> None:
    assert qa.quadrant_from_signs(1, -1) == "recovery"
    assert qa.quadrant_from_signs(1, 1) == "expansion"
    assert qa.quadrant_from_signs(-1, 1) == "slowdown"
    assert qa.quadrant_from_signs(-1, -1) == "contraction"
    assert qa.quadrant_from_signs(None, 1) is None
    assert qa.quadrant_from_signs(1, None) is None


def _kw(**over):
    """Shared build_snapshot kwargs for a strong, full-quality, valid expansion."""
    av = dt.datetime(2024, 3, 5, tzinfo=dt.timezone.utc)
    hist = [0.05 + 0.01 * i for i in range(30)]  # 30 distinct >= MIN_UNCERTAINTY_VINTAGES (24)
    base = dict(
        as_of=dt.date(2024, 3, 1), computed_at=av, previous_snapshot_id=None,
        growth_score=0.30, growth_history=hist, growth_prev_sign=1,
        growth_coverage=1.0, growth_freshness=1.0, growth_health=1.0,
        growth_contributions={"INDPRO": 0.30}, growth_u_floor=0.01,
        inflation_score=0.30, inflation_history=hist, inflation_prev_sign=1,
        inflation_coverage=1.0, inflation_freshness=1.0, inflation_health=1.0,
        inflation_contributions={"CPILFESL": 0.30}, inflation_u_floor=0.01,
        input_available_ats=[av],
        critical_expiries=[dt.datetime(2024, 4, 15, tzinfo=dt.timezone.utc)],
        model_version="macro_quadrant_us_v1",
        confidence_method="rolling_score_mad_distinct_vintages_v1",
        source_vintage_hash="deadbeefcafe1234",
    )
    base.update(over)
    return base


def test_build_snapshot_valid_when_both_axes_confirmed_and_confident() -> None:
    snap = qa.build_snapshot(**_kw())
    assert snap.status_at_compute == "valid"
    assert snap.quadrant == "expansion"
    assert snap.candidate_quadrant == "expansion"
    assert snap.candidate_confidence is not None and snap.candidate_confidence >= 0.70
    assert snap.previous_snapshot_id is None  # genesis
    # snapshot_id is the deterministic uuid5 over the canonical key + GENESIS.
    import uuid as _uuid

    from src.quadrant_snapshot import REGIME_SNAPSHOT_NAMESPACE
    assert snap.snapshot_id == str(_uuid.uuid5(
        REGIME_SNAPSHOT_NAMESPACE,
        "macro_quadrant_us_v1|2024-03-01|deadbeefcafe1234|GENESIS"))
    # latched memory is persisted even though it equals the effective sign here.
    assert snap.growth.internal_sign == 1 and snap.inflation.internal_sign == 1


def test_build_snapshot_unavailable_when_coverage_low_carries_null_quadrant() -> None:
    snap = qa.build_snapshot(**_kw(growth_coverage=0.50))  # below 0.80
    assert snap.status_at_compute == "unavailable"
    assert snap.quadrant is None
    assert snap.candidate_confidence is None  # §7: unavailable carries no confidence


def test_build_snapshot_low_confidence_on_axis_transition() -> None:
    # growth deadband (prev +1, tiny score) -> transition pending -> low_confidence.
    snap = qa.build_snapshot(**_kw(growth_score=0.05,
                                   growth_contributions={"INDPRO": 0.05}))
    assert snap.status_at_compute == "low_confidence"
    assert snap.quadrant is None
    assert snap.transition_pending is True
    # latched memory of the prior +1 is preserved across the deadband.
    assert snap.growth.internal_sign == 1 and snap.growth.sign is None


def test_build_snapshot_threads_previous_id_into_uuid() -> None:
    import uuid as _uuid

    from src.quadrant_snapshot import REGIME_SNAPSHOT_NAMESPACE
    prev = str(_uuid.uuid5(REGIME_SNAPSHOT_NAMESPACE, "seed"))
    snap = qa.build_snapshot(**_kw(previous_snapshot_id=prev))
    assert snap.previous_snapshot_id == prev
    assert snap.snapshot_id == str(_uuid.uuid5(
        REGIME_SNAPSHOT_NAMESPACE,
        f"macro_quadrant_us_v1|2024-03-01|deadbeefcafe1234|{prev}"))


def test_snapshot_to_record_and_audit_shapes() -> None:
    snap = qa.build_snapshot(**_kw())
    rec = qa.snapshot_to_record(snap)
    assert rec[0] == snap.snapshot_id  # first column is snapshot_id
    assert rec[1] == snap.previous_snapshot_id  # second column is previous_snapshot_id
    audit = qa.audit_records(snap.snapshot_id, {"growth": {"INDPRO": 0.30},
                                                "inflation": {"CPILFESL": 0.30}})
    assert {a[1] for a in audit} == {"growth", "inflation"}  # axis column
    assert all(a[0] == snap.snapshot_id for a in audit)


def test_macro_worker_exposes_versions() -> None:
    assert qm.MODEL_VERSION == "macro_quadrant_us_v1"
    assert qm.CONFIDENCE_METHOD == "rolling_score_mad_distinct_vintages_v1"


def test_macro_run_returns_lock_busy_sentinel(monkeypatch) -> None:
    import contextlib

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def commit(self): pass

    @contextlib.contextmanager
    def _busy(conn, lock_id):
        yield False

    monkeypatch.setattr(qm, "connect", lambda dsn: _Conn())
    monkeypatch.setattr(qm, "advisory_lock", _busy)
    monkeypatch.setattr(qa, "ensure_schema", lambda conn: None)
    out = qm.run("postgresql://unused")
    assert out["skipped"] == "lock_busy"


def test_load_previous_snapshot_reads_latest_row() -> None:
    class _Cur:
        def __init__(self, row): self._row = row
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params): self.sql, self.params = sql, params
        def fetchone(self): return self._row

    class _Conn:
        def __init__(self, row): self._row = row
        def cursor(self): return _Cur(self._row)

    # latest row -> {previous_snapshot_id, growth_internal_sign, inflation_internal_sign}
    out = qa.load_previous_snapshot(_Conn(("uuid-abc", 1, -1)), "macro_quadrant_us_v1")
    assert out == {"previous_snapshot_id": "uuid-abc",
                   "growth_internal_sign": 1, "inflation_internal_sign": -1}
    # genesis (no prior row) -> None
    assert qa.load_previous_snapshot(_Conn(None), "macro_quadrant_us_v1") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_quadrant_macro.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.quadrant_assemble'`

- [ ] **Step 3a: Implement the shared assembler `src/quadrant_assemble.py`**

```python
# src/quadrant_assemble.py
"""Shared assembler — turns per-axis (score, history, quality, prev_sign) into the
ONE QuadrantSnapshot both A2 workers emit, then into DB rows. The macro and market
workers call build_snapshot with different SOURCES; the snapshot shape, hysteresis,
confidence, hard gates, and persistence are identical here (freeze v1 §3-§10).
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any

from src.db import LOCK_REGIME_QUADRANT  # noqa: F401  (re-export convenience)
from src.quadrant_confidence import (
    MIN_CANDIDATE_CONFIDENCE,
    axis_confidence,
    resolve_status,
    uncertainty_raw,
)
from src.quadrant_hysteresis import axis_hysteresis
from src.quadrant_snapshot import (
    AxisDiagnostics,
    QuadrantSnapshot,
    make_snapshot_id,
)
from src.quadrant_staleness import available_at_snapshot, compute_stale_after

_SCHEMA = "schemas/regime_quadrant_snapshot.sql"

# Latched-chain read (owner decision C): the newest row per model_version supplies
# the predecessor id + the per-axis latched sign the hysteresis resumes from.
_PREV_SQL = (
    "SELECT snapshot_id, growth_internal_sign, inflation_internal_sign "
    "FROM regime_quadrant_snapshot WHERE model_version = %s "
    "ORDER BY as_of DESC, available_at DESC LIMIT 1"
)


def load_previous_snapshot(conn, model_version: str) -> dict | None:
    """Return {previous_snapshot_id, growth_internal_sign, inflation_internal_sign}
    for the latest snapshot of ``model_version``, or None at genesis."""
    with conn.cursor() as cur:
        cur.execute(_PREV_SQL, (model_version,))
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "previous_snapshot_id": str(row[0]),
        "growth_internal_sign": row[1],
        "inflation_internal_sign": row[2],
    }

_QUADRANT_BY_SIGNS = {
    (1, -1): "recovery",
    (1, 1): "expansion",
    (-1, 1): "slowdown",
    (-1, -1): "contraction",
}


def quadrant_from_signs(growth_sign, inflation_sign):
    """Map effective axis signs to a quadrant; None if either sign is None."""
    if growth_sign is None or inflation_sign is None:
        return None
    return _QUADRANT_BY_SIGNS[(growth_sign, inflation_sign)]


def classify_axis(
    *,
    score: float | None,
    history: list[float],
    prev_sign: int | None,
    coverage: float,
    freshness: float,
    source_health: float,
    u_floor: float,
) -> tuple[AxisDiagnostics, bool, str | None, float]:
    """Run uncertainty -> confidence -> hysteresis for one axis.

    Returns (diagnostics, transition_pending, reason, q_data). When the score or
    uncertainty cannot be computed, returns a fully-NULL diagnostics with
    transition_pending=True (the axis is not consumable).
    """
    q_data = min(coverage, freshness, source_health)
    if score is None:
        # no score at all: carry the prior latched memory forward unchanged.
        return (AxisDiagnostics(None, None, prev_sign, None, None, None, None),
                True, "no_score", q_data)
    u_raw = uncertainty_raw(history, u_floor)
    if u_raw is None:
        return (AxisDiagnostics(score, None, prev_sign, None, None, None, None),
                True, "insufficient_vintages", q_data)
    confidence, u_adj = axis_confidence(score, u_raw, q_data)
    internal_sign, effective_sign, pending, reason = axis_hysteresis(
        prev_sign, score, confidence, min_confidence=MIN_CANDIDATE_CONFIDENCE,
    )
    margin = (prev_sign * score) if prev_sign is not None else abs(score)
    diag = AxisDiagnostics(
        score=score, sign=effective_sign, internal_sign=internal_sign,
        candidate_confidence=confidence,
        margin=margin, uncertainty_raw=u_raw, uncertainty_adjusted=u_adj,
    )
    return diag, pending, reason, q_data


def build_snapshot(
    *,
    as_of: _dt.date,
    computed_at: _dt.datetime,
    previous_snapshot_id: str | None,
    growth_score: float | None,
    growth_history: list[float],
    growth_prev_sign: int | None,
    growth_coverage: float,
    growth_freshness: float,
    growth_health: float,
    growth_contributions: dict[str, float],
    growth_u_floor: float,
    inflation_score: float | None,
    inflation_history: list[float],
    inflation_prev_sign: int | None,
    inflation_coverage: float,
    inflation_freshness: float,
    inflation_health: float,
    inflation_contributions: dict[str, float],
    inflation_u_floor: float,
    input_available_ats: list[_dt.datetime],
    critical_expiries: list[_dt.datetime],
    model_version: str,
    confidence_method: str,
    source_vintage_hash: str,
    critical_structural_failure: bool = False,
    confidence_model_version: str = "confidence_v1.0",
) -> QuadrantSnapshot:
    """Assemble the QuadrantSnapshot from per-axis inputs (freeze §3-§10, owner
    decisions B/C). previous_snapshot_id closes the latched chain and enters the
    deterministic uuid5; per-axis u_floor is the seed from U_FLOOR_SEED."""
    g_diag, g_pending, g_reason, g_q = classify_axis(
        score=growth_score, history=growth_history, prev_sign=growth_prev_sign,
        coverage=growth_coverage, freshness=growth_freshness,
        source_health=growth_health, u_floor=growth_u_floor)
    i_diag, i_pending, i_reason, i_q = classify_axis(
        score=inflation_score, history=inflation_history, prev_sign=inflation_prev_sign,
        coverage=inflation_coverage, freshness=inflation_freshness,
        source_health=inflation_health, u_floor=inflation_u_floor)

    transition_pending = g_pending or i_pending
    reason_bits = [r for r in (g_reason, i_reason)
                   if r not in (None, "init", "hold")]
    transition_reason = ",".join(reason_bits) if reason_bits else None

    # candidate classification follows the candidate sign of the score (NOT the
    # effective post-hysteresis sign), so the UI/audit always has a quadrant guess.
    g_cand = _candidate_sign(growth_score)
    i_cand = _candidate_sign(inflation_score)
    candidate_quadrant = quadrant_from_signs(g_cand, i_cand)

    # consumable quadrant uses the EFFECTIVE (post-hysteresis) signs.
    consumable_quadrant = quadrant_from_signs(g_diag.sign, i_diag.sign)

    coverage_quality = min(growth_coverage, inflation_coverage)
    freshness_quality = min(growth_freshness, inflation_freshness)
    source_health_quality = min(growth_health, inflation_health)
    # a critical source past its hard_deadline expired BEFORE the snapshot computed.
    critical_source_expired = freshness_quality <= 0.0

    confidences = [c for c in (g_diag.candidate_confidence,
                               i_diag.candidate_confidence) if c is not None]
    candidate_confidence = min(confidences) if confidences else None

    available_at = available_at_snapshot(computed_at, input_available_ats)
    data_stale_after, pipeline_stale_after, stale_after = compute_stale_after(
        computed_at, critical_expiries)

    status = resolve_status(
        critical_structural_failure=critical_structural_failure,
        coverage=coverage_quality,
        critical_source_expired=critical_source_expired,
        source_health=source_health_quality,
        candidate_confidence=candidate_confidence if candidate_confidence is not None else 0.0,
        transition_pending=transition_pending,
    )
    # The persisted column never stores 'stale' (read-side / view derive it); a
    # compute-time stale degrades to low_confidence.
    if status == "stale":
        status = "low_confidence"

    # §7 coherence: only 'valid' keeps a non-NULL consumable quadrant + confidence.
    if status == "valid":
        quadrant = consumable_quadrant
        if quadrant is None:
            # both signs must be effective for valid; otherwise demote.
            status = "low_confidence"
    else:
        quadrant = None
    if status in ("unavailable", "invalid"):
        candidate_confidence = None

    snapshot_id = make_snapshot_id(
        model_version, as_of, source_vintage_hash, previous_snapshot_id)
    return QuadrantSnapshot(
        snapshot_id=snapshot_id,
        previous_snapshot_id=previous_snapshot_id,
        quadrant=quadrant,
        candidate_quadrant=candidate_quadrant,
        candidate_confidence=candidate_confidence,
        growth=g_diag, inflation=i_diag,
        coverage_quality=coverage_quality,
        freshness_quality=freshness_quality,
        source_health_quality=source_health_quality,
        transition_pending=transition_pending,
        transition_reason=transition_reason,
        as_of=as_of, available_at=available_at, computed_at=computed_at,
        data_stale_after=data_stale_after,
        pipeline_stale_after=pipeline_stale_after,
        stale_after=stale_after,
        status_at_compute=status,
        model_version=model_version,
        confidence_model_version=confidence_model_version,
        confidence_method=confidence_method,
        source_vintage_hash=source_vintage_hash,
    )


def _candidate_sign(score: float | None) -> int | None:
    if score is None:
        return None
    return 1 if score > 0 else -1


_RECORD_COLS = (
    "snapshot_id", "previous_snapshot_id",
    "quadrant", "candidate_quadrant", "candidate_confidence",
    "growth_score", "growth_sign", "growth_internal_sign",
    "growth_candidate_confidence", "growth_margin",
    "growth_uncertainty_raw", "growth_uncertainty_adjusted",
    "inflation_score", "inflation_sign", "inflation_internal_sign",
    "inflation_candidate_confidence",
    "inflation_margin", "inflation_uncertainty_raw", "inflation_uncertainty_adjusted",
    "coverage_quality", "freshness_quality", "source_health_quality",
    "transition_pending", "transition_reason",
    "as_of", "available_at", "computed_at",
    "data_stale_after", "pipeline_stale_after", "stale_after",
    "status_at_compute", "model_version", "confidence_model_version",
    "confidence_method", "source_vintage_hash",
)


def snapshot_to_record(s: QuadrantSnapshot) -> tuple:
    """Snapshot -> DB tuple in _RECORD_COLS order."""
    return (
        s.snapshot_id, s.previous_snapshot_id,
        s.quadrant, s.candidate_quadrant, s.candidate_confidence,
        s.growth.score, s.growth.sign, s.growth.internal_sign,
        s.growth.candidate_confidence, s.growth.margin,
        s.growth.uncertainty_raw, s.growth.uncertainty_adjusted,
        s.inflation.score, s.inflation.sign, s.inflation.internal_sign,
        s.inflation.candidate_confidence,
        s.inflation.margin, s.inflation.uncertainty_raw, s.inflation.uncertainty_adjusted,
        s.coverage_quality, s.freshness_quality, s.source_health_quality,
        s.transition_pending, s.transition_reason,
        s.as_of, s.available_at, s.computed_at,
        s.data_stale_after, s.pipeline_stale_after, s.stale_after,
        s.status_at_compute, s.model_version, s.confidence_model_version,
        s.confidence_method, s.source_vintage_hash,
    )


def audit_records(
    snapshot_id: str, contributions_by_axis: dict[str, dict[str, float]]
) -> list[tuple]:
    """One audit row per (snapshot_id, axis, series_id) from the contributions.

    The per-observation lineage columns (observation_period/vintage_id/
    revision_number) are NULL in A2 (the worker passes only the weighted z); A3
    wires the real lineage when the vintage walk threads it through.
    """
    rows: list[tuple] = []
    for axis, contribs in contributions_by_axis.items():
        for series_id, weighted_z in contribs.items():
            rows.append((snapshot_id, axis, series_id, weighted_z, None,
                         None, None, None, None, None, None, None))
    return rows


def ensure_schema(conn) -> None:
    sql_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), _SCHEMA)
    with open(sql_path, encoding="utf-8") as fh:
        conn.execute(fh.read())
    conn.commit()


_INSERT_SNAPSHOT = (
    f"INSERT INTO regime_quadrant_snapshot ({', '.join(_RECORD_COLS)}) "
    f"VALUES ({', '.join(['%s'] * len(_RECORD_COLS))}) "
    f"ON CONFLICT (snapshot_id) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in _RECORD_COLS if c != "snapshot_id")
)
_INSERT_AUDIT = (
    "INSERT INTO regime_quadrant_indicator_audit "
    "(snapshot_id, axis, series_id, z_score, weight, coverage, freshness, "
    " source_health, anomaly, observation_period, vintage_id, revision_number) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (snapshot_id, axis, series_id) DO UPDATE SET "
    "z_score = EXCLUDED.z_score"
)


def upsert_snapshot(conn, record: tuple, audit_rows: list[tuple]) -> None:
    """Idempotent upsert of one snapshot + its audit rows under one transaction."""
    with conn.cursor() as cur:
        cur.execute(_INSERT_SNAPSHOT, record)
        if audit_rows:
            cur.executemany(_INSERT_AUDIT, audit_rows)
    conn.commit()
```

- [ ] **Step 3b: Implement the macro worker `src/workers/quadrant_macro.py`**

```python
# src/workers/quadrant_macro.py
"""MacroReleaseAxisModel — the OFFICIAL strategic quadrant (freeze v1 §A, scope §1).

Consumes the point-in-time vintage store (A1 latest_vintage_as_of) for the seed
basket (A1 SEED_SOURCES), applies the per-series transform (seed: yoy), aggregates
by axis_weights, and emits the SAME QuadrantSnapshot the market worker emits via
the shared assembler. NEVER reads the latest-revision macro_data (look-ahead).
Market-implied is a separate worker and NEVER a fallback here: a bad macro snapshot
is persisted as non-valid and the backend turns that into QUADRANT_UNAVAILABLE.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
from typing import Any

from src import quadrant_assemble as qa
from src.db import LOCK_REGIME_QUADRANT, advisory_lock, connect
from src.macro_pit import latest_vintage_as_of
from src.macro_sources import SEED_SOURCES, axis_weights
from src.quadrant_confidence import U_FLOOR_SEED
from src.quadrant_score import axis_score, standardized_latest
from src.quadrant_staleness import source_deadlines

MODEL_VERSION = "macro_quadrant_us_v1"
CONFIDENCE_METHOD = "rolling_score_mad_distinct_vintages_v1"
SCORE_HISTORY_VINTAGES = 36   # distinct vintages window for uncertainty (>= MIN 24)
FRESHNESS_DECAY_WINDOW = _dt.timedelta(days=14)  # soft->hard linear decay (decision D)


def _axis_specs(axis: str):
    return [s for s in SEED_SOURCES if s.axis == axis]


def _score_axis(
    conn, axis: str, decision_time: _dt.datetime,
) -> tuple[float | None, dict[str, float], dict[str, float], list[_dt.datetime], list[_dt.datetime]]:
    """Compute (score, contributions, raw_z_by_series, input_available_ats,
    critical_expiries) for one axis from the PIT vintage store.

    raw z per series = latest transformed value <= decision_date; available_at_j =
    the vintage available_at proxied by decision_time (the PIT read already filters
    available_at <= decision_time, so the value IS knowable now). critical_expiries
    uses each MacroSourceSpec's cadence/grace/hard_max_age.
    """
    specs = _axis_specs(axis)
    weights = axis_weights(axis)
    series_ids = [s.series_id for s in specs]
    decision_date = decision_time.date()
    pit = latest_vintage_as_of(conn, series_ids, decision_time)

    z_by_series: dict[str, float | None] = {}
    for spec in specs:
        series = pit.get(spec.series_id, {})
        # two-stage standardize (economic_transform_id -> robust_z); None = missing.
        z = standardized_latest(spec, series, decision_date)
        # direction: a source whose rise means the OPPOSITE of the axis flips sign.
        z_by_series[spec.series_id] = (z * spec.direction) if z is not None else None

    score, contributions = axis_score(weights, z_by_series)

    input_available_ats = [decision_time]  # PIT guarantees availability <= now
    critical_expiries: list[_dt.datetime] = []
    for spec in specs:
        if not spec.critical:
            continue
        # monthly macro: next_expected_release seed = available + cadence (~30d);
        # the hard_max_age (45d) usually binds. (A3 will wire real release calendars.)
        next_release = decision_time + _dt.timedelta(days=30)
        critical_expiries.append(source_expiry(
            decision_time, next_release, spec.grace_period, spec.hard_max_age,
            FRESHNESS_DECAY_WINDOW))
    return score, contributions, z_by_series, input_available_ats, critical_expiries


def _coverage(z_by_series: dict[str, float], specs) -> float:
    """Σ|w|·I(valid) / Σ|w| over the axis (freeze §6 importance-weighted coverage)."""
    total = sum(abs(s.weight) for s in specs)
    if total <= 0:
        return 0.0
    have = sum(abs(s.weight) for s in specs
               if z_by_series.get(s.series_id) is not None)
    return have / total


def _score_history(conn, axis: str, decision_time: _dt.datetime) -> list[float]:
    """Distinct-vintage score history for the uncertainty MAD window.

    Walk back SCORE_HISTORY_VINTAGES monthly decision points, recomputing the axis
    score at each, and keep the DISTINCT values (the worker's recompute is
    deterministic given the vintage store).
    """
    history: list[float] = []
    for k in range(SCORE_HISTORY_VINTAGES):
        t = decision_time - _dt.timedelta(days=30 * (k + 1))
        score, *_ = _score_axis(conn, axis, t)
        if score is not None:
            history.append(score)
    return history


def ensure_schema(conn) -> None:
    qa.ensure_schema(conn)


def run(dsn: str, *, calc_date: str | None = None, limit: int | None = None) -> dict:
    """Compute today's macro quadrant snapshot and upsert it (idempotent)."""
    decision_time = (
        _dt.datetime.fromisoformat(calc_date).replace(tzinfo=_dt.timezone.utc)
        if calc_date else _dt.datetime.now(_dt.timezone.utc)
    )
    as_of = decision_time.date()
    with connect(dsn) as conn:
        with advisory_lock(conn, LOCK_REGIME_QUADRANT) as got:
            if not got:
                return {"days": 0, "upserted": 0, "skipped": "lock_busy"}
            ensure_schema(conn)

            # owner decision C — resume the latched chain from the last snapshot.
            prev = qa.load_previous_snapshot(conn, MODEL_VERSION)
            prev_id = prev["previous_snapshot_id"] if prev else None
            g_prev_sign = prev["growth_internal_sign"] if prev else None
            i_prev_sign = prev["inflation_internal_sign"] if prev else None

            g_score, g_contrib, g_z, g_av, g_exp = _score_axis(conn, "growth", decision_time)
            i_score, i_contrib, i_z, i_av, i_exp = _score_axis(conn, "inflation", decision_time)
            g_hist = _score_history(conn, "growth", decision_time)
            i_hist = _score_history(conn, "inflation", decision_time)

            g_specs, i_specs = _axis_specs("growth"), _axis_specs("inflation")
            g_cov, i_cov = _coverage(g_z, g_specs), _coverage(i_z, i_specs)
            # freshness/health: v1 seeds — PIT values are by construction fresh and
            # finite (the read already filtered availability); A3 wires real decay.
            g_fresh = i_fresh = 1.0
            g_health = 1.0 if g_score is not None else 0.0
            i_health = 1.0 if i_score is not None else 0.0

            source_vintage_hash = _vintage_hash(g_z, i_z, as_of)
            snap = qa.build_snapshot(
                as_of=as_of, computed_at=decision_time, previous_snapshot_id=prev_id,
                growth_score=g_score, growth_history=g_hist, growth_prev_sign=g_prev_sign,
                growth_coverage=g_cov, growth_freshness=g_fresh, growth_health=g_health,
                growth_contributions=g_contrib, growth_u_floor=U_FLOOR_SEED["growth"],
                inflation_score=i_score, inflation_history=i_hist,
                inflation_prev_sign=i_prev_sign,
                inflation_coverage=i_cov, inflation_freshness=i_fresh, inflation_health=i_health,
                inflation_contributions=i_contrib, inflation_u_floor=U_FLOOR_SEED["inflation"],
                input_available_ats=[*g_av, *i_av],
                critical_expiries=[*g_exp, *i_exp],
                model_version=MODEL_VERSION, confidence_method=CONFIDENCE_METHOD,
                source_vintage_hash=source_vintage_hash,
            )
            qa.upsert_snapshot(
                conn, qa.snapshot_to_record(snap),
                qa.audit_records(snap.snapshot_id,
                                 {"growth": g_contrib, "inflation": i_contrib}),
            )
    return {
        "days": 1, "upserted": 1, "status": snap.status_at_compute,
        "quadrant": snap.quadrant, "candidate_quadrant": snap.candidate_quadrant,
        "candidate_confidence": snap.candidate_confidence,
        "as_of": as_of.isoformat(), "model_version": MODEL_VERSION,
    }


def _vintage_hash(g_z: dict[str, Any], i_z: dict[str, Any], as_of: _dt.date) -> str:
    """Stable hash of the inputs that fed this snapshot (provenance / §8 cut)."""
    payload = repr((sorted(g_z.items()), sorted(i_z.items()), as_of.isoformat()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

> **NOTE — latched chain (owner decision C):** the worker resumes the hysteresis from the LAST snapshot of its `model_version` via `qa.load_previous_snapshot` — it threads that row's `growth_internal_sign`/`inflation_internal_sign` into `build_snapshot` as the per-axis `prev_sign`, and that row's `snapshot_id` becomes this snapshot's `previous_snapshot_id` (which also enters the deterministic uuid5). At genesis (no prior row) `prev=None` → `prev_sign=None` (re-init §5.1) and `previous_snapshot_id=None` → `"GENESIS"` in the id key. A full point-in-time historical BACKFILL (walking the whole monthly vintage series forward to rebuild the chain) is still A3 — only the live forward chain is A2. `U_FLOOR_SEED` (the per-axis seed floors) lives in `quadrant_confidence.py` (Task 5); the macro worker reads `U_FLOOR_SEED["growth"]`/`["inflation"]`.
>
> **NOTE — `source_vintage_hash` (A2 seed vs canonical §8):** `_vintage_hash` below hashes the standardized z-values + `as_of` so the daily recompute is deterministic and idempotent. The CANONICAL hash defined in Global Constraints (SHA-256 over ordered per-observation `source_id, observation_period, value, unit, release_at, available_at, vintage_id, revision_number, source_spec_version`) requires the full vintage lineage that A3 threads through `latest_vintage_as_of`; A2 uses the deterministic seed and the audit lineage columns stay NULL until then. The seed is sufficient for idempotency; switching to the canonical hash is an A3 step that does NOT change the snapshot contract.

- [ ] **Step 3c: Implement the market worker `src/workers/quadrant_market.py`**

```python
# src/workers/quadrant_market.py
"""MarketImpliedAxisModel — the preserved CHALLENGER (freeze scope §1, model
market_implied_quadrant_v0). Emits the SAME QuadrantSnapshot as the macro worker
via the shared assembler, from market proxies: growth = SPY 126d return; inflation
= TIP/IEF breakeven 126d momentum (the signals regime_gate already computes). This
worker runs SEPARATELY and is NEVER a fallback for the macro model — it exists for
shadow/regression/divergence research only.

Reuses the proxy fetch/align via a thin local copy of the price plumbing rather
than importing regime_gate (which must stay untouched). The score history for the
uncertainty MAD is the rolling 126d-return series over a 252-bd window.
"""
from __future__ import annotations

import datetime as _dt
import hashlib

from src import quadrant_assemble as qa
from src.db import LOCK_REGIME_QUADRANT, advisory_lock, connect
from src.quadrant_confidence import U_FLOOR_SEED
from src.quadrant_staleness import add_business_days, source_expiry

MODEL_VERSION = "market_implied_quadrant_v0"
CONFIDENCE_METHOD = "rolling_score_mad_252bd_v1"
WINDOW = 126
HISTORY_BD = 252
SPY_TICKER, IEF_TICKER, TIP_TICKER = "SPY", "IEF", "TIP"
HISTORY_START = _dt.date(2003, 1, 1)


def window_return(levels_desc: list[float], look: int) -> float | None:
    """levels newest-first: levels[0]/levels[look] - 1, or None during warmup."""
    if len(levels_desc) <= look:
        return None
    now, then = levels_desc[0], levels_desc[look]
    return (now / then - 1.0) if then > 0 else None


def rolling_score_history(levels_desc: list[float], look: int, span: int) -> list[float]:
    """Rolling window_return over the last ``span`` business days (newest-first)."""
    out: list[float] = []
    for offset in range(span):
        sub = levels_desc[offset:]
        r = window_return(sub, look)
        if r is not None:
            out.append(r)
    return out


def _fetch_levels(calc_date: _dt.date | None):
    """SPY level (growth) and TIP/IEF breakeven level (inflation), newest-first.

    Self-contained Tiingo fetch (does NOT import regime_gate). SPY is the spine;
    TIP/IEF carried forward on non-print days, both as ratio levels.
    """
    from src.workers._tiingo import TiingoClient

    with TiingoClient() as client:
        spy = client.fetch_daily_prices(SPY_TICKER, HISTORY_START, calc_date)
        ief = client.fetch_daily_prices(IEF_TICKER, HISTORY_START, calc_date)
        tip = client.fetch_daily_prices(TIP_TICKER, HISTORY_START, calc_date)
    if not spy:
        raise RuntimeError("Tiingo returned empty SPY history")

    ief_by = {d: float(v) for d, v in ief if v is not None and v > 0}
    tip_by = {d: float(v) for d, v in tip if v is not None and v > 0}
    last_ief = last_tip = None
    spy_levels: list[float] = []
    be_levels: list[float | None] = []
    for d, px in sorted(spy, key=lambda t: t[0]):
        if px is None or px <= 0:
            continue
        last_ief = ief_by.get(d, last_ief)
        last_tip = tip_by.get(d, last_tip)
        spy_levels.append(float(px))
        if last_tip is not None and last_ief and last_ief > 0:
            be_levels.append(last_tip / last_ief)
        else:
            be_levels.append(None)
    return spy_levels[::-1], be_levels[::-1]  # newest-first


def ensure_schema(conn) -> None:
    qa.ensure_schema(conn)


def run(dsn: str, *, calc_date: str | None = None, limit: int | None = None) -> dict:
    """Compute today's market-implied quadrant snapshot and upsert it."""
    cdate = _dt.date.fromisoformat(calc_date) if calc_date else None
    computed_at = _dt.datetime.now(_dt.timezone.utc)
    with connect(dsn) as conn:
        with advisory_lock(conn, LOCK_REGIME_QUADRANT) as got:
            if not got:
                return {"days": 0, "upserted": 0, "skipped": "lock_busy"}
            ensure_schema(conn)

            # owner decision C — resume the latched chain from the last snapshot.
            prev = qa.load_previous_snapshot(conn, MODEL_VERSION)
            prev_id = prev["previous_snapshot_id"] if prev else None
            g_prev_sign = prev["growth_internal_sign"] if prev else None
            i_prev_sign = prev["inflation_internal_sign"] if prev else None

            spy_desc, be_desc = _fetch_levels(cdate)
            be_clean = [b for b in be_desc if b is not None]
            as_of = cdate or computed_at.date()

            g_score = window_return(spy_desc, WINDOW)
            i_score = window_return(be_clean, WINDOW) if len(be_clean) > WINDOW else None
            g_hist = rolling_score_history(spy_desc, WINDOW, HISTORY_BD)
            i_hist = rolling_score_history(be_clean, WINDOW, HISTORY_BD)

            g_contrib = {"SPY_126d": g_score} if g_score is not None else {}
            i_contrib = {"TIP_IEF_126d": i_score} if i_score is not None else {}
            g_cov = 1.0 if g_score is not None else 0.0
            i_cov = 1.0 if i_score is not None else 0.0
            # market hard_max_age = 3 business days; available_at = computed (close+1
            # is already implied by using closes up to cdate). decay window 0 -> the
            # hard deadline binds immediately past soft for a daily source.
            expiries = [source_expiry(
                computed_at, add_business_days(computed_at, 1),
                _dt.timedelta(days=0), _dt.timedelta(days=3),
                _dt.timedelta(days=0))]

            vintage_hash = hashlib.sha256(
                repr((round(g_score or 0, 8), round(i_score or 0, 8),
                      as_of.isoformat())).encode()).hexdigest()
            snap = qa.build_snapshot(
                as_of=as_of, computed_at=computed_at, previous_snapshot_id=prev_id,
                growth_score=g_score, growth_history=g_hist, growth_prev_sign=g_prev_sign,
                growth_coverage=g_cov, growth_freshness=1.0,
                growth_health=1.0 if g_score is not None else 0.0,
                growth_contributions=g_contrib, growth_u_floor=U_FLOOR_SEED["growth"],
                inflation_score=i_score, inflation_history=i_hist,
                inflation_prev_sign=i_prev_sign,
                inflation_coverage=i_cov, inflation_freshness=1.0,
                inflation_health=1.0 if i_score is not None else 0.0,
                inflation_contributions=i_contrib, inflation_u_floor=U_FLOOR_SEED["inflation"],
                input_available_ats=[computed_at],
                critical_expiries=expiries,
                model_version=MODEL_VERSION, confidence_method=CONFIDENCE_METHOD,
                source_vintage_hash=vintage_hash,
            )
            qa.upsert_snapshot(
                conn, qa.snapshot_to_record(snap),
                qa.audit_records(snap.snapshot_id,
                                 {"growth": g_contrib, "inflation": i_contrib}),
            )
    return {
        "days": 1, "upserted": 1, "status": snap.status_at_compute,
        "quadrant": snap.quadrant, "candidate_quadrant": snap.candidate_quadrant,
        "as_of": as_of.isoformat(), "model_version": MODEL_VERSION,
    }
```

> **NOTE:** the per-axis seed floors live in `U_FLOOR_SEED` in `src/quadrant_confidence.py` (Task 5) — `{"growth": 0.25, "inflation": 0.25}` per owner decision B. The workers read `U_FLOOR_SEED["growth"]`/`["inflation"]`; there are no separate `U_FLOOR_GROWTH`/`U_FLOOR_INFLATION` module constants (the old 0.05 seed is superseded).

Add to the market worker's test file the `tests/test_quadrant_market.py` mirroring the macro one (window_return, rolling history, version strings, lock-busy):

```python
# tests/test_quadrant_market.py
from __future__ import annotations

from src.workers import quadrant_market as qmk


def test_window_return_newest_first() -> None:
    levels = [110.0] + [100.0] * 130  # now 110 vs 126d-ago 100 -> +10%
    assert abs(qmk.window_return(levels, 126) - 0.10) < 1e-9


def test_window_return_warmup_none() -> None:
    assert qmk.window_return([100.0, 99.0], 126) is None


def test_rolling_history_collects_returns() -> None:
    levels = [100.0 + i for i in range(400)][::-1]  # newest-first rising
    hist = qmk.rolling_score_history(levels, 126, 252)
    assert len(hist) >= 200 and all(isinstance(x, float) for x in hist)


def test_market_versions() -> None:
    assert qmk.MODEL_VERSION == "market_implied_quadrant_v0"
    assert qmk.CONFIDENCE_METHOD == "rolling_score_mad_252bd_v1"


def test_market_run_returns_lock_busy_sentinel(monkeypatch) -> None:
    import contextlib

    from src import quadrant_assemble as qa

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def commit(self): pass

    @contextlib.contextmanager
    def _busy(conn, lock_id):
        yield False

    monkeypatch.setattr(qmk, "connect", lambda dsn: _Conn())
    monkeypatch.setattr(qmk, "advisory_lock", _busy)
    monkeypatch.setattr(qa, "ensure_schema", lambda conn: None)
    out = qmk.run("postgresql://unused")
    assert out["skipped"] == "lock_busy"
```

In `src/run_worker.py`, extend the valid-worker error message string to include `quadrant_macro|quadrant_market` (cosmetic — `importlib` dispatch already works):

```python
            "WORKER env var not set (expected risk_metrics|characteristics|factor_model"
            "|nport_lookthrough|credit_regime|regime_composite|regime_gate"
            "|quadrant_macro|quadrant_market|macro_ingestion"
            "|macro_vintage|treasury_ingestion|benchmark_ingest|instrument_ingestion"
            "|eod_prices_warmer|sec_13f_ingestion|form345_ingestion)"
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_quadrant_macro.py tests/test_quadrant_market.py -v`
Expected: PASS (all)

- [ ] **Step 5: Smoke (env-gated — real PIT store / real Tiingo; run by the owner with keys, sandbox off)**

Append env-gated integration tests (one per worker). They need `DATABASE_URL` (Tiger cloud, with A1's `macro_observation_vintage` populated) and, for the market worker, `TIINGO_API_KEY`. ALFRED is NOT called here (the macro worker reads the already-ingested vintages); the A1 backfill of `macro_observation_vintage` must have run first.

```python
# append to tests/test_quadrant_macro.py
import os as _os

import pytest


@pytest.mark.skipif(not _os.getenv("DATABASE_URL"),
                    reason="needs DATABASE_URL with macro_observation_vintage populated")
def test_smoke_macro_run_emits_a_snapshot() -> None:
    out = qm.run(_os.environ["DATABASE_URL"])
    assert out["model_version"] == "macro_quadrant_us_v1"
    assert out["status"] in {"valid", "low_confidence", "unavailable", "invalid"}
    if out["status"] == "valid":
        assert out["quadrant"] in {"recovery", "expansion", "slowdown", "contraction"}
```

```python
# append to tests/test_quadrant_market.py
import os as _os

import pytest


@pytest.mark.skipif(
    not (_os.getenv("DATABASE_URL") and _os.getenv("TIINGO_API_KEY")),
    reason="needs DATABASE_URL + TIINGO_API_KEY")
def test_smoke_market_run_emits_a_snapshot() -> None:
    out = qmk.run(_os.environ["DATABASE_URL"])
    assert out["model_version"] == "market_implied_quadrant_v0"
    assert out["status"] in {"valid", "low_confidence", "unavailable", "invalid"}
```

Run (owner/session, keys set, sandbox off for Tiingo): `python -m pytest tests/test_quadrant_macro.py tests/test_quadrant_market.py -k smoke -v`
Expected: PASS (or SKIP if keys absent).

- [ ] **Step 6: Commit**

```bash
git add src/quadrant_assemble.py src/workers/quadrant_macro.py src/workers/quadrant_market.py \
        src/quadrant_confidence.py src/run_worker.py \
        tests/test_quadrant_macro.py tests/test_quadrant_market.py
git commit -m "feat(quadrant): macro + market AxisModel workers emit identical QuadrantSnapshot"
```

---

### Task 8: Backend reader v2 — consume only valid/fresh/confident snapshots (freeze §6)

> **REPO/BRANCH SWITCH:** this task is in the BACKEND repo `E:/investintell-light-combo/backend` @ branch `feat/combo-regime-allocator` — NOT the datalake worker repo. Paths below are relative to `backend/`. Run tests from `backend/` with its own venv.
>
> **CROSS-PLAN DEPENDENCY:** `app/services/taa_bands.py` is also edited by the Policy Core plan (track B, which adds `QuadrantPolicy`/`GateOverlay` consumption and raises `QUADRANT_UNAVAILABLE` at the call sites). This task is written autocontained: it only swaps the QUADRANT reader (new SQL + dataclass + `effective_status`) and leaves the GATE reader (`fetch_gate_regime` over `regime_gate_daily`) intact. If track B has already landed, apply only the non-conflicting reader pieces; if this lands first, track B builds on `fetch_quadrant_snapshot` below.

**Files:**
- Create: `app/services/quadrant_reader.py` (new reader, isolated from `taa_bands.py` to minimize the cross-plan conflict surface)
- Test: `tests/test_quadrant_reader.py`

**Interfaces:**
- Produces: frozen dataclass `QuadrantSnapshotRow` (the columns the consumable query selects); `effective_status(row, now) -> str` (mirrors §3); `async fetch_quadrant_snapshot(datalake: AsyncSession, *, model_version: str, decision_time: datetime) -> QuadrantSnapshotRow | None` running the §6 consumable query (`WHERE status_at_compute='valid' AND quadrant IS NOT NULL AND candidate_confidence >= 0.70 AND available_at <= :decision_time AND stale_after > :decision_time AND model_version = :model_version ORDER BY available_at DESC LIMIT 1`). Returns `None` when nothing is consumable (caller raises `QUADRANT_UNAVAILABLE` / no-trade — that escalation lives in the builder/track B, not the reader).

> **WHY THE BASE TABLE, NOT THE VIEW:** the operational view `regime_quadrant_current_v` (Task 1) filters with `now()`, which is correct for PRODUCTION but WRONG for backtest — a backtest at `decision_time` must not see snapshots that only became fresh/available afterwards. So the reader queries the BASE TABLE with `decision_time` bound for BOTH the point-in-time (`available_at <=`) and staleness (`stale_after >`) filters. In production `decision_time = now()`, so the reader returns exactly what the view would; the view stays the convenience accessor for dashboards/ops where `now()` is the only relevant cut.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quadrant_reader.py
from __future__ import annotations

import datetime as dt

import pytest

from app.services.quadrant_reader import (
    QuadrantSnapshotRow,
    effective_status,
    fetch_quadrant_snapshot,
)

UTC = dt.timezone.utc


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    """Fake AsyncSession capturing the SQL + bound params."""

    def __init__(self, row):
        self._row = row
        self.captured = None

    async def execute(self, stmt, params=None):
        self.captured = (str(stmt), params)
        return _Result(self._row)


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _valid_row(stale_after):
    return _Row(
        quadrant="expansion", candidate_quadrant="expansion",
        candidate_confidence=0.85, as_of=dt.date(2024, 3, 1),
        available_at=dt.datetime(2024, 3, 2, tzinfo=UTC),
        stale_after=stale_after, status_at_compute="valid",
        model_version="macro_quadrant_us_v1",
        growth_score=0.3, inflation_score=0.3, transition_pending=False,
    )


def test_effective_status_derives_stale() -> None:
    row = QuadrantSnapshotRow.from_db(_valid_row(dt.datetime(2024, 3, 3, tzinfo=UTC)))
    assert effective_status(row, dt.datetime(2024, 3, 4, tzinfo=UTC)) == "stale"
    assert effective_status(row, dt.datetime(2024, 3, 2, 12, tzinfo=UTC)) == "valid"


@pytest.mark.asyncio
async def test_fetch_returns_row_when_consumable() -> None:
    sess = _Session(_valid_row(dt.datetime(2024, 4, 1, tzinfo=UTC)))
    out = await fetch_quadrant_snapshot(
        sess, model_version="macro_quadrant_us_v1",
        decision_time=dt.datetime(2024, 3, 3, tzinfo=UTC))
    assert out is not None and out.quadrant == "expansion"


@pytest.mark.asyncio
async def test_fetch_query_filters_status_confidence_stale_and_pit() -> None:
    sess = _Session(None)
    await fetch_quadrant_snapshot(
        sess, model_version="macro_quadrant_us_v1",
        decision_time=dt.datetime(2024, 3, 3, tzinfo=UTC))
    sql, params = sess.captured
    assert "status_at_compute = 'valid'" in sql
    assert "quadrant IS NOT NULL" in sql
    assert "candidate_confidence >= 0.70" in sql
    assert "available_at <= " in sql
    assert "stale_after > " in sql
    assert "ORDER BY available_at DESC" in sql
    # forbidden: last-non-null forward-fill of any non-valid snapshot.
    assert "regime_date DESC" not in sql
    assert params["model_version"] == "macro_quadrant_us_v1"


@pytest.mark.asyncio
async def test_fetch_returns_none_when_nothing_consumable() -> None:
    sess = _Session(None)
    out = await fetch_quadrant_snapshot(
        sess, model_version="macro_quadrant_us_v1",
        decision_time=dt.datetime(2024, 3, 3, tzinfo=UTC))
    assert out is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_missing_relation() -> None:
    class _Boom:
        async def execute(self, *a, **k):
            raise RuntimeError("relation does not exist")
    out = await fetch_quadrant_snapshot(
        _Boom(), model_version="macro_quadrant_us_v1",
        decision_time=dt.datetime(2024, 3, 3, tzinfo=UTC))
    assert out is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_quadrant_reader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.quadrant_reader'`

- [ ] **Step 3: Implement the consumable reader**

```python
# app/services/quadrant_reader.py
"""Consumable QuadrantSnapshot reader (freeze v1 §6/§8).

Reads ONLY snapshots that are valid, fresh, confident, and available at the
decision time — NEVER the 'last non-null quadrant'. A missing/ambiguous/stale/
invalid snapshot yields None; the caller (portfolio builder / Policy Core) turns
that into QUADRANT_UNAVAILABLE + no-trade. The gate reader (fetch_gate_regime over
regime_gate_daily) is a SEPARATE dimension and is unchanged by this module.

This queries the BASE TABLE (not the regime_quadrant_current_v view), binding
``decision_time`` for both the point-in-time and staleness filters so a backtest
never sees the future; the view (which cuts with now()) is the ops/dashboard
accessor where now() is the only relevant decision time.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class QuadrantSnapshotRow:
    quadrant: str
    candidate_quadrant: str | None
    candidate_confidence: float | None
    as_of: _dt.date
    available_at: _dt.datetime
    stale_after: _dt.datetime
    status_at_compute: str
    model_version: str
    growth_score: float | None
    inflation_score: float | None
    transition_pending: bool

    @classmethod
    def from_db(cls, row: Any) -> "QuadrantSnapshotRow":
        def f(v: Any) -> float | None:
            return float(v) if v is not None else None
        return cls(
            quadrant=row.quadrant,
            candidate_quadrant=getattr(row, "candidate_quadrant", None),
            candidate_confidence=f(getattr(row, "candidate_confidence", None)),
            as_of=row.as_of,
            available_at=row.available_at,
            stale_after=row.stale_after,
            status_at_compute=row.status_at_compute,
            model_version=row.model_version,
            growth_score=f(getattr(row, "growth_score", None)),
            inflation_score=f(getattr(row, "inflation_score", None)),
            transition_pending=bool(getattr(row, "transition_pending", False)),
        )


def effective_status(row: QuadrantSnapshotRow, now: _dt.datetime) -> str:
    """Freeze §3: valid -> 'stale' once now >= stale_after; else pass through."""
    if row.status_at_compute == "valid" and now >= row.stale_after:
        return "stale"
    return row.status_at_compute


_CONSUMABLE_SQL = text("""
    SELECT quadrant, candidate_quadrant, candidate_confidence, as_of,
           available_at, stale_after, status_at_compute, model_version,
           growth_score, inflation_score, transition_pending
    FROM regime_quadrant_snapshot
    WHERE status_at_compute = 'valid'
      AND quadrant IS NOT NULL
      AND candidate_confidence >= 0.70
      AND model_version = :model_version
      AND available_at <= :decision_time
      AND stale_after > :decision_time
    ORDER BY available_at DESC
    LIMIT 1
""")


async def fetch_quadrant_snapshot(
    datalake: AsyncSession,
    *,
    model_version: str,
    decision_time: _dt.datetime,
) -> QuadrantSnapshotRow | None:
    """Latest consumable quadrant snapshot, or None (caller -> QUADRANT_UNAVAILABLE).

    ``decision_time`` is now() in production and the bar's decision time in
    backtest; it is used for BOTH the point-in-time filter (available_at <=) and
    the staleness filter (stale_after >), so a backtest never sees the future.
    """
    try:
        result = await datalake.execute(
            _CONSUMABLE_SQL,
            {"model_version": model_version, "decision_time": decision_time},
        )
        row = result.first()
    except Exception:
        return None
    if row is None:
        return None
    return QuadrantSnapshotRow.from_db(row)
```

> NOTE: the test `test_fetch_query_filters_...` asserts substrings against `str(stmt)`. SQLAlchemy `text()` stringifies to the literal SQL, so `"status_at_compute = 'valid'"`, `"available_at <= "`, `"stale_after > "`, and `"ORDER BY available_at DESC"` all appear verbatim. If the `backend` test suite lacks `pytest.mark.asyncio` support, the project already configures `asyncio_mode = "auto"` (used by the existing async builder tests); follow the same `pytest.ini`/`pyproject` setting — no new config in this task.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_quadrant_reader.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/quadrant_reader.py tests/test_quadrant_reader.py
git commit -m "feat(backend): consumable QuadrantSnapshot reader (valid/fresh/confident, no last-non-null)"
```

---

## Self-Review

**Spec coverage** (freeze v1 Parte A §2–§10 + §31/§36, scope §4–§7; + decisões finais do dono A–D):
- §3 dataclasses (`QuadrantSnapshot`/`AxisDiagnostics`, agora com `previous_snapshot_id` + `internal_sign` por eixo) + `effective_status` → Task 2. `snapshot_id` determinístico via `uuid5(namespace, model|as_of|vintage|prev)` (decisão C) → Task 2 `make_snapshot_id`.
- §3/§7 schema versionado (PK uuid, UNIQUE incl `previous_snapshot_id` NULLS NOT DISTINCT, `*_internal_sign` persistidos) + view operacional `regime_quadrant_current_v` + CHECKs de coerência/qualidade/ordenação temporal + auditoria §10 com lineage por observação → Task 1.
- Decisão A — `economic_transform_id` (impulso por família) + `standardizer_id` `robust_z_10y_distinct_vintages_v1`; `MacroSourceSpec` evoluído + `SEED_SOURCES` remapeado + funções puras testáveis (`log_3m3m_ann_v1`, `ann3m_minus_yoy_v1`, `log_qoq_saar_v1`, `mean3_gap_neutral_v1`, `delta_3m_level_v1`, `delta_3m_yoy_v1`) → Task 0; sem fallback `3m3m`→`yoy` (série insuficiente = INDISPONÍVEL).
- §4 score por eixo `s_a = Σ w_k·z_k` (transform→standardize→`axis_score` renormalizado) → Task 3.
- §5 hysteresis dos eixos (init §5.1, precedência troca-oposta-antes-de-estabilidade §5.2, deadband, memória interna preservada → agora EXPOSTA como `internal_sign`) → Task 4.
- Decisão B — confidence `Φ(s/u*)` + `u_raw = max(1.4826·MAD sobre vintages distintos, u_floor)`, `MIN_UNCERTAINTY_VINTAGES=24`, janela 36, `U_FLOOR_SEED=0.25` por eixo; as TRÊS qualidades completas (coverage importance-weighted, freshness soft/hard linear, source_health por checks); `u_adj = max(u_raw,u_floor)/max(q_data,0.25)`; `candidate_confidence = min(eixos)`; `MIN_SOURCE_HEALTH=0.90`; nova ORDEM DE STATUS (invalid→unavailable→stale→low(health)→low(conf)→low(transition)→valid) → Task 5.
- §8 `available_at = max(computed_at, max inputs)` + §9 `stale_after = min(data, pipeline)`, `pipeline = computed_at + 2 dias úteis`; decisão D — `source_deadlines` (soft = release+grace; hard = min(available+hard_max, soft+decay_window)) alimentando freshness e `source_expiry == hard` → Task 6.
- Decisão C — cadeia latched cross-run DENTRO do A2: `load_previous_snapshot` lê o último snapshot por `model_version`, threada `*_internal_sign` como `prev_sign` por eixo e o `snapshot_id` anterior como `previous_snapshot_id` (que entra no uuid5). Genesis → `prev_sign=None`/`"GENESIS"`. Só a CALIBRAÇÃO dos thresholds e o backfill PIT histórico ficam em A3 → Task 7.
- §3/§36 model_version/confidence_model_version/confidence_method/source_vintage_hash + os dois `*AxisModel` emitindo o MESMO snapshot via assembler compartilhado + dispatch (`run.py`/`run_worker.py`) → Task 7.
- Decisão D (fronteira) — A2 produz APENAS `QuadrantSnapshot`/`GateSnapshot`, sem ativos/fundos/proxies/constraints; §6 query consumível (proibido "último não-nulo") + `QUADRANT_UNAVAILABLE`/no-trade na fronteira (reader devolve None, caller escala) + point-in-time `available_at <= decision_time` sobre a TABELA BASE (a view usa `now()`, só para ops) → Task 8.

**Defaults documentados (ambiguidades autorizadas):** `economic_transform_id` por família + `standardizer_id` universal (Task 0, fórmulas travadas, thresholds A3); `U_FLOOR_SEED = {growth:0.25, inflation:0.25}` congelado em `confidence_v1.0` (Global Constraints + Task 5); `snapshot_id = uuid5(namespace, model|as_of|vintage_hash|prev|"GENESIS")` (Task 2); `source_vintage_hash` A2 = seed determinístico (z+as_of), canônico §8 é A3 (Task 7 NOTE); tabela separada `regime_quadrant_snapshot` ≠ `regime_gate_daily` (Task 1); "dia útil" = seg–sex sem feriados (Task 6); coverage = `Σ|w|·usable/Σ|w|` (Task 5 `coverage_quality`); freshness/health seeds do worker v1 = 1.0/finitude (Task 7, A3 wires decay real); `FRESHNESS_DECAY_WINDOW=14d` macro / `0d` market (Task 7).

**Placeholder scan:** sem TBD/TODO/"add error handling"/"similar to Task N"; cada step de código traz o código real (incl. as 6 funções de transform econômico e as 3 qualidades completas — sem meia-implementação); as NOTEs explicam decisões e o que é A3, não escondem implementação. Fixtures são dados construídos explicitamente.

**Type consistency:** `MacroSourceSpec` EVOLUÍDO (Task 0) usado idêntico por `standardized_latest` (Task 3) e pelo macro worker (Task 7) — o campo `economic_transform_id`/`standardizer_id`/`neutral_level` referenciado em todas. `QuadrantSnapshot`/`AxisDiagnostics` (Task 2, com `previous_snapshot_id`/`internal_sign`) consumidos idênticos por `build_snapshot`/`snapshot_to_record`/`_RECORD_COLS` (Task 7) e pelo DDL (Task 1, mesma ordem de colunas incl. `previous_snapshot_id` 2ª + os `*_internal_sign`). `axis_hysteresis -> (int|None, int|None, bool, str|None)` (Task 4) → `classify_axis` (Task 7) preenche `sign`/`internal_sign`. `uncertainty_raw -> float|None`, `axis_confidence -> (float,float)`, `coverage_quality`/`axis_freshness`/`source_health -> float`, `freshness_value -> float`, `resolve_status(critical_structural_failure, coverage, critical_source_expired, source_health, candidate_confidence, transition_pending) -> ComputeStatus` (Task 5) consumidos em `classify_axis`/`build_snapshot` (Task 7). `source_deadlines -> (datetime,datetime)` / `source_expiry -> datetime` (Task 6, assinatura de 5 args) usados pelos dois workers (Task 7). `make_snapshot_id(model_version, as_of, vintage_hash, prev) -> str` (Task 2) chamado por `build_snapshot` (Task 7). `load_previous_snapshot -> dict|None` (Task 7) consumido pelos dois `run()`. A query do reader (Task 8) seleciona colunas que existem no DDL (Task 1). `LOCK_REGIME_QUADRANT=900_208` definido na Task 1, usado na Task 7.

**Conflito com A1 (tratado):** `MacroSourceSpec`/`SEED_SOURCES` foram entregues em A1 com `transform_id`/`transform="yoy"` no MESMO repo/branch (`feat/combo-regime-gate`). A Task 0 evolui esse arquivo in-place (split do `transform_id`, +`neutral_level`/`minimum_valid_observations`, `SEED_SOURCES` remapeado) e ATUALIZA os testes de A1 que afirmavam `transform_id`/`yoy`. O worker A1 `macro_vintage.py` não referencia `transform_id` (só ingere vintages) → não quebra; `axis_weights` e `SOURCE_SPEC_VERSION` preservados. Documentado em Global Constraints ("Conflito com A1") e no header da Task 0.

**Cross-repo boundary:** Tasks 0–7 no repo worker (`feat/combo-regime-gate`); Task 8 no repo backend (`feat/combo-regime-allocator`) — sinalizado no header da Task 8 e na constraint global, com a dependência do track B (Policy Core toca `taa_bands.py`) isolada via novo módulo `quadrant_reader.py`.

**Deferred to owner's environment (não-A2 / ops):** backfill em massa de `macro_observation_vintage` (A1) deve ter rodado antes do smoke do macro worker; backfill PIT histórico da cadeia latched, hash canônico §8 e calibração dos thresholds/floors são A3; 2 cron services Railway (`quadrant_macro`/`quadrant_market`) + flip de model_version ativa no backend + merge para main + popular prod são A5 (ativação atômica §36) — explicitamente fora deste plano. Os smokes (Task 7 Step 5) são env-gated e rodáveis nesta sessão com `DATABASE_URL`/`TIINGO_API_KEY` e sandbox off.
