import { describe, expect, it } from "vitest";
import type { SeriesTreemapOptions } from "highcharts";

import { buildHcExposureTreemapOption } from "@/lib/charts/hc/treemap";
import type { ExposureItem } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";

const COLORS: ChartColors = {
  gain: "#198038",
  loss: "#a2191f",
  accent: "#7a1c24",
  accentMuted: "#6a181f",
  text: "#161616",
  textSecondary: "#525252",
  textMuted: "#6f6f6f",
  grid: "#ececec",
  surface: "#ffffff",
  accentWash: "#f4eaeb",
  textOnAccent: "#ffffff",
  bar: "#2b2f36",
  barMute: "#c4c8cf",
  blue: "#0f62fe",
  amber: "#9b6a00",
  categories: ["#7a1c24", "#2b2f36", "#565b63"],
};

const ITEMS: ExposureItem[] = [
  { key: "us_eq", label: "US Equity", direct_pct: 40, indirect_pct: 10, total_pct: 50 },
  { key: "fi", label: "Fixed Income", direct_pct: 0, indirect_pct: 30, total_pct: 30 },
  { key: "cash", label: "Cash", direct_pct: 0, indirect_pct: 0, total_pct: 20 },
  { key: "empty", label: "Empty", direct_pct: 0, indirect_pct: 0, total_pct: 0 },
];

function pointById(series: SeriesTreemapOptions, id: string) {
  const data = series.data as Array<{ id?: string; name: string; color?: string }>;
  return data.find((d) => d.id === id);
}

describe("buildHcExposureTreemapOption", () => {
  it("renders a single treemap series with squarified layout", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    expect(opt.chart?.type).toBe("treemap");
    const series = opt.series?.[0] as SeriesTreemapOptions;
    expect(series.type).toBe("treemap");
    expect(series.layoutAlgorithm).toBe("squarified");
  });

  it("is non-traversable by default", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    expect(series.allowTraversingTree).toBe(false);
  });

  it("opts into a zoomable (traversable) tree when configured", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS, { traversable: true });
    const series = opt.series?.[0] as SeriesTreemapOptions;
    expect(series.allowTraversingTree).toBe(true);
  });

  it("drops buckets with zero total", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    const names = (series.data as Array<{ name: string }>).map((d) => d.name);
    expect(names).not.toContain("Empty");
  });

  it("emits a parent tile plus direct/indirect leaves per bucket", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    const data = series.data as Array<{
      id?: string;
      name: string;
      parent?: string;
      value?: number;
    }>;
    // US Equity: parent + Direct(40) + Via funds(10).
    const usParent = data.find((d) => d.id === "bucket-0");
    expect(usParent?.name).toBe("US Equity");
    const usLeaves = data.filter((d) => d.parent === "bucket-0");
    expect(usLeaves.map((l) => l.name)).toEqual(["Direct", "Via funds"]);
    expect(usLeaves.map((l) => l.value)).toEqual([40, 10]);
  });

  it("emits a single Via funds leaf when there is no direct exposure", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    const data = series.data as Array<{ name: string; parent?: string; value?: number }>;
    const fiLeaves = data.filter((d) => d.parent === "bucket-1");
    expect(fiLeaves.map((l) => l.name)).toEqual(["Via funds"]);
    expect(fiLeaves[0]?.value).toBe(30);
  });

  it("falls back to a single full leaf for a bucket with total but no split (Cash)", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    const data = series.data as Array<{ name: string; parent?: string; value?: number }>;
    const cashLeaves = data.filter((d) => d.parent === "bucket-2");
    expect(cashLeaves).toHaveLength(1);
    expect(cashLeaves[0]?.value).toBe(20);
  });

  it("colors the Cash bucket with the muted grey", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    expect(pointById(series, "bucket-2")?.color).toBe(COLORS.barMute);
  });

  it("does not mutate the input array", () => {
    const input = [...ITEMS];
    buildHcExposureTreemapOption(input, COLORS);
    expect(input).toEqual(ITEMS);
  });
});
