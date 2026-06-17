import { describe, expect, it } from "vitest";

import { buildHcCumulativeOption } from "@/lib/charts/hc/cumulative";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import type { CumulativeReturns } from "@/lib/api/client";
import { formatDate, formatPercent } from "@/lib/format";

const CUMULATIVE: CumulativeReturns = {
  asset: [
    ["2024-01-01", 0.0],
    ["2024-01-02", 0.05],
    ["2024-01-03", -0.02],
  ],
  benchmark: [
    ["2024-01-01", 0.0],
    ["2024-01-02", 0.02],
    ["2024-01-03", 0.01],
  ],
};

describe("buildHcCumulativeOption", () => {
  it("returns a Highcharts Options object with chart type line", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    expect(opt.chart?.type).toBe("line");
  });

  it("enables the built-in legend for the comparison series", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    expect(opt.legend?.enabled).toBe(true);
  });

  it("uses a compact datetime xAxis", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    const xAxis = opt.xAxis as { type?: string; labels?: { format?: string } };
    expect(xAxis.type).toBe("datetime");
    expect(xAxis.labels?.format).toBe("{value:%b '%y}");
  });

  it("produces exactly two series", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    expect(opt.series).toHaveLength(2);
  });

  it("first series is benchmark (barMute color)", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    const s0 = opt.series![0] as { type?: string; color?: string; name?: string; data?: Array<[number, number]> };
    expect(s0.type).toBe("line");
    expect(s0.color).toBe(TEST_COLORS.barMute);
    expect(s0.name).toBe("SPY");
    expect(s0.data).toEqual([
      [dateToUtcMs("2024-01-01"), 0.0],
      [dateToUtcMs("2024-01-02"), 0.02],
      [dateToUtcMs("2024-01-03"), 0.01],
    ]);
  });

  it("second series is asset (accent color)", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    const s1 = opt.series![1] as { type?: string; color?: string; name?: string; data?: Array<[number, number]> };
    expect(s1.type).toBe("line");
    expect(s1.color).toBe(TEST_COLORS.accent);
    expect(s1.name).toBe("AAPL");
    expect(s1.data).toEqual([
      [dateToUtcMs("2024-01-01"), 0.0],
      [dateToUtcMs("2024-01-02"), 0.05],
      [dateToUtcMs("2024-01-03"), -0.02],
    ]);
  });

  it("series have markers disabled and lineWidth 2", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    for (const s of opt.series!) {
      const series = s as { marker?: { enabled?: boolean }; lineWidth?: number };
      expect(series.marker?.enabled).toBe(false);
      expect(series.lineWidth).toBe(2);
    }
  });

  it("formats yAxis labels as signed percent with 0 dp", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const formatter = yAxis.labels!.formatter!;
    expect(formatter.call({ value: 0.05 })).toBe(formatPercent(0.05, 0));
    expect(formatter.call({ value: -0.1 })).toBe(formatPercent(-0.1, 0));
    expect(formatter.call({ value: 0 })).toBe(formatPercent(0, 0));
  });

  it("formats tooltip as signed percent with 2 dp", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: { x: number; points?: Array<{ series: { name: string }; y: number }> }) => string;
    };
    const out = tooltip.formatter!.call({
      x: dateToUtcMs("2024-01-02"),
      points: [
        { series: { name: "SPY" }, y: 0.02 },
        { series: { name: "AAPL" }, y: 0.05 },
      ],
    });
    expect(out).toContain(formatDate("2024-01-02"));
    expect(out).toContain(formatPercent(0.02, 2, { signed: true }));
    expect(out).toContain(formatPercent(0.05, 2, { signed: true }));
  });

  it("handles empty CumulativeReturns gracefully", () => {
    const empty: CumulativeReturns = { asset: [], benchmark: [] };
    const opt = buildHcCumulativeOption(empty, "AAPL", "SPY", TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[]; type?: string };
    expect(xAxis.type).toBe("datetime");
    expect(xAxis.categories).toBeUndefined();
    const s0 = opt.series![0] as { data?: Array<[number, number]> };
    const s1 = opt.series![1] as { data?: Array<[number, number]> };
    expect(s0.data).toEqual([]);
    expect(s1.data).toEqual([]);
  });

  it("yAxis has no title text (global theme owns axis title chrome)", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    const yAxis = opt.yAxis as { title?: { text?: string | undefined } };
    expect(yAxis.title?.text).toBeUndefined();
  });

  it("tooltip is shared across series", () => {
    const opt = buildHcCumulativeOption(CUMULATIVE, "AAPL", "SPY", TEST_COLORS);
    expect((opt.tooltip as { shared?: boolean }).shared).toBe(true);
  });
});
