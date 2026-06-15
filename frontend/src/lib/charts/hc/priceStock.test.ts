import { describe, expect, it, vi } from "vitest";

import {
  MAX_COMPARE_SERIES,
  PRICE_SERIES_ID,
  VOLUME_SERIES_ID,
  addCompareSelection,
  buildHcPriceStockOption,
  compareSelectionKey,
  dataGroupingForPeriod,
  rangePresetFromExtremes,
  removeCompareSelection,
  toMainSeriesData,
  toVolumeSeriesData,
  type PriceBar,
  type PriceCompareSelection,
} from "@/lib/charts/hc/priceStock";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";

const BARS: PriceBar[] = [
  { t: Date.UTC(2024, 0, 2), o: 100, h: 110, l: 95, c: 108, v: 1000 },
  { t: Date.UTC(2024, 0, 3), o: 108, h: 112, l: 101, c: 104, v: 1200 },
  { t: Date.UTC(2024, 0, 4), o: 104, h: 109, l: 99, c: 107, v: 900 },
];

const COMPARE: PriceCompareSelection = {
  key: "stock:MSFT:",
  symbol: "MSFT",
  label: "MSFT",
  kind: "stock",
  instrumentId: null,
};

describe("priceStock data conversion", () => {
  it("maps OHLC bars to candlestick data", () => {
    expect(toMainSeriesData(BARS, "candles")).toEqual([
      [BARS[0].t, 100, 110, 95, 108],
      [BARS[1].t, 108, 112, 101, 104],
      [BARS[2].t, 104, 109, 99, 107],
    ]);
  });

  it("maps line and area data to close values", () => {
    expect(toMainSeriesData(BARS, "line")).toEqual([
      [BARS[0].t, 108],
      [BARS[1].t, 104],
      [BARS[2].t, 107],
    ]);
    expect(toMainSeriesData(BARS, "area")).toEqual([
      [BARS[0].t, 108],
      [BARS[1].t, 104],
      [BARS[2].t, 107],
    ]);
  });

  it("maps volume data to [time, volume]", () => {
    expect(toVolumeSeriesData(BARS)).toEqual([
      [BARS[0].t, 1000],
      [BARS[1].t, 1200],
      [BARS[2].t, 900],
    ]);
  });
});

describe("priceStock option builder", () => {
  it("builds a candlestick stock chart with price and volume series", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "candles",
      period: "D",
      range: "1Y",
      overlays: { sma20: true, sma50: false },
      panes: { volume: true, rsi: false },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{ id?: string; type?: string; linkedTo?: string }>;
    expect(series[0]).toMatchObject({ id: PRICE_SERIES_ID, type: "candlestick" });
    expect(series.some((s) => s.id === VOLUME_SERIES_ID && s.type === "column")).toBe(true);
    expect(series.some((s) => s.type === "sma" && s.linkedTo === PRICE_SERIES_ID)).toBe(true);
  });

  it("omits volume and OHLC-only series for NAV mode", () => {
    const opt = buildHcPriceStockOption({
      symbol: "FUNDX",
      bars: BARS,
      mode: "nav",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: true, sma50: false },
      panes: { volume: true, rsi: false },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{ id?: string; type?: string }>;
    expect(series[0]).toMatchObject({ id: PRICE_SERIES_ID, type: "line" });
    expect(series.some((s) => s.id === VOLUME_SERIES_ID)).toBe(false);
  });

  it("adds RSI on a dedicated axis when enabled", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: true },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{ type?: string; yAxis?: string }>;
    const axes = opt.yAxis as Array<{ id?: string }>;
    expect(series.some((s) => s.type === "rsi" && s.yAxis === "rsi-axis")).toBe(true);
    expect(axes.some((axis) => axis.id === "rsi-axis")).toBe(true);
  });

  it("uses logarithmic price axis only when log is active", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: false },
      scale: { log: true, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const axes = opt.yAxis as Array<{ id?: string; type?: string }>;
    expect(axes.find((axis) => axis.id === "price-axis")?.type).toBe("logarithmic");
  });

  it("sets native percent compare when percent scale is active", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: false },
      scale: { log: false, pct: true },
      compares: [COMPARE],
      compareData: { [COMPARE.key]: BARS },
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const plotOptions = opt.plotOptions as { series?: { compare?: string } };
    const series = opt.series as Array<{ id?: string; type?: string; name?: string }>;
    expect(plotOptions.series?.compare).toBe("percent");
    expect(series.some((s) => s.id === "compare-stock:MSFT:" && s.name === "MSFT")).toBe(true);
  });

  it("selects native data grouping by period", () => {
    expect(dataGroupingForPeriod("D")).toMatchObject({ forced: false });
    expect(dataGroupingForPeriod("W")).toMatchObject({
      forced: true,
      units: [["week", [1]]],
    });
    expect(dataGroupingForPeriod("M")).toMatchObject({
      forced: true,
      units: [["month", [1]]],
    });
  });
});

describe("priceStock compare helpers", () => {
  it("dedupes compare selections and caps at MAX_COMPARE_SERIES", () => {
    const first = addCompareSelection([], {
      symbol: "MSFT",
      name: null,
      kind: "stock",
      instrument_id: null,
    });
    expect(first).toHaveLength(1);
    expect(addCompareSelection(first, {
      symbol: "MSFT",
      name: null,
      kind: "stock",
      instrument_id: null,
    })).toHaveLength(1);

    let many = first;
    for (let i = 0; i < MAX_COMPARE_SERIES + 3; i += 1) {
      many = addCompareSelection(many, {
        symbol: `T${i}`,
        name: null,
        kind: "stock",
        instrument_id: null,
      });
    }
    expect(many).toHaveLength(MAX_COMPARE_SERIES);
  });

  it("removes compare selections by stable key", () => {
    const selection = {
      symbol: "VFIAX",
      name: "Vanguard 500 Index",
      kind: "mutual_fund",
      instrument_id: "fund-1",
    } as const;
    const key = compareSelectionKey(selection);
    const next = addCompareSelection([], selection);
    expect(removeCompareSelection(next, key)).toEqual([]);
  });
});

describe("priceStock range helper", () => {
  it("returns MAX when the visible range covers almost the full data span", () => {
    expect(rangePresetFromExtremes(0, 950, 0, 1000)).toBe("MAX");
  });

  it("returns the nearest calendar preset for partial windows", () => {
    const day = 86_400_000;
    expect(rangePresetFromExtremes(0, 29 * day, 0, 1000 * day)).toBe("1M");
    expect(rangePresetFromExtremes(0, 185 * day, 0, 1000 * day)).toBe("6M");
    expect(rangePresetFromExtremes(0, 370 * day, 0, 2000 * day)).toBe("1Y");
    expect(rangePresetFromExtremes(0, 1800 * day, 0, 4000 * day)).toBe("5Y");
  });
});
