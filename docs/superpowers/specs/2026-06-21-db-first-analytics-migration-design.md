# DB-First — Migração de cálculo analítico do request path para o banco

Data: 2026-06-21
Status: design aprovado (aguardando revisão da spec antes do plano)
Branch base atual: `feat/bl-amplo-constraints-drift`

## 1. Problema e objetivo

O sistema lida com grandes volumes de dados, mas vários endpoints calculam payloads
analíticos pesados em tempo de request, em Python (`pandas`/`numpy`), no processo do
FastAPI. Isso coloca cálculo no caminho crítico de cada chamada e mantém o app server
fazendo trabalho que deveria ser do banco. O objetivo é **DB-First**: o backend deixa
de calcular no request e passa a **ler** resultados — de tabela/MV materializada
(quando o resultado é estável por entidade) ou de função SQL que executa o cálculo
dentro do Postgres (quando o resultado é paramétrico e interativo). O frontend
permanece como camada de renderização; nenhum cálculo de negócio novo é introduzido nele.

Não-objetivo de produto: este trabalho não altera números nem a semântica das métricas.
Cada resultado novo deve ter **paridade** com o cálculo atual antes da troca.

**Exceção deliberada — `active-share`**: há uma mudança de produto já decidida que
acompanha esta migração. O `active-share` deixa de aceitar seleção de benchmark e passa a
ser computado **apenas contra o benchmark primário** da série. Isso **não** é paridade —
é remoção intencional de capacidade (ver §6 A5 para o contrato e o cleanup). Todos os
demais endpoints permanecem sob a regra de paridade acima.

## 2. Princípios e não-objetivos

- Nenhum `pandas`/`numpy` no request path dos endpoints migrados.
- Reaproveitar o que já está materializado no TimescaleDB Cloud antes de criar
  qualquer tabela ou worker (ver Inventário, §4). Não duplicar materialização existente.
- Padrão de materialização idêntico ao já existente (`risk_metrics` →
  `fund_risk_metrics` → `fund_risk_latest_mv`): worker em
  `investintell-datalake-workers`, tabela base, `*_latest_mv`, `REFRESH ... CONCURRENTLY`.
- Cálculo paramétrico/interativo (range/window contínuos) fica como **função SQL**
  on-demand, não materializado — preserva flexibilidade sem explosão combinatória.
- Resultados determinísticos por parâmetros podem ser **cacheados** (Redis já deployado).
- Formato de materialização **híbrido**: escalares e listas chatas em colunas/linhas
  tipadas; estruturas de grafo/árvore em coluna `payload jsonb` com `schema_version`.

Já entregue (commit `38dbdb4`, "make historical market data db-first"): a leitura de
**histórico de mercado** de `stocks`, `funds`, `portfolio`, `portfolios`, `statistics` e
`monte_carlo` já é DB-first — o request path não chama mais o Tiingo (o
`ensure_eod_or_http_error` foi removido; `eod_prices`/`nav_timeseries` são populados por
backfill/warming worker out-of-band). `stocks/*` lê de `cagg_eod_daily` (continuous
aggregate diário com policy de auto-refresh) em todos os ranges (1M/6M/1Y/5Y/MAX). DDL do
DB principal passou a ser versionado em `backend/db/ddl/` (ex.:
`2026-06-21_cagg_eod_daily_timeseries.sql`).

Fora de escopo (permanecem como estão): `macro/regime` (já DB-first), e o frontend (apenas
formatação; `periodContributions` está inativo). As ferramentas analíticas interativas
(`statistics/*`, `monte-carlo/*`, `backtest/walk-forward`, `correlation-regime`) **não**
ganham MV universal, mas ganham aceleração (Grupo E).

## 3. Estado atual (o que cada endpoint calcula hoje)

Referências de código (no momento do design):

- `funds/{id}/analysis` → `app/services/fund_analysis.py` (growth-of-100, drawdown,
  rolling vol/sharpe, retornos mensais, histograma, VaR/CVaR, best/worst day). Params:
  `range` (1Y/3Y/5Y/MAX), `window` (10..252).
- `funds/{id}/entity-analytics` → `app/services/fund_dossier_tier_b.py` (sharpe/sortino/
  calmar/alpha/beta/tracking/info ratio, capture, distribuição, rolling returns,
  drawdown periods, insiders). Params: `window` (3M/6M/1Y/3Y/5Y), `benchmark_id`.
- `funds/{id}/risk-timeseries` → `fund_dossier_tier_b.py` (drawdown série + eventos).
- `funds/{id}/factors` → `fund_dossier_tier_b.py` (OLS de 6 fatores → betas/t-stat;
  z-scores cross-section de style bias). Sem params.
- `funds/{id}/style-drift` → `fund_dossier_tier_b.py` (agregação N-PORT por trimestre/
  setor). Param: `quarters`.
- `funds/{id}/institutional-reveal` → `fund_dossier_tier_b.py` (cruza N-PORT × 13F,
  monta rede). Sem params.
- `funds/{id}/active-share` → `fund_dossier_tier_b.py` (`0.5·Σ|Δw|` vs benchmark).
  Param: `benchmark_id` (**será removido** — ver §6 A5: passa a só benchmark primário).
- `funds/{id}/holdings/top` → `fund_analysis.py` (top holdings + sector breakdown).
  Param: `limit`.
- `stocks/{ticker}/analysis` → `app/services/stock_analysis.py` (candles, rolling
  vol/beta/correlation, drawdown, histograma, VaR/CVaR). Params: `range`, `window`.
- `stocks/{ticker}/holders`, `holders/funds` → `app/services/stock_holders.py`
  (13F/N-PORT latest por ticker, enriquecido com preço de entrada/atual e ownership).
- `holdings/{cusip}/reverse-lookup` → `fund_dossier_tier_b.py` (13F + N-PORT por cusip).
- `portfolios/{id}/overview` → `app/services/portfolio_crud.py` (P&L/aggregates).
- `portfolios/{id}/lookthrough` → `app/services/lookthrough.py` (consolidação ponderada
  + árvore capped).

## 4. Inventário — o que já existe no TimescaleDB Cloud (reaproveitar)

Confirmado por inspeção do schema `public` (serviço `t83f4np6x4`, 2026-06-21):

| Objeto | Tipo | Volume / frescor | Uso na migração |
|---|---|---|---|
| `fund_risk_metrics` + `fund_risk_latest_mv` | tabela + MV | 76k linhas, diário (19/06) | Escalares de `entity-analytics` e `risk` (sharpe, sortino, calmar, alpha, beta, tracking error, info ratio, up/down capture, VaR/CVaR, max drawdown) |
| `nport_lookthrough_exposures` | tabela | 12,2M, dim `sector`/`issuer`/`currency`/`asset_class`, 31/01 | Sector breakdown de `holdings/top`; base do `lookthrough` |
| `nport_lookthrough_summary` | tabela | direct/indirect/coverage pct | Cabeçalho do `lookthrough` |
| `factor_model_fits` | tabela | 8 fits (por asset_class), `factor_returns` jsonb, 19/06 | Input do OLS de `factors` |
| `equity_characteristics_monthly` | tabela | 100k, valores brutos de style, 31/01 | z-scores de style-bias via SQL |
| `nport_holdings_history` | MV | pct_nav nos últimos 4 trimestres por holding | Base de `style-drift` |
| `sec_13f_entry` | MV | (cik, cusip, entry_date) | `entry_date` de `stocks/holders` |
| `nav_timeseries` | tabela | inclui `return_1d` | Daily returns de fundos (E1) |
| `cagg_eod_daily` | cagg (continuous) | 10,1M linhas, 2.222 tickers, 1962→2026-06-18; auto-refresh por policy + real-time agg | Fonte db-first de séries diárias de `stocks/*` (já em uso, `38dbdb4`); **base do `price_latest_mv`** (Grupo D) |
| `cagg_nav_daily` | cagg (continuous) | `instrument_id, bucket, nav, return_1d, n_obs, aum_usd`; auto-refresh por policy + real-time agg | Fonte db-first de séries diárias de `funds/*` (já em uso, `38dbdb4`); **base do `nav_latest_mv`** (Grupo D) |
| `cagg_eod_weekly/monthly`, `cagg_nav_weekly/monthly` | caggs | downsample pronto | Séries longas no Grupo C (superados pelos CAGGs diários para `stocks/*`/`funds/*`) |
| `sec_13f_holdings` | tabela | 10,1M, latest 2026-03-31 | Fonte de holders/reverse/institutional |
| `sec_nport_holdings` | tabela | 96,4M, latest 2026-01-31 | Fonte de holdings/active-share/style-drift |
| `fund_benchmark_candidates_v` | view | resolve benchmark primário por série | Benchmark de `active-share` |
| `redis-volume` (Railway, projeto investintell-light) | serviço | Online; `REDIS_URL` no `api` | Cache E2 |
| `optimize_jobs` (light) | tabela | estados pending/running/succeeded | Modelo de jobs async (E3) |

Descartar das premissas:
- `sec_institutional_allocations` — **vazia** (0 linhas). Não usar; usar `sec_13f_holdings`.
- `screener_metrics` — cobre só **136 tickers**; não serve de atalho para `stocks/analysis`
  genérico. `stocks/analysis` lê db-first de `cagg_eod_daily` (já feito em `38dbdb4`); as
  funções de janela/distribuição (Grupo C) compõem sobre essa fonte.

## 5. Fundação — padrão compartilhado

Pipeline de materialização (Grupos A/B/D), idêntico ao de `risk_metrics`:

1. **Worker** em `investintell-datalake-workers`, despachado por `WORKER=<nome>` em
   `src/run_worker.py`, agendado por cron no Railway, lendo do TimescaleDB Cloud.
2. **Tabela base** com chave de entidade + data (`as_of`/`report_date`/`calc_date`) +
   `organization_id` NULL (global), upsert idempotente. `*_metrics`/`*_exposures`
   (tipado) ou `*_artifacts` (JSONB com `schema_version int`).
3. **`*_latest_mv`** com `DISTINCT ON (entidade)` ordenado por data desc, índice único,
   `REFRESH MATERIALIZED VIEW CONCURRENTLY` ao fim do worker (conexão autocommit, fora
   do advisory lock), guardado por advisory lock próprio.
4. **Backend** lê o `latest_mv` e devolve: JSONB direto; tipado → SELECT + estruturação
   do dict (sem cálculo).

Para resultados deriváveis por agregação/janela puramente do que já existe, o pipeline
acima é substituído por **MV/função SQL** (sem worker Python). Cada `latest_mv`/MV expõe
a data da fonte para o frontend exibir frescor (como `nav_staleness` já faz).

## 6. Grupo A — Fund analytics estáveis

### A1 — `factors` (worker Python)
- Worker `fund_factors`: para cada fundo, OLS dos retornos mensais contra
  `factor_model_fits.factor_returns` (do `asset_class` do fundo) → betas, t-stat,
  significância. Tabela tipada `fund_factor_exposures(instrument_id, factor, beta,
  t_stat, significance, as_of)`.
- Style-bias z-scores: **view/função SQL** `fund_style_bias_v` sobre
  `equity_characteristics_monthly` — `(value - avg() OVER (PARTITION BY as_of)) /
  stddev() OVER (PARTITION BY as_of)` por fator. Sem worker.
- `fund_factor_exposures_latest_mv` para leitura.

### A2 — `style-drift` (MV / SQL)
- MV `fund_style_drift_mv(series_id, report_date, quarter, sector, weight)` agregando
  `sec_nport_holdings` (`SUM(pct_of_nav) GROUP BY report_date, sector`). `quarters` vira
  `WHERE report_date >= ...`/`LIMIT` na leitura. Sem worker.

### A3 — `institutional-reveal` (worker Python, JSONB)
- Worker `fund_institutional_reveal`: cruza top holdings do fundo (`sec_nport_holdings`)
  com `sec_13f_holdings` (por cusip), agrega por instituição e por security, monta a rede
  (top instituições/securities + arestas). Tabela `fund_institutional_reveal_artifacts(
  series_id, as_of, schema_version, payload jsonb)` + `_latest_mv`.

### A4 — `holdings/top` (MV / SQL)
- Top holdings: SELECT de `sec_nport_holdings` (latest, ORDER BY pct_of_nav). Sector
  breakdown: `nport_lookthrough_exposures` (dimension='sector') — já materializado.
  MV fina `fund_top_holdings_mv` (top-50 por série, truncado por `limit` na leitura) +
  reuso do lookthrough para sector. Sem worker.

### A5 — `active-share` (MV / SQL) — **mudança de produto, não paridade**
- MV `fund_active_share_mv(series_id, benchmark_series_id, active_share, overlap,
  n_portfolio, n_benchmark, n_common, as_of)`: FULL OUTER JOIN por cusip entre holdings
  do fundo e do **benchmark primário** (`fund_benchmark_candidates_v` →
  `benchmark_proxy_instrument_id` → série do ETF em `sec_nport_holdings`),
  `active_share = 0.5·Σ|w_fund - w_bench|`. Sem worker.
- **Decisão de produto (já tomada)**: o endpoint deixa de oferecer seleção de benchmark e
  serve sempre o benchmark primário. Isto é remoção intencional de capacidade, não
  paridade — por isso o teste de paridade (§12) compara apenas o caminho do benchmark
  primário, e não o caminho de `benchmark_id` arbitrário (que deixa de existir).
- **Tratamento do parâmetro `benchmark_id`**: o endpoint passa a **ignorar** um
  `benchmark_id` recebido (sem erro), respondendo sempre com o benchmark primário, para
  não quebrar clientes que ainda o enviem durante a transição. Em seguida o parâmetro é
  removido do contrato. O response inclui `benchmark_series_id`/identificação do benchmark
  efetivamente usado, para o cliente saber qual foi aplicado.
- **Cleanup do contrato órfão** (parte do escopo desta mudança, não opcional): remover
  `benchmark_id` do handler/serviço do backend, do schema/params do endpoint, dos tipos
  gerados da API, dos query keys do frontend e da UI de seleção, e dos testes que exercem
  o caminho por benchmark selecionado. Não deixar parâmetro aceito-mas-inerte no contrato
  final.

## 7. Grupo B — Stock/holdings por entidade

### B1 — `stocks/holders` (MV / SQL)
- MV `stock_institutional_holders_mv(ticker, cusip, cik, manager_name, shares,
  market_value, report_date, ownership_pct, entry_date)`: `sec_13f_holdings` (latest) +
  `sec_13f_entry` (entry_date) + `sec_cusip_ticker_map` + nomes
  (`sec_13f_filer_name`/`curated_institutions`/`sec_managers`) + `shares_outstanding`
  (`fundamentals_snapshot`). `current_price`/`entry_price` resolvidos por join com price
  `latest_mv` na leitura (sem cálculo). Sem worker.

### B2 — `stocks/holders/funds` (MV / SQL)
- MV `stock_fund_holders_mv(ticker, cusip, family_name, fund_name, series_id, shares,
  pct_of_nav, report_date)` sobre `sec_nport_holdings` (latest por cusip) + resolução de
  série/família. Backend agrupa family→funds. Sem worker.

### B3 — `holdings/{cusip}/reverse-lookup` (SQL)
- View/MV `holding_reverse_lookup`: lado institucional de `sec_13f_holdings` (por cusip,
  latest) + exposições de fundo de `sec_nport_holdings` (por cusip). Sem worker.

## 8. Grupo C — Séries interativas (funções SQL on-demand)

Sem materialização; cálculo movido para o Postgres via funções SQL/window functions.
`range` = filtro de data; `window` = argumento. Backend chama e devolve, sem `pandas`.

Funções base (reutilizadas pelos três endpoints):
- `fn_rolling_metrics(instrument/ticker, window, start, end)` → rolling vol e sharpe.
- `fn_rolling_beta_corr(asset, benchmark, window, start, end)` → rolling beta/correlação.
- `fn_drawdown(series, start, end)` → série de drawdown (cummax via window) + eventos.
- `fn_histogram(returns, bins, start, end)` → bins/counts.
- `fn_var_cvar(returns, level, start, end)` → VaR/CVaR histórico.

Endpoints:
- `funds/{id}/analysis`, `stocks/{ticker}/analysis` → compõem as funções acima sobre
  `cagg_nav_daily` (fundos) e `cagg_eod_daily` (stocks) — ambos já db-first em todos os
  ranges via `38dbdb4`. O que falta no Grupo C para esses endpoints são as **funções de
  janela/distribuição** (rolling, drawdown, histograma, VaR/CVaR) — a fonte de série já migrou.
- `funds/{id}/entity-analytics` → **escalares lidos de `fund_risk_metrics`**; apenas as
  séries (rolling returns, drawdown periods, distribuição) via funções SQL. Insiders
  continuam de `sec_insider_transactions` (leitura).
- `funds/{id}/risk-timeseries` → `fn_drawdown` (reclassificado de A para C: derivável de
  nav e muda diariamente, não vale materializar).

## 9. Grupo D — Suporte a portfólio

- `price_latest_mv(ticker, last_close, prev_close, as_of)` e
  `nav_latest_mv(instrument_id, last_nav, prev_nav, as_of)`: DISTINCT ON, últimos dois
  pontos por entidade.
- `portfolios/{id}/overview` continua **on-demand** (aritmética: qty × preço), lendo do
  `latest_mv` em vez de varrer a série.
- `portfolios/{id}/lookthrough` continua **on-demand** (consolidação ponderada + árvore
  capped), lendo das exposições já materializadas + `latest_mv` de preços. Sem mudança
  estrutural além da fonte de preço.

Portfólios são dinâmicos por usuário; não há materialização global possível. O ganho é
remover varreduras de série, não materializar resultado.

## 10. Grupo E — Aceleração de ferramentas interativas

### E1 — Ingredientes pré-computados
- Worker/cagg `daily_returns` para `eod_prices` (stocks); fundos já têm
  `nav_timeseries.return_1d`. Helper de **aligned returns** reusável + cache de
  covariância Ledoit-Wolf por `{asset_set, window}`. Beneficia Grupos C, E e o optimizer.

### E2 — Cache de resultado por hash (Redis existente)
- Camada nova, **separada do middleware de catálogo** (`app/core/cache.py`), usando o
  cliente Redis com fail-open já existente. Chave = hash dos parâmetros normalizados.
- `statistics/*`, `backtest/walk-forward`, `correlation-regime`: determinísticos →
  sempre cacheáveis. `monte-carlo/*`: cacheável **apenas com `seed`** (estocástico sem ele).
- Para entradas que envolvem portfólio do usuário, a chave inclui o **conteúdo/versão do
  portfólio** (não só o id), preservando isolamento por usuário. TTL por tipo de cálculo.

### E3 — Jobs assíncronos
- Reusa o modelo `optimize_jobs`: `walk-forward` grande e `monte-carlo` com muitas
  simulações enfileiram job (202 + polling) em vez de bloquear o request; resultado
  gravado e servido via E2.

## 11. Resumo do que se cria

| Item | Mecanismo | Worker Python? |
|---|---|---|
| `fund_factor_exposures` (+latest_mv) | tabela + worker `fund_factors` | sim |
| `fund_style_bias_v` | view/SQL | não |
| `fund_style_drift_mv` | MV | não |
| `fund_institutional_reveal_artifacts` (+latest_mv) | tabela JSONB + worker | sim |
| `fund_top_holdings_mv` | MV | não |
| `fund_active_share_mv` | MV | não |
| `stock_institutional_holders_mv` | MV | não |
| `stock_fund_holders_mv` | MV | não |
| `holding_reverse_lookup` | view/MV | não |
| `fn_rolling_metrics`/`fn_rolling_beta_corr`/`fn_drawdown`/`fn_histogram`/`fn_var_cvar` | funções SQL | não |
| `price_latest_mv`/`nav_latest_mv` | MV | não |
| `daily_returns` (stocks) + aligned-returns/LW-cov | cagg/worker + helper | sim (leve) |
| Cache E2 | módulo backend (Redis) | não |
| Jobs E3 | reuso `optimize_jobs` | não |

Total de workers Python novos: **`fund_factors`, `fund_institutional_reveal`,
`daily_returns`** (mais o helper de ingredientes do E1).

## 12. Estratégia de transição (paridade)

Para cada endpoint migrado:
1. Construir o objeto novo (MV/worker/função SQL).
2. **Teste de paridade**: comparar o output novo contra o cálculo atual em uma amostra
   representativa de entidades, dentro de tolerância numérica documentada. **Exceção
   `active-share`**: a paridade cobre apenas o caminho do benchmark primário (o caminho de
   `benchmark_id` arbitrário é descontinuado por decisão de produto — §6 A5 —, não
   comparado). O cleanup do contrato (`benchmark_id` fora de backend/tipos/frontend/testes)
   faz parte do passo de troca, não de uma migração separada.
3. **Dual-read** atrás de flag: a rota lê do caminho novo, com fallback ao antigo
   enquanto a flag estiver desligada; comparação registrada em ambiente de validação.
4. Trocar o caminho default; remover o código de cálculo Python só após a troca estável.

## 13. Testes

- Workers: testes de cálculo contra baseline (valores conhecidos / paridade com o atual).
- Funções SQL: paridade com o cálculo Python atual por amostra; bordas (séries curtas,
  janelas maiores que a série, gaps).
- Rotas: lêem do MV/função e não invocam `pandas` (asserção de ausência de cálculo).
- Cache E2: hit/miss, fail-open quando Redis indisponível, chave inclui versão de
  portfólio, monte-carlo sem `seed` não cacheia.
- Jobs E3: enfileiramento, polling, estados, resultado servido via cache.

## 14. Sequenciamento sugerido (para o plano)

1. Fundação + Grupo D (latest_mv de preço/nav) — destrava overview/lookthrough e Grupo C.
2. Grupo A (MV/SQL primeiro: style-drift, holdings/top, active-share, style-bias;
   depois workers: factors, institutional-reveal).
3. Grupo B (MVs de holders/reverse-lookup).
4. Grupo C (funções SQL + reescrita das três rotas).
5. Grupo E (E1 ingredientes → E2 cache → E3 jobs).

Cada passo entra com paridade verificada e dual-read antes da troca.

## 15. Riscos e questões em aberto

- **Cobertura de benchmark**: `active-share` depende de o proxy ETF primário ter holdings
  em `sec_nport_holdings`. ETFs sem N-PORT recente ficam sem active-share (estado vazio
  explícito, como hoje). Quantificar a cobertura no plano.
- **Frescor das fontes**: N-PORT (31/01) e 13F (Q1 2026) têm lag natural; os MV expõem a
  data da fonte. Definir cadência de cron alinhada à ingestão (não diária para N-PORT/13F).
- **Funções SQL pesadas**: `entity-analytics` tem muitas séries; validar performance das
  funções em janelas longas (apoiar-se nos caggs). Medir antes de remover o Python.
- **Versão de portfólio na chave de cache (E2)**: definir como derivar a versão (hash de
  posições + timestamp de atualização) para invalidar ao editar o portfólio.
- **`schema_version` dos artefatos JSONB**: processo de bump quando o shape muda
  (espelhar o guard já usado em `app/core/cache.py`).
