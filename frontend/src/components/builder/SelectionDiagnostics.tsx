"use client";

import { useState } from "react";

import { formatNumber } from "@/lib/format";
import type { OptimizeResponse } from "@/lib/api/client";

type Selection = NonNullable<OptimizeResponse["diagnostics"]["selection"]>;

/**
 * Collapsible Stage-1 selection summary for the broad-universe optimizer: how
 * many candidates were considered, how many representatives were picked, which
 * risk cluster each represents, and which funds were excluded (with the
 * fail-loud reason). The caller guards on `diagnostics.selection != null`.
 */
export function SelectionDiagnostics({ selection }: { selection: Selection }) {
  const [open, setOpen] = useState(false);
  const clusterEntries = Object.entries(selection.clusters);
  const nClusters = new Set(Object.values(selection.clusters)).size;
  return (
    <section className="border border-border bg-surface-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="ix-pad flex w-full items-center justify-between gap-2 text-left transition-colors hover:bg-layer-hover"
      >
        <h2 className="ix-label m-0">
          Selection
          <span className="ml-2 font-normal normal-case tracking-normal text-text-secondary">
            <span className="font-bold tabular-nums">
              {formatNumber(selection.n_candidates, 0)}
            </span>{" "}
            candidates →{" "}
            <span className="font-bold tabular-nums">
              {formatNumber(selection.n_selected, 0)}
            </span>{" "}
            positions · {nClusters} risk clusters
          </span>
        </h2>
        <span aria-hidden className="text-[11px] text-text-muted">
          {open ? "▲" : "▼"}
        </span>
      </button>
      {open && (
        <div className="ix-pad flex flex-col gap-4 border-t border-border pt-3">
          <table className="w-full max-w-[480px] border-collapse ix-fs tabular-nums">
            <thead>
              <tr className="bg-field">
                <th className="px-2.5 py-[9px] text-left font-semibold text-text-secondary">
                  Position
                </th>
                <th className="px-2.5 py-[9px] text-right font-semibold text-text-secondary">
                  Risk cluster
                </th>
              </tr>
            </thead>
            <tbody>
              {clusterEntries.map(([fund, cluster]) => (
                <tr key={fund} className="border-b border-border">
                  <td className="ix-cell px-2.5 font-bold text-accent">{fund}</td>
                  <td className="ix-cell px-2.5 text-right text-text-secondary">
                    #{cluster}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {selection.excluded.length > 0 && (
            <div>
              <p className="ix-label mb-1.5">
                Excluded ({selection.excluded.length})
              </p>
              <table className="w-full border-collapse ix-fs">
                <thead>
                  <tr className="bg-field">
                    <th className="px-2.5 py-[9px] text-left font-semibold text-text-secondary">
                      Fund
                    </th>
                    <th className="px-2.5 py-[9px] text-left font-semibold text-text-secondary">
                      Reason
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {selection.excluded.map((ex) => (
                    <tr key={ex.fund} className="border-b border-border">
                      <td className="ix-cell px-2.5 font-bold text-accent">
                        {ex.fund}
                      </td>
                      <td className="ix-cell px-2.5 text-text-secondary">
                        {ex.reason}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
