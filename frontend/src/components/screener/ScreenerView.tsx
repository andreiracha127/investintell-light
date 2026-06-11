"use client";

/**
 * Screener wizard — a persistent screen entity driven through three tabs:
 * Select Metrics (catalog toggles), Build (distribution + bounds + live
 * match count) and Results (server-side table + CSV). The active tab lives
 * in `?tab=` so refresh keeps the place.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  fetchMetricCatalog,
  fetchScreen,
  fetchScreens,
} from "@/lib/api/client";
import { BuildTab } from "@/components/screener/BuildTab";
import { ResultsTab } from "@/components/screener/ResultsTab";
import {
  CreateScreenForm,
  ScreenStrip,
} from "@/components/screener/ScreenStrip";
import { SelectMetricsTab } from "@/components/screener/SelectMetricsTab";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";

const TABS = [
  { id: "metrics", label: "Select Metrics" },
  { id: "build", label: "Build" },
  { id: "results", label: "Results" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function isTabId(value: string | null): value is TabId {
  return TABS.some((t) => t.id === value);
}

export function ScreenerView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  const tab: TabId = isTabId(rawTab) ? rawTab : "metrics";
  const setTab = (next: TabId) =>
    router.replace(`/screener?tab=${next}`, { scroll: false });

  const [selectedId, setSelectedId] = useState<number | null>(null);

  const screensQuery = useQuery({
    queryKey: ["screens"],
    queryFn: ({ signal }) => fetchScreens(signal),
    staleTime: 60_000,
    retry: retryPolicy,
  });
  const screens = screensQuery.data;

  // Keep the selection valid: default to the first screen, fall back when
  // the selected one is deleted, clear when none remain.
  useEffect(() => {
    if (!screens) return;
    if (screens.length === 0) {
      setSelectedId(null);
    } else if (
      selectedId === null ||
      !screens.some((s) => s.id === selectedId)
    ) {
      setSelectedId(screens[0].id);
    }
  }, [screens, selectedId]);

  const selected = screens?.find((s) => s.id === selectedId) ?? null;

  return (
    <div className="px-6 py-5 max-w-[1400px] mx-auto flex flex-col gap-5">
      <h1 className="text-2xl font-bold tracking-tight text-text-primary">
        Screener
      </h1>

      {screensQuery.isPending ? (
        <div
          aria-busy="true"
          aria-label="Loading screens"
          className="flex flex-col gap-5 animate-pulse"
        >
          <div className="h-[44px] rounded-xl bg-surface-2" />
          <div className="h-[320px] rounded-xl bg-surface-2" />
        </div>
      ) : screensQuery.isError ? (
        <ErrorPanel
          title="Failed to load screens"
          message={screensQuery.error.message}
          onRetry={() => screensQuery.refetch()}
        />
      ) : screens && screens.length === 0 ? (
        <EmptyState onCreated={setSelectedId} />
      ) : (
        <>
          <ScreenStrip
            screens={screens ?? []}
            selected={selected}
            onSelect={setSelectedId}
          />
          <WizardTabs tab={tab} onTab={setTab} hasScreen={selected !== null} />
          {selected && (
            <ScreenWizardBody
              key={selected.id}
              screenId={selected.id}
              screenName={selected.name}
              tab={tab}
            />
          )}
        </>
      )}
    </div>
  );
}

function EmptyState({ onCreated }: { onCreated: (id: number) => void }) {
  return (
    <div className="bg-surface-2 border border-border rounded-xl px-6 py-12 flex flex-col items-center gap-3">
      <h2 className="text-sm font-semibold text-text-primary">No screens yet</h2>
      <p className="text-[13px] text-text-secondary">
        Create your first screen to filter the stock universe by metrics.
      </p>
      <CreateScreenForm onCreated={onCreated} autoFocus />
    </div>
  );
}

function WizardTabs({
  tab,
  onTab,
  hasScreen,
}: {
  tab: TabId;
  onTab: (tab: TabId) => void;
  hasScreen: boolean;
}) {
  return (
    <div role="tablist" aria-label="Screener wizard steps" className="flex gap-1 border-b border-border">
      {TABS.map((t) => {
        const disabled = t.id !== "metrics" && !hasScreen;
        const active = tab === t.id;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={disabled}
            onClick={() => onTab(t.id)}
            className={`px-4 py-2 -mb-px border-b-2 text-[13px] font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              active
                ? "border-accent text-accent"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/** Loads the shared screen + catalog data once and renders the active tab. */
function ScreenWizardBody({
  screenId,
  screenName,
  tab,
}: {
  screenId: number;
  screenName: string;
  tab: TabId;
}) {
  const screenQuery = useQuery({
    queryKey: ["screen", screenId],
    queryFn: ({ signal }) => fetchScreen(screenId, signal),
    staleTime: 60_000,
    retry: retryPolicy,
  });
  const catalogQuery = useQuery({
    queryKey: ["screener-metrics"],
    queryFn: ({ signal }) => fetchMetricCatalog(signal),
    staleTime: Infinity, // static catalog — defined in code, not data
    retry: retryPolicy,
  });

  if (screenQuery.isPending || catalogQuery.isPending) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading screen"
        className="h-[320px] rounded-xl bg-surface-2 animate-pulse"
      />
    );
  }
  if (screenQuery.isError) {
    return (
      <ErrorPanel
        title="Failed to load screen"
        message={screenQuery.error.message}
        onRetry={() => screenQuery.refetch()}
      />
    );
  }
  if (catalogQuery.isError) {
    return (
      <ErrorPanel
        title="Failed to load metric catalog"
        message={catalogQuery.error.message}
        onRetry={() => catalogQuery.refetch()}
      />
    );
  }

  const screen = screenQuery.data;
  const catalog = catalogQuery.data;

  if (tab === "metrics") {
    return <SelectMetricsTab screen={screen} catalog={catalog} />;
  }
  if (tab === "build") {
    return <BuildTab screen={screen} catalog={catalog} />;
  }
  return <ResultsTab screenId={screenId} screenName={screenName} />;
}
