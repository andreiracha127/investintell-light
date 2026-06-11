"use client";

/**
 * Wizard Tab 3 — server-driven results table: dynamic columns from the
 * response, header-click sorting, prefix search, paging (25/page) and CSV
 * export (fetch + blob through the typed client so base-URL handling stays
 * consistent). The frontend formats; the backend filters/sorts/paginates.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  fetchScreenResults,
  fetchScreenResultsCsv,
  type ResultsColumn,
  type ResultsRow,
} from "@/lib/api/client";
import {
  BUTTON_CLASS,
  ErrorPanel,
  INPUT_CLASS,
  isSnapshotMissing,
  NO_DATA_NOTE,
  retryPolicy,
} from "@/components/screener/shared";
import { formatCompact, formatMetricValue } from "@/lib/format";

const PAGE_SIZE = 25;
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
  const [page, setPage] = useState(1);

  // Debounce the server-side search; a search change restarts at page 1
  // (separate effect so state updaters stay pure).
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchText.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchText]);
  useEffect(() => {
    setPage(1);
  }, [search]);

  const resultsQuery = useQuery({
    queryKey: ["screen-results", screenId, sort ?? "", dir, search, page],
    queryFn: ({ signal }) =>
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
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: retryPolicy,
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

  const onSort = (code: string) => {
    if (sort === code) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSort(code);
      setDir("asc");
    }
    setPage(1);
  };

  if (resultsQuery.isPending) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading screen results"
        className="h-[320px] bg-surface-2 animate-pulse"
      />
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
        message={resultsQuery.error.message}
        onRetry={() => resultsQuery.refetch()}
      />
    );
  }

  const { columns, rows, total } = resultsQuery.data;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const firstRow = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastRow = Math.min(page * PAGE_SIZE, total);

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
        className={`overflow-x-auto transition-opacity ${
          resultsQuery.isFetching ? "opacity-60" : ""
        }`}
      >
        <table className="w-full min-w-[760px] border-collapse ix-fs tabular-nums lining-nums">
          <thead>
            <tr className="bg-field">
              {columns.map((col) => {
                const textCol = col.data_type === "string";
                const active = sort === col.code;
                return (
                  <th
                    key={col.code}
                    className={`sticky top-0 whitespace-nowrap bg-field px-2.5 py-[9px] first:pl-[var(--ix-pad)] last:pr-[var(--ix-pad)] border-t border-t-border ${
                      textCol ? "text-left" : "text-right"
                    } ${
                      active
                        ? "border-b-2 border-b-accent font-bold text-accent"
                        : "border-b border-b-border-strong font-semibold text-text-secondary"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSort(col.code)}
                      aria-label={`Sort by ${col.name}`}
                      className={`whitespace-nowrap transition-colors ${
                        active
                          ? "font-bold text-accent"
                          : "font-semibold hover:text-text-primary"
                      }`}
                    >
                      {col.name}
                      {active && (
                        <span aria-hidden="true" className="ml-1">
                          {dir === "asc" ? "▲" : "▼"}
                        </span>
                      )}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={typeof row.ticker === "string" ? row.ticker : i}
                className={`border-b border-border transition-colors hover:bg-accent-wash ${
                  i % 2 === 1 ? "bg-zebra" : ""
                }`}
              >
                {columns.map((col) => (
                  <ResultCell key={col.code} row={row} col={col} />
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={Math.max(columns.length, 1)}
                  className="py-6 text-center text-[13px] text-text-muted"
                >
                  {total === 0 && search !== ""
                    ? `No matches for "${search}".`
                    : "No matches — loosen the filters, or the metrics snapshot may not be computed yet."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 border-t border-border px-[var(--ix-pad)] py-2.5 text-[12px] text-text-secondary">
        <span className="tabular-nums">
          {total === 0 ? "0 rows" : `${firstRow}–${lastRow} of ${formatCompact(total)}`}
        </span>
        <div className="ml-auto flex items-center gap-px">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || resultsQuery.isFetching}
            aria-label="Previous page"
            className="h-[30px] w-8 bg-field border border-border-strong text-text-secondary hover:bg-layer-hover transition-colors disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-field"
          >
            ‹
          </button>
          {pageWindow(page, totalPages).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPage(p)}
              disabled={resultsQuery.isFetching}
              aria-label={`Page ${p}`}
              aria-current={p === page ? "page" : undefined}
              className={`flex h-[30px] items-center px-3 tabular-nums transition-colors ${
                p === page
                  ? "bg-accent border border-accent font-bold text-on-accent"
                  : "bg-field border border-border-strong text-text-secondary hover:bg-layer-hover"
              }`}
            >
              {p}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || resultsQuery.isFetching}
            aria-label="Next page"
            className="h-[30px] w-8 bg-field border border-border-strong text-text-secondary hover:bg-layer-hover transition-colors disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-field"
          >
            ›
          </button>
        </div>
      </div>
    </section>
  );
}

/** Up to 5 page numbers centered on the current page — presentation only. */
function pageWindow(page: number, totalPages: number): number[] {
  const size = Math.min(5, totalPages);
  const start = Math.min(Math.max(1, page - 2), totalPages - size + 1);
  return Array.from({ length: size }, (_, i) => start + i);
}

const CELL_CLASS =
  "ix-cell px-2.5 first:pl-[var(--ix-pad)] last:pr-[var(--ix-pad)]";

function ResultCell({ row, col }: { row: ResultsRow; col: ResultsColumn }) {
  const value = row[col.code];

  if (col.code === "ticker" && typeof value === "string") {
    return (
      <td className={CELL_CLASS}>
        <Link
          href={`/stocks/${encodeURIComponent(value)}`}
          className="font-bold text-accent hover:underline"
        >
          {value}
        </Link>
      </td>
    );
  }
  if (col.data_type === "string") {
    return (
      <td className={`${CELL_CLASS} text-left text-text-secondary`}>
        <span className="block truncate max-w-[260px]">
          {value === null || value === undefined ? "—" : String(value)}
        </span>
      </td>
    );
  }
  // Percent metrics read as variations — color by sign, Cockpit gain/loss.
  const tone =
    col.data_type === "percent" && typeof value === "number" && value !== 0
      ? value > 0
        ? "font-bold text-gain"
        : "font-bold text-loss"
      : "text-text-primary";
  return (
    <td className={`${CELL_CLASS} text-right tabular-nums ${tone}`}>
      {typeof value === "number" ? formatMetricValue(value, col.data_type) : "—"}
    </td>
  );
}
