"use client";

/**
 * Labeled persisted-portfolio <select> fed by GET /portfolios.
 *
 * Auto-selects the first portfolio when the current value is null or no
 * longer exists; renders an empty-state link to /portfolio when none exist.
 * Load failures surface the backend message verbatim (fail loud).
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useId } from "react";

import { ApiError, fetchPortfolios } from "@/lib/api/client";
import { INPUT_CLASS, LABEL_CLASS } from "@/components/statistics/ui";

/** Never retry 4xx (deterministic), retry 5xx/network twice. */
const retryPolicy = (failureCount: number, err: Error) =>
  !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
  failureCount < 2;

export function PortfolioSelect({
  value,
  onChange,
  label = "Portfolio",
}: {
  value: number | null;
  onChange: (id: number | null) => void;
  label?: string;
}) {
  const selectId = useId();
  const portfoliosQuery = useQuery({
    queryKey: ["portfolios"],
    queryFn: ({ signal }) => fetchPortfolios(signal),
    staleTime: 60_000,
    retry: retryPolicy,
  });
  const portfolios = portfoliosQuery.data;

  // Keep the selection valid: default to the first portfolio, fall back when
  // the selected one disappears, clear when none remain.
  useEffect(() => {
    if (!portfolios) return;
    if (portfolios.length === 0) {
      if (value !== null) onChange(null);
    } else if (value === null || !portfolios.some((p) => p.id === value)) {
      onChange(portfolios[0].id);
    }
  }, [portfolios, value, onChange]);

  if (portfoliosQuery.isError) {
    return (
      <p role="alert" className="ix-fs break-words text-loss">
        Failed to load portfolios: {portfoliosQuery.error.message}
      </p>
    );
  }

  if (portfolios && portfolios.length === 0) {
    return (
      <p className="ix-fs text-text-secondary">
        No portfolios yet —{" "}
        <Link
          href="/portfolio"
          className="text-accent transition-colors hover:text-accent-muted"
        >
          create one in Portfolio Overview
        </Link>
        .
      </p>
    );
  }

  return (
    <label htmlFor={selectId} className={`min-w-[160px] ${LABEL_CLASS}`}>
      {label}
      <select
        id={selectId}
        value={value ?? ""}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={portfoliosQuery.isPending}
        className={INPUT_CLASS}
      >
        {portfoliosQuery.isPending ? (
          <option value="">Loading…</option>
        ) : (
          portfolios?.map((portfolio) => (
            <option key={portfolio.id} value={portfolio.id}>
              {portfolio.name}
            </option>
          ))
        )}
      </select>
    </label>
  );
}
