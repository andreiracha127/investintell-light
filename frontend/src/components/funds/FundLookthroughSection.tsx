"use client";

/**
 * Consolidated exposure section for the fund profile page.
 *
 * Fetches look-through data for the fund and renders the shared Sunburst + Grid
 * exposure map. 404 → renders nothing (fund has no decomposition data). Any
 * other error follows the view's error panel pattern.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  ApiError,
  fetchFundLookthrough,
  type ExposureItem,
  type FundHoldingsTop,
  type FundLookthrough,
  type PortfolioLookthrough,
} from "@/lib/api/client";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { ExposureSunburstGrid } from "@/components/lookthrough/ExposureSunburstGrid";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { assetClassLabel } from "@/lib/charts/hc/sunburst";
import { formatDate } from "@/lib/format";

export function FundLookthroughSection({
  instrumentId,
  holdingsTop,
}: {
  instrumentId: string;
  holdingsTop?: FundHoldingsTop | null;
}) {
  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const query = useQuery({
    queryKey: ["fund-lookthrough", instrumentId],
    queryFn: ({ signal }) => fetchFundLookthrough(instrumentId, {}, signal),
    staleTime: 60_000,
    retry: (failureCount, err) => {
      // Never retry 404 (fund has no decomposition data) or other 4xx.
      if (err instanceof ApiError && err.status === 404) return false;
      return retryPolicy(failureCount, err);
    },
  });

  // 404 → fund has no decomposition data; render nothing silently.
  if (
    query.isError &&
    query.error instanceof ApiError &&
    query.error.status === 404
  ) {
    return null;
  }

  if (query.isPending) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading consolidated exposure"
        className="h-[120px] bg-surface-2 animate-pulse"
      />
    );
  }

  if (query.isError) {
    return (
      <ErrorPanel
        title="Failed to load consolidated exposure"
        message={query.error.message}
        onRetry={() => query.refetch()}
      />
    );
  }

  const data = query.data;
  const assetItems = data.dimensions.asset_class ?? [];
  const tree = buildFundExposureTree(data, holdingsTop);
  const gridAssetItems = assetItems.length > 0
    ? assetItems
    : tree
        .filter((node) => !node.parent_id)
        .map<ExposureItem>((node) => ({
          key: node.key,
          label: node.label,
          direct_pct: node.value_pct,
          indirect_pct: 0,
          total_pct: node.value_pct,
        }));

  return (
    <section>
      {colors && (
        <ExposureSunburstGrid
          title="Exposure map"
          subtitle={data.report_date ? `As of ${formatDate(data.report_date)}` : undefined}
          rootName="Fund"
          tree={tree}
          assetItems={gridAssetItems}
          colors={colors}
        />
      )}
    </section>
  );
}

type ExposureNode = PortfolioLookthrough["tree"][number];

function safeId(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "unknown";
}

function pct(value: number | null | undefined): number {
  return Number.isFinite(value) ? Number(value) : 0;
}

function upsertNode(
  nodes: ExposureNode[],
  byId: Map<string, ExposureNode>,
  node: ExposureNode,
): ExposureNode {
  const existing = byId.get(node.id);
  if (existing) {
    existing.value_pct += node.value_pct;
    return existing;
  }
  nodes.push(node);
  byId.set(node.id, node);
  return node;
}

function buildFundExposureTree(
  data: FundLookthrough,
  holdingsTop?: FundHoldingsTop | null,
): ExposureNode[] {
  const holdings = holdingsTop?.top_holdings.filter((holding) => pct(holding.pct_of_nav) > 0) ?? [];
  if (holdings.length === 0) {
    return (data.dimensions.asset_class ?? []).map((item) => ({
      id: `asset|${safeId(item.key)}`,
      parent_id: null,
      key: item.key,
      label: assetClassLabel(item.key, item.label),
      kind: "asset_class",
      value_pct: item.total_pct,
    }));
  }

  const nodes: ExposureNode[] = [];
  const byId = new Map<string, ExposureNode>();
  for (const holding of holdings) {
    const assetKey = holding.asset_class ?? "UNKNOWN";
    const assetId = `asset|${safeId(assetKey)}`;
    const assetLabel = assetClassLabel(assetKey, holding.asset_class);
    const sectorLabel =
      holding.sector_label ??
      holding.gics_sector ??
      holding.sector ??
      "Unclassified";
    const sectorId = `${assetId}|sector|${safeId(sectorLabel)}`;
    const holdingKey = holding.cusip ?? holding.isin ?? `${holding.rank}`;
    const holdingId = `${sectorId}|holding|${safeId(holdingKey)}`;
    const weight = pct(holding.pct_of_nav);

    const assetNode = upsertNode(nodes, byId, {
      id: assetId,
      parent_id: null,
      key: assetKey,
      label: assetLabel,
      kind: "asset_class",
      value_pct: 0,
    });
    const sectorNode = upsertNode(nodes, byId, {
      id: sectorId,
      parent_id: assetId,
      key: sectorLabel,
      label: sectorLabel,
      kind: "sector",
      value_pct: 0,
    });
    assetNode.value_pct += weight;
    sectorNode.value_pct += weight;
    upsertNode(nodes, byId, {
      id: holdingId,
      parent_id: sectorId,
      key: holdingKey,
      label: holding.issuer_name ?? holdingKey,
      kind: "holding",
      value_pct: weight,
    });
  }

  return nodes;
}
