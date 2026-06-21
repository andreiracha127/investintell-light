/**
 * Pure adapter: StockHolders -> Highcharts Grid Pro Options for the Stocks →
 * Holders table. Read-only: manager, shares, market value, share of total, and
 * position return (return is null until prior-period history is ingested).
 * Pure (no React/DOM).
 */
import type { Options } from "@highcharts/grid-pro";

import type { StockHolders } from "@/lib/api/client";
import { formatNumber, formatPercent } from "@/lib/format";
import { GRAPHITE_THEME } from "./gridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const num = (v: unknown): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);

const toneClass = (n: number | null): string =>
  n === null ? "" : n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";

/** Compact USD for large institutional positions: 336352928002 -> "$336.4B". */
export function compactUsd(value: number | null): string {
  if (value === null) return "—";
  const abs = Math.abs(value);
  const [div, suffix] =
    abs >= 1e12 ? [1e12, "T"] : abs >= 1e9 ? [1e9, "B"] : abs >= 1e6 ? [1e6, "M"] : [1e3, "K"];
  return `$${formatNumber(value / div, 1)}${suffix}`;
}

/** Some source names arrive HTML-escaped (e.g. "JPMORGAN CHASE &amp; CO"). */
function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'");
}

/**
 * Normalize SHOUTY names ("VANGUARD INDEX FUNDS" -> "Vanguard Index Funds")
 * while leaving genuinely mixed-case names ("BlackRock, Inc.") untouched —
 * decided by whether upper-case letters dominate.
 */
export function titleCase(s: string): string {
  const t = decodeEntities(s);
  const upper = (t.match(/[A-Z]/g) || []).length;
  const lower = (t.match(/[a-z]/g) || []).length;
  if (upper <= lower) return t;
  return t.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

/* ── formatters ───────────────────────────────────────────────────── */
function managerFormatter(this: GridCell): string {
  return this.value ? escapeHtml(titleCase(String(this.value))) : "—";
}

function sharesFormatter(this: GridCell): string {
  const q = num(this.value);
  return q === null ? "—" : escapeHtml(formatNumber(q, 0));
}

function valueFormatter(this: GridCell): string {
  return escapeHtml(compactUsd(num(this.value)));
}

function pctFormatter(this: GridCell): string {
  const p = num(this.value);
  return p === null ? "—" : escapeHtml(formatPercent(p, 2));
}

/** ISO date -> calendar quarter label: "2023-12-31" -> "Q4 '23". */
function quarterLabel(d: string): string {
  const [y, m] = d.split("-");
  if (!y || !m) return d;
  return `Q${Math.ceil(Number(m) / 3)} '${y.slice(2)}`;
}

function returnFormatter(this: GridCell): string {
  const r = num(this.value);
  if (r === null) return '<span class="text-text-muted">—</span>';
  const entry = this.row.getCell("entry_date")?.value;
  const title = entry
    ? ` title="Stock return since this holder's entry quarter (${quarterLabel(String(entry))})"`
    : "";
  return `<span class="${toneClass(r)}"${title}>${escapeHtml(formatPercent(r, 1, { signed: true }))}</span>`;
}

/* ── columns + data ───────────────────────────────────────────────── */
export function holdersGridColumns(): GridColumns {
  // Wider primary column for hierarchy; the four numeric columns are narrow and
  // fixed so the Holder name absorbs the remaining width.
  return [
    { id: "manager", header: { format: "Holder" }, className: "ix-grid-cell-text", cells: { formatter: managerFormatter } },
    { id: "shares", header: { format: "Shares" }, width: 130, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: sharesFormatter } },
    { id: "market_value", header: { format: "Market value" }, width: 130, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: valueFormatter } },
    { id: "pct", header: { format: "% of Shares" }, width: 110, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: pctFormatter } },
    { id: "position_return", header: { format: "Return" }, width: 100, className: "ix-grid-cell-num", dataType: "number", cells: { formatter: returnFormatter } },
    { id: "entry_date", enabled: false },
    { id: "cik", enabled: false },
  ];
}

/** Case-insensitive match against the search box (holder name). */
function matchesSearch(name: string, q: string): boolean {
  const needle = q.trim().toLowerCase();
  return !needle || name.toLowerCase().includes(needle);
}

export function holdersGridData(
  data: StockHolders,
  opts: { search?: string } = {},
): LocalGridData {
  let rows = data.holders;
  if (opts.search) rows = rows.filter((h) => matchesSearch(h.manager_name, opts.search!));
  return {
    providerType: "local",
    columns: {
      manager: rows.map((h) => h.manager_name),
      shares: rows.map((h) => h.shares),
      market_value: rows.map((h) => h.market_value),
      // % of shares outstanding (ownership), computed by the backend.
      pct: rows.map((h) => h.pct_outstanding),
      position_return: rows.map((h) => h.position_return),
      entry_date: rows.map((h) => h.entry_date),
      cik: rows.map((h) => h.cik),
    },
  };
}

export function countMatchingHolders(data: StockHolders, search?: string): number {
  return search ? data.holders.filter((h) => matchesSearch(h.manager_name, search)).length : data.holders.length;
}

export function holdersToGridOptions(
  data: StockHolders,
  view: { search?: string } = {},
): Options {
  return {
    rendering: { theme: GRAPHITE_THEME, rows: { virtualization: true, strictHeights: false } },
    columnDefaults: { sorting: { enabled: true } },
    columns: holdersGridColumns(),
    data: holdersGridData(data, view),
  };
}
