"use client";

/**
 * Results tab — server-driven results table: dynamic columns from the
 * response, header-click sorting, prefix search and infinite-windowed
 * scrolling. The frontend formats; the backend filters/sorts/pages. The match
 * count and CSV export live in the persistent ScreenerHeader, so this tab only
 * reports its total upward via `onHeadline`.
 *
 * Rows load incrementally as the user scrolls the virtualized grid near the
 * bottom; a "Load more" button is the always-present a11y + safety-net fallback
 * (works regardless of grid internals). Sort/search live in the query key, so
 * changing either resets the infinite query to page 1.
 */
import { useEffect, useMemo, useState } from "react";

import { fetchScreenResults } from "@/lib/api/client";
import {
  ErrorPanel,
  INPUT_CLASS,
  isSnapshotMissing,
  NO_DATA_NOTE,
} from "@/components/screener/shared";
import { DataGrid } from "@/components/ui/DataGrid";
import { GridSkeleton } from "@/components/ui/GridSkeleton";
import { LoadMoreFooter } from "@/components/ui/LoadMoreFooter";
import { screenResultsToGridOptions } from "@/lib/grid/gridOptions";
import {
  useGridInfiniteScroll,
  useInfiniteGrid,
} from "@/lib/grid/useInfiniteGrid";

const PAGE_SIZE = 100;
type SortDir = "asc" | "desc";

export function ResultsTab({
  screenId,
  onHeadline,
}: {
  screenId: number;
  onHeadline: (count: number | null) => void;
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

  useEffect(() => {
    onHeadline(resultsQuery.isPending ? null : resultsQuery.total);
  }, [resultsQuery.isPending, resultsQuery.total, onHeadline]);

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
        <div className="relative w-[220px]">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M11 11l4 4" stroke="currentColor" strokeWidth="1.4" />
          </svg>
          <input value={searchText} onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search ticker / name…" aria-label="Search results by ticker or name"
            className={`w-full pl-[30px] ${INPUT_CLASS} text-[12px]`} />
        </div>
      </div>

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
