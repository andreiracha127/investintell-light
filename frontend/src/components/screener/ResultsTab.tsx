"use client";

/**
 * Wizard Tab 3 — server-driven results table: dynamic columns from the
 * response, header-click sorting, prefix search, infinite-windowed scrolling
 * and CSV export (fetch + blob through the typed client so base-URL handling
 * stays consistent). The frontend formats; the backend filters/sorts/pages.
 *
 * Scope (Task C): rows load incrementally as the user scrolls the virtualized
 * grid near the bottom; a "Load more" button is the always-present a11y +
 * safety-net fallback (works regardless of grid internals). Sort/search live
 * in the query key, so changing either resets the infinite query to page 1.
 */
import { useEffect, useMemo, useState } from "react";

import { fetchScreenResults, fetchScreenResultsCsv } from "@/lib/api/client";
import {
  BUTTON_CLASS,
  ErrorPanel,
  INPUT_CLASS,
  isSnapshotMissing,
  NO_DATA_NOTE,
} from "@/components/screener/shared";
import { DataGrid } from "@/components/ui/DataGrid";
import { GridSkeleton } from "@/components/ui/GridSkeleton";
import { LoadMoreFooter } from "@/components/ui/LoadMoreFooter";
import { formatCompact } from "@/lib/format";
import { screenResultsToGridOptions } from "@/lib/grid/gridOptions";
import {
  useGridInfiniteScroll,
  useInfiniteGrid,
} from "@/lib/grid/useInfiniteGrid";

const PAGE_SIZE = 100;
type SortDir = "asc" | "desc";

export function ResultsTab({
  screenId,
  screenName,
}: {
  screenId: number;
  screenName: string;
}) {
  const [sort, setSort] = useState<string | undefined>(undefined);
  const [dir, setDir] = useState<SortDir>("asc");
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");

  // Debounce the server-side search. A search change re-keys the infinite
  // query below, which resets it to page 1 automatically (no page state).
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchText.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchText]);

  // Infinite-windowed loader: sort/dir/search live in the key, so any change
  // restarts at page 1. Virtualization renders only the visible window.
  const resultsQuery = useInfiniteGrid({
    queryKey: ["screen-results", screenId, sort ?? "", dir, search],
    fetchPage: (page, signal) =>
      fetchScreenResults(
        screenId,
        {
          ...(sort !== undefined && { sort }),
          dir,
          ...(search !== "" && { search }),
          page,
          page_size: PAGE_SIZE,
        },
        signal,
      ),
    countOf: (p) => p.rows.length,
  });

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const exportCsv = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const blob = await fetchScreenResultsCsv(screenId, {
        ...(sort !== undefined && { sort }),
        dir,
        ...(search !== "" && { search }),
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${screenName.replace(/[^\w.-]+/g, "_")}-results.csv`;
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

  const { lastPage, pages, total, loadedCount } = resultsQuery;
  // Feed the grid a ScreenResults whose `.rows` is ALL loaded rows (columns are
  // stable across pages, so the last page's metadata is canonical).
  const mergedRows = useMemo(
    () => pages.flatMap((p) => p.rows),
    [pages],
  );
  const gridOptions = useMemo(
    () =>
      lastPage
        ? screenResultsToGridOptions(
            { ...lastPage, rows: mergedRows },
            { sort, dir },
            {
              onSortChange: (columnId, order) => {
                setSort(columnId);
                setDir(order);
              },
            },
          )
        : null,
    [lastPage, mergedRows, sort, dir],
  );

  // Automatic near-bottom trigger; the "Load more" button is the fallback.
  const onGridReady = useGridInfiniteScroll({
    hasNextPage: resultsQuery.hasNextPage,
    isFetchingNextPage: resultsQuery.isFetchingNextPage,
    fetchNextPage: resultsQuery.fetchNextPage,
  });

  if (resultsQuery.isPending) {
    return (
      <div aria-busy="true" aria-label="Loading screen results">
        <GridSkeleton className="h-[320px]" />
      </div>
    );
  }
  if (resultsQuery.isError) {
    return isSnapshotMissing(resultsQuery.error) ? (
      <div className="bg-surface-2 border border-border px-6 py-10 text-center text-[13px] text-text-muted">
        {NO_DATA_NOTE}
      </div>
    ) : (
      <ErrorPanel
        title="Failed to load results"
        message={resultsQuery.error?.message ?? "Unknown error"}
        onRetry={() => resultsQuery.refetch()}
      />
    );
  }

  return (
    <section className="bg-surface-2 border border-border">
      <div className="flex flex-wrap items-center gap-2.5 px-[var(--ix-pad)] py-3">
        <h2 className="ix-label m-0">Results</h2>
        <span className="inline-flex h-[22px] items-center bg-accent-wash border border-accent px-2 tabular-nums text-[11px] font-bold text-accent">
          {formatCompact(total)} matches
        </span>
        <div className="relative ml-auto w-[200px]">
          <svg
            width="13"
            height="13"
            viewBox="0 0 16 16"
            fill="none"
            aria-hidden="true"
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted"
          >
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M11 11l4 4" stroke="currentColor" strokeWidth="1.4" />
          </svg>
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search ticker / name…"
            aria-label="Search results by ticker or name"
            className={`w-full pl-[30px] ${INPUT_CLASS} text-[12px]`}
          />
        </div>
        <button
          type="button"
          onClick={() => void exportCsv()}
          disabled={exporting}
          aria-label="Export results as CSV"
          className={`${BUTTON_CLASS} inline-flex items-center gap-[7px] text-[12px]`}
        >
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path
              d="M8 1v9M4.5 7L8 10.5 11.5 7M2 14h12"
              stroke="currentColor"
              strokeWidth="1.3"
            />
          </svg>
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>

      {exportError && (
        <p role="alert" className="px-[var(--ix-pad)] pb-2 text-[12px] text-loss break-words">
          {exportError}
        </p>
      )}

      <div
        className={`transition-opacity ${resultsQuery.isFetching ? "opacity-60" : ""}`}
      >
        {gridOptions && (
          <DataGrid
            options={gridOptions}
            className="h-[560px] w-full"
            onReady={onGridReady}
            emptyMessage={
              total === 0 && search
                ? `No matches for "${search}".`
                : "No matches — loosen the filters, or the metrics snapshot may not be computed yet."
            }
          />
        )}
      </div>

      <LoadMoreFooter
        loaded={loadedCount}
        total={total}
        hasNextPage={resultsQuery.hasNextPage}
        isFetchingNextPage={resultsQuery.isFetchingNextPage}
        onLoadMore={resultsQuery.fetchNextPage}
      />
    </section>
  );
}
