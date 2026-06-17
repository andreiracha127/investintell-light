import { describe, expect, it } from "vitest";

import {
  buildHcMacroPerformanceOption,
  buildHcMacroRotationOption,
  buildHcRegimeStripOption,
} from "@/lib/charts/hc/regime";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { MacroRegime, RegimeFlip } from "@/lib/api/client";

/** Epoch ms for a "YYYY-MM-DD" date, UTC-safe (mirrors the builder). */
function ms(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/**
 * Mirror of the builder's private `withAlpha`: `#RRGGBB` + alpha -> rgba string.
 * The builder bakes the risk_on wash into the point `color` because xrange has
 * no per-point `opacity`; the expected color must be alpha-encoded the same way.
 */
function withAlpha(hex: string, a: number): string {
  const int = parseInt(hex.slice(1), 16);
  const r = (int >> 16) & 0xff;
  const g = (int >> 8) & 0xff;
  const b = int & 0xff;
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

const FLIPS: RegimeFlip[] = [
  { date: "2024-01-01", state: "risk_on" },
  { date: "2024-02-01", state: "risk_off" },
  { date: "2024-03-01", state: "risk_on" },
];
const AS_OF = "2024-04-01";

type XPoint = {
  x?: number;
  x2?: number;
  y?: number;
  name?: string;
  color?: string;
  custom?: { start?: string; end?: string; days?: number };
};

function points(opt: NonNullable<ReturnType<typeof buildHcRegimeStripOption>>): XPoint[] {
  const series = opt.series?.[0] as { data?: XPoint[] };
  return series.data ?? [];
}

describe("buildHcRegimeStripOption", () => {
  it("renders the periods as a single xrange data series", () => {
    const opt = buildHcRegimeStripOption(FLIPS, TEST_COLORS, AS_OF)!;
    // Every series is xrange; the period data lives in series[0]. (Additional
    // empty series exist only to seed the deduplicated legend swatches.)
    for (const s of opt.series ?? []) {
      expect((s as { type?: string }).type).toBe("xrange");
    }
    const dataBearing = (opt.series ?? []).filter(
      (s) => ((s as { data?: unknown[] }).data?.length ?? 0) > 0,
    );
    expect(dataBearing).toHaveLength(1);
  });

  it("maps each period to an x/x2 = start/end epoch-ms point", () => {
    const opt = buildHcRegimeStripOption(FLIPS, TEST_COLORS, AS_OF)!;
    const data = points(opt);
    expect(data).toHaveLength(3);
    expect(data[0].x).toBe(ms("2024-01-01"));
    expect(data[0].x2).toBe(ms("2024-02-01"));
    expect(data[1].x).toBe(ms("2024-02-01"));
    expect(data[1].x2).toBe(ms("2024-03-01"));
    // last period closed by asOf
    expect(data[2].x).toBe(ms("2024-03-01"));
    expect(data[2].x2).toBe(ms("2024-04-01"));
  });

  it("places every period on the single y=0 row", () => {
    const opt = buildHcRegimeStripOption(FLIPS, TEST_COLORS, AS_OF)!;
    for (const p of points(opt)) {
      expect(p.y).toBe(0);
    }
  });

  it("sorts flips ascending by date before deriving periods", () => {
    const unsorted: RegimeFlip[] = [
      { date: "2024-03-01", state: "risk_on" },
      { date: "2024-01-01", state: "risk_on" },
      { date: "2024-02-01", state: "risk_off" },
    ];
    const opt = buildHcRegimeStripOption(unsorted, TEST_COLORS, AS_OF)!;
    const data = points(opt);
    expect(data.map((p) => p.x)).toEqual([
      ms("2024-01-01"),
      ms("2024-02-01"),
      ms("2024-03-01"),
    ]);
  });

  it("colors risk_on with the alpha-washed gain token and risk_off with the loss token", () => {
    const opt = buildHcRegimeStripOption(FLIPS, TEST_COLORS, AS_OF)!;
    const data = points(opt);
    // risk_on bakes the 0.18 wash into the color (xrange ignores per-point opacity)
    expect(data[0].color).toBe(withAlpha(TEST_COLORS.gain, 0.18)); // risk_on
    expect(data[1].color).toBe(TEST_COLORS.loss); // risk_off (full strength)
    expect(data[2].color).toBe(withAlpha(TEST_COLORS.gain, 0.18)); // risk_on
  });

  it("encodes the risk_on wash into the point color as rgba alpha, with no bare opacity field", () => {
    const opt = buildHcRegimeStripOption(FLIPS, TEST_COLORS, AS_OF)!;
    const data = points(opt) as Array<XPoint & { opacity?: unknown }>;
    // The 0.18 wash lives in the color channel, encoded as rgba(...).
    expect(data[0].color).toBe(withAlpha(TEST_COLORS.gain, 0.18));
    expect(data[0].color).toMatch(/^rgba\(\d+, \d+, \d+, 0\.18\)$/);
    // risk_off keeps the full-strength solid loss token (no alpha).
    expect(data[1].color).toBe(TEST_COLORS.loss);
    // No data point may carry a bare `opacity` field (silently ignored by xrange).
    for (const p of data) {
      expect("opacity" in p).toBe(false);
    }
  });

  it("labels each point Risk-on / Risk-off by state", () => {
    const opt = buildHcRegimeStripOption(FLIPS, TEST_COLORS, AS_OF)!;
    const data = points(opt);
    expect(data[0].name).toBe("Risk-on");
    expect(data[1].name).toBe("Risk-off");
  });

  it("hides the x-axis chrome", () => {
    const opt = buildHcRegimeStripOption(FLIPS, TEST_COLORS, AS_OF)!;
    const xAxis = opt.xAxis as { visible?: boolean };
    expect(xAxis.visible).toBe(false);
  });

  it("renders a per-point tooltip with state, date range and day count", () => {
    const opt = buildHcRegimeStripOption(FLIPS, TEST_COLORS, AS_OF)!;
    const tooltip = opt.tooltip as {
      // Highcharts calls the tooltip formatter with `this` bound to the hovered
      // Point itself — `name`/`custom` live directly on the point, NOT under a
      // `this.point` wrapper. Exercise that real runtime shape.
      formatter?: (this: {
        name?: string;
        custom?: { start?: string; end?: string; days?: number };
      }) => string;
    };
    const out = tooltip.formatter!.call({
      name: "Risk-off",
      custom: { start: "2024-02-01", end: "2024-03-01", days: 29 },
    });
    expect(out).toContain("Risk-off");
    expect(out).toContain("2024-02-01");
    expect(out).toContain("2024-03-01");
    expect(out).toContain("29");
  });

  it("deduplicates legend entries to one Risk-on and one Risk-off", () => {
    const opt = buildHcRegimeStripOption(FLIPS, TEST_COLORS, AS_OF)!;
    // colorByPoint must be off so the single series doesn't generate one
    // legend item per point; legend semantics are surfaced via dedicated
    // placeholder series instead.
    const legendSeries = (opt.series ?? []).filter(
      (s) => (s as { showInLegend?: boolean }).showInLegend !== false,
    );
    const names = legendSeries.map((s) => (s as { name?: string }).name);
    expect(names).toContain("Risk-on");
    expect(names).toContain("Risk-off");
    // exactly one of each label
    expect(names.filter((n) => n === "Risk-on")).toHaveLength(1);
    expect(names.filter((n) => n === "Risk-off")).toHaveLength(1);
  });

  it("returns null for an empty flip list", () => {
    expect(buildHcRegimeStripOption([], TEST_COLORS, AS_OF)).toBeNull();
  });

  it("falls back to today when asOf is omitted (last period still closes)", () => {
    const single: RegimeFlip[] = [{ date: "2024-01-01", state: "risk_on" }];
    const opt = buildHcRegimeStripOption(single, TEST_COLORS)!;
    const data = points(opt);
    expect(data).toHaveLength(1);
    expect(data[0].x).toBe(ms("2024-01-01"));
    // end is strictly after start (today >> 2024-01-01)
    expect(data[0].x2!).toBeGreaterThan(data[0].x!);
  });
});

const HISTORY: MacroRegime["history"] = [
  {
    date: "2024-01-01",
    state: "risk_on",
    vote_count: 1,
    votes: { credit: true, trend: false, nfci: false },
    signal: { ratio: 0.82, p20_5y: 0.78, distance_pct: 5.1, nfci: -0.2 },
  },
  {
    date: "2024-01-02",
    state: "risk_off",
    vote_count: 2,
    votes: { credit: true, trend: true, nfci: false },
    signal: { ratio: 0.76, p20_5y: 0.79, distance_pct: -3.8, nfci: -0.1 },
  },
  {
    date: "2024-01-03",
    state: "risk_on",
    vote_count: 0,
    votes: { credit: false, trend: false, nfci: false },
    signal: { ratio: 0.84, p20_5y: 0.79, distance_pct: 6.3, nfci: -0.4 },
  },
];

describe("buildHcMacroRotationOption", () => {
  it("returns null for empty history", () => {
    expect(buildHcMacroRotationOption([], TEST_COLORS)).toBeNull();
  });

  it("maps vote pressure into a 96-104 RRG-style quadrant path", () => {
    const opt = buildHcMacroRotationOption(HISTORY, TEST_COLORS)!;
    const path = opt.series?.[0] as {
      type?: string;
      data?: Array<{ x?: number; y?: number; custom?: { voteCount?: number } }>;
    };
    expect(path.type).toBe("line");
    expect(path.data).toHaveLength(3);
    expect(path.data?.[0].x).toBeCloseTo(96 + (2 / 3) * 8);
    expect(path.data?.[1].x).toBeCloseTo(96 + (1 / 3) * 8);
    expect(path.data?.[1].y).toBeCloseTo(97.6);
    expect(path.data?.[2].x).toBe(104);
    expect(path.data?.[2].y).toBe(104);
    expect(path.data?.[1].custom?.voteCount).toBe(2);
  });

  it("draws quadrant reference axes at 100/100", () => {
    const opt = buildHcMacroRotationOption(HISTORY, TEST_COLORS)!;
    const xAxis = opt.xAxis as { plotLines?: Array<{ value?: number }> };
    const yAxis = opt.yAxis as { plotLines?: Array<{ value?: number }> };
    expect(xAxis.plotLines?.[0].value).toBe(100);
    expect(yAxis.plotLines?.[0].value).toBe(100);
  });
});

describe("buildHcMacroPerformanceOption", () => {
  it("normalizes portfolio and asset series to 100", () => {
    const opt = buildHcMacroPerformanceOption({
      portfolio: [
        ["2024-01-01", 1000],
        ["2024-01-02", 900],
      ],
      asset: [
        ["2024-01-01", 50],
        ["2024-01-02", 55],
      ],
      regimes: HISTORY,
      colors: TEST_COLORS,
      portfolioLabel: "Portfolio",
      assetLabel: "SPY",
    })!;
    const series = opt.series as Array<{ data?: Array<[number, number]>; name?: string }>;
    expect(series[0].name).toBe("Portfolio");
    expect(series[0].data).toEqual([
      [ms("2024-01-01"), 100],
      [ms("2024-01-02"), 90],
    ]);
    expect(series[1].data).toEqual([
      [ms("2024-01-01"), 100],
      [ms("2024-01-02"), 110.00000000000001],
    ]);
  });

  it("adds regime plot bands over the datetime xAxis", () => {
    const opt = buildHcMacroPerformanceOption({
      portfolio: [
        ["2024-01-01", 1000],
        ["2024-01-03", 990],
      ],
      asset: [
        ["2024-01-01", 50],
        ["2024-01-03", 49],
      ],
      regimes: HISTORY,
      colors: TEST_COLORS,
      portfolioLabel: "Portfolio",
      assetLabel: "SPY",
    })!;
    const xAxis = opt.xAxis as {
      type?: string;
      plotBands?: Array<{ color?: string; label?: { text?: string } }>;
    };
    expect(xAxis.type).toBe("datetime");
    expect(xAxis.plotBands?.length).toBeGreaterThan(0);
    expect(xAxis.plotBands?.some((band) => band.label?.text === "Risk-off")).toBe(true);
  });
});
