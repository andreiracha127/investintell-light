"use client";

/**
 * Active-criterion distribution panel.
 *
 * Design source: Screener.dc.html (distribution panel section). Same props,
 * same data flow, same `/lib` calls — presentation only:
 *   • heading with an info tooltip sourced from the catalog `scale_note`
 *   • upgraded histogram (real counts, "Companies" axis, accent in-range /
 *     grey out-of-range, range+count tooltip) via the page-prefixed builder
 *   • a plain-language read-out under the chart ("34 companies have … in range")
 *   • quick-range preset chips, and framed Min/Max fields with $/% affixes
 */
import { useEffect, useMemo, useState } from "react";

import type { MetricBuild, MetricDef, ScreenFilter } from "@/lib/api/client";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { FIELD_LABEL_CLASS } from "@/components/screener/shared";
import { InfoDot } from "@/components/ui/panels";
import { buildHcScreenerDistributionOption } from "@/lib/charts/hc/screener-distribution";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { formatCompact, formatMetricValue } from "@/lib/format";
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
  const isCurrency = metric.data_type === "currency";
  // $ prefixes the field (left); % suffixes it (right). Mirrors the prototype.
  const prefix = isCurrency ? "$" : "";
  const unit = isPercent ? "%" : "";

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
        ? buildHcScreenerDistributionOption(dist, { min: filter.min_value, max: filter.max_value }, metric.data_type, colors)
        : null,
    [dist, colors, filter.min_value, filter.max_value, metric.data_type],
  );

  const commit = (which: "min" | "max", text: string) => {
    const parsed = parseBound(text, isPercent);
    if (parsed === undefined) {
      // invalid → revert to the persisted value (visible validation feedback)
      if (which === "min") setMinText(toDisplayText(filter.min_value, isPercent));
      else setMaxText(toDisplayText(filter.max_value, isPercent));
      return;
    }
    const current = which === "min" ? filter.min_value : filter.max_value;
    if (parsed !== current) onEditBound(which, parsed);
  };

  const presets = (metric.presets ?? []).filter((p) => p.min_value !== null || p.max_value !== null);
  const matches = (p: { min_value: number | null; max_value: number | null }) =>
    filter.min_value === p.min_value && filter.max_value === p.max_value;

  // Plain-language read-out under the chart.
  const lo = filter.min_value == null ? "any" : formatMetricValue(filter.min_value, metric.data_type);
  const hi = filter.max_value == null ? "any" : formatMetricValue(filter.max_value, metric.data_type);
  const readOut =
    headline === null
      ? "—"
      : `${formatCompact(headline)} ${headline === 1 ? "company has" : "companies have"} ${metric.name} in range (${lo} to ${hi}). Shaded bars are inside your range.`;

  return (
    <section className="border-t border-border-strong bg-zebra ix-pad">
      {/* heading + match tag + reorder */}
      <div className="flex flex-wrap items-center gap-2.5">
        <h3 className="ix-label m-0 flex items-center gap-1.5">
          Distribution — {metric.name}
          {metric.scale_note && <InfoDot tip={metric.scale_note} />}
        </h3>
        <span className="inline-flex h-[22px] items-center bg-accent-wash border border-accent px-2 tabular-nums text-[11px] font-bold text-accent">
          {headline === null ? "— matches" : `${formatCompact(headline)} match`}
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

      <div className="mt-3.5 flex flex-wrap items-end gap-x-6 gap-y-4">
        {/* Histogram + read-out + quick ranges */}
        <div className="min-w-[300px] flex-1 max-w-[600px]">
          {option ? (
            <HighchartsChart options={option} modules={[]} className="h-[170px]" />
          ) : (
            <p className="h-[170px] flex items-center justify-center bg-field text-[13px] text-text-muted">
              No metric data yet — run the metrics job.
            </p>
          )}
          <p className="mt-2 text-[11.5px] text-text-secondary">{readOut}</p>
          {presets.length > 0 && (
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              <span className={`${FIELD_LABEL_CLASS} mr-0.5`}>Quick ranges</span>
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

        {/* Min / Max — framed fields with $/% affixes; commit on Enter/blur, revert on invalid */}
        <div className="flex items-end gap-4 text-[12px] text-text-secondary">
          {(["min", "max"] as const).map((which) => {
            const text = which === "min" ? minText : maxText;
            const setText = which === "min" ? setMinText : setMaxText;
            return (
              <label key={which} className="flex w-[130px] flex-col gap-[6px]">
                <span className={FIELD_LABEL_CLASS}>{which === "min" ? "Minimum" : "Maximum"}</span>
                <div className="flex h-[36px] items-center bg-field border-b border-border-strong focus-within:border-b-2 focus-within:border-b-accent">
                  {prefix && <span className="pl-2 text-[11px] text-text-muted">{prefix}</span>}
                  <input value={text} onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") commit(which, text); }}
                    onBlur={() => commit(which, text)} placeholder="—"
                    aria-label={`${which === "min" ? "Minimum" : "Maximum"} ${metric.name}${isPercent ? " in percent" : ""}`}
                    className="h-full w-full min-w-0 border-none bg-transparent px-2 text-right text-[14px] tabular-nums text-text-primary placeholder:text-text-muted outline-none" />
                  {unit && <span className="pr-2 text-[11px] text-text-muted">{unit}</span>}
                </div>
              </label>
            );
          })}
        </div>
      </div>
    </section>
  );
}
