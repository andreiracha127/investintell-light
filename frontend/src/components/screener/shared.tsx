"use client";

/**
 * Shared screener plumbing: input/button classes (Graphite tokens), the
 * standard retry policy, the fail-loud error panel, and the single place a
 * filter PUT/DELETE response is folded back into the query cache.
 */
import type { QueryClient } from "@tanstack/react-query";

import { ApiError, type FilterUpdateResponse } from "@/lib/api/client";

export const INPUT_CLASS =
  "px-2 py-1 rounded-[6px] bg-surface-1 border border-border text-[13px] " +
  "text-text-primary placeholder:text-text-muted focus:border-accent-muted focus:outline-none";

export const BUTTON_CLASS =
  "px-3 py-1 rounded-[6px] bg-surface-1 border border-border text-[12px] " +
  "text-text-secondary hover:text-text-primary hover:border-accent-muted " +
  "transition-colors disabled:opacity-40 disabled:cursor-not-allowed";

/** Shared retry policy: never retry 4xx (deterministic), retry 5xx/network twice. */
export const retryPolicy = (failureCount: number, err: Error) =>
  !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
  failureCount < 2;

/** The documented sparse-snapshot 422 ("metrics snapshot not computed yet"). */
export function isSnapshotMissing(err: unknown): boolean {
  return err instanceof ApiError && err.status === 422;
}

/** Muted note shown wherever the metrics snapshot has no data yet. */
export const NO_DATA_NOTE = "No metric data yet — run the metrics job.";

/**
 * Fold a filter PUT/DELETE response into the cache: the returned screen is
 * the new truth for ["screen", id]; the screens list (filter_count) and any
 * cached results pages are stale. Build-distribution cache updates are the
 * caller's job (PUT primes it, DELETE removes it).
 */
export function applyFilterResponse(
  queryClient: QueryClient,
  screenId: number,
  resp: FilterUpdateResponse,
): void {
  queryClient.setQueryData(["screen", screenId], resp.screen);
  queryClient.invalidateQueries({ queryKey: ["screens"] });
  queryClient.invalidateQueries({ queryKey: ["screen-results", screenId] });
}

export function ErrorPanel({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <div role="alert" className="bg-surface-2 border border-loss rounded-xl px-5 py-4">
      <h2 className="text-sm font-semibold text-loss mb-1">{title}</h2>
      <p className="text-[13px] text-text-secondary break-words whitespace-pre-wrap">
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 px-4 py-1.5 rounded-[6px] bg-surface-3 border border-border text-sm text-text-primary hover:border-accent-muted transition-colors"
      >
        Retry
      </button>
    </div>
  );
}
