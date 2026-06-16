# Design — Charts P2: Price chart em Highcharts Stock

- **Data:** 2026-06-15
- **Base confirmada:** `main` em `35c352e` (`Merge branch 'feat/highcharts-charts-migration' — Highcharts charts P0+P1`)
- **Escopo:** migrar o price chart `InteractiveChart` / canvas `ixchart` para Highcharts Stock.
- **Status:** aprovado em brainstorming. Proximo passo: `writing-plans`.

---

## 1. Objetivo

Reescrever `frontend/src/components/charts/InteractiveChart.tsx` para usar
Highcharts Stock como engine principal, preservando as features do chart atual
e ampliando o compare para multiplos simbolos simultaneos.

O P2 troca os consumidores de price chart para Highcharts Stock, mas nao remove
`frontend/src/lib/ixchart/*`. O engine canvas deve coexistir ate a fase futura
de limpeza.

---

## 2. Decisoes aprovadas

### D1 — Stock-first nativo

Highcharts Stock passa a ser a fonte de verdade para comportamento de chart
interativo. O objetivo nao e preservar pixel-a-pixel a UX do canvas, e sim usar
o comportamento profissional padrao do Stock para performance e facilidade de
integracao.

### D2 — Desenho via `stock-tools` nativo

As ferramentas de desenho usam a GUI nativa do modulo `stock-tools`. A toolbar
custom atual deixa de tentar controlar `Trend`, `Horizontal`, `Fib`, `Measure`,
`Undo` e `Clear`.

Graphite continua importante no tema-base do chart, mas a integracao visual da
GUI nativa de desenho nao e prioridade sobre performance, robustez e menor
codigo proprio.

### D3 — D/W/M via `dataGrouping` nativo

Os modos diario/semanal/mensal devem ser implementados com data grouping do
Highcharts Stock, nao com `resample()` no React. Isso reduz transformacao
manual e deixa candles/linhas agrupados sob responsabilidade do Stock.

### D4 — Compare multi-simbolo

O compare deixa de aceitar apenas um ativo por vez. Cada selecao via
`SymbolSearchInput` adiciona uma serie comparativa, removivel individualmente.
As comparacoes podem ser stocks, ETFs, mutual funds ou MMFs, mantendo o ganho de
`funds-chart-compare`.

---

## 3. Arquitetura

### 3.1 `HighchartsStockChart.tsx`

O wrapper Stock deve espelhar o padrao ESM ja usado no wrapper Core:

- importar `highcharts/esm/highstock.js` dinamicamente no client;
- registrar modulos ESM antes de criar o chart;
- aplicar `highchartsTheme(chartColors())` antes de `stockChart`;
- criar o chart uma vez, atualizar com `chart.update(options, true, true)`,
  chamar `reflow()` via `ResizeObserver` e destruir no unmount;
- expor `onReady(chart)` para a ponte imperativa de live ticks.

Modulos esperados para P2:

- `highcharts/esm/indicators/indicators.js`;
- `highcharts/esm/indicators/rsi.js`;
- `highcharts/esm/modules/annotations.js`;
- `highcharts/esm/modules/stock-tools.js`;
- modulos auxiliares se o build exigir para drag/edit de annotations.

Nao usar bundles UMD `highcharts/modules/*` nem `highcharts/indicators/*`, pois
o P1 ja confirmou que o Turbopack precisa do build ESM para auto-registro no
mesmo singleton de Highcharts.

### 3.2 Builder puro de opcoes

Criar um builder puro, provavelmente em
`frontend/src/lib/charts/hc/priceStock.ts`, que recebe dados e estado do chart
e retorna `Highcharts.Options`.

Responsabilidades do builder:

- transformar barras OHLCV em series Stock;
- selecionar `candlestick`, `ohlc`, `line` ou `area`;
- desabilitar tipos OHLC em `mode="nav"`;
- configurar axes/panes para price, volume e RSI;
- configurar SMA20/SMA50 como series `sma` ligadas a serie principal;
- configurar RSI como serie `rsi` em pane dedicado;
- configurar volume como `column` em eixo proprio para `mode="ohlcv"`;
- configurar compare multi-simbolo como series adicionais;
- aplicar `yAxis.type = "logarithmic"` quando log estiver ativo;
- aplicar compare/percent nativo do Stock quando `%` estiver ativo;
- configurar range selector, navigator, scrollbar e data grouping;
- conectar `xAxis.events.afterSetExtremes` ao callback de range sync;
- retornar empty state previsivel quando nao houver dados.

O builder nao acessa DOM, nao chama API e nao toca WebSocket. Deve ser testavel
em Vitest `.test.ts`.

### 3.3 `InteractiveChart.tsx`

`InteractiveChart` vira uma camada React de orquestracao:

- mantem props publicas atuais quando possivel:
  `symbol`, `bars`, `range`, `onRangeChange`, `mode`, `className`;
- controla tipo, D/W/M, indicadores, escala log/%, compare e live;
- usa TanStack Query para buscar historico de cada compare;
- monta opcoes via builder puro e renderiza `HighchartsStockChart`;
- guarda o chart em ref via `onReady`;
- assina `subscribeTicks(symbol, ...)` quando `live=true` e `mode="ohlcv"`;
- aplica ticks ao chart por API imperativa do Highcharts.

O componente continua sendo client-only e nao altera auth, fetchWithAuth ou
backend.

---

## 4. Comportamento esperado

### 4.1 Tipo de serie

Em `mode="ohlcv"`:

- candles;
- OHLC;
- line;
- area.

Em `mode="nav"`:

- line;
- area.

Se o modo mudar para `nav` enquanto o tipo atual for candle/OHLC, o componente
deve cair para `line`.

### 4.2 Periodo D/W/M

D/W/M altera data grouping nativo:

- `D`: agrupamento diario ou sem agrupamento forcado;
- `W`: agrupamento semanal;
- `M`: agrupamento mensal.

O P2 nao deve chamar `resample()` para preparar as series principais. O modulo
canvas pode continuar existindo, mas nao deve ser importado pelo novo price
chart exceto por tipos compartilhados se o plano decidir que isso e aceitavel.

### 4.3 Range presets e navigator

Os botoes `1M`, `6M`, `1Y`, `5Y`, `MAX` continuam visiveis e chamam
`xAxis.setExtremes` no chart.

Navigator, scrollbar e rangeSelector nativos tambem ficam disponiveis. Quando o
usuario muda a janela por navigator, rangeSelector, zoom ou pan, o
`afterSetExtremes` calcula a largura visivel e chama `onRangeChange` com o
preset mais proximo. Isso preserva a sincronizacao das metricas da pagina.

### 4.4 Indicadores

SMA20 e SMA50 sao series `sma` ligadas a serie principal. RSI usa a serie
`rsi`, em eixo/pane dedicado. Volume usa uma serie `column`, em eixo/pane
dedicado, apenas para `mode="ohlcv"`.

O estado default deve preservar a intencao atual:

- SMA20 ligado;
- SMA50 desligado;
- volume ligado em OHLCV;
- RSI desligado.

### 4.5 Log e percentual

Log e percentual continuam mutuamente exclusivos.

- Log configura o eixo de preco como `type: "logarithmic"`.
- Percentual usa o mecanismo nativo do Stock para comparar em `%`.

Com comparacoes ativas, `%` pode ser automaticamente ligado ou recomendado pela
UI, mas o plano deve escolher uma regra explicita e testavel para evitar
surpresas.

### 4.6 Compare multi-simbolo

`SymbolSearchInput` passa a adicionar uma nova comparacao em vez de substituir a
anterior. Cada compare deve aparecer como chip removivel.

Regras:

- evitar duplicatas por chave estavel (`kind + symbol + instrument_id`);
- preservar stocks/ETFs via `fetchStockHistory`;
- preservar mutual funds/MMFs via `fetchFundHistory`;
- renderizar cada compare como serie `line`;
- limitar a quantidade de comparacoes simultaneas se necessario para
  performance; sugestao inicial: maximo 5.

### 4.7 Live ticks

O live feed permanece o existente:

- `onFeedStatus`;
- `subscribeTicks`;
- `parseTick` descartando simulador.

O P2 muda apenas o consumidor.

Quando chega um tick:

- se ele pertence ao ponto/candle atual, atualizar o ultimo ponto com
  `point.update` ou equivalente;
- se representa um novo bucket de data, adicionar ponto com `series.addPoint`;
- atualizar OHLC e volume do ponto quando o tipo/serie principal for OHLCV;
- manter o status `LIVE`/`EOD` da toolbar;
- nao assinar live em `mode="nav"`.

Em data grouping semanal/mensal, a implementacao deve ser conservadora: atualizar
a serie de dados base e deixar o Stock reagrupar, em vez de tentar recalcular
manualmente o bucket agrupado.

### 4.8 Desenho

O desenho fica sob a GUI nativa de `stock-tools`. O componente deve registrar os
modulos e expor a GUI nativa no chart.

Nao e objetivo do P2 replicar exatamente a toolbar antiga de desenho. Ferramentas
como Fibonacci, measure, trendline, linhas horizontais, edicao e remocao devem
seguir os controles nativos do Stock.

---

## 5. Consumidores

### 5.1 `StockAnalysisView`

Deve continuar passando:

- `symbol={header.ticker}`;
- `bars={historyBars}`;
- `range={range}`;
- `onRangeChange={selectRange}`.

O `onRangeChange` continua atualizando a URL e a query de analytics.

### 5.2 `FundProfileView`

Deve continuar usando `historyQuery.data.mode`:

- ETF ou historico OHLCV: chart Stock com OHLCV e live quando houver ticker;
- mutual fund/MMF NAV: line/area, sem volume e sem live.

O compare multi-simbolo deve funcionar tambem no perfil de fundos.

---

## 6. Validacao

Rodar em `frontend/`:

- `pnpm typecheck`;
- `pnpm lint`;
- `pnpm test`;
- `pnpm build`.

Nota conhecida: existem testes `.test.tsx` do screener que podem falhar por
baseline `jsx: preserve` no Vite React. O P2 deve preferir testes novos puros
`.test.ts` e reportar essa baseline sem mascarar regressao.

Visual check:

- usar demo descartavel com fixtures ou backend local;
- confirmar light e dark;
- confirmar candles, navigator, data grouping D/W/M, ranges, SMA, RSI, volume,
  compare multi-simbolo, log, %, live tick simulado/fixture e stock-tools;
- deletar qualquer demo descartavel antes do commit final.

---

## 7. Riscos e mitigacoes

### R1 — `stock-tools` CSS/DOM

A GUI nativa pode exigir import de CSS, containers ou ajustes minimos para
aparecer corretamente no Next/Turbopack. Mitigacao: tratar como parte da tarefa
do wrapper Stock e validar visualmente.

### R2 — Live tick com agrupamento

Atualizar candles agrupados manualmente e fragil. Mitigacao: atualizar a serie
base e deixar Highcharts reagrupar; se necessario, redraw controlado para evitar
queda de performance.

### R3 — Log, percentual e compare

Essas opcoes interagem no eixo principal. Mitigacao: manter log e `%`
mutuamente exclusivos e cobrir o builder com testes de opcoes.

### R4 — Compare multi-simbolo

Muitas comparacoes podem gerar muitas queries e series. Mitigacao: deduplicar,
limitar quantidade simultanea e usar `staleTime` ja alinhado ao historico.

### R5 — Types Highcharts v13

Algumas opcoes de Stock/indicators podem nao estar perfeitamente expressas nos
tipos importados. Mitigacao: isolar casts no builder, com comentarios curtos
apenas quando o tipo da biblioteca for mais estreito que o runtime.

---

## 8. Fora de escopo

- Remover `frontend/src/lib/ixchart/*`;
- trocar endpoints para `/timeseries?range=` ou resolver profundidade historica
  de P3;
- alterar auth, InsForge, `fetchWithAuth` ou backend;
- remover `echarts`;
- reestilizar profundamente a GUI nativa do `stock-tools`;
- abrir PR nesta etapa de brainstorming.

---

## 9. Plano de implementacao esperado

O proximo passo e `superpowers:writing-plans`, com plano TDD em fatias pequenas:

1. reforcar wrapper Stock e registro ESM de modulos;
2. criar builder puro `priceStock` com testes;
3. migrar `InteractiveChart` para Highcharts Stock;
4. implementar compare multi-simbolo;
5. implementar ponte de live tick;
6. validar consumidores, build e visual check;
7. executar revisao adversarial e commits por tarefa em worktree isolado.
