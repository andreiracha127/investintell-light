/**
 * Pure option builder: allocation donut (Cockpit style).
 *
 * One slice per entry, colored from the categorical palette (accent first,
 * then the graphite ramp). No labels inside the chart — the legend is plain
 * HTML beside the donut (square swatches), so the option carries series only.
 * Slice values are relative magnitudes (weights or market values); the donut
 * shows proportions either way.
 */
import type { EChartsOption } from "echarts";

import type { ChartColors } from "@/lib/charts/theme";
import { formatNumber } from "@/lib/format";

export interface AllocationSlice {
  name: string;
  value: number;
}

export function buildAllocationOption(
  slices: AllocationSlice[],
  colors: ChartColors,
): EChartsOption {
  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      // ECharts computes the slice percent; the frontend only formats it.
      formatter: (params) => {
        const p = params as { name?: string; percent?: number };
        return `${p.name ?? ""}  ${formatNumber(p.percent ?? 0, 1)}%`;
      },
    },
    series: [
      {
        name: "Allocation",
        type: "pie",
        radius: ["55%", "85%"],
        center: ["50%", "50%"],
        data: slices.map((slice, i) => ({
          name: slice.name,
          value: slice.value,
          itemStyle: {
            color: colors.categories[i % colors.categories.length],
            borderWidth: 1,
            borderColor: colors.surface,
          },
        })),
        label: { show: false },
        labelLine: { show: false },
      },
    ],
  };
}
