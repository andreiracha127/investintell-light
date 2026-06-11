"use client";

/**
 * Static Portfolio Analysis — ad-hoc position form + render-ready results
 * from `POST /portfolio/analysis` via TanStack Query mutation.
 *
 * The frontend computes NO finance. The only numeric conversion is the
 * percent-input -> decimal-fraction step at the API boundary, done in exactly
 * one place (`buildRequest`). Quantities-mode results can be persisted via
 * "Save as portfolio" (see `SaveAsPortfolio` for the weights-mode limitation).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  createPortfolio,
  postPortfolioAnalysis,
  RANGE_PRESETS,
  type PortfolioAnalysis,
  type PortfolioAnalysisRequest,
  type PortfolioCreateRequest,
  type PortfolioMode,
  type RangePreset,
} from "@/lib/api/client";
import { parseDecimal } from "@/lib/parse";
import { buildAllocationOption } from "@/lib/charts/allocation";
import { buildRiskContributionsOption } from "@/lib/charts/contributions";
import { buildCumulativeOption } from "@/lib/charts/cumulative";
import { buildHeatmapOption } from "@/lib/charts/heatmap";
import { buildHistogramOption } from "@/lib/charts/histogram";
import { buildNavOption } from "@/lib/charts/nav";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { EChart } from "@/components/charts/EChart";
import { Card, StatRow, valueTone } from "@/components/ui/panels";

interface PositionRow {
  id: number;
  ticker: string;
  /** Raw input text: percent (40 = 40%) in weights mode, share count in quantities mode. */
  value: string;
}

const MIN_POSITIONS = 2;
const MAX_POSITIONS = 50;
/** Allowed deviation of the weight sum from 100, in percentage points. */
const WEIGHT_SUM_TOLERANCE_PP = 0.1;

const INPUT_CLASS =
  "px-3 py-1.5 rounded-[6px] bg-surface-1 border border-border text-[13px] " +
  "text-text-primary placeholder:text-text-muted focus:border-accent-muted focus:outline-none";

export function StaticPortfolioView() {
  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const [mode, setMode] = useState<PortfolioMode>("weights");
  const [rows, setRows] = useState<PositionRow[]>([
    { id: 1, ticker: "", value: "" },
    { id: 2, ticker: "", value: "" },
  ]);
  const nextRowId = useRef(3);
  const [range, setRange] = useState<RangePreset>("1Y");
  const [benchmark, setBenchmark] = useState("SPY");

  const mutation = useMutation({
    // 4xx responses surface their backend `detail` verbatim; mutations never
    // retry (TanStack default), so a 422 fails loud exactly once.
    mutationFn: (body: PortfolioAnalysisRequest) => postPortfolioAnalysis(body),
  });

  const updateRow = (id: number, patch: Partial<Omit<PositionRow, "id">>) => {
    setRows((prev) =>
      prev.map((row) => (row.id === id ? { ...row, ...patch } : row)),
    );
  };

  const addRow = () => {
    if (rows.length >= MAX_POSITIONS) return;
    const id = nextRowId.current++;
    setRows((prev) => [...prev, { id, ticker: "", value: "" }]);
  };

  const removeRow = (id: number) => {
    setRows((prev) =>
      prev.length <= MIN_POSITIONS ? prev : prev.filter((row) => row.id !== id),
    );
  };

  /** Switching modes clears the value column — no unit reinterpretation. */
  const switchMode = (next: PortfolioMode) => {
    if (next === mode) return;
    setMode(next);
    setRows((prev) => prev.map((row) => ({ ...row, value: "" })));
  };

  const validation = useMemo(() => {
    const values = rows.map((row) => parseDecimal(row.value));
    const tickersOk = rows.every((row) => row.ticker.trim().length > 0);
    const valuesOk = values.every((v) => Number.isFinite(v) && v > 0);
    // A row has an invalid value when the input is non-empty but parses NaN.
    const invalidValueIds = rows
      .filter((row) => row.value.trim() !== "" && !Number.isFinite(parseDecimal(row.value)))
      .map((row) => row.id);
    const weightSumPct = values.reduce(
      (sum, v) => sum + (Number.isFinite(v) ? v : 0),
      0,
    );
    const weightSumOk =
      Math.abs(weightSumPct - 100) <= WEIGHT_SUM_TOLERANCE_PP;
    const canSubmit =
      rows.length >= MIN_POSITIONS &&
      tickersOk &&
      valuesOk &&
      benchmark.trim().length > 0 &&
      (mode !== "weights" || weightSumOk);
    return { weightSumPct, weightSumOk, canSubmit, invalidValueIds };
  }, [rows, mode, benchmark]);

  /**
   * The ONE place form values become API units: weight percent inputs
   * (40 = 40%) divide by 100 into decimal fractions; quantities pass through.
   * Uses parseDecimal so that comma-separated decimals (e.g. "40,5") work.
   */
  const buildRequest = (): PortfolioAnalysisRequest => ({
    positions: rows.map((row) => {
      const ticker = row.ticker.trim().toUpperCase();
      const value = parseDecimal(row.value);
      return mode === "weights"
        ? { ticker, weight: value / 100 }
        : { ticker, quantity: value };
    }),
    mode,
    range,
    benchmark: benchmark.trim().toUpperCase(),
  });

  const onAnalyze = () => {
    if (!validation.canSubmit || mutation.isPending) return;
    mutation.mutate(buildRequest());
  };

  return (
    <div className="px-6 py-5 max-w-[1400px] mx-auto flex flex-col gap-5">
      <h1 className="text-2xl font-bold tracking-tight text-text-primary">
        Static Portfolio Analysis
      </h1>

      {/* ── Position form ── */}
      <Card title="Positions">
        <div className="flex flex-col gap-2">
          {rows.map((row, index) => {
            const isInvalid = validation.invalidValueIds.includes(row.id);
            return (
              <div key={row.id} className="flex items-center gap-2">
                <input
                  value={row.ticker}
                  onChange={(e) =>
                    updateRow(row.id, { ticker: e.target.value.toUpperCase() })
                  }
                  placeholder="TICKER"
                  aria-label={`Position ${index + 1} ticker`}
                  className={`w-[130px] uppercase ${INPUT_CLASS}`}
                />
                <input
                  value={row.value}
                  onChange={(e) => updateRow(row.id, { value: e.target.value })}
                  placeholder={mode === "weights" ? "Weight %" : "Quantity"}
                  aria-label={
                    mode === "weights"
                      ? `Position ${index + 1} weight in percent`
                      : `Position ${index + 1} quantity`
                  }
                  aria-invalid={isInvalid}
                  className={`w-[130px] tabular-nums ${INPUT_CLASS} ${
                    isInvalid ? "border-[var(--color-loss)]" : ""
                  }`}
                />
                <button
                  type="button"
                  onClick={() => removeRow(row.id)}
                  disabled={rows.length <= MIN_POSITIONS}
                  aria-label={`Remove position ${index + 1}`}
                  className="px-2 py-1 rounded-[6px] text-text-muted hover:text-loss hover:bg-surface-1 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  ×
                </button>
              </div>
            );
          })}
        </div>

        {validation.invalidValueIds.length > 0 && (
          <p
            role="alert"
            className="mt-2 text-[12px] text-loss"
          >
            Invalid number in highlighted field — use . or , as decimal separator
          </p>
        )}

        <button
          type="button"
          onClick={addRow}
          disabled={rows.length >= MAX_POSITIONS}
          className="mt-3 px-3 py-1.5 rounded-[6px] bg-surface-1 border border-border text-[12px] text-text-secondary hover:text-text-primary hover:border-accent-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          + Add position
        </button>

        {/* ── Controls row ── */}
        <div className="mt-4 pt-4 border-t border-border flex flex-wrap items-center gap-x-5 gap-y-3">
          {/* Mode toggle */}
          <div
            role="group"
            aria-label="Position mode"
            className="flex rounded-[7px] border border-border bg-surface-1 p-0.5"
          >
            {(["weights", "quantities"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => switchMode(m)}
                aria-pressed={m === mode}
                className={`px-3 py-1 rounded-[5px] text-[12px] font-medium transition-colors ${
                  m === mode
                    ? "bg-surface-3 text-accent"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                {m === "weights" ? "Weights" : "Quantities"}
              </button>
            ))}
          </div>

          {/* Range */}
          <div
            role="group"
            aria-label="Date range"
            className="flex rounded-[7px] border border-border bg-surface-1 p-0.5"
          >
            {RANGE_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setRange(preset)}
                aria-pressed={preset === range}
                className={`px-3 py-1 rounded-[5px] text-[12px] font-medium transition-colors ${
                  preset === range
                    ? "bg-surface-3 text-accent"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                {preset}
              </button>
            ))}
          </div>

          {/* Benchmark */}
          <label className="flex items-center gap-2 text-[12px] text-text-secondary">
            Benchmark
            <input
              value={benchmark}
              onChange={(e) => setBenchmark(e.target.value.toUpperCase())}
              placeholder="SPY"
              aria-label="Benchmark ticker"
              className={`w-[90px] uppercase ${INPUT_CLASS}`}
            />
          </label>

          {/* Weight-sum indicator */}
          {mode === "weights" && (
            <span
              className={`tabular-nums text-[13px] font-semibold ${
                validation.weightSumOk ? "text-gain" : "text-loss"
              }`}
            >
              Σ {formatNumber(validation.weightSumPct, 1)}%
            </span>
          )}

          <button
            type="button"
            onClick={onAnalyze}
            disabled={!validation.canSubmit || mutation.isPending}
            className="ml-auto px-5 py-1.5 rounded-[7px] bg-accent text-surface-0 text-sm font-semibold hover:bg-accent-strong transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? "Analyzing…" : "Analyze"}
          </button>
        </div>
      </Card>

      {/* ── Results ── */}
      {mutation.isPending ? (
        <ResultsSkeleton />
      ) : mutation.isError ? (
        <div
          role="alert"
          className="bg-surface-2 border border-loss rounded-xl px-5 py-4"
        >
          <h2 className="text-sm font-semibold text-loss mb-1">
            Analysis failed
          </h2>
          <p className="text-[13px] text-text-secondary break-words whitespace-pre-wrap">
            {mutation.error.message}
          </p>
        </div>
      ) : mutation.data && mutation.variables && colors ? (
        <Results
          data={mutation.data}
          request={mutation.variables}
          colors={colors}
        />
      ) : (
        <p className="text-[13px] text-text-muted">
          Add at least two positions and press Analyze to run a static
          portfolio analysis.
        </p>
      )}
    </div>
  );
}

/* ── Results ──────────────────────────────────────────────────────────────── */

function Results({
  data,
  request,
  colors,
}: {
  data: PortfolioAnalysis;
  /** The exact request that produced `data` — source for "Save as portfolio". */
  request: PortfolioAnalysisRequest;
  colors: ChartColors;
}) {
  const { params, allocation, stats } = data;

  const allocationOption = useMemo(
    () => buildAllocationOption(allocation.positions, colors),
    [allocation.positions, colors],
  );
  const navOption = useMemo(
    () => buildNavOption(data.nav, colors),
    [data.nav, colors],
  );
  const comparisonOption = useMemo(
    () =>
      buildCumulativeOption(
        {
          asset: data.benchmark_comparison.portfolio,
          benchmark: data.benchmark_comparison.benchmark,
        },
        "Portfolio",
        params.benchmark,
        colors,
      ),
    [data.benchmark_comparison, params.benchmark, colors],
  );
  const heatmapOption = useMemo(
    () => buildHeatmapOption(data.correlation_matrix, colors),
    [data.correlation_matrix, colors],
  );
  const contributionsOption = useMemo(
    () => buildRiskContributionsOption(data.risk_contributions, colors),
    [data.risk_contributions, colors],
  );
  const histogramOption = useMemo(
    () => buildHistogramOption(data.histogram, colors),
    [data.histogram, colors],
  );

  return (
    <div className="flex flex-col gap-5">
      {/* ── Params echo + save ── */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="tabular-nums text-[12px] text-text-muted">
          Window: {formatDate(params.start_date)} →{" "}
          {formatDate(params.end_date)} · Benchmark: {params.benchmark}
        </p>
        {/* Keyed to the analyzed request so a fresh analysis resets the
            save flow — a stale "Saved as …" must not imply the NEW result
            was persisted. */}
        <SaveAsPortfolio key={JSON.stringify(request)} request={request} />
      </div>

      {/* ── Allocation + statistics ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Allocation">
          <EChart option={allocationOption} className="h-[260px] w-full" />
          <table className="w-full mt-3 text-[13px]">
            <thead>
              <tr className="text-[11px] uppercase tracking-[0.06em] text-text-muted">
                <th className="py-1.5 text-left font-semibold">Ticker</th>
                <th className="py-1.5 text-right font-semibold">Weight</th>
                <th className="py-1.5 text-right font-semibold">
                  Initial Value
                </th>
              </tr>
            </thead>
            <tbody>
              {allocation.positions.map((position) => (
                <tr key={position.ticker} className="border-t border-border">
                  <td className="py-1.5 font-semibold text-text-primary">
                    {position.ticker}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-text-secondary">
                    {formatPercent(position.weight, 1)}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-text-secondary">
                    {formatCurrency(position.initial_value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Statistics">
          <dl>
            <StatRow
              label="Annualized Volatility"
              value={formatPercent(stats.annualized_volatility)}
            />
            <StatRow label="VaR 95 (1d)" value={formatPercent(stats.var_95)} />
            <StatRow label="VaR 99 (1d)" value={formatPercent(stats.var_99)} />
            <StatRow
              label="CVaR 95 (1d)"
              value={formatPercent(stats.cvar_95)}
            />
            <StatRow
              label="Total Return"
              value={formatPercent(stats.total_return, 2, { signed: true })}
              tone={valueTone(stats.total_return)}
            />
            <StatRow
              label={`Beta vs ${params.benchmark}`}
              value={formatNumber(stats.beta)}
            />
            <StatRow
              label={`Correlation vs ${params.benchmark}`}
              value={formatNumber(stats.correlation)}
            />
            <StatRow
              label="Diversification Ratio"
              value={formatNumber(stats.diversification_ratio)}
            />
            <StatRow
              label="Max Drawdown"
              value={formatPercent(stats.max_drawdown.depth)}
              tone="text-loss"
              detail={`${formatDate(stats.max_drawdown.peak_date)} → ${formatDate(stats.max_drawdown.trough_date)}`}
            />
            <StatRow
              label="Best Day"
              value={formatPercent(stats.best_day.value, 2, { signed: true })}
              tone="text-gain"
              detail={formatDate(stats.best_day.date)}
            />
            <StatRow
              label="Worst Day"
              value={formatPercent(stats.worst_day.value, 2, { signed: true })}
              tone="text-loss"
              detail={formatDate(stats.worst_day.date)}
            />
          </dl>
        </Card>
      </div>

      {/* ── NAV ── */}
      <Card
        title="Portfolio NAV"
        subtitle={
          params.mode === "weights"
            ? `initial ${formatCurrency(params.initial_nav)} (notional)`
            : undefined
        }
      >
        <EChart option={navOption} className="h-[300px] w-full" />
      </Card>

      {/* ── Vs benchmark ── */}
      <Card title={`Cumulative Return vs ${params.benchmark}`}>
        <EChart option={comparisonOption} className="h-[300px] w-full" />
      </Card>

      {/* ── Correlation + risk contributions ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Correlation Matrix">
          <EChart option={heatmapOption} className="h-[360px] w-full" />
        </Card>
        <Card title="Risk Contributions">
          <EChart option={contributionsOption} className="h-[360px] w-full" />
        </Card>
      </div>

      {/* ── Distribution ── */}
      <Card title="Daily Return Distribution">
        <EChart option={histogramOption} className="h-[280px] w-full" />
      </Card>
    </div>
  );
}

/* ── Save as portfolio ────────────────────────────────────────────────────── */

/**
 * Persist the just-analyzed positions via POST /portfolios.
 *
 * Persistence is quantity-based by design (a portfolio stores
 * ticker/quantity/acq_price), and the analysis response carries no
 * window-start prices, so a faithful weight→quantity conversion is impossible
 * without a backend change. Saving is therefore only offered for
 * quantities-mode analyses; weights mode shows a disabled button with a hint.
 */
function SaveAsPortfolio({ request }: { request: PortfolioAnalysisRequest }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");

  const saveMutation = useMutation({
    mutationFn: (body: PortfolioCreateRequest) => createPortfolio(body),
    onSuccess: () => {
      // The Portfolio Overview page lists portfolios from this cache key.
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
    },
  });

  if (request.mode !== "quantities") {
    return (
      <span
        className="ml-auto flex items-center gap-2"
        title="Switch to quantities mode to save"
      >
        <button
          type="button"
          disabled
          className="px-3 py-1 rounded-[6px] bg-surface-1 border border-border text-[12px] text-text-muted opacity-50 cursor-not-allowed"
        >
          Save as portfolio
        </button>
        <span className="text-[11px] text-text-muted">
          Switch to quantities mode to save
        </span>
      </span>
    );
  }

  if (saveMutation.isSuccess) {
    return (
      <p className="ml-auto text-[12px] text-text-secondary">
        Saved as{" "}
        <span className="font-semibold text-text-primary">
          {saveMutation.data.name}
        </span>
        {" · "}
        <Link
          href="/portfolio"
          className="text-accent hover:text-accent-strong transition-colors"
        >
          View in Portfolio Overview
        </Link>
      </p>
    );
  }

  const canSave = name.trim().length > 0 && !saveMutation.isPending;
  const save = () => {
    if (!canSave) return;
    saveMutation.mutate({
      name: name.trim(),
      cash: 0,
      positions: request.positions
        .filter(
          (p): p is typeof p & { quantity: number } => p.quantity != null,
        )
        .map((p) => ({ ticker: p.ticker, quantity: p.quantity })),
    });
  };

  return (
    <div className="ml-auto flex flex-col items-end gap-1">
      {open ? (
        <div className="flex items-center gap-2">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              else if (e.key === "Escape") setOpen(false);
            }}
            placeholder="Portfolio name"
            aria-label="Name for the saved portfolio"
            className={`w-[170px] ${INPUT_CLASS}`}
          />
          <button
            type="button"
            onClick={save}
            disabled={!canSave}
            className="px-3 py-1.5 rounded-[6px] bg-accent text-surface-0 text-[12px] font-semibold hover:bg-accent-strong transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saveMutation.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="px-3 py-1 rounded-[6px] bg-surface-1 border border-border text-[12px] text-text-secondary hover:text-text-primary hover:border-accent-muted transition-colors"
        >
          Save as portfolio
        </button>
      )}
      {saveMutation.isError && (
        <p role="alert" className="text-[12px] text-loss break-words max-w-[420px] text-right">
          {saveMutation.error.message}
        </p>
      )}
    </div>
  );
}

function ResultsSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading portfolio analysis"
      className="flex flex-col gap-5 animate-pulse"
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="h-[420px] rounded-xl bg-surface-2" />
        <div className="h-[420px] rounded-xl bg-surface-2" />
      </div>
      <div className="h-[300px] rounded-xl bg-surface-2" />
      <div className="h-[300px] rounded-xl bg-surface-2" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="h-[360px] rounded-xl bg-surface-2" />
        <div className="h-[360px] rounded-xl bg-surface-2" />
      </div>
    </div>
  );
}
