"use client";

/**
 * Shared screener plumbing: input/button classes (Cockpit Carbon tokens), the
 * standard retry policy, the fail-loud error panel, and the single place a
 * filter PUT/DELETE response is folded back into the query cache.
 */
import type { QueryClient } from "@tanstack/react-query";

import { ApiError, type FilterUpdateResponse } from "@/lib/api/client";

/** Carbon field: square, bottom-border only, accent focus rule. */
export const INPUT_CLASS =
  "h-[34px] px-2 bg-field border-0 border-b border-border-strong text-[13px] " +
  "text-text-primary placeholder:text-text-muted outline-none " +
  "focus:border-b-2 focus:border-b-accent";

/** Secondary (ghost) button — square, hairline-strong border. */
export const BUTTON_CLASS =
  "h-[34px] px-3.5 bg-field border border-border-strong text-[12.5px] " +
  "text-text-secondary hover:bg-layer-hover " +
  "transition-colors disabled:opacity-40 disabled:cursor-not-allowed";

/** Primary action button — solid accent, square. */
export const BUTTON_PRIMARY_CLASS =
  "h-[34px] px-4 bg-accent text-on-accent text-[12.5px] font-bold " +
  "hover:bg-accent-muted transition-colors " +
  "disabled:opacity-40 disabled:cursor-not-allowed";

/** Carbon field label — 10px uppercase tracked. */
export const FIELD_LABEL_CLASS =
  "text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted";

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
 * cached results pages are stale. This also invalidates the batch-build cache
 * (["screen-build", id]) that feeds the sparklines + distribution panel.
 */
export function applyFilterResponse(
  queryClient: QueryClient,
  screenId: number,
  resp: FilterUpdateResponse,
): void {
  queryClient.setQueryData(["screen", screenId], resp.screen);
  queryClient.invalidateQueries({ queryKey: ["screens"] });
  queryClient.invalidateQueries({ queryKey: ["screen-results", screenId] });
  queryClient.invalidateQueries({ queryKey: ["screen-build", screenId] }); // batch build (sparklines + panel)
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
    <div
      role="alert"
      className="bg-surface-2 border border-border border-l-[3px] px-5 py-4"
      style={{ borderLeftColor: "var(--color-loss)" }}
    >
      <h2 className="text-sm font-semibold text-loss mb-1">{title}</h2>
      <p className="text-[13px] text-text-secondary break-words whitespace-pre-wrap">
        {message}
      </p>
      <button type="button" onClick={onRetry} className={`mt-3 ${BUTTON_CLASS}`}>
        Retry
      </button>
    </div>
  );
}
