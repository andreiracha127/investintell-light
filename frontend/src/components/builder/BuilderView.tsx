"use client";

/**
 * Portfolio Builder (Claude Design) — optimize weights either over a
 * hand-picked basket ("Test a basket": unified stock/fund search + saved-
 * portfolio import) or over the filtered+ranked fund universe ("Search the
 * fund universe": no manual tickers). Set the goal + guardrails, optionally
 * express advanced views, and POST /builder/optimize. The backend computes ALL
 * finance; this view only collects inputs and renders the response. 422s
 * surface verbatim.
 *
 * Presentation upgrade only — same mutations, same /lib/api/client contracts,
 * same assetKey / universeDraftToSpec / toApiView logic. Plain-language copy
 * lives in BuilderCopy.tsx so the API enums stay code-keyed.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fetchPortfolioOverview,
  getBuilderOptimizeJob,
  postBuilderOptimize,
  postBuilderOptimizeAsync,
  type BuilderObjective,
  type BuilderViewIn,
  type OptimizeJobState,
  type OptimizeRequest,
  type OptimizeResponse,
  type PortfolioOverview,
} from "@/lib/api/client";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { InfoDot } from "@/components/ui/panels";
import { ErrorPanel } from "@/components/screener/shared";

import {
  assetKey,
  defaultUniverseDraft,
  toRef,
  universeDraftToSpec,
  type UniverseAsset,
  type UniverseDraft,
  type Mandate,
  MANDATE_CVAR_PRESETS,
  objectivesForBroad,
  resolveObjectiveForBroad,
} from "./assets";
import { OBJECTIVE_COPY, FIELD_COPY, METHOD_ITEMS, METHOD_FOOTNOTE } from "./BuilderCopy";
import { UniverseCard } from "./UniverseCard";
import { FundUniverseCard } from "./FundUniverseCard";
import { ViewsCard, toApiView, type ViewDraft } from "./ViewsCard";
import { ResultsPanel, type BaseAllocation } from "./ResultsPanel";

type BuilderMode = "simulate" | "universe";

const MODES: {
  value: BuilderMode;
  label: string;
  hint: string;
}[] = [
  {
    value: "simulate",
    label: "Test a basket",
    hint: "Pick stocks & funds",
  },
  {
    value: "universe",
    label: "Search the fund universe",
    hint: "Optimize a filtered set",
  },
];

const MANDATES: { value: Mandate; label: string }[] = [
  { value: "conservative", label: "Conservative" },
  { value: "defensive", label: "Defensive" },
  { value: "moderate_conservative", label: "Moderately conservative" },
  { value: "moderate", label: "Moderate" },
  { value: "balanced", label: "Balanced" },
  { value: "moderate_aggressive", label: "Moderately aggressive" },
  { value: "aggressive", label: "Aggressive" },
  { value: "growth", label: "Growth" },
];

const DEFAULT_MANDATE: Mandate = "moderate";

const AS_OF = "Jun 18, 2026";

/** A broad-universe job is done once it reaches a terminal lifecycle state. */
function isTerminalJob(status: OptimizeJobState | undefined): boolean {
  return status === "succeeded" || status === "failed";
}

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

  /* ── How it works panel ────────────────────────────────────────────── */
  const [methodOpen, setMethodOpen] = useState(false);
  useEffect(() => {
    if (!methodOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMethodOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [methodOpen]);

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
  const [objective, setObjective] = useState<BuilderObjective>("max_return_cvar");
  const [capPct, setCapPct] = useState("25");
  const [minWeightPct, setMinWeightPct] = useState("");
  // Blank = full nav_timeseries history (backend default; the 2-year gate is
  // removed). A typed value opts into a narrower estimation window.
  const [windowDays, setWindowDays] = useState("");
  const [mandate, setMandate] = useState<Mandate>(DEFAULT_MANDATE);
  const [cvarLimitPct, setCvarLimitPct] = useState(
    String(MANDATE_CVAR_PRESETS[DEFAULT_MANDATE]),
  );

  const onMandateChange = (next: Mandate) => {
    setMandate(next);
    setCvarLimitPct(String(MANDATE_CVAR_PRESETS[next]));
  };

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
  // Ranked/explicit: synchronous 200 + OptimizeResponse.
  const mutation = useMutation({
    mutationFn: (body: OptimizeRequest) => postBuilderOptimize(body),
  });

  // Broad-universe: dispatch a background job, then poll until terminal. The
  // dispatch mutation only carries the job_id; the poll query owns the result.
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobRequest, setJobRequest] = useState<OptimizeRequest | null>(null);
  const dispatch = useMutation({
    mutationFn: (body: OptimizeRequest) => postBuilderOptimizeAsync(body),
    onSuccess: (accepted) => setJobId(accepted.job_id),
  });
  const jobQuery = useQuery({
    queryKey: ["optimizeJob", jobId],
    queryFn: () => getBuilderOptimizeJob(jobId as string),
    enabled: jobId !== null,
    // Poll every 1.5s until the job reaches a terminal state, then stop.
    refetchInterval: (query) =>
      isTerminalJob(query.state.data?.status) ? false : 1500,
  });

  const resetRuns = () => {
    mutation.reset();
    dispatch.reset();
    setJobId(null);
    setJobRequest(null);
  };

  const switchMode = (next: BuilderMode) => {
    if (next === mode) return;
    setMode(next);
    resetRuns();
  };

  const cap = parseNum(capPct);
  const windowVal = parseNum(windowDays);
  const minWeight = parseNum(minWeightPct);
  const delta = parseNum(deltaText);
  const tau = parseNum(tauText);
  const cvarLimit = parseNum(cvarLimitPct);
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
  const cvarLimitOk =
    objective !== "max_return_cvar" || (cvarLimit !== null && cvarLimit > 0);
  const universeOk = universeCount === null || universeCount >= 2;

  const canRun =
    windowOk &&
    capOk &&
    blParamsOk &&
    cvarLimitOk &&
    (mode === "simulate"
      ? assets.length >= 2 && viewsValid
      : universeOk);

  const runPending = mutation.isPending || dispatch.isPending;

  const onRun = () => {
    if (!canRun || runPending) return;
    const constraints = {
      cap: cap !== null ? cap / 100 : null,
      min_weight: minWeight !== null ? minWeight / 100 : null,
    };
    const common = {
      objective,
      constraints,
      window_days: windowVal,
      mandate,
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
      ...(objective === "max_return_cvar" && cvarLimit !== null
        ? { cvar_limit: cvarLimit / 100 }
        : {}),
    };
    if (mode === "universe") {
      const universeBody: OptimizeRequest = {
        ...common,
        universe: universeDraftToSpec(universeDraft, universeKeptIds),
      };
      // Broad universe runs ASYNC (backend answers 202 + job_id, then polled);
      // a narrow ranked universe stays on the synchronous mutation.
      if (universeDraft.broadUniverse) {
        resetRuns();
        setJobRequest(universeBody);
        dispatch.mutate(universeBody);
      } else {
        mutation.mutate(universeBody);
      }
      return;
    }
    const completed = apiViews.filter((v): v is BuilderViewIn => v !== null);
    mutation.mutate({
      ...common,
      assets: assets.map(toRef),
      ...(completed.length > 0 && { views: completed }),
    });
  };

  const objectiveCopy = OBJECTIVE_COPY[objective];
  const broadUniverse = mode === "universe" && universeDraft.broadUniverse;
  const visibleObjectives = objectivesForBroad(broadUniverse);
  // Entering broad mode while a mu-based objective is selected silently resets
  // it to the mu-free default (the dropdown also hides it). Functional update
  // keeps `objective` out of the dependency list.
  useEffect(() => {
    setObjective((o) => resolveObjectiveForBroad(o, broadUniverse));
  }, [broadUniverse]);

  // The run that produced the visible result: the sync mutation's variables, or
  // the dispatched broad-universe request held in jobRequest.
  const submittedRequest = mutation.variables ?? jobRequest ?? undefined;
  const resultObjective = submittedRequest?.objective ?? objective;
  const resultConstraints = {
    cap: submittedRequest
      ? (submittedRequest.constraints.cap ?? null)
      : cap !== null
        ? cap / 100
        : null,
    min_weight: submittedRequest
      ? (submittedRequest.constraints.min_weight ?? null)
      : minWeight !== null
        ? minWeight / 100
        : null,
  };
  const resultWindowDays = submittedRequest
    ? (submittedRequest.window_days ?? null)
    : windowVal;
  const resultCvarLimit =
    resultObjective === "max_return_cvar"
      ? submittedRequest
        ? (submittedRequest.cvar_limit ?? null)
        : cvarLimit !== null
          ? cvarLimit / 100
          : null
      : null;
  const resultCvarLimitPct =
    resultObjective === "max_return_cvar"
      ? submittedRequest
        ? submittedRequest.cvar_limit != null
          ? String(submittedRequest.cvar_limit * 100)
          : null
        : cvarLimitPct
      : null;

  /* ── Unified run state across the sync and broad-async paths ─────────── */
  const jobStatus = jobQuery.data?.status;
  // "Optimizing…" while dispatching, before the first poll, or while the job is
  // pending/running on the backend.
  const jobOptimizing =
    jobId !== null &&
    (dispatch.isPending ||
      jobStatus === undefined ||
      jobStatus === "pending" ||
      jobStatus === "running");
  const jobResult: OptimizeResponse | null =
    jobStatus === "succeeded" && jobQuery.data?.result
      ? (jobQuery.data.result as OptimizeResponse)
      : null;
  // Surface backend job failures (verbatim error) and dispatch/poll transport
  // errors through the same error panel as the sync path.
  const jobErrorMessage =
    jobStatus === "failed"
      ? (jobQuery.data?.error ?? "Optimization failed")
      : dispatch.isError
        ? dispatch.error.message
        : jobQuery.isError
          ? jobQuery.error.message
          : null;

  const showOptimizing = mutation.isPending || jobOptimizing;
  const resultData = mutation.data ?? jobResult;
  const errorMessage = mutation.isError ? mutation.error.message : jobErrorMessage;

  const runHint = !canRun
    ? mode === "simulate" && assets.length < 2
      ? "Add at least two holdings to optimize."
      : "Resolve the highlighted inputs to optimize."
    : objective === "bl_utility" && views.length === 0
      ? "Tip: add a view in Advanced to tilt away from market weights."
      : "Re-optimizes with your current goal and guardrails.";

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-5">
      {/* ── Workspace header ──────────────────────────────────────────── */}
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3.5">
        <div>
          <h1 className="ix-title m-0 text-[clamp(22px,3.5vw,28px)]">
            Portfolio builder
          </h1>
          <div className="mb-1.5 mt-2 h-[3px] w-[34px] bg-accent" />
          <div className="max-w-[560px] text-[12px] text-text-secondary">
            Pick holdings, set your risk, and get suggested weights.
          </div>
        </div>
        <button
          type="button"
          onClick={() => setMethodOpen(true)}
          className="inline-flex h-[32px] items-center gap-[7px] border border-border-strong bg-field px-3 text-[12px] text-text-secondary transition-colors hover:bg-layer-hover"
        >
          <InfoDot tip="How the optimizer works" />
          How it works
        </button>
      </div>

      {/* ── Mode toggle + estimation chip ─────────────────────────────── */}
      <div className="mb-3.5 flex flex-wrap items-center gap-3.5">
        <div
          role="tablist"
          aria-label="Builder mode"
          className="flex border border-border-strong"
        >
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              role="tab"
              aria-selected={mode === m.value}
              onClick={() => switchMode(m.value)}
              className={`px-4 py-2 text-left leading-tight transition-colors ${
                mode === m.value
                  ? "bg-accent text-on-accent"
                  : "bg-field text-text-secondary hover:bg-layer-hover"
              }`}
            >
              <span className="block text-[12.5px] font-bold">{m.label}</span>
              <span className="block text-[10.5px] font-normal opacity-85">
                {m.hint}
              </span>
            </button>
          ))}
        </div>
        <span className="inline-flex items-center gap-1.5 border border-border bg-field px-2.5 py-1 text-[11px] text-text-muted">
          <span title="Estimates use daily prices and fund NAV history through the date shown.">
            Estimation data
          </span>{" "}
          · {AS_OF}
        </span>
      </div>

      <div className="flex flex-col gap-3.5">
        {deepLinkQuery.isError && (
          <p
            role="alert"
            className="ix-fs m-0 border-l-[3px] border-loss bg-surface-2 px-2.5 py-1.5 text-loss"
          >
            Couldn&apos;t import portfolio #{portfolioParam} — add assets
            manually. ({deepLinkQuery.error.message})
          </p>
        )}

        {/* ── ① Your basket / universe ──────────────────────────────── */}
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

        {/* ── ② Goal & guardrails ───────────────────────────────────── */}
        <NumberedSection step={2} title="Goal & guardrails">
          <div className="flex flex-wrap items-start gap-x-[18px] gap-y-4">
            <label className="flex w-[300px] max-w-full flex-col gap-1.5">
              <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
                {FIELD_COPY.objective.label}
                <InfoDot tip={objectiveCopy.tip} />
              </span>
              <select
                value={objective}
                onChange={(e) => setObjective(e.target.value as BuilderObjective)}
                aria-label="Optimization objective"
                className={SELECT_CLASS}
              >
                {visibleObjectives.map((o) => (
                  <option key={o.value} value={o.value}>
                    {OBJECTIVE_COPY[o.value].label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-[200px] flex-col gap-1.5">
              <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
                {FIELD_COPY.mandate.label}
                <InfoDot tip={FIELD_COPY.mandate.tip} />
              </span>
              <select
                value={mandate}
                onChange={(e) => onMandateChange(e.target.value as Mandate)}
                aria-label="Risk mandate"
                className={SELECT_CLASS}
              >
                {MANDATES.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <p className="ix-fs mb-0 mt-3 max-w-[680px] leading-relaxed text-text-secondary">
            {objectiveCopy.description}
          </p>

          {broadUniverse && (
            <p className="ix-fs mb-0 mt-2 max-w-[680px] leading-relaxed text-text-muted">
              Broad mode allocates on a pairwise covariance, so only
              covariance-based goals are available — &ldquo;Smallest worst-case
              loss&rdquo; (needs a common scenario window) and &ldquo;Follow my
              views&rdquo; (return-based) are not.
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-start gap-x-[22px] gap-y-4 border-t border-border pt-4">
            {objectiveCopy.usesLossLimit && (
              <AffixField
                label={FIELD_COPY.lossLimit.label}
                tip={FIELD_COPY.lossLimit.tip}
                affix={FIELD_COPY.lossLimit.affix}
                value={cvarLimitPct}
                onChange={setCvarLimitPct}
                ariaLabel="Daily loss limit"
                width="w-[172px]"
              />
            )}
            <AffixField
              label={FIELD_COPY.cap.label}
              tip={FIELD_COPY.cap.tip}
              affix={FIELD_COPY.cap.affix}
              value={capPct}
              onChange={setCapPct}
              placeholder="25"
              ariaLabel="Max per holding"
              width="w-[172px]"
            />
            <AffixField
              label={FIELD_COPY.minWeight.label}
              optional
              affix={FIELD_COPY.minWeight.affix}
              value={minWeightPct}
              onChange={setMinWeightPct}
              placeholder="—"
              ariaLabel="Min per holding"
              width="w-[172px]"
            />
            <AffixField
              label={FIELD_COPY.window.label}
              tip={FIELD_COPY.window.tip}
              affix={FIELD_COPY.window.affix}
              value={windowDays}
              onChange={setWindowDays}
              placeholder="all history"
              ariaLabel="History window"
              width="w-[208px]"
            />
          </div>
        </NumberedSection>

        {/* ── ③ Advanced (your market views) ────────────────────────── */}
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

        {/* ── Run ───────────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-center gap-3.5">
          <button
            type="button"
            onClick={onRun}
            disabled={!canRun || showOptimizing}
            className={`h-[38px] border border-accent bg-accent px-[22px] text-[13px] font-bold text-on-accent transition-colors hover:bg-accent-muted disabled:cursor-not-allowed disabled:opacity-40 ${
              showOptimizing ? "opacity-70" : ""
            }`}
          >
            {showOptimizing ? "Optimizing…" : "Suggest weights"}
          </button>
          <span className="ix-fs text-text-muted">{runHint}</span>
          {!cvarLimitOk && (
            <span className="ix-fs text-loss">
              &ldquo;Most return within a loss limit&rdquo; needs a daily loss
              limit — set a positive value.
            </span>
          )}
          {!blParamsOk && (
            <span className="ix-fs text-loss">
              &ldquo;Follow my views&rdquo; needs positive model parameters (δ,
              τ) — check the Advanced section.
            </span>
          )}
          {mode === "simulate" && assets.length >= 2 && !viewsValid && (
            <span className="ix-fs text-loss">
              Complete or remove incomplete views to run.
            </span>
          )}
          {mode === "universe" && !universeOk && (
            <span className="ix-fs text-loss">
              Fewer than 2 funds match — relax the filters.
            </span>
          )}
        </div>

        {/* ── Result area ─────────────────────────────────────────────── */}
        {showOptimizing ? (
          <ResultsSkeleton />
        ) : errorMessage ? (
          <ErrorPanel
            title="Optimization failed"
            message={errorMessage}
            onRetry={onRun}
          />
        ) : resultData ? (
          <ResultsPanel
            key={mutation.data ? mutation.submittedAt : (jobId ?? "job")}
            result={resultData}
            objective={resultObjective}
            constraints={resultConstraints}
            windowDays={resultWindowDays}
            cvarLimit={resultCvarLimit}
            assetsByKey={assetsByKey}
            base={mode === "simulate" ? base : null}
            colors={colors}
            grouped={mode === "universe"}
            cvarLimitPct={resultCvarLimitPct}
          />
        ) : (
          <p className="ix-pad ix-fs m-0 border border-border bg-surface-2 text-text-muted">
            {mode === "simulate"
              ? "Search and add stocks or funds (or import a saved portfolio), pick a goal, optionally add advanced views, then press Suggest weights."
              : "Filter and rank the fund universe, pick a goal, then press Suggest weights — the optimizer selects the funds for you."}
          </p>
        )}
      </div>

      {/* ── How it works side panel ───────────────────────────────────── */}
      {methodOpen && (
        <MethodPanel onClose={() => setMethodOpen(false)} />
      )}
    </div>
  );
}

const SELECT_CLASS =
  "h-[36px] border border-border-strong bg-field px-2.5 text-[13px] text-text-primary outline-none focus:border-accent";

function NumberedSection({
  step,
  title,
  children,
}: {
  step: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border border-border bg-surface-2">
      <div className="flex items-center gap-2.5 border-b border-border px-[var(--ix-pad)] py-3">
        <h2 className="ix-label m-0 flex items-center gap-2">
          <span className="inline-flex h-[18px] w-[18px] items-center justify-center bg-accent text-[10px] text-on-accent">
            {step}
          </span>
          {title}
        </h2>
      </div>
      <div className="ix-pad">{children}</div>
    </section>
  );
}

function AffixField({
  label,
  tip,
  optional,
  affix,
  value,
  onChange,
  placeholder,
  ariaLabel,
  width,
}: {
  label: string;
  tip?: string;
  optional?: boolean;
  affix: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  ariaLabel: string;
  width: string;
}) {
  return (
    <div className={`flex ${width} flex-col gap-1.5`}>
      <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
        {label}
        {optional && (
          <span className="font-normal normal-case tracking-normal text-text-muted">
            (optional)
          </span>
        )}
        {tip && <InfoDot tip={tip} />}
      </span>
      <div className="flex h-[36px] items-center border border-border-strong bg-field focus-within:border-accent">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          inputMode="decimal"
          aria-label={ariaLabel}
          className="h-full min-w-0 flex-1 border-0 bg-transparent pl-2.5 text-right text-[14px] tabular-nums text-text-primary outline-none placeholder:text-text-muted"
        />
        <span className="whitespace-nowrap px-2.5 text-[12px] text-text-muted">
          {affix}
        </span>
      </div>
    </div>
  );
}

function MethodPanel({ onClose }: { onClose: () => void }) {
  return (
    <>
      <div
        onClick={onClose}
        className="fixed inset-0 z-[70] bg-black/30"
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-label="How it works"
        className="fixed inset-y-0 right-0 z-[71] flex h-screen w-[380px] max-w-[92vw] flex-col overflow-auto border-l border-border-strong bg-surface-2 shadow-[-6px_0_24px_rgba(0,0,0,0.16)]"
      >
        <div className="sticky top-0 flex items-center justify-between gap-2.5 border-b border-border bg-surface-2 px-[var(--ix-pad)] py-4">
          <h2 className="ix-title m-0 text-[16px]">How it works</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="border-0 bg-transparent text-[18px] text-text-muted hover:text-text-primary"
          >
            ×
          </button>
        </div>
        <div className="ix-pad flex flex-col gap-4">
          {METHOD_ITEMS.map((m) => (
            <div key={m.title}>
              <h3 className="m-0 mb-1 text-[12.5px] font-bold text-text-primary">
                {m.title}
              </h3>
              <p className="m-0 text-[12px] leading-relaxed text-text-secondary">
                {m.body}
              </p>
            </div>
          ))}
          <p className="m-0 border-t border-border pt-3 text-[10.5px] text-text-muted">
            {METHOD_FOOTNOTE}
          </p>
        </div>
      </aside>
    </>
  );
}

function ResultsSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Optimizing portfolio"
      className="flex animate-pulse flex-col gap-px"
    >
      <div className="h-[88px] bg-surface-2" />
      <div className="h-[320px] bg-surface-2" />
    </div>
  );
}
