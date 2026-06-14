"use client";

import { useMemo, useState } from "react";

import type { MetricDef } from "@/lib/api/client";
import { INPUT_CLASS } from "@/components/screener/shared";

export function MetricBrowserPopover({
  catalog,
  selectedCodes,
  pendingCode,
  onToggleMetric,
  onClose,
}: {
  catalog: MetricDef[];
  selectedCodes: ReadonlySet<string>;
  pendingCode: string | undefined;
  onToggleMetric: (code: string) => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = needle === "" ? catalog : catalog.filter((m) =>
      m.name.toLowerCase().includes(needle) || m.code.toLowerCase().includes(needle) || m.abbreviation.toLowerCase().includes(needle));
    const map = new Map<string, MetricDef[]>();
    for (const m of filtered) (map.get(m.category) ?? map.set(m.category, []).get(m.category)!).push(m);
    return [...map.entries()];
  }, [catalog, search]);

  return (
    <div role="dialog" aria-label="Browse metrics by category"
      className="absolute z-20 mt-1 w-[360px] max-h-[420px] overflow-auto bg-surface-2 border border-border-strong shadow-[2px_2px_0_rgba(0,0,0,0.08)]">
      <div className="sticky top-0 flex items-center gap-2 bg-surface-2 border-b border-border px-3 py-2">
        <input autoFocus value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter…"
          aria-label="Filter metrics" className={`flex-1 ${INPUT_CLASS} text-[12px]`} />
        <span className="tabular-nums text-[11px] text-text-muted">{catalog.length} metrics</span>
        <button type="button" onClick={onClose} aria-label="Close" className="px-1.5 text-text-muted hover:text-text-primary">×</button>
      </div>
      {groups.map(([category, metrics]) => {
        const selectedInGroup = metrics.filter((m) => selectedCodes.has(m.code)).length;
        return (
          <div key={category} className="border-b border-border last:border-b-0">
            <div className="flex items-center justify-between px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.06em] text-accent">
              <span>{category}</span>
              <span className="tabular-nums font-normal text-text-muted">{selectedInGroup}/{metrics.length}</span>
            </div>
            <ul className="pb-1">
              {metrics.map((m) => {
                const on = selectedCodes.has(m.code);
                return (
                  <li key={m.code}>
                    <button type="button" onClick={() => onToggleMetric(m.code)} disabled={pendingCode === m.code} aria-pressed={on}
                      className={`w-full flex items-center gap-2 px-3 py-1 text-left text-[12.5px] transition-colors disabled:opacity-50 ${on ? "text-accent" : "text-text-secondary hover:bg-layer-hover"}`}>
                      <span aria-hidden="true" className={`inline-flex h-[13px] w-[13px] shrink-0 items-center justify-center border text-[9px] ${on ? "bg-accent border-accent text-on-accent" : "border-border-strong"}`}>{on ? "✓" : ""}</span>
                      <span className={on ? "font-semibold" : ""}>{m.name}</span>
                      <span className="ml-auto text-[11px] text-text-muted">{m.abbreviation}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
