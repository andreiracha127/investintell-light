import { describe, expect, it } from "vitest";

import { buildHcScatterOption } from "@/lib/charts/hc/scatter";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { BetaResponse } from "@/lib/api/client";
import { formatPercent } from "@/lib/format";

type Pair = [number, number];

const SCATTER: Pair[] = [
  [0.01, 0.02],
  [-0.005, -0.008],
  [0.03, 0.04],
];

const REGRESSION_LINE: Pair[] = [
  [-0.005, -0.004],
  [0.03, 0.035],
];

const LABELS: BetaResponse["labels"] = { x: "SPY", y: "Portfolio" };

describe("buildHcScatterOption", () => {
  it("returns two series: scatter and line", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    expect(opt.series).toHaveLength(2);
    const [s0, s1] = opt.series as Array<{ type: string }>;
    expect(s0.type).toBe("scatter");
    expect(s1.type).toBe("line");
  });

  it("maps scatter data as [x, y] pairs", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const s = opt.series?.[0] as { data?: Pair[] };
    expect(s.data).toEqual(SCATTER);
  });

  it("maps regression line data as [x, y] pairs", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const s = opt.series?.[1] as { data?: Pair[] };
    expect(s.data).toEqual(REGRESSION_LINE);
  });

  it("colors scatter dots with accent token", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const s = opt.series?.[0] as { color?: string };
    expect(s.color).toBe(TEST_COLORS.accent);
  });

  it("colors regression line with the text token", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const s = opt.series?.[1] as { color?: string };
    expect(s.color).toBe(TEST_COLORS.text);
  });

  it("draws the regression line at lineWidth 1.8", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const s = opt.series?.[1] as { lineWidth?: number };
    expect(s.lineWidth).toBe(1.8);
  });

  it("regression line series has enableMouseTracking: false", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const s = opt.series?.[1] as { enableMouseTracking?: boolean };
    expect(s.enableMouseTracking).toBe(false);
  });

  it("scatter series has opacity 0.45 to de-emphasise overplotted dots", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const s = opt.series?.[0] as { opacity?: number };
    expect(s.opacity).toBe(0.45);
  });

  it("xAxis has tight-scaling options (no forced zero, no padding)", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const xAxis = opt.xAxis as {
      startOnTick?: boolean;
      endOnTick?: boolean;
      minPadding?: number;
      maxPadding?: number;
    };
    expect(xAxis.startOnTick).toBe(false);
    expect(xAxis.endOnTick).toBe(false);
    expect(xAxis.minPadding).toBe(0);
    expect(xAxis.maxPadding).toBe(0);
  });

  it("yAxis has tight-scaling options (no forced zero, no padding)", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const yAxis = opt.yAxis as {
      startOnTick?: boolean;
      endOnTick?: boolean;
      minPadding?: number;
      maxPadding?: number;
    };
    expect(yAxis.startOnTick).toBe(false);
    expect(yAxis.endOnTick).toBe(false);
    expect(yAxis.minPadding).toBe(0);
    expect(yAxis.maxPadding).toBe(0);
  });

  it("xAxis title appends ' daily return' to label x", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const xAxis = opt.xAxis as { title?: { text?: string } };
    expect(xAxis.title?.text).toBe("SPY daily return");
  });

  it("yAxis title appends ' daily return' to label y", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const yAxis = opt.yAxis as { title?: { text?: string } };
    expect(yAxis.title?.text).toBe("Portfolio daily return");
  });

  it("draws a value:0 plotLine (grid color) on both axes", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const xAxis = opt.xAxis as {
      plotLines?: Array<{ value?: number; color?: string }>;
    };
    const yAxis = opt.yAxis as {
      plotLines?: Array<{ value?: number; color?: string }>;
    };
    expect(xAxis.plotLines?.[0].value).toBe(0);
    expect(xAxis.plotLines?.[0].color).toBe(TEST_COLORS.grid);
    expect(yAxis.plotLines?.[0].value).toBe(0);
    expect(yAxis.plotLines?.[0].color).toBe(TEST_COLORS.grid);
  });

  it("xAxis has gridLineWidth 1", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const xAxis = opt.xAxis as { gridLineWidth?: number };
    expect(xAxis.gridLineWidth).toBe(1);
  });

  it("xAxis labels are percent-formatted", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const xAxis = opt.xAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = xAxis.labels!.formatter!.call({ value: 0.0512 });
    expect(out).toBe(formatPercent(0.0512, 1));
  });

  it("yAxis labels are percent-formatted", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = yAxis.labels!.formatter!.call({ value: -0.03 });
    expect(out).toBe(formatPercent(-0.03, 1));
  });

  it("tooltip formatter includes both axis labels and signed percent values", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: unknown) => string;
    };
    // HC tooltip formatter `this` is the hovered Point: x and y are numeric fields.
    const out = tooltip.formatter!.call({ x: 0.01, y: 0.02 });
    expect(out).toContain("SPY");
    expect(out).toContain("Portfolio");
    expect(out).toContain(formatPercent(0.01, 2, { signed: true }));
    expect(out).toContain(formatPercent(0.02, 2, { signed: true }));
  });

  it("handles empty scatter array", () => {
    const opt = buildHcScatterOption([], REGRESSION_LINE, LABELS, TEST_COLORS);
    const s = opt.series?.[0] as { data?: Pair[] };
    expect(s.data).toEqual([]);
  });

  it("handles empty regression line array", () => {
    const opt = buildHcScatterOption(SCATTER, [], LABELS, TEST_COLORS);
    const s = opt.series?.[1] as { data?: Pair[] };
    expect(s.data).toEqual([]);
  });

  it("chart type is scatter", () => {
    const opt = buildHcScatterOption(SCATTER, REGRESSION_LINE, LABELS, TEST_COLORS);
    expect((opt.chart as { type?: string }).type).toBe("scatter");
  });
});
