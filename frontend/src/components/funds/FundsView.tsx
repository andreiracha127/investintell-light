"use client";

/**
 * Funds universe (F8.2) — server-driven dense table over GET /funds:
 * filter panel (search debounce, type/asset-class selects, free-text
 * strategy, numeric bounds), header-click sorting, square pagination and
 * CSV export. The frontend formats; the backend filters/sorts/paginates —
 * every metric is the mother-DB value (never recomputed here).
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  fetchFunds,
  fetchFundsCsv,
  type FundListItem,
  type FundsList,
  type FundsQuery,
} from "@/lib/api/client";
import { PageTitle } from "@/components/ui/panels";
import {
  BUTTON_CLASS,
  ErrorPanel,
  FIELD_LABEL_CLASS,
  INPUT_CLASS,
  retryPolicy,
} from "@/components/screener/shared";
import { formatCompact, formatDate, formatNumber, formatPercent } from "@/lib/format";

const PAGE_SIZE = 50;
type SortDir = "asc" | "desc";

type FundType = NonNullable<FundsQuery["fund_type"]>;
type AssetClass = NonNullable<FundsQuery["asset_class"]>;

const FUND_TYPES: { value: FundType; label: string }[] = [
  { value: "etf", label: "ETF" },
  { value: "mutual_fund", label: "Mutual fund" },
  { value: "mmf", label: "Money market" },
];

const ASSET_CLASSES: { value: AssetClass; label: string }[] = [
  { value: "equity", label: "Equity" },
  { value: "fixed_income", label: "Fixed income" },
  { value: "cash", label: "Cash" },
  { value: "alternatives", label: "Alternatives" },
];

const TYPE_TAG: Record<string, string> = {
  etf: "ETF",
  mutual_fund: "MF",
  mmf: "MMF",
};

// Backend stores the raw enum (equity/fixed_income/...); the table must show
// the same labels the filter dropdown uses.
const ASSET_CLASS_LABEL: Record<string, string> = Object.fromEntries(
  ASSET_CLASSES.map((a) => [a.value, a.label]),
);

/** Sortable table columns — code is the backend whitelist column. */
const COLUMNS: { code: string; label: string; numeric: boolean }[] = [
  { code: "ticker", label: "Ticker", numeric: false },
  { code: "name", label: "Name", numeric: false },
  { code: "fund_type", label: "Type", numeric: false },
  { code: "strategy_label", label: "Strategy", numeric: false },
  { code: "asset_class", label: "Asset class", numeric: false },
  { code: "aum_usd", label: "AUM", numeric: true },
  { code: "expense_ratio", label: "Expense", numeric: true },
  { code: "return_1y", label: "Return 1Y", numeric: true },
  { code: "volatility_1y", label: "Vol 1Y", numeric: true },
  { code: "sharpe_1y", label: "Sharpe 1Y", numeric: true },
  { code: "peer_sharpe_pctl", label: "Peer pctl", numeric: true },
  { code: "elite_flag", label: "Elite", numeric: true },
];

/** Parse a non-empty numeric input; invalid/blank -> undefined (no filter). */
function parseBound(text: string): number | undefined {
  if (text.trim() === "") return undefined;
  const value = Number(text);
  return Number.isFinite(value) ? value : undefined;
}

export function FundsView() {
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [fundType, setFundType] = useState<FundType | "">("");
  const [assetClass, setAssetClass] = useState<AssetClass | "">("");
  const [strategyText, setStrategyText] = useState("");
  const [strategy, setStrategy] = useState("");
  // Bound inputs in UI units: expense %, AUM $M, Sharpe raw, Vol %.
  const [expenseMaxPct, setExpenseMaxPct] = useState("");
  const [aumMinM, setAumMinM] = useState("");
  const [sharpeMin, setSharpeMin] = useState("");
  const [volMaxPct, setVolMaxPct] = useState("");
  const [sort, setSort] = useState("aum_usd");
  const [dir, setDir] = useState<SortDir>("desc");
  const [page, setPage] = useState(1);

  // Debounce free-text filters; any filter change restarts at page 1.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchText.trim());
      setStrategy(strategyText.trim());
    }, 300);
    return () => clearTimeout(timer);
  }, [searchText, strategyText]);

  const expenseMax = parseBound(expenseMaxPct);
  const aumMin = parseBound(aumMinM);
  const sharpe = parseBound(sharpeMin);
  const volMax = parseBound(volMaxPct);

  const query: FundsQuery = {
    ...(search !== "" && { search }),
    ...(fundType !== "" && { fund_type: fundType }),
    ...(assetClass !== "" && { asset_class: assetClass }),
    ...(strategy !== "" && { strategy_label: strategy }),
    // UI percent -> backend decimal fraction; $M -> USD.
    ...(expenseMax !== undefined && { expense_ratio_max: expenseMax / 100 }),
    ...(aumMin !== undefined && { aum_min: aumMin * 1e6 }),
    ...(sharpe !== undefined && { sharpe_1y_min: sharpe }),
    ...(volMax !== undefined && { volatility_1y_max: volMax / 100 }),
    sort,
    dir,
  };
  const filterKey = JSON.stringify(query);
  useEffect(() => {
    setPage(1);
  }, [filterKey]);

  const fundsQuery = useQuery({
    queryKey: ["funds", filterKey, page],
    queryFn: ({ signal }) =>
      fetchFunds({ ...query, page, page_size: PAGE_SIZE }, signal),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: retryPolicy,
  });

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const exportCsv = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const blob = await fetchFundsCsv(query);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "funds.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };

  const onSort = (code: string) => {
    if (sort === code) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSort(code);
      setDir(code === "ticker" || code === "name" ? "asc" : "desc");
    }
    setPage(1);
  };

  const data = fundsQuery.data;
  const meta = data
    ? `${formatCompact(data.total)} funds${
        data.staleness.source_calc_date
          ? ` · data as of ${formatDate(data.staleness.source_calc_date)}`
          : ""
      }`
    : "—";

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-5">
      <PageTitle title="Funds" meta={meta} />

      {/* ── Filters ─────────────────────────────────────────────────────── */}
      <section className="mb-4 border border-border bg-surface-2 px-[var(--ix-pad)] py-3">
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(160px,1fr))]">
          <label className="flex flex-col gap-1">
            <span className={FIELD_LABEL_CLASS}>Search</span>
            <input
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Ticker / name…"
              aria-label="Search funds by ticker or name"
              className={INPUT_CLASS}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={FIELD_LABEL_CLASS}>Type</span>
            <select
              value={fundType}
              onChange={(e) => setFundType(e.target.value as FundType | "")}
              aria-label="Fund type"
              className={INPUT_CLASS}
            >
              <option value="">All</option>
              {FUND_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className={FIELD_LABEL_CLASS}>Asset class</span>
            <select
              value={assetClass}
              onChange={(e) => setAssetClass(e.target.value as AssetClass | "")}
              aria-label="Asset class"
              className={INPUT_CLASS}
            >
              <option value="">All</option>
              {ASSET_CLASSES.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className={FIELD_LABEL_CLASS}>Strategy</span>
            <input
              value={strategyText}
              onChange={(e) => setStrategyText(e.target.value)}
              placeholder="e.g. Large Cap"
              aria-label="Strategy label contains"
              className={INPUT_CLASS}
            />
          </label>
          <BoundField
            label="Expense ≤ %"
            value={expenseMaxPct}
            onChange={setExpenseMaxPct}
            placeholder="0.50"
          />
          <BoundField
            label="AUM ≥ $M"
            value={aumMinM}
            onChange={setAumMinM}
            placeholder="100"
          />
          <BoundField
            label="Sharpe 1Y ≥"
            value={sharpeMin}
            onChange={setSharpeMin}
            placeholder="0.5"
          />
          <BoundField
            label="Vol 1Y ≤ %"
            value={volMaxPct}
            onChange={setVolMaxPct}
            placeholder="20"
          />
        </div>
      </section>

      {/* ── Table ───────────────────────────────────────────────────────── */}
      {fundsQuery.isPending ? (
        <div
          aria-busy="true"
          aria-label="Loading funds"
          className="h-[420px] bg-surface-2 animate-pulse"
        />
      ) : fundsQuery.isError ? (
        <ErrorPanel
          title="Failed to load funds"
          message={fundsQuery.error.message}
          onRetry={() => fundsQuery.refetch()}
        />
      ) : data === undefined ? null : (
        <FundsTable
          data={data}
          page={page}
          setPage={setPage}
          sort={sort}
          dir={dir}
          onSort={onSort}
          isFetching={fundsQuery.isFetching}
          exporting={exporting}
          exportError={exportError}
          onExport={() => void exportCsv()}
        />
      )}
    </div>
  );
}

function BoundField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className={FIELD_LABEL_CLASS}>{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        inputMode="decimal"
        aria-label={label}
        className={`${INPUT_CLASS} tabular-nums`}
      />
    </label>
  );
}

function FundsTable({
  data,
  page,
  setPage,
  sort,
  dir,
  onSort,
  isFetching,
  exporting,
  exportError,
  onExport,
}: {
  data: FundsList;
  page: number;
  setPage: (updater: (p: number) => number) => void;
  sort: string;
  dir: SortDir;
  onSort: (code: string) => void;
  isFetching: boolean;
  exporting: boolean;
  exportError: string | null;
  onExport: () => void;
}) {
  const { items, total } = data;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const firstRow = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastRow = Math.min(page * PAGE_SIZE, total);

  return (
    <section className="bg-surface-2 border border-border">
      <div className="flex flex-wrap items-center gap-2.5 px-[var(--ix-pad)] py-3">
        <h2 className="ix-label m-0">Universe</h2>
        <span className="inline-flex h-[22px] items-center bg-accent-wash border border-accent px-2 tabular-nums text-[11px] font-bold text-accent">
          {formatCompact(total)} matches
        </span>
        <div className="ml-auto" />
        <button
          type="button"
          onClick={onExport}
          disabled={exporting}
          aria-label="Export funds as CSV"
          className={`${BUTTON_CLASS} inline-flex items-center gap-[7px] text-[12px]`}
        >
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M8 1v9M4.5 7L8 10.5 11.5 7M2 14h12" stroke="currentColor" strokeWidth="1.3" />
          </svg>
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>

      {exportError && (
        <p role="alert" className="px-[var(--ix-pad)] pb-2 text-[12px] text-loss break-words">
          {exportError}
        </p>
      )}

      <div className={`overflow-x-auto transition-opacity ${isFetching ? "opacity-60" : ""}`}>
        <table className="w-full min-w-[1080px] border-collapse ix-fs tabular-nums lining-nums">
          <thead>
            <tr className="bg-field">
              {COLUMNS.map((col) => {
                const active = sort === col.code;
                return (
                  <th
                    key={col.code}
                    className={`sticky top-0 whitespace-nowrap bg-field px-2.5 py-[9px] first:pl-[var(--ix-pad)] last:pr-[var(--ix-pad)] border-t border-t-border ${
                      col.numeric ? "text-right" : "text-left"
                    } ${
                      active
                        ? "border-b-2 border-b-accent font-bold text-accent"
                        : "border-b border-b-border-strong font-semibold text-text-secondary"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSort(col.code)}
                      aria-label={`Sort by ${col.label}`}
                      className={`whitespace-nowrap transition-colors ${
                        active ? "font-bold text-accent" : "font-semibold hover:text-text-primary"
                      }`}
                    >
                      {col.label}
                      {active && (
                        <span aria-hidden="true" className="ml-1">
                          {dir === "asc" ? "▲" : "▼"}
                        </span>
                      )}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {items.map((fund, i) => (
              <FundRow key={fund.instrument_id} fund={fund} zebra={i % 2 === 1} />
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className="py-6 text-center text-[13px] text-text-muted">
                  No funds match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 border-t border-border px-[var(--ix-pad)] py-2.5 text-[12px] text-text-secondary">
        <span className="tabular-nums">
          {total === 0 ? "0 rows" : `${firstRow}–${lastRow} of ${formatCompact(total)}`}
        </span>
        <span className="text-[11px] text-text-muted">{data.classification_note}</span>
        <div className="ml-auto flex items-center gap-px">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || isFetching}
            aria-label="Previous page"
            className="h-[30px] w-8 bg-field border border-border-strong text-text-secondary hover:bg-layer-hover transition-colors disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-field"
          >
            ‹
          </button>
          {pageWindow(page, totalPages).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPage(() => p)}
              disabled={isFetching}
              aria-label={`Page ${p}`}
              aria-current={p === page ? "page" : undefined}
              className={`flex h-[30px] items-center px-3 tabular-nums transition-colors ${
                p === page
                  ? "bg-accent border border-accent font-bold text-on-accent"
                  : "bg-field border border-border-strong text-text-secondary hover:bg-layer-hover"
              }`}
            >
              {p}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || isFetching}
            aria-label="Next page"
            className="h-[30px] w-8 bg-field border border-border-strong text-text-secondary hover:bg-layer-hover transition-colors disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-field"
          >
            ›
          </button>
        </div>
      </div>
    </section>
  );
}

/** Up to 5 page numbers centered on the current page — presentation only. */
function pageWindow(page: number, totalPages: number): number[] {
  const size = Math.min(5, totalPages);
  const start = Math.min(Math.max(1, page - 2), totalPages - size + 1);
  return Array.from({ length: size }, (_, i) => start + i);
}

const CELL_CLASS = "ix-cell px-2.5 first:pl-[var(--ix-pad)] last:pr-[var(--ix-pad)]";

function signTone(value: number): string {
  if (value > 0) return "font-bold text-gain";
  if (value < 0) return "font-bold text-loss";
  return "text-text-primary";
}

function FundRow({ fund, zebra }: { fund: FundListItem; zebra: boolean }) {
  const href = `/funds/${encodeURIComponent(fund.instrument_id)}`;
  return (
    <tr
      className={`border-b border-border transition-colors hover:bg-accent-wash ${
        zebra ? "bg-zebra" : ""
      }`}
    >
      <td className={CELL_CLASS}>
        <Link href={href} className="font-bold text-accent hover:underline">
          {fund.ticker ?? "—"}
        </Link>
      </td>
      <td className={`${CELL_CLASS} text-left`}>
        <Link href={href} className="text-text-primary no-underline hover:underline">
          <span className="block max-w-[280px] truncate">{fund.name}</span>
        </Link>
      </td>
      <td className={`${CELL_CLASS} text-left`}>
        <span className="inline-flex h-[18px] items-center border border-border-strong bg-field px-1.5 text-[10px] font-bold uppercase tracking-[0.05em] text-text-secondary">
          {TYPE_TAG[fund.fund_type] ?? fund.fund_type}
        </span>
      </td>
      <td className={`${CELL_CLASS} text-left text-text-secondary`}>
        <span className="block max-w-[200px] truncate">{fund.strategy_label}</span>
      </td>
      <td className={`${CELL_CLASS} text-left text-text-secondary`}>
        {fund.asset_class
          ? (ASSET_CLASS_LABEL[fund.asset_class] ?? fund.asset_class)
          : "—"}
      </td>
      <td className={`${CELL_CLASS} text-right`}>
        {fund.aum_usd !== null ? `$${formatCompact(fund.aum_usd)}` : "—"}
      </td>
      <td className={`${CELL_CLASS} text-right`}>
        {fund.expense_ratio !== null ? formatPercent(fund.expense_ratio) : "—"}
      </td>
      <td
        className={`${CELL_CLASS} text-right ${
          fund.return_1y !== null ? signTone(fund.return_1y) : "text-text-primary"
        }`}
      >
        {fund.return_1y !== null ? formatPercent(fund.return_1y, 2, { signed: true }) : "—"}
      </td>
      <td className={`${CELL_CLASS} text-right`}>
        {fund.volatility_1y !== null ? formatPercent(fund.volatility_1y) : "—"}
      </td>
      <td className={`${CELL_CLASS} text-right`}>
        {fund.sharpe_1y !== null ? formatNumber(fund.sharpe_1y) : "—"}
      </td>
      <td className={`${CELL_CLASS} text-right`}>
        {fund.peer_sharpe_pctl !== null ? (
          <span className="inline-flex items-center justify-end gap-1.5">
            <span className="relative inline-block h-[4px] w-[52px] bg-field border border-border">
              <span
                className="absolute inset-y-0 left-0 bg-accent"
                style={{ width: `${Math.min(100, Math.max(0, fund.peer_sharpe_pctl))}%` }}
              />
            </span>
            <span className="w-[26px] text-right">{formatNumber(fund.peer_sharpe_pctl, 0)}</span>
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className={`${CELL_CLASS} text-right`}>
        {fund.elite_flag ? (
          <svg
            width="13"
            height="13"
            viewBox="0 0 16 16"
            fill="none"
            aria-label="Elite fund"
            className="inline text-accent"
          >
            <path d="M2.5 8.5L6.5 12.5L13.5 4" stroke="currentColor" strokeWidth="2" />
          </svg>
        ) : (
          <span className="text-text-muted">—</span>
        )}
      </td>
    </tr>
  );
}
