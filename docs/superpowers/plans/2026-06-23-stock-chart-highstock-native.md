# Stock Chart — Highstock 100% Native Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o chart de ações (`InteractiveChart` no caminho de stocks) por um componente novo 100% Highcharts Stock nativo — rangeSelector, navigator, stock-tools (desenho/anotações), indicadores nativos, compare nativo e live nativo — corrigindo as 3 falhas (compare deforma, anotações não funcionam, live não atualiza).

**Architecture:** Componente novo e isolado (`StockChart`) com builder puro (`stock.ts`) e helper de live puro (`stockLive.ts`). O wrapper cria o `stockChart` uma vez e aplica mudanças via API nativa (não `chart.update` destrutivo). O `InteractiveChart`/`priceStock.ts`/`priceStockLive.ts` permanecem intactos servindo o chart de fundos (NAV) até sessão futura.

**Tech Stack:** Next.js (App Router, Turbopack), React, TypeScript, Highcharts/Highstock 13.0.0 (ESM build), @tanstack/react-query, vitest.

## Global Constraints

- Highcharts **13.0.0**, sempre importado via `highcharts/esm/*` (registra módulos no mesmo singleton; os paths UMD não auto-registram sob Turbopack). Copiar o padrão de `HighchartsStockChart.tsx`.
- Cores via `ChartColors` (JS, lidas de CSS vars em runtime após mount). **NÃO** usar `styledMode` total. CSS custom apenas para a chrome nativa (rangeSelector/stock-tools/navigator/popups).
- **NÃO** modificar `InteractiveChart.tsx`, `priceStock.ts`, `priceStockLive.ts` — servem o chart de fundos (NAV) até sessão futura.
- `HistoryBar = { t: number; o: number; h: number; l: number; c: number; v: number }` (importar de `@/lib/api/client`).
- Testes: vitest. Suites puras no ambiente `node` (default); suites com DOM usam `// @vitest-environment jsdom` na 1ª linha.
- Sem remote git — commits locais na branch `feat/stock-chart-highstock-native` (worktree dedicado).
- Ícones do stock-tools já self-hosted em `public/highcharts/gfx/stock-icons/` (reusar `navigation.iconsURL: "/highcharts/gfx/stock-icons/"`).

---

### Task 0: Setup do worktree

**Files:** nenhum (ambiente).

- [ ] **Step 1: Instalar dependências no worktree**

Run (na raiz do worktree, que contém `pnpm-workspace.yaml`):
```bash
pnpm install
```
Expected: instalação conclui; `frontend/node_modules` populado (symlinks pnpm).

- [ ] **Step 2: Baseline verde**

Run:
```bash
cd frontend && pnpm typecheck && pnpm exec vitest run src/lib/charts/hc/ src/components/charts/
```
Expected: typecheck sem erros; suites de charts existentes passam. Anote qualquer falha pré-existente (não introduzida por este plano).

---

### Task 1: Builder puro `stock.ts` — tipos, dados de série e constantes

**Files:**
- Create: `frontend/src/lib/charts/hc/stock.ts`
- Test: `frontend/src/lib/charts/hc/stock.test.ts`

**Interfaces:**
- Produces:
  - `STOCK_PRICE_ID = "price-main"`, `STOCK_VOLUME_ID = "price-volume"` (string consts)
  - `type StockChartType = "candles" | "ohlc" | "line" | "area"`
  - `type StockScale = { log: boolean; pct: boolean }`
  - `interface StockCompare { key: string; label: string; bars: HistoryBar[] }`
  - `toMainSeriesData(bars: HistoryBar[], type: StockChartType): Array<[number,number] | [number,number,number,number,number]>`
  - `toVolumeSeriesData(bars: HistoryBar[]): Array<[number, number]>`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import {
  STOCK_PRICE_ID,
  STOCK_VOLUME_ID,
  toMainSeriesData,
  toVolumeSeriesData,
} from "./stock";
import type { HistoryBar } from "@/lib/api/client";

const BARS: HistoryBar[] = [
  { t: 1, o: 10, h: 12, l: 9, c: 11, v: 100 },
  { t: 2, o: 11, h: 13, l: 10, c: 12, v: 200 },
];

describe("stock series data", () => {
  it("ids are stable", () => {
    expect(STOCK_PRICE_ID).toBe("price-main");
    expect(STOCK_VOLUME_ID).toBe("price-volume");
  });

  it("candles/ohlc map to [t,o,h,l,c]", () => {
    expect(toMainSeriesData(BARS, "candles")).toEqual([
      [1, 10, 12, 9, 11],
      [2, 11, 13, 10, 12],
    ]);
    expect(toMainSeriesData(BARS, "ohlc")[0]).toEqual([1, 10, 12, 9, 11]);
  });

  it("line/area map to [t,c]", () => {
    expect(toMainSeriesData(BARS, "line")).toEqual([[1, 11], [2, 12]]);
    expect(toMainSeriesData(BARS, "area")[1]).toEqual([2, 12]);
  });

  it("volume maps to [t,v]", () => {
    expect(toVolumeSeriesData(BARS)).toEqual([[1, 100], [2, 200]]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/stock.test.ts`
Expected: FAIL — `stock.ts` não existe / exports não definidos.

- [ ] **Step 3: Write minimal implementation**

```ts
import type { HistoryBar } from "@/lib/api/client";

export const STOCK_PRICE_ID = "price-main";
export const STOCK_VOLUME_ID = "price-volume";

export type StockChartType = "candles" | "ohlc" | "line" | "area";
export type StockScale = { log: boolean; pct: boolean };

export interface StockCompare {
  key: string;
  label: string;
  bars: HistoryBar[];
}

export function toMainSeriesData(
  bars: HistoryBar[],
  type: StockChartType,
): Array<[number, number] | [number, number, number, number, number]> {
  if (type === "candles" || type === "ohlc") {
    return bars.map((b) => [b.t, b.o, b.h, b.l, b.c]);
  }
  return bars.map((b) => [b.t, b.c]);
}

export function toVolumeSeriesData(bars: HistoryBar[]): Array<[number, number]> {
  return bars.map((b) => [b.t, b.v]);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/stock.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/charts/hc/stock.ts frontend/src/lib/charts/hc/stock.test.ts
git commit -m "feat(stock-chart): pure series-data helpers for native stock builder"
```

---

### Task 2: Builder `stock.ts` — `buildStockOptions` (séries, eixos, rangeSelector→KPIs, compare, log, stockTools)

**Files:**
- Modify: `frontend/src/lib/charts/hc/stock.ts`
- Test: `frontend/src/lib/charts/hc/stock.test.ts`

**Interfaces:**
- Consumes (Task 1): `STOCK_PRICE_ID`, `STOCK_VOLUME_ID`, `toMainSeriesData`, `toVolumeSeriesData`, `StockChartType`, `StockScale`, `StockCompare`.
- Consumes: `ChartColors` from `@/lib/charts/chartColors`, `RangePreset` from `@/lib/api/client`.
- Produces:
  - `RANGE_BUTTONS` — array de `{ text: RangePreset } & Highcharts.RangeSelectorButtonsOptions`, na ordem `1M,6M,1Y,5Y,MAX`.
  - `rangeButtonIndexForPreset(p: RangePreset): number`
  - `interface StockOptionsInput { symbol: string; bars: HistoryBar[]; type: StockChartType; scale: StockScale; showVolume: boolean; sma20: boolean; compares: StockCompare[]; colors: ChartColors; selectedRangeIndex: number; onRangeButtonClick?: (preset: RangePreset) => void; }`
  - `buildStockOptions(input: StockOptionsInput): Highcharts.Options`

**Notas de design (para o implementador):**
- A série principal usa `id: STOCK_PRICE_ID`, tipo nativo (`candlestick`/`ohlc`/`line`/`area`), `dataGrouping` habilitado (Highstock agrupa por zoom).
- `SMA20` default ON é uma **série de indicador nativo**: `{ type: "sma", linkedTo: STOCK_PRICE_ID, params: { period: 20 } }`. (O módulo `indicators-all` é carregado pelo wrapper na Task 4.) RSI/MACD/Bollinger/etc. NÃO são pré-montados — o usuário os adiciona pela GUI nativa do stock-tools.
- Compare nativo: `plotOptions.series.compare = scale.pct ? "percent" : undefined`. As séries de compare usam os MESMOS dados completos (mesma janela), então o Highstock alinha tudo no eixo X compartilhado — corrigindo a deformação.
- rangeSelector nativo é a fonte do range das KPIs: `xAxis.events.afterSetExtremes(e)` chama `onRangeButtonClick(e.rangeSelectorButton.text)` **apenas quando** `e.rangeSelectorButton` existe (clique em botão), nunca em zoom livre — evitando o "snap para MAX".

- [ ] **Step 1: Write the failing test (append ao stock.test.ts)**

```ts
import { buildStockOptions, RANGE_BUTTONS, rangeButtonIndexForPreset } from "./stock";
import type { ChartColors } from "@/lib/charts/chartColors";

const COLORS = {
  gain: "#0a0", loss: "#a00", accent: "#900", accentMuted: "#a55",
  accentWash: "#eee", textOnAccent: "#fff", text: "#111", textSecondary: "#333",
  textMuted: "#777", grid: "#ccc", surface: "#fafafa", bar: "#444",
  barMute: "#999", blue: "#06c", amber: "#fa0",
  categories: ["#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8"],
} as unknown as ChartColors;

function baseInput(over: Partial<Parameters<typeof buildStockOptions>[0]> = {}) {
  return {
    symbol: "NVDA",
    bars: BARS,
    type: "candles" as const,
    scale: { log: false, pct: false },
    showVolume: true,
    sma20: true,
    compares: [],
    colors: COLORS,
    selectedRangeIndex: 2,
    ...over,
  };
}

describe("buildStockOptions", () => {
  it("range buttons map 1:1 to KPI presets", () => {
    expect(RANGE_BUTTONS.map((b) => b.text)).toEqual(["1M", "6M", "1Y", "5Y", "MAX"]);
    expect(rangeButtonIndexForPreset("1Y")).toBe(2);
    expect(rangeButtonIndexForPreset("MAX")).toBe(4);
  });

  it("main series uses the chart type and price id", () => {
    const opt = buildStockOptions(baseInput());
    const main = (opt.series ?? []).find((s) => (s as { id?: string }).id === "price-main");
    expect((main as { type?: string }).type).toBe("candlestick");
  });

  it("includes a native SMA20 indicator linked to the price series when sma20=true", () => {
    const opt = buildStockOptions(baseInput({ sma20: true }));
    const sma = (opt.series ?? []).find((s) => (s as { type?: string }).type === "sma");
    expect((sma as { linkedTo?: string }).linkedTo).toBe("price-main");
    expect((sma as { params?: { period?: number } }).params?.period).toBe(20);
  });

  it("omits SMA and volume when toggled off", () => {
    const opt = buildStockOptions(baseInput({ sma20: false, showVolume: false }));
    const types = (opt.series ?? []).map((s) => (s as { type?: string }).type);
    expect(types).not.toContain("sma");
    expect((opt.series ?? []).some((s) => (s as { id?: string }).id === "price-volume")).toBe(false);
  });

  it("sets compare=percent only when scale.pct", () => {
    expect((buildStockOptions(baseInput({ scale: { log: false, pct: true } }))
      .plotOptions?.series as { compare?: string }).compare).toBe("percent");
    expect((buildStockOptions(baseInput())
      .plotOptions?.series as { compare?: string }).compare).toBeUndefined();
  });

  it("uses logarithmic price axis only when scale.log", () => {
    const axes = buildStockOptions(baseInput({ scale: { log: true, pct: false } })).yAxis;
    const price = (axes as Array<{ id?: string; type?: string }>).find((a) => a.id === "price-axis");
    expect(price?.type).toBe("logarithmic");
  });

  it("adds one compare line series per compare entry", () => {
    const opt = buildStockOptions(baseInput({
      compares: [{ key: "AAPL::", label: "AAPL", bars: BARS }],
    }));
    expect((opt.series ?? []).some((s) => (s as { id?: string }).id === "compare-AAPL::")).toBe(true);
  });

  it("emits the preset only for range-button clicks, not free zoom", () => {
    const clicks: string[] = [];
    const opt = buildStockOptions(baseInput({ onRangeButtonClick: (p) => clicks.push(p) }));
    const after = (opt.xAxis as { events?: { afterSetExtremes?: (e: unknown) => void } }).events?.afterSetExtremes;
    after?.call({}, { min: 0, max: 1, rangeSelectorButton: { text: "6M" } });
    after?.call({}, { min: 0, max: 1 }); // free zoom — no button
    expect(clicks).toEqual(["6M"]);
  });

  it("enables stock-tools GUI and self-hosted icons", () => {
    const opt = buildStockOptions(baseInput());
    expect((opt.stockTools?.gui as { enabled?: boolean })?.enabled).toBe(true);
    expect(opt.navigation?.iconsURL).toBe("/highcharts/gfx/stock-icons/");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/stock.test.ts`
Expected: FAIL — `buildStockOptions`/`RANGE_BUTTONS`/`rangeButtonIndexForPreset` não definidos.

- [ ] **Step 3: Write the implementation (append/edit em stock.ts)**

```ts
import type { Options, SeriesOptionsType, YAxisOptions } from "highcharts";
import type { ChartColors } from "@/lib/charts/chartColors";
import type { RangePreset } from "@/lib/api/client";

export const RANGE_BUTTONS: Array<{ text: RangePreset } & Record<string, unknown>> = [
  { type: "month", count: 1, text: "1M" },
  { type: "month", count: 6, text: "6M" },
  { type: "year", count: 1, text: "1Y" },
  { type: "year", count: 5, text: "5Y" },
  { type: "all", text: "MAX" },
];

export function rangeButtonIndexForPreset(p: RangePreset): number {
  const i = RANGE_BUTTONS.findIndex((b) => b.text === p);
  return i >= 0 ? i : RANGE_BUTTONS.length - 1;
}

function nativeSeriesType(type: StockChartType): "candlestick" | "ohlc" | "line" | "area" {
  return type === "candles" ? "candlestick" : type;
}

export interface StockOptionsInput {
  symbol: string;
  bars: HistoryBar[];
  type: StockChartType;
  scale: StockScale;
  showVolume: boolean;
  sma20: boolean;
  compares: StockCompare[];
  colors: ChartColors;
  selectedRangeIndex: number;
  onRangeButtonClick?: (preset: RangePreset) => void;
}

export function buildStockOptions(input: StockOptionsInput): Options {
  const { symbol, bars, type, scale, showVolume, sma20, compares, colors,
    selectedRangeIndex, onRangeButtonClick } = input;

  const yAxis: YAxisOptions[] = [
    {
      id: "price-axis",
      height: showVolume ? "78%" : "100%",
      type: scale.log ? "logarithmic" : "linear",
      opposite: true,
      labels: { align: "left", x: 4 },
      title: { text: scale.pct ? "Change" : "Price (USD)" },
      resize: { enabled: true },
    },
  ];
  if (showVolume) {
    yAxis.push({
      id: "volume-axis",
      top: "80%",
      height: "20%",
      offset: 0,
      opposite: true,
      labels: { align: "left", x: 4 },
      title: { text: "Volume" },
    });
  }

  const series: SeriesOptionsType[] = [
    {
      id: STOCK_PRICE_ID,
      type: nativeSeriesType(type),
      name: symbol,
      data: toMainSeriesData(bars, type),
      yAxis: "price-axis",
      color: colors.accent,
      lineColor: colors.accent,
      upColor: colors.gain,
      upLineColor: colors.gain,
    } as SeriesOptionsType,
  ];
  if (showVolume) {
    series.push({
      id: STOCK_VOLUME_ID,
      type: "column",
      name: "Volume",
      data: toVolumeSeriesData(bars),
      yAxis: "volume-axis",
      color: colors.barMute,
    } as SeriesOptionsType);
  }
  if (sma20) {
    series.push({
      type: "sma",
      linkedTo: STOCK_PRICE_ID,
      name: "SMA 20",
      params: { period: 20 },
      color: colors.categories[2],
      lineWidth: 1,
      marker: { enabled: false },
    } as unknown as SeriesOptionsType);
  }
  compares.forEach((cmp, i) => {
    series.push({
      id: `compare-${cmp.key}`,
      type: "line",
      name: cmp.label,
      data: toMainSeriesData(cmp.bars, "line"),
      yAxis: "price-axis",
      color: colors.categories[(i + 4) % colors.categories.length],
      lineWidth: 1.4,
      marker: { enabled: false },
    } as SeriesOptionsType);
  });

  return {
    chart: { spacingTop: 8, spacingRight: 8, spacingBottom: 8, spacingLeft: 8 },
    rangeSelector: {
      enabled: true,
      selected: selectedRangeIndex,
      buttons: RANGE_BUTTONS as Highcharts.RangeSelectorButtonsOptions[],
      inputEnabled: false,
    },
    navigator: { enabled: true },
    scrollbar: { enabled: true },
    stockTools: {
      gui: {
        enabled: true,
        buttons: [
          "simpleShapes", "lines", "crookedLines", "measure", "advanced",
          "toggleAnnotations", "separator", "verticalLabels", "flags",
          "separator", "indicators", "currentPriceIndicator", "fullScreen",
        ],
      },
    },
    navigation: {
      bindingsClassName: "highcharts-bindings-container",
      iconsURL: "/highcharts/gfx/stock-icons/",
    },
    xAxis: {
      ordinal: true,
      events: {
        afterSetExtremes(e: { rangeSelectorButton?: { text?: string } }) {
          const text = e.rangeSelectorButton?.text;
          if (text && onRangeButtonClick) onRangeButtonClick(text as RangePreset);
        },
      },
    },
    yAxis,
    plotOptions: {
      series: {
        compare: scale.pct ? "percent" : undefined,
        dataGrouping: { enabled: true },
        marker: { enabled: false },
        turboThreshold: 0,
      },
      candlestick: {
        color: colors.loss, upColor: colors.gain,
        lineColor: colors.loss, upLineColor: colors.gain,
      },
      ohlc: { color: colors.loss, upColor: colors.gain },
      area: { fillColor: `${colors.accent}24`, threshold: null },
    },
    series,
    credits: { enabled: false },
    accessibility: { enabled: false },
  };
}
```

Nota: `Highcharts` namespace types — adicionar `import type Highcharts from "highcharts";` se `RangeSelectorButtonsOptions` for referenciado; ou simplificar o cast para `as unknown as NonNullable<Options["rangeSelector"]>["buttons"]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/stock.test.ts`
Expected: PASS (todos os testes de buildStockOptions + Task 1).

- [ ] **Step 5: Typecheck e commit**

```bash
cd frontend && pnpm typecheck
git add frontend/src/lib/charts/hc/stock.ts frontend/src/lib/charts/hc/stock.test.ts
git commit -m "feat(stock-chart): native buildStockOptions (rangeSelector, compare, sma, stocktools)"
```

---

### Task 3: Helper de live puro `stockLive.ts`

**Files:**
- Create: `frontend/src/lib/charts/hc/stockLive.ts`
- Test: `frontend/src/lib/charts/hc/stockLive.test.ts`

**Interfaces:**
- Consumes (Task 1): `STOCK_PRICE_ID`, `STOCK_VOLUME_ID`, `toMainSeriesData`, `toVolumeSeriesData`, `StockChartType`.
- Produces:
  - `interface LiveTickInput { price: number; size: number; timeMs: number }`
  - `interface MergeResult { bars: HistoryBar[]; appended: boolean }`
  - `parseTickTimeMs(time: string, fallback?: number): number`
  - `mergeTickIntoBars(bars: HistoryBar[], tick: LiveTickInput): MergeResult`
  - `applyTickToStockChart(args: { chart: import("highcharts").Chart; bar: HistoryBar; appended: boolean; type: StockChartType; showVolume: boolean; redraw?: boolean }): void`

**Nota:** lógica equivalente à de `priceStockLive.ts`, mas **independente** (não importa de `priceStock.ts`, que será removido com os fundos). A função pura (`mergeTickIntoBars`/`parseTickTimeMs`) é o foco dos testes; `applyTickToStockChart` é o side-effect (coberto pelo smoke test do wrapper).

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { mergeTickIntoBars, parseTickTimeMs } from "./stockLive";
import type { HistoryBar } from "@/lib/api/client";

const DAY = 86_400_000;
const bars: HistoryBar[] = [{ t: 0, o: 10, h: 12, l: 9, c: 11, v: 100 }];

describe("parseTickTimeMs", () => {
  it("parses ISO, falls back on junk", () => {
    expect(parseTickTimeMs("1970-01-01T00:00:00Z")).toBe(0);
    expect(parseTickTimeMs("", 42)).toBe(42);
    expect(parseTickTimeMs("nonsense", 7)).toBe(7);
  });
});

describe("mergeTickIntoBars", () => {
  it("updates the last bar on the same UTC day (no append)", () => {
    const r = mergeTickIntoBars(bars, { price: 13, size: 50, timeMs: 1000 });
    expect(r.appended).toBe(false);
    expect(r.bars).toHaveLength(1);
    expect(r.bars[0]).toMatchObject({ h: 13, l: 9, c: 13, v: 150 });
  });

  it("appends a new bar on a new UTC day", () => {
    const r = mergeTickIntoBars(bars, { price: 20, size: 5, timeMs: DAY + 1000 });
    expect(r.appended).toBe(true);
    expect(r.bars).toHaveLength(2);
    expect(r.bars[1]).toMatchObject({ t: DAY, o: 20, h: 20, l: 20, c: 20, v: 5 });
  });

  it("returns input unchanged when bars is empty", () => {
    expect(mergeTickIntoBars([], { price: 1, size: 1, timeMs: 1 })).toEqual({ bars: [], appended: false });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/stockLive.test.ts`
Expected: FAIL — módulo/exports inexistentes.

- [ ] **Step 3: Write the implementation**

```ts
import type { Chart, Point, Series } from "highcharts";
import type { HistoryBar } from "@/lib/api/client";
import {
  STOCK_PRICE_ID,
  STOCK_VOLUME_ID,
  toMainSeriesData,
  toVolumeSeriesData,
  type StockChartType,
} from "./stock";

export interface LiveTickInput { price: number; size: number; timeMs: number }
export interface MergeResult { bars: HistoryBar[]; appended: boolean }

export function parseTickTimeMs(time: string, fallback = Date.now()): number {
  if (!time) return fallback;
  const parsed = Date.parse(time);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function utcDayStart(ms: number): number {
  const d = new Date(ms);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

export function mergeTickIntoBars(bars: HistoryBar[], tick: LiveTickInput): MergeResult {
  if (!bars.length) return { bars, appended: false };
  const last = bars[bars.length - 1];
  if (utcDayStart(last.t) === utcDayStart(tick.timeMs)) {
    const updated: HistoryBar = {
      ...last,
      h: Math.max(last.h, tick.price),
      l: Math.min(last.l, tick.price),
      c: tick.price,
      v: last.v + tick.size,
    };
    return { bars: [...bars.slice(0, -1), updated], appended: false };
  }
  return {
    bars: [...bars, {
      t: utcDayStart(tick.timeMs),
      o: tick.price, h: tick.price, l: tick.price, c: tick.price, v: tick.size,
    }],
    appended: true,
  };
}

function getSeries(chart: Chart, id: string): Series | undefined {
  const found = chart.get(id);
  return found && "setData" in found ? (found as Series) : undefined;
}
function lastPoint(s: Series): Point | undefined {
  return s.points?.length ? s.points[s.points.length - 1] : undefined;
}

export function applyTickToStockChart({
  chart, bar, appended, type, showVolume, redraw = false,
}: {
  chart: Chart; bar: HistoryBar; appended: boolean;
  type: StockChartType; showVolume: boolean; redraw?: boolean;
}): void {
  const price = getSeries(chart, STOCK_PRICE_ID);
  if (!price) return;
  const [pricePoint] = toMainSeriesData([bar], type);
  if (appended) price.addPoint(pricePoint, false, false);
  else lastPoint(price)?.update(pricePoint, false);

  if (showVolume) {
    const vol = getSeries(chart, STOCK_VOLUME_ID);
    if (vol) {
      const [volPoint] = toVolumeSeriesData([bar]);
      if (appended) vol.addPoint(volPoint, false, false);
      else lastPoint(vol)?.update(volPoint, false);
    }
  }
  if (redraw) chart.redraw(false);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/stockLive.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/charts/hc/stockLive.ts frontend/src/lib/charts/hc/stockLive.test.ts
git commit -m "feat(stock-chart): pure live-tick merge + native addPoint applier"
```

---

### Task 4: Wrapper `StockChart.tsx` + CSS de chrome

**Files:**
- Create: `frontend/src/components/charts/StockChart.tsx`
- Create: `frontend/src/components/charts/stock-chart.css`
- Test: `frontend/src/components/charts/StockChart.test.tsx`

**Interfaces:**
- Consumes: `buildStockOptions`, `RANGE_BUTTONS`, `rangeButtonIndexForPreset`, `STOCK_PRICE_ID`, `STOCK_VOLUME_ID` (Task 1-2); `mergeTickIntoBars`, `parseTickTimeMs`, `applyTickToStockChart` (Task 3); `subscribeTicks`, `onFeedStatus` from `@/lib/livefeed/client`; `chartColors` from `@/lib/charts/chartColors`; `highchartsTheme` from `@/lib/charts/hc/theme`.
- Produces: `StockChart` component with props:
  ```ts
  {
    symbol: string;
    bars: HistoryBar[];
    initialRange: RangePreset;
    onRangeChange: (preset: RangePreset) => void;
    className?: string;
    isEmpty?: boolean;
    emptyMessage?: string;
  }
  ```

**Design (implementador):**
- Importes ESM no effect de criação (na ordem): `highcharts/esm/highstock.js`, `highcharts/esm/highcharts-more.js`, `highcharts/esm/indicators/indicators-all.js`, `highcharts/esm/modules/annotations.js`, `highcharts/esm/modules/stock-tools.js`. CSS: `highcharts/css/stocktools/gui.css`, `highcharts/css/annotations/popup.css`, e `./stock-chart.css`.
- Estado React (toolbar mínima própria para tipo/scale/compare/live continua existindo? **Não** — UI nativa). Tipo de série, escala, volume, SMA: a versão nativa expõe **indicadores e desenho pela GUI do stock-tools**; tipo de série e escala via a própria GUI nativa do stock-tools (`typeChange` e os botões nativos) OU mantidos como estado mínimo. Para esta migração "igual ao demo": deixar o **tipo inicial = candlestick, SMA20 on, volume on, scale linear**, e o usuário muda tipo/indicadores pela GUI nativa. (Compare e live precisam de UI própria — ver abaixo.)
- **Compare**: manter um `SymbolSearchInput` pequeno acima do chart (a busca não existe no stock-tools). Ao selecionar, buscar bars completos (`fetchStockHistory`) e `chart.addSeries({ id:'compare-...', type:'line', data, compare herda de plotOptions })`; remover via chip → `chart.get(id).remove()`. Ativar `%`/compare: `chart.update({ plotOptions:{ series:{ compare:'percent' } } }, true)` quando houver ≥1 compare.
- **Live**: `subscribeTicks(symbol)` em `useEffect([symbol])`; em cada tick → `mergeTickIntoBars` (ref dos bars) → `applyTickToStockChart` coalescido por `requestAnimationFrame` (padrão do `InteractiveChart` atual, linhas 81-86, 175-227). `onFeedStatus` controla o badge LIVE/EOD (nativo `currentPriceIndicator` do stock-tools opcional).
- **Criar uma vez, atualizar cirurgicamente**: NÃO usar `chart.update(buildStockOptions(...))` a cada render. Criar com as options iniciais; mudanças de `bars` (novo símbolo) via `series.setData`. Isso preserva anotações/desenhos.
- `onRangeChange`: ligado via `buildStockOptions({ onRangeButtonClick: onRangeChange })`.

- [ ] **Step 1: Write the smoke test (jsdom, mock do highstock)**

```tsx
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, cleanup } from "@testing-library/react";

const stockChart = vi.fn(() => ({
  destroy: vi.fn(), reflow: vi.fn(), get: vi.fn(), addSeries: vi.fn(),
  update: vi.fn(), redraw: vi.fn(), series: [],
}));
vi.mock("highcharts/esm/highstock.js", () => ({ default: { stockChart, setOptions: vi.fn() } }));
vi.mock("highcharts/esm/highcharts-more.js", () => ({}));
vi.mock("highcharts/esm/indicators/indicators-all.js", () => ({}));
vi.mock("highcharts/esm/modules/annotations.js", () => ({}));
vi.mock("highcharts/esm/modules/stock-tools.js", () => ({}));
vi.mock("highcharts/css/stocktools/gui.css", () => ({}));
vi.mock("highcharts/css/annotations/popup.css", () => ({}));
vi.mock("@/lib/livefeed/client", () => ({
  subscribeTicks: () => () => {}, onFeedStatus: () => () => {},
}));
vi.mock("@/lib/charts/chartColors", () => ({ chartColors: () => ({ categories: [], }) }));
vi.mock("@/lib/charts/hc/theme", () => ({ highchartsTheme: () => ({}) }));

import { StockChart } from "./StockChart";

afterEach(cleanup);

describe("StockChart wrapper", () => {
  it("creates a stockChart once and destroys on unmount", async () => {
    const { unmount } = render(
      <StockChart symbol="NVDA" bars={[{ t: 1, o: 1, h: 1, l: 1, c: 1, v: 1 }]}
        initialRange="1Y" onRangeChange={() => {}} />,
    );
    await vi.waitFor(() => expect(stockChart).toHaveBeenCalledTimes(1));
    unmount();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/components/charts/StockChart.test.tsx`
Expected: FAIL — `StockChart` não existe.

- [ ] **Step 3: Create `stock-chart.css`**

```css
/* Chrome nativa do Highstock vestida na paleta Graphite (bordô). Cores via
   CSS vars do tema; sem styledMode total (séries continuam coloridas via JS). */
.highcharts-range-selector-buttons text { fill: var(--color-text-secondary) !important; }
.highcharts-range-selector-buttons .highcharts-button-pressed text { fill: var(--color-on-accent) !important; }
.highcharts-range-selector-buttons .highcharts-button-pressed > rect,
.highcharts-range-selector-buttons .highcharts-button-pressed .highcharts-button-box {
  fill: var(--color-accent) !important;
}
.highcharts-stocktools-toolbar li > .highcharts-menu-item-btn { background-color: var(--color-surface-1); }
.highcharts-stocktools-toolbar { background: var(--color-surface-1); border-color: var(--color-border); }
.highcharts-popup { background: var(--color-surface-1); color: var(--color-text-primary); border: 1px solid var(--color-border); }
.highcharts-popup button.highcharts-popup-button { background: var(--color-accent); color: var(--color-on-accent); }
.highcharts-navigator-mask-inside { fill: var(--color-accent-wash); }
```
(Ajustar nomes de CSS vars aos tokens reais em `globals.css`; o implementador confere os nomes em uso.)

- [ ] **Step 4: Implement `StockChart.tsx`**

Implementar conforme o "Design" acima, espelhando o ciclo de vida de `HighchartsStockChart.tsx` (criar/reflow/destroy) e o live coalescido de `InteractiveChart.tsx:175-227`, mas: (a) criar o chart UMA vez via `buildStockOptions`, (b) atualizar `bars` por `series.setData` quando `symbol`/`bars` mudam, (c) ligar `onRangeButtonClick: onRangeChange`, (d) `SymbolSearchInput` para compare via `addSeries`/`remove`. Importar `import "./stock-chart.css"`.

Pontos obrigatórios:
- `chartRef` guarda o `Chart`; `barsRef` guarda os bars correntes para o callback de tick.
- `onReady` interno: após `stockChart(...)`, guardar em `chartRef` e assinar live.
- Volume/SMA iniciais: `showVolume: true`, `sma20: true` (paridade), `type: "candles"`.
- `selectedRangeIndex: rangeButtonIndexForPreset(initialRange)`.

- [ ] **Step 5: Run smoke test + typecheck**

Run: `cd frontend && pnpm exec vitest run src/components/charts/StockChart.test.tsx && pnpm typecheck`
Expected: PASS + typecheck limpo.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/charts/StockChart.tsx frontend/src/components/charts/stock-chart.css frontend/src/components/charts/StockChart.test.tsx
git commit -m "feat(stock-chart): native Highstock wrapper + chrome CSS + live"
```

---

### Task 5: Integração na `StockAnalysisView`

**Files:**
- Modify: `frontend/src/components/stocks/StockAnalysisView.tsx`

**Interfaces:**
- Consumes: `StockChart` (Task 4); `fetchStockHistory` from `@/lib/api/client`.

**Mudanças:**
1. Trocar a query de timeseries por histórico completo (sem `range` na key):
   ```ts
   const history = useQuery({
     queryKey: ["stock-history-full", ticker],
     queryFn: ({ signal }) => fetchStockHistory(ticker, 2520, signal),
     staleTime: 60 * 60 * 1000,
     retry: (n, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && n < 2,
   });
   ```
2. `historyBars = history.data?.bars ?? []` (já é `HistoryBar[]`; remover `stockTimeseriesToHistoryBars`/`fetchStockTimeseries` deste componente).
3. Em `AnalysisContent`, trocar `<InteractiveChart .../>` por:
   ```tsx
   <StockChart
     symbol={header.ticker}
     bars={historyBars}
     initialRange={range}
     onRangeChange={onRangeChange}
     className="w-full aspect-[16/10] min-h-[380px] max-h-[70vh]"
     isEmpty={historyBars.length === 0}
     emptyMessage="No price history in the synced window."
   />
   ```
   `onRangeChange={selectRange}` continua atualizando `range` → refetch do `analysis` query (KPIs). O chart NÃO refetcha bars (zoom client-side).
4. `range` permanece como state e na `analysis` query (KPIs). `analysis` query inalterada.

- [ ] **Step 1: Verificar/ajustar testes existentes do StockAnalysisView**

Run: `cd frontend && pnpm exec vitest run src/components/stocks/StockAnalysisView` (se houver suite). Ajustar mocks: o componente agora importa `StockChart` (não `InteractiveChart`) e usa `fetchStockHistory`. Atualizar mocks correspondentes.

- [ ] **Step 2: Aplicar as mudanças (1-4 acima).**

- [ ] **Step 3: Typecheck + testes**

Run: `cd frontend && pnpm typecheck && pnpm exec vitest run src/components/stocks/`
Expected: PASS / typecheck limpo.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/stocks/StockAnalysisView.tsx
git commit -m "feat(stock-chart): wire native StockChart into StockAnalysisView (full history + range→KPIs)"
```

---

### Task 6: Validação integrada (typecheck, testes, build, browser)

**Files:** nenhum (validação).

- [ ] **Step 1: Suite e tipos**

Run: `cd frontend && pnpm typecheck && pnpm exec vitest run && pnpm lint`
Expected: typecheck limpo; testes verdes (exceto falhas pré-existentes anotadas na Task 0); lint limpo.

- [ ] **Step 2: Build**

Run: `cd frontend && pnpm build`
Expected: build conclui sem erro (valida que os imports ESM de indicadores/stock-tools resolvem sob Turbopack).

- [ ] **Step 3: Browser-check (manual)**

Run: `cd frontend && pnpm dev`, abrir `/stocks/NVDA`. Verificar, anotando evidências:
- rangeSelector nativo (1M/6M/1Y/5Y/MAX) muda o zoom; clicar um botão atualiza as KPIs (Total Return · range, etc.).
- Compare (adicionar AAPL) entra na MESMA janela, sem deformar; `%` alinha as séries.
- stock-tools: desenhar trendline/Fibonacci e adicionar um indicador (RSI/MACD) pela GUI — persistem (não somem ao trocar range/zoom).
- LIVE: em pregão, o último candle atualiza; fora do pregão, fica EOD sem erro.
- Console sem o warning de touchstart (patch grid-pro) nem o de WebSocket.

- [ ] **Step 4: Commit (se houver ajustes do browser-check)**

```bash
git add -A && git commit -m "fix(stock-chart): browser-check adjustments"
```

---

## Self-Review (preenchido)

**Spec coverage:** UI nativa (rangeSelector/navigator/stock-tools/indicadores) → Tasks 2,4. Compare nativo → Tasks 2,4. Live nativo → Tasks 3,4. Dados diários completos + range→KPIs → Tasks 2,5. Estilização híbrida (CSS chrome) → Task 4. Componente isolado, fundos intactos → Global Constraints + Task 5 (não toca InteractiveChart). Testes → Tasks 1-4. Limpeza futura → fora de escopo (documentada na spec).

**Placeholders:** builders puros (Tasks 1-3) têm código e testes completos. Task 4 (wrapper) e Task 5 (integração) dão a estrutura completa + pontos obrigatórios + código dos trechos não óbvios; o corpo do wrapper espelha arquivos existentes citados por caminho/linha (HighchartsStockChart, InteractiveChart:175-227) — intencional, é um componente de UI validado no browser, não unidade pura.

**Type consistency:** `HistoryBar` usado em todas as tasks; `STOCK_PRICE_ID`/`STOCK_VOLUME_ID` definidos na Task 1 e consumidos em 2/3/4; `buildStockOptions`/`mergeTickIntoBars`/`applyTickToStockChart`/`rangeButtonIndexForPreset` com assinaturas estáveis entre as tasks.

## Fora de escopo
- Chart de fundos / modo NAV (sessão futura) — `InteractiveChart`/`priceStock.ts`/`priceStockLive.ts` permanecem.
- Intraday real (1m/5m).
- `styledMode` total.
- Remoção do código antigo (será feita quando os fundos migrarem).
