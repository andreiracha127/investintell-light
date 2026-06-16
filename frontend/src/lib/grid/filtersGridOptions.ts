import type { Options, TableCell } from "@highcharts/grid-pro";

import type { MetricBuild, MetricDef, ScreenFilter } from "@/lib/api/client";
import { sparklineSvg } from "./sparkline";
import { escapeHtml } from "./fundsGridOptions";
import { GRAPHITE_THEME } from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

export interface FiltersGridCallbacks {
  /** A Min/Max cell was edited; `value` is the API value (fraction for percent) or null (unbounded). */
  onEditBound: (metricCode: string, which: "min" | "max", value: number | null) => void;
  onRemove: (metricCode: string) => void;
  onMove: (metricCode: string, direction: "up" | "down") => void;
  onToggleSelect: (metricCode: string, checked: boolean) => void;
  /** Row activated (Metric cell clicked) → drives the DistributionPanel. */
  onSelectRow: (metricCode: string) => void;
}

const isPercent = (m: MetricDef | undefined): boolean => m?.data_type === "percent";
const num = (v: unknown): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);

/** API bound -> display number (percent fractions shown as 0-100). */
function toDisplay(value: number | null, percent: boolean): number | null {
  return value === null ? null : percent ? value * 100 : value;
}

/* ── formatters ───────────────────────────────────────────────────── */
function metricFormatter(this: GridCell): string {
  const abbr = this.row.getCell("abbr")?.value;
  const sub = abbr ? `<span class="ix-grid-sub">${escapeHtml(abbr)}</span>` : "";
  return `<button type="button" class="ix-grid-rowname">${escapeHtml(this.value ?? "")}</button>${sub}`;
}
function boundFormatter(this: GridCell): string {
  if (this.value === null || this.value === "") return `<span class="ix-grid-editable">—</span>`;
  const unit = this.row.getCell("unit")?.value;
  return `<span class="ix-grid-editable">${escapeHtml(String(this.value))}${unit ? escapeHtml(String(unit)) : ""}</span>`;
}
function distFormatter(this: GridCell): string {
  return this.value ? String(this.value) : "—"; // pre-rendered SVG string (or em-dash)
}
function upFormatter(): string {
  return `<span class="ix-grid-mv" title="Move up" aria-label="Move up">↑</span>`;
}
function downFormatter(): string {
  return `<span class="ix-grid-mv" title="Move down" aria-label="Move down">↓</span>`;
}
function removeFormatter(): string {
  return `<span class="ix-grid-remove" title="Remove" aria-label="Remove filter">×</span>`;
}

const codeOf = (cell: TableCell): string | null => {
  const code = cell.row.getCell("metric_code")?.value;
  return code == null ? null : String(code);
};

/* ── columns ──────────────────────────────────────────────────────── */
export function filtersGridColumns(callbacks: FiltersGridCallbacks): GridColumns {
  return [
    {
      id: "__select",
      header: { format: "" },
      className: "ix-grid-cell-check",
      cells: {
        renderer: { type: "checkbox" },
        events: {
          afterEdit(this: TableCell) {
            const c = codeOf(this);
            if (c) callbacks.onToggleSelect(c, this.value === true);
          },
        },
      },
    },
    {
      id: "__up",
      header: { format: "" },
      className: "ix-grid-cell-mv",
      cells: {
        formatter: upFormatter,
        events: {
          click(this: TableCell) {
            const c = codeOf(this);
            if (c) callbacks.onMove(c, "up");
          },
        },
      },
    },
    {
      id: "__down",
      header: { format: "" },
      className: "ix-grid-cell-mv",
      cells: {
        formatter: downFormatter,
        events: {
          click(this: TableCell) {
            const c = codeOf(this);
            if (c) callbacks.onMove(c, "down");
          },
        },
      },
    },
    {
      id: "metric",
      header: { format: "Metric" },
      className: "ix-grid-cell-text",
      cells: {
        formatter: metricFormatter,
        events: {
          click(this: TableCell) {
            const c = codeOf(this);
            if (c) callbacks.onSelectRow(c);
          },
        },
      },
    },
    { id: "min", header: { format: "Min" }, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: boundFormatter, editMode: { enabled: true } } },
    { id: "max", header: { format: "Max" }, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: boundFormatter, editMode: { enabled: true } } },
    { id: "dist", header: { format: "Distribution" }, className: "ix-grid-cell-num", cells: { formatter: distFormatter } },
    {
      id: "__remove",
      header: { format: "" },
      className: "ix-grid-cell-num",
      cells: {
        formatter: removeFormatter,
        events: {
          click(this: TableCell) {
            const c = codeOf(this);
            if (c) callbacks.onRemove(c);
          },
        },
      },
    },
    // hidden data-only columns used by formatters / handlers via row.getCell
    { id: "metric_code", enabled: false },
    { id: "abbr", enabled: false },
    { id: "unit", enabled: false },
    { id: "is_percent", enabled: false },
  ];
}

/* ── data ─────────────────────────────────────────────────────────── */
export function filtersGridData(
  filters: ScreenFilter[],
  catalog: Map<string, MetricDef>,
  builds: Map<string, MetricBuild>,
  selected: ReadonlySet<string>,
): LocalGridData {
  const ordered = [...filters].sort((a, b) => a.position - b.position);
  const columns: Record<string, Array<string | number | boolean | null>> = {
    __select: ordered.map((f) => selected.has(f.metric_code)),
    __up: ordered.map(() => null),
    __down: ordered.map(() => null),
    metric: ordered.map((f) => catalog.get(f.metric_code)?.name ?? f.metric_code),
    metric_code: ordered.map((f) => f.metric_code),
    abbr: ordered.map((f) => catalog.get(f.metric_code)?.abbreviation ?? ""),
    unit: ordered.map((f) => (isPercent(catalog.get(f.metric_code)) ? "%" : "")),
    is_percent: ordered.map((f) => isPercent(catalog.get(f.metric_code))),
    min: ordered.map((f) => toDisplay(f.min_value, isPercent(catalog.get(f.metric_code)))),
    max: ordered.map((f) => toDisplay(f.max_value, isPercent(catalog.get(f.metric_code)))),
    dist: ordered.map((f) => {
      const d = builds.get(f.metric_code)?.distribution;
      return d ? sparklineSvg(d, { min: f.min_value, max: f.max_value }) : null;
    }),
  };
  return { providerType: "local", columns };
}

/* ── full options ─────────────────────────────────────────────────── */
export function screenFiltersToGridOptions(
  filters: ScreenFilter[],
  catalog: Map<string, MetricDef>,
  builds: Map<string, MetricBuild>,
  selected: ReadonlySet<string>,
  callbacks: FiltersGridCallbacks,
): Options {
  return {
    rendering: { theme: GRAPHITE_THEME, rows: { virtualization: false, strictHeights: true } },
    columnDefaults: {
      sorting: { enabled: false },
      cells: {
        events: {
          afterEdit(this: TableCell) {
            const colId = this.column?.id;
            if (colId !== "min" && colId !== "max") return;
            const code = codeOf(this);
            if (!code) return;
            const percent = this.row.getCell("is_percent")?.value === true;
            const display = num(this.value);
            const apiValue = display === null ? null : percent ? display / 100 : display;
            callbacks.onEditBound(code, colId, apiValue);
          },
        },
      },
    },
    columns: filtersGridColumns(callbacks),
    data: filtersGridData(filters, catalog, builds, selected),
  };
}
