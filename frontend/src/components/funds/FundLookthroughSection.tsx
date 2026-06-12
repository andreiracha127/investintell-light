"use client";

/**
 * Consolidated exposure section for the fund profile page.
 *
 * Fetches look-through data for the fund, then delegates all rendering to the
 * shared `LookthroughPanel`. 404 → renders nothing (fund has no decomposition
 * data). Any other error follows the view's error panel pattern.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, fetchFundLookthrough } from "@/lib/api/client";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { LookthroughPanel } from "@/components/lookthrough/LookthroughPanel";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatDate } from "@/lib/format";

export function FundLookthroughSection({
  instrumentId,
}: {
  instrumentId: string;
}) {
  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const query = useQuery({
    queryKey: ["fund-lookthrough", instrumentId],
    queryFn: ({ signal }) => fetchFundLookthrough(instrumentId, {}, signal),
    staleTime: 60_000,
    retry: (failureCount, err) => {
      // Never retry 404 (fund has no decomposition data) or other 4xx.
      if (err instanceof ApiError && err.status === 404) return false;
      return retryPolicy(failureCount, err);
    },
  });

  // 404 → fund has no decomposition data; render nothing silently.
  if (
    query.isError &&
    query.error instanceof ApiError &&
    query.error.status === 404
  ) {
    return null;
  }

  if (query.isPending) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading consolidated exposure"
        className="h-[120px] bg-surface-2 animate-pulse"
      />
    );
  }

  if (query.isError) {
    return (
      <ErrorPanel
        title="Failed to load consolidated exposure"
        message={query.error.message}
        onRetry={() => query.refetch()}
      />
    );
  }

  const data = query.data;

  return (
    <section>
      {/* Section header */}
      <div className="mb-3">
        <h2 className="ix-label m-0">Consolidated exposure</h2>
        <p className="text-[12px] text-text-secondary mt-0.5">
          Through underlying funds{" "}
          {data.report_date ? `· as of ${formatDate(data.report_date)}` : ""}
        </p>
      </div>

      {colors && (
        <LookthroughPanel
          dimensions={data.dimensions}
          summary={data.summary}
          reportDate={data.report_date}
          colors={colors}
          expandedLabel="Funds expanded"
          expandedCount={data.summary.n_children_expanded}
        />
      )}
    </section>
  );
}
