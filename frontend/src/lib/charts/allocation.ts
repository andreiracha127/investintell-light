/**
 * Pure option builder: allocation donut.
 *
 * One slice per resolved position, colored from the categorical palette;
 * legend entries pair the ticker with its effective initial weight.
 */
import type { EChartsOption } from "echarts";

import type { AllocationPosition } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatPercent } from "@/lib/format";

export function buildAllocationOption(
  positions: AllocationPosition[],
  colors: ChartColors,
): EChartsOption {
  const weightByTicker = new Map(
    positions.map((position) => [position.ticker, position.weight]),
  );

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      valueFormatter: (value) =>
        typeof value === "number" ? formatPercent(value, 1) : String(value ?? ""),
    },
    legend: {
      orient: "vertical",
      right: 8,
      top: "middle",
      icon: "circle",
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: colors.textSecondary },
      formatter: (name: string) => {
        const weight = weightByTicker.get(name);
        return weight === undefined ? name : `${name}  ${formatPercent(weight, 1)}`;
      },
    },
    series: [
      {
        name: "Allocation",
        type: "pie",
        radius: ["55%", "82%"],
        center: ["35%", "50%"],
        data: positions.map((position, i) => ({
          name: position.ticker,
          value: position.weight,
          itemStyle: { color: colors.categories[i % colors.categories.length] },
        })),
        label: { show: false },
        labelLine: { show: false },
      },
    ],
  };
}
