import { describe, expect, it } from "vitest";
import type { SeriesPackedbubbleOptions } from "highcharts";

import {
  buildHcContributionBubbleOption,
  buildHcRiskBubbleOption,
  type BubbleItem,
} from "@/lib/charts/hc/bubble";
import type { ChartColors } from "@/lib/charts/chartColors";
import type { RiskContribution } from "@/lib/api/client";
import { formatPercent } from "@/lib/format";

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

const RISK: RiskContribution[] = [
  { ticker: "NVDA", contribution: 0.34 },
  { ticker: "MSFT", contribution: 0.22 },
  { ticker: "AGG", contribution: -0.04 },
  { ticker: "CASHX", contribution: 0 },
] as RiskContribution[];

describe("buildHcRiskBubbleOption", () => {
  it("renders a packedbubble series", () => {
    const opt = buildHcRiskBubbleOption(RISK, COLORS);
    expect(opt.chart?.type).toBe("packedbubble");
    const series = opt.series?.[0] as SeriesPackedbubbleOptions;
    expect(series.type).toBe("packedbubble");
    expect(series.name).toBe("Risk share");
  });

  it("sizes bubbles by |contribution| and drops zero/empty holdings, sorted desc", () => {
    const opt = buildHcRiskBubbleOption(RISK, COLORS);
    const series = opt.series?.[0] as SeriesPackedbubbleOptions;
    const data = series.data as Array<{ name: string; value: number }>;
    expect(data.map((d) => d.name)).toEqual(["NVDA", "MSFT", "AGG"]);
    expect(data.map((d) => d.value)).toEqual([0.34, 0.22, 0.04]);
  });

  it("colors positive contributions with the accent and negatives with loss", () => {
    const opt = buildHcRiskBubbleOption(RISK, COLORS);
    const series = opt.series?.[0] as SeriesPackedbubbleOptions;
    const data = series.data as Array<{ name: string; color: string }>;
    const byName = Object.fromEntries(data.map((d) => [d.name, d.color]));
    expect(byName.NVDA).toBe(COLORS.accent);
    expect(byName.AGG).toBe(COLORS.loss);
  });

  it("carries the signed contribution and computed share on point.custom", () => {
    const opt = buildHcRiskBubbleOption(RISK, COLORS);
    const series = opt.series?.[0] as SeriesPackedbubbleOptions;
    const data = series.data as Array<{
      name: string;
      custom?: { contribution: number; share: number };
    }>;
    const nvda = data.find((d) => d.name === "NVDA");
    const totalAbs = 0.34 + 0.22 + 0.04;
    expect(nvda?.custom?.contribution).toBe(0.34);
    expect(nvda?.custom?.share).toBeCloseTo(0.34 / totalAbs, 10);
  });

  it("formats the tooltip as a percent of total risk", () => {
    const opt = buildHcRiskBubbleOption(RISK, COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: unknown) => string;
    };
    const out = tooltip.formatter!.call({
      point: { name: "NVDA", options: { custom: { contribution: 0.34 } } },
    });
    expect(out).toContain(formatPercent(0.34, 1));
    expect(out).toContain("of total risk");
  });

  it("does not mutate the input array", () => {
    const input = [...RISK];
    buildHcRiskBubbleOption(input, COLORS);
    expect(input).toEqual(RISK);
  });
});
