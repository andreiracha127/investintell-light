"use client";

/**
 * Portfolio Builder (F8.5) — assemble a mixed fund/equity universe, set
 * constraints + objective, optionally express Black-Litterman views, and
 * POST /builder/optimize. The backend computes ALL finance; this view only
 * collects inputs and renders the response. 422s surface verbatim.
 */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  postBuilderOptimize,
  type BuilderObjective,
  type BuilderViewIn,
  type OptimizeRequest,
  type PortfolioOverview,
} from "@/lib/api/client";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { Card, PageTitle } from "@/components/ui/panels";
import {
  ErrorPanel,
  FIELD_LABEL_CLASS,
  INPUT_CLASS,
} from "@/components/screener/shared";

import { assetKey, toRef, type UniverseAsset, OBJECTIVES } from "./assets";
import { UniverseCard } from "./UniverseCard";
import { ViewsCard, toApiView, type ViewDraft } from "./ViewsCard";
import { ResultsPanel, type BaseAllocation } from "./ResultsPanel";

/** Parse a non-empty numeric input; invalid/blank -> null. */
function parseNum(text: string): number | null {
  if (text.trim() === "") return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

export function BuilderView() {
  // Chart tokens are CSS custom properties — readable only after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  /* ── Universe ──────────────────────────────────────────────────────── */
  const [assets, setAssets] = useState<UniverseAsset[]>([]);
  const [base, setBase] = useState<BaseAllocation | null>(null);

  const addAssets = (added: UniverseAsset[]) => {
    setAssets((prev) => {
      const seen = new Set(prev.map(assetKey));
      const fresh = added.filter((a) => {
        const key = assetKey(a);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      return fresh.length === 0 ? prev : [...prev, ...fresh];
    });
  };
  const removeAsset = (key: string) =>
    setAssets((prev) => prev.filter((a) => assetKey(a) !== key));

  const seedPortfolio = (overview: PortfolioOverview) => {
    addAssets(
      overview.positions.map((p) => ({ kind: "equity" as const, ticker: p.ticker })),
    );
    const total = overview.aggregates.total_market_value;
    setBase({
      name: overview.name,
      weights: new Map(
        total > 0
          ? overview.positions.map((p) => [
              `equity:${p.ticker.toUpperCase()}`,
              p.market_value / total,
            ])
          : [],
      ),
    });
  };

  const assetsByKey = useMemo(
    () => new Map(assets.map((a) => [assetKey(a), a])),
    [assets],
  );

  /* ── Constraints & objective ───────────────────────────────────────── */
  const [objective, setObjective] = useState<BuilderObjective>("min_cvar");
  const [capPct, setCapPct] = useState("25");
  const [minWeightPct, setMinWeightPct] = useState("");
  const [windowDays, setWindowDays] = useState("730");

  /* ── Views ─────────────────────────────────────────────────────────── */
  const [viewsOpen, setViewsOpen] = useState(false);
  const [views, setViews] = useState<ViewDraft[]>([]);

  const apiViews: (BuilderViewIn | null)[] = views.map((v) =>
    toApiView(v, assetsByKey),
  );
  const viewsValid = apiViews.every((v) => v !== null);

  /* ── Run ───────────────────────────────────────────────────────────── */
  const mutation = useMutation({
    mutationFn: (body: OptimizeRequest) => postBuilderOptimize(body),
  });

  const cap = parseNum(capPct);
  const windowVal = parseNum(windowDays);
  const minWeight = parseNum(minWeightPct);
  // Blank cap = uncapped (null); a typed but non-numeric cap blocks the run.
  const capOk = capPct.trim() === "" || cap !== null;
  const canRun =
    assets.length >= 2 && windowVal !== null && viewsValid && capOk;

  const onRun = () => {
    if (!canRun || mutation.isPending) return;
    const completed = apiViews.filter((v): v is BuilderViewIn => v !== null);
    mutation.mutate({
      assets: assets.map(toRef),
      objective,
      constraints: {
        cap: cap !== null ? cap / 100 : null,
        min_weight: minWeight !== null ? minWeight / 100 : null,
      },
      window_days: windowVal as number,
      ...(completed.length > 0 && { views: completed }),
      bl: { delta: 2.5, tau: 0.05 },
    });
  };

  const objectiveDef = OBJECTIVES.find((o) => o.value === objective);

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-5">
      <PageTitle
        title="Portfolio Builder"
        meta="CVXPY engine · Ledoit-Wolf Σ · Black-Litterman views"
      />

      <div className="flex flex-col gap-3">
        <UniverseCard
          assets={assets}
          onAdd={addAssets}
          onRemove={removeAsset}
          onSeedPortfolio={seedPortfolio}
        />

        <Card title="Constraints & objective">
          <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
            <label className="flex min-w-[210px] flex-col gap-1">
              <span className={FIELD_LABEL_CLASS}>Objective</span>
              <select
                value={objective}
                onChange={(e) => setObjective(e.target.value as BuilderObjective)}
                aria-label="Optimization objective"
                className={INPUT_CLASS}
              >
                {OBJECTIVES.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <NumField
              label="Cap per asset %"
              value={capPct}
              onChange={setCapPct}
              placeholder="25 (blank = uncapped)"
              width="w-[150px]"
            />
            <NumField
              label="Min weight % (opt.)"
              value={minWeightPct}
              onChange={setMinWeightPct}
              placeholder="—"
              width="w-[140px]"
            />
            <NumField
              label="Window (days)"
              value={windowDays}
              onChange={setWindowDays}
              placeholder="730"
              width="w-[120px]"
            />
          </div>
          {objectiveDef && (
            <p className="ix-fs mb-0 mt-2.5 text-text-muted">
              {objectiveDef.description}
            </p>
          )}
        </Card>

        <ViewsCard
          open={viewsOpen}
          onToggle={() => setViewsOpen((v) => !v)}
          views={views}
          setViews={setViews}
          assets={assets}
          blUtilityWithoutViews={objective === "bl_utility" && views.length === 0}
        />

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onRun}
            disabled={!canRun || mutation.isPending}
            className={`h-[34px] bg-accent px-5 text-[12.5px] font-bold text-on-accent transition-colors hover:bg-accent-muted disabled:cursor-not-allowed disabled:opacity-40 ${
              mutation.isPending ? "opacity-70" : ""
            }`}
          >
            {mutation.isPending ? "Optimizing…" : "Suggest weights"}
          </button>
          {assets.length < 2 && (
            <span className="ix-fs text-text-muted">
              Add at least 2 assets to optimize.
            </span>
          )}
          {assets.length >= 2 && !viewsValid && (
            <span className="ix-fs text-text-muted">
              Complete or remove incomplete views to run.
            </span>
          )}
        </div>

        {/* ── Result area ─────────────────────────────────────────────── */}
        {mutation.isPending ? (
          <ResultsSkeleton />
        ) : mutation.isError ? (
          <ErrorPanel
            title="Optimization failed"
            message={mutation.error.message}
            onRetry={onRun}
          />
        ) : mutation.data ? (
          <ResultsPanel
            key={mutation.submittedAt}
            result={mutation.data}
            objective={objective}
            assetsByKey={assetsByKey}
            base={base}
            colors={colors}
          />
        ) : (
          <p className="ix-pad ix-fs m-0 border border-border bg-surface-2 text-text-muted">
            Assemble a universe (saved portfolio positions, funds or ad-hoc
            tickers), pick an objective, optionally add Black-Litterman views,
            then press Suggest weights.
          </p>
        )}
      </div>
    </div>
  );
}

function NumField({
  label,
  value,
  onChange,
  placeholder,
  width,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  width: string;
}) {
  return (
    <label className={`flex ${width} flex-col gap-1`}>
      <span className={FIELD_LABEL_CLASS}>{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        inputMode="decimal"
        aria-label={label}
        className={`${INPUT_CLASS} tabular-nums`}
      />
    </label>
  );
}

function ResultsSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Optimizing portfolio"
      className="flex animate-pulse flex-col gap-px"
    >
      <div className="h-[84px] bg-surface-2" />
      <div className="h-[320px] bg-surface-2" />
    </div>
  );
}
