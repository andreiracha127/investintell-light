import type { Options, SeriesOptionsType, YAxisOptions } from "highcharts";
import type { HistoryBar, RangePreset } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";

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
    chart: {
      backgroundColor: "transparent",
      spacingTop: 8,
      spacingRight: 8,
      spacingBottom: 8,
      spacingLeft: 8,
    },
    rangeSelector: {
      enabled: true,
      selected: selectedRangeIndex,
      buttons: RANGE_BUTTONS as unknown as NonNullable<Options["rangeSelector"]>["buttons"],
      inputEnabled: false,
    },
    navigator: { enabled: true },
    scrollbar: { enabled: true },
    stockTools: {
      gui: {
        enabled: true,
        // Full default button set (matches Highcharts stock-tools documentation).
        // Each name maps to a pre-built NavigationBindings handler; the modules
        // loaded in StockChart.tsx (annotations-advanced, drag-panes,
        // price-indicator, full-screen) provide the implementations.
        buttons: [
          "indicators", "separator",
          "simpleShapes", "lines", "crookedLines", "measure", "advanced",
          "toggleAnnotations", "separator", "verticalLabels", "flags",
          "separator", "zoomChange", "fullScreen", "typeChange", "separator",
          "currentPriceIndicator", "saveChart",
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
        afterSetExtremes(e) {
          const text = (e as { rangeSelectorButton?: { text?: string } })
            .rangeSelectorButton?.text;
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
