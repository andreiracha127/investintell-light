/**
 * Pure adapter: weight tree rows → Highcharts Grid Pro Options for the grouped
 * results view (Asset Class → Strategy → Fund). Uses the Grid Pro TreeView
 * parent-id input; the `label` column is the tree column (expand/collapse) and
 * links fund leaves to their dossier. Mirrors the column/formatter pattern of
 * `fundsGridOptions.ts` (local provider `data` block, theme in `rendering`).
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

/** Tree column: leaf labels link to `/funds/<instrumentId>`; parents are plain. */
export function weightLabelFormatter(this: GridCell): string {
  const label = escapeHtml(this.value ?? "—");
  const id = this.row.getCell("instrumentId")?.value;
  return id === null || id === undefined || id === ""
    ? label
    : `<a class="ix-grid-link" href="/funds/${encodeURIComponent(String(id))}">${label}</a>`;
}

function weightFormatter(this: GridCell): string {
  const v = this.value;
  return v === null || v === undefined || v === "" ? "—" : formatPercent(Number(v));
}

/** Fund name column: leaf names; blank for parent (asset-class/strategy) rows. */
function nameFormatter(this: GridCell): string {
  const v = this.value;
  return v === null || v === undefined || v === ""
    ? ""
    : `<span class="ix-grid-trunc">${escapeHtml(v)}</span>`;
}

export function weightsTreeGridOptions(rows: WeightTreeRow[]): Options {
  const data: LocalGridData & { treeView: TreeViewOptionsLocal; idColumn?: string } = {
    providerType: "local",
    // TreeView parent-id input resolves parents via this row-id column; without
    // it the grid logs "data.idColumn is required" and renders a flat list.
    idColumn: "id",
    columns: {
      id: rows.map((r) => r.id),
      parentId: rows.map((r) => r.parentId ?? ""),
      label: rows.map((r) => r.label),
      name: rows.map((r) => r.name ?? ""),
      weight: rows.map((r) => r.weight),
      instrumentId: rows.map((r) => r.instrumentId ?? ""),
    },
    // Grid Pro TreeView (parent-id input): `label` is the expand/collapse
    // column; parentId references the `id` column. treeView lives on the local
    // data-provider options (TreeViewTypes.d.ts / grid-pro/tree-view/parent-id).
    treeView: {
      enabled: true,
      input: { type: "parentId", parentIdColumn: "parentId" },
      treeColumn: "label",
      expandedRowIds: "all",
    },
  };
  const columns: GridColumns = [
    {
      id: "label",
      header: { format: "Asset class / strategy / fund" },
      cells: { formatter: weightLabelFormatter },
    },
    {
      id: "name",
      header: { format: "Name" },
      cells: { formatter: nameFormatter },
    },
    {
      id: "weight",
      header: { format: "Weight" },
      cells: { formatter: weightFormatter },
    },
    { id: "id", enabled: false },
    { id: "parentId", enabled: false },
    { id: "instrumentId", enabled: false },
  ];
  return {
    rendering: {
      theme: GRAPHITE_THEME,
      rows: { strictHeights: true },
    },
    columns,
    data,
  };
}
