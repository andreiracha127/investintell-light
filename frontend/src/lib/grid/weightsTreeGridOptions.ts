/**
 * Pure adapter: weight tree rows → Highcharts Grid Pro Options for the grouped
 * results view (Asset class → Fund/Stock). Two-level parent-id TreeView, COLLAPSED
 * by default; the `label` column is the tree column (expand/collapse) and renders
 * the leaf as ticker (dossier link) over name, mirroring the Funds universe table.
 * Strategy and Weight are their own columns. Group rows show the asset-class label
 * and the aggregated weight in bold.
 */
import type { Options } from "@highcharts/grid-pro";

import type { WeightTreeRow } from "@/lib/builder/weightsTree";
import { formatPercent } from "@/lib/format";
import { GRAPHITE_THEME } from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
/** Grid `data` block variant that carries inline `columns` (local provider). */
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

/** TreeView options (Grid Pro). The module augments `LocalDataProviderOptions`
 * with `treeView` at runtime (TreeViewTypes.d.ts), but the augmentation is not
 * surfaced through the `@highcharts/grid-pro` entry types, so mirror the shape
 * locally and intersect it onto the local data block. */
interface TreeViewOptionsLocal {
  enabled?: boolean;
  input?: { type: "parentId"; parentIdColumn?: string };
  treeColumn?: string;
  expandedRowIds?: string[] | "all";
  stickyParents?: boolean;
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isGroupRow(cell: GridCell): boolean {
  return cell.row.getCell("isGroup")?.value === true;
}

/**
 * Tree column: group rows show the asset-class label in bold; leaves show the
 * ticker (linked to the fund dossier when there's an instrumentId) over the
 * display name — the Funds-universe "ticker over name" treatment.
 */
export function weightLabelFormatter(this: GridCell): string {
  const label = escapeHtml(this.value ?? "—");
  if (isGroupRow(this)) {
    return `<span class="ix-grid-group">${label}</span>`;
  }
  const id = this.row.getCell("instrumentId")?.value;
  const ticker =
    id === null || id === undefined || id === ""
      ? `<span class="ix-grid-sub">${label}</span>`
      : `<a class="ix-grid-link" href="/funds/${encodeURIComponent(String(id))}">${label}</a>`;
  const name = this.row.getCell("name")?.value;
  const nameLine =
    name === null || name === undefined || name === ""
      ? ""
      : `<span class="ix-grid-name">${escapeHtml(name)}</span>`;
  return `${ticker}${nameLine}`;
}

/** Strategy column: leaf strategy label; blank for group rows / strategy-less holdings. */
function strategyFormatter(this: GridCell): string {
  const v = this.value;
  return v === null || v === undefined || v === ""
    ? ""
    : `<span class="ix-grid-trunc">${escapeHtml(v)}</span>`;
}

/** Weight column: percent for all rows; bold for group (subtotal) rows. */
function weightFormatter(this: GridCell): string {
  const v = this.value;
  if (v === null || v === undefined || v === "") return "—";
  const text = formatPercent(Number(v));
  return isGroupRow(this) ? `<span class="ix-grid-group">${text}</span>` : text;
}

export function weightsTreeGridOptions(rows: WeightTreeRow[]): Options {
  const data: LocalGridData & { treeView: TreeViewOptionsLocal; idColumn?: string } = {
    providerType: "local",
    // TreeView parent-id input resolves parents via this row-id column; without
    // it the grid logs "data.idColumn is required" and renders a flat list.
    idColumn: "id",
    columns: {
      id: rows.map((r) => r.id),
      // Roots MUST be null (not ""): the parent-id tree adapter treats null as
      // "root", but "" as a reference to a (non-existent) row with id "" →
      // "Missing parent" → the tree build fails and the grid renders flat.
      parentId: rows.map((r) => r.parentId ?? null),
      label: rows.map((r) => r.label),
      name: rows.map((r) => r.name ?? ""),
      strategy: rows.map((r) => r.strategy ?? ""),
      weight: rows.map((r) => r.weight),
      instrumentId: rows.map((r) => r.instrumentId ?? ""),
      isGroup: rows.map((r) => r.isGroup),
    },
    // Grid Pro TreeView (parent-id input): `label` is the expand/collapse column;
    // parentId references the `id` column. COLLAPSED by default — only the
    // top-level asset-class rows show until the user expands a node.
    treeView: {
      enabled: true,
      input: { type: "parentId", parentIdColumn: "parentId" },
      treeColumn: "label",
      expandedRowIds: [],
    },
  };
  const columns: GridColumns = [
    {
      id: "label",
      header: { format: "Holding" },
      className: "ix-grid-cell-text",
      cells: { formatter: weightLabelFormatter },
    },
    {
      id: "strategy",
      header: { format: "Strategy" },
      className: "ix-grid-cell-text",
      cells: { formatter: strategyFormatter },
    },
    {
      id: "weight",
      header: { format: "Weight" },
      className: "ix-grid-cell-num",
      cells: { formatter: weightFormatter },
    },
    { id: "id", enabled: false },
    { id: "parentId", enabled: false },
    { id: "name", enabled: false },
    { id: "instrumentId", enabled: false },
    { id: "isGroup", enabled: false },
  ];
  return {
    rendering: {
      theme: GRAPHITE_THEME,
      // Leaves render ticker over name (two lines): let rows auto-size, matching
      // the positions grid, so the second line is not clipped.
      rows: { strictHeights: false },
    },
    columns,
    data,
  };
}
