/**
 * Pure option builder: allocation donut (Cockpit style) for Highcharts Core.
 *
 * One pie slice per entry, colored from the categorical palette (cycled).
 * No labels inside the chart — the legend is plain HTML beside the donut, so
 * the builder sets only the series and color assignments. Global chrome
 * (tooltip background, legend styling, grid, animation) is owned by the
 * Graphite theme applied via `Highcharts.setOptions(...)`.
 *
 * Input types live in the neutral chart types module for shared consumers.
 */
import type { Options, Point } from "highcharts";

import type { AllocationSlice } from "@/lib/charts/types";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber } from "@/lib/format";

export function buildHcAllocationOption(
  slices: AllocationSlice[],
  colors: ChartColors,
): Options {
  return {
    chart: { type: "pie" },
    legend: { enabled: false },
    tooltip: {
      pointFormatter(this: Point) {
        return `${this.key}  ${formatNumber(this.percentage ?? 0, 1)}%`;
      },
    },
    series: [
      {
        type: "pie",
        name: "Allocation",
        innerSize: "65%",
        borderWidth: 1,
        borderColor: colors.surface,
        dataLabels: { enabled: false },
        data: slices.map((slice, i) => ({
          name: slice.name,
          y: slice.value,
          color: colors.categories[i % colors.categories.length],
        })),
      },
    ],
  };
}
