"use client";

/**
 * Wizard Tab 1 — metric catalog grouped by category; clicking a row TOGGLES
 * the metric on the screen. ON = PUT filter with null bounds ("selected"
 * semantics — the backend excludes NULL rows); OFF = DELETE filter.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  deleteScreenFilter,
  putScreenFilter,
  type MetricDef,
  type Screen,
} from "@/lib/api/client";
import {
  applyFilterResponse,
  INPUT_CLASS,
} from "@/components/screener/shared";

export function SelectMetricsTab({
  screen,
  catalog,
}: {
  screen: Screen;
  catalog: MetricDef[];
}) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());

  const selectedCodes = useMemo(
    () => new Set(screen.filters.map((f) => f.metric_code)),
    [screen.filters],
  );

  const selectMutation = useMutation({
    mutationFn: (code: string) =>
      // Null bounds = "selected, unconstrained": results column + NULL exclusion.
      putScreenFilter(screen.id, code, { min_value: null, max_value: null }),
    onSuccess: (resp, code) => {
      applyFilterResponse(queryClient, screen.id, resp);
      // Prime the Build card so Tab 2 opens without a refetch.
      queryClient.setQueryData(["screen-build", screen.id, code], {
        distribution: resp.distribution,
        headline_count: resp.headline_count,
      });
    },
  });
  const deselectMutation = useMutation({
    mutationFn: (code: string) => deleteScreenFilter(screen.id, code),
    onSuccess: (resp, code) => {
      applyFilterResponse(queryClient, screen.id, resp);
      queryClient.removeQueries({
        queryKey: ["screen-build", screen.id, code],
      });
    },
  });

  const pendingCode =
    (selectMutation.isPending ? selectMutation.variables : undefined) ??
    (deselectMutation.isPending ? deselectMutation.variables : undefined);
  const mutationError = selectMutation.error ?? deselectMutation.error;

  const toggle = (code: string) => {
    if (pendingCode !== undefined) return;
    if (selectedCodes.has(code)) {
      deselectMutation.mutate(code);
    } else {
      selectMutation.mutate(code);
    }
  };

  // Search across name / code / abbreviation; grouping preserves catalog order.
  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered =
      needle === ""
        ? catalog
        : catalog.filter(
            (m) =>
              m.name.toLowerCase().includes(needle) ||
              m.code.toLowerCase().includes(needle) ||
              m.abbreviation.toLowerCase().includes(needle),
          );
    const map = new Map<string, MetricDef[]>();
    for (const metric of filtered) {
      const group = map.get(metric.category);
      if (group) {
        group.push(metric);
      } else {
        map.set(metric.category, [metric]);
      }
    }
    return [...map.entries()];
  }, [catalog, search]);

  return (
    <section className="bg-surface-2 border border-border rounded-xl p-4 flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[11px] font-semibold tracking-[0.06em] uppercase text-text-muted">
          Metric Catalog
        </h2>
        <span className="px-2 py-px rounded-[4px] bg-surface-3 border border-border tabular-nums text-[11px] text-accent">
          {selectedCodes.size} selected
        </span>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search metrics…"
          aria-label="Search metrics by name or code"
          className={`ml-auto w-[220px] ${INPUT_CLASS}`}
        />
      </div>

      {mutationError && (
        <p role="alert" className="text-[12px] text-loss break-words">
          {mutationError.message}
        </p>
      )}

      {catalog.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-text-muted">
          The metric catalog is empty.
        </p>
      ) : groups.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-text-muted">
          No metrics match &ldquo;{search.trim()}&rdquo;.
        </p>
      ) : (
        groups.map(([category, metrics]) => {
          const isCollapsed = collapsed.has(category);
          const selectedInGroup = metrics.filter((m) =>
            selectedCodes.has(m.code),
          ).length;
          return (
            <div key={category}>
              <button
                type="button"
                onClick={() =>
                  setCollapsed((prev) => {
                    const next = new Set(prev);
                    if (next.has(category)) {
                      next.delete(category);
                    } else {
                      next.add(category);
                    }
                    return next;
                  })
                }
                aria-expanded={!isCollapsed}
                aria-label={`Toggle category ${category}`}
                className="w-full flex items-center gap-2 py-1.5 text-left text-[11px] font-bold tracking-[0.08em] uppercase text-text-secondary hover:text-text-primary transition-colors"
              >
                <span aria-hidden="true" className="text-text-muted">
                  {isCollapsed ? "▸" : "▾"}
                </span>
                {category}
                <span className="tabular-nums font-normal normal-case tracking-normal text-[11px] text-text-muted">
                  {selectedInGroup > 0
                    ? `${selectedInGroup}/${metrics.length}`
                    : metrics.length}
                </span>
              </button>
              {!isCollapsed && (
                <ul className="flex flex-col gap-1 pb-2">
                  {metrics.map((metric) => (
                    <MetricRow
                      key={metric.code}
                      metric={metric}
                      selected={selectedCodes.has(metric.code)}
                      pending={pendingCode === metric.code}
                      onToggle={() => toggle(metric.code)}
                    />
                  ))}
                </ul>
              )}
            </div>
          );
        })
      )}
    </section>
  );
}

function MetricRow({
  metric,
  selected,
  pending,
  onToggle,
}: {
  metric: MetricDef;
  selected: boolean;
  pending: boolean;
  onToggle: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        disabled={pending}
        aria-pressed={selected}
        aria-label={`${selected ? "Deselect" : "Select"} metric ${metric.name}`}
        className={`w-full flex items-center gap-3 px-3 py-1.5 rounded-[6px] border text-left text-[13px] transition-colors disabled:opacity-50 disabled:cursor-wait ${
          selected
            ? "bg-surface-3 border-accent-muted"
            : "bg-surface-1 border-border hover:border-accent-muted"
        }`}
      >
        <span
          aria-hidden="true"
          className={`w-4 shrink-0 text-center ${
            selected ? "text-accent" : "text-text-muted"
          }`}
        >
          {pending ? "…" : selected ? "✓" : ""}
        </span>
        <span
          className={`font-medium ${
            selected ? "text-text-primary" : "text-text-secondary"
          }`}
        >
          {metric.name}
        </span>
        <span className="text-[11px] text-text-muted">{metric.abbreviation}</span>
        {metric.sub_category && (
          <span className="hidden sm:inline text-[11px] text-text-muted">
            {metric.sub_category}
          </span>
        )}
        <span className="ml-auto px-1.5 py-px rounded-[4px] bg-surface-2 border border-border text-[10px] text-text-muted">
          {metric.data_type}
        </span>
      </button>
    </li>
  );
}
