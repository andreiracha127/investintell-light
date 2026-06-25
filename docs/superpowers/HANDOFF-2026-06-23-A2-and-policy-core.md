# HANDOFF — COMBO regime_aware: planejar A2 + Backend Policy Core (em paralelo)

**Data:** 2026-06-23. **Para:** sessão fresh. **Tarefa:** escrever DOIS planos de implementação em paralelo —
(1) **A2** (workers de classificação de quadrante) e (2) **Backend Policy Core** — depois executá-los via SDD com Opus 4.8.

Este doc é auto-suficiente. Leia os specs e dossiês citados; não re-descubra o que já está mapeado.

---

## 0. O que é este projeto (1 parágrafo)

Rearquitetura do alocador `regime_aware` (codinome COMBO) do Investintell Light. Uma revisão adversarial achou bugs
reais (cap/overlap ignorados no two-level, goldfix quebra fund-only, infeasibilidade em universo estreito) e um P0
(bug de data que derrubava todo `regime_aware` em sessão real). O dono então congelou uma arquitetura nova v1:
**quadrante (macro, point-in-time) ⊥ gate (mercado, diário)**, 7 sleeves estruturais, fail-loud, sem `combined_regime`,
sem goldfix especial, com um compilador two-level que compila cap/min/overlap como constraints no Level-1.

## 1. Specs autoritativos (LEIA PRIMEIRO)

- `docs/superpowers/specs/2026-06-23-combo-regime-aware-architecture-freeze-v1.md` — o Architecture Freeze v1 (38 seções, APROVADO). Quadrante/gate/políticas/overlay/compilador/erros/legados.
- `docs/superpowers/specs/2026-06-23-combo-scope-decision-macro-v1.md` — adendo de escopo: quadrante OFICIAL = macro publicado PIT; market-implied vira challenger; confidence MAD-sobre-vintages; sequência A1–A5; `MacroSourceSpec`.

Os números de seção (§N) abaixo referem-se ao freeze v1.

## 2. Repos / branches / ambientes (CRÍTICO — dois repos distintos)

| Track | Repo / worktree | Branch | venv |
|---|---|---|---|
| **A2 (workers)** | `E:/investintell-datalake-workers-combo` | `feat/combo-regime-gate` | `.venv/Scripts/python.exe` |
| **Backend policy core** | `E:/investintell-light-combo/backend` | `feat/combo-regime-allocator` | `.venv/Scripts/python.exe` |

- Os planos (`.md`) ficam em `E:/investintell-light-combo/docs/superpowers/plans/`.
- **Sem remote** (merges locais). Rodar testes do diretório-raiz de cada repo com `.venv/Scripts/python -m pytest`.
- **Janela de rede do sandbox NÃO inclui `api.stlouisfed.org`**: chamadas FRED/ALFRED exigem `dangerouslyDisableSandbox: true`. A `FRED_API_KEY` vive em `E:/investintell-datalake-workers/.env` (`set -a; source ...; set +a`, sem ecoar).
- **Tiger prod** (data lake): service `t83f4np6x4` (use mcp tiger `db_execute_query`). Banco local de ingestão: `localhost:5434/investintell_alloc`.

## 3. O que já está feito (NÃO refazer)

**Plano 0 (P0 date fix)** — COMPLETO no backend light combo (`feat/combo-regime-allocator`, commits `dbdc36a..1c1cb19`). O `frame.index` vinha como `Index` de `datetime.date` (object dtype) e `frame_index.min().date()` levantava `AttributeError` em todo `regime_aware` real. Fix = `app/optimizer/dates.py::coerce_date` nos loaders. **Já resolvido — não se preocupe com isso.** Plano: `docs/superpowers/plans/2026-06-23-p0-date-normalization.md`.

**Plano A1 (infra macro vintage PIT)** — COMPLETO no datalake combo (`feat/combo-regime-gate`, commits `1e7017a..ac0f426`, ready-to-merge, smoke ALFRED real + DDL validada). Entregou:
- Tabela `macro_observation_vintage` (hypertable PIT): `(series_id, observation_period, vintage_date, value, available_at, revision_number, source, source_spec_version, ingested_at)`, PK `(series_id, observation_period, vintage_date)`. `available_at` = vintage_date 00:00 UTC. `LOCK_MACRO_VINTAGE=900_321`.
- `src/macro_sources.py`: `MacroSourceSpec` (frozen) + `SEED_SOURCES` (cesta seed: growth=INDPRO/PCEC96/PAYEMS/ACOGNO; inflation=CPILFESL/PPIFIS/AHETPI/MICH) + `axis_weights(axis) -> dict[series_id, peso_normalizado]` + `SOURCE_SPEC_VERSION="macro_quadrant_us_v1.0"`.
- `src/workers/macro_vintage.py`: `parse_alfred_vintages(series_id, payload) -> list[dict]` (ALFRED output_type=2, comprime a revisões reais), `fetch_vintages`, `rows_to_records`, `upsert_vintages` (ON CONFLICT DO NOTHING), `run(dsn, *, limit=None)`. Reusa `TokenBucket`/`FRED_BASE_URL` de `macro_ingestion`.
- `src/macro_pit.py`: **`latest_vintage_as_of(conn, series_ids, decision_time) -> dict[str, dict[date, float]]`** — a leitura PIT que A2 consome.
- Plano: `docs/superpowers/plans/2026-06-23-A1-macro-vintage-infra.md`. Ledger: `E:/investintell-datalake-workers-combo/.superpowers/sdd/progress.md`.
- **Pendente (não fazer agora — é A5/deploy):** backfill em massa das 8 séries (rodar `run()` contra o DB), cron Railway, ativação atômica.

## 4. Dossiês de pesquisa já levantados (consultar para detalhes finos)

- `E:/light-patches/combo-research/2026-06-23-terrain-map.json` — mapa do terreno (6 frentes): worker gate, taa_bands+call-sites, engine, overlap/lookthrough, schemas/rota, run_optimize/testes.
- `E:/light-patches/combo-research/2026-06-23-gap-analysis-freeze-v1.json` — gap analysis freeze-vs-código (6 áreas g1..g6): REUSÁVEL/MUDA/NOVO/AMBIGUIDADE/ESFORÇO por Parte. **g1**=worker snapshot, **g2**=policy core, **g3**=gate overlay, **g4**=two-level compiler, **g5**=pós-verif/erros/legados, **g6**=PIT/testes. Parsear com PowerShell `(Get-Content $f -Raw | ConvertFrom-Json).result.'g2-policy-core'`.

---

## 5. TRACK A — Plano A2 (workers de classificação de quadrante)

**Repo:** datalake combo (`feat/combo-regime-gate`). **Consome:** A1 (`macro_pit.latest_vintage_as_of`, `macro_sources`). **Dossiê:** gap `g1-worker-snapshot`.

**Objetivo:** dois workers que emitem **exatamente o mesmo `QuadrantSnapshot`** (§3): `MacroReleaseAxisModel` (oficial, consome a leitura PIT macro) e `MarketImpliedAxisModel` (challenger, do SPY 126d / TIP-IEF breakeven 126d que o `regime_gate.py` atual já calcula). Rodam separados; **sem híbrido; market-implied NUNCA é fallback** (§32, scope §1).

**Blocos (provável decomposição do plano):**
1. Schema `regime_quadrant_snapshot` (tabela NOVA versionada, §3/§7) + tabela de auditoria por-indicador (§10) + um `LOCK_*` novo. Colunas: quadrant/candidate_quadrant/candidate_confidence, AxisDiagnostics×2 (growth/inflation: score/sign/candidate_confidence/margin/uncertainty_raw/uncertainty_adjusted), coverage/freshness/source_health_quality, transition_pending/reason, as_of/available_at/computed_at, data_stale_after/pipeline_stale_after/stale_after, status_at_compute, model_version/confidence_model_version/confidence_method/source_vintage_hash, snapshot_id. CHECKs do §7. Validar contra Timescale via BEGIN/ROLLBACK.
2. `QuadrantSnapshot`/`AxisDiagnostics` dataclasses + `effective_status(snapshot, now)` derivado na leitura (§3/§6).
3. **Score por eixo**: a partir de `latest_vintage_as_of`, aplicar o `transform_id` por série (seed: yoy), agregar por `axis_weights`. (transform exato = ambiguidade, ver §7 abaixo.)
4. **Hysteresis de eixo (§5)** — estado latched POR EIXO (espelhar a state-machine de `build_rows` do `regime_gate.py`, que já faz isso para o gate): `AXIS_ENTER=0.25`/`AXIS_EXIT=0.10`, **precedência obrigatória: troca-oposta (`signed_margin <= -AXIS_ENTER`) ANTES de estabilidade (`>= AXIS_EXIT`)**, senão deadband → `transition_pending=true`, `quadrant=NULL`.
5. **Confidence (§4/§6, scope §6)** — `confidence_method="rolling_score_mad_distinct_vintages_v1"` (macro) / `"rolling_score_mad_252bd_v1"` (market): `u_raw = max(1.4826·MAD(s sobre VINTAGES DISTINTOS), u_floor)`, `MIN_UNCERTAINTY_VINTAGES=12` (senão unavailable), **sem /√n**; qualidades ponderadas por `|w_k|`; `q_data=min(3)`; `u_adj=u_raw/max(q_data,0.25)`; `confidence=Φ(|s|/u_adj)`; `candidate_confidence=min(eixos)`. **Hard gates SEPARADOS** (coverage<0.80→unavailable; crítica inválida→invalid; now≥stale_after→stale; transition_pending→low_confidence; confidence<0.70→low_confidence). Usa o **sinal candidato do score**, não o da hysteresis.
6. `stale_after` (§9): `min(data_stale_after, pipeline_stale_after)`; `pipeline_stale_after=computed_at+2 dias úteis`; `data_stale_after` por fonte crítica (hard_max_age do `MacroSourceSpec`).
7. Os dois `*AxisModel` emitindo o mesmo snapshot + o `run` de cada worker.
8. **Backend reader v2** (no light combo): trocar `taa_bands.fetch_gate_regime`/`_GATE_LATEST_SQL` pela query do §6 (`WHERE status_at_compute='valid' AND quadrant IS NOT NULL AND candidate_confidence>=0.70 AND stale_after>now() ORDER BY available_at DESC LIMIT 1`) — proibido "último não-nulo". Snapshot inválido → `QUADRANT_UNAVAILABLE` + no-trade.

**Reusável (g1):** `regime_gate.py` `build_rows` (state-machine latched), `macro_quadrant` (mapeamento growth_up×infl_up→4 quadrantes), o padrão `ensure_schema`/`run`/`advisory_lock`/upsert em chunks. O gate state-machine (votação 2-de-3 + dwell 21d) NÃO muda — é o `market_risk_gate`.

---

## 6. TRACK B — Plano Backend Policy Core

**Repo:** backend light combo (`feat/combo-regime-allocator`). **Independente do worker** (consome o contrato `QuadrantSnapshot` já materializado). **Dossiês:** gap `g2-policy-core`, `g3-gate-overlay`.

**Objetivo:** substituir o modelo antigo (`combined_regime`, `PROFILE_CENTERS` por band_state, `HW_SCALE` runtime, goldfix) por `QuadrantPolicy[profile][quadrant]` + `GateOverlay` ortogonais.

**Blocos (provável decomposição):**
1. **`QuadrantPolicy` (§14)**: `center`/`half_width`(finais, sem HW_SCALE)/`risk_assets_cap`/`defensive_floor`/`fixed_income_sub_budgets`/`policy_version`. `QUADRANT_POLICIES[profile][quadrant]` = **12 políticas** (3 perfis × 4 quadrantes). RECOVERY≡RISK_ON e EXPANSION≡INFLATION do `PROFILE_CENTERS` atual (renomear chaves); SLOWDOWN/CONTRACTION usam as **seeds §17/§18** (somam 100%, validadas). Half-widths finais (seed §19), aposentar `HW_SCALE` em runtime.
2. **Invariantes (§15) + startup validation (§37)**: `Σcenter=1`, `lo/hi`, `Σlo≤1≤Σhi`, `equity+thematic≤risk_assets_cap`, `cash+fixed_income+gold+long_short≥defensive_floor`; 12 políticas presentes; sem normalização em runtime. Plugar no boot (`app/main.py`).
3. **Ortogonalização (§12)**: APOSENTAR `combined_regime` (gap g2: ~8 call-sites de produção + schemas/rota + dezenas de testes — a maior fatia). `band_state_from_quadrant` e `profile_sleeve_bands` saem; entra `QUADRANT_POLICIES[profile][quadrant]`. Listar e reescrever cada call-site (ver g2 + terrain-map).
4. **`GateOverlay` (§22)**: `GateOverlayShape(cvar_tightening/beta_tightening/risk_assets_reduction)` + `ProfileGatePolicy(intensity/bl_view_confidence_multiplier)`. Fórmulas `effective_*` substituem `DEFAULT_RISK_OFF_CVAR_FACTOR`. `risk_off.bl_view_confidence_multiplier=0.0` (μ=π, NUNCA `confidence=0` em `omega_idzorek`). `beta_tightening` **reusa** `beta_graduated_caps` escalando o coeficiente (decisão travada — ver g3).
5. Aposentar legados (§I, parcial — o resto é no compilador, Plano C): `STAG_GOLD`, `goldfix_target`/`_haven`, `hedge`/`SH` dos centros, `effective_class_bands`/`DEFAULT_TAA_BANDS` (quando o `complete_macro` do compilador substituir o S4a — pré-requisito, coordenar).

**NOTA:** `fixed_income_sub_budgets` = **contrato + campo versionado vazio na v1**, sem imposição real (§20 diz não declarar tilts FI até calibrados). O compilador two-level (cap/min/overlap como matriz M, preflight, pós-verificação) é o **Plano C separado** (não este) — mas o policy core deve expor `risk_assets_cap`/`defensive_floor`/sub-budgets para C consumir.

---

## 7. DECISÕES TRAVADAS (não re-litigar)

- Quadrante OFICIAL = **macro publicado point-in-time** (`macro_quadrant_us_v1`). Market-implied = challenger (`market_implied_quadrant_v0`), shadow/regressão, **nunca fallback**. Gate = market, diário.
- **Macro-ingestion atual (`macro_data`) NÃO tem vintages** (auditado: Tiger prod + local 5434, só valor revisado, FRED). Por isso A1 criou `macro_observation_vintage` via ALFRED. NÃO reusar `macro_data` para PIT.
- Confidence = proxy operacional MAD-sobre-vintages (NÃO 252d forward-filled, NÃO probabilidade calibrada). Calibrar SÓ contra abstenção/flips/reversões/estabilidade — **nunca CAGR/Sharpe**.
- 7 sleeves estruturais; **SH só research** (fora de centros/prior/fills). SLOWDOWN **sem goldfix** (mesmo pipeline).
- Fail-loud: nunca pesos com warnings; nunca relaxa constraint; nunca troca mandato; `QUADRANT_UNAVAILABLE`/no-trade quando inválido. `strategic_neutral` só como objetivo explícito.
- Ativação atômica (§36): worker v2 + backend v2 juntos. **Não mergear para main agora; não popular prod.**
- A cesta seed do A1 e os centros SLOWDOWN/CONTRACTION são **seeds a calibrar** (parameter freeze = A3/A4, trabalho do dono no harness). A próxima sessão implementa a ESTRUTURA com as seeds.

## 8. AMBIGUIDADES DE IMPLEMENTAÇÃO a resolver com o dono (antes ou durante o plano)

- **A2 — `transform_id` por série**: a seed é `yoy`; confirmar a transformação exata por família (yoy / mom annualizado / z-score) — afeta o score. Propor default e seguir.
- **A2 — mecânica de `u_floor` e das 3 qualidades** com fontes macro: como medir coverage/freshness/source_health concretamente (g1 lista isso como o ESFORÇO-G da confidence). Propor defaults; o dono calibra os valores.
- **A2 — `snapshot_id` / `as_of` vs `vintage`**: g1 propõe `snapshot_id` determinístico (`model_version:as_of:vintage_hash[:12]`) e tabela separada `regime_quadrant_snapshot` (≠ `regime_gate_daily`). Confirmar.
- **Backend — destino do `beta_tightening`**: reusar `beta_graduated_caps` (decisão travada) vs beta cap novo no Level-1 — confirmar o ponto de aplicação (g3 detalha as 2 leituras).
- **Two-level**: o compilador (matriz M, complete_macro/strict, preflight, pós-verificação) é o **Plano C**, separado destes dois. NÃO incluir em A2/policy-core; mas o policy core expõe as constraints que C compila.

## 9. Como executar (padrão estabelecido nesta linha de trabalho)

1. **Planejar**: skill `superpowers:writing-plans`. Como A2 e policy-core são **independentes**, escrever os DOIS planos — pode despachar **2 subagentes Opus em paralelo** (um por plano) OU um workflow de 2 frentes (ultracode). Cada plano: header + Global Constraints + tasks TDD com código real, **sem placeholders** (ver os planos P0/A1 como modelo de granularidade).
2. **Executar**: skill `superpowers:subagent-driven-development` com **Opus 4.8** (implementers + reviewers), um subagente fresco por task, review spec+qualidade por task (template em `.../subagent-driven-development/task-reviewer-prompt.md`), fix-loop em Critical/Important, ledger em `<repo>/.superpowers/sdd/progress.md`, review final whole-branch. Scripts: `task-brief PLAN N`, `review-package BASE HEAD` (rodar do repo-raiz correto). **Validar DDL contra Timescale via BEGIN/ROLLBACK** e rodar smokes reais (ALFRED com sandbox-off) como fiz no A1.
3. As duas frentes podem ser executadas em paralelo (repos/branches distintos — sem colisão).

## 10. Estado de memória

`combo-regime-aware-rearch.md` (memória de projeto) resume tudo isto e linka [[combo-regime-allocator-build]] [[combo-bl-utility-calibration]]. Os ledgers SDD vivem em cada repo. Atualizar a memória ao fim de A2/policy-core.
