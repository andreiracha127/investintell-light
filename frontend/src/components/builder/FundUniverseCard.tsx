"use client";

/**
 * Fund-universe card — instead of hand-picking tickers, the user filters and
 * ranks the whole fund universe; the backend optimizes the top `maxAssets`
 * candidates that have enough overlapping history. A live count (GET /funds
 * with the same filters) shows how big the matching set is before running.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { fetchFunds } from "@/lib/api/client";
import { Card } from "@/components/ui/panels";
import {
  FIELD_LABEL_CLASS,
  INPUT_CLASS,
  retryPolicy,
} from "@/components/screener/shared";
import { formatNumber } from "@/lib/format";

import {
  RANK_BY_LABELS,
  universeDraftToCountQuery,
  type UniverseDraft,
  type UniverseRankBy,
} from "./assets";

const FUND_TYPES: { value: UniverseDraft["fundType"]; label: string }[] = [
  { value: "", label: "Any type" },
  { value: "etf", label: "ETF" },
  { value: "mutual_fund", label: "Mutual fund" },
  { value: "mmf", label: "Money-market" },
];

const ASSET_CLASSES: { value: UniverseDraft["assetClass"]; label: string }[] = [
  { value: "", label: "Any asset class" },
  { value: "equity", label: "Equity" },
  { value: "fixed_income", label: "Fixed income" },
  { value: "cash", label: "Cash" },
  { value: "alternatives", label: "Alternatives" },
];

export function FundUniverseCard({
  draft,
  setDraft,
  onCount,
}: {
  draft: UniverseDraft;
  setDraft: (updater: (prev: UniverseDraft) => UniverseDraft) => void;
  /** Report the matching-fund count up so the parent can gate the run. */
  onCount: (count: number | null) => void;
}) {
  const countQuery = useQuery({
    queryKey: ["builder-universe-count", universeDraftToCountQuery(draft)],
    queryFn: ({ signal }) => fetchFunds(universeDraftToCountQuery(draft), signal),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: retryPolicy,
  });
  const total = countQuery.data?.total ?? null;

  useEffect(() => {
    onCount(countQuery.isSuccess ? (countQuery.data?.total ?? 0) : null);
  }, [countQuery.isSuccess, countQuery.data?.total, onCount]);

  const patch = (p: Partial<UniverseDraft>) => setDraft((prev) => ({ ...prev, ...p }));
  const effectiveN = total !== null ? Math.min(draft.maxAssets, total) : draft.maxAssets;

  return (
    <Card title="Fund universe" subtitle="filter &amp; rank — no manual tickers">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <Select
          label="Fund type"
          value={draft.fundType}
          onChange={(v) => patch({ fundType: v as UniverseDraft["fundType"] })}
          options={FUND_TYPES}
        />
        <Select
          label="Asset class"
          value={draft.assetClass}
          onChange={(v) => patch({ assetClass: v as UniverseDraft["assetClass"] })}
          options={ASSET_CLASSES}
        />
        <NumField
          label="AUM ≥ ($M)"
          value={draft.aumMinM}
          onChange={(v) => patch({ aumMinM: v })}
          placeholder="any"
          width="w-[110px]"
        />
        <NumField
          label="Expense ≤ (%)"
          value={draft.expenseMaxPct}
          onChange={(v) => patch({ expenseMaxPct: v })}
          placeholder="any"
          width="w-[120px]"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-3">
        <label className="flex min-w-[170px] flex-col gap-1">
          <span className={FIELD_LABEL_CLASS}>Rank by</span>
          <select
            value={draft.rankBy}
            onChange={(e) => patch({ rankBy: e.target.value as UniverseRankBy })}
            aria-label="Rank funds by"
            className={INPUT_CLASS}
          >
            {(Object.keys(RANK_BY_LABELS) as UniverseRankBy[]).map((k) => (
              <option key={k} value={k}>
                {RANK_BY_LABELS[k]}
              </option>
            ))}
          </select>
        </label>
        <Select
          label="Order"
          value={draft.rankDir}
          onChange={(v) => patch({ rankDir: v as "asc" | "desc" })}
          options={[
            { value: "desc", label: "Best first (high→low)" },
            { value: "asc", label: "Low→high" },
          ]}
        />
        <label className="flex w-[200px] flex-col gap-1">
          <span className={FIELD_LABEL_CLASS}>
            How many funds{" "}
            <span className="tabular-nums normal-case text-text-secondary">
              {draft.maxAssets}
            </span>
          </span>
          <input
            type="range"
            min={2}
            max={50}
            step={1}
            value={draft.maxAssets}
            onChange={(e) => patch({ maxAssets: Number(e.target.value) })}
            aria-label="Number of funds to optimize (2 to 50)"
            className="h-[34px] accent-[var(--color-accent)]"
          />
        </label>
      </div>

      <p className="ix-fs mb-0 mt-3 border-l-[3px] border-accent bg-accent-wash px-2.5 py-1.5 text-text-secondary">
        {countQuery.isError ? (
          <span className="text-loss">{countQuery.error.message}</span>
        ) : total === null ? (
          "Counting matching funds…"
        ) : total < 2 ? (
          <>
            Only <span className="font-bold tabular-nums">{formatNumber(total, 0)}</span>{" "}
            fund{total === 1 ? "" : "s"} match — relax the filters (need at least 2).
          </>
        ) : (
          <>
            ≈ <span className="font-bold tabular-nums">{formatNumber(total, 0)}</span>{" "}
            funds match · optimizing the top{" "}
            <span className="font-bold tabular-nums">{effectiveN}</span> by{" "}
            {RANK_BY_LABELS[draft.rankBy]}. Funds without enough overlapping NAV
            history are skipped automatically.
          </>
        )}
      </p>
    </Card>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex min-w-[150px] flex-col gap-1">
      <span className={FIELD_LABEL_CLASS}>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className={INPUT_CLASS}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
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
