/**
 * Pure adapter: the top-N ranked fund preview -> Highcharts Grid Pro Options
 * for the universe-pruning grid. The first column is a Pro CheckboxRenderer
 * ("Use") whose boolean value comes from the caller's `selectedIds` set;
 * toggling it fires `afterEdit`, which reports the row's instrument_id + new
 * checked state back via `onToggle`. The remaining columns are read-only
 * (ticker link, name, AUM/expense/sharpe), and a hidden `instrument_id` column
 * feeds the formatters + the toggle handler. Pure (no React/DOM); unit-tested.
 * Sorting is disabled — the row order IS the backend rank.
 */
import type { Options, TableCell } from "@highcharts/grid-pro";

import type { FundsList } from "@/lib/api/client";
import { formatCompact, formatNumber, formatPercent } from "@/lib/format";
import { escapeHtml } from "./fundsGridOptions";
import { GRAPHITE_THEME } from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
/** Grid `data` block variant that carries inline `columns` (local provider). */
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

export interface UniversePreviewCallbacks {
  /** A checkbox toggled: kept = include this fund id in the optimization. */
  onToggle: (id: string, checked: boolean) => void;
}

/** Display fields (excl. the synthetic `__include`) pivoted into grid data. */
const DATA_KEYS = [
  "ticker",
  "name",
  "aum_usd",
  "expense_ratio",
  "sharpe_1y",
  "instrument_id",
] as const;

function fundHref(row: GridCell["row"]): string | null {
  const id = row.getCell("instrument_id")?.value;
  return id === null || id === undefined
    ? null
    : `/funds/${encodeURIComponent(String(id))}`;
}

/** number|null -> "—" or fn(n). */
function numOrDash(value: unknown, fn: (n: number) => string): string {
  return value === null || value === undefined || value === ""
    ? "—"
    : fn(Number(value));
}

function tickerFormatter(this: GridCell): string {
  const label = escapeHtml(this.value ?? "—");
  const href = fundHref(this.row);
  return href ? `<a class="ix-grid-link" href="${href}">${label}</a>` : label;
}

function nameFormatter(this: GridCell): string {
  return `<span class="ix-grid-trunc">${escapeHtml(this.value ?? "")}</span>`;
}

function aumFormatter(this: GridCell): string {
  return numOrDash(this.value, (n) => `$${formatCompact(n)}`);
}

function expenseFormatter(this: GridCell): string {
  return numOrDash(this.value, (n) => formatPercent(n));
}

function sharpeFormatter(this: GridCell): string {
  return numOrDash(this.value, (n) => formatNumber(n));
}

export function universePreviewColumns(
  callbacks: UniversePreviewCallbacks,
): GridColumns {
  return [
    {
      id: "__include",
      header: { format: "Use" },
      className: "ix-grid-cell-check",
      cells: {
        renderer: { type: "checkbox" },
        events: {
          afterEdit(this: TableCell) {
            const id = this.row.getCell("instrument_id")?.value;
            if (id == null) return;
            callbacks.onToggle(String(id), this.value === true);
          },
        },
      },
    },
    { id: "ticker", header: { format: "Ticker" }, className: "ix-grid-cell-text", cells: { formatter: tickerFormatter } },
    { id: "name", header: { format: "Name" }, className: "ix-grid-cell-text", cells: { formatter: nameFormatter } },
    { id: "aum_usd", header: { format: "AUM" }, className: "ix-grid-cell-num", cells: { formatter: aumFormatter } },
    { id: "expense_ratio", header: { format: "Expense" }, className: "ix-grid-cell-num", cells: { formatter: expenseFormatter } },
    { id: "sharpe_1y", header: { format: "Sharpe 1Y" }, className: "ix-grid-cell-num", cells: { formatter: sharpeFormatter } },
    { id: "instrument_id", enabled: false },
  ];
}

export function universePreviewData(
  funds: FundsList["items"],
  selectedIds: Set<string>,
): LocalGridData {
  const columns: Record<string, Array<string | number | boolean | null>> = {
    __include: funds.map((it) => {
      const id = (it as Record<string, unknown>).instrument_id;
      return id != null && selectedIds.has(String(id));
    }),
  };
  for (const key of DATA_KEYS) {
    columns[key] = funds.map((it) => {
      const v = (it as Record<string, unknown>)[key];
      return typeof v === "number" || typeof v === "string" || typeof v === "boolean"
        ? v
        : null;
    });
  }
  return { providerType: "local", columns };
}

export function universePreviewToGridOptions(
  funds: FundsList["items"],
  selectedIds: Set<string>,
  callbacks: UniversePreviewCallbacks,
): Options {
  return {
    rendering: {
      theme: GRAPHITE_THEME,
      rows: { virtualization: true, virtualizationThreshold: 100, strictHeights: true },
    },
    columnDefaults: { sorting: { enabled: false } },
    columns: universePreviewColumns(callbacks),
    data: universePreviewData(funds, selectedIds),
  };
}
