# Sprint B — Constraints persistidos, overlap por ação e NAV synth no save — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`).

**Goal:** Persistir, por portfólio, os limites de construção (cap por posição, min/max por classe de ativo, teto único de overlap por ação) aplicados a TODOS os objetivos do otimizador; aplicar o teto de overlap como constraint dura linear (apenas ações, via look-through); e sintetizar a NAV ao salvar (inception + pesos iniciais).

**Architecture:** O engine ganha uma forma genérica de restrição linear (`LinearConstraint`: `coef·w ≤ hi`, `≥ lo`) aplicada na base de TODOS os solvers — isso unifica block budgets (hoje só em min_cvar/max_return_cvar) e habilita a constraint de overlap. Uma matriz fundo→ação (equity, via `lookthrough.py`) gera os coeficientes do overlap. Os limites são persistidos numa tabela `portfolio_constraints` ao salvar, e o save passa a criar transações de inception e materializar a NAV.

**Tech Stack:** cvxpy/CLARABEL, SQLAlchemy async, Pydantic v2, FastAPI, Next.js/React Query, pytest, vitest.

## Global Constraints
- **Overlap = exposição look-through por AÇÃO** (`Σ_fundos w_fundo · h_{fundo,ação} + exposição_direta_ação ≤ overlap_cap`). É restrição LINEAR nos pesos. NÃO é turnover, NÃO é w-vs-w0. Apenas holdings de **equity**; dívida/caixa dos fundos são ignorados. Fundos sem look-through contribuem 0 (best-effort, documentado).
- Teto de overlap é **único por portfólio** (um escalar), não por ação.
- `cap` (máx por posição) e `overlap_cap` (máx por ação look-through) são limites DISTINTOS e ambos preservados.
- Vocabulário de classes: `equity | fixed_income | cash | alternatives | multi_asset`.
- Branch: `feat/bl-amplo-constraints-drift`. Implementers NÃO criam/trocam de branch — commitam na branch atual.
- DDL nova em `backend/db/ddl/` (convenção datada). Model novo registrado em `app/models/__init__.py`.
- TDD; gate verde (pytest/ruff/mypy/vitest/typecheck/build) ao fim da sprint.

---

### Task 1: `LinearConstraint` genérica no engine, aplicada a todos os objetivos

**Files:**
- Modify: `backend/app/optimizer/engine.py` (`base_constraints` ~L209-218, `bounds_constraints` ~L290-351, todos os `solve_*`; `solve_bl_utility` está em `black_litterman.py`)
- Test: `backend/tests/test_optimizer_engine.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class LinearConstraint: coef: np.ndarray (n,); lo: float | None; hi: float | None; label: str`. Cada `solve_*` aceita um novo kwarg `linear: list[LinearConstraint] | None = None` e adiciona, para cada `lc`: `lc.coef @ w <= lc.hi` (se hi) e `>= lo` (se lo). Também faz block budgets (hoje só em min_cvar/max_return_cvar) valerem para `solve_min_vol`/`solve_erc`/`solve_max_diversification`/`solve_equal_weight`/`solve_bl_utility` — pela mesma via.
- Pré-solve: validar inviabilidade óbvia (ex.: `hi < 0`) como `OptimizerError` (fail-loud), seguindo o padrão de `_check_constraint_params`/`bounds_constraints`.

**Comportamento:** Centralizar num helper (ex.: estender `base_constraints` para receber `blocks` e `linear`) e fazer TODOS os solvers chamarem esse caminho único, em vez de cada um remontar `[w>=0, sum(w)==1]`. Manter retrocompatibilidade (kwargs default None → comportamento atual).

- [ ] **Step 1: Testes falhando** — para um problema de 3 ativos, `solve_min_vol` com um `LinearConstraint(coef=[1,1,0], hi=0.5)` retorna pesos com `w0+w1 ≤ 0.5+1e-6`; idem `solve_bl_utility`; e um block budget aplicado a `solve_erc` é respeitado. Um `LinearConstraint(hi=-1)` levanta `OptimizerError`.
- [ ] **Step 2: Rodar e ver falhar** (`cd backend && .venv/Scripts/python -m pytest tests/test_optimizer_engine.py -k linear -v`).
- [ ] **Step 3: Implementar** o dataclass + caminho de constraints único + kwargs em todos os solvers.
- [ ] **Step 4: Rodar e ver passar** + suite do engine inteira sem regressão.
- [ ] **Step 5: Commit** `Add generic LinearConstraint to optimizer, honored by all objectives`.

---

### Task 2: Tabela e model `portfolio_constraints`

**Files:**
- Create: `backend/db/ddl/2026-06-20_portfolio_constraints.sql`
- Create: `backend/app/models/portfolio_constraint.py`; Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/portfolio_constraints.py`
- Test: `backend/tests/test_portfolio_constraints.py`

**Interfaces:**
- Produces: tabela-cabeçalho 1:1 `portfolio_constraint_set` (`portfolio_id` PK/FK cascade, `cap float | null`, `min_weight float | null`, `overlap_cap float | null`, timestamps) e linhas `portfolio_class_limits` (`portfolio_id` FK, `asset_class` text CHECK no vocabulário, `min_weight float | null`, `max_weight float | null`, UNIQUE(portfolio_id, asset_class)). Service: `upsert_constraints(session, portfolio_id, *, cap, min_weight, overlap_cap, class_limits: list[(asset_class, lo, hi)]) -> None` e `get_constraints(session, portfolio_id) -> ConstraintSet | None`.
- Seguir o padrão de model/DDL/registro do projeto (ver `app/models/portfolio.py`, `app/models/optimize_job.py`, DDL datado) e o mecanismo de schema de teste em `backend/tests/conftest.py`.

- [ ] **Step 1: Testes falhando** dos CRUD (upsert cria; upsert de novo atualiza; get devolve o conjunto; cascade ao deletar portfólio — ou ao menos FK presente; class limit duplicado por classe é rejeitado/sobrescrito conforme upsert).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Criar DDL + models + service + registrar.**
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Add portfolio_constraints tables and CRUD service`.

---

### Task 3: Look-through — matriz fundo→ação (equity)

**Files:**
- Modify: `backend/app/services/lookthrough.py` (nova função pública) — OU novo `backend/app/services/lookthrough_exposure.py` se `lookthrough.py` já estiver grande.
- Test: `backend/tests/test_lookthrough_exposure.py`

**Interfaces:**
- Produces: `async def fund_equity_exposure(session_or_datalake, fund_instrument_ids: list[int]) -> dict[int, dict[str, float]]` — para cada fund id, um mapa `security_key -> pct_of_nav` (fração 0..1) considerando APENAS holdings de equity, com a expansão child-series que o look-through já faz (reusar `build_portfolio_exposure_tree`/`consolidate_portfolio`/`fetch_many_lookthroughs` — NÃO reescrever a decomposição). `security_key` = identificador estável da ação (CUSIP normalizado; ticker quando resolúvel). Fundos sem look-through → ausentes do dict (contribuem 0 a jusante).

**Investigação obrigatória (implementer):** decida, lendo `lookthrough.py`, a forma mais barata de obter exposição por security de equity reaproveitando a infra existente (o tree já desce a folhas CUSIP/security; filtre `asset_class == 'equity'`). NÃO consultar tabelas cruas se uma função de consolidação já entrega isso. Se a granularidade por security exigir uma query nova a `sec_nport_holdings`/`fund_holdings_v` (cusip/isin/issuer_name/asset_class/pct_of_nav por series), siga o padrão de query dinâmica já usado no arquivo.

- [ ] **Step 1: Teste falhando** — com fixtures de 2 fundos cujos holdings de equity (via a infra de look-through, stubbada como os testes existentes de lookthrough fazem) incluem uma ação comum, `fund_equity_exposure` retorna os pcts esperados por security; holdings de dívida são excluídos; fundo sem look-through não aparece.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** reusando a decomposição existente.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Add fund→equity-security look-through exposure matrix`.

---

### Task 4: Constraint de overlap no otimizador

**Files:**
- Modify: `backend/app/services/portfolio_builder.py` (`run_optimize`, ~L502-622 onde cap/constraints e solvers são montados; `_resolve_block_budgets` ~L221)
- Modify: `backend/app/schemas/builder.py` (`ConstraintsIn`: novo `overlap_cap: float | None = None`)
- Test: `backend/tests/test_builder_overlap.py`

**Interfaces:**
- Consumes: `fund_equity_exposure` (Task 3), `engine.LinearConstraint` (Task 1).
- Produces: quando `constraints.overlap_cap` está setado, montar, para cada ação `s` presente em ≥1 fundo do conjunto final, o vetor `coef_s` de tamanho n onde `coef_s[i] = h_{fundo_i, s}` (pct do fundo i na ação s) e `coef_s[i] = 1` se o ativo i É a própria ação s (holding direto); então `LinearConstraint(coef_s, hi=overlap_cap)`. **Poda:** só gerar a constraint para ações onde `sum(coef_s) > overlap_cap` (as únicas que podem ser violadas). Passar `linear=[...]` aos solvers. Best-effort: fundos sem exposição contribuem 0.

**Comportamento:** vale em ambos os modos (explícito e amplo — no amplo, sobre os representantes já selecionados). Holdings diretos de equity (ativo que é uma ação) entram com coef 1 na sua própria constraint. Documentar a limitação (fundos sem N-PORT). Se nenhuma ação ultrapassa a poda, nenhuma constraint é adicionada (no-op).

- [ ] **Step 1: Teste falhando** — universo com 3 fundos, 2 deles com 30% e 40% (look-through) na mesma ação X; `overlap_cap=0.10`; otimizar e afirmar que a exposição agregada a X (`Σ w_fundo·h_fundo,X`) no resultado é `≤ 0.10+1e-6`. Sem `overlap_cap`, a exposição passa de 0.10 (controle).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** montagem dos coeficientes + poda + wiring.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Enforce per-equity look-through overlap cap as a hard solver constraint`.

---

### Task 5: Save — persistir constraints + inception + materializar NAV

**Files:**
- Modify: `backend/app/schemas/builder.py` (`SaveRequest`: `constraints: ConstraintsIn | None = None`, `inception_date: date | None = None`)
- Modify: `backend/app/services/builder_save.py` (`run_save`)
- Test: `backend/tests/test_builder_save_route.py` (+ unit em `test_builder_save.py` se existir)

**Interfaces:**
- Consumes: `portfolio_constraints.upsert_constraints` (Task 2), `portfolio_ledger.materialize_portfolio_nav` (existe, `portfolio_ledger.py:370`).
- Produces: `run_save` passa a (a) gravar `cap`/`min_weight`/`overlap_cap`/class limits em `portfolio_constraints`; (b) setar `inception_date` (payload ou hoje); (c) criar uma `PortfolioTransaction` de inception (buy) por posição na `inception_date` com quantidade/preço usados na sizing; (d) `await materialize_portfolio_nav(session, portfolio.id)` após flush.

**Investigação obrigatória (implementer):** verifique se `portfolio_crud.create_portfolio` já cria transações; se cria, não duplicar — apenas materializar. Os pesos-alvo (baseline da Sprint C) são exatamente os `weights` do `SaveRequest`; persistí-los virá no início da Sprint C — aqui NÃO criar tabela de target weights (YAGNI até a Sprint C precisar). Garantir que a NAV materializada no inception não quebre quando preços de referência faltarem (o save já trata preço ausente como 422).

- [ ] **Step 1: Testes falhando** — save com `constraints` persiste o conjunto (consultável via service); `inception_date` setado no portfólio; após o save existe ≥1 linha em `portfolio_nav_daily` (NAV materializada). Caminho sem constraints continua funcionando.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** no `run_save` + schema.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Persist constraints, set inception, and materialize NAV on builder save`.

---

### Task 6: Endpoints CRUD de constraints

**Files:**
- Modify: `backend/app/api/routes/portfolios.py` (ou o módulo de rotas de portfólio; localizar) — `GET /portfolios/{id}/constraints`, `PUT /portfolios/{id}/constraints`
- Modify: `backend/app/schemas/portfolios.py` (schemas de entrada/saída dos constraints)
- Test: `backend/tests/test_portfolios_constraints_route.py`

**Interfaces:**
- Consumes: `portfolio_constraints.get_constraints/upsert_constraints`.
- Produces: `GET` retorna o conjunto persistido (ou defaults vazios/404 conforme o padrão das outras rotas de portfólio); `PUT` valida (`0 ≤ min ≤ max ≤ 1`, `0 < cap ≤ 1`, `0 < overlap_cap ≤ 1`) e faz upsert. Seguir o padrão de auth/tenancy das rotas de portfólio existentes (provavelmente exige `get_current_user`, como `/save`).

- [ ] **Step 1: Testes falhando** — `PUT` grava e `GET` reflete; validação rejeita `min>max` (422); portfólio inexistente → 404.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** rotas + schemas.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** `Add GET/PUT portfolio constraints endpoints`.

---

### Task 7: Frontend — constraints no builder e na página do portfólio

**Files:**
- Modify: `frontend/src/components/builder/BuilderView.tsx` (seção Goal & Guardrails: inputs min/max por classe + campo overlap cap; enviar em `constraints` no optimize e no save)
- Modify: `frontend/src/lib/api/client.ts` (incluir `overlap_cap`/`block_budgets`/`constraints` no payload; chamadas `getPortfolioConstraints`/`putPortfolioConstraints`)
- Modify: página do portfólio (`frontend/src/app/portfolio/page.tsx` + nova seção `PortfolioConstraintsSection.tsx`) — exibir/editar constraints
- Regenerar tipos: `backend/openapi.json` (script `scripts/export_openapi.py`) + `pnpm run types`
- Test: vitest para a seção nova e para o envio dos constraints

**Interfaces:**
- Consumes: `GET/PUT /portfolios/{id}/constraints`; campos novos do `OptimizeRequest`/`SaveRequest`.
- Produces: UI para definir min/max por classe + overlap cap no builder (enviados na otimização e no save) e uma seção editável no portfólio (`PUT`).

- [ ] **Step 1: Testes falhando** — builder envia `constraints` (com `overlap_cap` e `block_budgets`) no optimize; `PortfolioConstraintsSection` carrega via `GET`, edita e salva via `PUT` (mock).
- [ ] **Step 2: Rodar e ver falhar** (`cd frontend && pnpm test`).
- [ ] **Step 3: Implementar** UI + client + tipos regenerados.
- [ ] **Step 4: Rodar e ver passar** + `pnpm run typecheck`.
- [ ] **Step 5: Commit** `Add constraints UI in builder and portfolio page`.

---

### Task 8: Gate verde da Sprint B

- [ ] **Step 1: Backend** `cd backend && .venv/Scripts/python -m pytest -q` → verde (ou só falhas pré-existentes conhecidas).
- [ ] **Step 2: ruff/mypy** nos arquivos da Sprint B.
- [ ] **Step 3: Frontend** `pnpm test && pnpm run typecheck && pnpm build`.
- [ ] **Step 4: Commit** de ajustes de gate, se houver.

## Self-Review (cobertura da spec §5)
- §5.1 block budgets em todos os objetivos → Task 1.
- §5.2 overlap constraint dura por ação (equity, poda, best-effort) → Tasks 3 (matriz) + 4 (constraint).
- §5.3 persistência dos constraints → Tasks 2 (tabelas) + 5 (gravar no save) + 6 (CRUD).
- §5.4 NAV synth no save (inception + pesos iniciais) → Task 5. Baseline de pesos-alvo: os `weights` do save são o baseline; a persistência explícita do alvo entra na Sprint C (evita YAGNI aqui).
- §5.5 frontend → Task 7.
- §5.6 testes → embutidos + Task 8.
