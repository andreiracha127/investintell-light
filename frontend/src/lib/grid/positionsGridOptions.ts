/**
 * Pure adapter: PortfolioOverview -> Highcharts Grid Pro Options for the
 * positions table. Editable shares/cost (Pro cell editing) with bespoke
 * read-only renderers (ticker link + name, change/pnl sub-lines, EXEC/REF
 * basis badge + commission), aggregates baked into the P&L / Mkt Value
 * headers, and a × action column. Pure (no React/DOM); the edit/remove
 * callbacks are injected by the component.
 */
import type { Options, TableCell } from "@highcharts/grid-pro";

import type { PortfolioOverview } from "@/lib/api/client";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import { GRAPHITE_THEME } from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type Aggregates = PortfolioOverview["aggregates"];
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

export interface PositionsCallbacks {
  onEditShares: (ticker: string, value: number) => void;
  onEditCost: (ticker: string, value: number | null) => void;
  onRemove: (ticker: string) => void;
}

/**
 * Column ids referenced cross-file by the live-tick effect (which reads the
 * "ticker" cell to match a symbol and writes the "last" cell). Shared so a
 * rename stays compile-safe; other column ids stay inline.
 */
export const POSITION_COLS = { ticker: "ticker", last: "last" } as const;

export function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Share count without fake precision: 8 -> "8", 8.5 -> "8.50". */
export function formatShares(quantity: number): string {
  return formatNumber(quantity, Number.isInteger(quantity) ? 0 : 2);
}

const toneClass = (n: number | null): string =>
  n === null ? "" : n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";

const num = (v: unknown): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);

/* ── read-only formatters ─────────────────────────────────────────── */
function tickerFormatter(this: GridCell): string {
  const t = escapeHtml(this.value ?? "—");
  const name = this.row.getCell("name")?.value;
  const sub = name ? `<span class="ix-grid-name">${escapeHtml(name)}</span>` : "";
  return `<a class="ix-grid-link" href="/stocks/${encodeURIComponent(String(this.value ?? ""))}">${t}</a>${sub}`;
}

function lastFormatter(this: GridCell): string {
  return escapeHtml(formatCurrency(num(this.value) ?? 0));
}

function changeFormatter(this: GridCell): string {
  const change = num(this.value);
  const pct = num(this.row.getCell("change_pct")?.value);
  if (change === null || pct === null) return "—";
  const cls = toneClass(change);
  return `<span class="${cls}">${escapeHtml(formatCurrency(change, { signed: true }))}<span class="ix-grid-sub">${escapeHtml(formatPercent(pct, 2, { signed: true }))}</span></span>`;
}

function costFormatter(this: GridCell): string {
  const price = num(this.value);
  const basis = String(this.row.getCell("basis")?.value ?? "");
  const commission = num(this.row.getCell("commission")?.value);
  const exec = basis === "executed";
  const badge = `<span class="ix-grid-basis ${exec ? "ix-grid-basis-exec" : ""}">${exec ? "EXEC" : "REF"}</span>`;
  const value = `<span class="ix-grid-editable">${price === null ? "—" : escapeHtml(formatCurrency(price))}</span>`;
  const comm = commission === null ? "" : `<span class="ix-grid-comm">incl. comm. ${escapeHtml(formatCurrency(commission))}</span>`;
  return `${badge} ${value}${comm}`;
}

function sharesFormatter(this: GridCell): string {
  const q = num(this.value);
  return q === null ? "—" : `<span class="ix-grid-editable">${escapeHtml(formatShares(q))}</span>`;
}

function pnlFormatter(this: GridCell): string {
  const pnl = num(this.value);
  const pct = num(this.row.getCell("pnl_pct")?.value);
  if (pnl === null || pct === null) return "—";
  const cls = toneClass(pnl);
  return `<span class="${cls}">${escapeHtml(formatCurrency(pnl, { signed: true }))}<span class="ix-grid-sub">${escapeHtml(formatPercent(pct, 2, { signed: true }))}</span></span>`;
}

function mktValueFormatter(this: GridCell): string {
  return escapeHtml(formatCurrency(num(this.value) ?? 0));
}

/* ── column + data builders ───────────────────────────────────────── */
const PNL_AGG = (a: Aggregates): string => {
  if (a.total_pnl === null) return "P&L";
  const pct = a.total_pnl_pct !== null ? ` (${formatPercent(a.total_pnl_pct, 2, { signed: true })})` : "";
  return `P&L · ${formatCurrency(a.total_pnl, { signed: true })}${pct}`;
};

export function positionsGridColumns(aggregates: Aggregates, callbacks?: PositionsCallbacks): GridColumns {
  const cols: GridColumns = [
    { id: POSITION_COLS.ticker, header: { format: "Ticker" }, className: "ix-grid-cell-text", cells: { formatter: tickerFormatter } },
    { id: POSITION_COLS.last, header: { format: "Last" }, className: "ix-grid-cell-num", cells: { formatter: lastFormatter } },
    { id: "change", header: { format: "Change" }, className: "ix-grid-cell-num", cells: { formatter: changeFormatter } },
    { id: "cost", header: { format: "Cost" }, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: costFormatter, editMode: { enabled: true } } },
    { id: "shares", header: { format: "Shares" }, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: sharesFormatter, editMode: { enabled: true } } },
    { id: "pnl", header: { format: PNL_AGG(aggregates) }, className: "ix-grid-cell-num", cells: { formatter: pnlFormatter } },
    { id: "mktvalue", header: { format: `Mkt Value · ${formatCurrency(aggregates.total_market_value)}` }, className: "ix-grid-cell-num", cells: { formatter: mktValueFormatter } },
    {
      id: "__remove",
      header: { format: "" },
      className: "ix-grid-cell-num",
      cells: {
        formatter() { return `<span class="ix-grid-remove" title="Remove" aria-label="Remove position">×</span>`; },
        events: {
          click(this: TableCell) {
            const ticker = this.row.getCell("ticker")?.value;
            if (ticker != null && callbacks) callbacks.onRemove(String(ticker));
          },
        },
      },
    },
    // hidden data-only columns used by formatters via row.getCell
    { id: "name", enabled: false },
    { id: "change_pct", enabled: false },
    { id: "basis", enabled: false },
    { id: "commission", enabled: false },
    { id: "pnl_pct", enabled: false },
  ];
  return cols;
}

export function positionsGridData(positions: PortfolioOverview["positions"]): LocalGridData {
  const map: Record<string, string> = {
    ticker: "ticker", name: "name", last: "last_close", change: "change", change_pct: "change_pct",
    cost: "acq_price", basis: "basis", commission: "commission", shares: "quantity",
    pnl: "pnl", pnl_pct: "pnl_pct", mktvalue: "market_value",
  };
  const columns: Record<string, Array<string | number | boolean | null>> = {};
  for (const [colId, field] of Object.entries(map)) {
    columns[colId] = positions.map((p) => {
      const v = (p as Record<string, unknown>)[field];
      return typeof v === "number" || typeof v === "string" || typeof v === "boolean" ? v : null;
    });
  }
  return { providerType: "local", columns };
}

export function positionsToGridOptions(
  overview: PortfolioOverview,
  callbacks: PositionsCallbacks,
): Options {
  return {
    rendering: { theme: GRAPHITE_THEME, rows: { virtualization: false, strictHeights: false } },
    columnDefaults: {
      sorting: { enabled: false },
      cells: {
        events: {
          afterEdit(this: TableCell) {
            const colId = this.column?.id;
            const ticker = this.row.getCell("ticker")?.value;
            if (ticker == null) return;
            const value = num(this.value);
            if (colId === "shares") {
              if (value !== null) callbacks.onEditShares(String(ticker), value);
            } else if (colId === "cost") {
              callbacks.onEditCost(String(ticker), value);
            }
          },
        },
      },
    },
    columns: positionsGridColumns(overview.aggregates, callbacks),
    data: positionsGridData(overview.positions),
  };
}
