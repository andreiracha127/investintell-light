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
import { PageTitle } from "@/components/ui/panels";

const TABS = [
  { id: "metrics", label: "Select metrics" },
  { id: "build", label: "Build criteria" },
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
    <div
      className="mx-auto flex max-w-[1360px] flex-col"
      style={{ padding: "20px clamp(14px,3vw,28px) 40px" }}
    >
      <PageTitle
        title="Screener"
        meta={
          selected ? (
            <>
              {selected.name} ·{" "}
              <span className="tabular-nums">{selected.filter_count}</span>{" "}
              active filters
            </>
          ) : (
            "Build a metric-driven screen of the stock universe"
          )
        }
      />

      {screensQuery.isPending ? (
        <div
          aria-busy="true"
          aria-label="Loading screens"
          className="flex flex-col gap-px animate-pulse"
        >
          <div className="h-[44px] bg-surface-2" />
          <div className="h-[320px] bg-surface-2" />
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
          <div className="mt-4">
            <WizardTabs tab={tab} onTab={setTab} hasScreen={selected !== null} />
          </div>
          {selected && (
            <div className="mt-px">
              <ScreenWizardBody
                key={selected.id}
                screenId={selected.id}
                screenName={selected.name}
                tab={tab}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function EmptyState({ onCreated }: { onCreated: (id: number) => void }) {
  return (
    <div className="bg-surface-2 border border-border px-6 py-12 flex flex-col items-center gap-3">
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
    <div role="tablist" aria-label="Screener wizard steps" className="flex">
      {TABS.map((t, i) => {
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
            className={`flex h-[38px] flex-1 items-center justify-center gap-2 px-3.5 text-[12.5px] transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              i > 0 ? "border-l-0" : ""
            } ${
              active
                ? "relative z-[1] border border-accent bg-accent font-bold text-on-accent"
                : "border border-border-strong bg-field text-text-secondary hover:bg-layer-hover"
            }`}
          >
            <span
              aria-hidden="true"
              className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[9px] font-bold ${
                active ? "bg-[rgba(255,255,255,0.22)]" : "bg-layer-active"
              }`}
            >
              {i + 1}
            </span>
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
        className="h-[320px] bg-surface-2 animate-pulse"
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
