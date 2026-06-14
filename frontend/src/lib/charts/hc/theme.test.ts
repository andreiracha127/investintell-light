import { describe, expect, it } from "vitest";

import { highchartsTheme } from "@/lib/charts/hc/theme";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";

describe("highchartsTheme", () => {
  it("uses the categorical palette as the series colors", () => {
    expect(highchartsTheme(TEST_COLORS).colors).toEqual(TEST_COLORS.categories);
  });

  it("renders a transparent, square, shadowless chart and tooltip", () => {
    const t = highchartsTheme(TEST_COLORS);
    expect(t.chart?.backgroundColor).toBe("transparent");
    expect(t.chart?.borderRadius).toBe(0);
    expect(t.tooltip?.shadow).toBe(false);
    expect(t.tooltip?.backgroundColor).toBe(TEST_COLORS.surface);
  });

  it("binds axis gridlines and labels to graphite tokens", () => {
    const t = highchartsTheme(TEST_COLORS);
    expect((t.xAxis as { gridLineColor?: string }).gridLineColor).toBe(TEST_COLORS.grid);
    expect((t.yAxis as { labels?: { style?: { color?: string } } }).labels?.style?.color).toBe(TEST_COLORS.textMuted);
  });

  it("maps candlestick up/down to gain/loss", () => {
    const t = highchartsTheme(TEST_COLORS);
    expect(t.plotOptions?.candlestick?.upColor).toBe(TEST_COLORS.gain);
    expect(t.plotOptions?.candlestick?.color).toBe(TEST_COLORS.loss);
  });

  it("disables credits", () => {
    expect(highchartsTheme(TEST_COLORS).credits?.enabled).toBe(false);
  });

  it("suppresses the default chart title", () => {
    const t = highchartsTheme(TEST_COLORS);
    expect(t.title).toBeDefined();
    expect(t.title?.text).toBeUndefined();
    expect(t.title?.style?.color).toBe(TEST_COLORS.text);
  });
});
