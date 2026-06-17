import type { DataGroupingOptionsObject, Options, SeriesOptionsType } from "highcharts";

import type { RangePreset, SymbolSearchResult } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";

export type PriceChartType = "candles" | "ohlc" | "line" | "area";
export type PricePeriod = "D" | "W" | "M";
export type PriceMode = "ohlcv" | "nav";

export interface PriceBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface PriceCompareSelection {
  key: string;
  symbol: string;
  label: string;
  kind: SymbolSearchResult["kind"];
  instrumentId: string | null;
}

export interface PriceStockOptionsInput {
  symbol: string;
  bars: PriceBar[];
  mode: PriceMode;
  type: PriceChartType;
  period: PricePeriod;
  range: RangePreset;
  overlays: { sma20: boolean; sma50: boolean };
  panes: { volume: boolean; rsi: boolean };
  scale: { log: boolean; pct: boolean };
  compares: PriceCompareSelection[];
  compareData: Record<string, PriceBar[]>;
  colors: ChartColors;
  onVisibleRangeChange?: (next: RangePreset) => void;
}

export const PRICE_SERIES_ID = "price-main";
export const VOLUME_SERIES_ID = "price-volume";
export const MAX_COMPARE_SERIES = 5;

const RANGE_MS: Record<Exclude<RangePreset, "MAX">, number> = {
  "1M": 30 * 86_400_000,
  "6M": 183 * 86_400_000,
  "1Y": 365 * 86_400_000,
  "5Y": 365 * 5 * 86_400_000,
};

export function toMainSeriesData(
  bars: PriceBar[],
  type: PriceChartType,
): Array<[number, number] | [number, number, number, number, number]> {
  if (type === "candles" || type === "ohlc") {
    return bars.map((bar) => [bar.t, bar.o, bar.h, bar.l, bar.c]);
  }
  return bars.map((bar) => [bar.t, bar.c]);
}

export function toVolumeSeriesData(bars: PriceBar[]): Array<[number, number]> {
  return bars.map((bar) => [bar.t, bar.v]);
}

/**
 * Estudos taylor-made — port das funções puras da engine ixchart (commit
 * 709a6fb, `lib/ixchart/series.ts`). Substituem os indicadores nativos do
 * Highstock (`type: "sma"`/`"rsi"`), que não registram de forma confiável sob
 * o build ESM/Turbopack e deixavam os estudos sem renderizar.
 */

/** Média móvel simples sobre os closes (janela deslizante O(n)). */
export function smaValues(bars: PriceBar[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let acc = 0;
  for (let i = 0; i < bars.length; i++) {
    acc += bars[i].c;
    if (i >= period) acc -= bars[i - period].c;
    if (i >= period - 1) out[i] = acc / period;
  }
  return out;
}

/** RSI de Wilder (suavização exponencial dos ganhos/perdas médios). */
export function rsiValues(bars: PriceBar[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let g = 0;
  let l = 0;
  for (let i = 1; i < bars.length; i++) {
    const d = bars[i].c - bars[i - 1].c;
    const up = Math.max(d, 0);
    const dn = Math.max(-d, 0);
    if (i <= period) {
      g += up / period;
      l += dn / period;
    } else {
      g = (g * (period - 1) + up) / period;
      l = (l * (period - 1) + dn) / period;
    }
    if (i >= period) out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  return out;
}

/** Alinha valores de indicador aos bars como pontos [t, value] (mantém nulls). */
export function indicatorSeriesData(
  bars: PriceBar[],
  values: (number | null)[],
): Array<[number, number | null]> {
  return bars.map((bar, index) => [bar.t, values[index]]);
}

export function dataGroupingForPeriod(period: PricePeriod): DataGroupingOptionsObject {
  if (period === "W") {
    return { enabled: true, forced: true, units: [["week", [1]]] };
  }
  if (period === "M") {
    return { enabled: true, forced: true, units: [["month", [1]]] };
  }
  return {
    enabled: true,
    forced: false,
    units: [
      ["day", [1]],
      ["week", [1]],
      ["month", [1]],
    ],
  };
}

export function compareSelectionKey(
  item: Pick<SymbolSearchResult, "kind" | "symbol" | "instrument_id">,
): string {
  return `${item.kind}:${item.symbol.toUpperCase()}:${item.instrument_id ?? ""}`;
}

export function toCompareSelection(item: SymbolSearchResult): PriceCompareSelection {
  return {
    key: compareSelectionKey(item),
    symbol: item.symbol.toUpperCase(),
    label: item.symbol.toUpperCase(),
    kind: item.kind,
    instrumentId: item.instrument_id,
  };
}

export function addCompareSelection(
  current: PriceCompareSelection[],
  item: SymbolSearchResult,
): PriceCompareSelection[] {
  const next = toCompareSelection(item);
  if (current.some((entry) => entry.key === next.key)) return current;
  if (current.length >= MAX_COMPARE_SERIES) return current;
  return [...current, next];
}

export function removeCompareSelection(
  current: PriceCompareSelection[],
  key: string,
): PriceCompareSelection[] {
  return current.filter((entry) => entry.key !== key);
}

export function rangePresetFromExtremes(
  min: number,
  max: number,
  dataMin: number,
  dataMax: number,
): RangePreset {
  const visible = Math.max(0, max - min);
  const total = Math.max(0, dataMax - dataMin);
  if (total > 0 && visible / total >= 0.9) return "MAX";

  let best: Exclude<RangePreset, "MAX"> = "1M";
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const [preset, duration] of Object.entries(RANGE_MS) as Array<
    [Exclude<RangePreset, "MAX">, number]
  >) {
    const distance = Math.abs(Math.log(Math.max(1, visible)) - Math.log(duration));
    if (distance < bestDistance) {
      best = preset;
      bestDistance = distance;
    }
  }
  return best;
}

function stockSeriesType(type: PriceChartType): "candlestick" | "ohlc" | "line" | "area" {
  if (type === "candles") return "candlestick";
  return type;
}

function paneLayout(panes: { volume: boolean; rsi: boolean }) {
  const extra = Number(panes.volume) + Number(panes.rsi);
  if (extra === 0) return { priceHeight: "100%", volumeTop: "0%", rsiTop: "0%" };
  if (extra === 1) return { priceHeight: "72%", volumeTop: "74%", rsiTop: "74%" };
  return { priceHeight: "58%", volumeTop: "60%", rsiTop: "80%" };
}

function emptyNavigatorData(bars: PriceBar[]): Array<[number, number]> {
  return bars.map((bar) => [bar.t, bar.c]);
}

function periodBucketStart(timeMs: number, period: PricePeriod): number {
  if (period === "D") return timeMs;
  const date = new Date(timeMs);
  if (period === "M") {
    return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1);
  }
  const day = date.getUTCDay() || 7;
  return Date.UTC(
    date.getUTCFullYear(),
    date.getUTCMonth(),
    date.getUTCDate() - day + 1,
  );
}

function closeDataForCore(
  bars: PriceBar[],
  period: PricePeriod,
  percent: boolean,
): Array<[number, number]> {
  const byBucket = new Map<number, PriceBar>();
  for (const bar of bars) {
    byBucket.set(periodBucketStart(bar.t, period), bar);
  }
  const grouped = [...byBucket.values()].sort((a, b) => a.t - b.t);
  const base = grouped.find((bar) => bar.c > 0)?.c ?? null;
  return grouped.map((bar) => [
    bar.t,
    percent && base !== null ? ((bar.c / base) - 1) * 100 : bar.c,
  ]);
}

export function buildHcPriceCoreOption(input: PriceStockOptionsInput): Options {
  const {
    symbol,
    bars,
    type,
    period,
    scale,
    compares,
    compareData,
    colors,
    onVisibleRangeChange,
  } = input;
  const safeType: "line" | "area" = type === "area" ? "area" : "line";
  const dataMin = bars[0]?.t ?? 0;
  const dataMax = bars[bars.length - 1]?.t ?? 0;
  const percent = scale.pct;

  const series: SeriesOptionsType[] = [
    {
      id: PRICE_SERIES_ID,
      type: safeType,
      name: symbol,
      data: closeDataForCore(bars, period, percent),
      color: colors.accent,
      lineWidth: 2,
      marker: { enabled: false },
      tooltip: { valueDecimals: percent ? 2 : 2 },
    } as SeriesOptionsType,
  ];

  compares.forEach((compare, index) => {
    series.push({
      id: `compare-${compare.key}`,
      type: "line",
      name: compare.label,
      data: closeDataForCore(compareData[compare.key] ?? [], period, percent),
      color: colors.categories[(index + 4) % colors.categories.length],
      lineWidth: 1.4,
      marker: { enabled: false },
      tooltip: { valueDecimals: percent ? 2 : 2 },
    } as SeriesOptionsType);
  });

  return {
    chart: {
      type: safeType,
      spacingTop: 8,
      spacingRight: 8,
      spacingBottom: 8,
      spacingLeft: 8,
    },
    xAxis: {
      type: "datetime",
      events: {
        afterSetExtremes(event) {
          if (!onVisibleRangeChange) return;
          const min = typeof event.min === "number" ? event.min : dataMin;
          const max = typeof event.max === "number" ? event.max : dataMax;
          onVisibleRangeChange(rangePresetFromExtremes(min, max, dataMin, dataMax));
        },
      },
    },
    yAxis: {
      type: scale.log && !percent ? "logarithmic" : "linear",
      title: { text: undefined },
      // Omit `labels` when not percent: `labels: undefined` makes Highcharts'
      // merge overwrite the default labels object, and Axis.init then throws
      // reading `labels.rotation`. The spread keeps the key absent in that case.
      ...(percent ? { labels: { format: "{value}%" } } : {}),
    },
    tooltip: {
      shared: true,
      valueSuffix: percent ? "%" : undefined,
      valueDecimals: 2,
    },
    plotOptions: {
      series: {
        marker: { enabled: false },
        turboThreshold: 0,
      },
      area: {
        fillColor: `${colors.accent}24`,
        threshold: null,
      },
    },
    series,
    credits: { enabled: false },
  };
}

export function buildHcPriceStockOption(input: PriceStockOptionsInput): Options {
  const {
    symbol,
    bars,
    mode,
    type,
    period,
    overlays,
    panes,
    scale,
    compares,
    compareData,
    colors,
    onVisibleRangeChange,
  } = input;
  const safeType: PriceChartType =
    mode === "nav" && (type === "candles" || type === "ohlc") ? "line" : type;
  const dataGrouping = dataGroupingForPeriod(period);
  const showVolume = mode === "ohlcv" && panes.volume;
  const layout = paneLayout({ volume: showVolume, rsi: panes.rsi });
  const dataMin = bars[0]?.t ?? 0;
  const dataMax = bars[bars.length - 1]?.t ?? 0;

  const yAxis: NonNullable<Options["yAxis"]> = [
    {
      id: "price-axis",
      height: layout.priceHeight,
      type: scale.log ? "logarithmic" : "linear",
      // Price axis on the right (trading convention). Labels align "left" so
      // they sit OUTSIDE the plot, to the right of the axis line — `align:
      // "right"` pushed them inside, overlapping the latest candles.
      opposite: true,
      labels: { align: "left", x: 4 },
      title: { text: undefined },
      resize: { enabled: true },
    },
  ];

  if (showVolume) {
    (yAxis as Array<Record<string, unknown>>).push({
      id: "volume-axis",
      top: layout.volumeTop,
      height: panes.rsi ? "18%" : "24%",
      offset: 0,
      opposite: true,
      labels: { align: "left", x: 4 },
      title: { text: undefined },
    });
  }

  if (panes.rsi) {
    (yAxis as Array<Record<string, unknown>>).push({
      id: "rsi-axis",
      top: layout.rsiTop,
      height: showVolume ? "18%" : "24%",
      min: 0,
      max: 100,
      offset: 0,
      opposite: true,
      labels: { align: "left", x: 4 },
      title: { text: undefined },
      plotLines: [
        { value: 30, color: colors.grid, width: 1 },
        { value: 70, color: colors.grid, width: 1 },
      ],
    });
  }

  const series: SeriesOptionsType[] = [
    {
      id: PRICE_SERIES_ID,
      type: stockSeriesType(safeType),
      name: symbol,
      data: toMainSeriesData(bars, safeType),
      yAxis: "price-axis",
      color: colors.accent,
      lineColor: colors.accent,
      upColor: colors.gain,
      upLineColor: colors.gain,
      dataGrouping,
      tooltip: { valueDecimals: 2 },
    } as SeriesOptionsType,
  ];

  if (showVolume) {
    series.push({
      id: VOLUME_SERIES_ID,
      type: "column",
      name: "Volume",
      data: toVolumeSeriesData(bars),
      yAxis: "volume-axis",
      color: colors.barMute,
      dataGrouping,
      tooltip: { valueDecimals: 0 },
    } as SeriesOptionsType);
  }

  if (overlays.sma20) {
    series.push({
      type: "line",
      name: "SMA20",
      data: indicatorSeriesData(bars, smaValues(bars, 20)),
      yAxis: "price-axis",
      color: colors.categories[2],
      lineWidth: 1,
      marker: { enabled: false },
      dataGrouping,
      tooltip: { valueDecimals: 2 },
    } as SeriesOptionsType);
  }

  if (overlays.sma50) {
    series.push({
      type: "line",
      name: "SMA50",
      data: indicatorSeriesData(bars, smaValues(bars, 50)),
      yAxis: "price-axis",
      color: colors.categories[3],
      lineWidth: 1,
      marker: { enabled: false },
      dataGrouping,
      tooltip: { valueDecimals: 2 },
    } as SeriesOptionsType);
  }

  if (panes.rsi) {
    series.push({
      type: "line",
      name: "RSI 14",
      data: indicatorSeriesData(bars, rsiValues(bars, 14)),
      yAxis: "rsi-axis",
      color: colors.bar,
      lineWidth: 1,
      marker: { enabled: false },
      dataGrouping,
      tooltip: { valueDecimals: 2 },
    } as SeriesOptionsType);
  }

  compares.forEach((compare, index) => {
    const compareBars = compareData[compare.key] ?? [];
    series.push({
      id: `compare-${compare.key}`,
      type: "line",
      name: compare.label,
      data: toMainSeriesData(compareBars, "line"),
      yAxis: "price-axis",
      color: colors.categories[(index + 4) % colors.categories.length],
      lineWidth: 1.4,
      marker: { enabled: false },
      dataGrouping,
      tooltip: { valueDecimals: 2 },
    } as SeriesOptionsType);
  });

  return {
    chart: { spacingTop: 8, spacingRight: 8, spacingBottom: 8, spacingLeft: 8 },
    // Range is driven by the custom toolbar buttons in InteractiveChart, which
    // refetch at the correct per-range granularity. Disable Highstock's native
    // rangeSelector so the two date selectors don't coexist and conflict.
    rangeSelector: { enabled: false },
    navigator: {
      enabled: true,
      series: { data: emptyNavigatorData(bars), color: colors.barMute },
    },
    scrollbar: { enabled: true },
    // Barchart-style drawing/annotation toolbar. Drop the native `indicators`
    // group (those SMA/RSI series fail to register under ESM — we draw studies
    // as computed line series instead) and `typeChange` (the custom toolbar
    // already owns series type), keeping only the drawing/annotation tools.
    stockTools: {
      gui: {
        enabled: true,
        buttons: [
          "simpleShapes",
          "lines",
          "crookedLines",
          "measure",
          "advanced",
          "toggleAnnotations",
          "separator",
          "verticalLabels",
          "flags",
          "separator",
          "currentPriceIndicator",
          "saveChart",
        ],
      },
    },
    // Self-hosted stock-tools icons (copied to public/), so the toolbar does
    // not depend on the highcharts.com CDN (CSP / offline safe).
    navigation: {
      bindingsClassName: "highcharts-bindings-container",
      iconsURL: "/highcharts/gfx/stock-icons/",
    },
    xAxis: {
      ordinal: true,
      events: {
        afterSetExtremes(event) {
          if (!onVisibleRangeChange) return;
          const min = typeof event.min === "number" ? event.min : dataMin;
          const max = typeof event.max === "number" ? event.max : dataMax;
          onVisibleRangeChange(rangePresetFromExtremes(min, max, dataMin, dataMax));
        },
      },
    },
    yAxis,
    tooltip: {
      split: false,
      shared: true,
      valueDecimals: scale.pct ? 2 : undefined,
    },
    plotOptions: {
      series: {
        compare: scale.pct ? "percent" : undefined,
        dataGrouping,
        marker: { enabled: false },
        turboThreshold: 0,
      },
      candlestick: {
        color: colors.loss,
        upColor: colors.gain,
        lineColor: colors.loss,
        upLineColor: colors.gain,
      },
      ohlc: {
        color: colors.loss,
        upColor: colors.gain,
      },
      area: {
        fillColor: `${colors.accent}24`,
        threshold: null,
      },
    },
    series,
    credits: { enabled: false },
  };
}
