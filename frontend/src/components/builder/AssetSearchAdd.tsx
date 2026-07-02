"use client";

/**
 * Unified asset autocomplete for the builder — type a ticker OR a name and add
 * stocks and funds alike (GET /search/symbols). Replaces the old "memorize the
 * ticker" free-text entry: 250ms debounce, ↑/↓/Enter/Esc keyboard nav, click
 * outside closes, already-added hits are disabled. The input clears after each
 * add so a basket is assembled with repeated picks.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { fetchSymbolSearch, type SymbolSearchResult } from "@/lib/api/client";
import { FIELD_LABEL_CLASS, INPUT_CLASS } from "@/components/screener/shared";

import { assetKey, symbolToAsset, type UniverseAsset } from "./assets";

const KIND_LABEL: Record<string, string> = {
  stock: "Stock",
  etf: "ETF",
  mutual_fund: "Mutual fund",
  mmf: "MMF",
};

export function AssetSearchAdd({
  inUniverse,
  onAdd,
}: {
  /** assetKeys already in the basket — those hits render as disabled. */
  inUniverse: Set<string>;
  onAdd: (asset: UniverseAsset) => void;
}) {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  useEffect(() => {
    const timer = setTimeout(() => setQ(text.trim()), 250);
    return () => clearTimeout(timer);
  }, [text]);

  const { data: results = [], isFetching } = useQuery({
    queryKey: ["builder-symbol-search", q],
    queryFn: ({ signal }) => fetchSymbolSearch(q, signal),
    enabled: q.length >= 1,
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const add = (item: SymbolSearchResult) => {
    const asset = symbolToAsset(item);
    if (inUniverse.has(assetKey(asset))) return;
    onAdd(asset);
    setText("");
    setQ("");
    setHi(-1);
    setOpen(false);
  };

  // Render the dropdown whenever there's something to say about the current
  // search — including "fetching" and "no matches" — so an empty or in-flight
  // query isn't silent (the old `results.length > 0` gate hid both states).
  const trimmed = text.trim();
  const dropdownVisible = open && trimmed.length > 0;
  const showEmpty = dropdownVisible && !isFetching && results.length === 0;

  return (
    <div ref={rootRef} className="relative flex w-full max-w-[440px] flex-col gap-1">
      <span className={FIELD_LABEL_CLASS}>Search stocks &amp; funds</span>
      <input
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setHi(-1);
        }}
        onFocus={() => text && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHi((i) => Math.min(i + 1, results.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHi((i) => Math.max(i - 1, -1));
          } else if (e.key === "Enter") {
            // Escape closes the list (open=false) without clearing results;
            // don't commit a hidden suggestion on a follow-up Enter.
            if (!open) return;
            e.preventDefault();
            if (hi >= 0 && results[hi]) add(results[hi]);
            else if (results[0]) add(results[0]);
          } else if (e.key === "Escape") {
            setOpen(false);
            setHi(-1);
          }
        }}
        placeholder="Ticker or name — e.g. AAPL, Vanguard 500, VTI…"
        aria-label="Search stocks and funds by ticker or name"
        aria-expanded={dropdownVisible}
        aria-autocomplete="list"
        aria-controls={listId}
        aria-activedescendant={
          open && hi >= 0 && results[hi] ? `${listId}-opt-${hi}` : undefined
        }
        role="combobox"
        className={INPUT_CLASS}
      />
      {dropdownVisible && (
        <ul
          id={listId}
          role="listbox"
          className={`absolute left-0 top-full z-30 mt-1 max-h-72 w-full min-w-[360px] overflow-auto border border-border-strong bg-surface-1 shadow-lg transition-opacity ${
            isFetching ? "opacity-70" : ""
          }`}
        >
          {isFetching ? (
            <li role="presentation" className="px-2.5 py-1.5 text-[12px] text-text-muted">
              Searching…
            </li>
          ) : showEmpty ? (
            <li role="presentation" className="px-2.5 py-1.5 text-[12px] text-text-muted">
              No matches for &ldquo;{q}&rdquo;
            </li>
          ) : (
            results.map((r, i) => {
              const added = inUniverse.has(assetKey(symbolToAsset(r)));
              return (
                <li key={`${r.kind}:${r.symbol}`} role="option" aria-selected={i === hi}>
                  <button
                    type="button"
                    disabled={added}
                    onMouseEnter={() => setHi(i)}
                    onClick={() => add(r)}
                    className={`flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left text-[12px] transition-colors hover:bg-accent-wash disabled:cursor-not-allowed disabled:opacity-40 ${
                      i === hi ? "bg-layer-hover" : ""
                    }`}
                  >
                    <span className="w-[64px] shrink-0 font-bold tabular-nums text-accent">
                      {r.symbol}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-text-secondary">
                      {r.name}
                    </span>
                    <span className="shrink-0 text-[10px] uppercase text-text-muted">
                      {KIND_LABEL[r.kind] ?? r.kind}
                    </span>
                    <span className="w-[42px] shrink-0 text-right text-[11px] text-text-muted">
                      {added ? "Added" : "+ Add"}
                    </span>
                  </button>
                </li>
              );
            })
          )}
        </ul>
      )}
    </div>
  );
}
