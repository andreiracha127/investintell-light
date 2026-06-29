import { describe, expect, it } from "vitest";
import {
  buildStockOptions,
  RANGE_BUTTONS,
  rangeButtonIndexForPreset,
  STOCK_PRICE_ID,
  STOCK_VOLUME_ID,
  toMainSeriesData,
  toVolumeSeriesData,
} from "./stock";
import type { HistoryBar } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";

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
    sma20: false,
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

  it("maps the chart type to the native main-series type", () => {
    const mainTypeFor = (type: "ohlc" | "line" | "area") => {
      const opt = buildStockOptions(baseInput({ type }));
      const main = (opt.series ?? []).find((s) => (s as { id?: string }).id === "price-main");
      return (main as { type?: string }).type;
    };
    expect(mainTypeFor("ohlc")).toBe("ohlc");
    expect(mainTypeFor("line")).toBe("line");
    expect(mainTypeFor("area")).toBe("area");
  });

  it("includes a native SMA20 indicator linked to the price series when sma20=true", () => {
    const opt = buildStockOptions(baseInput({ sma20: true }));
    const sma = (opt.series ?? []).find((s) => (s as { type?: string }).type === "sma");
    expect((sma as { linkedTo?: string }).linkedTo).toBe("price-main");
    expect((sma as { params?: { period?: number } }).params?.period).toBe(20);
  });

  it("does not include SMA by default (stock-tools GUI provides it on demand)", () => {
    const opt = buildStockOptions(baseInput());
    const types = (opt.series ?? []).map((s) => (s as { type?: string }).type);
    expect(types).not.toContain("sma");
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
