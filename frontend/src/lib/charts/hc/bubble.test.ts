import { describe, expect, it } from "vitest";
import type { SeriesPackedbubbleOptions } from "highcharts";

import {
  buildHcContributionBubbleOption,
  type BubbleItem,
} from "@/lib/charts/hc/bubble";
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
  categories: ["#7a1c24", "#2b2f36"],
};

const ITEMS: BubbleItem[] = [
  { ticker: "AAPL", value: 1200, ret: 0.12 },
  { ticker: "JPM", value: -300, ret: -0.04 },
  { ticker: "CASHX", value: 0, ret: 0 },
  { ticker: "MSFT", value: 800, ret: 0.08 },
];

describe("buildHcContributionBubbleOption", () => {
  it("renders a packedbubble series", () => {
    const opt = buildHcContributionBubbleOption(ITEMS, COLORS);
    expect(opt.chart?.type).toBe("packedbubble");
    const series = opt.series?.[0] as SeriesPackedbubbleOptions;
    expect(series.type).toBe("packedbubble");
  });

  it("uses magnitude as bubble value and drops zero-contribution holdings", () => {
    const opt = buildHcContributionBubbleOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesPackedbubbleOptions;
    const data = series.data as Array<{ name: string; value: number }>;
    // CASHX (0) dropped; remaining sorted by magnitude desc.
    expect(data.map((d) => d.name)).toEqual(["AAPL", "MSFT", "JPM"]);
    expect(data.map((d) => d.value)).toEqual([1200, 800, 300]);
  });

  it("colors bubbles gain/loss by the sign of the contribution", () => {
    const opt = buildHcContributionBubbleOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesPackedbubbleOptions;
    const data = series.data as Array<{ name: string; color: string }>;
    const byName = Object.fromEntries(data.map((d) => [d.name, d.color]));
    expect(byName.AAPL).toBe(COLORS.gain);
    expect(byName.JPM).toBe(COLORS.loss);
  });

  it("carries signed contribution and return on point.custom", () => {
    const opt = buildHcContributionBubbleOption(ITEMS, COLORS);
    const series = opt.series?.[0] as SeriesPackedbubbleOptions;
    const data = series.data as Array<{
      name: string;
      custom?: { contribution: number; ret: number };
    }>;
    const jpm = data.find((d) => d.name === "JPM");
    expect(jpm?.custom?.contribution).toBe(-300);
    expect(jpm?.custom?.ret).toBe(-0.04);
  });

  it("does not mutate the input array", () => {
    const input = [...ITEMS];
    buildHcContributionBubbleOption(input, COLORS);
    expect(input).toEqual(ITEMS);
  });
});
