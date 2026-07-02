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
  postBuilderOptimize,
  type BuilderObjective,
  type BuilderViewIn,
  type OptimizeRequest,
  type PortfolioOverview,
} from "@/lib/api/client";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { InfoDot, PAGE_CONTAINER_CLASS } from "@/components/ui/panels";
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
import { OBJECTIVE_COPY, FIELD_COPY } from "./BuilderCopy";
import { UniverseCard } from "./UniverseCard";
import { FundUniverseCard } from "./FundUniverseCard";
import { ViewsCard, toApiView, type ViewDraft } from "./ViewsCard";
import { ResultsPanel, type BaseAllocation } from "./ResultsPanel";

type BuilderMode = "simulate" | "universe";

const MODES: {
  value: BuilderMode;
  label: string;
}[] = [
  {
    value: "simulate",
    label: "Basket",
  },
  {
    value: "universe",
    label: "Fund universe",
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

  const objectiveCopy = OBJECTIVE_COPY[objective];
  const broadUniverse = mode === "universe" && universeDraft.broadUniverse;
  const visibleObjectives = objectivesForBroad(broadUniverse);
  // Entering broad mode while a mu-based objective is selected silently resets
  // it to the mu-free default (the dropdown also hides it). Functional update
  // keeps `objective` out of the dependency list.
  useEffect(() => {
    setObjective((o) => resolveObjectiveForBroad(o, broadUniverse));
  }, [broadUniverse]);

  const submittedRequest = mutation.variables;
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

  const runHint = !canRun
    ? mode === "simulate" && assets.length < 2
      ? "Add at least two holdings to optimize."
      : "Resolve the highlighted inputs to optimize."
    : objective === "bl_utility" && views.length === 0
      ? "No views: market-weight baseline."
      : null;

  return (
    <div className={PAGE_CONTAINER_CLASS}>
      {/* ── Workspace header ──────────────────────────────────────────── */}
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3.5">
        <div>
          <h1 className="ix-title m-0 text-[clamp(22px,3.5vw,28px)]">
            Portfolio builder
          </h1>
          <div className="mb-1.5 mt-2 h-[3px] w-[34px] bg-accent" />
        </div>
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
            </button>
          ))}
        </div>
        <span className="inline-flex items-center gap-1.5 border border-border bg-field px-2.5 py-1 text-[11px] text-text-muted">
          <span>Data</span>{" "}
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

          {broadUniverse && (
            <p className="ix-fs mb-0 mt-3 max-w-[680px] text-text-muted">
              Broad mode: covariance objectives only.
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
            disabled={!canRun || mutation.isPending}
            className={`h-[38px] border border-accent bg-accent px-[22px] text-[13px] font-bold text-on-accent transition-colors hover:bg-accent-muted disabled:cursor-not-allowed disabled:opacity-40 ${
              mutation.isPending ? "opacity-70" : ""
            }`}
          >
            {mutation.isPending ? "Optimizing…" : "Suggest weights"}
          </button>
          {runHint && <span className="ix-fs text-text-muted">{runHint}</span>}
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
            No run yet.
          </p>
        )}
      </div>
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
