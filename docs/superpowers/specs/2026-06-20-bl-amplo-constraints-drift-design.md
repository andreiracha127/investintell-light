# Black-Litterman no universo amplo, constraints persistidos e monitor de drift/overlap

**Data:** 2026-06-20
**Branch:** `feat/bl-amplo-constraints-drift` (base: `fix/lookthrough-series-resolution`)
**Status:** Aprovado para implementação (autonomia delegada pelo dono)

## 1. Contexto e motivação

Hoje o Portfolio Builder só roda Black-Litterman (objetivos baseados em retorno) no modo **Ranked top-N**, limitado a `MAX_UNIVERSE_ASSETS = 50` ([`app/schemas/builder.py:98`](../../../backend/app/schemas/builder.py)). O modo **Broad → lean** (`broad_universe=True`) roda sobre todo o universo filtrado (até `MAX_UNIVERSE_CANDIDATES = 5000`), mas é "risk-structure-only" (gate G5): o schema bloqueia `bl_utility` e `max_return_cvar` no modo amplo ([`app/schemas/builder.py:232-257`](../../../backend/app/schemas/builder.py)).

A hipótese inicial ("falta o CLARABEL") foi **descartada**: o CLARABEL está instalado e é o solver primário (`engine.py:39: _SOLVER_LADDER = (cp.CLARABEL, cp.SCS)`). A limitação é de arquitetura, não de biblioteca. O repositório legado (`investintell-allocation`) roda BL sobre ~50–100 fundos pós-dedup (escala parecida com a do light) — a diferença real é um **pipeline assíncrono** de construção, não o número de fundos.

Decisão do dono: trazer a capacidade prática (BL sobre o universo amplo + constraints institucionais + monitoramento) sem replicar o over-engineering do legado (mandato/governance global, stress suite, validation gate de 18 checks, narrativa, lineage, SSE). Cada peça fica no mínimo viável.

## 2. Objetivos e não-objetivos

### Objetivos
- Permitir BL (objetivos baseados em retorno) no modo de universo amplo, usando **apenas o prior de equilíbrio** (sem views).
- Executar a otimização ampla de forma **assíncrona** (sem travar o request), com persistência mínima.
- Persistir, por portfólio, os **limites de construção**: cap por posição, mín por posição, mín/máx por classe de ativo, e teto único de exposição look-through por ação (overlap).
- Aplicar o teto de overlap como **constraint dura no otimizador** (apenas ações).
- Ao salvar um portfólio do builder, **sintetizar o NAV** (inception date + pesos iniciais), criando o baseline de pesos-alvo.
- **Monitorar** diariamente o drift (vs. alvo e vs. limites de classe) e trimestralmente o overlap, com **alertas in-app**.

### Não-objetivos (fora de escopo)
- Views por classe de ativo no modo amplo (registrado como extensão futura).
- Mandato/governance global, stress suite, validation gate institucional, narrativa Jinja2, lineage, SSE de progresso, alertas por e-mail.
- Overlap sobre crédito/renda fixa. O teto de overlap é **defesa de risco de mercado de ações apenas**; o risco de mercado de FI é capturado por duration/curva (features `empirical_duration`/`credit_beta` já existentes).

## 3. Arquitetura geral

Três sprints sequenciais sobre uma mesma branch. A entrega `A` é independente; `B` introduz os constraints persistidos e o NAV synth; `C` depende de `B` (limites + baseline de alvo) e da camada de rebalance já existente (`rebalance_policies`).

```
Sprint A  →  Sprint B  →  Sprint C
(BL amplo     (constraints +     (drift diário +
 + async)      overlap + NAV)     overlap trimestral)
```

Vocabulário fixo de classes (já existe, [`app/schemas/builder.py:84-86`](../../../backend/app/schemas/builder.py)):
`equity | fixed_income | cash | alternatives | multi_asset`.

---

## 4. Sprint A — Black-Litterman no universo amplo (execução assíncrona)

### 4.1 Destravar BL no modo amplo
- **Schema** ([`app/schemas/builder.py:232-257`](../../../backend/app/schemas/builder.py)): remover as duas validações que rejeitam `bl_utility`/`max_return_cvar` quando `broad_universe=True`. **Manter** a rejeição de *views* no modo amplo (views referenciam fundos que o usuário não escolhe).
- **Seleção** ([`app/optimizer/data.py:431` `select_universe_funds`](../../../backend/app/optimizer/data.py)): quando o objetivo é baseado em retorno, passar `require_aum=True` no Stage-1, garantindo `w_mkt` computável para todos os representantes.
- **Orquestrador** ([`app/services/portfolio_builder.py` `run_optimize`](../../../backend/app/services/portfolio_builder.py)): no caminho amplo, após o Stage-2 montar Σ, computar `w_mkt` sobre os K representantes (AUM normalizado) → `equilibrium()` → `solve_bl_utility`/`solve_max_return_cvar` com **zero views**. O backend já suporta `bl_utility` com zero views usando π diretamente (docstring `portfolio_builder.py:12`); é reaproveitar esse ramo no caminho amplo.

Resultado: no modo amplo, a alocação passa a considerar retorno+risco (pesos de mercado revertidos por risco, ajustados aos limites), em vez de só estrutura de risco.

### 4.2 Execução assíncrona
Tabela nova `optimize_jobs` (DDL em `backend/db/ddl/`, seguindo a convenção datada do projeto):

| coluna | tipo | papel |
|---|---|---|
| `id` | uuid PK | job_id devolvido ao cliente |
| `organization_id` | uuid | escopo/RLS (padrão do projeto) |
| `status` | text | `pending` / `running` / `succeeded` / `failed` |
| `request` | jsonb | o `OptimizeRequest` serializado |
| `result` | jsonb | o `OptimizeResponse` quando `succeeded` |
| `error` | text | mensagem verbatim quando `failed` |
| `created_at` / `updated_at` | timestamptz | tempo de vida |

- `POST /builder/optimize` ([`app/api/routes/builder.py:38-57`](../../../backend/app/api/routes/builder.py)): quando `universe.broad_universe = True`, insere o job (`pending`), dispara `asyncio.create_task` (mesmo padrão do legado), responde **202 + `{job_id}`**. Caminho explícito/ranked permanece **síncrono** (sem mudança para quem já usa).
- `GET /builder/optimize/{job_id}`: devolve `status` e, quando terminal, `result` ou `error`.
- O worker roda `run_optimize()` existente e grava o resultado no job. O estado vive na tabela (não em memória) → o polling funciona mesmo se a API rodar em múltiplos pods.

### 4.3 Frontend
- [`BuilderView.tsx`](../../../frontend/src/components/builder/BuilderView.tsx): no modo amplo, trocar o `useMutation` direto por: disparar o job (recebe `job_id`) → `useQuery` com `refetchInterval` (~1,5 s) em `/optimize/{job_id}` até status terminal → renderizar `result` no `ResultsPanel` existente, ou `error`. Indicador "otimizando…". Modo ranked inalterado. A forma do `OptimizeResponse` não muda.

### 4.4 Testes (TDD)
- Schema: objetivos BL aceitos no amplo; views ainda rejeitadas no amplo.
- Orquestrador amplo+BL: pesos coerentes com equilibrium e respeitando `cap`; `require_aum` exclui fundos sem AUM.
- Ciclo de job: `pending → running → succeeded`; caminho de erro → `failed` com mensagem verbatim.
- Frontend: fluxo de polling (mock do job até terminal).

### 4.5 Decisões assumidas
- Async **apenas no modo amplo** (ranked rápido continua síncrono).
- **Sem rotina de expurgo** de jobs antigos nesta sprint (YAGNI; registrar como extensão).

---

## 5. Sprint B — Constraints persistidos, overlap e NAV synth no save

### 5.1 Limites por classe de ativo em todos os objetivos
Hoje os `block_budgets` (Σ-peso por `asset_class` entre `lo`/`hi`) só são honrados pelo `min_cvar` ([`app/optimizer/engine.py` `BlockBudget`/`base_constraints`](../../../backend/app/optimizer/engine.py)). Estender essas restrições lineares a **todos** os objetivos convexos (`bl_utility`, `max_return_cvar`, `min_vol`, `erc`, `max_diversification`), de modo que valham também para o BL do Sprint A.

### 5.2 Constraint dura de overlap (apenas ações)
Para cada **ação final** `s` (security), adicionar a restrição linear ao solver:

```
Σ_fundos ( w_fundo · h_{fundo,s} )  +  exposição_direta_s   ≤   overlap_cap
```

- `h_{fundo,s}` = fração do NAV do fundo investida na ação `s`, via look-through N-PORT ([`app/services/lookthrough.py`](../../../backend/app/services/lookthrough.py), recém-melhorado com resolução child-series até ações).
- **Apenas holdings de equity** entram (filtra dívida/caixa dentro dos fundos).
- `overlap_cap` é um **teto único por portfólio** (ex.: "nenhuma ação > X% via look-through").
- **Fundos sem N-PORT** contribuem 0 para o somatório (não há look-through) — limitação documentada; aceitável para ações US, onde a cobertura N-PORT é alta.
- **Escala:** gerar constraint apenas para ações cuja exposição agregada *máxima possível* exceda o teto (poda), mantendo o problema enxuto para o cvxpy.
- A constraint vale tanto no modo explícito quanto no amplo (no amplo, sobre os representantes selecionados no Stage-1).

Este teto é **complementar** ao `cap` por posição (máx por ativo direto que você detém — atende a regra UCITS de 10% por posição) e ao `min_weight` por posição. Ambos preservados.

### 5.3 Persistência dos constraints
Tabela nova `portfolio_constraints` (DDL em `backend/db/ddl/`), espelhando o padrão de [`rebalance_policies`](../../../backend/app/models/rebalance.py):

- **Limites por classe** — uma linha por `(portfolio_id, asset_class)` com `min_weight`/`max_weight`.
- **Caps escalares por portfólio** — `cap` (máx por posição), `min_weight` global opcional, `overlap_cap` (teto de overlap). Guardados em colunas escalares numa tabela-cabeçalho `portfolio_constraint_set` (1:1 com `portfolio_id`), com as linhas por classe referenciando-a. (Decisão de modelagem fina: cabeçalho escalar + linhas por classe; resolver detalhes de FK/cascade na implementação.)
- `created_at` / `updated_at`; cascade em `ON DELETE` do portfólio.

Ao `POST /builder/save` ([`app/services/builder_save.py:241-346`](../../../backend/app/services/builder_save.py)): gravar o conjunto de constraints usado na otimização. `GET`/`PUT /portfolios/{id}/constraints` para edição posterior na tela do portfólio.

### 5.4 NAV synth no save (inception + pesos iniciais)
Ao transformar o resultado do builder em portfólio, além de criar posições, **acionar o sintetizador de NAV** ([`app/services/portfolio_ledger.py`](../../../backend/app/services/portfolio_ledger.py) `build_transaction_nav`/`materialize_portfolio_nav`; worker [`app/jobs/workers/portfolio_nav_daily.py`](../../../backend/app/jobs/workers/portfolio_nav_daily.py)):
- Registrar `inception_date` com os pesos iniciais de cada ativo (transações de inception no ledger imutável).
- Materializar a NAV a partir do inception.
- Persistir os **pesos-alvo** (snapshot dos pesos da otimização) — baseline para o drift da Sprint C. Persistir junto ao conjunto de constraints (ou tabela irmã `portfolio_target_weights` por `(portfolio_id, asset_ref)`); decisão fina na implementação, mantendo a regra: alvo = pesos no inception.

### 5.5 Frontend
- Builder (seção *Goal & Guardrails*): inputs de mín/máx por classe + campo de teto de overlap, além do `cap`/`min_weight` por posição já existentes.
- Página do portfólio: seção editável de constraints (chama `PUT /portfolios/{id}/constraints`).

### 5.6 Testes (TDD)
- Engine: block budgets honrados por cada objetivo; constraint de overlap reduz exposição agregada de uma ação repetida em múltiplos fundos abaixo do teto; poda de ações irrelevantes não altera o ótimo.
- Overlap com fundo sem N-PORT: contribui 0 (sem crash).
- Save: persiste constraints; aciona NAV synth (inception_date setado, NAV materializada, pesos-alvo gravados).
- Endpoints CRUD de constraints (GET/PUT) com validação (0 ≤ min ≤ max ≤ 1).

---

## 6. Sprint C — Monitor de drift e overlap, alertas in-app

### 6.1 O que é vigiado
- **Diário:** (a) drift dos pesos atuais vs. pesos-alvo além das bandas de rebalance (`band_abs`/`band_rel` de [`rebalance_policies`](../../../backend/app/models/rebalance.py)); (b) breach dos limites de classe (Sprint B) pelos pesos atuais.
- **Trimestral** (na divulgação do N-PORT): exposição look-through agregada por ação excede o `overlap_cap` — mesmo tendo passado na construção, pode derivar com novos holdings/preços.

### 6.2 Pesos atuais e alvo
- Pesos **atuais**: derivados de posições + preços (já calculado em [`portfolio_crud.build_overview`](../../../backend/app/services/portfolio_crud.py)).
- Pesos **alvo**: baseline persistido no inception (Sprint B §5.4).

### 6.3 Workers
- `portfolio_drift_daily.py` (mesmo padrão de `portfolio_nav_daily.py`, agendado via cron após a materialização do NAV): compara pesos atuais vs. limites de classe e bandas de drift; grava o estado.
- Avaliação trimestral de overlap: reaproveita o look-through; pode ser um ramo do worker diário que só recomputa overlap quando há `report_date` novo de N-PORT, ou um worker `portfolio_overlap_quarterly.py` disparado pelo cron do `nport-lookthrough`. Decisão fina na implementação (preferir o ramo condicional para enxugar).

### 6.4 Estado e alertas
Tabela nova `portfolio_drift_status` (DDL em `backend/db/ddl/`): resultado da última avaliação por portfólio — lista de breaches (`type` ∈ `drift_band|class_limit|overlap`, alvo/limite violado, valor atual, severidade), `evaluated_at`.
- `GET /portfolios/{id}/alerts`: expõe o estado mais recente.
- Frontend: badge/lista de alertas na página do portfólio. **Sem e-mail, sem SSE.**

### 6.5 Testes (TDD)
- Worker diário: detecta breach de classe e drift de banda; portfólio dentro das faixas → sem alertas.
- Overlap trimestral: dispara quando a exposição agregada por ação excede o teto; idempotência da reavaliação.
- Endpoint de alertas: reflete o último estado gravado.

---

## 7. Riscos e limitações

- **Cobertura N-PORT no overlap:** fundos sem look-through contribuem 0 → a exposição agregada por ação pode ser subestimada. Documentado; aceitável para ações US. A constraint é best-effort sobre os fundos com look-through disponível.
- **Escala da constraint de overlap:** o número de ações finais pode ser grande; mitigado pela poda (só ações cuja exposição máxima possível excede o teto).
- **Latência do modo amplo:** mitigada pela execução assíncrona (Sprint A).
- **Multi-pod:** o estado de jobs vive na tabela `optimize_jobs`, não em memória → polling robusto.
- **Reconciliação de branch:** baseada em `fix/lookthrough-series-resolution`; quando esta entrar na main, os commits reconciliam pelos mesmos SHAs.

## 8. Modelo de dados — resumo das tabelas novas

| Tabela | Sprint | Conteúdo |
|---|---|---|
| `optimize_jobs` | A | jobs assíncronos de otimização (status/request/result/error) |
| `portfolio_constraint_set` | B | cabeçalho 1:1 por portfólio: `cap`, `min_weight`, `overlap_cap` |
| `portfolio_constraints` | B | linhas por `(portfolio_id, asset_class)`: `min_weight`/`max_weight` |
| `portfolio_target_weights` | B | baseline de pesos-alvo no inception (por `portfolio_id, asset_ref`) |
| `portfolio_drift_status` | C | resultado da última avaliação de drift/overlap por portfólio |

## 9. Sequenciamento e gates

Ordem: A → B → C. Cada sprint segue TDD e só é considerada concluída com o gate verde do projeto (typecheck, lint, testes backend e frontend, build). Commits atômicos por unidade lógica. Execução delegada a subagentes Opus 4.8.
