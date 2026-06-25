"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Chart, Point } from "highcharts";
import type { Grid } from "@highcharts/grid-pro";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { DataGrid } from "@/components/ui/DataGrid";
import { buildHcExposureSunburstOption, assetClassLabel } from "@/lib/charts/hc/sunburst";
import type { ChartColors } from "@/lib/charts/chartColors";
import type { ExposureItem, PortfolioLookthrough } from "@/lib/api/client";
import {
  exposureGridOptions,
  type ExposureGridRow,
} from "@/lib/grid/exposureGridOptions";
import { formatNumber } from "@/lib/format";

const ROOT_ID = "portfolio-root";

type ExposureNode = PortfolioLookthrough["tree"][number];

function nodeLabel(node: ExposureNode): string {
  if (node.kind === "asset_class") return assetClassLabel(node.key, node.label);
  if (node.key === "__OTHER__") return "Other holdings";
  return node.label || node.key;
}

function kindLabel(kind: string): string {
  return kind
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function nodePct(node: ExposureNode, assetItems: ExposureItem[]): number {
  if (node.kind !== "asset_class") return node.value_pct;
  const asset = assetItems.find(
    (item) => item.key.trim().toUpperCase() === node.key.trim().toUpperCase(),
  );
  return asset?.total_pct ?? node.value_pct;
}

function childrenOf(tree: ExposureNode[], parentId: string): ExposureNode[] {
  const parent = parentId === ROOT_ID ? null : parentId;
  return tree
    .filter((node) => node.parent_id === parent)
    .sort((a, b) => b.value_pct - a.value_pct);
}

function rowFromNode(node: ExposureNode, assetItems: ExposureItem[]): ExposureGridRow {
  return {
    id: node.id,
    label: nodeLabel(node),
    kind: kindLabel(node.kind),
    pct: nodePct(node, assetItems),
  };
}

function tableParentId(tree: ExposureNode[], activeId: string): string {
  const activeChildren = childrenOf(tree, activeId);
  if (activeChildren.length > 0) return activeId;
  const activeNode = tree.find((node) => node.id === activeId);
  return activeNode?.parent_id ?? ROOT_ID;
}

export function ExposureSunburstGrid({
  title,
  subtitle,
  rootName,
  tree,
  assetItems,
  colors,
  className,
}: {
  title: string;
  subtitle?: string;
  rootName: string;
  tree: ExposureNode[];
  assetItems: ExposureItem[];
  colors: ChartColors;
  className?: string;
}) {
  const chartRef = useRef<Chart | null>(null);
  const previousActiveRef = useRef<string | null>(null);
  const detachGridHoverRef = useRef<(() => void) | null>(null);
  const [activeId, setActiveId] = useState<string>(ROOT_ID);

  useEffect(() => {
    if (activeId === ROOT_ID) return;
    if (!tree.some((node) => node.id === activeId)) setActiveId(ROOT_ID);
  }, [activeId, tree]);

  const onPointFocus = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const options = useMemo(
    () =>
      buildHcExposureSunburstOption(tree, assetItems, colors, {
        activeId,
        rootName,
        valueLabel: "% NAV",
        onPointFocus,
      }),
    [activeId, assetItems, colors, onPointFocus, rootName, tree],
  );

  const activeParentId = tableParentId(tree, activeId);
  const tableRows = useMemo(
    () => childrenOf(tree, activeParentId).map((node) => rowFromNode(node, assetItems)),
    [activeParentId, assetItems, tree],
  );
  const gridOptions = useMemo(
    () => exposureGridOptions(tableRows, activeId),
    [activeId, tableRows],
  );
  const activeParentNode = tree.find((node) => node.id === activeParentId);
  const activeParentLabel =
    activeParentId === ROOT_ID || !activeParentNode
      ? rootName
      : nodeLabel(activeParentNode);
  const activeTotal = tableRows.reduce((sum, row) => sum + row.pct, 0);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (previousActiveRef.current && previousActiveRef.current !== activeId) {
      (chart.get(previousActiveRef.current) as Point | undefined)?.setState("");
    }
    if (activeId !== ROOT_ID) {
      (chart.get(activeId) as Point | undefined)?.setState("hover");
      previousActiveRef.current = activeId;
    } else {
      previousActiveRef.current = null;
    }
  }, [activeId]);

  const onGridReady = useCallback((grid: Grid) => {
    detachGridHoverRef.current?.();
    const body = grid.viewport?.tbodyElement;
    if (!body) return;
    const onMove = (event: MouseEvent) => {
      const target = event.target instanceof Element
        ? event.target.closest("[data-exposure-id]")
        : null;
      const id = target?.getAttribute("data-exposure-id");
      if (id) setActiveId(id);
    };
    const onLeave = () => setActiveId(activeParentId);
    body.addEventListener("mousemove", onMove);
    body.addEventListener("mouseleave", onLeave);
    detachGridHoverRef.current = () => {
      body.removeEventListener("mousemove", onMove);
      body.removeEventListener("mouseleave", onLeave);
    };
  }, [activeParentId]);

  useEffect(() => () => detachGridHoverRef.current?.(), []);

  if (tree.length === 0) return null;

  return (
    <section className={`border border-border bg-surface-2 ${className ?? ""}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-[var(--ix-pad)] py-3">
        <div>
          <h2 className="ix-label m-0">{title}</h2>
          {subtitle && (
            <p className="m-0 mt-0.5 text-[12px] text-text-secondary">{subtitle}</p>
          )}
        </div>
        <span className="text-[11px] tabular-nums text-text-muted">
          {formatNumber(activeTotal, 1)}% NAV
        </span>
      </div>

      <div className="grid gap-px bg-border lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.85fr)]">
        <div className="bg-surface-2 px-4 py-4">
          <HighchartsChart
            options={options}
            className="h-[520px] w-full md:h-[620px]"
            isEmpty={tree.length === 0}
            emptyMessage="No exposure hierarchy available."
            onReady={(chart) => {
              chartRef.current = chart;
            }}
          />
        </div>
        <div className="flex min-h-[420px] flex-col bg-surface-2">
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <span className="text-[11px] font-bold uppercase tracking-[0.07em] text-text-muted">
              {activeParentLabel}
            </span>
            {activeId !== ROOT_ID && (
              <button
                type="button"
                onClick={() => setActiveId(ROOT_ID)}
                className="h-[24px] border border-border-strong bg-field px-2 text-[11px] text-text-secondary hover:bg-layer-hover"
              >
                Reset
              </button>
            )}
          </div>
          <DataGrid
            options={gridOptions}
            className="min-h-0 flex-1"
            emptyMessage="No items."
            onReady={onGridReady}
          />
        </div>
      </div>
    </section>
  );
}
