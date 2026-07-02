import { describe, expect, it } from "vitest";
import type { SeriesSunburstOptions } from "highcharts";

import {
  assetClassLabel,
  buildHcExposureSunburstOption,
  computeAssetResiduals,
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
    id: "series|equity|S_A",
    parent_id: "asset|equity",
    key: "S_A",
    label: "Parent ETF",
    kind: "series",
    value_pct: 60,
  },
  {
    id: "cusip|equity|S_A|037833100",
    parent_id: "series|equity|S_A",
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
    expect(data.find((point) => point.id === "series|equity|S_A")?.name).toBe("Parent ETF");
    expect(data.find((point) => point.id === "cusip|equity|S_A|037833100")?.name).toBe("Apple Inc");
  });

  it("assigns values only to leaf holdings", () => {
    const opt = buildHcExposureSunburstOption(TREE, ASSETS, COLORS);
    const series = opt.series?.[0] as SeriesSunburstOptions;
    const data = series.data as Array<{ id?: string; value?: number }>;
    expect(data.find((point) => point.id === "asset|equity")?.value).toBeUndefined();
    expect(data.find((point) => point.id === "series|equity|S_A")?.value).toBeUndefined();
    expect(data.find((point) => point.id === "cusip|equity|S_A|037833100")?.value).toBe(60);
  });

  it("adds a residual 'Other holdings' leaf so the asset-class arc sums to the true total", () => {
    // ASSETS says equity is 75% of NAV, but the sampled tree leaves only sum
    // to 60% (e.g. a top-25 holdings cap). The arc should still add up to 75.
    const assetsWithResidual: ExposureItem[] = [
      { key: "equity", label: null, direct_pct: 75, indirect_pct: 0, total_pct: 75 },
    ];
    const opt = buildHcExposureSunburstOption(TREE, assetsWithResidual, COLORS);
    const series = opt.series?.[0] as SeriesSunburstOptions;
    const data = series.data as Array<{
      id?: string;
      parent?: string;
      name?: string;
      value?: number;
      color?: string;
    }>;
    const residual = data.find((point) => point.id === "asset|equity|__other__");
    expect(residual).toBeDefined();
    expect(residual?.parent).toBe("asset|equity");
    expect(residual?.name).toBe("Other holdings");
    expect(residual?.value).toBeCloseTo(15, 4);
    expect(residual?.color).toBe(COLORS.barMute);

    const leafSum = data
      .filter((point) => point.parent && point.value !== undefined)
      .reduce((sum, point) => sum + (point.value ?? 0), 0);
    expect(leafSum).toBeCloseTo(75, 4);
  });

  it("omits the residual leaf when the sample already covers the true total", () => {
    const opt = buildHcExposureSunburstOption(TREE, ASSETS, COLORS);
    const series = opt.series?.[0] as SeriesSunburstOptions;
    const data = series.data as Array<{ id?: string }>;
    expect(data.find((point) => point.id === "asset|equity|__other__")).toBeUndefined();
  });

  // The chart and the drill table share this residual computation so their
  // rows and totals cannot drift apart (PR review r3510027269).
  it("computeAssetResiduals derives the residual the table also renders", () => {
    const assetsWithResidual: ExposureItem[] = [
      { key: "equity", label: null, direct_pct: 75, indirect_pct: 0, total_pct: 75 },
    ];
    const residuals = computeAssetResiduals(TREE, assetsWithResidual);
    expect(residuals).toHaveLength(1);
    expect(residuals[0]).toMatchObject({
      id: "asset|equity|__other__",
      parentId: "asset|equity",
    });
    expect(residuals[0].valuePct).toBeCloseTo(15, 4);
  });

  it("computeAssetResiduals returns nothing when the sample covers the total", () => {
    expect(computeAssetResiduals(TREE, ASSETS)).toEqual([]);
  });

  it("sanitizes N-PORT asset class codes", () => {
    expect(assetClassLabel("EC")).toBe("Equity");
    expect(assetClassLabel("DBT")).toBe("Debt");
    expect(assetClassLabel("RA")).toBe("Real assets");
    expect(assetClassLabel("fixed_income")).toBe("Fixed Income");
    expect(assetClassLabel("alternatives")).toBe("Alternatives");
  });
});
