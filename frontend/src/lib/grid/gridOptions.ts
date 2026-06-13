/**
 * Pure adapter: turns the backend `ScreenResults` payload + current sort state
 * into a Highcharts Grid `Options` object. No React, no DOM — unit-tested.
 *
 * The grid renders; TanStack Query remains the data source. `afterSort` feeds
 * the column id + new order back to the caller, which re-fetches server-side.
 */
import type { Column, Options } from "@highcharts/grid-pro";

import type { ResultsColumn, ResultsRow, ScreenResults } from "@/lib/api/client";
import { formatMetricValue } from "@/lib/format";

export type SortDir = "asc" | "desc";

/** CSS class defined in grid-theme.css. */
export const GRAPHITE_THEME = "hcg-theme-graphite";

export interface GridSortState {
  sort?: string;
  dir: SortDir;
}

export interface GridCallbacks {
  onSortChange: (columnId: string, dir: SortDir) => void;
}

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;

/** Per-column cell formatter: text verbatim, numbers via the project formatter. */
function makeCellFormatter(dataType: string): CellFormatter {
  return function (this: GridCell): string {
    const value = this.value;
    if (value === null || value === undefined || value === "") return "—";
    if (dataType === "string") return String(value);
    return formatMetricValue(Number(value), dataType);
  };
}

/** Build the grid column definitions from the backend's dynamic columns. */
export function gridColumnsFromResults(
  columns: ResultsColumn[],
  state: GridSortState,
): GridColumns {
  return columns.map((col) => ({
    id: col.code,
    header: { format: col.name },
    className: col.data_type === "string" ? "ix-grid-cell-text" : "ix-grid-cell-num",
    cells: { formatter: makeCellFormatter(col.data_type) },
    ...(col.code === state.sort ? { sorting: { order: state.dir } } : {}),
  }));
}

/** Pivot the row objects into the grid's column-oriented `local` data block. */
export function gridDataFromResults(
  columns: ResultsColumn[],
  rows: ResultsRow[],
): NonNullable<Options["data"]> {
  const cols: Record<string, Array<string | number | null>> = {};
  for (const col of columns) {
    cols[col.code] = rows.map((row) => {
      const v = (row as Record<string, unknown>)[col.code];
      return typeof v === "number" || typeof v === "string" ? v : null;
    });
  }
  return { providerType: "local", columns: cols };
}

/** Full mapping: ScreenResults + sort state → grid Options. */
export function screenResultsToGridOptions(
  results: ScreenResults,
  state: GridSortState,
  callbacks: GridCallbacks,
): Options {
  return {
    rendering: {
      theme: GRAPHITE_THEME,
      rows: { virtualization: true, virtualizationThreshold: 100, strictHeights: true },
    },
    columnDefaults: {
      sorting: { enabled: true },
      events: {
        afterSort(this: Column) {
          const order = this.options.sorting?.order;
          // Guard: ignore the programmatic re-render that re-applies current state.
          if (
            (order === "asc" || order === "desc") &&
            !(this.id === state.sort && order === state.dir)
          ) {
            callbacks.onSortChange(this.id, order);
          }
        },
      },
    },
    columns: gridColumnsFromResults(results.columns, state),
    data: gridDataFromResults(results.columns, results.rows),
  };
}
