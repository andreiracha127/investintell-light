"use client";

/** Landing /stocks: strip de índices + leaders + setores, de UM payload
 *  (GET /stocks/overview, cacheado no backend). Refetch a cada 60s. */
import { useQuery } from "@tanstack/react-query";
import { fetchMarketOverview } from "@/lib/api/client";
import { formatDate } from "@/lib/format";
import { IndexStrip } from "@/components/stocks/IndexStrip";
import { LeadersTable } from "@/components/stocks/LeadersTable";
import { SectorPanel } from "@/components/stocks/SectorPanel";

export function MarketOverview() {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["market-overview"],
    queryFn: ({ signal }) => fetchMarketOverview(signal),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  if (error) {
    return (
      <div className="flex min-h-full items-center justify-center px-6 py-10">
        <div className="w-full max-w-[520px] border border-border border-l-[3px] border-l-[var(--color-loss)] bg-surface-2 px-8 py-6">
          <h1 className="mb-3 text-lg font-bold text-text-primary">Failed to load market overview</h1>
          <p className="text-sm text-loss break-words">{(error as Error).message}</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="mt-4 px-4 py-1.5 bg-field border border-border-strong text-sm font-semibold text-text-primary hover:bg-layer-hover transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (isPending || !data) {
    return (
      <div aria-busy="true" className="mx-auto flex max-w-[1360px] animate-pulse flex-col px-[clamp(14px,3vw,28px)] pb-10 pt-5">
        <div className="mb-px grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-[72px] bg-surface-2" />
          ))}
        </div>
        <div className="mb-px h-[480px] border border-border bg-surface-2" />
        <div className="h-[280px] border border-border bg-surface-2" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-[1360px] flex-col gap-px px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      <div className="mb-2 flex items-baseline justify-between">
        <h1 className="m-0 font-serif text-[clamp(22px,3.5vw,28px)] font-bold tracking-[-0.01em] text-text-primary">
          Stocks
        </h1>
        {data.as_of && (
          <span className="border border-border bg-field px-[7px] py-[2px] text-[10.5px] text-text-muted">
            EOD · {formatDate(data.as_of)} · {data.universe_size} symbols
          </span>
        )}
      </div>
      <IndexStrip indices={data.indices} />
      <LeadersTable overview={data} />
      <SectorPanel sectors={data.sectors} />
    </div>
  );
}
