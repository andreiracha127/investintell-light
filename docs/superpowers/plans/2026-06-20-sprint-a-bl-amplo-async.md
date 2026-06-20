# Sprint A — BL no universo amplo + execução assíncrona — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Destravar `bl_utility`/`max_return_cvar` no modo `broad_universe` (prior de equilíbrio, zero views) e executar a otimização ampla de forma assíncrona via tabela `optimize_jobs`.

**Architecture:** O backend de `run_optimize` já roda BL no caminho broad (converge para o bloco BL comum; `needs_bl` já computa `w_mkt`/`equilibrium` e `require_aum`). A trava está só na validação do schema. A execução assíncrona adiciona uma tabela mínima de jobs, um ramo 202+job_id no endpoint para o modo amplo, e polling no frontend.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, cvxpy/CLARABEL, Next.js + React Query, pytest, vitest.

## Global Constraints
- Erros de domínio → `BuilderError` → 422 com mensagem verbatim (`humanize_error`).
- Async **apenas** no modo amplo (`universe.broad_universe = True`); ranked/explícito continua síncrono.
- Estado de job vive na tabela (nunca em memória) → polling robusto multi-pod.
- Vocabulário de classes: `equity | fixed_income | cash | alternatives | multi_asset`.
- DDL nova em `backend/db/ddl/` seguindo a convenção datada do projeto.
- TDD: teste falhando antes da implementação; gate verde (typecheck/lint/pytest/vitest/build) antes de fechar a sprint.

---

### Task 1: Destravar BL no modo amplo (schema)

**Files:**
- Modify: `backend/app/schemas/builder.py` (validador `_check_asset_source`, ~L212-258)
- Test: `backend/tests/test_builder_schema.py` (ou o arquivo de testes de schema existente do builder)

**Interfaces:**
- Consumes: `OptimizeRequest`, `UniverseSpecIn`, `Objective`.
- Produces: regras de validação atualizadas — `bl_utility` e `max_return_cvar` passam a ser aceitos quando `universe` (inclusive `broad_universe=True`); *views* continuam rejeitadas com `universe`.

**Mudança exata:**
- Remover o bloco que rejeita `max_return_cvar` com `universe` broad (atual ~L235-240) e o que o rejeita com qualquer `universe` (atual ~L241-245). **Manter** `cvar_limit is None → ValueError` (atual ~L233-234).
- Remover o bloco que rejeita `bl_utility` no broad (atual ~L246-257).
- **Manter** a rejeição de `views` + `universe` (atual ~L219-226).

- [ ] **Step 1: Escrever testes falhando**

Em `test_builder_schema.py`, adicionar:
```python
def test_bl_utility_allowed_in_broad_universe():
    req = OptimizeRequest(
        universe=UniverseSpecIn(broad_universe=True, max_positions=20),
        objective="bl_utility",
    )
    assert req.objective == "bl_utility"  # não levanta

def test_max_return_cvar_allowed_in_broad_universe():
    req = OptimizeRequest(
        universe=UniverseSpecIn(broad_universe=True, max_positions=20),
        objective="max_return_cvar",
        cvar_limit=0.02,
    )
    assert req.cvar_limit == 0.02  # não levanta

def test_max_return_cvar_still_requires_cvar_limit():
    with pytest.raises(ValidationError, match="cvar_limit"):
        OptimizeRequest(
            universe=UniverseSpecIn(broad_universe=True),
            objective="max_return_cvar",
        )

def test_views_still_rejected_with_universe():
    with pytest.raises(ValidationError, match="views cannot be combined"):
        OptimizeRequest(
            universe=UniverseSpecIn(broad_universe=True),
            objective="bl_utility",
            views=[AbsoluteViewIn(asset=FundRefIn(id=1), ret=0.1, confidence=0.5)],
        )
```
(Ajustar imports/forma dos `ViewIn` ao que o schema exige — ver `AbsoluteViewIn` real.)

- [ ] **Step 2: Rodar e ver falhar**
Run: `cd backend && python -m pytest tests/test_builder_schema.py -k "broad_universe or cvar_limit or views_still" -v`
Expected: FAIL (os dois primeiros levantam ValidationError hoje).

- [ ] **Step 3: Remover as travas no validador `_check_asset_source`**
Editar o validador conforme "Mudança exata" acima.

- [ ] **Step 4: Rodar e ver passar**
Run: `cd backend && python -m pytest tests/test_builder_schema.py -v`
Expected: PASS (todos, inclusive os de regressão de views).

- [ ] **Step 5: Commit**
```bash
git add backend/app/schemas/builder.py backend/tests/test_builder_schema.py
git commit -m "Allow BL objectives in broad-universe mode (equilibrium prior, no views)"
```

---

### Task 2: Teste de integração — BL roda no broad (orquestrador)

**Files:**
- Test: `backend/tests/test_lookthrough.py`? Não — usar o arquivo de testes do builder/optimizer existente (`backend/tests/test_portfolio_builder.py` ou equivalente; localizar via `ls backend/tests | grep -i builder`).

**Interfaces:**
- Consumes: `portfolio_builder.run_optimize(session, OptimizeRequest, datalake=None)`.
- Produces: confirmação de que `bl_utility` + `broad_universe` produz pesos válidos (somam 1, respeitam cap) usando o prior de equilíbrio, sem views.

**Objetivo:** garantir que a remoção da trava (Task 1) realmente faz o caminho broad+BL funcionar de ponta a ponta no serviço (não só no schema). Usar as fixtures/seam de teste já existentes do builder (procurar como os testes atuais montam universo de fundos com AUM e NAV; reusar `_OVERRIDE_REGIME_STATE` se necessário).

- [ ] **Step 1: Localizar o padrão de teste do builder**
Run: `cd backend && ls tests | grep -iE "builder|optimi"` e ler um teste de `broad_universe` existente para copiar o setup (fixtures de Fund/FundNav/AUM).

- [ ] **Step 2: Escrever teste falhando/garantia**
Test que monta um universo broad pequeno (≥4 fundos com AUM>0 e NAV suficiente), chama `run_optimize` com `objective="bl_utility"`, `universe.broad_universe=True`, e afirma: `sum(weights) ≈ 1`, todos `≥ 0`, `≤ cap` efetivo, e `expected.mu_equilibrium is not None`.

- [ ] **Step 3: Rodar**
Run: `cd backend && python -m pytest tests/<arquivo>::test_bl_utility_broad_end_to_end -v`
Expected: PASS (backend já suporta; se falhar, investigar `_market_weights_for`/`require_aum`).

- [ ] **Step 4: Commit**
```bash
git add backend/tests/<arquivo>
git commit -m "Test BL equilibrium runs end-to-end over broad universe"
```

---

### Task 3: Tabela e modelo `optimize_jobs`

**Files:**
- Create: `backend/db/ddl/2026-06-20_optimize_jobs.sql`
- Create/Modify: `backend/app/models/optimize_job.py` (novo model SQLAlchemy)
- Test: `backend/tests/test_optimize_jobs_model.py`

**Interfaces:**
- Produces: model `OptimizeJob` com colunas `id: UUID`, `organization_id: UUID`, `status: str` (`pending|running|succeeded|failed`), `request: dict (JSONB)`, `result: dict | None (JSONB)`, `error: str | None`, `created_at`, `updated_at`. CRUD helpers em `app/services/optimize_jobs.py`: `create_job(session, org_id, request) -> OptimizeJob`, `get_job(session, job_id) -> OptimizeJob | None`, `mark_running/mark_succeeded(result)/mark_failed(error)`.

**DDL (modelo de referência — ajustar tipos ao padrão do projeto, ver outro DDL recente):**
```sql
CREATE TABLE optimize_jobs (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    status       text NOT NULL CHECK (status IN ('pending','running','succeeded','failed')),
    request      jsonb NOT NULL,
    result       jsonb,
    error        text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON optimize_jobs (organization_id, created_at DESC);
```

- [ ] **Step 1: Escrever teste falhando** dos CRUD helpers (`create_job` → `pending`; `mark_succeeded` grava result e muda status; `get_job` recupera).
- [ ] **Step 2: Rodar e ver falhar** (`ModuleNotFoundError`/tabela ausente).
- [ ] **Step 3: Criar DDL + model + service** (`OptimizeJob`, `optimize_jobs.py`). Aplicar o DDL no banco de teste pelo mecanismo que os testes do projeto usam (ver conftest/fixtures de schema).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Add optimize_jobs table and CRUD service`.

---

### Task 4: Endpoint assíncrono para o modo amplo

**Files:**
- Modify: `backend/app/api/routes/builder.py` (endpoint `optimize`; novo `GET /builder/optimize/{job_id}`)
- Modify: `backend/app/schemas/builder.py` (novo `OptimizeJobAccepted {job_id}` e `OptimizeJobStatus {status, result?, error?}`)
- Test: `backend/tests/test_builder_async.py`

**Interfaces:**
- Consumes: `optimize_jobs.create_job/get_job/mark_*`, `portfolio_builder.run_optimize`.
- Produces: `POST /builder/optimize` no modo amplo → **202** + `OptimizeJobAccepted`; síncrono no resto (200 + `OptimizeResponse`). `GET /builder/optimize/{job_id}` → `OptimizeJobStatus`.

**Comportamento:**
- Se `payload.universe and payload.universe.broad_universe`: criar job (`pending`), disparar `asyncio.create_task(_run_job(job_id, payload, org_id))`, responder 202 + `{job_id}`. O `_run_job` abre sessão própria, `mark_running`, roda `run_optimize`, `mark_succeeded(result.model_dump())` ou, em `BuilderError`, `mark_failed(humanize_error(...))`.
- Caso contrário: comportamento atual (síncrono).
- `GET /optimize/{job_id}`: 404 se não existe; senão devolve status e, se terminal, `result` (já como `OptimizeResponse`) ou `error`.

- [ ] **Step 1: Escrever testes** (broad → 202+job_id; GET até `succeeded` retorna result; caminho de erro → `failed` com mensagem; ranked → 200 síncrono inalterado). Usar `httpx.AsyncClient`/TestClient conforme o padrão do projeto; aguardar o task com pequeno polling/`asyncio.sleep` ou injetando execução determinística.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** o ramo async + `GET` + schemas.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Run broad-universe optimize asynchronously via job + polling endpoint`.

---

### Task 5: Frontend — disparar job e fazer polling no modo amplo

**Files:**
- Modify: `frontend/src/components/builder/BuilderView.tsx`
- Modify: `frontend/src/lib/api/client.ts` (novas chamadas `postBuilderOptimizeAsync`, `getBuilderOptimizeJob`)
- Test: `frontend/src/components/builder/__tests__/BuilderView.async.test.tsx` (ou local de testes FE do projeto)

**Interfaces:**
- Consumes: `POST /builder/optimize` (202 no amplo), `GET /builder/optimize/{job_id}`.
- Produces: no modo amplo, `BuilderView` dispara o job e faz polling até terminal, renderizando `result` no `ResultsPanel` existente, ou o `error`.

**Comportamento:**
- Detectar modo amplo no submit (mesma flag que envia `broad_universe`). Se amplo: chamar a versão async → guardar `job_id` → `useQuery({queryKey:['optimizeJob',job_id], queryFn, refetchInterval: d => terminal? false : 1500})`. Mostrar "otimizando…". Em `succeeded`, alimentar o `ResultsPanel`; em `failed`, mostrar `error`. Ranked continua no `useMutation` síncrono.

- [ ] **Step 1: Escrever teste** (mock do 202 + sequência de GET `pending→running→succeeded`; assert que o `ResultsPanel` recebe os pesos; teste do caminho `failed`).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** client + fluxo de polling no `BuilderView`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Poll async optimize job in broad-universe builder mode`.

---

### Task 6: Gate verde + fechamento da Sprint A

- [ ] **Step 1: Backend** `cd backend && python -m pytest -q` → tudo verde (ou só falhas pré-existentes conhecidas, documentadas).
- [ ] **Step 2: Lint/type backend** conforme o projeto (`ruff`/`mypy` se configurados).
- [ ] **Step 3: Frontend** `cd frontend && pnpm test && pnpm typecheck && pnpm build`.
- [ ] **Step 4: Commit final** se houver ajustes de gate; senão, sprint A concluída.

## Self-Review (cobertura da spec §4)
- §4.1 destravar BL no amplo → Task 1 (+ Task 2 garante e2e). `require_aum` já existe no código (confirmado L317).
- §4.2 execução assíncrona (tabela + endpoints) → Tasks 3, 4.
- §4.3 frontend polling → Task 5.
- §4.4 testes → embutidos por tarefa + Task 6 (gate).
- §4.5 async só no amplo / sem expurgo → Global Constraints + Task 4 (ramo condicional).
