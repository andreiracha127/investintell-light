import { describe, expect, it, vi } from "vitest";

import {
  applyTickToLiveChart,
  mergeTickIntoBars,
  mergeTickIntoBarsResult,
  parseTickTimeMs,
} from "@/lib/charts/hc/priceStockLive";
import {
  PRICE_SERIES_ID,
  VOLUME_SERIES_ID,
  type PriceBar,
} from "@/lib/charts/hc/priceStock";

const DAY1 = Date.UTC(2024, 0, 2, 21);
const DAY2 = Date.UTC(2024, 0, 3, 14);

const BARS: PriceBar[] = [
  { t: Date.UTC(2024, 0, 2), o: 100, h: 105, l: 98, c: 102, v: 1000 },
];

describe("parseTickTimeMs", () => {
  it("parses an ISO time string", () => {
    expect(parseTickTimeMs("2024-01-03T14:30:00.000Z", DAY1)).toBe(
      Date.UTC(2024, 0, 3, 14, 30),
    );
  });

  it("falls back when the tick time is empty or invalid", () => {
    expect(parseTickTimeMs("", DAY1)).toBe(DAY1);
    expect(parseTickTimeMs("not-a-date", DAY1)).toBe(DAY1);
  });
});

describe("mergeTickIntoBars", () => {
  it("updates the latest bar when the tick is on the same UTC date", () => {
    const next = mergeTickIntoBars(BARS, { price: 107, size: 50, timeMs: DAY1 });
    expect(next).toHaveLength(1);
    expect(next[0]).toEqual({
      t: BARS[0].t,
      o: 100,
      h: 107,
      l: 98,
      c: 107,
      v: 1050,
    });
    expect(BARS[0].c).toBe(102);
  });

  it("appends a new bar when the tick is on a later UTC date", () => {
    const next = mergeTickIntoBars(BARS, { price: 111, size: 75, timeMs: DAY2 });
    expect(next).toHaveLength(2);
    expect(next[1]).toEqual({
      t: Date.UTC(2024, 0, 3),
      o: 111,
      h: 111,
      l: 111,
      c: 111,
      v: 75,
    });
  });

  it("returns the same empty array when there are no bars", () => {
    const empty: PriceBar[] = [];
    expect(mergeTickIntoBars(empty, { price: 1, size: 1, timeMs: DAY1 })).toBe(empty);
  });
});

describe("mergeTickIntoBarsResult", () => {
  it("flags a same-day tick as an update of the last bar (appended=false)", () => {
    const result = mergeTickIntoBarsResult(BARS, { price: 107, size: 50, timeMs: DAY1 });
    expect(result.appended).toBe(false);
    expect(result.bars).toHaveLength(1);
    expect(result.bars[0].c).toBe(107);
  });

  it("flags a new-day tick as an append (appended=true)", () => {
    const result = mergeTickIntoBarsResult(BARS, { price: 111, size: 75, timeMs: DAY2 });
    expect(result.appended).toBe(true);
    expect(result.bars).toHaveLength(2);
  });

  it("returns appended=false and the same empty array when there are no bars", () => {
    const empty: PriceBar[] = [];
    const result = mergeTickIntoBarsResult(empty, { price: 1, size: 1, timeMs: DAY1 });
    expect(result.appended).toBe(false);
    expect(result.bars).toBe(empty);
  });
});

type FakePoint = { update: ReturnType<typeof vi.fn> };
type FakeSeries = {
  points: FakePoint[];
  setData: ReturnType<typeof vi.fn>;
  addPoint: ReturnType<typeof vi.fn>;
};

function makeChart() {
  const pricePoint: FakePoint = { update: vi.fn() };
  const volumePoint: FakePoint = { update: vi.fn() };
  const price: FakeSeries = {
    points: [pricePoint],
    setData: vi.fn(),
    addPoint: vi.fn(),
  };
  const volume: FakeSeries = {
    points: [volumePoint],
    setData: vi.fn(),
    addPoint: vi.fn(),
  };
  const redraw = vi.fn();
  const chart = {
    get: (id: string) =>
      id === PRICE_SERIES_ID ? price : id === VOLUME_SERIES_ID ? volume : undefined,
    redraw,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
  return { chart, price, volume, pricePoint, volumePoint, redraw };
}

const UPDATED_BAR: PriceBar = {
  t: Date.UTC(2024, 0, 2),
  o: 100,
  h: 107,
  l: 98,
  c: 107,
  v: 1050,
};
const NEW_BAR: PriceBar = {
  t: Date.UTC(2024, 0, 3),
  o: 111,
  h: 111,
  l: 111,
  c: 111,
  v: 75,
};

describe("applyTickToLiveChart", () => {
  it("updates the last point in place (not setData) for a same-day bar", () => {
    const { chart, price, pricePoint } = makeChart();
    applyTickToLiveChart({
      chart,
      bar: UPDATED_BAR,
      appended: false,
      type: "candles",
      showVolume: false,
    });
    expect(pricePoint.update).toHaveBeenCalledWith(
      [UPDATED_BAR.t, 100, 107, 98, 107],
      false,
    );
    expect(price.addPoint).not.toHaveBeenCalled();
    expect(price.setData).not.toHaveBeenCalled();
  });

  it("uses [t, c] for line/area updates", () => {
    const { chart, pricePoint } = makeChart();
    applyTickToLiveChart({
      chart,
      bar: UPDATED_BAR,
      appended: false,
      type: "line",
      showVolume: false,
    });
    expect(pricePoint.update).toHaveBeenCalledWith([UPDATED_BAR.t, 107], false);
  });

  it("appends a point (addPoint, not setData) for a new-day bar", () => {
    const { chart, price, pricePoint } = makeChart();
    applyTickToLiveChart({
      chart,
      bar: NEW_BAR,
      appended: true,
      type: "candles",
      showVolume: false,
    });
    expect(price.addPoint).toHaveBeenCalledWith(
      [NEW_BAR.t, 111, 111, 111, 111],
      false,
      false,
    );
    expect(pricePoint.update).not.toHaveBeenCalled();
    expect(price.setData).not.toHaveBeenCalled();
  });

  it("updates the volume point in place when showVolume is true", () => {
    const { chart, volume, volumePoint } = makeChart();
    applyTickToLiveChart({
      chart,
      bar: UPDATED_BAR,
      appended: false,
      type: "candles",
      showVolume: true,
    });
    expect(volumePoint.update).toHaveBeenCalledWith([UPDATED_BAR.t, 1050], false);
    expect(volume.addPoint).not.toHaveBeenCalled();
  });

  it("appends a volume point when showVolume is true and appended", () => {
    const { chart, volume } = makeChart();
    applyTickToLiveChart({
      chart,
      bar: NEW_BAR,
      appended: true,
      type: "candles",
      showVolume: true,
    });
    expect(volume.addPoint).toHaveBeenCalledWith([NEW_BAR.t, 75], false, false);
  });

  it("does not touch volume when showVolume is false", () => {
    const { chart, volume, volumePoint } = makeChart();
    applyTickToLiveChart({
      chart,
      bar: UPDATED_BAR,
      appended: false,
      type: "candles",
      showVolume: false,
    });
    expect(volumePoint.update).not.toHaveBeenCalled();
    expect(volume.addPoint).not.toHaveBeenCalled();
  });

  it("redraws once when redraw is true, never otherwise", () => {
    const a = makeChart();
    applyTickToLiveChart({
      chart: a.chart,
      bar: UPDATED_BAR,
      appended: false,
      type: "candles",
      showVolume: false,
      redraw: true,
    });
    expect(a.redraw).toHaveBeenCalledTimes(1);
    expect(a.redraw).toHaveBeenCalledWith(false);

    const b = makeChart();
    applyTickToLiveChart({
      chart: b.chart,
      bar: UPDATED_BAR,
      appended: false,
      type: "candles",
      showVolume: false,
    });
    expect(b.redraw).not.toHaveBeenCalled();
  });

  it("is a no-op when the main series is missing", () => {
    const redraw = vi.fn();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const chart = { get: () => undefined, redraw } as any;
    expect(() =>
      applyTickToLiveChart({
        chart,
        bar: UPDATED_BAR,
        appended: false,
        type: "candles",
        showVolume: true,
        redraw: true,
      }),
    ).not.toThrow();
    expect(redraw).not.toHaveBeenCalled();
  });
});
