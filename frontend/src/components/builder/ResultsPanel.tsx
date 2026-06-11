"use client";

/**
 * Builder results — KPI tiles, the proposed-weights table (inline weight
 * bars, current/delta columns when seeded from a saved portfolio), the
 * Current-vs-Proposed donuts, a collapsible μ diagnostics table, the
 * client-side CSV export, and Save-as-portfolio (POST /builder/save).
 */
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import {
  postBuilderSave,
  type BuilderObjective,
  type BuilderSaveRequest,
  type OptimizeResponse,
} from "@/lib/api/client";
import { buildAllocationOption } from "@/lib/charts/allocation";
import type { ChartColors } from "@/lib/charts/theme";
import { formatNumber, formatPercent } from "@/lib/format";
import { EChart } from "@/components/charts/EChart";
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

  /* ── Save as portfolio ─────────────────────────────────────────────── */
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState(
    () => `Builder ${objective} ${new Date().toISOString().slice(0, 10)}`,
  );
  const [notionalText, setNotionalText] = useState("1000000");
  const saveMutation = useMutation({
    mutationFn: (body: BuilderSaveRequest) => postBuilderSave(body),
  });

  const notional = Number(notionalText);
  const notionalOk = Number.isFinite(notional) && notional > 0;
  const canSave = saveName.trim().length > 0 && notionalOk && !saveMutation.isPending;

  const onSave = () => {
    if (!canSave) return;
    saveMutation.mutate({
      name: saveName.trim(),
      notional_usd: notional,
      weights: weights
        .filter((w) => w.weight > SAVE_WEIGHT_FLOOR)
        .map((w) => ({ asset: w.asset, weight: w.weight })),
    });
  };

  const rows: WeightRow[] = useMemo(
    () =>
      weights.map((w) => {
        const key = assetKey(w.asset);
        const known = assetsByKey.get(key);
        return {
          key,
          ticker: known
            ? assetTicker(known)
            : w.asset.kind === "equity"
              ? w.asset.ticker
              : w.asset.id,
          name: known ? assetName(known) : "",
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
        ? buildAllocationOption(
            rows.map((r) => ({ name: r.ticker, value: r.weight })),
            colors,
          )
        : null,
    [rows, colors],
  );
  const currentDonut = useMemo(
    () =>
      colors && base
        ? buildAllocationOption(
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
            {saveMutation.isSuccess && (
              <p className="ix-fs mb-0 mt-3 flex flex-wrap items-center gap-x-3 border border-border bg-field px-3 py-2">
                <span>
                  Saved as{" "}
                  <span className="font-bold text-accent">
                    {saveMutation.data.name}
                  </span>{" "}
                  ({saveMutation.data.positions.length} positions, notional{" "}
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
              <Donut title={`Current — ${base?.name ?? ""}`} option={currentDonut} />
            )}
            <Donut title="Proposed" option={proposedDonut} />
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
  option,
}: {
  title: string;
  option: NonNullable<ReturnType<typeof buildAllocationOption>>;
}) {
  return (
    <div className="bg-surface-2 px-2 py-2">
      <div className="mb-1 text-center text-[10px] font-bold uppercase tracking-[0.08em] text-text-muted">
        {title}
      </div>
      <EChart option={option} className="h-[240px] w-full" />
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
