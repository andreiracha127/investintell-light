"use client";

/**
 * Portfolio news panel — aggregated articles across the portfolio's tickers.
 *
 * Fetches `GET /portfolios/{id}/news` independently of the overview query so a
 * slow/failed news fetch can never delay or break the positions table.
 *
 * Cockpit news list: square uppercase source tag, hairline row dividers,
 * layer-hover rows — pure presentation, identical data flow.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchPortfolioNews } from "@/lib/api/client";
import { formatDate } from "@/lib/format";

export function PortfolioNewsPanel({ portfolioId }: { portfolioId: number }) {
  const { data, error } = useQuery({
    queryKey: ["portfolio-news", portfolioId],
    queryFn: ({ signal }) => fetchPortfolioNews(portfolioId, {}, signal),
    staleTime: 5 * 60 * 1000, // matches the backend's per-ticker staleness order of magnitude
    // Decorative panel: a failure just hides it, so retries only add latency/noise.
    retry: false,
  });

  // INTENTIONAL swallow — allowed ONLY here because this panel is decorative:
  // news must never break the page (the current Tiingo plan even 403s the news
  // endpoint). On error or zero articles the whole section is hidden (the
  // backend already logged the failure loudly).
  if (error || !data || data.count === 0) {
    return null;
  }

  return (
    <section className="ix-pad border border-border bg-surface-2">
      <div className="mb-2.5 flex items-center gap-2">
        <h2 className="ix-label m-0">
          News
          <span className="ml-2 font-normal normal-case tracking-normal text-text-secondary">
            · aggregated across portfolio holdings
          </span>
        </h2>
        {data.stale && (
          <span
            title="Live refresh failed — showing previously cached articles."
            className="border border-border bg-field px-1.5 py-px text-[10px] text-text-muted"
          >
            cached
          </span>
        )}
      </div>
      <div className="flex flex-col">
        {data.items.map((item) => (
          <a
            key={item.id}
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-baseline gap-3 border-b border-border py-[9px] last:border-b-0 hover:bg-layer-hover"
          >
            <span className="shrink-0 border border-border bg-field px-1.5 py-[2px] text-[9.5px] font-bold uppercase tracking-[0.06em] text-text-secondary">
              {item.source ?? "news"}
            </span>
            <span className="ix-fs min-w-0 flex-1 text-text-primary">
              {item.title}
            </span>
            <span className="shrink-0 text-[10.5px] tabular-nums text-text-muted">
              {formatDate(item.published_at.slice(0, 10))}
            </span>
          </a>
        ))}
      </div>
    </section>
  );
}
