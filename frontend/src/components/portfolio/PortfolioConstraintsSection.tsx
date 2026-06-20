"use client";

/**
 * Construction-constraints editor for the portfolio overview page (Sprint B).
 *
 * Loads the persisted set via GET /portfolios/{id}/constraints, lets the user
 * edit the header limits (cap, min weight, overlap cap) and per-asset-class
 * min/max weight bounds, and PUTs the whole set back (replaced wholesale).
 *
 * Scale contract: the backend stores decimal fractions (0.30 = 30%). The form
 * works in PERCENT for readability and converts on load/save. Blank = no limit
 * of that kind (null); the backend treats null/empty as unconstrained.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getPortfolioConstraints,
  putPortfolioConstraints,
  type ClassLimit,
  type ConstraintAssetClass,
  type PortfolioConstraints,
  type PortfolioConstraintsPut,
} from "@/lib/api/client";
import { Card } from "@/components/ui/panels";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";

/** Asset classes the per-class bounds can constrain, with display labels. */
const ASSET_CLASS_OPTIONS: { value: ConstraintAssetClass; label: string }[] = [
  { value: "equity", label: "Equity" },
  { value: "fixed_income", label: "Fixed income" },
  { value: "cash", label: "Cash" },
  { value: "alternatives", label: "Alternatives" },
  { value: "multi_asset", label: "Multi-asset" },
];

/** Per-class min/max bounds as raw percent text (blank = no bound that side). */
type ClassLimitDraft = Partial<
  Record<ConstraintAssetClass, { min: string; max: string }>
>;

/** Decimal fraction -> percent text ("" for null). */
function fracToPct(value: number | null | undefined): string {
  return value == null ? "" : String(Math.round(value * 1e6) / 1e4);
}

/** Percent text -> decimal fraction (null for blank/invalid). */
function pctToFrac(text: string): number | null {
  if (text.trim() === "") return null;
  const v = Number(text);
  return Number.isFinite(v) ? v / 100 : null;
}

/** Build the per-class draft from the persisted class limits. */
function classLimitsToDraft(limits: ClassLimit[]): ClassLimitDraft {
  const draft: ClassLimitDraft = {};
  for (const limit of limits) {
    draft[limit.asset_class] = {
      min: fracToPct(limit.min_weight),
      max: fracToPct(limit.max_weight),
    };
  }
  return draft;
}

/** Convert the per-class draft into the API class_limits list. A class
 *  contributes only when at least one bound is set. */
function draftToClassLimits(draft: ClassLimitDraft): ClassLimit[] {
  const out: ClassLimit[] = [];
  for (const { value: cls } of ASSET_CLASS_OPTIONS) {
    const entry = draft[cls];
    if (!entry) continue;
    const min = pctToFrac(entry.min);
    const max = pctToFrac(entry.max);
    if (min === null && max === null) continue;
    out.push({ asset_class: cls, min_weight: min, max_weight: max });
  }
  return out;
}

export function PortfolioConstraintsSection({
  portfolioId,
}: {
  portfolioId: number;
}) {
  const queryClient = useQueryClient();

  const constraintsQuery = useQuery({
    queryKey: ["portfolio-constraints", portfolioId],
    queryFn: ({ signal }) => getPortfolioConstraints(portfolioId, signal),
    staleTime: 60_000,
    retry: retryPolicy,
  });

  // Form state, seeded once the query resolves (and re-seeded on portfolio change).
  const [capPct, setCapPct] = useState("");
  const [minWeightPct, setMinWeightPct] = useState("");
  const [overlapCapPct, setOverlapCapPct] = useState("");
  const [classLimits, setClassLimits] = useState<ClassLimitDraft>({});

  const seedFrom = (data: PortfolioConstraints) => {
    setCapPct(fracToPct(data.cap));
    setMinWeightPct(fracToPct(data.min_weight));
    setOverlapCapPct(fracToPct(data.overlap_cap));
    setClassLimits(classLimitsToDraft(data.class_limits ?? []));
  };

  // Seed the editable form once the GET resolves. Tracking the loaded payload by
  // reference avoids clobbering in-progress edits on background refetches.
  const loaded = constraintsQuery.data;
  useEffect(() => {
    if (loaded) seedFrom(loaded);
  }, [loaded]);

  const setClassBound = (
    cls: ConstraintAssetClass,
    side: "min" | "max",
    value: string,
  ) =>
    setClassLimits((prev) => ({
      ...prev,
      [cls]: { ...(prev[cls] ?? { min: "", max: "" }), [side]: value },
    }));

  const saveMutation = useMutation({
    mutationFn: (body: PortfolioConstraintsPut) =>
      putPortfolioConstraints(portfolioId, body),
    onSuccess: (saved) => {
      queryClient.setQueryData(["portfolio-constraints", portfolioId], saved);
      seedFrom(saved);
    },
  });

  const onSave = () => {
    const body: PortfolioConstraintsPut = {
      cap: pctToFrac(capPct),
      min_weight: pctToFrac(minWeightPct),
      overlap_cap: pctToFrac(overlapCapPct),
      class_limits: draftToClassLimits(classLimits),
    };
    saveMutation.mutate(body);
  };

  if (constraintsQuery.isPending) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading construction constraints"
        className="h-[88px] animate-pulse bg-surface-2"
      />
    );
  }
  if (constraintsQuery.isError) {
    return (
      <ErrorPanel
        title="Failed to load construction constraints"
        message={constraintsQuery.error.message}
        onRetry={() => constraintsQuery.refetch()}
      />
    );
  }

  return (
    <section>
      <Card title="Construction constraints">
        <p className="mt-1 text-[12px] text-text-secondary">
          Limits used when rebuilding or rebalancing this portfolio. Leave a
          field blank for no limit. Values are a percent of the portfolio.
        </p>

        <div className="mt-3 flex flex-wrap gap-x-[18px] gap-y-4">
          <PctField
            label="Max per holding"
            ariaLabel="Max per holding"
            value={capPct}
            onChange={setCapPct}
          />
          <PctField
            label="Min per holding"
            ariaLabel="Min per holding"
            value={minWeightPct}
            onChange={setMinWeightPct}
          />
          <PctField
            label="Overlap cap"
            ariaLabel="Overlap cap"
            value={overlapCapPct}
            onChange={setOverlapCapPct}
          />
        </div>

        <div className="mt-4 border-t border-border pt-4">
          <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
            Asset-class limits (% of portfolio)
          </p>
          <div className="flex flex-wrap gap-x-[18px] gap-y-3">
            {ASSET_CLASS_OPTIONS.map((cls) => {
              const entry = classLimits[cls.value] ?? { min: "", max: "" };
              return (
                <fieldset
                  key={cls.value}
                  className="m-0 flex flex-col gap-1.5 border-0 p-0"
                >
                  <span className="text-[11px] font-bold text-text-secondary">
                    {cls.label}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <BoundInput
                      ariaLabel={`${cls.label} min`}
                      value={entry.min}
                      onChange={(v) => setClassBound(cls.value, "min", v)}
                      placeholder="min"
                    />
                    <span className="text-[11px] text-text-muted">–</span>
                    <BoundInput
                      ariaLabel={`${cls.label} max`}
                      value={entry.max}
                      onChange={(v) => setClassBound(cls.value, "max", v)}
                      placeholder="max"
                    />
                    <span className="text-[11px] text-text-muted">%</span>
                  </div>
                </fieldset>
              );
            })}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-3">
          <button
            type="button"
            onClick={onSave}
            disabled={saveMutation.isPending}
            className="h-[32px] border border-accent bg-accent px-4 text-[12px] font-bold text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saveMutation.isPending ? "Saving…" : "Save constraints"}
          </button>
          {saveMutation.isSuccess && (
            <span className="text-[12px] text-gain">Saved.</span>
          )}
          {saveMutation.isError && (
            <span
              role="alert"
              className="break-words text-[12px] text-loss"
            >
              {saveMutation.error.message}
            </span>
          )}
        </div>
      </Card>
    </section>
  );
}

function PctField({
  label,
  ariaLabel,
  value,
  onChange,
}: {
  label: string;
  ariaLabel: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex w-[172px] flex-col gap-1.5">
      <span className="text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
        {label}
      </span>
      <div className="flex h-[36px] items-center border border-border-strong bg-field focus-within:border-accent">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="—"
          inputMode="decimal"
          aria-label={ariaLabel}
          className="h-full min-w-0 flex-1 border-0 bg-transparent pl-2.5 text-right text-[14px] tabular-nums text-text-primary outline-none placeholder:text-text-muted"
        />
        <span className="px-2.5 text-[12px] text-text-muted">%</span>
      </div>
    </label>
  );
}

function BoundInput({
  ariaLabel,
  value,
  onChange,
  placeholder,
}: {
  ariaLabel: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      inputMode="decimal"
      aria-label={ariaLabel}
      className="h-[32px] w-[64px] border border-border-strong bg-field px-2 text-right text-[13px] tabular-nums text-text-primary outline-none focus:border-accent placeholder:text-text-muted"
    />
  );
}
