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

/**
 * Whether two resolved asset refs point at the same underlying asset (same
 * kind + ticker/id). Used to block a degenerate X = Y run — e.g. regressing
 * SPY on SPY, or correlating a portfolio with itself — which the backend
 * accepts but produces a meaningless, trivially-perfect result.
 */
export function sameAssetRef(a: AssetRef | null, b: AssetRef | null): boolean {
  if (a === null || b === null) return false;
  if (a.kind === "ticker" && b.kind === "ticker") return a.ticker === b.ticker;
  if (a.kind === "portfolio" && b.kind === "portfolio") return a.id === b.id;
  return false;
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
    <fieldset className="m-0 flex min-w-0 flex-col gap-[5px] border-0 p-0">
      <legend className="p-0 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
        {label}
      </legend>

      <div className="flex flex-wrap items-end gap-2">
        <div
          role="group"
          aria-label={`${label} kind`}
          className="flex h-[34px] border border-border-strong"
        >
          {(["ticker", "portfolio"] as const).map((kind, index) => (
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
              className={`px-3 text-[12px] transition-colors ${
                index > 0 ? "border-l border-border-strong" : ""
              } ${
                kind === value.kind
                  ? "bg-accent font-bold text-on-accent"
                  : "bg-field font-medium text-text-secondary hover:bg-layer-hover"
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
            className={`w-[110px] !uppercase ${INPUT_CLASS}`}
          />
        ) : (
          <PortfolioSelect
            label=""
            value={value.id}
            onChange={(id) => onChange({ kind: "portfolio", id })}
          />
        )}
      </div>
    </fieldset>
  );
}
