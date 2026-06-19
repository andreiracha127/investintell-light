import { describe, expect, it } from "vitest";
import type { SeriesSunburstOptions } from "highcharts";

import {
  assetClassLabel,
  buildHcExposureSunburstOption,
} from "@/lib/charts/hc/sunburst";
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

const TREE: PortfolioLookthrough["tree"] = [
  {
    id: "asset|equity",
    parent_id: null,
    key: "equity",
    label: "Equity",
    kind: "asset_class",
    value_pct: 60,
  },
  {
    id: "strategy|equity|Large Blend",
    parent_id: "asset|equity",
    key: "Large Blend",
    label: "Large Blend",
    kind: "strategy",
    value_pct: 60,
  },
  {
    id: "series|equity|Large Blend|S_A",
    parent_id: "strategy|equity|Large Blend",
    key: "S_A",
    label: "Parent ETF",
    kind: "series",
    value_pct: 60,
  },
  {
    id: "cusip|equity|Large Blend|S_A|037833100",
    parent_id: "series|equity|Large Blend|S_A",
    key: "037833100",
    label: "Apple Inc",
    kind: "cusip",
    value_pct: 60,
  },
];

const ASSETS: ExposureItem[] = [
  { key: "equity", label: null, direct_pct: 60, indirect_pct: 0, total_pct: 60 },
];

describe("buildHcExposureSunburstOption", () => {
  it("builds a drillable sunburst series from the exposure tree", () => {
    const opt = buildHcExposureSunburstOption(TREE, ASSETS, COLORS);
    expect(opt.chart?.type).toBe("sunburst");
    const series = opt.series?.[0] as SeriesSunburstOptions;
    expect(series.type).toBe("sunburst");
    expect(series.allowDrillToNode).toBe(true);
  });

  it("adds a root and maps asset parents under it", () => {
    const opt = buildHcExposureSunburstOption(TREE, ASSETS, COLORS);
    const series = opt.series?.[0] as SeriesSunburstOptions;
    const data = series.data as Array<{ id?: string; parent?: string; name?: string; value?: number }>;
    expect(data.find((point) => point.id === "portfolio-root")?.parent).toBe("");
    expect(data.find((point) => point.id === "asset|equity")?.parent).toBe("portfolio-root");
    expect(data.find((point) => point.id === "asset|equity")?.name).toBe("Equity");
    expect(data.find((point) => point.id === "strategy|equity|Large Blend")?.name).toBe("Large Blend");
    expect(data.find((point) => point.id === "series|equity|Large Blend|S_A")?.name).toBe("Parent ETF");
    expect(data.find((point) => point.id === "cusip|equity|Large Blend|S_A|037833100")?.name).toBe("Apple Inc");
  });

  it("assigns values only to leaf holdings", () => {
    const opt = buildHcExposureSunburstOption(TREE, ASSETS, COLORS);
    const series = opt.series?.[0] as SeriesSunburstOptions;
    const data = series.data as Array<{ id?: string; value?: number }>;
    expect(data.find((point) => point.id === "asset|equity")?.value).toBeUndefined();
    expect(data.find((point) => point.id === "strategy|equity|Large Blend")?.value).toBeUndefined();
    expect(data.find((point) => point.id === "series|equity|Large Blend|S_A")?.value).toBeUndefined();
    expect(data.find((point) => point.id === "cusip|equity|Large Blend|S_A|037833100")?.value).toBe(60);
  });

  it("sanitizes N-PORT asset class codes", () => {
    expect(assetClassLabel("EC")).toBe("Equity");
    expect(assetClassLabel("DBT")).toBe("Debt");
    expect(assetClassLabel("RA")).toBe("Real assets");
    expect(assetClassLabel("fixed_income")).toBe("Fixed Income");
    expect(assetClassLabel("alternatives")).toBe("Alternatives");
  });
});
