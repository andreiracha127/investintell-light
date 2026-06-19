import { describe, expect, it } from "vitest";

import type { MarketBreadth, SectorPerf } from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import {
  buildHcMarketBreadthOption,
  buildHcSectorPerformanceOption,
  buildHcVolumeBreadthOption,
} from "@/lib/charts/hc/stock-overview";

const SECTORS: SectorPerf[] = [
  { sector: "Technology", change_pct_median: 0.024, n: 180 },
  { sector: "Energy", change_pct_median: -0.012, n: 42 },
];

const BREADTH: MarketBreadth = {
  tracked: 100,
  advancing: 62,
  declining: 31,
  unchanged: 7,
  advance_decline_ratio: 2,
  new_highs_52w: 8,
  new_lows_52w: 3,
  up_volume_share: 0.64,
};

function seriesAt(option: ReturnType<typeof buildHcMarketBreadthOption>, index: number) {
  return option.series![index] as {
    data: Array<{ custom?: { detail?: string }; y: number }>;
    name: string;
    type: string;
  };
}

describe("buildHcSectorPerformanceOption", () => {
  it("returns a Highcharts bar chart with one zero plot line", () => {
    const option = buildHcSectorPerformanceOption(SECTORS, TEST_COLORS);
    const yAxis = option?.yAxis as {
      labels?: { enabled?: boolean };
      plotBands?: Array<{ from: number; to: number }>;
      plotLines?: Array<{ value: number }>;
    };

    expect(option?.chart).toMatchObject({ type: "bar" });
    expect(yAxis.plotBands).toHaveLength(2);
    expect(yAxis.plotLines).toHaveLength(1);
    expect(yAxis.plotLines?.[0].value).toBe(0);
    expect(yAxis.labels?.enabled).toBe(false);
  });

  it("uses the sector labels and signed median changes as the series data", () => {
    const option = buildHcSectorPerformanceOption(SECTORS, TEST_COLORS);
    const xAxis = option?.xAxis as { categories?: string[] };
    const series = option?.series?.[0] as { data: Array<{ y: number }> };

    expect(xAxis.categories).toEqual(["Technology", "Energy"]);
    expect(series.data.map((point) => point.y)).toEqual([0.024, -0.012]);
  });

  it("returns null for empty sector data", () => {
    expect(buildHcSectorPerformanceOption([], TEST_COLORS)).toBeNull();
  });
});

describe("buildHcMarketBreadthOption", () => {
  it("returns a thin stacked force bar chart for price breadth", () => {
    const option = buildHcMarketBreadthOption(BREADTH, TEST_COLORS);
    const xAxis = option.xAxis as { categories?: string[]; labels?: { enabled?: boolean } };
    const plotOptions = option.plotOptions as { bar?: { stacking?: string } };

    expect(option.chart).toMatchObject({ height: 70, type: "bar" });
    expect(option.chart).not.toHaveProperty("polar");
    expect(xAxis.categories).toEqual([""]);
    expect(xAxis.labels?.enabled).toBe(false);
    expect(plotOptions.bar?.stacking).toBe("normal");
  });

  it("maps price breadth into declining and advancing force segments", () => {
    const option = buildHcMarketBreadthOption(BREADTH, TEST_COLORS);
    const ys = [0, 1].map((idx) => seriesAt(option, idx).data[0].y);

    expect(ys).toEqual([-0.31, 0.62]);
    expect(seriesAt(option, 0).data[0].custom?.detail).toContain("declining stocks");
    expect(seriesAt(option, 1).data[0].custom?.detail).toContain("advancing stocks");
  });

  it("names price force segments for Highcharts tooltip use", () => {
    const option = buildHcMarketBreadthOption(BREADTH, TEST_COLORS);

    expect(seriesAt(option, 0).type).toBe("bar");
    expect(seriesAt(option, 0).name).toBe("Declining");
    expect(seriesAt(option, 1).name).toBe("Advancing");
  });
});

describe("buildHcVolumeBreadthOption", () => {
  it("maps volume breadth into down-volume and up-volume force segments", () => {
    const option = buildHcVolumeBreadthOption(BREADTH, TEST_COLORS);
    const ys = [0, 1].map((idx) => seriesAt(option, idx).data[0].y);

    expect(ys).toEqual([-0.36, 0.64]);
    expect(seriesAt(option, 0).name).toBe("Down-volume");
    expect(seriesAt(option, 1).name).toBe("Up-volume");
    expect(seriesAt(option, 1).data[0].custom?.detail).toContain("advancing stocks");
  });
});
