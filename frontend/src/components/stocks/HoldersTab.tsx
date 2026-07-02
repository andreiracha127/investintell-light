"use client";

/**
 * Stocks → Holders tab. Two complementary views, toggled:
 *  - "By manager" (13F): every institutional holder with ownership %.
 *  - "By fund" (N-PORT): registered funds grouped Family → Fund (tree).
 * The frontend computes no finance — every number comes from the backend
 * payloads.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  ApiError,
  fetchStockFundHolders,
  fetchStockHolders,
} from "@/lib/api/client";
import { DataGrid } from "@/components/ui/DataGrid";
import { Card } from "@/components/ui/panels";
import { compactUsd, holdersToGridOptions } from "@/lib/grid/holdersGridOptions";
import { fundHoldersTreeGridOptions } from "@/lib/grid/fundHoldersTreeGridOptions";
import { formatDate } from "@/lib/format";

type View = "manager" | "funds";

const QUERY_OPTS = {
  staleTime: 60 * 60 * 1000, // 13F / N-PORT change quarterly
  // Keep the previous ticker's table on screen while the next loads (no flash).
  placeholderData: keepPreviousData,
  retry: (failureCount: number, err: unknown) =>
    !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
    failureCount < 2,
} as const;

export function HoldersTab({ ticker }: { ticker: string }) {
  const [view, setView] = useState<View>("manager");

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-2 px-1 pt-2 sm:px-3">
      <div className="flex items-center gap-px border-b border-border" role="tablist">
        {([
          ["manager", "By manager (13F)"],
          ["funds", "By fund (N-PORT)"],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={view === id}
            onClick={() => setView(id)}
            className={`px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors ${
              view === id
                ? "border-b-2 border-b-accent text-text-primary"
                : "border-b-2 border-b-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {view === "manager" ? (
        <ManagerView ticker={ticker} />
      ) : (
        <FundView ticker={ticker} />
      )}
    </div>
  );
}

/* ── By manager (13F) ─────────────────────────────────────────────────────── */
function ManagerView({ ticker }: { ticker: string }) {
  const [search, setSearch] = useState("");
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["stock-holders", ticker],
    queryFn: ({ signal }) => fetchStockHolders(ticker, signal),
    ...QUERY_OPTS,
  });
  const options = useMemo(
    () => (data ? holdersToGridOptions(data, { search }) : null),
    [data, search],
  );

  if (error) return <ErrorCard title="Institutional Holders" error={error} onRetry={refetch} />;
  if (isPending || !data || !options) return <GridSkeleton />;

  const empty = data.empty_state;
  return (
    <Card
      title="Institutional Holders"
      subtitle={`(${data.holder_count})`}
      actions={
        <span className="text-[12px] text-text-secondary tabular-nums">
          {data.total_market_value != null && <>Aggregate {compactUsd(data.total_market_value)} · </>}
          {data.period ? `13F ${formatDate(data.period)}` : "—"}
        </span>
      }
    >
      {empty ? (
        <p className="px-1 py-6 text-sm text-text-secondary">{empty.reason}</p>
      ) : (
        <>
          <SearchBox value={search} onChange={setSearch} placeholder="Filter holders…" />
          <DataGrid options={options} className="h-[520px] w-full" emptyMessage="No holders match your filter." />
        </>
      )}
    </Card>
  );
}

/* ── By fund (N-PORT) ─────────────────────────────────────────────────────── */
function FundView({ ticker }: { ticker: string }) {
  const [search, setSearch] = useState("");
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["stock-fund-holders", ticker],
    queryFn: ({ signal }) => fetchStockFundHolders(ticker, signal),
    ...QUERY_OPTS,
  });
  const options = useMemo(
    () => (data ? fundHoldersTreeGridOptions(data, { search }) : null),
    [data, search],
  );

  if (error) return <ErrorCard title="Fund Holders" error={error} onRetry={refetch} />;
  if (isPending || !data || !options) return <GridSkeleton />;

  const empty = data.empty_state;
  return (
    <Card
      title="Fund Holders"
      subtitle={`(${data.family_count} families · ${data.fund_count} funds)`}
      actions={
        <span className="text-[12px] text-text-secondary tabular-nums">
          {data.total_market_value != null && <>Aggregate {compactUsd(data.total_market_value)} · </>}
          {data.period ? `N-PORT ${formatDate(data.period)}` : "—"}
        </span>
      }
    >
      {empty ? (
        <p className="px-1 py-6 text-sm text-text-secondary">{empty.reason}</p>
      ) : (
        <>
          <SearchBox value={search} onChange={setSearch} placeholder="Filter families or funds…" />
          <DataGrid options={options} className="h-[520px] w-full" emptyMessage="No funds match your filter." />
        </>
      )}
    </Card>
  );
}

/* ── shared bits ──────────────────────────────────────────────────────────── */
function SearchBox({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <div className="mb-px">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full max-w-[320px] border border-border bg-field px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-strong focus:outline-none"
      />
    </div>
  );
}

function ErrorCard({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: unknown;
  onRetry: () => void;
}) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <Card title={title}>
      <div className="px-1 py-6">
        <p className="text-sm text-loss break-words">{message}</p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 px-4 py-1.5 bg-field border border-border-strong text-sm font-semibold text-text-primary hover:bg-layer-hover transition-colors"
        >
          Retry
        </button>
      </div>
    </Card>
  );
}

function GridSkeleton() {
  return <div className="h-[560px] animate-pulse border border-border bg-surface-2" />;
}
