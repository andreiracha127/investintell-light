"use client";

/**
 * Simulate card — assemble a test basket from a single unified search
 * (stocks + funds) and/or by importing a saved portfolio. The chip list is the
 * source of truth; the optimizer runs over exactly these assets.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  fetchPortfolioOverview,
  type PortfolioOverview,
} from "@/lib/api/client";
import { Card } from "@/components/ui/panels";
import { BUTTON_CLASS, ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { PortfolioSelect } from "@/components/statistics/PortfolioSelect";
import { formatCompact } from "@/lib/format";

import { AssetSearchAdd } from "./AssetSearchAdd";
import { assetKey, assetName, assetTicker, type UniverseAsset } from "./assets";

export function UniverseCard({
  assets,
  onAdd,
  onRemove,
  onSeedPortfolio,
}: {
  assets: UniverseAsset[];
  onAdd: (added: UniverseAsset[]) => void;
  onRemove: (key: string) => void;
  onSeedPortfolio: (overview: PortfolioOverview) => void;
}) {
  const [importOpen, setImportOpen] = useState(false);
  const inUniverse = new Set(assets.map(assetKey));

  return (
    <Card title="Simulate" subtitle={`${assets.length} assets`}>
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <AssetSearchAdd inUniverse={inUniverse} onAdd={(asset) => onAdd([asset])} />
        <button
          type="button"
          onClick={() => setImportOpen((v) => !v)}
          aria-expanded={importOpen}
          className={`${BUTTON_CLASS} h-[34px]`}
        >
          {importOpen ? "Hide portfolio import" : "Import a saved portfolio"}
        </button>
      </div>

      {importOpen && (
        <div className="mt-3 border-t border-border pt-3">
          <PortfolioSeed onSeedPortfolio={onSeedPortfolio} />
        </div>
      )}

      {/* ── Single asset list (chips) ───────────────────────────────────── */}
      <div className="mt-3.5 border-t border-border pt-3">
        {assets.length === 0 ? (
          <p className="ix-fs m-0 text-text-muted">
            No assets yet — search for stocks or funds above, or import a saved
            portfolio (minimum 2 to optimize).
          </p>
        ) : (
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
            {assets.map((asset) => {
              const key = assetKey(asset);
              const name = assetName(asset);
              return (
                <li
                  key={key}
                  className="flex h-[26px] items-center gap-1.5 border border-border-strong bg-field pl-1.5"
                >
                  <span
                    className={`px-1 text-[9px] font-bold uppercase tracking-[0.06em] ${
                      asset.kind === "fund"
                        ? "bg-accent-wash text-accent"
                        : "bg-layer-active text-text-secondary"
                    }`}
                  >
                    {asset.kind === "fund" ? "Fund" : "EQ"}
                  </span>
                  <span className="text-[12px] font-bold tabular-nums text-text-primary">
                    {assetTicker(asset)}
                  </span>
                  {name && (
                    <span className="max-w-[160px] truncate text-[11px] text-text-secondary">
                      {name}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => onRemove(key)}
                    aria-label={`Remove ${assetTicker(asset)}`}
                    className="flex h-full w-6 items-center justify-center text-text-muted transition-colors hover:bg-layer-hover hover:text-loss"
                  >
                    ×
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}

/* ── Import: saved portfolio ──────────────────────────────────────────────── */

function PortfolioSeed({
  onSeedPortfolio,
}: {
  onSeedPortfolio: (overview: PortfolioOverview) => void;
}) {
  const [portfolioId, setPortfolioId] = useState<number | null>(null);

  const overviewQuery = useQuery({
    queryKey: ["builder-overview", portfolioId],
    queryFn: ({ signal }) => fetchPortfolioOverview(portfolioId as number, signal),
    enabled: portfolioId !== null,
    staleTime: 30_000,
    retry: retryPolicy,
  });
  const overview = overviewQuery.data;

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-end gap-3">
        <PortfolioSelect value={portfolioId} onChange={setPortfolioId} />
        <button
          type="button"
          onClick={() => overview && onSeedPortfolio(overview)}
          disabled={!overview || overview.positions.length === 0}
          className={BUTTON_CLASS}
        >
          Add positions as assets
        </button>
      </div>
      {portfolioId !== null && overviewQuery.isPending && (
        <div
          aria-busy="true"
          aria-label="Loading portfolio overview"
          className="h-[34px] w-[260px] animate-pulse bg-field"
        />
      )}
      {overviewQuery.isError && (
        <ErrorPanel
          title="Failed to load portfolio"
          message={overviewQuery.error.message}
          onRetry={() => overviewQuery.refetch()}
        />
      )}
      {overview && (
        <p className="ix-fs m-0 tabular-nums text-text-secondary">
          {overview.name} · {overview.positions.length} positions · $
          {formatCompact(overview.aggregates.total_market_value)} — positions
          become equity refs; current weights are kept for comparison.
        </p>
      )}
    </div>
  );
}
