# Dispatch — API Latency Tail Fix (Tiingo sync I/O off the request path)

**Date:** 2026-06-16
**Repo:** `E:\investintell-light`
**Service under test:** Railway `api` (`6c7ae990-2751-466e-89d0-5b94c72f4679`), URL `https://api-production-2b6d.up.railway.app`
**Purpose:** eliminar a **cauda** de latência da API (p90–p99 = 4–11 s) sem regredir a mediana (p50 = 67 ms). A causa-raiz é ingestão Tiingo **síncrona no caminho da request** (`ensure_eod`/`ensure_news`), não o que as 5 recomendações originais apontavam.

---

## Diagnóstico (medido, não suposto)

Toda a investigação foi empírica. Topologia atual (pós-flip 2026-06-14): API no **Railway**, DB no **TimescaleDB Cloud** `t83f4np6x4` (`us-west-2`, porta **direta** 33132 — sem pooler), Redis **interno do Railway** (`redis.railway.internal`). O InsForge compute está `stopped` e fora do caminho de dados.

Percentis de resposta medidos no edge do Railway (`http_response_time`, 400 reqs):

| Métrica | Valor |
|---------|-------|
| p50 | **67 ms** |
| p90 | **4 372 ms** |
| p95 | **8 882 ms** |
| p99 | **11 138 ms** |

Medições por rota (cliente local → Railway; o piso de ~0,45 s de ttfb é distância cliente→edge, não servidor):

| Rota | miss | hit | cacheada? |
|------|------|-----|-----------|
| `/health` | 0,65 s (`cache:redis`, `database:ok`) | — | — |
| `/funds` | 0,80 s | 0,59 s | sim (`x-cache` ok) |
| `/stocks/overview` | **2,83 s** | 0,59 s | sim |
| `/stocks/SPY/analysis` | ~1,5 s (consistente em 3 runs) | — | **não** |

**Conclusão:** infra saudável (p50 baixo prova DB próximo, Redis ativo, cache funcionando). O problema é **cauda bimodal**: rápido quando os dados estão quentes (`fresh`), segundos quando um ticker cruza o limiar de staleness e a request do usuário paga o fetch Tiingo síncrono.

Mecânica confirmada no código:
- `app/ingestion/service.py::ensure_eod_data` classifica tickers em `fresh` / `stale` / `cold` (`classify_tickers`). **`fresh` é pulado** (→ p50 de 67 ms). `stale` → fetch incremental síncrono; `cold` → full-history síncrono (cap `max_cold_tickers_per_request`).
- O fetch roda **dentro do handler**, segurando a conexão do pool durante I/O de rede externa + rate-limit Tiingo.
- Rotas afetadas (chamam `ensure_eod_or_http_error` / `ensure_news` no path): `/stocks/{ticker}/prices|history|timeseries|analysis|news`, `/stocks/overview` (4 `INDEX_TICKERS`), `/funds/{id}/history` (ETFs).

**Amplificador:** `app/core/db.py` usa `create_async_engine(..., pool_pre_ping=True)` sem `pool_size`/`max_overflow`/`pool_timeout` explícitos. `pre_ping` adiciona +1 RTT por checkout; sob rajada, requests rápidas (cache hit) enfileiram atrás das presas em Tiingo → a cauda chega a 11 s.

**Descartado por evidência:** cold-start/hibernação (`Application startup complete` aparece **1×** às 01:03 e não se repete — sem reboots); Redis caindo p/ memória (`/health` = `redis`); DB cross-region dominante (p50=67 ms refuta); queries de DB lentas (idem).

---

## Reavaliação das 5 recomendações originais

| # | Recomendação | Veredito |
|---|--------------|----------|
| 1 | Redis timeout 0,5 s → 2 s | **Não fazer.** `/health`=`redis`: Redis sadio e interno. Sem fallback p/ memória acontecendo. Timeout maior só piora o fail-open futuro. |
| 2 | Adicionar `/stocks/` ao cache | **Perigoso como está.** `/stocks/` pegaria `/stocks/{ticker}/news` (tem `stale`, muda) — viola a regra do módulo. Só cache **cirúrgico** de `/stocks/{ticker}/analysis` (Task 5, opcional). |
| 3 | `/funds` faz 2 queries / índices | **Não-problema.** `fetch_funds` usa `count().over()` (1 query); `fetch_staleness` já tem cache in-process 300 s; e `/funds` inteiro é cacheado. p50 já é baixo. |
| 4 | Warm de índices em background | **Correto** — é um caso da causa-raiz (Task 2). |
| 5 | Pool `pool_size=20` | **Alavanca errada.** Pool maior não cura latência de request único; reenquadrado para `pre_ping`/timeouts (Task 3). |

Números de impacto da análise original (-30 %, -50 %, "2,6 s") não vieram de medição e não batem (`analysis`≈1,5 s; `overview`-miss≈2,8 s). Ignorar; validar tudo por `http_response_time` antes/depois.

---

## Decisões do dono (resolver ANTES da execução)

1. **Estratégia de frescor.**
   - **A (ponte, código no app):** stale-while-revalidate — `stale` serve o DB na hora e dispara refresh em background; `cold` permanece síncrono com deadline. Entregável rápido.
   - **B (destino, arquitetural):** um worker/cron do datalake mantém o universo quente; rotas viram **DB-first puras**; `ensure` on-demand só para `cold` absoluto. Alinha com a doutrina registrada ("workers ingerem/computam, o app só lê").
   - Recomendação: fazer **A agora**, planejar **B** depois. Confirme.
2. **Comportamento de `cold` ticker** (sem dado nenhum): bloquear-com-deadline-curto (mantém contrato atual, com teto) **ou** responder 202/placeholder e buscar em background. Recomendação: bloquear-com-deadline.
3. **Task 5 (cache de `analysis`)**: aplicar ou deixar fora. Recomendação: deixar fora até A estabilizar (o cache mascara, não corrige).

---

## Current Baseline

- branch: `main`
- Untracked não relacionados a preservar:
  - `.idea/AugmentWebviewStateStore.xml`
  - `backend/_gate_vs_full_backtest.py`
  - `backend/_navdata.csv`
  - `backend/_navdata.err`
  - `docs/dispatch-highcharts-p2-price-stock-execution.md`
  - `docs/superpowers/plans/2026-06-13-highcharts-grid-plan4-universe-checkbox.md`
- Este dispatch: `docs/dispatch-api-latency-tail-fix.md`

## Preserve Dirty Work

Antes de qualquer trabalho:

```powershell
git status --short --branch
```

Preserve os untracked acima. Não faça `stash`/`reset`/`clean` no worktree primário sem o dono pedir.

## Recommended Execution Surface

Worktree limpo (este é um trabalho de backend isolado):

```powershell
git worktree add E:\investintell-light-latency -b fix/api-latency-tail HEAD
cd E:\investintell-light-latency
git status --short --branch
```

Se o nome de branch já existir, use um único (ex.: `fix/api-latency-tail-2`).

## Read First

No worktree limpo, leia:

1. `AGENTS.md` (ou `CLAUDE.md`) — convenções
2. `backend/app/ingestion/service.py` — `ensure_eod_data`, `ingest_one_ticker`, `classify_tickers`, `incremental_start`, `full_history_start`
3. `backend/app/api/_shared.py` — `ensure_eod_or_http_error`, `raise_news_fetch_error`
4. `backend/app/api/routes/stocks.py` — `get_market_overview`, `get_stock_analysis`, `*timeseries/history/prices/news`
5. `backend/app/api/routes/funds.py` — `get_fund_history`
6. `backend/app/core/db.py` — engine/pool
7. `backend/app/core/cache.py` — middleware e prefixos
8. `backend/app/ingestion/news.py` — `ensure_news`
9. `backend/app/core/config.py` — `eod_staleness_hours`, `max_cold_tickers_per_request`, `news_fetch_limit`, `catalog_cache_ttl_seconds`

Repo manda sobre qualquer snippet deste dispatch.

## Required Opening Verification

```powershell
rg -n "pool_pre_ping|pool_size|max_overflow|pool_timeout|pool_recycle" backend/app/core/db.py
rg -n "ensure_eod_or_http_error|ensure_news|BackgroundTasks" backend/app/api/routes/stocks.py backend/app/api/routes/funds.py
rg -n "classify_tickers|needs_fetch|fresh|stale|cold" backend/app/ingestion/service.py
```

Esperado na criação do dispatch: `db.py` só com `pool_pre_ping=True`; rotas chamando `ensure_*` síncrono e **sem** `BackgroundTasks`; `service.py` com a classificação `fresh/stale/cold` e `fresh` pulado.

## Scope

Backend apenas. Tirar I/O Tiingo síncrono do caminho da request e blindar o pool, preservando o contrato fail-loud existente (404 ticker desconhecido, 503 rate-limit, 502 provider, 422 cold-cap).

## Non-Scope

- Sem mudanças de frontend.
- Sem trocar o provedor de dados.
- **Não** aplicar as recs 1 e 3; **não** usar `/stocks/` blanket no cache.
- Sem deploy sem pedido explícito do dono (após verde local).
- Sem redesenho das rotas além do necessário para mover o `ensure` de lugar.

---

## Execution Tasks (TDD)

> Regra de cada task: escrever o teste que falha → implementar → `pytest` verde + `mypy`/`ruff` limpos. Comandos rodam de `backend/`.

### Task 0 — Observabilidade por rota (medir antes/depois)

Adicionar um middleware/logger que registra duração por rota (path + ms) para correlacionar com `http_response_time`. Capturar o baseline ANTES das mudanças e re-medir ao final.

- Arquivo: `backend/app/core/` (novo middleware leve) + wiring no app factory.
- Teste: o log/coletor emite a duração para uma rota de exemplo.

```powershell
cd backend; pytest -q app/tests/ -k timing; ruff check .; mypy app
```

### Task 1 — Stale-while-revalidate no `ensure_eod` (CORE)

Para tickers **`stale`** (já existem no DB, só velhos): servir os dados atuais imediatamente e disparar o refresh incremental **fora do request** (FastAPI `BackgroundTasks` na Estratégia A). Tickers **`fresh`**: inalterado. **`cold`**: comportamento por Decisão do Dono #2 (default: síncrono com deadline da Task 4).

Implementação (Estratégia A):
- Separar "o que precisa de fetch e bloqueia" (`cold`) de "o que pode revalidar depois" (`stale`) em `ensure_eod_data` (ou num novo entry-point `ensure_eod_swr`).
- As rotas passam um `BackgroundTasks` e agendam o refresh `stale`; o handler não espera.
- Riscos a tratar explicitamente (cobrir em teste): (a) o background task precisa de **sessão de DB nova** (a da request fecha); (b) o **rate-limit Tiingo é por-processo** — não dispare N refreshes simultâneos sem coalescer; (c) **deduplicar** refresh concorrente do mesmo ticker (flag/lock "refresh in flight") para não enfileirar fetches duplicados.

Testes (mock do `TiingoClient` com latência artificial):
- ticker `stale` + Tiingo lento → resposta retorna **rápido** com os dados existentes; o refresh roda depois.
- ticker `cold` → ainda busca (ou 202, conforme decisão) e fail-loud preservado.
- ticker `fresh` → zero chamadas Tiingo (inalterado).
- erros Tiingo no background **não** derrubam a request já enviada.

```powershell
cd backend; pytest -q app/tests/ -k "ensure or ingest or stale"; ruff check .; mypy app
```

### Task 2 — Background warm dos índices em `/stocks/overview`

Os 4 `INDEX_TICKERS` nunca devem bloquear o overview (já é cacheado; o miss paga ~2,8 s hoje). Mover o `ensure` dos índices para background (reusa o mecanismo da Task 1); a rota serve `indices=[]`/últimos conhecidos sem esperar, mantendo a degradação já documentada.

- Arquivo: `backend/app/api/routes/stocks.py::get_market_overview`.
- Teste: Tiingo lento nos índices → `/stocks/overview` retorna sem bloquear; índices populam no próximo hit.

```powershell
cd backend; pytest -q app/tests/ -k overview; ruff check .; mypy app
```

### Task 3 — Blindar o pool de conexões

Em `backend/app/core/db.py`:
- Remover `pool_pre_ping=True` (custa +1 RTT/req cross-region) e usar `pool_recycle` (ex.: 1800 s) + tratamento de conexão morta.
- Definir `pool_size`, `max_overflow` e **`pool_timeout` curto** explícitos para que um refresh travado não esgote nem bloqueie indefinidamente o checkout. Dimensionar com o teto de conexões do TimescaleDB Cloud (compartilhado com os workers) — **não** subir às cegas.

- Teste: a engine é criada com os parâmetros esperados (asserção de config); sanity de que uma query simples ainda roda.

```powershell
cd backend; pytest -q app/tests/ -k "db or engine or pool"; ruff check .; mypy app
```

### Task 4 — Deadline na chamada Tiingo síncrona inevitável

Onde o fetch síncrono permanece (`cold`, conforme decisão), envolver com `asyncio.timeout(...)` (deadline curto, ex.: 3–5 s) e mapear o estouro para a degradação/erro já existente (não pendurar a request). Garante **teto** na cauda mesmo no pior caso.

- Arquivos: `backend/app/api/_shared.py` (ou no client wrapper).
- Teste: Tiingo além do deadline → erro/degradação mapeado, request não excede o teto.

```powershell
cd backend; pytest -q app/tests/ -k "timeout or deadline or cold"; ruff check .; mypy app
```

### Task 5 — (Opcional, Decisão #3) Cache cirúrgico de `/stocks/{ticker}/analysis`

Somente se sancionado. Cachear **apenas** essa rota (não o prefixo `/stocks/`), com TTL curto e chave já incluindo `range`/`benchmark`/`window` (o `cache_key` atual ordena a querystring). **Nunca** tocar `/stocks/{ticker}/news`.

- Teste: 2ª chamada idêntica → `x-cache: hit`; `news` permanece sem cache.

---

## Verificação final (antes de declarar pronto)

```powershell
cd backend
pytest -q
ruff check .
mypy app
```

Depois (com o dono, se houver deploy): re-medir o edge e comparar com o baseline —

```text
http_response_time (service api): p90/p95/p99 devem cair de 4,4/8,9/11,1 s
para a casa de centenas de ms; p50 deve permanecer ~67 ms.
```

Critério de aceite: **p95 < 1 s** sob o mesmo padrão de tráfego, sem regredir o p50, e nenhuma rota perdendo o contrato fail-loud (404/503/502/422 preservados).

## Não fazer

- Não aumentar o timeout do Redis (rec 1).
- Não adicionar `/stocks/` (blanket) ao cache (rec 2).
- Não subir `pool_size` isoladamente como "cura" de latência (rec 5 — só dentro da Task 3).
- Não remover o `ensure` de `cold` sem a decisão do dono (quebraria tickers fora do universo).
