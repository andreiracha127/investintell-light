# Migração do FastAPI para o Railway + persistência dinâmica no TimescaleDB

- **Data:** 2026-06-13
- **Status:** Design aprovado (aguardando revisão do spec)
- **Branch:** `feat/railway-timescaledb-migration`
- **Autor:** Andreicr1 + Claude (Opus 4.8)

---

## 1. Contexto e motivação

Hoje o FastAPI quant engine do Investintell Light roda no **InsForge compute** (container Docker que escala a zero — `backend/Dockerfile`), com Auth/RLS gerenciados pelo InsForge à frente da aplicação. O catálogo de fundos é servido a partir de **tabelas-snapshot** (`funds`, `fund_risk_latest`, `fund_nav`, `fund_holdings`, `fund_classes`) materializadas diariamente pelo cron Railway `fund-catalog-sync` (`scripts/sync_funds.py` → `app/sync/funds.py`).

O objetivo desta migração:

1. Mover o FastAPI para o **Railway** como serviço always-on, eliminando o cold start do scale-to-zero do InsForge (causa de latência diagnosticada — listagens medem 8–12 ms no banco; o atraso percebido é o cold start, não SQL).
2. Manter a **autenticação vinculada ao InsForge**, validando os JWTs localmente no FastAPI (que hoje **não valida token nenhum** — confia no gateway do InsForge).
3. Trocar a persistência por **consultas dinâmicas de alta performance** ao TimescaleDB, **eliminando os snapshots estáticos** do `sync_funds.py`.
4. Preparar o terreno para **Highcharts Stock**, com saída JSON em arrays nativos de `[timestamp, valor]`.

### Descoberta que reduz o risco

O mirror (snapshots) **e** as tabelas-fonte vivem no **mesmo banco Tiger** (`Investintell-Prod` `t83f4np6x4`, `us-west-2`, schema `public`). O `sync_funds.py` não copia entre bancos — materializa dentro do próprio Tiger. Portanto, "decomissionar o snapshot" **não é migração cross-database**: é reescrever o SQL do catálogo para ler as fontes diretamente, no mesmo engine SQLAlchemy.

---

## 2. Estado atual (verificado)

### Engines / configuração
- `app/core/db.py` → `create_async_engine(settings.database_url)` — engine primário. Em produção `DATABASE_URL` aponta para o Tiger (`public`).
- `app/core/datalake.py` → engine lazy read-only sobre `settings.datalake_db_url` (mesmo Tiger), usado só pelo look-through.
- `app/core/config.py` → `Settings`: `database_url`, `datalake_db_url`, `tiingo_token`, `redis_url`, `cors_allow_origins`, etc. **Nenhuma configuração de InsForge/Auth.**

### Modelos (`app/models/fund.py`) — alvos do decomissionamento
| Modelo | Tabela | Fonte dinâmica equivalente (mesmo Tiger) |
|---|---|---|
| `Fund` | `funds` | `instruments_universe` (type='fund') ⋈ `strategy_reclassification_stage` (labels) ⋈ `sec_registered_funds`/`sec_money_market_funds` (fees/AUM) |
| `FundRiskLatest` | `fund_risk_latest` | `fund_risk_metrics` (última `calc_date` por instrumento, `organization_id IS NULL`) |
| `FundNav` | `fund_nav` | `nav_timeseries` (histórico completo) + `cagg_nav_monthly` |
| `FundHolding` | `fund_holdings` | `sec_nport_holdings` (última report_date por série) |
| `FundClass` | `fund_classes` | `sec_fund_classes` |

### Serviço de catálogo (`app/services/funds_catalog.py`)
- `build_funds_select` / `filter_conditions` / `SORT_WHITELIST` — lista paginada `Fund LEFT JOIN FundRiskLatest`, com whitelist de sort (gate de injeção) e exclusão incondicional de `Unclassified`.
- `fetch_fund_profile` — Fund + risco + NAV 2a decimado em Python (`decimate_nav`, alvo ~260 pts) + holdings top-50 + share classes.

### Rotas de séries (`app/api/routes/stocks.py`)
- `GET /stocks/{ticker}/prices` → `eod_prices` (objeto `PricePoint`).
- `GET /stocks/{ticker}/history` → OHLCV ajustado como **array de objetos** `{t,o,h,l,c,v}` (epoch ms). Resample semanal/mensal é client-side.
- `GET /stocks/{ticker}/analysis`, `/news`, `/overview`.

### TimescaleDB (Tiger `t83f4np6x4`)
- Hypertables relevantes: `eod_prices`, `nav_timeseries`, `fund_risk_metrics`, `sec_nport_holdings`, `benchmark_nav`, `intraday_market_ticks`.
- CAGGs existentes: `cagg_nav_monthly` (mensal sobre `nav_timeseries`), `cagg_nport_series_profile`. **Nenhum CAGG sobre `eod_prices`.**
- `eod_prices(ticker, date, open, high, low, close, volume, adj_open, adj_high, adj_low, adj_close, adj_volume, div_cash, split_factor)`.
- `nav_timeseries(instrument_id uuid, nav_date, nav, return_1d, aum_usd, currency, source, return_type)`.

### Auth
- **Não há validação de token no FastAPI.** A proteção atual é o gateway do InsForge + CORS (`cors_allow_origins`). `app/core/cache.py::CatalogCacheMiddleware` já distingue rotas **públicas de catálogo** (cacheadas) de **dados de usuário** (nunca cacheados) — fronteira reaproveitada para a auth.

---

## 3. Objetivos e não-objetivos

### Objetivos
- Serviço FastAPI deployável no Railway (config + Dockerfile), always-on.
- Validação local de JWT do InsForge (RS256/JWKS) nas rotas de dados de usuário.
- Catálogo de fundos e séries servidos por consultas dinâmicas ao Tiger (VIEW + MATERIALIZED VIEW + CAGGs), sem snapshots do `sync_funds.py`.
- Novos endpoints de timeseries com saída array-nativa para Highcharts Stock.

### Não-objetivos (desta rodada)
- **Não** executar o deploy/flip do serviço Railway (entregar runbook).
- **Não** migrar o data lake (já está no Tiger).
- **Não** reescrever o frontend ECharts → Highcharts (apenas preparar o backend).
- **Não** dropar tabelas-snapshot (renomear para `_deprecated`, validar paridade primeiro).
- **Não** tocar nos workers do Railway além do passo de `REFRESH` da MV.

### Fronteira de execução desta rodada
- **Escrevo** todo o código, migrations/SQL, testes e o runbook.
- **Executo** o DDL aditivo no Tiger de produção (VIEWs/MVs/CAGGs — não destrutivo, reversível).
- **NÃO** faço deploy no Railway nem flip de tráfego.

---

## 4. Decisões arquiteturais

### D1 — "Métricas latest por fundo": MATERIALIZED VIEW (Abordagem B)
`fund_risk_latest` deixa de ser snapshot copiado pelo `sync_funds.py` e passa a ser uma **MATERIALIZED VIEW** no Tiger:
```sql
CREATE MATERIALIZED VIEW fund_risk_latest_mv AS
SELECT DISTINCT ON (instrument_id) *
FROM fund_risk_metrics
WHERE organization_id IS NULL
ORDER BY instrument_id, calc_date DESC;
CREATE UNIQUE INDEX ON fund_risk_latest_mv (instrument_id);
```
Refrescada por `REFRESH MATERIALIZED VIEW CONCURRENTLY fund_risk_latest_mv` ao fim do worker `risk_metrics` (que **já roda diário** no Railway). Mantém latência de ms; é DB-nativo; sempre coerente com o último cálculo; sem cópia cross-DB.

**Rejeitadas:** VIEW pura `DISTINCT ON` (varre ~4.500 linhas por request ao filtrar/ordenar a lista) e tabela+trigger (mesmas peças móveis sem ganho).

### D2 — `funds` vira VIEW
`funds` passa a ser uma **VIEW** sobre `instruments_universe (instrument_type='fund')`, com a mesma cascata de classificação/fees/AUM que o `sync_funds.py` aplica hoje, expressa em SQL. (Baixa cardinalidade, sem métricas pesadas → VIEW basta; não precisa materializar.)

### D3 — CAGGs novos para downsample
- `cagg_eod_weekly`, `cagg_eod_monthly` sobre `eod_prices` (OHLC: `first(open)`, `max(high)`, `min(low)`, `last(close)`, `sum(volume)`; idem colunas `adj_*`).
- `cagg_nav_weekly` sobre `nav_timeseries` (`cagg_nav_monthly` já existe).
- Políticas `add_continuous_aggregate_policy` alinhadas à ingestão diária.

### D4 — Auth local, fronteira pública/privada
JWKS/RS256 verificado localmente; protege só rotas de dados de usuário; catálogo/timeseries seguem públicos (postura atual preservada).

### D5 — Compat de endpoints
`/prices` e `/history` permanecem; novos `/timeseries` saem no formato array Highcharts. Snapshots renomeados `_deprecated`, não dropados, até paridade confirmada.

---

## 5. Design detalhado por diretiva

### §1 — Deploy (`backend/railway.api.toml`) — NOVO arquivo
```toml
[build]
builder = "dockerfile"
[deploy]
startCommand = "uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port $PORT"
restartPolicyType = "always"
healthcheckPath = "/health"
healthcheckTimeout = 120
```
Apontado pelo serviço FastAPI via `railway_config_file` (mesmo padrão do `railway.livefeed.toml`). Não substitui o `railway.toml` existente (cron do sync, a ser aposentado na Fase 4).

**Env vars (runbook, não commitadas):** `DATABASE_URL`, `DATALAKE_DB_URL`, `INSFORGE_ISSUER`, `INSFORGE_JWKS_URL`, `INSFORGE_AUDIENCE`, `CORS_ALLOW_ORIGINS`, `TIINGO_TOKEN`, `REDIS_URL` (opcional).

### §2 — Persistência e CAGGs
- DDL aditivo (D1–D3) executado no Tiger nesta rodada, em transação, com rollback documentado.
- Modelos SQLAlchemy repontados: `FundRiskLatest.__tablename__ = "fund_risk_latest_mv"`; `Fund` aponta para a VIEW `funds`; `FundNav` deixa de existir como tabela própria — os reads de NAV passam por `nav_timeseries` (com nova projeção). `FundHolding`/`FundClass` apontam para VIEWs sobre `sec_nport_holdings`/`sec_fund_classes`.
- `funds_catalog.py`: `SORT_WHITELIST`/`filter_conditions`/`build_funds_select` mantêm a mesma superfície pública; só as colunas-fonte mudam. A whitelist de sort continua sendo o gate de injeção.

### §3 — Endpoints de timeseries (novos)
- `GET /stocks/{ticker}/timeseries?range=&interval=` → `eod_prices` (diário) | `cagg_eod_weekly` | `cagg_eod_monthly`.
- `GET /funds/{id}/timeseries?range=&interval=` → `nav_timeseries` (diário) | `cagg_nav_weekly` | `cagg_nav_monthly`.
- Seleção de granularidade por `range`: `≤1A` diário, `1–5A` semanal, `>5A` mensal. Downsample no banco (CAGG) — sem `decimate_nav` em Python. Payload limitado por design.

### §4 — Auth (`app/core/auth.py` — novo)
- `HTTPBearer` → decode RS256 com JWKS cacheado (TTL + refresh on `kid` miss), valida `iss`/`exp`/`aud`, extrai `sub` e claims de org.
- Dependência `get_current_user` aplicada a `/portfolios*`, builder save e posições salvas. Catálogo/`/stocks/*`/`/screener`/`/funds` (lista) seguem públicos.
- Falha-fechado: rota protegida sem token válido → `401`; JWKS indisponível → `503`.
- Novas settings em `config.py`: `insforge_issuer`, `insforge_jwks_url`, `insforge_audience`.

### §5 — Formato Highcharts (`app/schemas/timeseries.py` — novo)
- Linha: `[[t_ms, value], …]`; OHLC: `[[t_ms, o, h, l, c], …]`; volume: `[[t_ms, v], …]`. `t_ms` = epoch ms UTC.
- Endpoints `/timeseries` retornam esse formato; `/prices` e `/history` permanecem para compat até a migração do frontend.

---

## 6. Estratégia de testes (TDD)

- **Unit (puro):** builders de SQL repontados (filtros/sort), seleção de CAGG por `range`, serializers Highcharts (arrays), verificação de JWT com tokens forjados por chave de teste (válido/expirado/`kid` desconhecido/aud errada).
- **Integração (contra Tiger):** paridade mirror vs. dinâmico — mesma lista (contagem + ordenação) e mesmo perfil para uma amostra de instrumentos; CAGGs retornam OHLC coerente com o cru.
- **Regressão:** os ~710 testes atuais permanecem verdes; rotas protegidas ganham casos `401`/`200`.

---

## 7. Fases e sequenciamento

| Fase | Entrega | Depende de |
|---|---|---|
| 0 | `railway.api.toml` + runbook de env vars | — |
| 1 | `app/core/auth.py` + settings + proteção das rotas de usuário + testes | — |
| 2 | DDL (MV/VIEWs/CAGGs) no Tiger + modelos repontados + `funds_catalog` dinâmico + testes de paridade | — |
| 3 | Endpoints `/timeseries` + schemas Highcharts + testes | 2 |
| 4 | Aposentar `sync_funds.py`/`railway.toml` do cron + renomear snapshots `_deprecated` + `REFRESH` no worker `risk_metrics` | 2, 3 estáveis |

---

## 8. Riscos e rollback

| Risco | Mitigação |
|---|---|
| DDL em prod quebra leitura atual | DDL é **aditivo** (novos nomes `_mv`/`cagg_*`); snapshots originais intactos até Fase 4; rollback = `DROP` dos objetos novos |
| MV defasada vs. snapshot | `REFRESH CONCURRENTLY` ao fim do worker diário; staleness exposto na API (como hoje) |
| Paridade dinâmico ≠ snapshot | Testes de paridade (Fase 2) bloqueiam o decomissionamento (Fase 4) |
| Auth nova bloqueia usuários | Fronteira conservadora (só dados de usuário); falha-fechado só nas rotas protegidas; catálogo intacto |
| Deploy Railway | Fora desta rodada; runbook revisável antes do flip |

---

## 9. Questões em aberto

Nenhuma — defaults D1–D5 aprovados. O mecanismo exato de JWKS do InsForge (URL/issuer/aud) será descoberto na Fase 1 e registrado no runbook; se o InsForge expuser apenas HS256, a Fase 1 reavalia para segredo compartilhado (decisão de fallback documentada, não bloqueante para o spec).
