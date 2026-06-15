"use client";

import { useEffect, useMemo, useState } from "react";

import type { MetricBuild, MetricDef, ScreenFilter } from "@/lib/api/client";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { FIELD_LABEL_CLASS } from "@/components/screener/shared";
import { buildHcDistributionOption } from "@/lib/charts/hc/distribution";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatCompact } from "@/lib/format";
import { parseBound, toDisplayText } from "@/lib/screener/bounds";

export function DistributionPanel({
  metric,
  filter,
  build,
  headline,
  canMoveUp,
  canMoveDown,
  onEditBound,
  onApplyPreset,
  onMove,
}: {
  metric: MetricDef;
  filter: ScreenFilter;
  build: MetricBuild | undefined;
  headline: number | null;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onEditBound: (which: "min" | "max", value: number | null) => void;
  onApplyPreset: (min: number | null, max: number | null) => void;
  onMove: (direction: "up" | "down") => void;
}) {
  const isPercent = metric.data_type === "percent";
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => setColors(chartColors()), []);

  const [minText, setMinText] = useState(() => toDisplayText(filter.min_value, isPercent));
  const [maxText, setMaxText] = useState(() => toDisplayText(filter.max_value, isPercent));
  // Re-sync when the active row OR its persisted bounds change (edited via grid).
  useEffect(() => {
    setMinText(toDisplayText(filter.min_value, isPercent));
    setMaxText(toDisplayText(filter.max_value, isPercent));
  }, [filter.metric_code, filter.min_value, filter.max_value, isPercent]);

  const dist = build?.distribution ?? null;
  const option = useMemo(
    () =>
      dist && colors
        ? buildHcDistributionOption(dist, { min: filter.min_value, max: filter.max_value }, metric.data_type, colors)
        : null,
    [dist, colors, filter.min_value, filter.max_value, metric.data_type],
  );

  const commit = (which: "min" | "max", text: string) => {
    const parsed = parseBound(text, isPercent);
    if (parsed === undefined) return; // invalid → no commit
    const current = which === "min" ? filter.min_value : filter.max_value;
    if (parsed !== current) onEditBound(which, parsed);
  };

  const presets = (metric.presets ?? []).filter((p) => p.min_value !== null || p.max_value !== null);
  const matches = (p: { min_value: number | null; max_value: number | null }) =>
    filter.min_value === p.min_value && filter.max_value === p.max_value;
  const unit = isPercent ? "%" : "";

  return (
    <section className="border-t border-border bg-surface-2 ix-pad">
      <div className="flex flex-wrap items-center gap-2.5">
        <h3 className="ix-label m-0">Distribution — {metric.name}</h3>
        <span className="inline-flex h-[22px] items-center bg-accent-wash border border-accent px-2 tabular-nums text-[11px] font-bold text-accent">
          {headline === null ? "— matches" : `${formatCompact(headline)} matches`}
        </span>
        <div className="ml-auto flex items-center gap-px">
          <button type="button" onClick={() => onMove("up")} disabled={!canMoveUp}
            aria-label={`Move ${metric.name} up`}
            className="h-[28px] w-7 bg-field border border-border-strong text-text-secondary hover:bg-layer-hover disabled:opacity-30 disabled:cursor-not-allowed">↑</button>
          <button type="button" onClick={() => onMove("down")} disabled={!canMoveDown}
            aria-label={`Move ${metric.name} down`}
            className="h-[28px] w-7 bg-field border border-border-strong text-text-secondary hover:bg-layer-hover disabled:opacity-30 disabled:cursor-not-allowed">↓</button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-3">
        {/* Histogram — width-controlled so it never stretches on wide screens */}
        <div className="w-full max-w-[560px]">
          {option ? (
            <HighchartsChart options={option} className="h-[150px]" />
          ) : (
            <p className="h-[150px] flex items-center justify-center bg-zebra text-[13px] text-text-muted">
              No metric data yet — run the metrics job.
            </p>
          )}
          {presets.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {presets.map((p) => (
                <button key={p.name} type="button" onClick={() => onApplyPreset(p.min_value, p.max_value)}
                  aria-pressed={matches(p)}
                  className={`inline-flex h-[22px] items-center border px-2.5 text-[11px] font-bold transition-colors ${
                    matches(p) ? "bg-accent-wash border-accent text-accent" : "bg-field border-border-strong text-text-secondary hover:bg-layer-hover"
                  }`}>{p.name}</button>
              ))}
            </div>
          )}
        </div>

        {/* Min / Max — commit on Enter/blur; mirror the grid's inline edit */}
        <div className="flex items-end gap-3.5 text-[12px] text-text-secondary">
          {(["min", "max"] as const).map((which) => {
            const text = which === "min" ? minText : maxText;
            const setText = which === "min" ? setMinText : setMaxText;
            return (
              <label key={which} className="flex w-[120px] flex-col gap-[5px]">
                <span className={FIELD_LABEL_CLASS}>{which === "min" ? "Min" : "Max"}</span>
                <div className="flex h-[34px] items-center bg-field border-b border-border-strong focus-within:border-b-2 focus-within:border-b-accent">
                  <input value={text} onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") commit(which, text); }}
                    onBlur={() => commit(which, text)} placeholder="—"
                    aria-label={`${which === "min" ? "Minimum" : "Maximum"} ${metric.name}${isPercent ? " in percent" : ""}`}
                    className="h-full w-full border-none bg-transparent px-2 text-right text-[13px] tabular-nums text-text-primary placeholder:text-text-muted outline-none" />
                  {unit && <span className="px-2 text-[11px] text-text-muted">{unit}</span>}
                </div>
              </label>
            );
          })}
        </div>
      </div>
    </section>
  );
}
