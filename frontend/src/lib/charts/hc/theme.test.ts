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
    // Flat Carbon language: square tooltip, bars/columns/series.
    expect(t.tooltip?.borderRadius).toBe(0);
    expect(t.plotOptions?.column?.borderRadius).toBe(0);
    expect(t.plotOptions?.bar?.borderRadius).toBe(0);
    expect(
      (t.plotOptions?.series as { borderRadius?: number } | undefined)?.borderRadius,
    ).toBe(0);
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

  it("themes the Stock rangeSelector, navigator and scrollbar with graphite tokens", () => {
    const t = highchartsTheme(TEST_COLORS);
    expect(t.rangeSelector?.buttonTheme?.states?.select?.fill).toBe(TEST_COLORS.accent);
    expect(
      (t.rangeSelector?.labelStyle as { color?: string } | undefined)?.color,
    ).toBe(TEST_COLORS.textMuted);
    expect(t.navigator?.outlineColor).toBe(TEST_COLORS.grid);
    expect(t.navigator?.maskFill).toContain(TEST_COLORS.accent);
    expect(t.scrollbar?.barBackgroundColor).toBe(TEST_COLORS.barMute);
  });
});
