"use client";

/**
 * Universe card — assembles the builder's asset list from three seeds
 * (saved portfolio positions, fund search, ad-hoc equity tickers). Seeds
 * can be mixed freely; the single chip list below is the source of truth.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  fetchFunds,
  fetchPortfolioOverview,
  type FundListItem,
  type PortfolioOverview,
} from "@/lib/api/client";
import { Card } from "@/components/ui/panels";
import {
  BUTTON_CLASS,
  ErrorPanel,
  FIELD_LABEL_CLASS,
  INPUT_CLASS,
  retryPolicy,
} from "@/components/screener/shared";
import { PortfolioSelect } from "@/components/statistics/PortfolioSelect";
import { formatCompact } from "@/lib/format";

import { assetKey, assetName, assetTicker, type UniverseAsset } from "./assets";

type SeedMode = "portfolio" | "funds" | "adhoc";

const SEED_MODES: { value: SeedMode; label: string }[] = [
  { value: "portfolio", label: "Saved portfolio" },
  { value: "funds", label: "Funds" },
  { value: "adhoc", label: "Ad-hoc" },
];

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
  const [mode, setMode] = useState<SeedMode>("portfolio");

  return (
    <Card title="Universe" subtitle={`${assets.length} assets`}>
      <div className="mb-3 flex items-stretch border border-border-strong w-fit">
        {SEED_MODES.map((m) => (
          <button
            key={m.value}
            type="button"
            onClick={() => setMode(m.value)}
            aria-pressed={mode === m.value}
            className={`h-[30px] px-3.5 text-[11.5px] transition-colors ${
              mode === m.value
                ? "bg-accent font-bold text-on-accent"
                : "bg-field font-medium text-text-secondary hover:bg-layer-hover"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {mode === "portfolio" && <PortfolioSeed onSeedPortfolio={onSeedPortfolio} />}
      {mode === "funds" && <FundSeed assets={assets} onAdd={onAdd} />}
      {mode === "adhoc" && <AdhocSeed onAdd={onAdd} />}

      {/* ── Single asset list (chips) ───────────────────────────────────── */}
      <div className="mt-3.5 border-t border-border pt-3">
        {assets.length === 0 ? (
          <p className="ix-fs m-0 text-text-muted">
            No assets yet — seed from a saved portfolio, the fund universe or
            ad-hoc tickers (minimum 2 to optimize).
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

/* ── Seed: saved portfolio ────────────────────────────────────────────────── */

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

/* ── Seed: fund search ────────────────────────────────────────────────────── */

function FundSeed({
  assets,
  onAdd,
}: {
  assets: UniverseAsset[];
  onAdd: (added: UniverseAsset[]) => void;
}) {
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchText.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchText]);

  const fundsQuery = useQuery({
    queryKey: ["builder-funds", search],
    queryFn: ({ signal }) =>
      fetchFunds({ search, page: 1, page_size: 8, sort: "aum_usd", dir: "desc" }, signal),
    enabled: search !== "",
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: retryPolicy,
  });

  const inUniverse = new Set(assets.map(assetKey));
  const addFund = (fund: FundListItem) => {
    onAdd([
      { kind: "fund", id: fund.instrument_id, ticker: fund.ticker, name: fund.name },
    ]);
  };

  return (
    <div className="flex flex-col gap-2">
      <label className="flex max-w-[340px] flex-col gap-1">
        <span className={FIELD_LABEL_CLASS}>Search funds</span>
        <input
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Ticker / name…"
          aria-label="Search funds by ticker or name"
          className={INPUT_CLASS}
        />
      </label>
      {search !== "" && fundsQuery.isPending && (
        <div
          aria-busy="true"
          aria-label="Searching funds"
          className="h-[120px] animate-pulse bg-field"
        />
      )}
      {fundsQuery.isError && (
        <ErrorPanel
          title="Fund search failed"
          message={fundsQuery.error.message}
          onRetry={() => fundsQuery.refetch()}
        />
      )}
      {search !== "" && fundsQuery.data && (
        <ul
          className={`m-0 list-none border border-border p-0 transition-opacity ${
            fundsQuery.isFetching ? "opacity-60" : ""
          }`}
        >
          {fundsQuery.data.items.length === 0 && (
            <li className="px-2.5 py-2 text-[12px] text-text-muted">
              No funds match &ldquo;{search}&rdquo;.
            </li>
          )}
          {fundsQuery.data.items.map((fund) => {
            const added = inUniverse.has(`fund:${fund.instrument_id}`);
            return (
              <li key={fund.instrument_id} className="border-b border-border last:border-b-0">
                <button
                  type="button"
                  onClick={() => addFund(fund)}
                  disabled={added}
                  className="flex w-full items-baseline gap-2 px-2.5 py-[7px] text-left transition-colors hover:bg-accent-wash disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <span className="w-[56px] shrink-0 text-[12px] font-bold tabular-nums text-accent">
                    {fund.ticker ?? "—"}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[12px] text-text-primary">
                    {fund.name}
                  </span>
                  <span className="shrink-0 text-[11px] tabular-nums text-text-secondary">
                    {fund.aum_usd !== null ? `$${formatCompact(fund.aum_usd)}` : "—"}
                  </span>
                  <span className="shrink-0 text-[11px] text-text-muted">
                    {added ? "Added" : "+ Add"}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ── Seed: ad-hoc tickers ─────────────────────────────────────────────────── */

function AdhocSeed({ onAdd }: { onAdd: (added: UniverseAsset[]) => void }) {
  const [text, setText] = useState("");

  const parse = (): UniverseAsset[] =>
    text
      .split(",")
      .map((t) => t.trim().toUpperCase())
      .filter((t) => t !== "")
      .map((ticker) => ({ kind: "equity" as const, ticker }));

  const add = () => {
    const parsed = parse();
    if (parsed.length === 0) return;
    onAdd(parsed);
    setText("");
  };

  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex w-[340px] max-w-full flex-col gap-1">
        <span className={FIELD_LABEL_CLASS}>Equity tickers (comma-separated)</span>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") add();
          }}
          placeholder="AAPL, MSFT, GLD…"
          aria-label="Ad-hoc equity tickers, comma separated"
          className={`${INPUT_CLASS} uppercase`}
        />
      </label>
      <button
        type="button"
        onClick={add}
        disabled={parse().length === 0}
        className={BUTTON_CLASS}
      >
        Add tickers
      </button>
    </div>
  );
}
