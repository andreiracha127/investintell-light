import { describe, expect, it } from "vitest";
import type { SeriesTreemapOptions } from "highcharts";

import {
  buildHcExposureTreemapOption,
  exposureBucketLabel,
} from "@/lib/charts/hc/treemap";
import type { ExposureItem, PortfolioLookthrough } from "@/lib/api/client";
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

  it("keeps the flat fallback non-traversable", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    expect(series.allowTraversingTree).toBe(false);
  });

  it("uses the asset-class hierarchy when tree nodes are available", () => {
    const tree: PortfolioLookthrough["tree"] = [
      {
        id: "asset|EC",
        parent_id: null,
        key: "EC",
        label: "EC",
        kind: "asset_class",
        value_pct: 60,
      },
      {
        id: "issuer|EC|037833",
        parent_id: "asset|EC",
        key: "037833",
        label: "Apple Inc",
        kind: "issuer",
        value_pct: 60,
      },
      {
        id: "security|EC|037833|037833100",
        parent_id: "issuer|EC|037833",
        key: "037833100",
        label: "Apple Inc",
        kind: "security",
        value_pct: 60,
      },
    ];
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS, {
      dimension: "asset_class",
      tree,
    });
    const series = opt.series?.[0] as SeriesTreemapOptions;
    const data = series.data as Array<{
      id?: string;
      name: string;
      parent?: string;
      value?: number;
    }>;
    expect(series.allowTraversingTree).toBe(true);
    expect(data.find((d) => d.id === "asset|EC")?.name).toBe("Equity");
    expect(data.find((d) => d.id === "asset|EC")?.value).toBeUndefined();
    expect(data.find((d) => d.id === "security|EC|037833|037833100")?.value).toBe(60);
  });

  it("drops buckets with zero total", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    const names = (series.data as Array<{ name: string }>).map((d) => d.name);
    expect(names).not.toContain("Empty");
  });

  it("emits one tile per bucket sized by total exposure", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    const data = series.data as Array<{
      id?: string;
      name: string;
      parent?: string;
      value?: number;
    }>;
    const usTile = data.find((d) => d.id === "bucket-0");
    expect(usTile?.name).toBe("US Equity");
    expect(usTile?.value).toBe(50);
    expect(data.some((d) => d.parent)).toBe(false);
  });

  it("uses total exposure even when there is no direct exposure", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    const data = series.data as Array<{ id?: string; name: string; value?: number }>;
    const fiTile = data.find((d) => d.id === "bucket-1");
    expect(fiTile?.name).toBe("Fixed Income");
    expect(fiTile?.value).toBe(30);
  });

  it("keeps a bucket with total but no direct/indirect split", () => {
    const opt = buildHcExposureTreemapOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesTreemapOptions;
    const data = series.data as Array<{ id?: string; name: string; value?: number }>;
    const cashTile = data.find((d) => d.id === "bucket-2");
    expect(cashTile?.name).toBe("Cash");
    expect(cashTile?.value).toBe(20);
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

  it("sanitizes N-PORT asset class codes", () => {
    expect(
      exposureBucketLabel(
        { key: "EC", label: null, direct_pct: 100, indirect_pct: 0, total_pct: 100 },
        "asset_class",
      ),
    ).toBe("Equity");
    expect(
      exposureBucketLabel(
        { key: "DBT", label: null, direct_pct: 20, indirect_pct: 0, total_pct: 20 },
        "asset_class",
      ),
    ).toBe("Debt");
    expect(
      exposureBucketLabel(
        { key: "RA", label: null, direct_pct: 10, indirect_pct: 0, total_pct: 10 },
        "asset_class",
      ),
    ).toBe("Real assets");
  });
});
