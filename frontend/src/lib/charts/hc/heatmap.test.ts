import { describe, expect, it } from "vitest";

import { buildHcHeatmapOption } from "@/lib/charts/hc/heatmap";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { CorrelationMatrix } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";

const CORR: CorrelationMatrix = {
  tickers: ["AAA", "BBB", "CCC"],
  matrix: [
    [1, 0.6, 0.1],
    [0.6, 1, 0.4],
    [0.1, 0.4, 1],
  ],
};

type HeatmapCell = { x: number; y: number; value: number };

function cells(opt: ReturnType<typeof buildHcHeatmapOption>): HeatmapCell[] {
  const series = opt.series?.[0] as { data?: HeatmapCell[] };
  return series.data ?? [];
}

describe("buildHcHeatmapOption", () => {
  it("emits a single heatmap series", () => {
    const opt = buildHcHeatmapOption(CORR, TEST_COLORS);
    const series = opt.series?.[0] as { type?: string; name?: string };
    expect(series.type).toBe("heatmap");
    expect(series.name).toBe("Correlation");
  });

  it("maps matrix[y][x] to {x, y, value} cells in row-major order", () => {
    const opt = buildHcHeatmapOption(CORR, TEST_COLORS);
    const data = cells(opt);
    // 3x3 matrix -> 9 cells.
    expect(data).toHaveLength(9);
    // First row (y=0): [1, 0.6, 0.1].
    expect(data[0]).toMatchObject({ x: 0, y: 0, value: 1 });
    expect(data[1]).toMatchObject({ x: 1, y: 0, value: 0.6 });
    expect(data[2]).toMatchObject({ x: 2, y: 0, value: 0.1 });
    // Second row (y=1) carries matrix[1].
    expect(data[3]).toMatchObject({ x: 0, y: 1, value: 0.6 });
    expect(data[5]).toMatchObject({ x: 2, y: 1, value: 0.4 });
    // Last cell is matrix[2][2].
    expect(data[8]).toMatchObject({ x: 2, y: 2, value: 1 });
  });

  it("flips the per-cell dataLabel color above the 0.55 threshold", () => {
    const opt = buildHcHeatmapOption(CORR, TEST_COLORS);
    const data = cells(opt);
    // value 1 (> 0.55) -> on-accent text.
    expect((data[0] as { dataLabels?: { color?: string } }).dataLabels?.color).toBe(
      TEST_COLORS.textOnAccent,
    );
    // value 0.6 (> 0.55) -> on-accent text.
    expect((data[1] as { dataLabels?: { color?: string } }).dataLabels?.color).toBe(
      TEST_COLORS.textOnAccent,
    );
    // value 0.1 (<= 0.55) -> primary text.
    expect((data[2] as { dataLabels?: { color?: string } }).dataLabels?.color).toBe(
      TEST_COLORS.text,
    );
    // value 0.4 (<= 0.55) -> primary text.
    expect((data[5] as { dataLabels?: { color?: string } }).dataLabels?.color).toBe(
      TEST_COLORS.text,
    );
  });

  it("treats exactly 0.55 as below the light-label threshold", () => {
    const corr: CorrelationMatrix = { tickers: ["X"], matrix: [[0.55]] };
    const opt = buildHcHeatmapOption(corr, TEST_COLORS);
    const data = cells(opt);
    expect((data[0] as { dataLabels?: { color?: string } }).dataLabels?.color).toBe(
      TEST_COLORS.text,
    );
  });

  it("sets x/y axis categories to the tickers, y reversed", () => {
    const opt = buildHcHeatmapOption(CORR, TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    const yAxis = opt.yAxis as { categories?: string[]; reversed?: boolean };
    expect(xAxis.categories).toEqual(["AAA", "BBB", "CCC"]);
    expect(yAxis.categories).toEqual(["AAA", "BBB", "CCC"]);
    expect(yAxis.reversed).toBe(true);
  });

  it("configures a hidden continuous colorAxis 0..1 with accentWash -> accent stops", () => {
    const opt = buildHcHeatmapOption(CORR, TEST_COLORS);
    const colorAxis = opt.colorAxis as {
      min?: number;
      max?: number;
      stops?: [number, string][];
      visible?: boolean;
    };
    expect(colorAxis.min).toBe(0);
    expect(colorAxis.max).toBe(1);
    expect(colorAxis.visible).toBe(false);
    expect(colorAxis.stops).toEqual([
      [0, TEST_COLORS.accentWash],
      [1, TEST_COLORS.accent],
    ]);
  });

  it("formats cell dataLabels with formatNumber — this is the Point (real HC context)", () => {
    const opt = buildHcHeatmapOption(CORR, TEST_COLORS);
    const series = opt.series?.[0] as {
      dataLabels?: {
        enabled?: boolean;
        style?: { fontSize?: string };
        formatter?: (this: { x: number; y: number; value: number }) => string;
      };
    };
    expect(series.dataLabels?.enabled).toBe(true);
    // fontSize is set via style (HC CSSObject), matching legacy fontSize:10 parity.
    expect(series.dataLabels?.style?.fontSize).toBe("10px");
    // In real HC, `this` on a dataLabels formatter IS the Point itself.
    const out = series.dataLabels!.formatter!.call({ x: 1, y: 0, value: 0.6 });
    expect(out).toBe(formatNumber(0.6));
  });

  it("formats the tooltip as 'rowTicker × colTicker: value' — this is the Point (real HC context)", () => {
    const opt = buildHcHeatmapOption(CORR, TEST_COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: { x: number; y: number; value: number }) => string;
    };
    // In real HC, `this` on a tooltip formatter IS the hovered Point.
    // x = column index (BBB = 1), y = row index (AAA = 0), value = cell value.
    const out = tooltip.formatter!.call({ x: 1, y: 0, value: 0.6 });
    expect(out).toBe(`AAA × BBB: ${formatNumber(0.6)}`);
  });

  it("configures hover state with borderWidth:2 for visual emphasis parity", () => {
    const opt = buildHcHeatmapOption(CORR, TEST_COLORS);
    const series = opt.series?.[0] as {
      states?: { hover?: { borderWidth?: number; borderColor?: string } };
    };
    expect(series.states?.hover?.borderWidth).toBe(2);
    expect(series.states?.hover?.borderColor).toBe(TEST_COLORS.grid);
  });

  it("renders an empty series for an empty matrix", () => {
    const empty: CorrelationMatrix = { tickers: [], matrix: [] };
    const opt = buildHcHeatmapOption(empty, TEST_COLORS);
    expect(cells(opt)).toEqual([]);
  });
});
