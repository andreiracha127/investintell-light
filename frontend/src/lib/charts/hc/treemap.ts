/**
 * Pure option builder: consolidated look-through treemap (Highcharts `treemap`,
 * registered in the Core wrapper).
 *
 * One parent tile per exposure bucket (asset class / sector / currency /
 * issuer), sized by its total portfolio weight and colored from the categorical
 * palette (Cash → muted grey). Each bucket splits into up to two leaf tiles —
 * "Direct" and "Via funds" — sized by the direct/indirect split the backend
 * look-through provides, brightened from the parent color. Tile area therefore
 * equals portfolio weight, matching the bars it replaces.
 *
 * NOTE: the backend look-through aggregates by bucket (ExposureItem with
 * direct/indirect/total), so leaves are the direct-vs-fund split, not the
 * individual underlying holdings. Per-holding drill-down would need a
 * holding×bucket matrix the API does not expose.
 *
 * Chrome (tooltip styling) is owned by the global Graphite theme; the builder
 * sets only the series, token colors, and percent formatting.
 */
import type { Options, PointOptionsObject } from "highcharts";

import type { ExposureItem } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber } from "@/lib/format";

const isCash = (label: string) => label.trim().toLowerCase() === "cash";
const round2 = (v: number) => parseFloat(v.toFixed(4));

/**
 * Build a look-through treemap for one exposure dimension.
 *
 * @param items  Exposure items for the active dimension (percent-point values).
 * @param colors Design-token color bag (from chartColors()).
 */
export function buildHcExposureTreemapOption(
  items: ExposureItem[],
  colors: ChartColors,
): Options {
  const sorted = [...items]
    .filter((item) => item.total_pct > 0)
    .sort((a, b) => b.total_pct - a.total_pct);

  const data: PointOptionsObject[] = [];
  sorted.forEach((item, i) => {
    const label = item.label ?? item.key;
    const parentId = `bucket-${i}`;
    const color = isCash(label)
      ? colors.barMute
      : colors.categories[i % colors.categories.length];
    data.push({ id: parentId, name: label, color });

    const direct = round2(item.direct_pct);
    const indirect = round2(item.indirect_pct);
    if (direct > 0) {
      data.push({ name: "Direct", parent: parentId, value: direct, custom: { bucket: label } });
    }
    if (indirect > 0) {
      data.push({ name: "Via funds", parent: parentId, value: indirect, custom: { bucket: label } });
    }
    // Bucket with a positive total but no direct/indirect split: one full leaf.
    if (direct <= 0 && indirect <= 0) {
      data.push({
        name: label,
        parent: parentId,
        value: round2(item.total_pct),
        custom: { bucket: label },
      });
    }
  });

  return {
    chart: { type: "treemap" },
    legend: { enabled: false },
    tooltip: {
      useHTML: true,
      formatter() {
        const point = (
          this as unknown as {
            point: {
              name: string;
              value?: number;
              options: { custom?: { bucket?: string } };
            };
          }
        ).point;
        const bucket = point.options.custom?.bucket;
        const value = point.value ?? 0;
        if (bucket && bucket !== point.name) {
          return `<div style="font-size:12px"><b>${bucket}</b> · ${point.name}<br/>${formatNumber(
            value,
            2,
          )}% of portfolio</div>`;
        }
        return `<div style="font-size:12px"><b>${point.name}</b><br/>${formatNumber(
          value,
          2,
        )}% of portfolio</div>`;
      },
    },
    series: [
      {
        type: "treemap",
        name: "Exposure",
        layoutAlgorithm: "squarified",
        allowTraversingTree: false,
        animationLimit: 1000,
        levels: [
          {
            level: 1,
            borderWidth: 3,
            borderColor: colors.surface,
            layoutAlgorithm: "squarified",
            dataLabels: {
              enabled: true,
              align: "left",
              verticalAlign: "top",
              style: {
                color: colors.textOnAccent,
                fontWeight: "bold",
                fontSize: "11px",
                textOutline: "none",
              },
            },
          },
          {
            level: 2,
            borderWidth: 1,
            borderColor: colors.surface,
            colorVariation: { key: "brightness", to: 0.45 },
            dataLabels: {
              enabled: true,
              style: {
                color: colors.text,
                fontWeight: "normal",
                fontSize: "10px",
                textOutline: "none",
              },
            },
          },
        ],
        data,
      },
    ],
  };
}
