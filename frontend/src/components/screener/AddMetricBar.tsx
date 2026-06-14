"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { MetricDef } from "@/lib/api/client";
import { INPUT_CLASS, BUTTON_CLASS } from "@/components/screener/shared";
import { MetricBrowserPopover } from "@/components/screener/MetricBrowserPopover";

export function AddMetricBar({
  catalog,
  selectedCodes,
  pendingCode,
  onToggleMetric,
}: {
  catalog: MetricDef[];
  selectedCodes: ReadonlySet<string>;
  pendingCode: string | undefined;
  onToggleMetric: (code: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [browsing, setBrowsing] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // NOTE: mouse + Escape only for now; full keyboard combobox nav (↑/↓/Enter, aria roles) deferred — see builder/AssetSearchAdd.tsx for the template when wired.
  // Typeahead suggestions: not-yet-selected metrics matching the query.
  const suggestions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle === "") return [];
    return catalog
      .filter((m) => !selectedCodes.has(m.code))
      .filter((m) => m.name.toLowerCase().includes(needle) || m.abbreviation.toLowerCase().includes(needle) || m.code.toLowerCase().includes(needle))
      .slice(0, 8);
  }, [catalog, selectedCodes, query]);

  const add = (code: string) => { onToggleMetric(code); setQuery(""); };

  // Dismiss the dropdown/popover on an outside click (role="dialog" contract).
  const open = browsing || suggestions.length > 0;
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) {
        setBrowsing(false);
        setQuery("");
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div
      ref={wrapRef}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          setBrowsing(false);
          setQuery("");
        }
      }}
      className="relative flex flex-wrap items-center gap-2 bg-surface-2 border-b border-border px-[var(--ix-pad)] py-2.5"
    >
      <span className="ix-label m-0">Add metric</span>
      <div className="relative w-[280px]">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a metric…  (P/E, ROE, Beta…)"
          aria-label="Find a metric by name or code" className={`w-full ${INPUT_CLASS} text-[12px]`} />
        {suggestions.length > 0 && (
          <ul className="absolute z-20 mt-px w-full max-h-[260px] overflow-auto bg-surface-2 border border-border-strong">
            {suggestions.map((m) => (
              <li key={m.code}>
                <button type="button" onClick={() => add(m.code)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-[12.5px] text-text-secondary hover:bg-layer-hover">
                  <span>{m.name}</span>
                  <span className="ml-auto text-[11px] text-text-muted">{m.abbreviation} · {m.category}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <button type="button" onClick={() => setBrowsing((v) => !v)} aria-expanded={browsing}
        className={`${BUTTON_CLASS} text-[12px]`}>Browse by category ▾</button>
      {browsing && (
        <MetricBrowserPopover catalog={catalog} selectedCodes={selectedCodes} pendingCode={pendingCode}
          onToggleMetric={onToggleMetric} onClose={() => setBrowsing(false)} />
      )}
    </div>
  );
}
