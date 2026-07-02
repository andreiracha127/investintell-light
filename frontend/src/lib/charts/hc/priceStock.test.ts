import { describe, expect, it, vi } from "vitest";

import {
  MAX_COMPARE_SERIES,
  PRICE_SERIES_ID,
  VOLUME_SERIES_ID,
  addCompareSelection,
  buildHcPriceCoreOption,
  buildHcPriceStockOption,
  clipBarsFrom,
  commonCompareStart,
  compareSelectionKey,
  dataGroupingForPeriod,
  indicatorSeriesData,
  rangePresetFromExtremes,
  removeCompareSelection,
  resampleBars,
  priceStockTooltipFormatter,
  rsiValues,
  smaValues,
  toMainSeriesData,
  toVolumeSeriesData,
  type PriceBar,
  type PriceCompareSelection,
  type PriceStockOptionsInput,
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
    const series = opt.series as Array<{ id?: string; type?: string; name?: string; yAxis?: string }>;
    expect(series[0]).toMatchObject({ id: PRICE_SERIES_ID, type: "candlestick" });
    expect(series.some((s) => s.id === VOLUME_SERIES_ID && s.type === "column")).toBe(true);
    // Taylor-made SMA: a computed line series on the price axis (not the native
    // Highstock `sma` indicator, which failed to register under ESM).
    expect(series.some((s) => s.name === "SMA20" && s.type === "line" && s.yAxis === "price-axis")).toBe(true);
  });

  it("titles the price y-axis 'Price (USD)' and the volume pane 'Volume'", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "candles",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: true, rsi: false },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const axes = opt.yAxis as Array<{ id?: string; title?: { text?: string } }>;
    expect(axes.find((a) => a.id === "price-axis")?.title?.text).toBe("Price (USD)");
    expect(axes.find((a) => a.id === "volume-axis")?.title?.text).toBe("Volume");
  });

  it("titles the price y-axis 'Change' under the percent scale", () => {
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
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const axes = opt.yAxis as Array<{ id?: string; title?: { text?: string } }>;
    expect(axes.find((a) => a.id === "price-axis")?.title?.text).toBe("Change");
  });

  it("installs a shared OHLC tooltip formatter", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "candles",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: true, rsi: false },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const tooltip = opt.tooltip as { shared?: boolean; useHTML?: boolean; formatter?: unknown };
    expect(tooltip.shared).toBe(true);
    expect(tooltip.useHTML).toBe(true);
    expect(typeof tooltip.formatter).toBe("function");
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
    const series = opt.series as Array<{ type?: string; name?: string; yAxis?: string }>;
    const axes = opt.yAxis as Array<{ id?: string }>;
    // Taylor-made RSI: a computed line series bound to the dedicated RSI axis.
    expect(series.some((s) => s.name === "RSI 14" && s.type === "line" && s.yAxis === "rsi-axis")).toBe(true);
    expect(axes.some((axis) => axis.id === "rsi-axis")).toBe(true);
  });

  describe("taylor-made studies", () => {
    const close = (values: number[]): PriceBar[] =>
      values.map((c, i) => ({ t: Date.UTC(2024, 0, i + 1), o: c, h: c, l: c, c, v: 0 }));

    it("smaValues is null until the window fills, then the simple mean", () => {
      // closes 1..5, period 3 → [null, null, 2, 3, 4]
      expect(smaValues(close([1, 2, 3, 4, 5]), 3)).toEqual([null, null, 2, 3, 4]);
    });

    it("rsiValues is null for the first `period` bars then bounded 0..100", () => {
      const rsi = rsiValues(close([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]), 14);
      expect(rsi.slice(0, 14).every((v) => v === null)).toBe(true);
      // strictly increasing closes → no losses → RSI pinned at 100
      expect(rsi[14]).toBe(100);
      expect(rsi[15]).toBe(100);
    });

    it("resampleBars is a no-op for D and aggregates OHLCV per month", () => {
      const bars: PriceBar[] = [
        { t: Date.UTC(2024, 0, 2), o: 10, h: 12, l: 9, c: 11, v: 100 },
        { t: Date.UTC(2024, 0, 15), o: 11, h: 15, l: 8, c: 14, v: 200 },
        { t: Date.UTC(2024, 1, 1), o: 14, h: 16, l: 13, c: 15, v: 50 },
      ];
      expect(resampleBars(bars, "D")).toBe(bars);
      const monthly = resampleBars(bars, "M");
      expect(monthly).toHaveLength(2);
      // Jan bucket: open of first, high/low extremes, close of last, summed vol.
      expect(monthly[0]).toMatchObject({ t: bars[0].t, o: 10, h: 15, l: 8, c: 14, v: 300 });
      expect(monthly[1]).toMatchObject({ o: 14, c: 15, v: 50 });
    });

    it("studies computed on resampled bars yield period-scale averages", () => {
      // 8 weekly closes; SMA over the monthly resample averages whole months.
      const weekly: PriceBar[] = Array.from({ length: 8 }, (_, i) => {
        const c = 10 + i;
        return { t: Date.UTC(2024, Math.floor(i / 4), (i % 4) * 7 + 1), o: c, h: c, l: c, c, v: 0 };
      });
      const monthly = resampleBars(weekly, "M");
      expect(monthly).toHaveLength(2); // 2 months
      // Monthly closes are the last close of each month (13 and 17); SMA2 → null, 15.
      expect(smaValues(monthly, 2)).toEqual([null, 15]);
    });

    it("indicatorSeriesData aligns values to bar timestamps and keeps nulls", () => {
      const bars = close([10, 11, 12]);
      expect(indicatorSeriesData(bars, [null, 11, 11.5])).toEqual([
        [bars[0].t, null],
        [bars[1].t, 11],
        [bars[2].t, 11.5],
      ]);
    });
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

describe("compare start alignment", () => {
  const LATER_BARS: PriceBar[] = BARS.slice(1); // compare history starts one bar later

  it("commonCompareStart returns the latest inception when calendars align", () => {
    expect(
      commonCompareStart(BARS, [COMPARE], { [COMPARE.key]: LATER_BARS }),
    ).toBe(LATER_BARS[0].t);
    expect(commonCompareStart(BARS, [], {})).toBe(BARS[0].t);
    expect(commonCompareStart([], [], {})).toBeNull();
  });

  it("commonCompareStart returns the first bar SHARED by all series when calendars differ", () => {
    // Compare starts earlier (Jan 1) than the main series (Jan 2) but is
    // missing Jan 2 — so the latest inception (Jan 2) is not a shared bar.
    // The first bar present in both is Jan 3.
    const crossCalendar: PriceBar[] = [
      { t: Date.UTC(2024, 0, 1), o: 1, h: 1, l: 1, c: 1, v: 0 },
      { t: Date.UTC(2024, 0, 3), o: 1, h: 1, l: 1, c: 1, v: 0 },
      { t: Date.UTC(2024, 0, 4), o: 1, h: 1, l: 1, c: 1, v: 0 },
    ];
    expect(
      commonCompareStart(BARS, [COMPARE], { [COMPARE.key]: crossCalendar }),
    ).toBe(Date.UTC(2024, 0, 3));
  });

  it("clipBarsFrom drops bars before the alignment start and is a no-op on null", () => {
    expect(clipBarsFrom(BARS, LATER_BARS[0].t)).toEqual(LATER_BARS);
    expect(clipBarsFrom(BARS, null)).toEqual(BARS);
  });

  it("Core percent mode rebases main and compare at the same (later) date", () => {
    const opt = buildHcPriceCoreOption({
      symbol: "FUNDX",
      bars: BARS,
      mode: "nav",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: false },
      scale: { log: false, pct: true },
      compares: [COMPARE],
      compareData: { [COMPARE.key]: LATER_BARS },
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{ data?: Array<[number, number]> }>;
    // Main series is clipped to the compare's inception: both start at 0% on
    // the SAME date instead of each on its own first bar.
    expect(series[0]?.data?.[0]).toEqual([LATER_BARS[0].t, 0]);
    expect(series[1]?.data?.[0]).toEqual([LATER_BARS[0].t, 0]);
  });

  it("Stock percent mode clips every series to the common inception", () => {
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
      compareData: { [COMPARE.key]: LATER_BARS },
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{
      id?: string;
      data?: Array<[number, number]>;
    }>;
    const main = series.find((s) => s.id === PRICE_SERIES_ID);
    const compare = series.find((s) => s.id === `compare-${COMPARE.key}`);
    expect(main?.data?.[0]?.[0]).toBe(LATER_BARS[0].t);
    expect(compare?.data?.[0]?.[0]).toBe(LATER_BARS[0].t);
  });

  it("price mode (non-percent) keeps full histories untouched", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: false },
      scale: { log: false, pct: false },
      compares: [COMPARE],
      compareData: { [COMPARE.key]: LATER_BARS },
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{ id?: string; data?: Array<[number, number]> }>;
    const main = series.find((s) => s.id === PRICE_SERIES_ID);
    expect(main?.data?.[0]?.[0]).toBe(BARS[0].t);
  });
});

describe("priceCore option builder", () => {
  it("builds Core-safe line options without Stock-only controls or indicator series", () => {
    const opt = buildHcPriceCoreOption({
      symbol: "FUNDX",
      bars: BARS,
      mode: "nav",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: true, sma50: true },
      panes: { volume: true, rsi: true },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const stockOnly = opt as typeof opt & {
      rangeSelector?: unknown;
      navigator?: unknown;
      scrollbar?: unknown;
      stockTools?: unknown;
    };
    const series = opt.series as Array<{ id?: string; type?: string }>;
    expect(stockOnly.rangeSelector).toBeUndefined();
    expect(stockOnly.navigator).toBeUndefined();
    expect(stockOnly.scrollbar).toBeUndefined();
    expect(stockOnly.stockTools).toBeUndefined();
    expect(series).toHaveLength(1);
    expect(series[0]).toMatchObject({ id: PRICE_SERIES_ID, type: "line" });
    expect(series.some((s) => s.type === "sma" || s.type === "rsi")).toBe(false);
  });

  it("normalizes compare series to percent in Core mode without Stock compare", () => {
    const opt = buildHcPriceCoreOption({
      symbol: "FUNDX",
      bars: BARS,
      mode: "nav",
      type: "area",
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
    const series = opt.series as Array<{ data?: Array<[number, number]>; type?: string }>;
    expect(plotOptions.series?.compare).toBeUndefined();
    expect(series[0]?.type).toBe("area");
    expect(series[0]?.data?.map((point) => Number(point[1].toFixed(4)))).toEqual([
      0,
      -3.7037,
      -0.9259,
    ]);
    expect(series[1]?.data?.[0]?.[1]).toBe(0);
  });

  it("groups Core mode data to the last close in each month", () => {
    const opt = buildHcPriceCoreOption({
      symbol: "FUNDX",
      bars: [
        { t: Date.UTC(2024, 0, 2), o: 1, h: 1, l: 1, c: 10, v: 0 },
        { t: Date.UTC(2024, 0, 31), o: 1, h: 1, l: 1, c: 12, v: 0 },
        { t: Date.UTC(2024, 1, 1), o: 1, h: 1, l: 1, c: 15, v: 0 },
      ],
      mode: "nav",
      type: "line",
      period: "M",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: false },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{ data?: Array<[number, number]> }>;
    expect(series[0]?.data).toEqual([
      [Date.UTC(2024, 0, 31), 12],
      [Date.UTC(2024, 1, 1), 15],
    ]);
  });

  it("never sets yAxis.labels to undefined (would crash Highcharts Axis.init on labels.rotation)", () => {
    const base: Omit<PriceStockOptionsInput, "scale"> = {
      symbol: "FUNDX",
      bars: BARS,
      mode: "nav",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    };

    // Non-percent: the labels key must be OMITTED (not `labels: undefined`),
    // otherwise Highcharts' merge overwrites the default labels object with
    // undefined and Axis.init throws reading `labels.rotation`.
    const linear = buildHcPriceCoreOption({ ...base, scale: { log: false, pct: false } });
    expect("labels" in (linear.yAxis as Record<string, unknown>)).toBe(false);

    // Percent: the labels object is still emitted for the % tick format.
    const percent = buildHcPriceCoreOption({ ...base, scale: { log: false, pct: true } });
    expect((percent.yAxis as { labels?: unknown }).labels).toEqual({ format: "{value}%" });
  });
});

describe("priceStockTooltipFormatter", () => {
  const colSeries = (name: string) => ({ series: { name, options: { type: "column" } } });
  const lineSeries = (name: string) => ({ series: { name, options: { type: "line" } } });

  it("renders an O/H/L/C row with a bold close, SMA values, and compact volume", () => {
    const ctx = {
      x: Date.UTC(2024, 0, 2),
      points: [
        { ...lineSeries("AAPL"), open: 100, high: 110, low: 95, close: 108, y: 108, color: "#000" },
        { ...lineSeries("SMA20"), y: 105.25, color: "#abc" },
        { ...colSeries("Volume"), y: 1_500_000, color: "#999" },
      ],
    };
    const html = priceStockTooltipFormatter.call(ctx as never, false, "#777");
    expect(html).toContain("O 100.00 · H 110.00 · L 95.00");
    expect(html).toContain("C <b>108.00</b>");
    expect(html).toContain("SMA20: 105.25");
    expect(html).toContain("Vol: 1.5M");
  });

  it("renders a single Price row for line series without OHLC fields", () => {
    const ctx = {
      x: Date.UTC(2024, 0, 2),
      points: [{ ...lineSeries("AAPL"), point: {}, y: 108, color: "#000" }],
    };
    const html = priceStockTooltipFormatter.call(ctx as never, false, "#777");
    expect(html).toContain("Price: <b>108.00</b>");
  });

  it("labels the value row 'Change' with a percent suffix under the percent scale", () => {
    const ctx = {
      x: Date.UTC(2024, 0, 2),
      points: [{ ...lineSeries("AAPL"), point: {}, y: 3.5, color: "#000" }],
    };
    const html = priceStockTooltipFormatter.call(ctx as never, true, "#777");
    expect(html).toContain("Change: <b>3.50%</b>");
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
