"use client";

/**
 * Black-Litterman views card (collapsible). Each view is either absolute
 * ("asset returns q% a.a.") or relative ("long − short = q%"), with an
 * Idzorek confidence slider. Drafts reference universe assets by `assetKey`;
 * the parent converts complete drafts to the API shape.
 */
import type { BuilderViewIn } from "@/lib/api/client";
import { FIELD_LABEL_CLASS, INPUT_CLASS } from "@/components/screener/shared";

import { assetKey, assetTicker, toRef, type UniverseAsset } from "./assets";

export interface ViewDraft {
  /** Local list key — never sent to the backend. */
  id: number;
  type: "absolute" | "relative";
  /** assetKey of the subject (absolute) — "" while unset. */
  asset: string;
  /** assetKeys of the legs (relative) — "" while unset. */
  long: string;
  short: string;
  /** Expected return in % a.a. as typed (converted to fraction on submit). */
  qPct: string;
  confidence: number;
}

let nextDraftId = 1;
export function newViewDraft(): ViewDraft {
  return {
    id: nextDraftId++,
    type: "absolute",
    asset: "",
    long: "",
    short: "",
    qPct: "",
    confidence: 0.5,
  };
}

/** Parse the q input ("% a.a."): finite number or null. */
function parseQ(text: string): number | null {
  if (text.trim() === "") return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/**
 * Convert a draft to the API view, or null while incomplete/invalid
 * (unset asset, asset removed from the universe, non-numeric q,
 * relative view with identical legs).
 */
export function toApiView(
  draft: ViewDraft,
  assetsByKey: Map<string, UniverseAsset>,
): BuilderViewIn | null {
  const q = parseQ(draft.qPct);
  if (q === null) return null;
  if (draft.type === "absolute") {
    const asset = assetsByKey.get(draft.asset);
    if (!asset) return null;
    return { type: "absolute", asset: toRef(asset), q: q / 100, confidence: draft.confidence };
  }
  const long = assetsByKey.get(draft.long);
  const short = assetsByKey.get(draft.short);
  if (!long || !short || draft.long === draft.short) return null;
  return {
    type: "relative",
    long: toRef(long),
    short: toRef(short),
    q: q / 100,
    confidence: draft.confidence,
  };
}

/** Friendly confidence presets (Idzorek confidence ∈ (0,1]). */
const CONFIDENCE_LEVELS = [
  { label: "Low", value: 0.25 },
  { label: "Medium", value: 0.5 },
  { label: "High", value: 0.75 },
] as const;

export function ViewsCard({
  open,
  onToggle,
  showViews,
  views,
  setViews,
  assets,
  blUtilityWithoutViews,
  delta,
  tau,
  onDelta,
  onTau,
}: {
  open: boolean;
  onToggle: () => void;
  /** Market views only make sense for a hand-picked basket (Simulate mode). */
  showViews: boolean;
  views: ViewDraft[];
  setViews: (updater: (prev: ViewDraft[]) => ViewDraft[]) => void;
  assets: UniverseAsset[];
  blUtilityWithoutViews: boolean;
  /** Black-Litterman model parameters as raw text (validated by the parent). */
  delta: string;
  tau: string;
  onDelta: (value: string) => void;
  onTau: (value: string) => void;
}) {
  const update = (id: number, patch: Partial<ViewDraft>) =>
    setViews((prev) => prev.map((v) => (v.id === id ? { ...v, ...patch } : v)));
  const remove = (id: number) => setViews((prev) => prev.filter((v) => v.id !== id));

  const summary = showViews
    ? views.length === 0
      ? "optional — add your own return expectations"
      : `${views.length} view${views.length > 1 ? "s" : ""}`
    : "model parameters";

  return (
    <section className="border border-border bg-surface-2">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="ix-pad flex w-full items-center justify-between gap-2 text-left transition-colors hover:bg-layer-hover"
      >
        <h2 className="ix-label m-0">
          Advanced — your market views
          <span className="ml-2 font-normal normal-case tracking-normal text-text-secondary">
            · {summary}
          </span>
        </h2>
        <span aria-hidden className="text-[11px] text-text-muted">
          {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div className="ix-pad flex flex-col gap-4 border-t border-border pt-3">
          {showViews && (
            <div className="flex flex-col gap-3">
              <h3 className="ix-label m-0 text-text-secondary">Market views</h3>
              {views.map((view) => (
                <ViewRow
                  key={view.id}
                  view={view}
                  assets={assets}
                  onChange={(patch) => update(view.id, patch)}
                  onRemove={() => remove(view.id)}
                />
              ))}

              <div>
                <button
                  type="button"
                  onClick={() => setViews((prev) => [...prev, newViewDraft()])}
                  className="h-[30px] border border-border-strong bg-field px-3 text-[12px] text-text-secondary transition-colors hover:bg-layer-hover"
                >
                  + Add a view
                </button>
              </div>

              <p className="ix-fs m-0 text-text-muted">
                A view is your expectation for an asset (&ldquo;X returns 12% a
                year&rdquo;) or a pair (&ldquo;X beats Y by 5%&rdquo;). Views need
                a known AUM for every asset — funds only; equities and funds
                without AUM are rejected (422).
              </p>
              {blUtilityWithoutViews && (
                <p role="status" className="ix-fs m-0 border-l-[3px] border-accent bg-accent-wash px-2.5 py-1.5 text-text-secondary">
                  BL max utility with zero views reproduces the market-cap (AUM)
                  weights — add a view to express a tilt.
                </p>
              )}
            </div>
          )}

          {/* ── Model parameters (rarely changed) ───────────────────────── */}
          <div className="flex flex-col gap-2">
            <h3 className="ix-label m-0 text-text-secondary">Model parameters</h3>
            <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
              <ParamField
                label="Risk aversion (δ)"
                value={delta}
                onChange={onDelta}
                placeholder="2.5"
              />
              <ParamField
                label="Uncertainty (τ)"
                value={tau}
                onChange={onTau}
                placeholder="0.05"
              />
            </div>
            <p className="ix-fs m-0 text-text-muted">
              Black-Litterman tuning for the equilibrium prior. The defaults
              (δ=2.5, τ=0.05) suit most cases — leave them unless you know why.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}

function ParamField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <label className="flex w-[150px] flex-col gap-1">
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

function ViewRow({
  view,
  assets,
  onChange,
  onRemove,
}: {
  view: ViewDraft;
  assets: UniverseAsset[];
  onChange: (patch: Partial<ViewDraft>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3 border border-border bg-surface-1 px-3 py-2.5">
      <label className="flex flex-col gap-1">
        <span className={FIELD_LABEL_CLASS}>Type</span>
        <select
          value={view.type}
          onChange={(e) => onChange({ type: e.target.value as ViewDraft["type"] })}
          aria-label="View type"
          className={INPUT_CLASS}
        >
          <option value="absolute">Absolute</option>
          <option value="relative">Relative</option>
        </select>
      </label>

      {view.type === "absolute" ? (
        <AssetSelect
          label="Asset"
          value={view.asset}
          assets={assets}
          onChange={(asset) => onChange({ asset })}
        />
      ) : (
        <>
          <AssetSelect
            label="Long"
            value={view.long}
            assets={assets}
            onChange={(long) => onChange({ long })}
          />
          <AssetSelect
            label="Short"
            value={view.short}
            assets={assets}
            onChange={(short) => onChange({ short })}
          />
        </>
      )}

      <label className="flex w-[110px] flex-col gap-1">
        <span className={FIELD_LABEL_CLASS}>
          {view.type === "absolute" ? "Return % a.a." : "Spread % a.a."}
        </span>
        <input
          value={view.qPct}
          onChange={(e) => onChange({ qPct: e.target.value })}
          placeholder={view.type === "absolute" ? "12" : "5"}
          inputMode="decimal"
          aria-label="View expected return, percent per year"
          className={`${INPUT_CLASS} tabular-nums`}
        />
      </label>

      <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
        <span className={FIELD_LABEL_CLASS}>How sure are you?</span>
        <div
          role="radiogroup"
          aria-label="View confidence"
          className="flex items-stretch border border-border-strong"
        >
          {CONFIDENCE_LEVELS.map((lvl) => (
            <button
              key={lvl.label}
              type="button"
              role="radio"
              aria-checked={view.confidence === lvl.value}
              onClick={() => onChange({ confidence: lvl.value })}
              className={`h-[34px] px-3 text-[11.5px] transition-colors ${
                view.confidence === lvl.value
                  ? "bg-accent font-bold text-on-accent"
                  : "bg-field font-medium text-text-secondary hover:bg-layer-hover"
              }`}
            >
              {lvl.label}
            </button>
          ))}
        </div>
      </fieldset>

      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove view"
        className="ml-auto h-[30px] border border-border-strong bg-field px-3 text-[12px] text-text-secondary transition-colors hover:bg-layer-hover hover:text-loss"
      >
        Remove
      </button>
    </div>
  );
}

function AssetSelect({
  label,
  value,
  assets,
  onChange,
}: {
  label: string;
  value: string;
  assets: UniverseAsset[];
  onChange: (key: string) => void;
}) {
  return (
    <label className="flex min-w-[150px] flex-col gap-1">
      <span className={FIELD_LABEL_CLASS}>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={`View ${label.toLowerCase()} asset`}
        className={INPUT_CLASS}
      >
        <option value="">— select —</option>
        {assets.map((asset) => {
          const key = assetKey(asset);
          return (
            <option key={key} value={key}>
              {assetTicker(asset)}
              {asset.kind === "equity" ? " (equity)" : ""}
            </option>
          );
        })}
      </select>
    </label>
  );
}
