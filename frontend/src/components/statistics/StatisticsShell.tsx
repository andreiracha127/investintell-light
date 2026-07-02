/**
 * Group layout for the Statistics tools: the shared serif page title plus the
 * Carbon content switcher (Scenario | Beta | Correlation | Stock Correlation)
 * above the tool content. Pure layout — no hooks, no data fetching.
 *
 * Design source: Statistics.dc.html — the title carries a subtitle
 * ("Quantitative analysis of risk, sensitivity and correlation.") and a
 * pricing-basis badge in its trailing slot.
 */
import { PAGE_CONTAINER_CLASS, PageTitle } from "@/components/ui/panels";
import { StatisticsTabs } from "@/components/statistics/StatisticsTabs";

export function StatisticsShell({ children }: { children: React.ReactNode }) {
  return (
    <div className={PAGE_CONTAINER_CLASS}>
      <PageTitle
        title="Statistics"
        meta="Quantitative analysis of risk, sensitivity and correlation."
      >
        {/* No fabricated "as of" date here: each tool's result carries its own
            real data window. The badge only states the pricing basis. */}
        <span
          title="End-of-day prices, updated after the market closes."
          className="inline-flex cursor-help items-center border border-border bg-field px-[9px] py-1 text-[11px] text-text-muted"
        >
          End-of-day prices
        </span>
      </PageTitle>
      <StatisticsTabs />
      <div className="flex flex-col gap-px">{children}</div>
    </div>
  );
}
