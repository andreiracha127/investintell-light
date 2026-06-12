# Spec — Redesenho da área de Stocks (padrão Barchart)

**Data:** 2026-06-12 · **Status:** aprovado (decisões via AskUserQuestion na sessão de brainstorming)

## Objetivo

Substituir a página única `/stocks/[ticker]` (EOD, chart estático) por uma área de Stocks
em dois níveis, inspirada em barchart.com/stocks:

1. **`/stocks`** — landing de mercado: strip de índices, tabela Market Leaders com tabs,
   painel de setores, botão "+ Portfólio" por linha.
2. **`/stocks/[ticker]`** — detalhe que abre **direto no chart interativo** (sem etapa
   intermediária como no Barchart), com as métricas da ação abaixo do gráfico.

## Decisões aprovadas

| Decisão | Escolha |
|---|---|
| Engine do chart | **Portar IXChart** (canvas, zero deps, do protótipo `design/chart.html` do repo workers) para TS em `src/lib/ixchart/` |
| Fonte de dados REST | **Light backend** (FastAPI) — origem única; WS direto ao livefeed worker |
| Blocos da landing | Leaders (Gainers/Losers/52w H/L), strip de índices, painel de setores, botão add-to-portfolio |
| Intraday | Fase 2 (hypertable ticks). Nesta fase: candles **diários** + tick ao vivo animando o candle do dia |

## Revisão de fonte de dados (descoberta pós-aprovação)

A investigação do schema real mudou a implementação **sem mudar a arquitetura aprovada**
(Light backend continua sendo a origem):

- O data lake (`nav_timeseries`) contém **apenas fundos/ETFs** (`instrument_type='fund'`) —
  não há ações individuais lá.
- O Light **já tem localmente** o universo de ~5.000 ações dos EUA:
  `universe_constituents` (SEC crosswalk), `eod_prices` (OHLCV **com volume**, backfill
  Tiingo) e `screener_metrics`. O overview é servido 100% das tabelas locais.
- **"Most Active" volta ao escopo**: foi excluído na decisão por exigir volume no repo
  workers — premissa falsa, `eod_prices.volume` já existe localmente. Custo zero.
- **Setor**: `sec_cusip_ticker_map` (data lake, replicada do projeto allocation) já mapeia
  ticker→GICS para ~7.000 tickers nos 11 setores. O enriquecimento vira uma coluna
  `sector` em `universe_constituents` + script de sync — **sem chamadas SEC novas e sem
  tocar no repo workers**.

O repo `investintell-datalake-workers` **não é alterado** nesta fase (o livefeed WS já
está em produção: `wss://livefeed-production-2c39.up.railway.app/stream`).

## Backend (FastAPI, investintell-light)

- `GET /stocks/overview` — um payload para a landing inteira:
  `{ as_of, universe_size, indices, most_active, gainers, losers, highs_52w, lows_52w, sectors }`.
  - Leaders de `eod_prices` ⋈ `universe_constituents(status='active')`: dois últimos
    closes por ticker (% dia), extremos 52w, volume do dia.
  - Piso de liquidez nas tabelas rankeadas: `close ≥ $5` e dollar volume ≥ $5M.
  - Índices SPY/QQQ/DIA/IWM: warm via `ensure_eod` (caminho existente) + sparkline 30d.
  - Setores: mediana do % dia por `sector` (linhas líquidas); `sectors: []` enquanto o
    enriquecimento não rodar — o frontend oculta o painel.
  - Cache: prefixo `/stocks/overview` no middleware de catálogo existente.
  - Universo vazio (deploy sem backfill) → 200 com listas vazias, não 5xx.
- `GET /stocks/{ticker}/history?bars=N` — OHLCV diário cru no contrato do
  `CHART_ARCHITECTURE.md`: `{t,o,h,l,c,v}` com `t` em epoch ms UTC. Reusa
  `ensure_eod` + `_select_ohlcv_rows`. Limitação documentada: OHLC cru (consistente com
  ticks ao vivo); splits antigos aparecem sem ajuste.
- Migration `0011`: coluna `sector` (nullable) em `universe_constituents` +
  `scripts/enrich_sectors.py` (lê `sec_cusip_ticker_map` do data lake via DSN já
  configurado, `mode()` por ticker, UPDATE local).

## Frontend (Next.js 15, investintell-light)

- **Port IXChart** → `src/lib/ixchart/{types,tokens,series,engine,livefeed}.ts`:
  - `series.ts`: funções puras (resample D/W/M, SMA, RSI, niceTicks, formatadores) —
    unit-tested (vitest, novo dev-dep).
  - `tokens.ts`: lê os mesmos CSS custom properties do `chartColors()` (reage a
    tema/accent/density).
  - `engine.ts`: classe `Chart` portada do protótipo (pan/zoom/crosshair/drawing/
    overlays/compare/log/%); dados sintéticos e fetch de métricas do protótipo são
    **removidos** — barras entram por `setBars()`.
  - `livefeed.ts`: cliente WS sem simulador; **ticks `source:"sim"` são ignorados** —
    fora do pregão a UI mostra EOD honesto, nunca preço fake. Reconexão com backoff.
- `src/components/charts/InteractiveChart.tsx` — wrapper React client-only (canvas +
  toolbar: tipo/período/range/overlays/painéis/escala/compare/desenho) + legenda OHLC.
- `src/lib/livefeed/useLiveTicks.ts` — **um** WebSocket compartilhado por aba
  (subscribe aditivo/unsubscribe, protocolo do worker), updates com throttle rAF.
- Landing `/stocks`: `page.tsx` + `MarketOverview` (TanStack Query no overview) =
  `IndexStrip` + `LeadersTable` (tabs, preços live, link p/ detalhe, `AddToPortfolio`)
  + `SectorPanel` (oculto se vazio).
- Detalhe: `StockAnalysisView` refatorada — header com preço live (flash gain/loss),
  `InteractiveChart` full-width no topo (history `bars=2520`), card estático
  "Price · OHLC + Volume" removido, range switcher migra para a toolbar do chart;
  demais blocos (KPIs, cumulative, rolling, histograma, stats, news) preservados.
- Nav (`AppShell`): "Stock Analysis" → **"Stocks"**, href `/stocks`.
- Env: `NEXT_PUBLIC_LIVEFEED_WS_URL` (sem ela, tudo degrada para EOD puro).

## Estados e erros

- Falha/ausência do WS → badge "EOD", zero quebra (chart e tabelas funcionam com REST).
- 404 ticker / falhas de análise seguem `StatePanel` + retry existentes.
- Skeletons no padrão atual para landing e detalhe.

## Testes

- Backend: ranking puro (`rank_overview`) unit-tested; rotas `overview`/`history` com
  service stubado (padrão `test_macro_regime_route.py`); cache do overview.
- Frontend: vitest para `series.ts` e parser de tick; `typecheck` + `lint`;
  smoke visual Playwright nas duas rotas.

## Fora de escopo (fase 2)

Hypertable `ticks` + candles intraday 1m/5m; worker REST `/metrics`; re-sort live da
tabela de leaders; ajuste de splits no history.
