"use client";

/**
 * Input do Compare com dropdown de sugestões (estilo Barchart): debounce
 * 250ms → GET /search/symbols; teclado ↑/↓/Enter/Esc; clique fora fecha.
 * Enter sem item destacado usa o texto cru como ticker (fallback).
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { fetchSymbolSearch, type SymbolSearchResult } from "@/lib/api/client";

const KIND_LABEL: Record<string, string> = {
  stock: "Stock",
  etf: "ETF",
  mutual_fund: "Mutual fund",
  mmf: "MMF",
};

export function SymbolSearchInput({
  onSelect,
  onClear,
  active = null,
  placeholder = "Compare...",
}: {
  onSelect: (item: SymbolSearchResult) => void;
  onClear?: () => void;
  /** Símbolo ativo (mostra o ×). */
  active?: string | null;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  // debounce 250ms
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

  const pick = (item: SymbolSearchResult) => {
    onSelect(item);
    setText("");
    setQ("");
    setOpen(false);
    setHi(-1);
  };

  return (
    <div ref={rootRef} className="relative flex items-center gap-1">
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
            e.preventDefault();
            if (hi >= 0 && results[hi]) pick(results[hi]);
            else if (text.trim()) {
              // fallback: texto cru como ticker de ação
              pick({
                symbol: text.trim().toUpperCase(),
                name: null,
                kind: "stock",
                instrument_id: null,
              });
            }
          } else if (e.key === "Escape") {
            setOpen(false);
            setHi(-1);
          }
        }}
        placeholder={placeholder}
        aria-label="Compare symbol"
        aria-expanded={open && results.length > 0}
        aria-autocomplete="list"
        aria-controls={listId}
        role="combobox"
        className="h-7 w-32 border border-border-strong bg-field px-2 text-[11px] text-text-primary placeholder:text-text-muted"
      />
      {active && onClear && (
        <button
          type="button"
          aria-label={`Remove comparison ${active}`}
          className="text-[11px] text-text-muted hover:text-text-primary"
          onClick={onClear}
        >
          x
        </button>
      )}
      {open && results.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute left-0 top-full z-30 mt-1 max-h-64 w-72 overflow-auto border border-border-strong bg-surface-1 shadow-lg"
        >
          {results.map((r, i) => (
            <li key={`${r.kind}:${r.symbol}`} role="option" aria-selected={i === hi}>
              <button
                type="button"
                onMouseEnter={() => setHi(i)}
                onClick={() => pick(r)}
                className={`flex w-full items-baseline gap-2 px-2 py-1.5 text-left text-[12px] ${
                  i === hi ? "bg-layer-hover" : ""
                }`}
              >
                <span className="font-bold text-accent">{r.symbol}</span>
                <span className="min-w-0 flex-1 truncate text-text-secondary">{r.name}</span>
                <span className="shrink-0 text-[10px] uppercase text-text-muted">
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
