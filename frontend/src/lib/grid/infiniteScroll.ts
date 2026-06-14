/**
 * Pure helpers for infinite-windowed virtual scrolling (Task C). No React, no
 * DOM — unit-tested. The hook (`useInfiniteGrid`) and the views compose these.
 *
 * The page-param contract mirrors TanStack Query's `getNextPageParam`:
 * pages are 1-based; the next page is `allPages.length + 1` as long as fewer
 * rows than `total` have been loaded. When the loaded count reaches (or
 * exceeds) `total`, return `undefined` to stop fetching.
 */

/** Anything paged by our endpoints exposes a numeric `total`. */
export interface PagedTotal {
  total: number;
}

/**
 * Total rows loaded so far across every fetched page.
 *
 * @param pages   The pages fetched so far (in order).
 * @param countOf Extracts the row count contributed by one page.
 */
export function loadedCount<TPage>(
  pages: readonly TPage[],
  countOf: (page: TPage) => number,
): number {
  return pages.reduce((sum, page) => sum + countOf(page), 0);
}

/**
 * The 1-based page param to fetch next, or `undefined` when the full set is
 * loaded. Robust to a server `total` that drifts below the loaded count
 * (e.g. rows deleted between requests) — it never asks for more than `total`.
 *
 * Assumes deterministic, non-empty paging: the backend keeps returning rows
 * until `loaded >= total`. An empty mid-stream page would not advance `loaded`,
 * so this would keep requesting the next index (the server is the stop guard).
 *
 * @param lastPage The most recently fetched page (carries the live `total`).
 * @param allPages Every page fetched so far (its length is the next index).
 * @param countOf  Extracts the row count contributed by one page.
 */
export function nextPageParam<TPage extends PagedTotal>(
  lastPage: TPage,
  allPages: readonly TPage[],
  countOf: (page: TPage) => number,
): number | undefined {
  const loaded = loadedCount(allPages, countOf);
  return loaded < lastPage.total ? allPages.length + 1 : undefined;
}

/**
 * Whether a scroll container is within `threshold` pixels of its bottom.
 * Pure arithmetic over the three scroll metrics so it can be unit-tested
 * without a DOM. `threshold` is the trigger distance (px) from the bottom.
 */
export function isNearBottom(
  metrics: { scrollTop: number; clientHeight: number; scrollHeight: number },
  threshold: number,
): boolean {
  const { scrollTop, clientHeight, scrollHeight } = metrics;
  return scrollTop + clientHeight >= scrollHeight - threshold;
}
