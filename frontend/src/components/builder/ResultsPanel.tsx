"use client";

/**
 * Builder results — KPI tiles, the proposed-weights table (inline weight
 * bars, current/delta columns when seeded from a saved portfolio), the
 * Current-vs-Proposed donuts, a collapsible μ diagnostics table, the
 * client-side CSV export, and Save-as-portfolio (POST /builder/save).
 */
import { useMutation, useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import {
  fetchFundProfile,
  postBuilderSave,
  type BuilderObjective,
  type BuilderSaveRequest,
  type FundProfile,
  type OptimizeResponse,
} from "@/lib/api/client";
import { parseDecimal } from "@/lib/parse";
import { buildHcAllocationOption } from "@/lib/charts/hc/allocation";
import type { ChartColors } from "@/lib/charts/theme";
import { formatNumber, formatPercent } from "@/lib/format";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { Card, KpiTile, valueTone } from "@/components/ui/panels";
import {
  BUTTON_CLASS,
  BUTTON_PRIMARY_CLASS,
  ErrorPanel,
  FIELD_LABEL_CLASS,
  INPUT_CLASS,
} from "@/components/screener/shared";

import { assetKey, assetName, assetTicker, type UniverseAsset } from "./assets";

/** Current allocation of the base portfolio (when seeded from a saved one). */
export interface BaseAllocation {
  name: string;
  /** assetKey ("equity:<TICKER>") -> weight fraction by market value. */
  weights: Map<string, number>;
}

interface WeightRow {
  key: string;
  ticker: string;
  name: string;
  weight: number;
  kind: "fund" | "equity";
}

/** Weights below this are numeric solver noise — a quantity would round to 0. */
const SAVE_WEIGHT_FLOOR = 1e-6;

/** Per-row execution inputs of the save step (F8.6b), all raw text. */
interface ExecutionInputs {
  /** "" = the representative class (no class_ticker sent). */
  classTicker: string;
  fill: string;
  commission: string;
  tradeDate: string;
}

const EMPTY_EXECUTION: ExecutionInputs = {
  classTicker: "",
  fill: "",
  commission: "",
  tradeDate: "",
};

/** Parse an optional positive number; undefined = invalid, null = empty. */
function parseOptionalPositive(raw: string): number | null | undefined {
  if (raw.trim() === "") return null;
  const v = parseDecimal(raw);
  return Number.isFinite(v) && v > 0 ? v : undefined;
}

/** Parse an optional non-negative number; undefined = invalid, null = empty. */
function parseOptionalNonNegative(raw: string): number | null | undefined {
  if (raw.trim() === "") return null;
  const v = parseDecimal(raw);
  return Number.isFinite(v) && v >= 0 ? v : undefined;
}

/** Latest non-null NAV of a fund profile (the series reference price). */
function lastNav(profile: FundProfile | undefined): number | null {
  if (!profile) return null;
  for (let i = profile.nav.length - 1; i >= 0; i--) {
    const nav = profile.nav[i].nav;
    if (nav !== null) return nav;
  }
  return null;
}

export function ResultsPanel({
  result,
  objective,
  assetsByKey,
  base,
  colors,
}: {
  result: OptimizeResponse;
  objective: BuilderObjective;
  assetsByKey: Map<string, UniverseAsset>;
  base: BaseAllocation | null;
  colors: ChartColors | null;
}) {
  const { weights, expected, diagnostics } = result;

  /* ── Save as portfolio (with the optional execution step, F8.6b) ───── */
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState(
    () => `Builder ${objective} ${new Date().toISOString().slice(0, 10)}`,
  );
  const [notionalText, setNotionalText] = useState("1000000");
  const [execution, setExecution] = useState<Record<string, ExecutionInputs>>({});
  const saveMutation = useMutation({
    mutationFn: (body: BuilderSaveRequest) => postBuilderSave(body),
  });

  // One save row per weight above the floor (solver noise excluded).
  const saveRows = useMemo(
    () =>
      weights
        .filter((w) => w.weight > SAVE_WEIGHT_FLOOR)
        .map((w) => {
          const key = assetKey(w.asset);
          const known = assetsByKey.get(key);
          return {
            key,
            asset: w.asset,
            weight: w.weight,
            ticker: known
              ? assetTicker(known)
              : (w.ticker ??
                (w.asset.kind === "equity" ? w.asset.ticker : w.asset.id)),
          };
        }),
    [weights, assetsByKey],
  );

  // Fund profiles, loaded LAZILY when the form opens — they provide the
  // class catalog (select options) and the latest series NAV (Qty @ ref).
  const fundIds = useMemo(
    () => [
      ...new Set(
        saveRows.flatMap((r) => (r.asset.kind === "fund" ? [r.asset.id] : [])),
      ),
    ],
    [saveRows],
  );
  const profileQueries = useQueries({
    queries: fundIds.map((id) => ({
      queryKey: ["fund-profile", id],
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchFundProfile(id, signal),
      enabled: saveOpen,
      staleTime: 5 * 60_000,
    })),
  });
  const profilesById = new Map<string, FundProfile>();
  profileQueries.forEach((q, i) => {
    if (q.data) profilesById.set(fundIds[i], q.data);
  });
  // Data-freshness tag for the reference-price note (max NAV date synced).
  const staleness = profileQueries.reduce<string | null>(
    (acc, q) =>
      q.data?.source_nav_max_date && (!acc || q.data.source_nav_max_date > acc)
        ? q.data.source_nav_max_date
        : acc,
    null,
  );

  const notional = Number(notionalText);
  const notionalOk = Number.isFinite(notional) && notional > 0;

  // Per-row validation: an invalid fill/commission (or a commission/date
  // without a fill — ambiguous, the backend rejects it) blocks the save.
  const rowState = saveRows.map((row) => {
    const exec = execution[row.key] ?? EMPTY_EXECUTION;
    const fill = parseOptionalPositive(exec.fill);
    const commission = parseOptionalNonNegative(exec.commission);
    const valid =
      fill !== undefined &&
      commission !== undefined &&
      (fill !== null || (commission === null && exec.tradeDate.trim() === ""));
    return { row, exec, fill: fill ?? null, commission: commission ?? null, valid };
  });
  const allRowsValid = rowState.every((s) => s.valid);
  const canSave =
    saveName.trim().length > 0 && notionalOk && allRowsValid && !saveMutation.isPending;

  const onSave = () => {
    if (!canSave) return;
    saveMutation.mutate({
      name: saveName.trim(),
      notional_usd: notional,
      weights: rowState.map(({ row, exec, fill, commission }) => ({
        asset: row.asset,
        weight: row.weight,
        ...(fill !== null ? { fill_price: fill } : {}),
        ...(fill !== null && commission !== null ? { commission } : {}),
        ...(fill !== null && exec.tradeDate.trim() !== ""
          ? { trade_date: exec.tradeDate }
          : {}),
        // "" = representative class — omit class_ticker entirely.
        ...(row.asset.kind === "fund" && exec.classTicker
          ? { class_ticker: exec.classTicker }
          : {}),
      })),
    });
  };

  const setExecField = (key: string, field: keyof ExecutionInputs, value: string) =>
    setExecution((prev) => ({
      ...prev,
      [key]: { ...(prev[key] ?? EMPTY_EXECUTION), [field]: value },
    }));

  const executedCount = saveMutation.data
    ? saveMutation.data.positions.filter((p) => p.basis === "executed").length
    : 0;
  const referenceCount = saveMutation.data
    ? saveMutation.data.positions.length - executedCount
    : 0;

  const rows: WeightRow[] = useMemo(
    () =>
      weights.map((w) => {
        const key = assetKey(w.asset);
        const known = assetsByKey.get(key);
        return {
          key,
          ticker: known
            ? assetTicker(known)
            : (w.ticker ??
              (w.asset.kind === "equity" ? w.asset.ticker : w.asset.id)),
          name: known ? assetName(known) : (w.name ?? ""),
          weight: w.weight,
          kind: w.asset.kind,
        };
      }),
    [weights, assetsByKey],
  );
  const maxWeight = Math.max(...rows.map((r) => r.weight), 1e-9);

  const proposedDonut = useMemo(
    () =>
      colors
        ? buildHcAllocationOption(
            rows.map((r) => ({ name: r.ticker, value: r.weight })),
            colors,
          )
        : null,
    [rows, colors],
  );
  const currentDonut = useMemo(
    () =>
      colors && base
        ? buildHcAllocationOption(
            [...base.weights.entries()].map(([key, weight]) => ({
              name: key.replace(/^equity:/, ""),
              value: weight,
            })),
            colors,
          )
        : null,
    [base, colors],
  );

  const exportCsv = () => {
    const lines = [
      "kind,ticker,name,weight",
      ...rows.map(
        (r) =>
          `${r.kind},${csvField(r.ticker)},${csvField(r.name)},${r.weight.toFixed(6)}`,
      ),
    ];
    const blob = new Blob([lines.join("\n") + "\n"], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "builder-weights.csv";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col gap-px">
      {/* ── KPI tiles ───────────────────────────────────────────────────── */}
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile
          label="Vol (ann.)"
          value={formatPercent(expected.vol_ann)}
          tone="text-accent"
        />
        <KpiTile
          label="CVaR 95 in-sample"
          value={formatPercent(expected.cvar_95_in_sample)}
          detail="worst 5% of daily scenarios"
        />
        {expected.return_ann_bl !== null && (
          <KpiTile
            label="Return ann. (BL)"
            value={formatPercent(expected.return_ann_bl, 2, { signed: true })}
            tone={valueTone(expected.return_ann_bl)}
          />
        )}
        <KpiTile label="N obs" value={formatNumber(diagnostics.n_obs, 0)} />
        <KpiTile label="Status" value={diagnostics.status} />
      </div>

      {/* ── Weights table ───────────────────────────────────────────────── */}
      <Card
        title="Proposed weights"
        subtitle={base ? `vs ${base.name}` : undefined}
        actions={
          <span className="flex items-center gap-2">
            <button
              type="button"
              onClick={exportCsv}
              className={`${BUTTON_CLASS} inline-flex items-center gap-[7px] text-[12px]`}
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M8 1v9M4.5 7L8 10.5 11.5 7M2 14h12" stroke="currentColor" strokeWidth="1.3" />
              </svg>
              Export CSV
            </button>
            <button
              type="button"
              onClick={() => setSaveOpen((v) => !v)}
              aria-expanded={saveOpen}
              className={BUTTON_CLASS}
            >
              Save as portfolio
            </button>
          </span>
        }
      >
        {saveOpen && (
          <div className="mb-3 border border-border bg-surface-2 p-3">
            <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
              <label className="flex min-w-[280px] flex-1 flex-col gap-1">
                <span className={FIELD_LABEL_CLASS}>Portfolio name</span>
                <input
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  aria-label="Portfolio name"
                  maxLength={80}
                  className={INPUT_CLASS}
                />
              </label>
              <label className="flex w-[160px] flex-col gap-1">
                <span className={FIELD_LABEL_CLASS}>Notional USD</span>
                <input
                  value={notionalText}
                  onChange={(e) => setNotionalText(e.target.value)}
                  inputMode="decimal"
                  aria-label="Notional USD"
                  placeholder="1000000"
                  className={`${INPUT_CLASS} tabular-nums`}
                />
              </label>
              <button
                type="button"
                onClick={onSave}
                disabled={!canSave}
                className={BUTTON_PRIMARY_CLASS}
              >
                {saveMutation.isPending ? "Saving…" : "Save"}
              </button>
            </div>

            {/* ── Execution step (optional, F8.6b) ─────────────────────── */}
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse ix-fs tabular-nums lining-nums">
                <thead>
                  <tr className="bg-field">
                    <Th align="left">Asset</Th>
                    <Th align="right">Weight</Th>
                    <Th align="right">Qty @ ref</Th>
                    <Th align="left">Class</Th>
                    <Th align="right">Fill price</Th>
                    <Th align="right">Commission</Th>
                    <Th align="left">Trade date</Th>
                    <Th align="left">{/* basis badge */}</Th>
                  </tr>
                </thead>
                <tbody>
                  {rowState.map(({ row, exec, fill }) => {
                    const profile =
                      row.asset.kind === "fund"
                        ? profilesById.get(row.asset.id)
                        : undefined;
                    // Informational sizing preview at the series NAV — the
                    // backend recomputes authoritatively on save (equities'
                    // reference price is resolved server-side only).
                    const refNav = lastNav(profile);
                    const qtyAtRef =
                      notionalOk && refNav !== null && refNav > 0
                        ? (row.weight * notional) / refNav
                        : null;
                    const executed = fill !== null;
                    return (
                      <tr key={row.key} className="border-b border-border">
                        <td className="ix-cell px-2.5 first:pl-[var(--ix-pad)]">
                          <span className="font-bold text-accent">{row.ticker}</span>
                        </td>
                        <td className="ix-cell px-2.5 text-right">
                          {formatPercent(row.weight)}
                        </td>
                        <td
                          className="ix-cell px-2.5 text-right text-text-secondary"
                          title="Informational estimate at the reference NAV — the backend sizes positions authoritatively on save."
                        >
                          {qtyAtRef !== null ? formatNumber(qtyAtRef, 4) : "—"}
                        </td>
                        <td className="ix-cell px-2.5">
                          {row.asset.kind === "fund" ? (
                            <select
                              value={exec.classTicker}
                              onChange={(e) =>
                                setExecField(row.key, "classTicker", e.target.value)
                              }
                              aria-label={`Share class for ${row.ticker}`}
                              className={`${INPUT_CLASS} h-[26px] max-w-[200px]`}
                            >
                              <option value="">
                                {profile?.ticker
                                  ? `${profile.ticker} (representative)`
                                  : "Representative"}
                              </option>
                              {(profile?.classes ?? []).map((c) => (
                                <option key={c.class_id} value={c.ticker}>
                                  {c.ticker}
                                  {c.class_name ? ` — ${c.class_name}` : ""}
                                  {c.expense_ratio !== null
                                    ? ` (${formatPercent(c.expense_ratio)})`
                                    : ""}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span className="text-text-muted">—</span>
                          )}
                        </td>
                        <td className="ix-cell px-2.5 text-right">
                          <input
                            value={exec.fill}
                            onChange={(e) =>
                              setExecField(row.key, "fill", e.target.value)
                            }
                            inputMode="decimal"
                            placeholder="—"
                            aria-label={`Fill price for ${row.ticker}`}
                            className={`${INPUT_CLASS} h-[26px] w-[90px] text-right tabular-nums`}
                          />
                        </td>
                        <td className="ix-cell px-2.5 text-right">
                          <input
                            value={exec.commission}
                            onChange={(e) =>
                              setExecField(row.key, "commission", e.target.value)
                            }
                            inputMode="decimal"
                            placeholder="—"
                            aria-label={`Commission for ${row.ticker}`}
                            className={`${INPUT_CLASS} h-[26px] w-[80px] text-right tabular-nums`}
                          />
                        </td>
                        <td className="ix-cell px-2.5">
                          <input
                            type="date"
                            value={exec.tradeDate}
                            onChange={(e) =>
                              setExecField(row.key, "tradeDate", e.target.value)
                            }
                            aria-label={`Trade date for ${row.ticker}`}
                            className={`${INPUT_CLASS} h-[26px] w-[130px] tabular-nums`}
                          />
                        </td>
                        <td className="ix-cell px-2.5 pr-[var(--ix-pad)]">
                          <span
                            className={`border px-[5px] py-[1px] text-[9px] font-bold tracking-[0.06em] ${
                              executed
                                ? "border-accent text-accent"
                                : "border-border text-text-muted"
                            }`}
                            title={
                              executed
                                ? "Executed — the fill (plus commission) defines the real cost basis."
                                : "Reference — saved at the spot/NAV reference price (analysis-grade cost basis)."
                            }
                          >
                            {executed ? "EXEC" : "REF"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="ix-fs mb-0 mt-2 text-text-muted">
              Reference prices as of{" "}
              {staleness ?? "the latest available close/NAV"} — fills with
              commissions define real cost basis. Fund class NAV proxied by
              series NAV.
            </p>

            {saveMutation.isSuccess && (
              <p className="ix-fs mb-0 mt-3 flex flex-wrap items-center gap-x-3 border border-border bg-field px-3 py-2">
                <span>
                  Saved as{" "}
                  <span className="font-bold text-accent">
                    {saveMutation.data.name}
                  </span>{" "}
                  ({saveMutation.data.positions.length} positions —{" "}
                  <span className="tabular-nums">
                    {referenceCount} REF / {executedCount} EXEC
                  </span>
                  , notional{" "}
                  <span className="tabular-nums">
                    {formatNumber(saveMutation.data.notional_usd, 0)}
                  </span>
                  ).
                </span>
                <Link
                  href="/portfolio"
                  className="font-bold text-accent underline-offset-2 hover:underline"
                >
                  Open in Portfolio →
                </Link>
              </p>
            )}
            {saveMutation.isError && (
              <div className="mt-3">
                <ErrorPanel
                  title="Save failed"
                  message={saveMutation.error.message}
                  onRetry={onSave}
                />
              </div>
            )}
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse ix-fs tabular-nums lining-nums">
            <thead>
              <tr className="bg-field">
                <Th align="left">Asset</Th>
                <Th align="right">Weight</Th>
                <Th align="left">{/* bar */}</Th>
                {base && <Th align="right">Current</Th>}
                {base && <Th align="right">Δ</Th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const current = base?.weights.get(row.key) ?? 0;
                const delta = row.weight - current;
                return (
                  <tr
                    key={row.key}
                    className={`border-b border-border ${i % 2 === 1 ? "bg-zebra" : ""}`}
                  >
                    <td className="ix-cell px-2.5 first:pl-[var(--ix-pad)]">
                      <span className="font-bold text-accent">{row.ticker}</span>
                      {row.name && (
                        <span className="ml-2 inline-block max-w-[260px] truncate align-bottom text-text-secondary">
                          {row.name}
                        </span>
                      )}
                    </td>
                    <td className="ix-cell px-2.5 text-right font-bold">
                      {formatPercent(row.weight)}
                    </td>
                    <td className="ix-cell w-[180px] px-2.5">
                      <span className="relative block h-[6px] w-full border border-border bg-field">
                        <span
                          className="absolute inset-y-0 left-0 bg-accent"
                          style={{ width: `${(row.weight / maxWeight) * 100}%` }}
                        />
                      </span>
                    </td>
                    {base && (
                      <td className="ix-cell px-2.5 text-right text-text-secondary">
                        {formatPercent(current)}
                      </td>
                    )}
                    {base && (
                      <td
                        className={`ix-cell px-2.5 pr-[var(--ix-pad)] text-right font-bold ${valueTone(delta)}`}
                      >
                        {formatPercent(delta, 2, { signed: true })}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── Donuts: Current vs Proposed ─────────────────────────────────── */}
      {proposedDonut && (
        <Card title={currentDonut ? "Allocation — current vs proposed" : "Allocation — proposed"}>
          <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(260px,1fr))]">
            {currentDonut && (
              <Donut title={`Current — ${base?.name ?? ""}`} options={currentDonut} />
            )}
            <Donut title="Proposed" options={proposedDonut} />
          </div>
        </Card>
      )}

      {/* ── μ diagnostics (only when views drove a posterior) ───────────── */}
      {diagnostics.mu_equilibrium != null && diagnostics.mu_posterior != null && (
        <MuDiagnostics
          rows={rows}
          equilibrium={diagnostics.mu_equilibrium}
          posterior={diagnostics.mu_posterior}
        />
      )}
    </div>
  );
}

function csvField(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function Th({ align, children }: { align: "left" | "right"; children?: React.ReactNode }) {
  return (
    <th
      className={`whitespace-nowrap border-b border-b-border-strong px-2.5 py-[9px] ${
        align === "right" ? "text-right" : "text-left"
      } font-semibold text-text-secondary first:pl-[var(--ix-pad)] last:pr-[var(--ix-pad)]`}
    >
      {children}
    </th>
  );
}

function Donut({
  title,
  options,
}: {
  title: string;
  options: NonNullable<ReturnType<typeof buildHcAllocationOption>>;
}) {
  return (
    <div className="bg-surface-2 px-2 py-2">
      <div className="mb-1 text-center text-[10px] font-bold uppercase tracking-[0.08em] text-text-muted">
        {title}
      </div>
      <HighchartsChart options={options} className="h-[240px] w-full" />
    </div>
  );
}

function MuDiagnostics({
  rows,
  equilibrium,
  posterior,
}: {
  rows: WeightRow[];
  equilibrium: number[];
  posterior: number[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="border border-border bg-surface-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="ix-pad flex w-full items-center justify-between gap-2 text-left transition-colors hover:bg-layer-hover"
      >
        <h2 className="ix-label m-0">
          Diagnostics
          <span className="ml-2 font-normal normal-case tracking-normal text-text-secondary">
            μ equilibrium vs posterior (ann.)
          </span>
        </h2>
        <span aria-hidden className="text-[11px] text-text-muted">
          {open ? "▲" : "▼"}
        </span>
      </button>
      {open && (
        <div className="ix-pad border-t border-border pt-3">
          <table className="w-full max-w-[480px] border-collapse ix-fs tabular-nums lining-nums">
            <thead>
              <tr className="bg-field">
                <Th align="left">Asset</Th>
                <Th align="right">μ equilibrium</Th>
                <Th align="right">μ posterior</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.key} className="border-b border-border">
                  <td className="ix-cell px-2.5 font-bold text-accent first:pl-[var(--ix-pad)]">
                    {row.ticker}
                  </td>
                  <td className="ix-cell px-2.5 text-right text-text-secondary">
                    {equilibrium[i] !== undefined ? formatPercent(equilibrium[i]) : "—"}
                  </td>
                  <td className="ix-cell px-2.5 pr-[var(--ix-pad)] text-right font-bold">
                    {posterior[i] !== undefined ? formatPercent(posterior[i]) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
