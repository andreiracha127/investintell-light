"use client";

/**
 * Global header search — typeahead over GET /search/symbols (debounce 250ms,
 * ↑/↓/Enter/Esc keyboard navigation, click-outside closes). Routes by kind:
 * stocks → /stocks/{ticker}; catalogued funds (ETF / mutual fund / MMF) →
 * /funds/{instrument_id}. Enter with no highlighted suggestion falls back to
 * treating the raw text as a stock ticker.
 */
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchSymbolSearch, type SymbolSearchResult } from "@/lib/api/client";

const KIND_LABEL: Record<string, string> = {
  stock: "Stock",
  etf: "ETF",
  mutual_fund: "Mutual fund",
  mmf: "MMF",
};

function targetHref(item: SymbolSearchResult): string {
  if (item.instrument_id) {
    return `/funds/${encodeURIComponent(item.instrument_id)}`;
  }
  return `/stocks/${encodeURIComponent(item.symbol.toUpperCase())}`;
}

export function TickerSearch() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  // Debounce keystrokes into the query the API sees.
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250);
    return () => clearTimeout(t);
  }, [text]);

  const { data: results = [] } = useQuery({
    queryKey: ["symbol-search", q],
    queryFn: ({ signal }) => fetchSymbolSearch(q, signal),
    enabled: q.length >= 1,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const go = (item: SymbolSearchResult) => {
    router.push(targetHref(item));
    setText("");
    setQ("");
    setOpen(false);
    setHi(-1);
  };

  return (
    <div ref={rootRef} role="search" className="relative min-w-0 flex-1">
      <svg
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
      >
        <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
        <path d="M11 11l4 4" stroke="currentColor" strokeWidth="1.4" />
      </svg>
      <input
        type="text"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setOpen(true);
          setHi(-1);
        }}
        onFocus={() => text && setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setHi((i) => Math.min(i + 1, results.length - 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setHi((i) => Math.max(i - 1, -1));
          } else if (event.key === "Enter") {
            event.preventDefault();
            const trimmed = text.trim();
            // `results` belong to the debounced query `q`; they may still lag
            // the current input. Only auto-pick the top hit when the results
            // are for exactly what's typed — otherwise treat the raw text as a
            // ticker so a fast Enter never routes to a stale suggestion.
            const resultsCurrent = q === trimmed;
            if (hi >= 0 && results[hi]) {
              go(results[hi]);
            } else if (results.length > 0 && open && resultsCurrent) {
              go(results[0]);
            } else if (trimmed) {
              go({
                symbol: trimmed.toUpperCase(),
                name: null,
                kind: "stock",
                instrument_id: null,
              });
            }
          } else if (event.key === "Escape") {
            setOpen(false);
            setHi(-1);
          }
        }}
        placeholder="Search stocks & funds…"
        aria-label="Search stocks and funds"
        aria-expanded={open && results.length > 0}
        aria-autocomplete="list"
        aria-controls={listId}
        role="combobox"
        autoComplete="off"
        spellCheck={false}
        className="h-9 w-full max-w-[440px] border-0 border-b border-border-strong bg-field pl-[34px] pr-3 text-[13px] text-text-primary outline-none placeholder:text-text-muted focus:border-b-2 focus:border-accent"
      />
      {open && results.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Symbol suggestions"
          className="absolute left-0 top-full z-[70] mt-1 max-h-[320px] w-full max-w-[440px] overflow-auto border border-border-strong bg-surface-1 shadow-lg"
        >
          {results.map((r, i) => (
            <li key={`${r.kind}:${r.symbol}:${r.instrument_id ?? ""}`} role="option" aria-selected={i === hi}>
              <button
                type="button"
                onMouseEnter={() => setHi(i)}
                onClick={() => go(r)}
                className={`flex w-full items-baseline gap-2.5 px-3 py-2 text-left text-[12.5px] ${
                  i === hi ? "bg-layer-hover" : ""
                }`}
              >
                <span className="w-[52px] shrink-0 font-bold tabular-nums text-accent">
                  {r.symbol}
                </span>
                <span className="min-w-0 flex-1 truncate text-text-secondary">
                  {r.name}
                </span>
                <span className="shrink-0 text-[10px] font-bold uppercase tracking-[0.06em] text-text-muted">
                  {KIND_LABEL[r.kind] ?? r.kind}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
