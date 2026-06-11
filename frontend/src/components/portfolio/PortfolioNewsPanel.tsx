"use client";

/**
 * Portfolio news panel — aggregated articles across the portfolio's tickers.
 *
 * Fetches `GET /portfolios/{id}/news` independently of the overview query so a
 * slow/failed news fetch can never delay or break the positions table.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchPortfolioNews } from "@/lib/api/client";
import { NewsSection } from "@/components/stocks/NewsPanel";

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

  return <NewsSection stale={data.stale} items={data.items} />;
}
