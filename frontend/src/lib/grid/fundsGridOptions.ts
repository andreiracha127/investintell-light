/**
 * Pure adapter: FundsList -> Highcharts Grid Pro Options for the Funds universe.
 * Fixed columns with bespoke cell renderers (profile links, type tag, sign-
 * coloured return, elite check, formatted numerics). Pure (no React/DOM) and
 * unit-tested. Reuses the shared theme/sort types from gridOptions.ts.
 */
import type { Column, Options } from "@highcharts/grid-pro";

import type { FundsList } from "@/lib/api/client";
import { formatCompact, formatNumber, formatPercent } from "@/lib/format";
import {
  GRAPHITE_THEME,
  type GridCallbacks,
  type GridSortState,
} from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type SortOrder = NonNullable<
  NonNullable<GridColumns[number]["sorting"]>["orderSequence"]
>[number];

const TYPE_TAG: Record<string, string> = { etf: "ETF", mutual_fund: "MF", mmf: "MMF" };
const ASSET_CLASS_LABEL: Record<string, string> = {
  equity: "Equity",
  fixed_income: "Fixed income",
  cash: "Cash",
  alternatives: "Alternatives",
};

const NUM_SEQ: SortOrder[] = ["desc", "asc", null];
const TEXT_SEQ: SortOrder[] = ["asc", "desc", null];

/** All FundListItem keys we feed to the grid (display columns + link internals). */
const DATA_KEYS = [
  "ticker", "name", "fund_type", "strategy_label", "asset_class",
  "aum_usd", "expense_ratio", "return_1y", "volatility_1y", "sharpe_1y",
  "peer_sharpe_pctl", "manager_score", "elite_flag", "instrument_id", "profile_href",
] as const;

/** Escape text destined for a cell's HTML formatter output. */
export function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fundHref(row: GridCell["row"]): string | null {
  const rowData = (row as GridCell["row"] & { data?: Record<string, unknown> }).data;
  const dataHref = rowData?.profile_href;
  const href = dataHref ?? row.getCell("profile_href")?.value;
  if (href !== null && href !== undefined && href !== "") {
    return String(href);
  }
  const dataId = rowData?.instrument_id;
  const id = dataId ?? row.getCell("instrument_id")?.value;
  return id === null || id === undefined || id === "" ? null : `/funds/${encodeURIComponent(String(id))}`;
}

/** number|null -> "—" or fn(n). */
function numOrDash(value: unknown, fn: (n: number) => string): string {
  return value === null || value === undefined || value === "" ? "—" : fn(Number(value));
}

function tickerFormatter(this: GridCell): string {
  const label = escapeHtml(this.value ?? "—");
  const href = fundHref(this.row);
  return href && this.value != null && this.value !== ""
    ? `<a class="ix-grid-link" href="${escapeHtml(href)}">${label}</a>`
    : label;
}

function nameFormatter(this: GridCell): string {
  return `<span class="ix-grid-trunc">${escapeHtml(this.value ?? "")}</span>`;
}

function typeFormatter(this: GridCell): string {
  const v = String(this.value ?? "");
  return `<span class="ix-grid-tag">${escapeHtml(TYPE_TAG[v] ?? v)}</span>`;
}

function assetClassFormatter(this: GridCell): string {
  const v = this.value;
  if (v === null || v === undefined || v === "") return "—";
  return escapeHtml(ASSET_CLASS_LABEL[String(v)] ?? String(v));
}

function strategyFormatter(this: GridCell): string {
  return `<span class="ix-grid-trunc">${escapeHtml(this.value ?? "")}</span>`;
}

function returnFormatter(this: GridCell): string {
  const v = this.value;
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  const cls = n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";
  const text = escapeHtml(formatPercent(n, 2, { signed: true }));
  return `<span class="${cls}">${text}</span>`;
}

function eliteFormatter(this: GridCell): string {
  return this.value
    ? `<span class="ix-grid-elite" aria-label="Elite fund">✓</span>`
    : `<span class="text-text-muted">—</span>`;
}

interface FundColSpec {
  id: string;
  label: string;
  numeric: boolean;
  width: number;
  formatter: CellFormatter;
}

const FUND_COLUMNS: FundColSpec[] = [
  { id: "ticker", label: "Ticker", numeric: false, width: 100, formatter: tickerFormatter },
  { id: "name", label: "Name", numeric: false, width: 340, formatter: nameFormatter },
  { id: "fund_type", label: "Type", numeric: false, width: 90, formatter: typeFormatter },
  { id: "strategy_label", label: "Strategy", numeric: false, width: 220, formatter: strategyFormatter },
  { id: "asset_class", label: "Asset class", numeric: false, width: 130, formatter: assetClassFormatter },
  { id: "aum_usd", label: "AUM", numeric: true, width: 120, formatter(this: GridCell) { return numOrDash(this.value, (n) => `$${formatCompact(n)}`); } },
  { id: "expense_ratio", label: "Expense", numeric: true, width: 100, formatter(this: GridCell) { return numOrDash(this.value, (n) => formatPercent(n)); } },
  { id: "return_1y", label: "Return 1Y", numeric: true, width: 110, formatter: returnFormatter },
  { id: "volatility_1y", label: "Vol 1Y", numeric: true, width: 100, formatter(this: GridCell) { return numOrDash(this.value, (n) => formatPercent(n)); } },
  { id: "sharpe_1y", label: "Sharpe 1Y", numeric: true, width: 100, formatter(this: GridCell) { return numOrDash(this.value, (n) => formatNumber(n)); } },
  { id: "peer_sharpe_pctl", label: "Peer pctl", numeric: true, width: 100, formatter(this: GridCell) { return numOrDash(this.value, (n) => formatNumber(n, 0)); } },
  { id: "manager_score", label: "Score", numeric: true, width: 90, formatter(this: GridCell) { return numOrDash(this.value, (n) => formatNumber(n)); } },
  { id: "elite_flag", label: "Elite", numeric: true, width: 80, formatter: eliteFormatter },
];

export function fundsGridColumns(state: GridSortState): GridColumns {
  const cols: GridColumns = FUND_COLUMNS.map((c) => ({
    id: c.id,
    header: { format: c.label },
    className: c.numeric ? "ix-grid-cell-num" : "ix-grid-cell-text",
    width: c.width,
    cells: { formatter: c.formatter },
    sorting: {
      orderSequence: c.numeric ? NUM_SEQ : TEXT_SEQ,
      ...(c.id === state.sort ? { order: state.dir } : {}),
    },
  }));
  cols.push({ id: "instrument_id", enabled: false });
  cols.push({ id: "profile_href", enabled: false });
  return cols;
}

/** Grid `data` block variant that carries inline `columns` (local provider). */
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

export function fundsGridData(items: FundsList["items"]): LocalGridData {
  const columns: Record<string, Array<string | number | boolean | null>> = {};
  for (const key of DATA_KEYS) {
    columns[key] = items.map((it) => {
      if (key === "profile_href") {
        const id = (it as Record<string, unknown>).instrument_id;
        return typeof id === "string"
          ? `/funds/${encodeURIComponent(id)}`
          : null;
      }
      const v = (it as Record<string, unknown>)[key];
      return typeof v === "number" || typeof v === "string" || typeof v === "boolean"
        ? v
        : null;
    });
  }
  return { providerType: "local", columns };
}

export function fundsListToGridOptions(
  data: FundsList,
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
          if (
            (order === "asc" || order === "desc") &&
            !(this.id === state.sort && order === state.dir)
          ) {
            callbacks.onSortChange(this.id, order);
          }
        },
      },
    },
    columns: fundsGridColumns(state),
    data: fundsGridData(data.items),
  };
}
