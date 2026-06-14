"use client";

/**
 * Footer for infinite-windowed list views (Task C): a "loaded X of N" indicator
 * plus an always-present "Load more" button. The button is the a11y + safety-net
 * fallback for the automatic near-bottom scroll trigger — it must work
 * regardless of grid internals, so it depends only on the query controls.
 */
import { formatCompact } from "@/lib/format";

export function LoadMoreFooter({
  loaded,
  total,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: {
  loaded: number;
  total: number;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}) {
  const allLoaded = !hasNextPage;
  return (
    <div className="flex flex-wrap items-center gap-2.5 border-t border-border px-[var(--ix-pad)] py-2.5 text-[12px] text-text-secondary">
      <span className="tabular-nums" aria-live="polite">
        {total === 0
          ? "0 rows"
          : `Loaded ${formatCompact(loaded)} of ${formatCompact(total)}`}
      </span>
      {/* On an empty result the empty-state overlay covers the grid, so a
          disabled "All loaded" button reads oddly — show only the count. */}
      {total > 0 && (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={allLoaded || isFetchingNextPage}
          aria-label="Load more rows"
          className="ml-auto flex h-[30px] items-center px-3 tabular-nums bg-field border border-border-strong text-text-secondary transition-colors hover:bg-layer-hover disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-field"
        >
          {isFetchingNextPage
            ? "Loading…"
            : allLoaded
              ? "All loaded"
              : "Load more"}
        </button>
      )}
    </div>
  );
}
