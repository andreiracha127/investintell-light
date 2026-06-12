# Funds detail com chart interativo + Compare com autocomplete — Design

**Data:** 2026-06-12
**Branch:** `feat/stocks-redesign` (continuação do stocks-redesign)
**Spec anterior:** `2026-06-12-stocks-redesign-design.md` (IXChart, livefeed, /stocks)

## Objetivo

Replicar no detalhe do fundo (`/funds/[id]`) o modelo do detalhe de ação: chart
interativo IXChart no lugar do NAV chart estático (ECharts). ETFs negociam em
bolsa — têm OHLCV real e live price — e portanto usam exatamente o fluxo de
stocks; mutual funds/MMF só têm NAV diário e usam o chart em modo linha/área.
Além disso, o campo Compare dos dois charts (stocks e funds) ganha um dropdown
de sugestões estilo Barchart, alimentado por um endpoint único de busca.

## Decisões (com o usuário)

1. **Escopo Funds:** só o detalhe `/funds/[id]` — a landing `/funds` (tabela
   filtrada server-driven) permanece como está.
2. **ETF = stocks:** fund_type `etf` (ticker negociado) usa OHLCV ajustado e
   live ticks, chart completo (candles/OHLC/volume/RSI/etc).
3. **Mutual fund/MMF = NAV:** chart em modo `nav` — toolbar esconde
   Candles/OHLC/VOL; default Line; mantém D/W/M, ranges, SMA20/50, RSI, log/%,
   compare e desenhos; sem subscribe de livefeed.
4. **Compare:** endpoint único `GET /search/symbols` buscando ações E fundos;
   o dropdown entra no Compare do chart de stocks e no de funds.

## Backend

### `GET /funds/{instrument_id}/history?bars=` (novo)

Mesmo contrato do `/stocks/{ticker}/history`, mais um discriminador:

```json
{ "ticker": "VFIAX", "mode": "nav", "count": 1260,
  "bars": [{ "t": 0, "o": 0, "h": 0, "l": 0, "c": 0, "v": 0 }] }
```

- Resolve o fundo por `instrument_id` (404 se não existir).
- **ETF** (critério: `fund_type == "etf"` e ticker presente): delega ao mesmo
  caminho dos stocks — `ensure_eod` + selector OHLCV ajustado de `eod_prices`;
  `mode: "ohlcv"`.
- **Demais** (mutual_fund, mmf, ou ETF sem cobertura Tiingo → fallback): série
  NAV completa de `fund_nav` (sem decimação), `o=h=l=c=nav`, `v=0`;
  `mode: "nav"`. Recorte: `bars` mais recentes (default 2520, ge=30 le=5000).
- 404 quando não há nenhuma série (nem eod_prices nem fund_nav).

### `GET /search/symbols?q=&limit=` (novo)

- `q` min 1 char (trim); `limit` default 10, le=25. Sem chamadas Tiingo.
- Busca case-insensitive por prefixo de ticker OU substring de nome em:
  - `universe_constituents` (status active) → `kind: "stock"`;
  - `funds` com ticker não-nulo → `kind` = fund_type (`etf`, `mutual_fund`,
    `mmf`), inclui `instrument_id`.
- Resposta: `[{ "symbol", "name", "kind", "instrument_id" }]`
  (`instrument_id` null para stocks). Ordenação: match exato de ticker
  primeiro, depois prefixo de ticker, depois nome; dedup por symbol — quando
  o mesmo ticker aparece no universe E em funds (caso típico: ETF), a linha
  do fund vence, pois carrega `instrument_id` e o `kind` mais específico.
- Prefixo `/search/symbols` entra em `CACHED_GET_PREFIXES`? NÃO — query muda a
  cada tecla; o cache de catálogo indexa por URL completa e viraria churn.
  Fica sem cache (a query é barata: ILIKE em duas tabelas locais pequenas).

## Frontend

### `InteractiveChart` — prop `mode`

```ts
mode?: "ohlcv" | "nav"   // default "ohlcv" (comportamento atual)
```

- `mode="nav"`: TYPES reduzido a Line/Area (default `line`), grupo VOL
  removido (RSI fica), botão LIVE removido e sem `subscribeTicks`.
- `mode="ohlcv"`: comportamento atual intacto.

### `FundProfileView`

- O `Card` do NAV (EChart `buildFundNavOption`) é substituído pelo
  `InteractiveChart`:
  - query `["fund-history", instrumentId]` → `fetchFundHistory(instrumentId)`;
  - `mode` vem da resposta (`data.mode`), `symbol` = ticker do fundo (para o
    livefeed no caso ETF);
  - range local (useState, default `1Y`) — o profile não tem ranges hoje, o
    chart ganha os presets 1M/6M/1Y/5Y/MAX próprios.
- Risk metrics, holdings e lookthrough permanecem como estão.

### `SymbolSearchInput` (novo componente)

- Props: `value`, `onSelect(item: SymbolSearchResult)`, `onClear()`,
  `placeholder`.
- Comportamento: debounce 250ms → `fetchSymbolSearch(q)`; dropdown com até 10
  itens `TICKER — Nome (tipo)`; teclado ↑/↓/Enter/Esc; clique fora fecha;
  Enter sem seleção usa o texto cru (fallback = comportamento atual).
- Substitui o `<input>` livre do Compare no `InteractiveChart`. Ao selecionar:
  - `kind: "stock" | "etf"` → compare via `fetchStockHistory(symbol)`;
  - `kind: "mutual_fund" | "mmf"` → compare via
    `fetchFundHistory(instrument_id)` (barras NAV; comparação é por close,
    funciona igual).

### Client API

- `fetchFundHistory(instrumentId, bars?, signal?)` e
  `fetchSymbolSearch(q, signal?)` + tipos derivados de `paths` (regen
  OpenAPI).

## Testes

- **Backend (TDD):**
  - history: ETF delega ao caminho OHLCV (selector stubado, `mode: "ohlcv"`);
    mutual fund vira barras NAV `o=h=l=c` `mode: "nav"`; 404 sem série;
    validação de `bars`.
  - search: match por prefixo de ticker; match por substring de nome; mistura
    stock+fund ordenada (exato primeiro); `limit`; `q` vazio → 422.
- **Frontend:** o mapeamento NAV→bars é backend, então não há lógica
  financeira nova no client; vitest só se alguma lógica pura for extraída do
  dropdown; typecheck + lint; smoke visual (Playwright): ETF com candles+LIVE,
  mutual fund em linha sem VOL, dropdown do Compare sugerindo e plotando.

## Execução

- Worktree isolado `E:\investintell-light\.worktrees\stocks-redesign`
  (branch `feat/stocks-redesign`) — a working tree principal está em uso por
  outra sessão.
- Backend roda com `uv run` a partir de `<worktree>/backend`; frontend com
  `pnpm` a partir de `<worktree>/frontend` (workspace pnpm na raiz do
  worktree).

## Fora de escopo

- Redesign da landing `/funds`.
- Live NAV para mutual funds (não existe).
- Busca fuzzy/ranking sofisticado no search (prefixo+substring bastam).
