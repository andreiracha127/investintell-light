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
import {
  ErrorPanel,
  PAGE_CONTAINER_CLASS,
  PageTitle,
} from "@/components/ui/panels";

export function MarketOverview() {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["market-overview"],
    queryFn: ({ signal }) => fetchMarketOverview(signal),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  if (error) {
    return (
      <div className={PAGE_CONTAINER_CLASS}>
        <PageTitle title="Stocks" />
        <ErrorPanel
          title="Failed to load market overview"
          message={(error as Error).message}
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  if (isPending || !data) {
    return (
      <div aria-busy="true" className={`${PAGE_CONTAINER_CLASS} flex animate-pulse flex-col`}>
        {/* Index strip: 4 cards ~80px */}
        <div className="mb-3.5 grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-20 bg-surface-2" />
          ))}
        </div>
        {/* Leaders table ~420px */}
        <div className="mb-3.5 h-[420px] border border-border bg-surface-2" />
        {/* Sector + breadth panels */}
        <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
          <div className="h-[300px] bg-surface-2" />
          <div className="h-[300px] bg-surface-2" />
        </div>
      </div>
    );
  }

  return (
    <div className={`${PAGE_CONTAINER_CLASS} flex flex-col`}>
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
