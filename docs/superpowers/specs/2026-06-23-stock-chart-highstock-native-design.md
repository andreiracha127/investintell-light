# Stock Chart — migração para Highcharts Stock 100% nativo

**Data:** 2026-06-23
**Escopo:** chart de ações na página de stocks (`StockAnalysisView`). NÃO inclui o chart de fundos (NAV), que ganhará componente próprio em sessão futura.

## Problema

O `InteractiveChart` atual é uma colcha de retalhos: usa Highcharts Stock como motor, mas reimplementa à mão recursos que o Highstock tem nativos, e os dois lados brigam. Três falhas observadas, todas com a mesma raiz:

1. **Comparação deforma o gráfico.** A série de comparação é buscada com 2520 dias fixos (~10 anos) em `InteractiveChart.tsx:122`, enquanto a série principal está limitada à janela do range. Com o `rangeSelector` nativo desligado (`priceStock.ts:605`) e nada fixando `xAxis.min/max`, o eixo X mostra a união (2017–2026) e esmaga a série principal; o `compare:"percent"` usa como base o início dessa janela inteira, explodindo o eixo Y ("Change" −200…1200).
2. **Anotações/desenhos não funcionam.** O stock-tools e annotations nativos carregam, mas `chart.update(options, true, true, false)` (`HighchartsStockChart.tsx:84`) roda a cada clique de qualquer controle e o redesenho atropela bindings/anotações.
3. **Live não atualiza.** Live custom (`applyTickToLiveChart`) compete com esse `update()` completo; fora do pregão não há ticks reais (ticks `source:"sim"` são descartados por design).

A "mistura": SMA/RSI calculados à mão (port do ixchart, `priceStock.ts:122-152`), resample D/W/M custom, range custom (botões + refetch), compare custom — tudo reimplementando o nativo. Migrar para Highstock nativo elimina a classe inteira de bugs.

**Viabilidade confirmada:** os módulos de indicadores nativos ESM existem (`highcharts/esm/indicators/indicators-all.js` + individuais). O "indicadores falham sob ESM" registrado em sessões antigas era path de import desatualizado; o wrapper já importa de `highcharts/esm/...` com sucesso.

## Decisões (aprovadas)

- **UI:** nativa do Highstock (rangeSelector, navigator, stock-tools GUI para desenho/anotações, menu de indicadores nativo), como os demos oficiais.
- **Recursos preservados:** todos têm equivalente nativo — live (demo live-candlestick), compare (demo compare), estilização on-brand (demo stock-css-design), intraday/area (demo intraday-area, capacidade futura).
- **Dados:** histórico **diário completo** carregado uma vez; rangeSelector/navigator fazem zoom e `dataGrouping` no client; live atualiza o último bar via `addPoint`. Sem intraday novo (arquitetura suporta depois).
- **Estratégia:** componente **novo e isolado** para stocks; `InteractiveChart` antigo permanece servindo fundos (NAV) até a sessão do chart de fundos.
- **Estilização:** **híbrido** — cores das séries via `ChartColors`/tema (JS, consistente com os 16 builders `hc/`); CSS dedicado para vestir a chrome nativa (rangeSelector, stock-tools, navigator, popups) na paleta bordô. NÃO adotar `styledMode` total (afetaria o tema global e os demais charts).

## Arquitetura

Três peças novas em `frontend/src/`:

### `components/charts/StockChart.tsx`
Wrapper fino do Highstock nativo, no molde do `HighchartsStockChart` atual: importa `highcharts/esm/highstock.js` e registra os módulos ESM (`indicators/indicators-all.js`, `stock-tools.js`, `annotations.js`, `highcharts-more.js`), cria via `stockChart`, `reflow` no resize, `destroy` no unmount.

Diferença-chave: cria o chart **uma vez** e empurra mudanças via API nativa (`addSeries`/`series.update`/`series.setData`/`addPoint`) em vez de `chart.update(options, …)` a cada clique — é isso que hoje atropela anotações e live. As mudanças reativas (tipo de série, toggle de pane, compare, escala) são aplicadas cirurgicamente por `useEffect` que diffeia contra o estado anterior.

### `lib/charts/hc/stock.ts`
Builder puro que monta as `Options` nativas iniciais: rangeSelector (botões 1M/6M/1Y/5Y/MAX casados com os presets das KPIs), navigator, scrollbar, `stockTools.gui` com o catálogo de indicadores (`indicators-all`), eixos de preço/volume/RSI, tooltip, e `navigation.iconsURL` self-hosted (`/highcharts/gfx/stock-icons/`). Substitui `priceStock.ts` — sem `resampleBars`/`smaValues`/`rsiValues`/compare custom (tudo nativo).

### `lib/charts/hc/stockLive.ts`
Helper puro de live, padrão do demo live-candlestick: dado o último ponto da série e um tick, decide append (novo dia) vs update (mesmo dia) e retorna a instrução para `series.addPoint`/`point.update`. Substitui `priceStockLive.ts`. Lógica pura testável; o side-effect (chamar a API do chart) fica no componente.

### Consumidor: `StockAnalysisView.tsx`
Troca `InteractiveChart` por `StockChart`. Passa a buscar o **histórico diário completo** (teto longo / MAX) uma vez, em vez de refetch por range. O `range` (state) deixa de alimentar os bars e passa a ser **emitido pelo rangeSelector nativo**: ao mudar o range/zoom, o `StockChart` chama um callback `onRangeChange(preset)` que recarrega **somente as KPIs/estatísticas** (Total Return, Drawdown, Volatilidade). Sincronia chart↔KPIs preservada, sem refetch de bars.

## Mapeamento custom → nativo

| Recurso | Hoje (custom) | Novo (nativo) |
|---|---|---|
| Tipo (candles/OHLC/line/area) | toolbar custom + rebuild | `series.update({ type })` |
| SMA/EMA/RSI/MACD/Bollinger… | cálculo manual (ixchart) como linhas | módulos nativos via `linkedTo` + GUI (`indicators-all`) |
| Volume | série column custom | pane nativo |
| Desenho/anotações | stock-tools (apagado pelo `update()`) | stock-tools + annotations, sem `update()` destrutivo |
| Compare multi-símbolo | séries manuais, janelas divergentes | `series.compare="percent"`, mesma janela |
| Range | botões custom + refetch backend | rangeSelector nativo (client zoom) |
| Escala % / Log | flags custom | `compare:"percent"` / `yAxis.type` |
| Live | `applyTickToLiveChart` vs `update()` | `addPoint`/`point.update` |

## Fluxo de dados

1. `StockAnalysisView` busca o histórico diário completo do símbolo (uma vez; cache por ticker).
2. `StockChart` monta o chart nativo com esses bars; rangeSelector aplica a janela inicial (ex. 1Y).
3. Usuário muda o range pelos **botões do rangeSelector** (1M/6M/1Y/5Y/MAX, mapeados 1:1 aos presets de KPI) → zoom client-side instantâneo no chart + callback emite o preset → `StockAnalysisView` recarrega só as estatísticas. Zoom livre pelo navigator/arrasto NÃO dispara refetch de KPI (mantém o preset do último botão), evitando o "snap para MAX" que afligia o código antigo ao inferir preset dos extremes.
4. Compare: busca do símbolo adicional (mesma janela completa) → `addSeries` com `compare:"percent"`.
5. Live: `subscribeTicks(symbol)` → helper `stockLive` decide append/update → API do chart. Degrada para EOD sem feed.

## Estados e erros

- Empty (sem histórico): overlay "No price history".
- Loading: placeholder até cores/dados prontos.
- Live sem feed: silencioso, fica no último close. WebSocket usa o `closeSocket` seguro já corrigido (não fecha em CONNECTING).
- Compare com símbolo sem dados: ignora a série, mantém o chart.

## Testes

- `lib/charts/hc/stock.ts` (puro): montagem de séries por tipo, eixos por pane, opções de compare/range/escala, rangeSelector. Vitest node.
- `lib/charts/hc/stockLive.ts` (puro): lógica append-vs-update, boundary de dia, tick fora de ordem. Vitest node.
- `components/charts/StockChart.tsx`: smoke test jsdom mínimo (cria/destrói, expõe `onReady`), no padrão dos wrappers atuais, com `WebSocket`/import dinâmico mockados.

## Limpeza

Nada é removido agora. Quando os fundos migrarem para o chart próprio, remover numa única limpeza: `InteractiveChart.tsx`, `priceStock.ts`, `priceStockLive.ts` (+ testes). Até lá, coexistem isolados.

## Fora de escopo

- Chart de fundos / modo NAV (sessão futura).
- Intraday real (1m/5m) — arquitetura suporta, mas depende de feed intradiário no backend.
- `styledMode` total.
