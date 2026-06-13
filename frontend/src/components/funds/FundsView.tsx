"use client";

/**
 * Funds universe (F8.2) — server-driven dense table over GET /funds:
 * filter panel (search debounce, type/asset-class selects, free-text
 * strategy, numeric bounds), header-click sorting, infinite-windowed
 * scrolling and CSV export. The frontend formats; the backend
 * filters/sorts/pages — every metric is the mother-DB value (never
 * recomputed here).
 *
 * Scope (Task C): rows load incrementally as the user scrolls the virtualized
 * grid near the bottom; a "Load more" button is the always-present a11y +
 * safety-net fallback. Filters/sort live in the query key, so any change resets
 * the infinite query to page 1.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchFunds,
  fetchFundsCsv,
  type FundsList,
  type FundsQuery,
} from "@/lib/api/client";
import { DataGrid } from "@/components/ui/DataGrid";
import { GridSkeleton } from "@/components/ui/GridSkeleton";
import { LoadMoreFooter } from "@/components/ui/LoadMoreFooter";
import { fundsListToGridOptions } from "@/lib/grid/fundsGridOptions";
import {
  useGridInfiniteScroll,
  useInfiniteGrid,
} from "@/lib/grid/useInfiniteGrid";
import { PageTitle } from "@/components/ui/panels";
import {
  BUTTON_CLASS,
  ErrorPanel,
  FIELD_LABEL_CLASS,
  INPUT_CLASS,
} from "@/components/screener/shared";
import { formatCompact, formatDate } from "@/lib/format";

const PAGE_SIZE = 100;
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

  // Debounce free-text filters; the debounced values feed the query key below,
  // so any filter change restarts the infinite query at page 1.
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

  // Infinite-windowed loader: filters/sort live in the key, so any change
  // restarts at page 1. Virtualization renders only the visible window.
  const fundsQuery = useInfiniteGrid({
    queryKey: ["funds", filterKey],
    fetchPage: (page, signal) =>
      fetchFunds({ ...query, page, page_size: PAGE_SIZE }, signal),
    countOf: (p) => p.items.length,
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

  // The grid toggles internally and reports the resulting order via afterSort;
  // we just apply it (which re-keys the query → resets to page 1). Setters are
  // stable, so [] deps are correct.
  const onSortChange = useCallback((code: string, nextDir: SortDir) => {
    setSort(code);
    setDir(nextDir);
  }, []);

  // Merge all loaded pages' items; the last page carries canonical metadata
  // (total, staleness, classification_note).
  const lastPage = fundsQuery.lastPage;
  const mergedItems = useMemo(
    () => fundsQuery.pages.flatMap((p) => p.items),
    [fundsQuery.pages],
  );
  const mergedData: FundsList | undefined = lastPage
    ? { ...lastPage, items: mergedItems }
    : undefined;

  const meta = lastPage
    ? `${formatCompact(lastPage.total)} funds${
        lastPage.staleness.source_calc_date
          ? ` · data as of ${formatDate(lastPage.staleness.source_calc_date)}`
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
        <div aria-busy="true" aria-label="Loading funds">
          <GridSkeleton className="h-[420px]" />
        </div>
      ) : fundsQuery.isError ? (
        <ErrorPanel
          title="Failed to load funds"
          message={fundsQuery.error?.message ?? "Unknown error"}
          onRetry={() => fundsQuery.refetch()}
        />
      ) : mergedData === undefined ? null : (
        <FundsTable
          data={mergedData}
          loadedCount={fundsQuery.loadedCount}
          sort={sort}
          dir={dir}
          onSortChange={onSortChange}
          isFetching={fundsQuery.isFetching}
          hasNextPage={fundsQuery.hasNextPage}
          isFetchingNextPage={fundsQuery.isFetchingNextPage}
          fetchNextPage={fundsQuery.fetchNextPage}
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
  loadedCount,
  sort,
  dir,
  onSortChange,
  isFetching,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  exporting,
  exportError,
  onExport,
}: {
  data: FundsList;
  loadedCount: number;
  sort: string;
  dir: SortDir;
  onSortChange: (code: string, dir: SortDir) => void;
  isFetching: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
  exporting: boolean;
  exportError: string | null;
  onExport: () => void;
}) {
  const { total } = data;
  const gridOptions = useMemo(
    () => fundsListToGridOptions(data, { sort, dir }, { onSortChange }),
    [data, sort, dir, onSortChange],
  );

  // Automatic near-bottom trigger; the "Load more" button is the fallback.
  const onGridReady = useGridInfiniteScroll({
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  });

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

      <div className={`transition-opacity ${isFetching ? "opacity-60" : ""}`}>
        <DataGrid
          options={gridOptions}
          className="h-[600px] w-full"
          onReady={onGridReady}
          emptyMessage="No funds match the current filters."
        />
      </div>

      {data.classification_note && (
        <p className="border-t border-border px-[var(--ix-pad)] py-2 text-[11px] text-text-muted">
          {data.classification_note}
        </p>
      )}

      <LoadMoreFooter
        loaded={loadedCount}
        total={total}
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        onLoadMore={fetchNextPage}
      />
    </section>
  );
}
