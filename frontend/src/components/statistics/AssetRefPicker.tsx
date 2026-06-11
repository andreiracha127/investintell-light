"use client";

/**
 * Picker for one beta/correlation axis: a Ticker | Portfolio kind toggle plus
 * a ticker input or the persisted-portfolio select.
 *
 * The draft mirrors the API's discriminated `AssetRef` but tolerates
 * incomplete input (empty ticker, no portfolio yet); `toAssetRef` is the one
 * place a draft becomes a valid request value (or null when incomplete).
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiError, fetchPortfolios, type AssetRef } from "@/lib/api/client";
import { PortfolioSelect } from "@/components/statistics/PortfolioSelect";
import { INPUT_CLASS } from "@/components/statistics/ui";

export type AssetRefDraft =
  | { kind: "ticker"; ticker: string }
  | { kind: "portfolio"; id: number | null };

/** Never retry 4xx (deterministic), retry 5xx/network twice. */
const retryPolicy = (failureCount: number, err: Error) =>
  !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
  failureCount < 2;

/**
 * Y-axis default: the first persisted portfolio once the list loads (or
 * ticker AAPL when none exist), unless the user already touched the picker.
 */
export function useDefaultAssetY(): [
  AssetRefDraft,
  (draft: AssetRefDraft) => void,
] {
  const [draft, setDraft] = useState<AssetRefDraft>({
    kind: "ticker",
    ticker: "AAPL",
  });
  const touched = useRef(false);

  const portfoliosQuery = useQuery({
    queryKey: ["portfolios"],
    queryFn: ({ signal }) => fetchPortfolios(signal),
    staleTime: 60_000,
    retry: retryPolicy,
  });
  const portfolios = portfoliosQuery.data;

  useEffect(() => {
    if (touched.current || !portfolios || portfolios.length === 0) return;
    setDraft({ kind: "portfolio", id: portfolios[0].id });
  }, [portfolios]);

  const set = (next: AssetRefDraft) => {
    touched.current = true;
    setDraft(next);
  };
  return [draft, set];
}

/** Convert a draft to a request-ready AssetRef, or null when incomplete. */
export function toAssetRef(draft: AssetRefDraft): AssetRef | null {
  if (draft.kind === "ticker") {
    const ticker = draft.ticker.trim().toUpperCase();
    return ticker.length > 0 ? { kind: "ticker", ticker } : null;
  }
  return draft.id !== null ? { kind: "portfolio", id: draft.id } : null;
}

export function AssetRefPicker({
  label,
  value,
  onChange,
}: {
  label: string;
  value: AssetRefDraft;
  onChange: (draft: AssetRefDraft) => void;
}) {
  return (
    <fieldset className="flex flex-wrap items-center gap-2">
      <legend className="float-left mr-1 text-[12px] text-text-secondary">
        {label}
      </legend>

      <div
        role="group"
        aria-label={`${label} kind`}
        className="flex rounded-[7px] border border-border bg-surface-1 p-0.5"
      >
        {(["ticker", "portfolio"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            onClick={() => {
              if (kind === value.kind) return;
              // PortfolioSelect auto-fills the first portfolio for a null id.
              onChange(
                kind === "ticker"
                  ? { kind: "ticker", ticker: "" }
                  : { kind: "portfolio", id: null },
              );
            }}
            aria-pressed={kind === value.kind}
            className={`px-3 py-1 rounded-[5px] text-[12px] font-medium transition-colors ${
              kind === value.kind
                ? "bg-surface-3 text-accent"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {kind === "ticker" ? "Ticker" : "Portfolio"}
          </button>
        ))}
      </div>

      {value.kind === "ticker" ? (
        <input
          value={value.ticker}
          onChange={(e) =>
            onChange({ kind: "ticker", ticker: e.target.value.toUpperCase() })
          }
          placeholder="TICKER"
          aria-label={`${label} ticker`}
          className={`w-[110px] uppercase ${INPUT_CLASS}`}
        />
      ) : (
        <PortfolioSelect
          label=""
          value={value.id}
          onChange={(id) => onChange({ kind: "portfolio", id })}
        />
      )}
    </fieldset>
  );
}
