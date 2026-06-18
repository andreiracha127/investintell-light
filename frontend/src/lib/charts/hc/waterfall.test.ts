import { describe, expect, it } from "vitest";
import type { SeriesWaterfallOptions } from "highcharts";

import {
  buildHcContributionWaterfallOption,
  type ContributionRow,
} from "@/lib/charts/hc/waterfall";
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
  categories: ["#7a1c24", "#2b2f36", "#565b63"],
};

const ROWS: ContributionRow[] = [
  { label: "AAPL", value: 1200, ret: 0.12 },
  { label: "JPM", value: -300, ret: -0.04 },
  { label: "MSFT", value: 800, ret: 0.08 },
];

describe("buildHcContributionWaterfallOption", () => {
  it("renders a single waterfall series sorted by contribution desc", () => {
    const opt = buildHcContributionWaterfallOption(ROWS, COLORS);
    expect(opt.chart?.type).toBe("waterfall");
    const series = opt.series?.[0] as SeriesWaterfallOptions;
    expect(series.type).toBe("waterfall");
    // 3 holdings + the closing Total point.
    expect(series.data).toHaveLength(4);
    const names = (series.data as Array<{ name: string }>).map((d) => d.name);
    expect(names).toEqual(["AAPL", "MSFT", "JPM", "Total"]);
  });

  it("marks the final point as a sum in graphite", () => {
    const opt = buildHcContributionWaterfallOption(ROWS, COLORS);
    const series = opt.series?.[0] as SeriesWaterfallOptions;
    const last = (series.data as Array<{ isSum?: boolean; color?: string }>)[3];
    expect(last.isSum).toBe(true);
    expect(last.color).toBe(COLORS.bar);
  });

  it("colors rises gain and falls loss via series up/down colors", () => {
    const opt = buildHcContributionWaterfallOption(ROWS, COLORS);
    const wf = opt.plotOptions?.waterfall as {
      upColor?: string;
      color?: string;
    };
    expect(wf.upColor).toBe(COLORS.gain);
    expect(wf.color).toBe(COLORS.loss);
  });

  it("carries each holding's return on point.custom for the tooltip", () => {
    const opt = buildHcContributionWaterfallOption(ROWS, COLORS);
    const series = opt.series?.[0] as SeriesWaterfallOptions;
    const aapl = (series.data as Array<{ name: string; custom?: { ret: number } }>)[0];
    expect(aapl.name).toBe("AAPL");
    expect(aapl.custom?.ret).toBe(0.12);
  });

  it("does not mutate the input array", () => {
    const input = [...ROWS];
    buildHcContributionWaterfallOption(input, COLORS);
    expect(input).toEqual(ROWS);
  });
});
