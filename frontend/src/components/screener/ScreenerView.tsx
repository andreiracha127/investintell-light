"use client";

/**
 * Screener workspace: a persistent header (screen switcher + live count + save
 * status + Reset/Export) over two tabs — Build (unified metric add + editable
 * filters grid + distribution panel) and Results (server-driven Grid Pro).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  deleteScreenFilter,
  fetchMetricCatalog,
  fetchScreen,
  fetchScreenResultsCsv,
  fetchScreens,
} from "@/lib/api/client";
import { BuildPanel } from "@/components/screener/BuildPanel";
import { ResultsTab } from "@/components/screener/ResultsTab";
import { ScreenerHeader } from "@/components/screener/ScreenerHeader";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";

const TABS = [
  { id: "build", label: "Build" },
  { id: "results", label: "Results" },
] as const;
type TabId = (typeof TABS)[number]["id"];
type SaveStatus = "idle" | "saving" | "error";

export function ScreenerView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tab: TabId = searchParams.get("tab") === "results" ? "results" : "build";
  const setTab = (next: TabId) => router.replace(`/screener?tab=${next}`, { scroll: false });

  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [headline, setHeadline] = useState<number | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const screensQuery = useQuery({ queryKey: ["screens"], queryFn: ({ signal }) => fetchScreens(signal), staleTime: 60_000, retry: retryPolicy });
  const screens = screensQuery.data;
  useEffect(() => {
    if (!screens) return;
    if (screens.length === 0) setSelectedId(null);
    else if (selectedId === null || !screens.some((s) => s.id === selectedId)) setSelectedId(screens[0].id);
  }, [screens, selectedId]);
  const selected = screens?.find((s) => s.id === selectedId) ?? null;

  const screenQuery = useQuery({
    queryKey: ["screen", selectedId], queryFn: ({ signal }) => fetchScreen(selectedId as number, signal),
    enabled: selectedId !== null, staleTime: 60_000, retry: retryPolicy,
  });
  const catalogQuery = useQuery({ queryKey: ["screener-metrics"], queryFn: ({ signal }) => fetchMetricCatalog(signal), staleTime: Infinity, retry: retryPolicy });

  const onReset = async () => {
    const screen = screenQuery.data;
    if (!screen || screen.filters.length === 0 || !window.confirm("Clear all filters from this screen?")) return;
    setSaveStatus("saving");
    try {
      await Promise.all(screen.filters.map((f) => deleteScreenFilter(screen.id, f.metric_code)));
      for (const key of [["screen", screen.id], ["screen-build", screen.id], ["screen-results", screen.id], ["screens"]])
        queryClient.invalidateQueries({ queryKey: key });
      setSaveStatus("idle");
    } catch { setSaveStatus("error"); }
  };

  const onExport = async () => {
    if (selectedId === null) return;
    setExporting(true);
    setExportError(null);
    try {
      // Header export uses default ordering — the Results tab's local sort/search isn't shared here.
      const blob = await fetchScreenResultsCsv(selectedId, { dir: "asc" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(selected?.name ?? "screen").replace(/[^\w.-]+/g, "_")}-results.csv`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err));
    } finally { setExporting(false); }
  };

  if (screensQuery.isError) {
    return <div className="mx-auto max-w-[1360px] p-[var(--ix-pad)]"><ErrorPanel title="Failed to load screens" message={screensQuery.error.message} onRetry={() => screensQuery.refetch()} /></div>;
  }
  if (catalogQuery.isError) {
    return <div className="mx-auto max-w-[1360px] p-[var(--ix-pad)]"><ErrorPanel title="Failed to load metric catalog" message={catalogQuery.error.message} onRetry={() => catalogQuery.refetch()} /></div>;
  }

  return (
    <div className="flex flex-col pb-10">
      <ScreenerHeader screens={screens ?? []} selected={selected} onSelect={setSelectedId}
        headline={headline} saveStatus={saveStatus} onReset={onReset} onExport={onExport} exporting={exporting} />
      {exportError && (
        <p role="alert" className="mx-auto w-full max-w-[1360px] px-[var(--ix-pad)] pt-2 text-[12px] text-loss break-words">
          Export failed: {exportError}
        </p>
      )}

      <div className="mx-auto w-full max-w-[1360px] px-[var(--ix-pad)]">
        <div role="tablist" aria-label="Screener views" className="mt-3 flex">
          {TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
              className={`h-[36px] px-5 text-[12.5px] border transition-colors ${
                tab === t.id ? "relative z-[1] bg-surface-2 border-border border-b-surface-2 font-bold text-accent"
                  : "bg-field border-border-strong text-text-secondary hover:bg-layer-hover"
              }`}>{t.label}</button>
          ))}
        </div>
      </div>

      <div className="-mt-px">
        {tab === "build" ? (
          catalogQuery.data ? (
            <BuildPanel screen={screenQuery.data ?? null} catalog={catalogQuery.data}
              onScreenCreated={setSelectedId} onHeadline={setHeadline} onSaveStatus={setSaveStatus} />
          ) : (
            <div className="mx-auto max-w-[1360px] h-[320px] bg-surface-2 animate-pulse" />
          )
        ) : selected ? (
          <div className="mx-auto max-w-[1360px]">
            <ResultsTab screenId={selected.id} onHeadline={setHeadline} />
          </div>
        ) : (
          <div className="mx-auto max-w-[1360px] px-6 py-12 text-center text-[13px] text-text-muted">
            Create a screen in the Build tab to see results.
          </div>
        )}
      </div>
    </div>
  );
}
