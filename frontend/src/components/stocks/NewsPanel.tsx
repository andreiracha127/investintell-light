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
    <section className="ix-pad border border-border bg-surface-2">
      <div className="mb-2.5 flex items-center gap-2">
        <h2 className="ix-label m-0">Latest News</h2>
        {stale && (
          <span
            title="Live refresh failed — showing previously cached articles."
            className="border border-border bg-field px-1.5 py-px text-[10px] text-text-muted"
          >
            cached
          </span>
        )}
      </div>
      <ul className="m-0 flex list-none flex-col p-0">
        {items.map((item) => (
          <NewsRow key={item.id} item={item} />
        ))}
      </ul>
    </section>
  );
}

const MS_PER_MINUTE = 60_000;
const MS_PER_HOUR = 60 * MS_PER_MINUTE;
const MS_PER_DAY = 24 * MS_PER_HOUR;

/**
 * Recency label for a full ISO timestamp: relative ("2h ago", "35m ago")
 * under 24h old (when the hour actually matters), a plain date otherwise.
 * Pure — `now` is injectable for tests, defaulting to the real clock.
 */
export function formatNewsRecency(publishedAt: string, now: number = Date.now()): string {
  const publishedMs = Date.parse(publishedAt);
  if (!Number.isFinite(publishedMs)) return formatDate(publishedAt.slice(0, 10));

  const ageMs = now - publishedMs;
  if (ageMs < 0 || ageMs >= MS_PER_DAY) return formatDate(publishedAt.slice(0, 10));

  const ageMinutes = Math.floor(ageMs / MS_PER_MINUTE);
  if (ageMinutes < 1) return "just now";
  if (ageMinutes < 60) return `${ageMinutes}m ago`;
  return `${Math.floor(ageMinutes / 60)}h ago`;
}

function NewsRow({ item }: { item: NewsArticle }) {
  return (
    <li className="border-b border-border last:border-b-0">
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-baseline gap-3 py-[9px] transition-colors hover:bg-layer-hover"
      >
        {item.source && (
          <span className="flex-none border border-border bg-field px-1.5 py-[2px] text-[9.5px] font-bold uppercase tracking-[0.06em] text-text-secondary">
            {item.source}
          </span>
        )}
        <span className="min-w-0 flex-1 text-[13px] text-text-primary">
          {item.title}
        </span>
        <span className="flex-none text-[10.5px] tabular-nums text-text-muted">
          {formatNewsRecency(item.published_at)}
        </span>
      </a>
    </li>
  );
}
