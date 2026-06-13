"use client";

/**
 * `useInfiniteGrid` — generic infinite-windowed loader for the list views
 * (funds + screener). Wraps TanStack Query's `useInfiniteQuery` over the
 * existing paged endpoints and exposes the concatenated pages plus the
 * fetch-next controls the grid wiring needs.
 *
 * Design notes (Task C):
 * - Every page carries the live `total`; `getNextPageParam` (the pure
 *   `nextPageParam` helper) stops once `loadedCount >= total`.
 * - The caller folds sort/dir/filters/search into `queryKey`, so any of those
 *   changing RESETS the infinite query to page 1 automatically — no manual
 *   page state. The grid's virtualization renders only the visible window even
 *   though we hand it ALL loaded rows.
 * - `placeholderData: keepPreviousData` + `staleTime: 30_000` + `retry` mirror
 *   the previous single-page `useQuery` calls so behaviour is unchanged apart
 *   from accumulation.
 */
import {
  keepPreviousData,
  useInfiniteQuery,
  type QueryKey,
} from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";
import type { Grid } from "@highcharts/grid-pro";

import { retryPolicy } from "@/components/screener/shared";
import {
  isNearBottom,
  loadedCount as sumLoaded,
  nextPageParam,
  type PagedTotal,
} from "@/lib/grid/infiniteScroll";

/** Distance (px) from the bottom of the body that triggers the next fetch. */
// ~3 row-heights of prefetch lead so the next page lands before the user hits bottom.
const NEAR_BOTTOM_PX = 320;

export interface UseInfiniteGridParams<TPage extends PagedTotal> {
  /** Stable cache key — include sort/dir/filters/search so changes reset to page 1. */
  queryKey: QueryKey;
  /** Fetch one page (1-based) with an abort signal. */
  fetchPage: (page: number, signal: AbortSignal) => Promise<TPage>;
  /** Row count contributed by one page (`p.rows.length` or `p.items.length`). */
  countOf: (page: TPage) => number;
  /** Disable until prerequisites are ready (e.g. a screen id). Default: enabled. */
  enabled?: boolean;
}

export interface UseInfiniteGridResult<TPage extends PagedTotal> {
  /** Pages in fetch order (each retains its own `total`/metadata). */
  pages: TPage[];
  /** The most recent page — source of stable columns/metadata for the adapter. */
  lastPage: TPage | undefined;
  /** Server-reported grand total across all pages. */
  total: number;
  /** Rows accumulated so far across every loaded page. */
  loadedCount: number;
  fetchNextPage: () => void;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  isFetching: boolean;
  refetch: () => void;
}

/**
 * Wrap `useInfiniteQuery` for a paged list endpoint. `TPage` is the raw page
 * payload (e.g. `FundsList` / `ScreenResults`); the caller merges the flattened
 * rows into the page shape its adapter expects.
 */
export function useInfiniteGrid<TPage extends PagedTotal>(
  params: UseInfiniteGridParams<TPage>,
): UseInfiniteGridResult<TPage> {
  const { queryKey, fetchPage, countOf, enabled = true } = params;

  const query = useInfiniteQuery<TPage, Error>({
    queryKey,
    queryFn: ({ pageParam, signal }) => fetchPage(pageParam as number, signal),
    initialPageParam: 1,
    getNextPageParam: (lastPage, allPages) =>
      nextPageParam(lastPage, allPages, countOf),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: retryPolicy,
    enabled,
  });

  const pages = useMemo(() => query.data?.pages ?? [], [query.data]);
  const lastPage = pages.length > 0 ? pages[pages.length - 1] : undefined;
  const total = lastPage?.total ?? 0;
  const loaded = useMemo(() => sumLoaded(pages, countOf), [pages, countOf]);

  return {
    pages,
    lastPage,
    total,
    loadedCount: loaded,
    fetchNextPage: () => void query.fetchNextPage(),
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isPending: query.isPending,
    isError: query.isError,
    error: query.error,
    isFetching: query.isFetching,
    refetch: () => void query.refetch(),
  };
}

/**
 * Returns a stable `onReady(grid)` handler for `<DataGrid onReady>` that wires a
 * passive `scroll` listener on the grid body (`viewport.tbodyElement`). When the
 * user scrolls near the bottom and there's another page (and we're not already
 * fetching), it triggers `fetchNextPage`. This is the AUTOMATIC trigger; the
 * "Load more" button remains the guaranteed fallback.
 *
 * The listener is bound once per grid `onReady` call and reads the latest
 * `{ hasNextPage, isFetchingNextPage, fetchNextPage }` through a ref, so it
 * always sees fresh values without rebinding. Every access to
 * `grid.viewport?.tbodyElement` is guarded; the previous listener is removed
 * before a new one is attached (DataGrid re-calls `onReady` after each update,
 * which may rebuild the tbody) and on unmount.
 */
export function useGridInfiniteScroll(controls: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
}): (grid: Grid) => void {
  const controlsRef = useRef(controls);
  controlsRef.current = controls;

  // Track the currently-bound element + handler so we can detach on re-ready.
  const boundRef = useRef<{ el: HTMLElement; handler: () => void } | null>(null);

  const detach = useCallback(() => {
    const bound = boundRef.current;
    if (bound) {
      bound.el.removeEventListener("scroll", bound.handler);
      boundRef.current = null;
    }
  }, []);

  const onReady = useCallback(
    (grid: Grid) => {
      const el = grid.viewport?.tbodyElement;
      if (!el) return;
      // Re-ready on the same tbody → nothing to do; on a rebuilt tbody → rebind.
      if (boundRef.current?.el === el) return;
      detach();

      const handler = () => {
        const { hasNextPage, isFetchingNextPage, fetchNextPage } =
          controlsRef.current;
        if (!hasNextPage || isFetchingNextPage) return;
        const metrics = {
          scrollTop: el.scrollTop,
          clientHeight: el.clientHeight,
          scrollHeight: el.scrollHeight,
        };
        if (isNearBottom(metrics, NEAR_BOTTOM_PX)) fetchNextPage();
      };
      el.addEventListener("scroll", handler, { passive: true });
      boundRef.current = { el, handler };
    },
    [detach],
  );

  // Clean up on unmount.
  useEffect(() => detach, [detach]);

  return onReady;
}
