# Calibration Seed v0.1 Execution Report

Data: 2026-06-24

Branch backend: `feat/combo-regime-allocator`

Worker repo usado para A3 operacional: `E:/investintell-datalake-workers-combo`

## Escopo Executado

Foi executada a parte disponivel da sequencia recomendada:

1. Commit do documento de parametros e seed v0.1.
2. Validacao dos testes puros A1/A2 no worker.
3. Backfill PIT das 8 series macro vintage via `macro_vintage`.
4. Materializacao do snapshot oficial macro-release via `quadrant_macro`.
5. Materializacao do snapshot shadow market-implied via `quadrant_market`.
6. Aplicacao da seed A4 v0.1 no backend:
   - gate corrigido;
   - centros/caps/floors conservative slowdown/contraction corrigidos;
   - guardrails de viabilidade e monotonia adicionados em testes.

## Commits

Documento de parametros/seed:

```text
6bc214a docs(combo): add regime-aware calibration seed
```

## A3 - Execucao Operacional Disponivel

### Testes Worker

Comando:

```powershell
cd E:\investintell-datalake-workers-combo
.\.venv\Scripts\python.exe -m pytest `
  tests\test_macro_sources.py `
  tests\test_macro_transforms.py `
  tests\test_macro_vintage.py `
  tests\test_macro_pit.py `
  tests\test_quadrant_score.py `
  tests\test_quadrant_confidence.py `
  tests\test_quadrant_hysteresis.py `
  tests\test_quadrant_snapshot.py `
  tests\test_quadrant_macro.py `
  tests\test_quadrant_market.py -q
```

Resultado:

```text
81 passed, 4 skipped
```

### Backfill PIT Macro Vintage

Comando executado com `DATABASE_URL` e `FRED_API_KEY` carregados de `E:/investintell-datalake-workers/.env`, sem imprimir segredos:

```powershell
$env:WORKER='macro_vintage'
.\.venv\Scripts\python.exe -m src.run_worker
```

Resultado:

```json
{"worker": "macro_vintage", "status": "ok", "series": 8, "upserted": 70747}
```

Contagem atual na tabela `macro_observation_vintage`:

| Series | Rows | Observation min | Observation max | Vintage min | Vintage max |
|---|---:|---|---|---|---|
| ACOGNO | 3,267 | 1992-02-01 | 2026-04-01 | 2011-06-24 | 2026-06-03 |
| AHETPI | 3,983 | 1964-01-01 | 2026-05-01 | 1999-08-06 | 2026-06-05 |
| CPILFESL | 2,256 | 1957-01-01 | 2026-05-01 | 1996-12-12 | 2026-06-10 |
| INDPRO | 38,718 | 1919-01-01 | 2026-05-01 | 1927-01-26 | 2026-06-15 |
| MICH | 584 | 1978-01-01 | 2026-04-01 | 1999-02-26 | 2026-04-24 |
| PAYEMS | 13,679 | 1939-01-01 | 2026-05-01 | 1955-05-06 | 2026-06-05 |
| PCEC96 | 7,473 | 1959-01-01 | 2026-04-01 | 1979-11-19 | 2026-05-28 |
| PPIFIS | 787 | 2009-11-01 | 2026-05-01 | 2014-02-19 | 2026-06-11 |

### Snapshot Macro-Release Oficial

Comando:

```powershell
$env:WORKER='quadrant_macro'
.\.venv\Scripts\python.exe -m src.run_worker
```

Resultado:

```json
{
  "worker": "quadrant_macro",
  "days": 1,
  "upserted": 1,
  "status": "valid",
  "quadrant": "expansion",
  "candidate_quadrant": "expansion",
  "candidate_confidence": 0.7958603180582218,
  "as_of": "2026-06-24",
  "model_version": "macro_quadrant_us_v1"
}
```

### Snapshot Market-Implied Shadow

Comando:

```powershell
$env:WORKER='quadrant_market'
.\.venv\Scripts\python.exe -m src.run_worker
```

Resultado:

```json
{
  "worker": "quadrant_market",
  "days": 1,
  "upserted": 1,
  "status": "low_confidence",
  "quadrant": null,
  "candidate_quadrant": "expansion",
  "as_of": "2026-06-24",
  "model_version": "market_implied_quadrant_v0"
}
```

Estado atual em `regime_quadrant_snapshot`:

| Model version | Status | Count | Max as_of | Max confidence |
|---|---|---:|---|---:|
| macro_quadrant_us_v1 | valid | 1 | 2026-06-24 | 0.7959 |
| market_implied_quadrant_v0 | low_confidence | 1 | 2026-06-24 | 0.5216 |

## A3 - Bloqueio Do Replay/Grid Completo

O worker de producao atual ainda esta na seed A2:

- pesos macro simples de 8 series;
- `AXIS_ENTER = 0.25`;
- `AXIS_EXIT = 0.10`;
- `U_FLOOR_SEED = {"growth": 0.25, "inflation": 0.25}`;
- confidence por `Phi(abs(score) / u_adj)`.

A seed v0.1 do parecer exige um harness/config ainda nao implementado:

- classes de transformacao v0.1 por familia;
- cesta ampliada ou explicitamente mapeada para familias growth/inflation;
- pesos por familia, nao apenas por serie;
- `u_t = 0.35C + 0.20F + 0.25A + 0.20V`;
- hysteresis por eixo com `growth enter=0.35`, `inflation enter=0.40`, `exit=0.15`;
- confidence operacional `0.60u + 0.40sqrt(m_growth*m_inflation)`;
- replay historico/grid search sem escrever snapshots fora de ordem na tabela oficial.

Portanto, A3 ficou executado ate o limite operacional existente: PIT backfill + snapshot oficial atual + market-implied shadow atual. O replay/grid v0.1 ainda precisa de um harness separado para nao contaminar a cadeia latched oficial em `regime_quadrant_snapshot`.

## A4 - Seed v0.1 Aplicada No Backend

Alteracoes aplicadas:

### Gate

| Parametro | Antes | Depois |
|---|---:|---:|
| `cvar_tightening` | 0.50 | 0.35 |
| `beta_tightening` | 0.30 | 0.25 |
| `risk_assets_reduction` | 0.10 | 0.07 |

Intensidades permanecem:

| Profile | Intensity |
|---|---:|
| conservative | 0.50 |
| moderate | 0.70 |
| aggressive | 1.00 |

### Conservative Slowdown/Contraction

| Quadrant | Cash | Equity | FI | Thematic | Alternatives | Gold | L/S | Risk cap | Defensive floor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| slowdown | 21% | 5% | 34% | 1% | 10% | 16% | 13% | 12% | 68% |
| contraction | 28% | 3% | 45% | 0% | 4% | 10% | 10% | 8% | 74% |

Guardrails adicionados:

- `aggressive/recovery/risk_off`: cap efetivo `38%` contra piso geometrico `36%`, folga `2pp`.
- Conservative risk-assets: `7.47% -> 6.30% -> 6.00% -> 3.00%`.

### Testes Backend Executados

Focado policy/gate/two-level:

```text
96 passed
```

Gates Plano C:

```text
tests/test_optimizer_sleeves.py tests/test_builder_regime_two_level.py
60 passed

tests/test_builder_regime_aware_schema.py tests/test_effective_policy.py tests/test_gate_overlay.py tests/test_optimizer_mandate.py tests/test_builder_schema.py tests/test_quadrant_policy.py
92 passed

tests/test_builder_overlap.py tests/test_optimizer_engine.py
59 passed
```

## Proximo Passo Tecnico

Construir um harness A3/A4 separado, read-only por padrao, que:

1. leia `macro_observation_vintage`;
2. gere replay PIT historico em tabela/arquivo de trabalho, nao em `regime_quadrant_snapshot`;
3. implemente a seed v0.1 de transformacoes/family weights/confidence;
4. produza relatorio macro-release vs market-implied;
5. rode grid search pequeno;
6. exporte um manifest versionado de parameter freeze.

