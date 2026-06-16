# Design — Migração total ECharts/ixchart → Highcharts Core + Stock, e port do dossier de fundos

- **Data:** 2026-06-14
- **Branch / worktree:** `feat/highcharts-charts-migration` em `E:/investintell-light-highcharts` (base `7583d7b`)
- **Status:** Draft para revisão (brainstorming → spec). Próximo passo: `writing-plans`.
- **Repos envolvidos:** `investintell-light` (FastAPI + Next.js), `investintell-datalake-workers` (workers Cloud), `investintell-allocation` (legado — somente leitura/referência).

---

## 1. Objetivo

Substituir **totalmente** os gráficos atuais (ECharts + o motor canvas próprio `ixchart`) por **Highcharts Core** (gráficos estáticos) e **Highcharts Stock** (séries temporais e preço/live), eliminar o limite de profundidade de dados (730 dias) consumindo as CAGGs do TimescaleDB, portar o **dossier completo de fundos do legado (23 visualizações, 5 abas + 2 modais)** para o repositório atual seguindo o design system **Graphite**, e introduzir uma camada de **cache server-side** (SSR + route handlers) para mitigar a latência (cold-start do Railway).

Fora de escopo declarado pelo dono no brief original: nenhum — o dono escolheu a versão maximalista em todas as decisões (ver §3). O único item que o brief marcava "fora de escopo" (gráficos dinâmicos via WebSocket) foi **explicitamente trazido para dentro** pela decisão de aposentar o `ixchart`.

---

## 2. Achados da auditoria (fundamentam o desenho)

Auditoria por 5 agentes paralelos + análise de gap por 3 agentes (modelo de dados do Light, contratos do backend legado, inventário dos datalake-workers).

### 2.1 Existem DOIS sistemas de chart no Light, não um
1. **ECharts** (`echarts@^6`): wrapper fino `src/components/charts/EChart.tsx` (`echarts.init`, `ResizeObserver`, `setOption(opt, {notMerge:true})`) consumido por 11 views, alimentado por **17 builders puros** em `src/lib/charts/*` (~28 instâncias de chart). Cores lidas de CSS vars via `chartColors()` (`src/lib/charts/theme.ts`).
2. **`ixchart`**: motor **canvas-2D próprio** (`src/lib/ixchart/engine.ts`, ~818 linhas) + wrapper `src/components/charts/InteractiveChart.tsx`. É o gráfico de **preço candlestick/OHLC/line/area com ferramentas de desenho, SMA/RSI/volume e live-ticks (WebSocket via `useLiveTicks`)**. Não usa ECharts.
3. **`src/lib/charts/price.ts` (`buildPriceOption`, candlestick ECharts) é código morto** (nunca importado).
4. **Highcharts Core e Stock NÃO estão instalados.** Só existe `@highcharts/grid-pro@^3.0.0` (tabela, usado por `DataGrid.tsx`) e `echarts@^6`. Stack: Next.js 15.5.19 (App Router, Turbopack), React 19.1.0, Tailwind v4 (`@theme`), TanStack Query ^5, Vitest ^4.

### 2.2 O design system Graphite e o padrão de wrapper
- **`DataGrid.tsx`** é o padrão de referência: `'use client'`, `import('@highcharts/grid-pro')` dinâmico dentro de `useEffect`, guarda de corrida (`disposed`), create-once (`[]`), `update()` em `[options]`, `destroy()` no unmount, wrapper "burro" que recebe `Options` já construído por adapters puros em `src/lib/grid/*`.
- **Tema (crucial p/ Highcharts):** SVG do Highcharts **não** herda CSS vars retroativamente. É obrigatório usar a **Estratégia 2** (a mesma do ECharts/ixchart): ler tokens em runtime via `getComputedStyle` (`chartColors()` em `src/lib/charts/theme.ts` / `readIxTokens()` em `src/lib/ixchart/tokens.ts`) e depender do **remount por `key`** do `AppShell` (`<main key={theme-accent-density}>`) para recomputar no switch de tema. Pré-paint garantido por script inline em `layout.tsx`.
- **Tokens Graphite** (em `globals.css`, semânticos `--color-*`): `surface-0..3`, `text-primary/secondary/muted`, `accent` (oxblood `#7a1c24` claro / `#e0828a` escuro), `accent-wash`, `gain`/`loss` (+`-muted`), `chart-grid`, `chart-bar`/`chart-bar-mute`, `cat-1..8` (paleta categórica). Regras: cantos retos (`--radius-*: 0`), sem sombra, hairline, numerais tabulares, títulos serif / dados sans.

### 2.3 Camada de dados — o "limite de 730 dias" real e as CAGGs já existentes
- O limite que afeta charts é **`NAV_WINDOW_DAYS = 365*2` (730)** + **`NAV_TARGET_POINTS = 260`** em `backend/app/services/funds_catalog.py:37-38` → recorta o `nav[]` do **perfil** de fundo (alimenta heatmap mensal + drawdown em `FundProfileView`).
- O `current_date - 730` no DDL `funds_v` é **elegibilidade de catálogo** (quais fundos existem) — **NÃO mexer**.
- O gate de 2 anos do otimizador já foi removido (`DEFAULT_WINDOW_DAYS = None`).
- **`openapi.json` está obsoleto**: `window_days` ainda mostra `default: 730` (código vivo é `None`). Regenerar.
- **CAGGs já existem** na TimescaleDB Cloud: `cagg_nav_weekly`, `cagg_nav_monthly`, `cagg_eod_weekly`, `cagg_eod_monthly`.
- **Endpoints range-aware com downsampling no banco JÁ EXISTEM mas NÃO são consumidos pelo frontend:** `GET /funds/{id}/timeseries?range=` e `GET /stocks/{ticker}/timeseries?range=` (daily ≤1Y / weekly CAGG 1–5Y / monthly CAGG >5Y; `MAX` = histórico completo). Não há `fetchFundTimeseries`/`fetchStockTimeseries` em `client.ts`.
- Charts interativos hoje buscam `bars=2520` fixo uma vez; os botões de range só dão zoom client-side.

### 2.4 Caching — inexistente no server
- **Nenhum cache server-side**: sem route handlers, sem `revalidate`/`unstable_cache`, sem SSR hydration. `next.config.ts` vazio. Páginas são Server Components que delegam 100% a views client com React Query (`staleTime` 30s–1h). Navegação fria = round-trip ao backend (cold-start do Railway `api-production-2b6d` é o gargalo dominante; listagens SQL são 8–12ms).
- Rota mais pesada/exposta a cold-start: `GET /funds/{id}/history` (scan cru de 2520 barras + warm Tiingo p/ ETFs).

### 2.5 Pivô da análise de gap — o dossier já é quase todo calculado, só não é exposto
Os **datalake-workers** (`investintell-datalake-workers`) já produzem na Cloud quase todo o dado do dossier:

| Dado | Produzido por | Tabela de saída |
|---|---|---|
| Returns 1m–10y, vol, **GARCH conditional vol** (`volatility_garch`,`vol_model`), Sharpe/Sortino/Calmar, **VaR/CVaR 95** + **CVaR 99/99.9 EVT**, beta/alpha/TE/IR, up/down capture, **peer percentiles** | `risk_metrics` | `fund_risk_metrics` (+ MV `fund_risk_latest_mv`) |
| Style instruments por fundo (size, B/M, momentum, quality, investment, profitability) | `characteristics` | `equity_characteristics_monthly` |
| Modelo de fatores IPCA (gamma loadings + factor returns + OOS R²) | `factor_model` | `factor_model_fits` |
| Look-through N-PORT (issuer/asset_class/sector/currency, direto/indireto) | `nport_lookthrough` | `nport_lookthrough_exposures`, `_summary` |
| NAV benchmark por bloco | `benchmark_ingest` | `benchmark_nav` |
| Regime vote2of3 (binário) + regime de crédito | `regime_composite`, `credit_regime` | `regime_composite_daily`, `credit_regime_daily` |

O backend do Light **não lê** essas tabelas; sua `fund_risk_latest_mv` espelha só 33 colunas (sem `volatility_garch`, sem métricas de classe/fator) e não há nenhum endpoint de dossier. Os helpers de análise (`backend/app/analytics/rolling.py`, `risk.py`, `distribution.py`, `_series.py`) existem mas só estão ligados a **stocks** (`GET /stocks/{ticker}/analysis` é o template a espelhar para fundos).

**Genuinamente ausente** (sem worker, sem tabela em nenhum repo):
- **13F institucional** (`sec_13f_holdings`, `curated_institutions`, `sec_managers`) → reverse-lookup, overlap institucional, holder-network (viz #19/#20/#21).
- **Insider / Form 4** (`sec_insider_sentiment`) → insider flow + gauge (viz #18, dentro de entity-analytics).
- **Série contínua de regime-probabilidade** (`macro_regime_history.p_high_vol`): Light só tem regime binário.
- **Série temporal de GARCH** (só o valor latest é persistido, não uma série).
- `manager_score`/`elite_flag`: colunas existem mas estão NULL (scoring não portado).

### 2.6 O dossier legado (23 visualizações) e contratos de API
Backend legado FastAPI encontrado em `E:/investintell-allocation/backend/`. Contratos exatos extraídos (ver §6.B). Convenções: 252 dias úteis, rf=0.04, CVaR 0.95, **VaR modificado = Cornish-Fisher**, drawdown do `risk/timeseries` em %, do `entity` em fração; alias de wire `volatility_garch→conditional_volatility`; relabel de regime `RISK_ON/NEUTRAL/CRISIS → Expansion/Cautious/Stress`.

---

## 3. Decisões (registradas)

| # | Decisão | Escolha do dono |
|---|---|---|
| D1 | Destino do `ixchart` | **Migrar tudo p/ Highcharts Core+Stock, aposentar `ixchart`** — inclusive live-ticks via `Stock series.addPoint`. |
| D2 | Escopo do legado | **Dossier completo (23 viz)**. |
| D3 | Caching | **SSR prefetch + `HydrationBoundary` + route handlers c/ `revalidate`**. |
| D4 | Limite 730 | **Wirar aos `/timeseries` CAGG + subir/parametrizar `NAV_WINDOW_DAYS` + novas CAGGs se preciso**. |
| D5 | Tier C (13F + insider) | **Construir ingestão SEC 13F + Form 4 agora (fase P7)**. |
| D6 | IA da página de fundos | **Redesign de dossier completo (5 abas + 2 modais) em Graphite**. |

---

## 4. Arquitetura

### 4.1 Frontend — wrappers e tema

**`src/lib/charts/hc/theme.ts`** — `highchartsTheme(colors: ChartColors): Highcharts.Options`. Tema global Graphite: `colors:[cat1..cat8]`, `chart.backgroundColor:'transparent'`, `chart.style.fontFamily` = stack sans literal, `xAxis/yAxis.gridLineColor = grid`, `lineColor = border`, label color `textMuted`, title color `textPrimary`, `chart.borderRadius:0`, sem sombras, `plotOptions.series.animation:false`, numerais tabulares no `labels.style`. Cria também variantes `up/down = gain/loss` para candles.

**`src/components/charts/HighchartsChart.tsx`** (Core) — espelha `DataGrid.tsx`:
- `'use client'`, `import type { Options, Chart } from 'highcharts'` (type-only); `const Highcharts = await import('highcharts')` dinâmico em `useEffect`.
- Props: `{ options: Options; className?: string; constructorType?: 'chart'; emptyMessage?: string; loading?: boolean; onReady?: (chart: Chart)=>void }`.
- Lifecycle: `latestOptions`/`onReadyRef` em refs (sem re-run do create), create-once `[]` com guarda `disposed`, `chart.update(options, true, true)` em `[options]`, `ResizeObserver(()=>chart.reflow())`, `chart.destroy()` no unmount.
- Aplica o tema global via `Highcharts.setOptions(highchartsTheme(colors))` (uma vez por instância/mount; ok pois é idempotente por mount e o remount do AppShell recarrega).
- Overlay de empty/loading absoluto, token-styled (`text-text-muted`), igual ao `DataGrid`.

**`src/components/charts/HighchartsStockChart.tsx`** (Stock) — variante que importa `highcharts/highstock` (`import('highcharts/highstock')`), `constructorType:'stockChart'`, com suporte a `navigator`, `rangeSelector`, `scrollbar`, `annotations` (módulo `highcharts/modules/annotations`), e API imperativa para live: expõe `onReady(chart)` para o consumidor chamar `chart.series[i].addPoint(...)` com os ticks de `useLiveTicks`. Carrega módulos (`annotations`, `accessibility` off) de forma idempotente.

Decisão de empacotamento: **um pacote `highcharts`** (Highstock faz parte do mesmo pacote via `highcharts/highstock`). NÃO usar `highcharts-react-official` (convenção do repo é wrapper ref-based próprio). Configurar `Highcharts.setOptions({ accessibility: { enabled: false }})` ou incluir o módulo de acessibilidade (decisão de P0; default: incluir `modules/accessibility` para evitar warning e melhorar a11y).

**Builders** — `src/lib/charts/hc/*` (puros, testáveis com Vitest, recebem `ChartColors`, retornam `Highcharts.Options`). Um por tipo, espelhando os 17 atuais (ver mapa §5).

**Retirada do `ixchart`** — o `InteractiveChart` é reescrito sobre `HighchartsStockChart`:
- candlestick/OHLC/line/area → `series.type` correspondente do Stock;
- range 1M/6M/1Y/5Y/MAX → `rangeSelector` (passa a **refetch** via `/timeseries?range=` em vez de zoom client-side);
- pan/zoom/crosshair → nativos do Stock (`navigator`, `tooltip.crosshairs`);
- ferramentas de desenho (trend/hline/fib/measure) → `annotations` (módulo) + UI própria;
- SMA/RSI/VOL → `highcharts/indicators/*` (módulos de indicadores do Stock) ou séries derivadas reusando `src/lib/ixchart/series.ts` (decisão P2; preferir indicadores nativos);
- live-ticks → `chart.series[priceIdx].addPoint([t, price], true, false)` no callback do `useLiveTicks`/`subscribeTicks` (mantém `client.ts`/`useLiveTicks.ts`).

**Limpeza final (P8):** remover `echarts`, `src/lib/charts/*` (ECharts), `src/lib/ixchart/*`, `EChart.tsx`, `InteractiveChart.tsx` antigo, `price.ts`.

### 4.2 Backend — 3 tiers

Todos read-only sobre Cloud onde o dado existe. Padrão: novos routers em `backend/app/api/routes/funds_analysis.py` (Tier A/B) reusando `analytics/*`; sanitização de boundary igual ao legado (alias garch, relabel de regime).

**Tier A — expor dado já presente (barato):**
- `GET /funds/{id}/analysis?range=&window=` — espelha `GET /stocks/{ticker}/analysis` sobre `nav_timeseries`: growth-of-$100 (rebased), monthly returns, distribution (histograma), rolling vol/sharpe (window=252), série de drawdown (underwater). Reusa `analytics/_series.py`, `rolling.py`, `risk.py`, `distribution.py`. Carrega NAV via `optimizer/data.py:_fund_return_series`.
- `GET /funds/{id}/holdings/top` — sector_breakdown + top-25 a partir de `fund_holdings_v` / look-through (resolve sector via dimensão de look-through, dado que `gics_sector` está NULL).
- `GET /funds/{id}/peers?limit=` — cohort por `peer_strategy_label` + linhas de comparação (vol/sharpe/expense/maxdd/cvar) a partir de `funds_v` + `fund_risk_latest_mv`.
- `GET /funds/scatter?limit=` — colunar (ids/names/expected_returns=return_1y/volatilities/tail_risks=cvar_95_12m/strategies) a partir de `funds_v` (ou montar client-side a partir de `/funds`).

**Tier B — superficiar dado dos workers que o Light não lê (médio):**
- **Estender `fund_risk_latest_mv`** (ou ler `fund_risk_metrics` direto) para expor `volatility_garch`, `vol_model`, `cvar_99_evt`, métricas de classe (migration 0012: `empirical_duration`, `credit_beta`/`_r2`, etc.) e os campos de fator. Atualizar `FundRiskOut`/openapi. (Migration SQL via Tiger MCP — ver §7.)
- `GET /funds/{id}/factors` — `market_sensitivities` (OLS de retornos do fundo sobre `factor_model_fits`, t-stats→significance) + `style_bias` (z-scores cross-section de `equity_characteristics_monthly`). Portar `factor_model_service`/`research.py` do legado.
- `GET /funds/{id}/style-drift?quarters=` — **nova view** `fund_holdings_history_v` sobre os `report_date`s históricos de `sec_nport_holdings`, agregando sector weight por trimestre.
- `GET /funds/{id}/entity-analytics?window=&benchmark_id=` — portar `quant_engine`: risk_statistics, drawdown+worst_periods, capture (mensal), rolling_returns multi-janela, distribution (FD bins + skew/kurt), return_statistics, **tail_risk (VaR paramétrico + Cornish-Fisher modificado + ETL/ETR + STARR/Rachev + Jarque-Bera)**. `insider_data` fica `None` até P7. Benchmark via `benchmark_nav`.
- `GET /funds/{id}/risk-timeseries?from=&to=` — drawdown series (`nav` vs window-max, %) + **conditional_volatility computada on-the-fly** (GARCH(1,1) via `arch` sobre os retornos NAV, replicando o worker; alias de wire) + regime band derivada de `regime_composite_daily` (binário → faixas Expansion/Cautious/Stress; sem `p_high_vol` contínuo, documentar a divergência do legado).
- `GET /funds/{id}/active-share?benchmark_id=` — se o benchmark resolver para um fundo com N-PORT (`sec_nport_holdings`): `0.5·Σ|w_p−w_b|`. Caso contrário, empty-state.

**Tier C — dado AUSENTE → ingestão nova (P7, repo datalake-workers):**
- Worker **`thirteenf_ingestion`**: parse SEC EDGAR 13F-HR (information table) → tabela `sec_13f_holdings` (cik, period, cusip, name, value, shares); seed de `curated_institutions` (managers institucionais relevantes) e `sec_managers`. Cadência trimestral.
- Worker **`insider_ingestion`**: parse SEC Form 4 → `sec_insider_sentiment` (cik, quarter, buy_value, sell_value). Cadência diária/semanal.
- Endpoints Light (Tier B/C boundary): `GET /funds/{id}/institutional-reveal`, `GET /holdings/{cusip}/reverse-lookup`, e o `insider_data` do `entity-analytics` passam a popular. Antes de P7, esses 5 painéis renderizam empty-state "dados não disponíveis".

### 4.3 Caching (D3)

- **Route handlers** em `frontend/src/app/api/funds/[id]/<sub>/route.ts` que fazem proxy do FastAPI usando `unstable_cache`(fn, keys, `{ revalidate, tags }`) — tags por fundo (`fund:{id}`) e por tipo de série. Headers `Cache-Control: s-maxage=…, stale-while-revalidate=…`.
- **SSR prefetch**: a página `app/funds/[id]/page.tsx` (Server Component) faz `queryClient.prefetchQuery` das séries acima e passa via `<HydrationBoundary state={dehydrate(queryClient)}>` para a view client. Primeira pintura já com dado (sem round-trip frio).
- `revalidate` por rota: séries longas/históricas com `revalidate` maior (ex.: 3600s), perfil 300s. Invalidação por tag em eventos (ex.: import "bring to universe", refresh de métricas).
- Mantém React Query no client para interações (troca de range/aba) com `staleTime` alinhado ao `revalidate`.

### 4.4 Profundidade de dados (D4)

- Adicionar `fetchFundTimeseries(id, range)` e `fetchStockTimeseries(ticker, range)` em `src/lib/api/client.ts`.
- `HighchartsStockChart` consumidores passam a usar `/timeseries?range=` (daily/weekly/monthly CAGG; `MAX` = histórico completo) com queryKey incluindo `range` → refetch por range.
- Parametrizar/subir `NAV_WINDOW_DAYS`/`NAV_TARGET_POINTS` em `funds_catalog.py` (ou expor a janela longa pelo `/funds/{id}/analysis`, deixando o perfil enxuto). Heatmap mensal + drawdown passam a aceitar histórico completo.
- Regenerar `openapi.json` + `api.d.ts` (corrigir `window_days default` e adicionar novos endpoints/campos).
- Novas CAGGs só se necessário (ex.: bucket diário muito longo penalizar; provavelmente não — as CAGGs semanais/mensais já cobrem MAX).

### 4.5 IA do dossier de fundos (D6)

Reconstruir `app/funds/[id]` como dossier (Radix Tabs + modais Graphite), espelhando o legado:
- **Header**: identidade + pills (ticker/type/elite) + 5 KPIs (AUM, expense, risk-adj 1Y, return 1Y, vol 1Y) + ações (Deep Analysis ↗, Relationships ↗, Add to portfolio / Bring to universe).
- **Abas**: Performance (growth/monthly/distribution/rolling/risk-overlay), Holdings (donut setorial + top-10), Style (style-drift stacked area), Factors (radar style-bias + barras de sensibilidade), Peers (tabela + scatter).
- **Modal Deep Analysis**: seções A–H (risk stats, underwater, capture, rolling returns, distribution+VaR/CVaR, return stats, tail-risk ladder, insider — esta com empty-state até P7).
- **Modal Relationships**: Holder network (force graph), Institutional overlap (circular graph + ranked bar), Active share (gauge) — empty-state até P7 para network/overlap.
- **Lista de fundos** (`app/funds`): adicionar o **Risk & Return scatter map** (FocusModal) sobre `/funds/scatter`.
- Empty-states, formatadores (fração×100 vs pré-pontos) e paleta portados de `core-runtime`/`core-charts` adaptados a Graphite.

---

## 5. Mapa de migração builder-a-builder (ECharts → Highcharts)

| Builder atual (`src/lib/charts/`) | Viz | Highcharts (`src/lib/charts/hc/`) |
|---|---|---|
| `nav.ts buildNavOption` | linha NAV | `line` (Core) ou `stockChart` |
| `cumulative.ts buildCumulativeOption` | 2 linhas (asset vs bench) | `line` ×2 |
| `rolling.ts buildRollingOption` | linha rolling (vol/beta/corr) | `line` (yAxis bounds reusados) |
| `histogram.ts buildHistogramOption` | barra histograma | `column` |
| `distribution.ts buildDistributionOption` | barra dist (screener) | `column` (cor por banda) |
| `contributions.ts buildRiskContributionsOption` | barra horizontal | `bar` |
| `allocation.ts buildAllocationOption` | donut | `pie` (innerSize) |
| `heatmap.ts buildHeatmapOption` | heatmap correl (visualMap contínuo) | `heatmap` + `colorAxis` |
| `performance.ts buildMonthlyReturnsOption` | heatmap mensal (diverging) | `heatmap` + `colorAxis` diverging |
| `performance.ts buildDrawdownOption` | linha+área+markArea | `area` + `plotBands` (pior janela) |
| `scatter.ts buildScatterOption` | scatter + reta regressão | `scatter` + `line` (silent) |
| `lookthrough.ts buildExposureBarsOption` | barra horizontal empilhada | `bar` stacked |
| `rebalance.ts buildDriftBandsOption` | barra h + scatter + markArea | `bar` + `scatter` + `plotBands`/`xrange` |
| `regime.ts buildRegimeStripOption` | strip timeline empilhada | `xrange` (1 série, por período) |
| `stacked.ts buildStackedAreaOption` | área empilhada + total | `area` stacked + `line` total |
| `stacked.ts buildStackedPercentOption` | área empilhada 100% | `area` `stacking:'percent'` |
| `stacked.ts buildMultiLineOption` | multi-linha (TOTAL destacado) | `line` (TOTAL acentuado) |
| `price.ts buildPriceOption` (morto) + `ixchart` engine | candlestick + volume + zoom + live | **Highcharts Stock** (candlestick + navigator + rangeSelector + annotations + indicators + `addPoint`) |

Interatividade a reproduzir: tooltip axis/item → `tooltip.shared`/`split`; `axisPointer cross/shadow` → `crosshairs`; `visualMap` → `colorAxis`; `dataZoom` → `navigator`/`rangeSelector` (Stock); `markArea` → `plotBands`/annotations; legendas in-chart vs HTML externo preservadas. Sem `brush`/`markLine` (não usados).

---

## 6. Contratos de endpoint

### 6.A Endpoints novos no Light (resumo — schema detalhado por fase)
`/funds/{id}/analysis`, `/funds/{id}/holdings/top`, `/funds/{id}/style-drift`, `/funds/{id}/factors`, `/funds/{id}/peers`, `/funds/{id}/entity-analytics`, `/funds/{id}/risk-timeseries`, `/funds/{id}/active-share`, `/funds/{id}/institutional-reveal`, `/holdings/{cusip}/reverse-lookup`, `/funds/scatter`. Reusar onde existir: `/funds/{id}/timeseries` (já existe), `/macro/regime` (já existe).

### 6.B Contratos legados de referência (extraídos do backend `investintell-allocation`)
Campos e computações exatos (252 dias úteis; rf=0.04; CVaR 0.95; VaR modificado=Cornish-Fisher; alias `volatility_garch→conditional_volatility`; relabel regime). Os contratos completos (returns-risk, holdings/top, style-drift, research/funds, peers, risk/timeseries, entity-analytics, active-share, institutional-reveal, reverse-lookup, research/scatter) estão capturados na auditoria e serão transcritos como schemas Pydantic v2 no plano de cada fase. Pontos de atenção:
- `entity-analytics`: `risk_statistics`, `drawdown{dates,values,worst_periods}`, `capture{up/down}`, `rolling_returns.series[1M/3M/6M/1Y]`, `distribution{bin_edges,bin_counts,var_95,cvar_95,skewness,kurtosis}`, `return_statistics`, `tail_risk{var_parametric_90/95/99, var_modified_95/99, etl_95, starr, rachev, jarque_bera}`, `insider_data|null`.
- `risk-timeseries`: drawdown e conditional_volatility em `*100`; regime em `{time,value,regime}`.
- `research/scatter`: arrays colunares paralelos por índice.

---

## 7. Evolução de schema (TimescaleDB Cloud, via Tiger MCP — NÃO alembic local)

- **Estender `fund_risk_latest_mv`** com `volatility_garch`, `vol_model`, `cvar_99_evt`/`cvar_999_evt`/`evt_xi_shape`, métricas de classe (0012) e campos de fator. `REFRESH MATERIALIZED VIEW CONCURRENTLY`.
- **Nova view `fund_holdings_history_v`** sobre `sec_nport_holdings` (todos os `report_date`, sector weight por trimestre) para style-drift.
- **Tier C (P7)**: novas tabelas `sec_13f_holdings`, `curated_institutions`, `sec_managers`, `sec_insider_sentiment` (criadas/escritas pelos workers novos no repo datalake-workers; promovidas a hypertable quando aplicável).
- Avaliar (provavelmente desnecessário) novas CAGGs para janelas muito longas.
- Padrões: advisory lock + `REFRESH CONCURRENTLY` (já usados no projeto); migrations idempotentes.

---

## 8. Decomposição em fases (cada fase → seu próprio plano via `writing-plans`)

| Fase | Entregável | Depende de |
|---|---|---|
| **P0** | Setup worktree (feito) + `npm i highcharts`; `HighchartsChart` + `HighchartsStockChart` + `hc/theme.ts` + testes de wrapper; baseline verde | — |
| **P1** | Portar os 17 builders ECharts → `hc/*` (paridade visual/funcional, componente a componente, com testes puros) e trocar os consumidores | P0 |
| **P2** | Reescrever `InteractiveChart` sobre Highcharts Stock (preço, range→refetch, desenho via annotations, indicadores, live-ticks via addPoint); aposentar `ixchart` | P0, (P3 p/ refetch) |
| **P3** | Profundidade: `fetchFundTimeseries`/`fetchStockTimeseries`; charts usam `/timeseries` CAGG; parametrizar `NAV_WINDOW_DAYS`; regen openapi | — |
| **P4** | Backend Tier A (`/funds/{id}/analysis`, `/holdings/top`, `/peers`, `/scatter`) + shell da IA de dossier (abas) | P1 |
| **P5** | Backend Tier B (`/factors`, `/style-drift`, `/entity-analytics`, `/risk-timeseries`, `/active-share`; estender MV) + abas/modais (Performance/Holdings/Style/Factors/Peers/Deep Analysis) | P4 |
| **P6** | Caching: route handlers + `unstable_cache`/revalidate + SSR prefetch/`HydrationBoundary` | P4 |
| **P7** | Tier C: workers `thirteenf_ingestion` + `insider_ingestion` (repo datalake-workers) + tabelas + endpoints institutional-reveal/reverse-lookup/insider; ligar os 5 painéis | P5 |
| **P8** | Remover `echarts`/`ixchart`/builders antigos/`price.ts`; regen final de contrato; limpeza | P1, P2, P5 |

Fases P1, P2, P3 e P4(parcial) podem ser paralelizadas (subagent-driven) por terem baixa interdependência.

---

## 9. Estratégia de testes

- **Builders (`hc/*`)**: testes puros Vitest (mesma disciplina dos adapters de grid) — dado fixo → opção esperada (séries, eixos, cores de token, casos `null`/vazio).
- **Wrappers**: testes de render/lifecycle (mount/update/destroy, reflow, empty/loading) com jsdom.
- **Backend**: testes por endpoint (shape do contrato, janelas de range, casos sem NAV/holdings, paridade numérica com fórmulas do legado: 252d, rf=0.04, Cornish-Fisher).
- **Workers (P7)**: testes de parse de fixtures 13F/Form 4.
- **Gate**: lint + typecheck + Vitest (frontend) + pytest (backend) verdes antes de cada merge. Baseline conhecida: 18 falhas pré-existentes em `statistics` (não-charts) — não regredir além disso.
- **Visual check**: snapshot/visual no browser por aba do dossier (light/dark) antes do merge final.

---

## 10. Riscos e mitigações

- **Paridade visual ECharts→Highcharts**: heatmap (colorAxis), regime strip (xrange) e drift bands (markArea→plotBands) são os mais sensíveis. Mitigar com testes de builder + visual check.
- **Stock substituindo `ixchart`**: ferramentas de desenho e live-ticks são o maior risco de regressão (o `ixchart` é 818 linhas de comportamento custom). Mitigar com P2 isolado + testes de interação.
- **GARCH on-the-fly vs worker**: divergência numérica possível; replicar params do worker (`arch` GARCH(1,1)/EWMA 0.94 fallback) e testar contra o latest persistido.
- **Regime contínuo ausente**: documentar divergência (faixa binária vs `p_high_vol`); não inventar probabilidade.
- **Tier C (SEC parsing)**: 13F/Form 4 são pipelines novos e frágeis; isolar em P7, com empty-states garantindo que o dossier funcione sem eles.
- **Bundle size**: Highcharts Core+Stock+módulos é pesado; usar `import()` dinâmico (já no design) e carregar Stock/indicadores só onde usados.
- **Cache + dado fresco**: `revalidate`/tags devem invalidar em refresh de métricas (cron 07:00 UTC) para não servir séries velhas.

---

## 11. Fora de escopo

- Reimplementar o motor de live-feed/WebSocket (`client.ts`/`useLiveTicks.ts` permanecem; só muda o consumidor do chart).
- Migrar o `@highcharts/grid-pro` (tabelas) — já está em produção e é ortogonal.
- Recalcular métricas no Light (continua read-only; cálculo é dos workers).
- Money-market (N-MFP) metrics (fora do escopo dos workers atuais).

---

## 12. Próximos passos

1. Revisão deste spec pelo dono.
2. `writing-plans` para gerar o plano de implementação detalhado da **P0** (e sequenciar P1–P3 paralelas).
3. Execução subagent-driven na worktree `feat/highcharts-charts-migration`.
