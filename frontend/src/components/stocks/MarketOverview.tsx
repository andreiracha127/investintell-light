"use client";

/** Landing /stocks: strip de índices + leaders + setores, de UM payload
 *  (GET /stocks/overview, cacheado no backend). Refetch a cada 60s. */
import { useQuery } from "@tanstack/react-query";
import { fetchMarketOverview } from "@/lib/api/client";
import { formatDate } from "@/lib/format";
import { IndexStrip } from "@/components/stocks/IndexStrip";
import { LeadersTable } from "@/components/stocks/LeadersTable";
import { SectorPanel } from "@/components/stocks/SectorPanel";
import { MarketBreadthPanel } from "@/components/stocks/MarketBreadthPanel";
import { PageTitle } from "@/components/ui/panels";

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
        <div className="mb-3.5 grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-20 bg-surface-2" />
          ))}
        </div>
        <div className="mb-3.5 h-[480px] border border-border bg-surface-2" />
        <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
          <div className="h-[320px] bg-surface-2" />
          <div className="h-[320px] bg-surface-2" />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-[1360px] flex-col px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      <PageTitle title="Stocks">
        {data.as_of && (
          <span className="inline-flex items-center gap-1.5 border border-border bg-field px-[9px] py-1 text-[11px] text-text-muted">
            <span
              title="End-of-day prices, updated after the market closes."
              className="cursor-help border-b border-dotted border-current"
            >
              End of day
            </span>
            {" · "}
            {formatDate(data.as_of)} · {data.universe_size} symbols
          </span>
        )}
      </PageTitle>
      <IndexStrip indices={data.indices} />
      <LeadersTable overview={data} />
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
        <SectorPanel sectors={data.sectors} />
        <MarketBreadthPanel breadth={data.breadth} />
      </div>
    </div>
  );
}
