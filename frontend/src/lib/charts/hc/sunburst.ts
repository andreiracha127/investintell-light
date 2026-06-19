/**
 * Pure option builder: portfolio exposure sunburst.
 *
 * The API supplies a parent-linked tree: asset class -> series ID -> CUSIP.
 * Parent rings carry labels and color; leaf rings carry values.
 */
import type { Options, PointOptionsObject } from "highcharts";

import type { ExposureItem, PortfolioLookthrough } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber } from "@/lib/format";

const ASSET_CLASS_LABELS: Record<string, string> = {
  ABS: "Asset-backed securities",
  "ABS-MBS": "ABS / MBS",
  "ABS-O": "Asset-backed securities",
  C: "Cash and equivalents",
  CE: "Cash and equivalents",
  CMBS: "Commercial MBS",
  CORP: "Corporate bonds",
  DBT: "Debt",
  EC: "Equity",
  EP: "Preferred equity",
  MBS: "Mortgage-backed securities",
  RA: "Real assets",
  RE: "Real estate",
  STIV: "Short-term investments",
  UST: "U.S. Treasuries",
  UNKNOWN: "Unclassified",
};

const round4 = (value: number) => parseFloat(value.toFixed(4));

export function assetClassLabel(key: string, fallback?: string | null): string {
  const normalized = key.trim().toUpperCase();
  return ASSET_CLASS_LABELS[normalized] ?? fallback ?? key;
}

function nodeLabel(node: PortfolioLookthrough["tree"][number]): string {
  if (node.kind === "asset_class") return assetClassLabel(node.key, node.label);
  if (node.key === "__OTHER__") return "Other holdings";
  return node.label || node.key;
}

function leafIds(tree: PortfolioLookthrough["tree"]): Set<string> {
  const parentIds = new Set(
    tree
      .map((node) => node.parent_id)
      .filter((id): id is string => Boolean(id)),
  );
  return new Set(tree.filter((node) => !parentIds.has(node.id)).map((node) => node.id));
}

function topAssetId(
  node: PortfolioLookthrough["tree"][number],
  byId: Map<string, PortfolioLookthrough["tree"][number]>,
): string {
  let current = node;
  while (current.parent_id) {
    const parent = byId.get(current.parent_id);
    if (!parent) break;
    current = parent;
  }
  return current.id;
}

export function buildHcExposureSunburstOption(
  tree: PortfolioLookthrough["tree"],
  assetItems: ExposureItem[],
  colors: ChartColors,
): Options {
  const byId = new Map(tree.map((node) => [node.id, node]));
  const leaves = leafIds(tree);
  const assetNodes = tree.filter((node) => !node.parent_id);
  const colorByAsset = new Map(
    assetNodes.map((node, index) => [
      node.id,
      colors.categories[index % colors.categories.length],
    ]),
  );
  const assetTotals = new Map(
    assetItems.map((item) => [
      item.key.trim().toUpperCase(),
      { total: item.total_pct, label: assetClassLabel(item.key, item.label) },
    ]),
  );

  const data: PointOptionsObject[] = [
    {
      id: "portfolio-root",
      parent: "",
      name: "Portfolio",
      color: colors.surface,
      custom: {
        valuePct: assetItems.reduce((sum, item) => sum + item.total_pct, 0),
      },
    },
    ...tree.map((node) => {
      const topId = topAssetId(node, byId);
      const assetTotal = node.kind === "asset_class"
        ? assetTotals.get(node.key.trim().toUpperCase())
        : undefined;
      return {
        id: node.id,
        parent: node.parent_id ?? "portfolio-root",
        name: assetTotal?.label ?? nodeLabel(node),
        value: leaves.has(node.id) ? round4(node.value_pct) : undefined,
        color: colorByAsset.get(topId),
        custom: {
          rawKey: node.key,
          kind: node.kind,
          valuePct: assetTotal?.total ?? node.value_pct,
        },
      };
    }),
  ];

  return {
    chart: {
      type: "sunburst",
      backgroundColor: "transparent",
      spacing: [24, 18, 18, 18],
    },
    legend: { enabled: false },
    tooltip: {
      useHTML: true,
      formatter() {
        const point = (
          this as unknown as {
            point: {
              name: string;
              options: {
                custom?: { rawKey?: string; valuePct?: number; kind?: string };
              };
            };
          }
        ).point;
        const value = point.options.custom?.valuePct ?? 0;
        return `<div style="font-size:12px"><b>${point.name}</b><br/>${formatNumber(
          value,
          2,
        )}% of portfolio</div>`;
      },
    },
    plotOptions: {
      sunburst: {
        borderColor: colors.surface,
        borderWidth: 1,
        cursor: "pointer",
      },
    },
    series: [
      {
        type: "sunburst",
        name: "Exposure",
        allowDrillToNode: true,
        levelIsConstant: false,
        size: "92%",
        data,
        levels: [
          {
            level: 1,
            dataLabels: { enabled: false },
          },
          {
            level: 2,
            colorByPoint: true,
            dataLabels: {
              enabled: true,
              rotationMode: "parallel",
              style: {
                color: colors.textOnAccent,
                fontSize: "11px",
                fontWeight: "bold",
                textOutline: "none",
              },
            },
          },
          {
            level: 3,
            dataLabels: {
              enabled: true,
              rotationMode: "circular",
              style: {
                color: colors.textOnAccent,
                fontSize: "10px",
                textOutline: "none",
              },
            },
          },
          {
            level: 4,
            dataLabels: {
              enabled: false,
            },
          },
        ],
      },
    ],
  };
}
