import type { Options } from "@highcharts/grid-pro";

import { formatNumber } from "@/lib/format";
import { GRAPHITE_THEME } from "./gridOptions";

export interface ExposureGridRow {
  id: string;
  label: string;
  kind: string;
  pct: number;
}

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function rowId(cell: GridCell): string {
  return String(cell.row.getCell("id")?.value ?? "");
}

function activeClass(cell: GridCell, activeId: string | null | undefined): string {
  return activeId && rowId(cell) === activeId ? " ix-grid-active" : "";
}

function labelFormatter(activeId: string | null | undefined): CellFormatter {
  return function (this: GridCell): string {
    const id = escapeHtml(rowId(this));
    const label = escapeHtml(this.value ?? "—");
    const kind = escapeHtml(this.row.getCell("kind")?.value ?? "");
    return `<span class="ix-grid-exposure${activeClass(this, activeId)}" data-exposure-id="${id}">
      <span class="ix-grid-trunc">${label}</span>
      <span class="ix-grid-name">${kind}</span>
    </span>`;
  };
}

function pctFormatter(activeId: string | null | undefined): CellFormatter {
  return function (this: GridCell): string {
    const value = Number(this.value ?? 0);
    return `<span class="ix-grid-exposure-value${activeClass(this, activeId)}" data-exposure-id="${escapeHtml(rowId(this))}">
      ${escapeHtml(formatNumber(value, 2))}%
    </span>`;
  };
}

export function exposureGridOptions(
  rows: ExposureGridRow[],
  activeId: string | null | undefined,
): Options {
  const data: LocalGridData = {
    providerType: "local",
    columns: {
      id: rows.map((row) => row.id),
      label: rows.map((row) => row.label),
      kind: rows.map((row) => row.kind),
      pct: rows.map((row) => row.pct),
    },
  };
  const columns: GridColumns = [
    {
      id: "label",
      header: { format: "Item" },
      className: "ix-grid-cell-text",
      cells: { formatter: labelFormatter(activeId) },
    },
    {
      id: "pct",
      header: { format: "% NAV" },
      width: 92,
      className: "ix-grid-cell-num",
      cells: { formatter: pctFormatter(activeId) },
    },
    { id: "id", enabled: false },
    { id: "kind", enabled: false },
  ];

  return {
    rendering: {
      theme: GRAPHITE_THEME,
      rows: { strictHeights: false, virtualization: true, virtualizationThreshold: 60 },
    },
    // Sorting only reorders the currently-displayed sibling rows (children of
    // the active drill node); each row still carries its own `data-exposure-id`
    // via the cell formatters below, so the sunburst hover/drill sync (which
    // reads that attribute, not row position) is unaffected by re-ordering.
    columnDefaults: { sorting: { enabled: true } },
    columns,
    data,
  };
}
