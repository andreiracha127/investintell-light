import { describe, expect, it } from "vitest";

import { buildHcMacroPerformanceOption } from "@/lib/charts/hc/regime";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { MacroRegime } from "@/lib/api/client";

/** Epoch ms for a "YYYY-MM-DD" date, UTC-safe (mirrors the builder). */
function ms(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/**
 * Mirror of the builder's private `withAlpha`: `#RRGGBB` + alpha -> rgba string.
 */
function withAlpha(hex: string, a: number): string {
  const int = parseInt(hex.slice(1), 16);
  const r = (int >> 16) & 0xff;
  const g = (int >> 8) & 0xff;
  const b = int & 0xff;
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

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

  it("uses 2.2 / 1.6 line widths for the portfolio and asset series", () => {
    const opt = buildHcMacroPerformanceOption({
      portfolio: [
        ["2024-01-01", 1000],
        ["2024-01-02", 1010],
      ],
      asset: [
        ["2024-01-01", 50],
        ["2024-01-02", 51],
      ],
      regimes: HISTORY,
      colors: TEST_COLORS,
      portfolioLabel: "Portfolio",
      assetLabel: "SPY",
    })!;
    const series = opt.series as Array<{ lineWidth?: number }>;
    expect(series[0].lineWidth).toBe(2.2);
    expect(series[1].lineWidth).toBe(1.6);
  });

  it("suppresses the Highcharts legend (the page renders its own)", () => {
    const opt = buildHcMacroPerformanceOption({
      portfolio: [
        ["2024-01-01", 1000],
        ["2024-01-02", 1010],
      ],
      asset: [
        ["2024-01-01", 50],
        ["2024-01-02", 51],
      ],
      regimes: HISTORY,
      colors: TEST_COLORS,
      portfolioLabel: "Portfolio",
      assetLabel: "SPY",
    })!;
    const legend = opt.legend as { enabled?: boolean };
    expect(legend.enabled).toBe(false);
  });

  it("projects each series to running drawdown when view is 'drawdown'", () => {
    const opt = buildHcMacroPerformanceOption({
      portfolio: [
        ["2024-01-01", 1000],
        ["2024-01-02", 1100],
        ["2024-01-03", 990],
      ],
      asset: [
        ["2024-01-01", 50],
        ["2024-01-02", 55],
        ["2024-01-03", 55],
      ],
      regimes: HISTORY,
      colors: TEST_COLORS,
      portfolioLabel: "Portfolio",
      assetLabel: "SPY",
      view: "drawdown",
    })!;
    const series = opt.series as Array<{ type?: string; data?: Array<[number, number]> }>;
    // Portfolio: new high at 1100, then -10% off that peak.
    expect(series[0].type).toBe("area");
    expect(series[0].data?.[0]).toEqual([ms("2024-01-01"), 0]);
    expect(series[0].data?.[1]).toEqual([ms("2024-01-02"), 0]);
    expect(series[0].data?.[2][1]).toBeCloseTo(-10);
    // Drawdown reference plot line sits at 0, not 100.
    const yAxis = opt.yAxis as { plotLines?: Array<{ value?: number }> };
    expect(yAxis.plotLines?.[0].value).toBe(0);
  });

  it("titles the drawdown axis 'Drawdown'", () => {
    const opt = buildHcMacroPerformanceOption({
      portfolio: [
        ["2024-01-01", 1000],
        ["2024-01-02", 990],
      ],
      asset: [
        ["2024-01-01", 50],
        ["2024-01-02", 49],
      ],
      regimes: HISTORY,
      colors: TEST_COLORS,
      portfolioLabel: "Portfolio",
      assetLabel: "SPY",
      view: "drawdown",
    })!;
    const yAxis = opt.yAxis as { title?: { text?: string } };
    expect(yAxis.title?.text).toBe("Drawdown");
  });

  it("colors the reference plot line with the muted-text token and the crosshair with grid", () => {
    const opt = buildHcMacroPerformanceOption({
      portfolio: [
        ["2024-01-01", 1000],
        ["2024-01-02", 1010],
      ],
      asset: [
        ["2024-01-01", 50],
        ["2024-01-02", 51],
      ],
      regimes: HISTORY,
      colors: TEST_COLORS,
      portfolioLabel: "Portfolio",
      assetLabel: "SPY",
    })!;
    const yAxis = opt.yAxis as { plotLines?: Array<{ color?: string }> };
    expect(yAxis.plotLines?.[0].color).toBe(TEST_COLORS.textMuted);
    const xAxis = opt.xAxis as { crosshair?: { color?: string }; tickPixelInterval?: number };
    expect(xAxis.crosshair?.color).toBe(TEST_COLORS.grid);
    expect(xAxis.tickPixelInterval).toBe(96);
  });

  it("shades only risk_off windows, with a 1px border and no band label", () => {
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
      plotBands?: Array<{
        color?: string;
        borderColor?: string;
        borderWidth?: number;
        label?: { text?: string };
      }>;
    };
    expect(xAxis.type).toBe("datetime");
    // Only the single risk_off window (2024-01-02) is shaded; risk_on windows
    // are left clear.
    expect(xAxis.plotBands).toHaveLength(1);
    const band = xAxis.plotBands![0];
    expect(band.color).toBe(withAlpha(TEST_COLORS.loss, 0.16));
    expect(band.borderColor).toBe(withAlpha(TEST_COLORS.loss, 0.4));
    expect(band.borderWidth).toBe(1);
    // No per-band "Risk-off" label text any more.
    expect(band.label).toBeUndefined();
    expect(xAxis.plotBands?.some((b) => b.label?.text === "Risk-off")).toBe(false);
  });

  it("rebases both series at the first COMMON date when inceptions differ", () => {
    const opt = buildHcMacroPerformanceOption({
      // Portfolio history starts a day later than the asset's.
      portfolio: [
        ["2024-01-02", 900],
        ["2024-01-03", 990],
      ],
      asset: [
        ["2024-01-01", 50],
        ["2024-01-02", 55],
        ["2024-01-03", 66],
      ],
      regimes: HISTORY,
      colors: TEST_COLORS,
      portfolioLabel: "Portfolio",
      assetLabel: "SPY",
    })!;
    const series = opt.series as Array<{ data?: Array<[number, number]> }>;
    // Both curves start at 100 on the SAME date (the later inception): the
    // asset's 2024-01-01 point is clipped and its base becomes the Jan-02 55.
    expect(series[0].data?.[0]).toEqual([ms("2024-01-02"), 100]);
    expect(series[1].data?.[0]).toEqual([ms("2024-01-02"), 100]);
    expect(series[1].data?.[1][1]).toBeCloseTo((66 / 55) * 100);
  });

  it("rebases both series at the first SHARED date when calendars differ", () => {
    const opt = buildHcMacroPerformanceOption({
      // Portfolio's later inception (Jan-02) is a date the asset is MISSING
      // (a holiday); the first date present in both is Jan-03.
      portfolio: [
        ["2024-01-02", 900],
        ["2024-01-03", 990],
      ],
      asset: [
        ["2024-01-01", 50],
        ["2024-01-03", 66],
      ],
      regimes: HISTORY,
      colors: TEST_COLORS,
      portfolioLabel: "Portfolio",
      assetLabel: "SPY",
    })!;
    const series = opt.series as Array<{ data?: Array<[number, number]> }>;
    // Both start at 100 on Jan-03 (first shared observation), NOT Jan-02 which
    // only the portfolio has — so the two curves are comparable.
    expect(series[0].data?.[0]).toEqual([ms("2024-01-03"), 100]);
    expect(series[1].data?.[0]).toEqual([ms("2024-01-03"), 100]);
    expect(series[0].data).toHaveLength(1);
    expect(series[1].data).toHaveLength(1);
  });
});
