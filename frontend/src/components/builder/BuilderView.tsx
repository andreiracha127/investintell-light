"use client";

/**
 * Portfolio Builder (F8.5) — optimize weights either over a hand-picked basket
 * ("Simulate": unified stock/fund search + saved-portfolio import) or over the
 * filtered+ranked fund universe ("Fund universe": no manual tickers). Set
 * constraints + objective, optionally express advanced views, and POST
 * /builder/optimize. The backend computes ALL finance; this view only collects
 * inputs and renders the response. 422s surface verbatim.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fetchPortfolioOverview,
  postBuilderOptimize,
  type BuilderObjective,
  type BuilderViewIn,
  type OptimizeRequest,
  type PortfolioOverview,
} from "@/lib/api/client";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { Card, PageTitle } from "@/components/ui/panels";
import {
  ErrorPanel,
  FIELD_LABEL_CLASS,
  INPUT_CLASS,
} from "@/components/screener/shared";

import {
  assetKey,
  defaultUniverseDraft,
  toRef,
  universeDraftToSpec,
  type UniverseAsset,
  type UniverseDraft,
  OBJECTIVES,
  objectivesForBroad,
  resolveObjectiveForBroad,
} from "./assets";
import { UniverseCard } from "./UniverseCard";
import { FundUniverseCard } from "./FundUniverseCard";
import { ViewsCard, toApiView, type ViewDraft } from "./ViewsCard";
import { ResultsPanel, type BaseAllocation } from "./ResultsPanel";

type BuilderMode = "simulate" | "universe";

const MODES: { value: BuilderMode; label: string; hint: string }[] = [
  { value: "simulate", label: "Simulate", hint: "Pick stocks & funds to test" },
  { value: "universe", label: "Fund universe", hint: "Optimize a filtered set" },
];

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

  /* ── Mode ──────────────────────────────────────────────────────────── */
  const [mode, setMode] = useState<BuilderMode>("simulate");

  /* ── Simulate universe ─────────────────────────────────────────────── */
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

  const seedPortfolio = useCallback((overview: PortfolioOverview) => {
    setAssets((prev) => {
      const seen = new Set(prev.map(assetKey));
      const fresh = overview.positions
        .map((p) => ({ kind: "equity" as const, ticker: p.ticker }))
        .filter((a) => !seen.has(assetKey(a)));
      return fresh.length === 0 ? prev : [...prev, ...fresh];
    });
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
  }, []);

  const assetsByKey = useMemo(
    () => new Map(assets.map((a) => [assetKey(a), a])),
    [assets],
  );

  /* ── Fund universe ─────────────────────────────────────────────────── */
  const [universeDraft, setUniverseDraft] = useState<UniverseDraft>(defaultUniverseDraft);
  const [universeCount, setUniverseCount] = useState<number | null>(null);
  // Kept fund ids when the user prunes the previewed top-N; [] = keep all
  // (send no explicit list → backend uses the full top-N).
  const [universeKeptIds, setUniverseKeptIds] = useState<string[]>([]);

  /* ── Constraints & objective ───────────────────────────────────────── */
  const [objective, setObjective] = useState<BuilderObjective>("min_cvar");
  const [capPct, setCapPct] = useState("25");
  const [minWeightPct, setMinWeightPct] = useState("");
  // Blank = full nav_timeseries history (backend default; the 2-year gate is
  // removed). A typed value opts into a narrower estimation window.
  const [windowDays, setWindowDays] = useState("");

  /* ── Advanced (views + BL model params) ────────────────────────────── */
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [views, setViews] = useState<ViewDraft[]>([]);
  const [deltaText, setDeltaText] = useState("2.5");
  const [tauText, setTauText] = useState("0.05");

  const apiViews: (BuilderViewIn | null)[] = views.map((v) =>
    toApiView(v, assetsByKey),
  );
  const viewsValid = apiViews.every((v) => v !== null);

  /* ── Deep-link: /builder?portfolio=<id> auto-seeds the Simulate basket ── */
  const searchParams = useSearchParams();
  const portfolioParam = searchParams.get("portfolio");
  const seededRef = useRef(false);
  const deepLinkQuery = useQuery({
    queryKey: ["builder-deeplink", portfolioParam],
    queryFn: ({ signal }) =>
      fetchPortfolioOverview(Number(portfolioParam), signal),
    enabled:
      portfolioParam !== null && /^\d+$/.test(portfolioParam) && !seededRef.current,
    staleTime: 60_000,
  });
  useEffect(() => {
    if (deepLinkQuery.data && !seededRef.current) {
      seededRef.current = true;
      setMode("simulate");
      seedPortfolio(deepLinkQuery.data);
    }
  }, [deepLinkQuery.data, seedPortfolio]);

  /* ── Run ───────────────────────────────────────────────────────────── */
  const mutation = useMutation({
    mutationFn: (body: OptimizeRequest) => postBuilderOptimize(body),
  });

  const switchMode = (next: BuilderMode) => {
    if (next === mode) return;
    setMode(next);
    mutation.reset();
  };

  const cap = parseNum(capPct);
  const windowVal = parseNum(windowDays);
  const minWeight = parseNum(minWeightPct);
  const delta = parseNum(deltaText);
  const tau = parseNum(tauText);
  // Blank cap = uncapped (null); a typed but non-numeric cap blocks the run.
  const capOk = capPct.trim() === "" || cap !== null;
  // Blank window = full history (null → backend uses all of nav_timeseries);
  // a typed but non-numeric window blocks the run (mirrors cap).
  const windowOk = windowDays.trim() === "" || windowVal !== null;
  // δ/τ only drive the Black-Litterman utility objective; every other objective
  // ignores them, so a blank/edited value must not block those runs.
  const blParamsOk =
    objective !== "bl_utility" ||
    (delta !== null && delta > 0 && tau !== null && tau > 0);
  const universeOk = universeCount === null || universeCount >= 2;

  const canRun =
    windowOk &&
    capOk &&
    blParamsOk &&
    (mode === "simulate"
      ? assets.length >= 2 && viewsValid
      : universeOk);

  const onRun = () => {
    if (!canRun || mutation.isPending) return;
    const constraints = {
      cap: cap !== null ? cap / 100 : null,
      min_weight: minWeight !== null ? minWeight / 100 : null,
    };
    const common = {
      objective,
      constraints,
      window_days: windowVal,
      // turnover_lambda has a backend default (0.0) but the generated contract
      // types it as required; the builder has no turnover control, so send 0
      // (no turnover penalty — the backend skips the current_weights guard).
      turnover_lambda: 0,
      // Always send valid BL params; non-BL objectives fall back to defaults
      // (the backend schema validates δ>0, τ>0 regardless of objective).
      bl: {
        delta: delta !== null && delta > 0 ? delta : 2.5,
        tau: tau !== null && tau > 0 ? tau : 0.05,
      },
    };
    if (mode === "universe") {
      mutation.mutate({
        ...common,
        universe: universeDraftToSpec(universeDraft, universeKeptIds),
      });
      return;
    }
    const completed = apiViews.filter((v): v is BuilderViewIn => v !== null);
    mutation.mutate({
      ...common,
      assets: assets.map(toRef),
      ...(completed.length > 0 && { views: completed }),
    });
  };

  const objectiveDef = OBJECTIVES.find((o) => o.value === objective);
  const broadUniverse = mode === "universe" && universeDraft.broadUniverse;
  const visibleObjectives = objectivesForBroad(broadUniverse);
  // Entering broad mode while a mu-based objective is selected silently resets
  // it to the mu-free default (the dropdown also hides it). Functional update
  // keeps `objective` out of the dependency list.
  useEffect(() => {
    setObjective((o) => resolveObjectiveForBroad(o, broadUniverse));
  }, [broadUniverse]);

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-5">
      <PageTitle
        title="Portfolio Builder"
        meta="CVXPY engine · Ledoit-Wolf Σ · Black-Litterman views"
      />

      <div className="flex flex-col gap-3">
        {/* ── Mode toggle ─────────────────────────────────────────────── */}
        <div className="flex items-stretch border border-border-strong w-fit">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => switchMode(m.value)}
              aria-pressed={mode === m.value}
              title={m.hint}
              className={`flex h-[34px] flex-col justify-center px-4 text-[12.5px] transition-colors ${
                mode === m.value
                  ? "bg-accent font-bold text-on-accent"
                  : "bg-field font-medium text-text-secondary hover:bg-layer-hover"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {deepLinkQuery.isError && (
          <p
            role="alert"
            className="ix-fs m-0 border-l-[3px] border-loss bg-surface-2 px-2.5 py-1.5 text-loss"
          >
            Couldn&apos;t import portfolio #{portfolioParam} — add assets
            manually. ({deepLinkQuery.error.message})
          </p>
        )}

        {mode === "simulate" ? (
          <UniverseCard
            assets={assets}
            onAdd={addAssets}
            onRemove={removeAsset}
            onSeedPortfolio={seedPortfolio}
          />
        ) : (
          <FundUniverseCard
            draft={universeDraft}
            setDraft={setUniverseDraft}
            onCount={setUniverseCount}
            onSelectionChange={setUniverseKeptIds}
          />
        )}

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
                {visibleObjectives.map((o) => (
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
              label="Window (days, opt.)"
              value={windowDays}
              onChange={setWindowDays}
              placeholder="blank = full history"
              width="w-[180px]"
            />
          </div>
          {objectiveDef && (
            <p className="ix-fs mb-0 mt-2.5 text-text-muted">
              {objectiveDef.description}
            </p>
          )}
          {broadUniverse && (
            <p className="ix-fs mb-0 mt-2 text-text-muted">
              Broad mode allocates on a pairwise covariance, so only
              covariance-based objectives are available — Min CVaR (needs a
              common scenario window) and BL max utility (return-based, gate G5)
              are not.
            </p>
          )}
        </Card>

        <ViewsCard
          open={advancedOpen}
          onToggle={() => setAdvancedOpen((v) => !v)}
          showViews={mode === "simulate"}
          views={views}
          setViews={setViews}
          assets={assets}
          blUtilityWithoutViews={objective === "bl_utility" && views.length === 0}
          delta={deltaText}
          tau={tauText}
          onDelta={setDeltaText}
          onTau={setTauText}
        />

        <div className="flex flex-wrap items-center gap-3">
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
          {mode === "simulate" && assets.length < 2 && (
            <span className="ix-fs text-text-muted">
              Add at least 2 assets to optimize.
            </span>
          )}
          {mode === "simulate" && assets.length >= 2 && !viewsValid && (
            <span className="ix-fs text-text-muted">
              Complete or remove incomplete views to run.
            </span>
          )}
          {mode === "universe" && !universeOk && (
            <span className="ix-fs text-text-muted">
              Fewer than 2 funds match — relax the filters.
            </span>
          )}
          {!blParamsOk && (
            <span className="ix-fs text-text-muted">
              BL max utility needs positive model parameters (δ, τ) — check the
              Advanced section.
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
            base={mode === "simulate" ? base : null}
            colors={colors}
            grouped={mode === "universe"}
          />
        ) : (
          <p className="ix-pad ix-fs m-0 border border-border bg-surface-2 text-text-muted">
            {mode === "simulate"
              ? "Search and add stocks or funds (or import a saved portfolio), pick an objective, optionally add advanced views, then press Suggest weights."
              : "Filter and rank the fund universe, pick an objective, then press Suggest weights — the optimizer selects the funds for you."}
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
