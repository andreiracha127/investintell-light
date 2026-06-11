"use client";

/**
 * News panel — a decorative secondary section on the Stock Analysis page.
 *
 * Fetches `GET /stocks/{ticker}/news` independently of the analysis query so
 * a slow/failed news fetch can never delay or break the charts.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchTickerNews, type NewsArticle } from "@/lib/api/client";
import { formatDate } from "@/lib/format";

export function NewsPanel({ ticker }: { ticker: string }) {
  const { data, error } = useQuery({
    queryKey: ["news", ticker],
    queryFn: ({ signal }) => fetchTickerNews(ticker, {}, signal),
    staleTime: 5 * 60 * 1000, // matches the backend's per-ticker staleness order of magnitude
    // Decorative panel: a failure just hides it, so retries only add latency/noise.
    retry: false,
  });

  // INTENTIONAL swallow — allowed ONLY here because this panel is decorative:
  // news must never break the page. On error or zero articles the whole
  // section is hidden (the backend already logged the failure loudly).
  if (error || !data || data.count === 0) {
    return null;
  }

  return <NewsSection stale={data.stale} items={data.items} />;
}

/**
 * Shared presentational news section — pure markup, no fetching. Also used by
 * the portfolio news panel so both surfaces render articles identically.
 */
export function NewsSection({
  stale,
  items,
}: {
  stale: boolean;
  items: NewsArticle[];
}) {
  return (
    <section className="bg-surface-2 border border-border rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-[11px] font-semibold tracking-[0.06em] uppercase text-text-muted">
          News
        </h2>
        {stale && (
          <span
            title="Live refresh failed — showing previously cached articles."
            className="px-1.5 py-px rounded-[4px] bg-surface-3 border border-border text-[10px] text-text-muted"
          >
            cached
          </span>
        )}
      </div>
      <ul className="flex flex-col">
        {items.map((item) => (
          <NewsRow key={item.id} item={item} />
        ))}
      </ul>
    </section>
  );
}

function NewsRow({ item }: { item: NewsArticle }) {
  return (
    <li className="py-2.5 border-b border-border last:border-b-0">
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-[13px] font-medium text-text-primary hover:text-accent transition-colors"
      >
        {item.title}
      </a>
      <div className="mt-0.5 text-[11px] text-text-muted">
        {item.source ? `${item.source} · ` : ""}
        {formatDate(item.published_at.slice(0, 10))}
      </div>
      {item.description && (
        <p className="mt-1 text-[12px] leading-relaxed text-text-secondary line-clamp-2">
          {item.description}
        </p>
      )}
    </li>
  );
}
