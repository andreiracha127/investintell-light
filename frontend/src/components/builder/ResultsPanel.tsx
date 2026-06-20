"use client";

/**
 * Builder results workspace (onda 1): a tabbed shell around the optimize
 * response. "Allocation" is the original results body; the other tabs are
 * isolated components wired by later tasks.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";

import type {
  BuilderObjective,
  OptimizeRequest,
  OptimizeResponse,
} from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";

import { BUTTON_CLASS, BUTTON_PRIMARY_CLASS } from "@/components/screener/shared";

import type { UniverseAsset } from "./assets";
import { OBJECTIVE_COPY } from "./BuilderCopy";
import { AllocationTab, type AllocationActions } from "./AllocationTab";
import { BacktestTab } from "./BacktestTab";
import { ProjectionTab } from "./ProjectionTab";
import { RiskTab } from "./RiskTab";
import type { UsedConstraints } from "./tabShared";

/** Current allocation of the base portfolio (when seeded from a saved one). */
export interface BaseAllocation {
  name: string;
  /** assetKey ("equity:<TICKER>") -> weight fraction by market value. */
  weights: Map<string, number>;
}

type ResultTabId = "allocation" | "risk" | "backtest" | "projection";

const TABS: { id: ResultTabId; label: string }[] = [
  { id: "allocation", label: "Allocation" },
  { id: "risk", label: "Risk" },
  { id: "backtest", label: "Backtest" },
  { id: "projection", label: "Projection" },
];

const RESULT_VERSIONS = new WeakMap<OptimizeResponse, string>();
let nextResultVersion = 0;

interface TabState {
  version: string;
  activeTab: ResultTabId;
  visitedTabs: Set<ResultTabId>;
}

function initialTabState(version: string): TabState {
  return {
    version,
    activeTab: "allocation",
    visitedTabs: new Set<ResultTabId>(["allocation"]),
  };
}

function resultVersion(result: OptimizeResponse): string {
  const existing = RESULT_VERSIONS.get(result);
  if (existing) return existing;
  const version = `result-${nextResultVersion}`;
  nextResultVersion += 1;
  RESULT_VERSIONS.set(result, version);
  return version;
}

export function ResultsPanel({
  result,
  objective,
  constraints,
  saveConstraints = null,
  windowDays,
  cvarLimit,
  assetsByKey,
  base,
  colors,
  grouped,
  cvarLimitPct,
}: {
  result: OptimizeResponse;
  objective: BuilderObjective;
  constraints: UsedConstraints;
  /** Full constraints actually sent on the run, persisted on save (Sprint B). */
  saveConstraints?: OptimizeRequest["constraints"] | null;
  windowDays: number | null;
  cvarLimit: number | null;
  assetsByKey: Map<string, UniverseAsset>;
  base: BaseAllocation | null;
  colors: ChartColors | null;
  grouped: boolean;
  cvarLimitPct: string | null;
}) {
  const version = useMemo(() => resultVersion(result), [result]);
  const [tabState, setTabState] = useState<TabState>(() =>
    initialTabState(version),
  );
  // Export / Save controls live in the header (Builder.dc.html) but their logic
  // stays in AllocationTab, which registers them here while it is mounted.
  const [allocationActions, setAllocationActions] =
    useState<AllocationActions | null>(null);
  const effectiveTabState =
    tabState.version === version ? tabState : initialTabState(version);
  const { activeTab, visitedTabs } = effectiveTabState;

  useEffect(() => {
    if (tabState.version !== version) setTabState(initialTabState(version));
  }, [tabState.version, version]);

  const selectTab = (tab: ResultTabId) => {
    setTabState((previous) => {
      const current =
        previous.version === version ? previous : initialTabState(version);
      if (current.activeTab === tab && current.visitedTabs.has(tab)) {
        return current;
      }
      const nextVisited = new Set(current.visitedTabs);
      nextVisited.add(tab);
      return { version, activeTab: tab, visitedTabs: nextVisited };
    });
  };

  const metaParts = [
    OBJECTIVE_COPY[objective].label,
    `${result.weights.length} ${result.weights.length === 1 ? "holding" : "holdings"}`,
    constraints.cap != null
      ? `max ${(constraints.cap * 100).toFixed(0)}% each`
      : "uncapped",
  ];

  return (
    <div className="border border-border bg-surface-2">
      {/* ── Results header: serif title + meta + result tabs ──────────── */}
      <div className="border-b border-border px-[var(--ix-pad)] pt-3.5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="ix-title m-0 text-[17px]">Suggested portfolio</h2>
            <div className="mt-0.5 text-[11.5px] text-text-muted">
              {metaParts.join(" · ")}
            </div>
          </div>
          {activeTab === "allocation" && allocationActions && (
            <span className="flex items-center gap-2">
              <button
                type="button"
                onClick={allocationActions.exportCsv}
                className={`${BUTTON_CLASS} inline-flex items-center gap-[7px] text-[12px]`}
              >
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 16 16"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M8 1v9M4.5 7L8 10.5 11.5 7M2 14h12"
                    stroke="currentColor"
                    strokeWidth="1.3"
                  />
                </svg>
                Export CSV
              </button>
              <button
                type="button"
                onClick={allocationActions.toggleSave}
                aria-expanded={allocationActions.saveOpen}
                className={BUTTON_PRIMARY_CLASS}
              >
                Save as portfolio
              </button>
            </span>
          )}
        </div>
        <div
          className="mt-3.5 flex flex-wrap gap-0"
          role="tablist"
          aria-label="Builder result tabs"
        >
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              id={`builder-result-tab-${tab.id}`}
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls={`builder-result-panel-${tab.id}`}
              onClick={() => selectTab(tab.id)}
              className={`relative h-[38px] border border-b-0 border-border px-5 text-[12px] font-bold uppercase tracking-[0.04em] transition-colors ${
                activeTab === tab.id
                  ? "top-px bg-surface-2 text-accent shadow-[inset_0_2px_0_var(--color-accent)]"
                  : "bg-zebra text-text-secondary hover:bg-layer-hover hover:text-text-primary"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="ix-pad">
      <TabPanel active={activeTab === "allocation"} id="allocation">
        <AllocationTab
          key={`allocation-${version}`}
          result={result}
          objective={objective}
          assetsByKey={assetsByKey}
          base={base}
          colors={colors}
          grouped={grouped}
          cvarLimitPct={cvarLimitPct}
          saveConstraints={saveConstraints}
          onRegisterActions={setAllocationActions}
        />
      </TabPanel>
      {visitedTabs.has("risk") && (
        <TabPanel active={activeTab === "risk"} id="risk">
          <RiskTab
            key={`risk-${version}`}
            result={result}
            assetsByKey={assetsByKey}
            colors={colors}
          />
        </TabPanel>
      )}
      {visitedTabs.has("backtest") && (
        <TabPanel active={activeTab === "backtest"} id="backtest">
          <BacktestTab
            key={`backtest-${version}`}
            result={result}
            objective={objective}
            constraints={constraints}
            windowDays={windowDays}
            cvarLimit={cvarLimit}
            colors={colors}
          />
        </TabPanel>
      )}
      {visitedTabs.has("projection") && (
        <TabPanel active={activeTab === "projection"} id="projection">
          <ProjectionTab
            key={`projection-${version}`}
            result={result}
            colors={colors}
          />
        </TabPanel>
      )}
      </div>
    </div>
  );
}

function TabPanel({
  active,
  id,
  children,
}: {
  active: boolean;
  id: ResultTabId;
  children: ReactNode;
}) {
  return (
    <div
      id={`builder-result-panel-${id}`}
      role="tabpanel"
      aria-labelledby={`builder-result-tab-${id}`}
      hidden={!active}
      className={active ? "block" : "hidden"}
    >
      {children}
    </div>
  );
}
