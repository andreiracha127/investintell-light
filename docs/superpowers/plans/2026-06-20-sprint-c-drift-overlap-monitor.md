# Sprint C — Monitor de drift, breach de classe e overlap, alertas in-app — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`).

**Goal:** Um worker diário avalia, por portfólio, (a) drift dos pesos atuais vs. pesos do inception além das bandas de rebalance, (b) breach dos limites por classe de ativo (Sprint B), e (c) — quando há N-PORT novo (trimestral) — overlap por ação acima do teto; grava o estado numa tabela e expõe alertas in-app.

**Architecture:** Reusa o núcleo existente: `rebalance/evaluator.compute_drifts` para a classificação de drift, `portfolio_constraints.get_constraints` para os limites, `lookthrough_exposure.fund_equity_exposure` para o overlap, e o padrão de worker de `portfolio_nav_daily.py`. Persiste o resultado da última avaliação numa única tabela `portfolio_drift_status` (breaches em JSONB). Sem e-mail, sem SSE, sem histórico.

**Tech Stack:** SQLAlchemy async, FastAPI, Pydantic v2, worker CLI + advisory lock, Next.js/React Query, pytest, vitest.

## Global Constraints
- **Alvo do drift = pesos do INCEPTION** (reconstruídos das transações de inception: `peso_i = qty_i·price_i / Σ qty·price` na `inception_date`), NÃO a realocação ótima do evaluator. Usar `compute_drifts(current, target, band_abs, band_rel)` para classificar.
- **Drift e class breach: cadência diária.** **Overlap: recomputar só quando o `report_date` do N-PORT é mais recente que o último avaliado** (senão reusar o último resultado). N-PORT é trimestral.
- Pesos atuais e pesos-alvo são frações do VALOR INVESTIDO (cash fora), consistente com o evaluator/overview existentes.
- Class breach: peso atual agregado por `asset_class` vs. `portfolio_class_limits` (min/max). Vocabulário: equity|fixed_income|cash|alternatives|multi_asset.
- Overlap do portfólio por ação `s`: `Σ_fundos peso_fundo_atual · h_{fundo,s}` (look-through equity), comparado a `overlap_cap`.
- Uma row por portfólio em `portfolio_drift_status` (upsert pelo worker). Alertas in-app via `GET /portfolios/{id}/alerts`. Sem e-mail/SSE.
- Branch: `feat/bl-amplo-constraints-drift`. Implementers NÃO criam/trocam de branch.
- DDL datada em `backend/db/ddl/`; model registrado em `app/models/__init__.py`. Advisory lock novo (ex.: `900_042`).
- TDD; gate verde ao fim da sprint.

---

### Task 1: Tabela e model `portfolio_drift_status` + service de leitura/escrita

**Files:**
- Create: `backend/db/ddl/2026-06-20_portfolio_drift_status.sql`
- Create: `backend/app/models/portfolio_drift_status.py`; Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/portfolio_drift.py` (parte de persistência nesta task)
- Test: `backend/tests/test_portfolio_drift_status.py`

**Interfaces:**
- Produces: tabela `portfolio_drift_status` — `portfolio_id` (PK, FK `portfolios.id` ON DELETE CASCADE), `evaluated_at timestamptz`, `worst_status text` (`ok|maintenance|urgent`), `breaches jsonb` (objeto: `{position_drifts: [...], class_breaches: [...], overlap_breaches: [...], overlap_report_date: date|null}`), `created_at`/`updated_at`. Service: `upsert_drift_status(session, portfolio_id, *, evaluated_at, worst_status, breaches: dict) -> None` e `get_drift_status(session, portfolio_id) -> DriftStatus | None` (typed).
- Seguir o padrão de `portfolio_constraint.py`/`optimize_job.py` (int PK family, DDL espelhada, registro, conftest schema).

- [ ] **Step 1: Testes falhando** dos CRUD (upsert cria; re-upsert atualiza; get devolve typed; get(missing)→None; JSONB round-trip do dict de breaches).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Criar DDL + model + service + registro.**
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Add portfolio_drift_status table and CRUD service`.

---

### Task 2: Avaliação — drift vs inception, class breach, overlap breach

**Files:**
- Modify: `backend/app/services/portfolio_drift.py` (lógica de avaliação)
- Test: `backend/tests/test_portfolio_drift_eval.py`

**Interfaces:**
- Consumes: `portfolio_crud.build_overview`/`resolve_position_taxonomy` (pesos atuais + asset_class), `portfolio_constraints.get_constraints`, `rebalance.evaluator.compute_drifts` (+ `RebalancePolicy` bands), `lookthrough_exposure.fund_equity_exposure`, transações de inception (`portfolio_transactions` na `inception_date`).
- Produces, em `portfolio_drift.py`:
  - `def inception_target_weights(inception_txns) -> dict[str, float]` — `qty·price` normalizado por ticker.
  - `def compute_class_breaches(weights_by_class: dict[str,float], constraints: ConstraintSet | None) -> list[ClassBreach]` — para cada class limit, breach se `current < min` ou `current > max`.
  - `async def compute_overlap_breaches(session, datalake, fund_weights: dict[uuid,float], overlap_cap, report_date) -> list[OverlapBreach]` — consolida `Σ peso_fundo·h_{fundo,s}` por security; breach se `> overlap_cap`.
  - `async def evaluate_portfolio_drift(session, datalake, portfolio, *, previous: DriftStatus | None, as_of) -> tuple[worst_status, breaches_dict]` — orquestra: pesos atuais (overview), target do inception, `compute_drifts` (bands da policy ou defaults), class breaches, e overlap **só se** o N-PORT `report_date` mudou vs. `previous.breaches["overlap_report_date"]` (senão reaproveita `previous` overlap). Deriva `worst_status` da pior severidade (drift `urgent`/`maintenance`; qualquer class/overlap breach ≥ `maintenance`).

**Decisão (verbatim):** o alvo é o inception, não a realocação ótima. Para o portfólio sem `inception_date`/transações (ex.: criado fora do builder), drift vs alvo é pulado (sem target) — só class/overlap são avaliados; documentar.

- [ ] **Step 1: Testes falhando** — `inception_target_weights` normaliza; `compute_class_breaches` detecta abaixo do min e acima do max e nada quando dentro; `compute_overlap_breaches` soma exposição por ação e marca breach acima do teto; `evaluate_portfolio_drift` reusa overlap anterior quando `report_date` não mudou e recomputa quando muda; `worst_status` correto.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** os helpers + orquestração (stub das fontes como os testes de rebalance/overview/lookthrough fazem).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Evaluate portfolio drift, class and overlap breaches`.

---

### Task 3: Worker `portfolio_drift_daily.py`

**Files:**
- Create: `backend/app/jobs/workers/portfolio_drift_daily.py`
- Modify: `backend/app/services/portfolio_drift.py` (adicionar `materialize_all_portfolio_drifts(session, datalake, *, portfolio_ids=None, as_of=None) -> dict`)
- Test: `backend/tests/test_portfolio_drift_worker.py`

**Interfaces:**
- Consumes: `evaluate_portfolio_drift`, `get_drift_status`/`upsert_drift_status`.
- Produces: worker espelhando `portfolio_nav_daily.py` — `async def run(*, portfolio_ids=None, as_of=None) -> dict`, advisory lock novo (`900_042`), abre sessão primária + datalake opcional (mesmo padrão da Sprint A T4b: `datalake.py` `_get_sessionmaker`), itera portfólios, chama `evaluate_portfolio_drift` (passando o `previous` via `get_drift_status` para a otimização de overlap), faz `upsert_drift_status`, commit, retorna `{status, lock_id, portfolios:[...]}`. CLI `python -m app.jobs.workers.portfolio_drift_daily [--portfolio-id N ...] [--as-of YYYY-MM-DD]`.

- [ ] **Step 1: Teste falhando** — `run(portfolio_ids=[id])` materializa uma row em `portfolio_drift_status` (status condizente com o setup); idempotência (re-run atualiza, não duplica); lock skip path.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** worker + `materialize_all_portfolio_drifts`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Add portfolio_drift_daily worker`.

---

### Task 4: Endpoint de alertas

**Files:**
- Modify: `backend/app/api/routes/rebalance.py` (ou `portfolios.py`) — `GET /portfolios/{portfolio_id}/alerts`
- Modify: `backend/app/schemas/portfolios.py` (ou rebalance) — schema de saída dos alertas
- Test: `backend/tests/test_portfolio_alerts_route.py`

**Interfaces:**
- Consumes: `portfolio_drift.get_drift_status`.
- Produces: `GET /portfolios/{id}/alerts` → o estado mais recente (`evaluated_at`, `worst_status`, `breaches`); se não há avaliação ainda → estado vazio (`worst_status="ok"`, listas vazias), 200; 404 só se o portfólio não existe. Auth como as rotas irmãs.

- [ ] **Step 1: Testes falhando** — após upsert, GET reflete o estado; sem avaliação → 200 vazio; portfólio inexistente → 404.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** rota + schema.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Add GET portfolio alerts endpoint`.

---

### Task 5: Frontend — seção/badge de alertas

**Files:**
- Create: `frontend/src/components/portfolio/PortfolioDriftSection.tsx`
- Modify: `frontend/src/components/portfolio/PortfolioOverviewView.tsx` (integrar a seção)
- Modify: `frontend/src/lib/api/client.ts` (`getPortfolioAlerts(id)`)
- Regenerar tipos: `backend/openapi.json` (`scripts/export_openapi.py`) + `pnpm run types`
- Test: vitest da seção

**Interfaces:**
- Consumes: `GET /portfolios/{id}/alerts`.
- Produces: um badge de status (verde `ok` / laranja `maintenance` / vermelho `urgent`) + lista dos breaches (drift por posição, breach de classe, overlap por ação). React Query (`queryKey: ['portfolio', id, 'alerts']`, staleTime ~5min). Seguir o padrão de `PortfolioRebalanceSection.tsx`/`PortfolioConstraintsSection.tsx`.

- [ ] **Step 1: Teste falhando** — a seção busca via GET (mock) e renderiza o badge do `worst_status` e os itens de breach; estado vazio → "sem alertas".
- [ ] **Step 2: Rodar e ver falhar** (`pnpm test`).
- [ ] **Step 3: Implementar** seção + client + tipos.
- [ ] **Step 4: Rodar e ver passar** + `pnpm run typecheck`.
- [ ] **Step 5: Commit** `Add portfolio drift/alerts section to the portfolio page`.

---

### Task 6: Gate verde da Sprint C

- [ ] **Step 1: Backend** `cd backend && .venv/Scripts/python -m pytest -q` → verde (ou só falhas pré-existentes conhecidas, ex.: mypy `funds_catalog.py:291`).
- [ ] **Step 2: ruff/mypy** nos arquivos da Sprint C.
- [ ] **Step 3: Frontend** `pnpm test && pnpm run typecheck && pnpm build`.
- [ ] **Step 4: Commit** de ajustes de gate, se houver.

## Self-Review (cobertura da spec §6)
- §6.1 vigia drift (diário) + class breach (diário) + overlap (trimestral via report_date) → Tasks 2, 3.
- §6.2 pesos atuais (overview) + alvo (inception) → Task 2.
- §6.3 worker diário (padrão nav_daily) → Task 3.
- §6.4 estado/alertas in-app (tabela + endpoint + badge) → Tasks 1, 4, 5. Sem e-mail/SSE.
