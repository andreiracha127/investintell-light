"use client";

/**
 * Wizard Tab 2 — one card per selected filter (position order): preset chips,
 * min/max inputs, and the universe distribution histogram with the selected
 * band accent-highlighted. The header shows the live headline match count,
 * updated from every filter PUT response (and the build GET on tab open).
 *
 * Range slider note: the dual-thumb slider is F7 polish — here the two
 * numeric inputs + clickable presets + the highlighted histogram deliver the
 * explore-before-cut value with exact, accessible bounds.
 *
 * Percent boundary rule (the portfolio-form pattern): metrics with
 * data_type "percent" are decimal fractions in the API and displayed/entered
 * as 0-100 here — display = value*100, send = input/100. Conversion happens
 * ONLY in `toDisplayText` / `parseBound` below; currency/float/int pass raw.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  deleteScreenFilter,
  fetchBuildMetric,
  putScreenFilter,
  type Distribution,
  type FilterBody,
  type MetricDef,
  type PresetBand,
  type Screen,
  type ScreenFilter,
} from "@/lib/api/client";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import {
  applyFilterResponse,
  ErrorPanel,
  FIELD_LABEL_CLASS,
  isSnapshotMissing,
  NO_DATA_NOTE,
  retryPolicy,
} from "@/components/screener/shared";
import { buildHcDistributionOption } from "@/lib/charts/hc/distribution";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatCompact } from "@/lib/format";
import { parseDecimal } from "@/lib/parse";

/** Build-card cache shape: PUT responses may legitimately carry no distribution. */
interface BuildCardData {
  distribution: Distribution | null;
  headline_count: number;
  available_count: number;
}

export function BuildTab({
  screen,
  catalog,
}: {
  screen: Screen;
  catalog: MetricDef[];
}) {
  // Live headline count — fed by every PUT response and each build GET.
  const [headline, setHeadline] = useState<number | null>(null);

  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const byCode = useMemo(
    () => new Map(catalog.map((m) => [m.code, m])),
    [catalog],
  );
  const filters = useMemo(
    () => [...screen.filters].sort((a, b) => a.position - b.position),
    [screen.filters],
  );

  return (
    <section className="flex flex-col gap-px">
      <div className="bg-surface-2 border border-border px-[var(--ix-pad)] py-3 flex flex-wrap items-center gap-2.5">
        <h2 className="ix-label m-0">Build Filters</h2>
        <span
          aria-live="polite"
          className="ml-auto inline-flex h-[22px] items-center bg-accent-wash border border-accent px-2 tabular-nums text-[11px] font-bold text-accent"
        >
          {headline === null ? "— matches" : `${formatCompact(headline)} matches`}
        </span>
      </div>

      {filters.length === 0 ? (
        <div className="bg-surface-2 border border-border border-t-0 px-6 py-10 text-center text-[13px] text-text-muted">
          No metrics selected — pick some in Select Metrics.
        </div>
      ) : (
        filters.map((filter) => (
          <FilterCard
            key={filter.metric_code}
            screenId={screen.id}
            filter={filter}
            metric={byCode.get(filter.metric_code)}
            colors={colors}
            onHeadline={setHeadline}
          />
        ))
      )}
    </section>
  );
}

/* ── One filter card ──────────────────────────────────────────────────────── */

function FilterCard({
  screenId,
  filter,
  metric,
  colors,
  onHeadline,
}: {
  screenId: number;
  filter: ScreenFilter;
  /** Undefined only if the catalog is missing the code — degrade to raw code. */
  metric: MetricDef | undefined;
  colors: ChartColors | null;
  onHeadline: (count: number) => void;
}) {
  const queryClient = useQueryClient();
  const isPercent = metric?.data_type === "percent";

  // API value -> input text (percent fractions display as 0-100).
  const toDisplayText = (value: number | null): string =>
    value === null ? "" : String(isPercent ? value * 100 : value);

  // Input text -> API value: "" = unbounded (null), invalid = undefined.
  const parseBound = (text: string): number | null | undefined => {
    if (text.trim() === "") return null;
    const v = parseDecimal(text);
    if (!Number.isFinite(v)) return undefined;
    return isPercent ? v / 100 : v;
  };

  const [minText, setMinText] = useState(() => toDisplayText(filter.min_value));
  const [maxText, setMaxText] = useState(() => toDisplayText(filter.max_value));

  const buildQuery = useQuery<BuildCardData, Error>({
    queryKey: ["screen-build", screenId, filter.metric_code],
    queryFn: ({ signal }) => fetchBuildMetric(screenId, filter.metric_code, signal),
    staleTime: 60_000,
    retry: retryPolicy,
  });

  // Report the headline count from the build GET (tab open / refetch).
  const buildHeadline = buildQuery.data?.headline_count;
  useEffect(() => {
    if (buildHeadline !== undefined) onHeadline(buildHeadline);
  }, [buildHeadline, onHeadline]);

  const putMutation = useMutation({
    mutationFn: (body: FilterBody) =>
      putScreenFilter(screenId, filter.metric_code, body),
    onSuccess: (resp) => {
      applyFilterResponse(queryClient, screenId, resp);
      queryClient.setQueryData<BuildCardData>(
        ["screen-build", screenId, filter.metric_code],
        { distribution: resp.distribution, headline_count: resp.headline_count, available_count: resp.available_count },
      );
      onHeadline(resp.headline_count);
    },
  });
  const removeMutation = useMutation({
    mutationFn: () => deleteScreenFilter(screenId, filter.metric_code),
    onSuccess: (resp) => {
      applyFilterResponse(queryClient, screenId, resp);
      queryClient.removeQueries({
        queryKey: ["screen-build", screenId, filter.metric_code],
      });
      onHeadline(resp.headline_count);
    },
  });

  const parsedMin = parseBound(minText);
  const parsedMax = parseBound(maxText);
  const minInvalid = parsedMin === undefined;
  const maxInvalid = parsedMax === undefined;

  const commitBounds = () => {
    if (parsedMin === undefined || parsedMax === undefined) return;
    if (parsedMin === filter.min_value && parsedMax === filter.max_value) return;
    putMutation.mutate({ min_value: parsedMin, max_value: parsedMax });
  };

  const applyPreset = (preset: PresetBand) => {
    setMinText(toDisplayText(preset.min_value));
    setMaxText(toDisplayText(preset.max_value));
    putMutation.mutate({
      min_value: preset.min_value,
      max_value: preset.max_value,
    });
  };
  const clearBounds = () => {
    setMinText("");
    setMaxText("");
    if (filter.min_value !== null || filter.max_value !== null) {
      putMutation.mutate({ min_value: null, max_value: null });
    }
  };

  // The catalog ships a null/null "Custom" preset; our dedicated Custom chip
  // below covers that semantics (clear bounds), so drop unbounded duplicates.
  const presets = (metric?.presets ?? []).filter(
    (p) => p.min_value !== null || p.max_value !== null,
  );
  const matchesPreset = (p: PresetBand) =>
    filter.min_value === p.min_value && filter.max_value === p.max_value;
  const customActive = !presets.some(matchesPreset);

  const distribution = buildQuery.data?.distribution ?? null;
  const availableCount = buildQuery.data?.available_count;
  const option = useMemo(
    () =>
      distribution && colors
        ? buildHcDistributionOption(
            distribution,
            { min: filter.min_value, max: filter.max_value },
            metric?.data_type ?? "float",
            colors,
          )
        : null,
    [distribution, colors, filter.min_value, filter.max_value, metric?.data_type],
  );

  const name = metric?.name ?? filter.metric_code;
  const pending = putMutation.isPending || removeMutation.isPending;
  const mutationError = putMutation.error ?? removeMutation.error;
  const unit = isPercent ? "%" : "";

  return (
    <div className="bg-surface-2 border border-border ix-pad flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[13px] font-bold text-text-primary">{name}</h3>
        {metric && (
          <span className="text-[11px] text-text-muted">
            {metric.abbreviation} · {metric.scale_note}
          </span>
        )}
        <button
          type="button"
          onClick={() => removeMutation.mutate()}
          disabled={pending}
          aria-label={`Remove filter ${name}`}
          title={`Remove ${name}`}
          className="ml-auto px-1.5 py-0.5 text-text-muted hover:text-loss hover:bg-layer-hover transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        >
          ×
        </button>
      </div>

      {/* Distribution histogram — the visual behind the range inputs. */}
      {buildQuery.isPending ? (
        <div
          aria-busy="true"
          aria-label={`Loading ${name} distribution`}
          className="h-[140px] bg-zebra animate-pulse"
        />
      ) : buildQuery.isError ? (
        isSnapshotMissing(buildQuery.error) ? (
          <p className="h-[140px] flex items-center justify-center bg-zebra text-[13px] text-text-muted">
            {NO_DATA_NOTE}
          </p>
        ) : (
          <ErrorPanel
            title={`Failed to load ${name} distribution`}
            message={buildQuery.error.message}
            onRetry={() => buildQuery.refetch()}
          />
        )
      ) : availableCount === 0 ? (
        <p className="h-[140px] flex items-center justify-center bg-zebra text-[13px] text-text-muted">
          {NO_DATA_NOTE}
        </p>
      ) : option ? (
        <HighchartsChart options={option} className="h-[140px]" />
      ) : (
        <p className="h-[140px] flex items-center justify-center bg-zebra text-[13px] text-text-muted">
          No companies in this band.
        </p>
      )}

      {/* Preset chips + Custom (clears bounds). */}
      {presets.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {presets.map((preset) => (
            <button
              key={preset.name}
              type="button"
              onClick={() => applyPreset(preset)}
              disabled={pending}
              aria-pressed={matchesPreset(preset)}
              aria-label={`Apply preset ${preset.name} for ${name}`}
              className={`inline-flex h-[22px] items-center border px-2.5 text-[11px] font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                matchesPreset(preset)
                  ? "bg-accent-wash border-accent text-accent"
                  : "bg-field border-border-strong text-text-secondary hover:bg-layer-hover"
              }`}
            >
              {preset.name}
            </button>
          ))}
          <button
            type="button"
            onClick={clearBounds}
            disabled={pending}
            aria-pressed={customActive}
            aria-label={`Clear bounds for ${name}`}
            className={`inline-flex h-[22px] items-center border px-2.5 text-[11px] font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              customActive
                ? "bg-accent-wash border-accent text-accent"
                : "bg-field border-border-strong text-text-secondary hover:bg-layer-hover"
            }`}
          >
            Custom
          </button>
        </div>
      )}

      {/* Min/max bounds — commit on Enter or blur; empty = unbounded. */}
      <div className="flex flex-wrap items-end gap-3.5 text-[12px] text-text-secondary">
        <label className="flex w-[130px] flex-col gap-[5px]">
          <span className={FIELD_LABEL_CLASS}>Min</span>
          <div
            className={`flex h-[34px] items-center bg-field border-b ${
              minInvalid ? "border-b-[var(--color-loss)]" : "border-b-border-strong"
            } focus-within:border-b-2 focus-within:border-b-accent`}
          >
            <input
              value={minText}
              onChange={(e) => setMinText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitBounds();
              }}
              onBlur={commitBounds}
              placeholder="—"
              aria-label={`Minimum ${name}${isPercent ? " in percent" : ""}`}
              aria-invalid={minInvalid}
              className="h-full w-full border-none bg-transparent px-2 text-right text-[13px] tabular-nums text-text-primary placeholder:text-text-muted outline-none"
            />
            {unit && <span className="px-2 text-[11px] text-text-muted">{unit}</span>}
          </div>
        </label>
        <label className="flex w-[130px] flex-col gap-[5px]">
          <span className={FIELD_LABEL_CLASS}>Max</span>
          <div
            className={`flex h-[34px] items-center bg-field border-b ${
              maxInvalid ? "border-b-[var(--color-loss)]" : "border-b-border-strong"
            } focus-within:border-b-2 focus-within:border-b-accent`}
          >
            <input
              value={maxText}
              onChange={(e) => setMaxText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitBounds();
              }}
              onBlur={commitBounds}
              placeholder="—"
              aria-label={`Maximum ${name}${isPercent ? " in percent" : ""}`}
              aria-invalid={maxInvalid}
              className="h-full w-full border-none bg-transparent px-2 text-right text-[13px] tabular-nums text-text-primary placeholder:text-text-muted outline-none"
            />
            {unit && <span className="px-2 text-[11px] text-text-muted">{unit}</span>}
          </div>
        </label>
        {pending && <span className="pb-2 text-text-muted">Saving…</span>}
      </div>

      {mutationError && (
        <p role="alert" className="text-[12px] text-loss break-words">
          {mutationError.message}
        </p>
      )}
    </div>
  );
}
