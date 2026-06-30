"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createScreen,
  deleteScreenFilter,
  fetchScreenBuildAll,
  putScreenFilter,
  reorderScreenFilters,
  type FilterBody,
  type MetricDef,
  type Screen,
} from "@/lib/api/client";
import { AddMetricBar } from "@/components/screener/AddMetricBar";
import { FiltersGrid } from "@/components/screener/FiltersGrid";
import { applyFilterResponse, ErrorPanel, retryPolicy } from "@/components/screener/shared";
import type { FiltersGridCallbacks } from "@/lib/grid/filtersGridOptions";

type SaveStatus = "idle" | "saving" | "error";

const DistributionPanel = dynamic(
  () =>
    import("@/components/screener/DistributionPanel").then(
      (mod) => mod.DistributionPanel,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="h-[240px] animate-pulse border-x border-b border-border bg-surface-2" />
    ),
  },
);

export function BuildPanel({
  screen,
  catalog,
  onScreenCreated,
  onHeadline,
  onSaveStatus,
}: {
  screen: Screen | null;
  catalog: MetricDef[];
  onScreenCreated: (id: number) => void;
  onHeadline: (count: number | null) => void;
  onSaveStatus: (status: SaveStatus) => void;
}) {
  const queryClient = useQueryClient();
  const screenId = screen?.id ?? null;

  const catalogMap = useMemo(() => new Map(catalog.map((m) => [m.code, m])), [catalog]);
  const filters = useMemo(
    () => (screen ? [...screen.filters].sort((a, b) => a.position - b.position) : []),
    [screen],
  );
  const filterCodes = useMemo(() => new Set(filters.map((f) => f.metric_code)), [filters]);

  const buildQuery = useQuery({
    queryKey: ["screen-build", screenId],
    queryFn: ({ signal }) => fetchScreenBuildAll(screenId as number, signal),
    enabled: screenId !== null && filters.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: retryPolicy,
  });
  const builds = useMemo(
    () => new Map((buildQuery.data?.metrics ?? []).map((m) => [m.metric_code, m])),
    [buildQuery.data],
  );

  // Live headline: batch-build first, overwritten by each mutation response.
  const headline = buildQuery.data?.headline_count ?? null;
  useEffect(() => onHeadline(headline), [headline, onHeadline]);

  const [activeCode, setActiveCode] = useState<string | null>(null);
  const [selectedForDelete, setSelectedForDelete] = useState<ReadonlySet<string>>(new Set());

  // Keep the active row valid (default to the first filter; clear when none).
  useEffect(() => {
    if (filters.length === 0) setActiveCode(null);
    else if (activeCode === null || !filterCodes.has(activeCode)) setActiveCode(filters[0].metric_code);
  }, [filters, filterCodes, activeCode]);

  const putMutation = useMutation({
    mutationFn: ({ code, body }: { code: string; body: FilterBody }) => putScreenFilter(screenId as number, code, body),
    onMutate: () => onSaveStatus("saving"),
    onSuccess: (resp) => { applyFilterResponse(queryClient, screenId as number, resp); onHeadline(resp.headline_count); onSaveStatus("idle"); },
    onError: () => onSaveStatus("error"),
  });
  const removeMutation = useMutation({
    mutationFn: (code: string) => deleteScreenFilter(screenId as number, code),
    onMutate: () => onSaveStatus("saving"),
    onSuccess: (resp) => { applyFilterResponse(queryClient, screenId as number, resp); onHeadline(resp.headline_count); onSaveStatus("idle"); },
    onError: () => onSaveStatus("error"),
  });
  const reorderMutation = useMutation({
    mutationFn: (codes: string[]) => reorderScreenFilters(screenId as number, codes),
    onMutate: () => onSaveStatus("saving"),
    onSuccess: (s) => {
      queryClient.setQueryData(["screen", s.id], s);
      queryClient.invalidateQueries({ queryKey: ["screen-results", s.id] });
      onSaveStatus("idle");
    },
    onError: () => onSaveStatus("error"),
  });

  // Add (or toggle off) a metric. Lazy-creates an "Untitled screen" on first add.
  const toggleMetric = useCallback(
    async (code: string) => {
      if (filterCodes.has(code)) { removeMutation.mutate(code); return; }
      try {
        onSaveStatus("saving");
        let id = screenId;
        if (id === null) {
          const created = await createScreen({ name: "Untitled screen" });
          id = created.id;
          queryClient.setQueryData(["screen", id], created);
          queryClient.invalidateQueries({ queryKey: ["screens"] });
          onScreenCreated(id);
        }
        const resp = await putScreenFilter(id, code, { min_value: null, max_value: null });
        applyFilterResponse(queryClient, id, resp);
        onHeadline(resp.headline_count);
        setActiveCode(code);
        onSaveStatus("idle");
      } catch { onSaveStatus("error"); }
    },
    [filterCodes, screenId, queryClient, onScreenCreated, onHeadline, onSaveStatus, removeMutation],
  );

  const editBound = useCallback(
    (code: string, which: "min" | "max", value: number | null) => {
      const f = filters.find((x) => x.metric_code === code);
      if (!f) return;
      putMutation.mutate({
        code,
        body: { min_value: which === "min" ? value : f.min_value, max_value: which === "max" ? value : f.max_value },
      });
    },
    [filters, putMutation],
  );

  const move = useCallback(
    (code: string, direction: "up" | "down") => {
      const codes = filters.map((f) => f.metric_code);
      const i = codes.indexOf(code);
      const j = direction === "up" ? i - 1 : i + 1;
      if (i < 0 || j < 0 || j >= codes.length) return;
      [codes[i], codes[j]] = [codes[j], codes[i]];
      reorderMutation.mutate(codes);
    },
    [filters, reorderMutation],
  );

  const toggleSelect = useCallback((code: string, checked: boolean) => {
    setSelectedForDelete((prev) => {
      const next = new Set(prev);
      if (checked) next.add(code); else next.delete(code);
      return next;
    });
  }, []);

  const gridCallbacks: FiltersGridCallbacks = useMemo(
    () => ({
      onEditBound: editBound,
      onRemove: (code) => removeMutation.mutate(code),
      onMove: move,
      onToggleSelect: toggleSelect,
      onSelectRow: setActiveCode,
    }),
    [editBound, move, toggleSelect, removeMutation],
  );

  const deleteSelected = () => {
    if (screenId === null) return;
    for (const code of selectedForDelete) removeMutation.mutate(code);
    setSelectedForDelete(new Set());
  };

  const pendingCode = putMutation.isPending ? putMutation.variables?.code : undefined;

  // ── render ──────────────────────────────────────────────────────────
  const activeFilter = filters.find((f) => f.metric_code === activeCode) ?? null;
  const activeMetric = activeCode ? catalogMap.get(activeCode) : undefined;

  return (
    <section className="mx-auto max-w-[1360px] flex flex-col">
      <AddMetricBar catalog={catalog} selectedCodes={filterCodes} pendingCode={pendingCode} onToggleMetric={toggleMetric} />

      {filters.length === 0 ? (
        <div className="bg-surface-2 border-x border-b border-border px-6 py-12 text-center text-[13px] text-text-muted">
          No metrics yet — add one above to start building your screen.
          <div className="mt-2 text-[11px] text-text-muted">① Name &nbsp;→&nbsp; ② Add metrics &amp; set ranges &nbsp;→&nbsp; ③ See results</div>
        </div>
      ) : buildQuery.isError ? (
        <ErrorPanel title="Failed to load distributions" message={buildQuery.error.message} onRetry={() => buildQuery.refetch()} />
      ) : (
        <>
          {selectedForDelete.size > 0 && (
            <div className="bg-surface-2 border-x border-b border-border px-[var(--ix-pad)] py-2">
              <button type="button" onClick={deleteSelected}
                className="border border-loss text-loss bg-field px-2.5 py-1 text-[11px] font-bold hover:bg-loss-muted">
                Delete {selectedForDelete.size} selected
              </button>
            </div>
          )}
          <FiltersGrid filters={filters} catalog={catalogMap} builds={builds} selectedForDelete={selectedForDelete}
            callbacks={gridCallbacks} className="border-x border-border" />
          {activeFilter && activeMetric && (
            <DistributionPanel
              metric={activeMetric}
              filter={activeFilter}
              build={builds.get(activeFilter.metric_code)}
              headline={headline}
              canMoveUp={filters[0].metric_code !== activeFilter.metric_code}
              canMoveDown={filters[filters.length - 1].metric_code !== activeFilter.metric_code}
              onEditBound={(which, value) => editBound(activeFilter.metric_code, which, value)}
              onApplyPreset={(min, max) => putMutation.mutate({ code: activeFilter.metric_code, body: { min_value: min, max_value: max } })}
              onMove={(dir) => move(activeFilter.metric_code, dir)}
            />
          )}
        </>
      )}
    </section>
  );
}
