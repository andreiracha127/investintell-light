/**
 * Pure adapter: StockFundHolders → Highcharts Grid Pro tree Options for the
 * Holders "by fund" view. Two-level parent-id TreeView (Family → Fund),
 * COLLAPSED by default. Parent rows aggregate market value; leaf rows show the
 * fund's shares, market value and % of NAV. Pure (no React/DOM).
 */
import type { Options } from "@highcharts/grid-pro";

import type { StockFundHolders } from "@/lib/api/client";
import { formatNumber, formatPercent } from "@/lib/format";
import { GRAPHITE_THEME } from "./gridOptions";
import { compactUsd, titleCase } from "./holdersGridOptions";

type GridColumns = NonNullable<Options["columns"]>;
type CellFormatter = NonNullable<NonNullable<GridColumns[number]["cells"]>["formatter"]>;
type GridCell = ThisParameterType<CellFormatter>;
type LocalGridData = Extract<NonNullable<Options["data"]>, { columns?: unknown }>;

interface TreeViewOptionsLocal {
  enabled?: boolean;
  input?: { type: "parentId"; parentIdColumn?: string };
  treeColumn?: string;
  expandedRowIds?: string[] | "all";
  stickyParents?: boolean;
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const num = (v: unknown): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);

function isGroupRow(cell: GridCell): boolean {
  return cell.row.getCell("isGroup")?.value === true;
}

/** Tree column: family in bold (title-cased, with fund count); fund name as a
 *  leaf, linked to its dossier when the fund is in the Light catalogue. */
function labelFormatter(this: GridCell): string {
  if (isGroupRow(this)) {
    const label = escapeHtml(titleCase(String(this.value ?? "—")));
    const n = this.row.getCell("fund_count")?.value;
    const badge = n ? ` <span class="ix-grid-name">(${escapeHtml(n)})</span>` : "";
    return `<span class="ix-grid-group">${label}</span>${badge}`;
  }
  const label = escapeHtml(titleCase(String(this.value ?? "—")));
  const id = this.row.getCell("instrument_id")?.value;
  if (id !== null && id !== undefined && id !== "") {
    return `<a class="ix-grid-link" href="/funds/${encodeURIComponent(String(id))}">${label}</a>`;
  }
  return `<span class="ix-grid-sub">${label}</span>`;
}

function sharesFormatter(this: GridCell): string {
  const q = num(this.value);
  return q === null ? "" : escapeHtml(formatNumber(q, 0));
}

function valueFormatter(this: GridCell): string {
  const v = num(this.value);
  if (v === null) return "—";
  const text = escapeHtml(compactUsd(v));
  return isGroupRow(this) ? `<span class="ix-grid-group">${text}</span>` : text;
}

/** % of the fund's NAV (percent points from the backend, e.g. 15.6). */
function navFormatter(this: GridCell): string {
  const v = num(this.value);
  if (v === null || isGroupRow(this)) return "";
  return escapeHtml(formatPercent(v / 100, 1));
}

function matches(s: string, q: string): boolean {
  return s.toLowerCase().includes(q.trim().toLowerCase());
}

export function fundHoldersTreeGridOptions(
  data: StockFundHolders,
  opts: { search?: string } = {},
): Options {
  const q = opts.search?.trim() ?? "";
  const id: string[] = [];
  const parentId: (string | null)[] = [];
  const label: string[] = [];
  const shares: (number | null)[] = [];
  const market_value: (number | null)[] = [];
  const pct_nav: (number | null)[] = [];
  const pct_nav_1: (number | null)[] = [];
  const pct_nav_2: (number | null)[] = [];
  const pct_nav_3: (number | null)[] = [];
  const fund_count: (number | null)[] = [];
  const instrument_id: (string | null)[] = [];
  const isGroup: boolean[] = [];

  // The grid's parent-id tree requires unique row ids; guard against any
  // duplicate family cik / series id from the source.
  const seen = new Set<string>();
  for (const fam of data.families) {
    const famMatch = !q || matches(fam.family, q);
    const funds = famMatch ? fam.funds : fam.funds.filter((f) => matches(f.fund_name, q));
    if (funds.length === 0) continue;
    const famId = `fam:${fam.registrant_cik}`;
    if (seen.has(famId)) continue;
    seen.add(famId);
    id.push(famId); parentId.push(null); label.push(fam.family);
    shares.push(null);
    market_value.push(famMatch ? fam.market_value : funds.reduce((s, f) => s + (f.market_value ?? 0), 0));
    pct_nav.push(null); pct_nav_1.push(null); pct_nav_2.push(null); pct_nav_3.push(null);
    fund_count.push(fam.fund_count); instrument_id.push(null); isGroup.push(true);
    for (const f of funds) {
      const fid = `fund:${f.series_id}`;
      if (seen.has(fid)) continue;
      seen.add(fid);
      id.push(fid); parentId.push(famId); label.push(f.fund_name);
      shares.push(f.quantity); market_value.push(f.market_value);
      pct_nav.push(f.pct_of_nav); pct_nav_1.push(f.pct_nav_q1);
      pct_nav_2.push(f.pct_nav_q2); pct_nav_3.push(f.pct_nav_q3);
      fund_count.push(null); instrument_id.push(f.instrument_id); isGroup.push(false);
    }
  }

  const dataBlock: LocalGridData & { treeView: TreeViewOptionsLocal; idColumn?: string } = {
    providerType: "local",
    idColumn: "id",
    columns: { id, parentId, label, shares, market_value, pct_nav, pct_nav_1, pct_nav_2, pct_nav_3, fund_count, instrument_id, isGroup },
    treeView: {
      enabled: true,
      input: { type: "parentId", parentIdColumn: "parentId" },
      treeColumn: "label",
      // Expand all when filtering so matches are visible; collapsed otherwise.
      expandedRowIds: q ? "all" : [],
    },
  };
  const columns: GridColumns = [
    { id: "label", header: { format: "Family / Fund" }, className: "ix-grid-cell-text", cells: { formatter: labelFormatter } },
    { id: "shares", header: { format: "Shares" }, width: 110, className: "ix-grid-cell-num", cells: { formatter: sharesFormatter } },
    { id: "market_value", header: { format: "Market value" }, width: 120, className: "ix-grid-cell-num", cells: { formatter: valueFormatter } },
    // Last 4 quarters of % of NAV — exposure trajectory (latest first).
    { id: "pct_nav", header: { format: "% NAV" }, width: 78, className: "ix-grid-cell-num", cells: { formatter: navFormatter } },
    { id: "pct_nav_1", header: { format: "Q -1" }, width: 70, className: "ix-grid-cell-num", cells: { formatter: navFormatter } },
    { id: "pct_nav_2", header: { format: "Q -2" }, width: 70, className: "ix-grid-cell-num", cells: { formatter: navFormatter } },
    { id: "pct_nav_3", header: { format: "Q -3" }, width: 70, className: "ix-grid-cell-num", cells: { formatter: navFormatter } },
    { id: "id", enabled: false },
    { id: "parentId", enabled: false },
    { id: "fund_count", enabled: false },
    { id: "instrument_id", enabled: false },
    { id: "isGroup", enabled: false },
  ];
  return {
    rendering: { theme: GRAPHITE_THEME, rows: { strictHeights: false } },
    columns,
    data: dataBlock,
  };
}
