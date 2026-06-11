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
        className="h-[320px] rounded-xl bg-surface-2 animate-pulse"
      />
    );
  }
  if (resultsQuery.isError) {
    return isSnapshotMissing(resultsQuery.error) ? (
      <div className="bg-surface-2 border border-border rounded-xl px-6 py-10 text-center text-[13px] text-text-muted">
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
    <section className="bg-surface-2 border border-border rounded-xl p-4 flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[11px] font-semibold tracking-[0.06em] uppercase text-text-muted">
          Results
        </h2>
        <span className="px-2 py-px rounded-[4px] bg-surface-3 border border-border tabular-nums text-[11px] text-accent">
          {formatCompact(total)} matches
        </span>
        <input
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Search ticker/name…"
          aria-label="Search results by ticker or name"
          className={`ml-auto w-[220px] ${INPUT_CLASS}`}
        />
        <button
          type="button"
          onClick={() => void exportCsv()}
          disabled={exporting}
          aria-label="Export results as CSV"
          className={BUTTON_CLASS}
        >
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>

      {exportError && (
        <p role="alert" className="text-[12px] text-loss break-words">
          {exportError}
        </p>
      )}

      <div
        className={`overflow-x-auto transition-opacity ${
          resultsQuery.isFetching ? "opacity-60" : ""
        }`}
      >
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-[11px] uppercase tracking-[0.06em] text-text-muted border-b border-border">
              {columns.map((col) => {
                const textCol = col.data_type === "string";
                const active = sort === col.code;
                return (
                  <th
                    key={col.code}
                    className={`py-2 px-3 first:pl-0 last:pr-0 font-semibold ${
                      textCol ? "text-left" : "text-right"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSort(col.code)}
                      aria-label={`Sort by ${col.name}`}
                      className={`uppercase tracking-[0.06em] transition-colors hover:text-text-primary ${
                        active ? "text-accent" : ""
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
                className="border-b border-border last:border-b-0"
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

      <div className="pt-2 border-t border-border flex flex-wrap items-center gap-3 text-[12px] text-text-secondary">
        <span className="tabular-nums">
          {total === 0 ? "0 rows" : `${firstRow}–${lastRow} of ${formatCompact(total)}`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || resultsQuery.isFetching}
            aria-label="Previous page"
            className={BUTTON_CLASS}
          >
            ← Prev
          </button>
          <span className="tabular-nums">
            Page {page} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || resultsQuery.isFetching}
            aria-label="Next page"
            className={BUTTON_CLASS}
          >
            Next →
          </button>
        </div>
      </div>
    </section>
  );
}

function ResultCell({ row, col }: { row: ResultsRow; col: ResultsColumn }) {
  const value = row[col.code];

  if (col.code === "ticker" && typeof value === "string") {
    return (
      <td className="py-2 px-3 first:pl-0">
        <Link
          href={`/stocks/${encodeURIComponent(value)}`}
          className="font-semibold text-text-primary hover:text-accent transition-colors"
        >
          {value}
        </Link>
      </td>
    );
  }
  if (col.data_type === "string") {
    return (
      <td className="py-2 px-3 first:pl-0 last:pr-0 text-left text-text-secondary">
        <span className="block truncate max-w-[260px]">
          {value === null || value === undefined ? "—" : String(value)}
        </span>
      </td>
    );
  }
  return (
    <td className="py-2 px-3 first:pl-0 last:pr-0 text-right tabular-nums text-text-primary">
      {typeof value === "number" ? formatMetricValue(value, col.data_type) : "—"}
    </td>
  );
}
