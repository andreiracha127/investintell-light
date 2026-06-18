import { describe, expect, it } from "vitest";

import { buildHcMacroRrgOption } from "@/lib/charts/hc/macro-rrg";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { MacroRegime } from "@/lib/api/client";

type HistoryPoint = MacroRegime["history"][number];

/** Build a synthetic, deterministic regime history of `n` points. */
function makeHistory(n: number): HistoryPoint[] {
  const out: HistoryPoint[] = [];
  for (let i = 0; i < n; i += 1) {
    const ratio = 0.9 + 0.05 * Math.sin(i / 9);
    const p20 = 0.8;
    const distance = (ratio / p20 - 1) * 100;
    const nfci = -0.2 + 0.4 * Math.sin(i / 13);
    const credit = ratio < p20;
    const trend = i % 3 === 0;
    const nfciVote = nfci > 0;
    const vc = (credit ? 1 : 0) + (trend ? 1 : 0) + (nfciVote ? 1 : 0);
    const day = String((i % 28) + 1).padStart(2, "0");
    const month = String((Math.floor(i / 28) % 12) + 1).padStart(2, "0");
    out.push({
      date: `2025-${month}-${day}`,
      state: vc >= 2 ? "risk_off" : "risk_on",
      vote_count: vc,
      votes: { credit, trend, nfci: nfciVote },
      signal: { ratio, p20_5y: p20, distance_pct: distance, nfci },
    });
  }
  return out;
}

type SplineSeries = {
  type?: string;
  name?: string;
  data?: Array<{ x?: number; y?: number; custom?: { date?: string; signal?: string } }>;
  dashStyle?: string;
  zIndex?: number;
};

function splineSeries(opt: NonNullable<ReturnType<typeof buildHcMacroRrgOption>>): SplineSeries[] {
  return (opt.series ?? []).filter(
    (s) => (s as { type?: string }).type === "spline",
  ) as SplineSeries[];
}

describe("buildHcMacroRrgOption", () => {
  it("returns null for empty history", () => {
    expect(buildHcMacroRrgOption([], TEST_COLORS)).toBeNull();
  });

  it("emits four signal tails: Composite, Credit, Trend, Conditions", () => {
    const opt = buildHcMacroRrgOption(makeHistory(120), TEST_COLORS)!;
    const names = splineSeries(opt).map((s) => s.name);
    expect(names).toEqual(["Composite", "Credit", "Trend", "Conditions"]);
  });

  it("draws the quadrant labels as a non-interactive scatter series", () => {
    const opt = buildHcMacroRrgOption(makeHistory(120), TEST_COLORS)!;
    const quad = (opt.series ?? []).find(
      (s) => (s as { type?: string }).type === "scatter",
    ) as { data?: Array<{ dataLabels?: { format?: string } }>; enableMouseTracking?: boolean };
    const labels = (quad.data ?? []).map((d) => d.dataLabels?.format);
    expect(labels).toEqual(["RECOVERY", "EXPANSION", "CONTRACTION", "SLOWDOWN"]);
    expect(quad.enableMouseTracking).toBe(false);
  });

  it("centres both axes on 100 with reference plot lines and a 96-104 envelope", () => {
    const opt = buildHcMacroRrgOption(makeHistory(120), TEST_COLORS)!;
    const xAxis = opt.xAxis as { min?: number; max?: number; plotLines?: Array<{ value?: number }> };
    const yAxis = opt.yAxis as { min?: number; max?: number; plotLines?: Array<{ value?: number }> };
    expect(xAxis.min).toBe(96);
    expect(xAxis.max).toBe(104);
    expect(yAxis.min).toBe(96);
    expect(yAxis.max).toBe(104);
    expect(xAxis.plotLines?.[0].value).toBe(100);
    expect(yAxis.plotLines?.[0].value).toBe(100);
  });

  it("clamps every tail vertex inside the axis envelope", () => {
    const opt = buildHcMacroRrgOption(makeHistory(160), TEST_COLORS)!;
    for (const series of splineSeries(opt)) {
      for (const point of series.data ?? []) {
        expect(point.x!).toBeGreaterThanOrEqual(96);
        expect(point.x!).toBeLessThanOrEqual(104);
        expect(point.y!).toBeGreaterThanOrEqual(96);
        expect(point.y!).toBeLessThanOrEqual(104);
      }
    }
  });

  it("renders the Composite tail solid and on top, the signals dotted", () => {
    const opt = buildHcMacroRrgOption(makeHistory(120), TEST_COLORS)!;
    const [composite, credit, trend, conditions] = splineSeries(opt);
    expect(composite.dashStyle).toBe("Solid");
    expect(composite.zIndex).toBe(5);
    expect(credit.dashStyle).toBe("Dot");
    expect(trend.dashStyle).toBe("Dot");
    expect(conditions.dashStyle).toBe("Dot");
  });

  it("attaches the real date to each tail vertex for the tooltip", () => {
    const opt = buildHcMacroRrgOption(makeHistory(120), TEST_COLORS)!;
    const composite = splineSeries(opt)[0];
    const data = composite.data ?? [];
    expect(data.length).toBeGreaterThan(0);
    for (const point of data) {
      expect(point.custom?.signal).toBe("Composite");
      expect(point.custom?.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });

  it("marks the most recent vertex of each tail with a larger today marker", () => {
    const opt = buildHcMacroRrgOption(makeHistory(120), TEST_COLORS)!;
    for (const series of splineSeries(opt)) {
      const data = series.data ?? [];
      const last = data[data.length - 1] as { marker?: { radius?: number } };
      expect(last.marker?.radius).toBe(5);
    }
  });

  it("registers a render hook so the quadrant background paints on every draw", () => {
    const opt = buildHcMacroRrgOption(makeHistory(120), TEST_COLORS)!;
    const chart = opt.chart as { events?: { render?: unknown } };
    expect(typeof chart.events?.render).toBe("function");
  });

  it("renders the per-point tooltip from the vertex's signal name and date", () => {
    const opt = buildHcMacroRrgOption(makeHistory(120), TEST_COLORS)!;
    const tooltip = opt.tooltip as {
      // Highcharts binds the non-shared formatter's `this` to the hovered Point;
      // exercise that real runtime shape (custom + series live on the point).
      formatter?: (this: {
        series: { name: string; color: string };
        custom?: { date?: string; signal?: string };
      }) => string;
    };
    const out = tooltip.formatter!.call({
      series: { name: "Composite", color: "#7a1c24" },
      custom: { date: "2025-03-14", signal: "Composite" },
    });
    expect(out).toContain("Composite");
    expect(out).toContain("Mar");
    expect(out).toContain("2025");
  });
});
