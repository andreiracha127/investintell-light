/**
 * Pure option builder: allocation donut (Cockpit style) for Highcharts Core.
 *
 * One pie slice per entry, colored from the categorical palette (cycled).
 * Global chrome (tooltip background, legend styling, grid, animation) is owned by
 * the Graphite theme applied via `Highcharts.setOptions(...)`.
 *
 * Config:
 *  - `innerSize` — donut hole (default "62%", matching the mockup).
 *  - `dataLabels` — leader labels "name x%" inside the chart (Builder donuts,
 *    which have no external legend). Default off (Portfolio renders an HTML legend).
 *  - `valueFormatter` — when set, the tooltip adds a formatted value line above
 *    the "% of portfolio" line (e.g. the currency value for the Portfolio donut).
 *
 * Input types live in the neutral chart types module for shared consumers.
 */
import type { Options, Point } from "highcharts";

import type { AllocationSlice } from "@/lib/charts/types";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber } from "@/lib/format";

export interface AllocationConfig {
  innerSize?: string;
  dataLabels?: boolean;
  valueFormatter?: (value: number) => string;
}

export function buildHcAllocationOption(
  slices: AllocationSlice[],
  colors: ChartColors,
  config: AllocationConfig = {},
): Options {
  const innerSize = config.innerSize ?? "62%";
  const valueFormatter = config.valueFormatter;
  return {
    chart: { type: "pie" },
    legend: { enabled: false },
    tooltip: {
      useHTML: true,
      pointFormatter(this: Point) {
        const name = String(this.key ?? this.name ?? "");
        const pct = formatNumber(this.percentage ?? 0, 1);
        const valueLine = valueFormatter
          ? `<div style="font-variant-numeric:tabular-nums;">${valueFormatter(this.y ?? 0)}</div>`
          : "";
        return `<b>${name}</b>${valueLine}<div style="color:${colors.textMuted};">${pct}% of portfolio</div>`;
      },
    },
    series: [
      {
        type: "pie",
        name: "Allocation",
        innerSize,
        borderWidth: 1,
        borderColor: colors.surface,
        dataLabels: config.dataLabels
          ? {
              enabled: true,
              distance: 12,
              connectorWidth: 1,
              connectorColor: colors.grid,
              style: { fontWeight: "400", textOutline: "none", color: colors.text },
              formatter(this: Point) {
                return `${String(this.key ?? this.name ?? "")} ${Math.round(this.percentage ?? 0)}%`;
              },
            }
          : { enabled: false },
        states: { hover: { halo: { size: 4 }, brightness: 0.06 } },
        data: slices.map((slice, i) => ({
          name: slice.name,
          y: slice.value,
          color: colors.categories[i % colors.categories.length],
        })),
      },
    ],
  };
}
