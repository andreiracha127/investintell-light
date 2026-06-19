/**
 * Pure adapter: PortfolioOverview -> Highcharts Grid Pro Options for the
 * positions table. Clickable field renderers (ticker link, buy date, avg cost,
 * quantity), read-only financial columns, plain value headers, and a Trade
 * action column. Pure (no React/DOM); the edit/trade callbacks are injected by
 * the component.
 */
import type { Options, TableCell } from "@highcharts/grid-pro";

import type { PortfolioOverview } from "@/lib/api/client";
import {
  formatCurrency,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { GRAPHITE_THEME } from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

export interface PositionsCallbacks {
  onEditShares: (ticker: string, value: number | null) => void;
  onEditCost: (ticker: string, value: number | null) => void;
  onEditTradeDate: (ticker: string, value: string | null) => void;
  onTrade: (ticker: string) => void;
  /** Open the position detail side panel (click on a non-interactive cell). */
  onOpenDetail?: (ticker: string) => void;
}

/** Columns whose click has its own behavior (edit / link / remove) — never
 *  triggers the detail panel. */
const NON_DETAIL_COLS = new Set([
  "cost",
  "shares",
  "ticker",
  "trade_date",
  "__trade",
]);

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
/**
 * Symbol cell: ticker link + a FUND badge for fund/ETF holdings. A holding is a
 * fund/ETF when the backend exposes its fund `instrument_id` (null for direct
 * equities). The company name now lives in its own column, so it is no longer a
 * sub-line here (matching the Claude Design mockup).
 */
function tickerFormatter(this: GridCell): string {
  const t = escapeHtml(this.value ?? "—");
  const isFund = this.row.getCell("instrument_id")?.value != null;
  // Reuse the shared `ix-grid-basis` badge style (token-based, bordered chip);
  // a leading hair-space separates it from the symbol link.
  const badge = isFund
    ? ` <span class="ix-grid-basis" title="Fund / ETF — detailed exposure on the Exposure tab.">FUND</span>`
    : "";
  return `<a class="ix-grid-link" href="/stocks/${encodeURIComponent(String(this.value ?? ""))}">${t}</a>${badge}`;
}

function nameFormatter(this: GridCell): string {
  return this.value ? escapeHtml(String(this.value)) : "—";
}

function pnlPctFormatter(this: GridCell): string {
  const pct = num(this.value);
  if (pct === null) return "—";
  return `<span class="${toneClass(pct)}">${escapeHtml(formatPercent(pct, 2, { signed: true }))}</span>`;
}

function lastFormatter(this: GridCell): string {
  return escapeHtml(formatCurrency(num(this.value) ?? 0));
}

function costFormatter(this: GridCell): string {
  const price = num(this.value);
  const commission = num(this.row.getCell("commission")?.value);
  const value = `<button type="button" class="ix-grid-value-button ix-grid-editable" title="Set average cost">${price === null ? "—" : escapeHtml(formatCurrency(price))}</button>`;
  const comm = commission === null ? "" : `<span class="ix-grid-comm">incl. comm. ${escapeHtml(formatCurrency(commission))}</span>`;
  return `${value}${comm}`;
}

function formatBuyDate(value: unknown): string {
  const [year, month, day] = String(value ?? "").slice(0, 10).split("-");
  if (!year || !month || !day) return "Set date";
  return `${day}/${month}/${year.slice(-2)}`;
}

function dateFormatter(this: GridCell): string {
  const value = this.value;
  return `<button type="button" class="ix-grid-date" title="Set buy date">${
    value ? escapeHtml(formatBuyDate(value)) : "Set date"
  }</button>`;
}

function sharesFormatter(this: GridCell): string {
  const q = num(this.value);
  return `<button type="button" class="ix-grid-value-button ix-grid-editable" title="Set quantity">${
    q === null ? "—" : escapeHtml(formatShares(q))
  }</button>`;
}

function pnlFormatter(this: GridCell): string {
  const pnl = num(this.value);
  if (pnl === null) return "—";
  return `<span class="${toneClass(pnl)}">${escapeHtml(formatCurrency(pnl, { signed: true }))}</span>`;
}

function mktValueFormatter(this: GridCell): string {
  return escapeHtml(formatCurrency(num(this.value) ?? 0));
}

/* ── column + data builders ───────────────────────────────────────── */
export function positionsGridColumns(callbacks?: PositionsCallbacks): GridColumns {
  // Column order mirrors the Claude Design mockup: Symbol, Company, Qty,
  // Avg cost, Price, Market value, P&L, P&L %, action. The "Change" column the
  // grid used to carry is dropped from the visible set (its data stays as a
  // hidden column for the live-tick path / data contract).
  const cols: GridColumns = [
    { id: POSITION_COLS.ticker, header: { format: "Symbol" }, className: "ix-grid-cell-text", cells: { formatter: tickerFormatter } },
    { id: "name", header: { format: "Company" }, className: "ix-grid-cell-text", cells: { formatter: nameFormatter } },
    {
      id: "trade_date",
      header: { format: "Buy date" },
      className: "ix-grid-cell-text",
      cells: {
        formatter: dateFormatter,
        events: {
          click(this: TableCell) {
            const ticker = this.row.getCell("ticker")?.value;
            if (ticker == null || !callbacks) return;
            callbacks.onEditTradeDate(
              String(ticker),
              this.value == null ? null : String(this.value),
            );
          },
        },
      },
    },
    { id: POSITION_COLS.last, header: { format: "Price" }, className: "ix-grid-cell-num", cells: { formatter: lastFormatter } },
    {
      id: "cost",
      header: { format: "Avg cost" },
      className: "ix-grid-cell-num",
      dataType: "number",
      cells: {
        formatter: costFormatter,
        events: {
          click(this: TableCell) {
            const ticker = this.row.getCell("ticker")?.value;
            if (ticker == null || !callbacks) return;
            callbacks.onEditCost(String(ticker), num(this.value));
          },
        },
      },
    },
    {
      id: "shares",
      header: { format: "Qty" },
      className: "ix-grid-cell-num",
      dataType: "number",
      cells: {
        formatter: sharesFormatter,
        events: {
          click(this: TableCell) {
            const ticker = this.row.getCell("ticker")?.value;
            if (ticker == null || !callbacks) return;
            callbacks.onEditShares(String(ticker), num(this.value));
          },
        },
      },
    },
    { id: "mktvalue", header: { format: "Market value" }, className: "ix-grid-cell-num", cells: { formatter: mktValueFormatter } },
    { id: "pnl", header: { format: "P&L" }, className: "ix-grid-cell-num", cells: { formatter: pnlFormatter } },
    { id: "pnl_pct", header: { format: "P&L %" }, className: "ix-grid-cell-num", cells: { formatter: pnlPctFormatter } },
    {
      id: "__trade",
      header: { format: "Trade" },
      className: "ix-grid-cell-num",
      sorting: { enabled: false },
      cells: {
        formatter() { return `<button type="button" class="ix-grid-trade" title="Register buy or sell">Trade</button>`; },
        events: {
          click(this: TableCell) {
            const ticker = this.row.getCell("ticker")?.value;
            if (ticker != null && callbacks) callbacks.onTrade(String(ticker));
          },
        },
      },
    },
    // hidden data-only columns consumed by formatters via row.getCell and by the
    // live-tick effect (change/change_pct preserved for the data contract).
    { id: "instrument_id", enabled: false },
    { id: "change", enabled: false },
    { id: "change_pct", enabled: false },
    { id: "basis", enabled: false },
    { id: "commission", enabled: false },
  ];
  return cols;
}

/** Case-insensitive match of a position against the search box (symbol/name). */
function matchesSearch(p: PortfolioOverview["positions"][number], q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  const ticker = String(p.ticker ?? "").toLowerCase();
  const name = String(p.name ?? "").toLowerCase();
  return ticker.includes(needle) || name.includes(needle);
}

/**
 * Pivot positions into the grid's column-oriented local data, optionally
 * filtered by a search term and capped to `limit` rows (Load-more). Filtering
 * here is presentation-only — it slices already-fetched overview data and never
 * touches the data call.
 */
export function positionsGridData(
  positions: PortfolioOverview["positions"],
  opts: { search?: string; limit?: number } = {},
): LocalGridData {
  const map: Record<string, string> = {
    ticker: "ticker", name: "name", instrument_id: "instrument_id",
    last: "last_close", change: "change", change_pct: "change_pct",
    cost: "acq_price", basis: "basis", commission: "commission",
    trade_date: "trade_date", shares: "quantity",
    pnl: "pnl", pnl_pct: "pnl_pct", mktvalue: "market_value",
  };
  let rows = opts.search ? positions.filter((p) => matchesSearch(p, opts.search!)) : positions;
  if (opts.limit != null) rows = rows.slice(0, opts.limit);
  const columns: Record<string, Array<string | number | boolean | null>> = {};
  for (const [colId, field] of Object.entries(map)) {
    columns[colId] = rows.map((p) => {
      const v = (p as Record<string, unknown>)[field];
      return typeof v === "number" || typeof v === "string" || typeof v === "boolean" ? v : null;
    });
  }
  return { providerType: "local", columns };
}

/** Count of positions matching the current search (for the header counter). */
export function countMatchingPositions(
  positions: PortfolioOverview["positions"],
  search?: string,
): number {
  return search ? positions.filter((p) => matchesSearch(p, search)).length : positions.length;
}

export function positionsToGridOptions(
  overview: PortfolioOverview,
  callbacks: PositionsCallbacks,
  view: { search?: string; limit?: number } = {},
): Options {
  return {
    rendering: { theme: GRAPHITE_THEME, rows: { virtualization: false, strictHeights: false } },
    columnDefaults: {
      // Column sorting: the grid renders its native aria-sort + sort-arrow
      // affordance per column header (the action column opts out above).
      sorting: { enabled: true },
      cells: {
        events: {
          click(this: TableCell) {
            // Row → detail panel, except on cells with their own click
            // (field buttons, the ticker link, and the Trade action).
            if (!callbacks.onOpenDetail) return;
            const colId = this.column?.id;
            if (colId && NON_DETAIL_COLS.has(colId)) return;
            const ticker = this.row.getCell("ticker")?.value;
            if (ticker != null) callbacks.onOpenDetail(String(ticker));
          },
        },
      },
    },
    columns: positionsGridColumns(callbacks),
    data: positionsGridData(overview.positions, view),
  };
}
