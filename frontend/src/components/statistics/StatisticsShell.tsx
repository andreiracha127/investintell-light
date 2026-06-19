/**
 * Group layout for the Statistics tools: the shared serif page title plus the
 * Carbon content switcher (Scenario | Beta | Correlation | Stock Correlation)
 * above the tool content. Pure layout — no hooks, no data fetching.
 *
 * Design source: Statistics.dc.html — the title carries a subtitle
 * ("Quantitative analysis of risk, sensitivity and correlation.") and an
 * "End of day · <date>" badge in its trailing slot.
 */
import { PageTitle } from "@/components/ui/panels";
import { StatisticsTabs } from "@/components/statistics/StatisticsTabs";
import { formatDate } from "@/lib/format";

/** Today's date as a local ISO `YYYY-MM-DD` string for the EOD badge. */
function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export function StatisticsShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      <PageTitle
        title="Statistics"
        meta="Quantitative analysis of risk, sensitivity and correlation."
      >
        <span className="inline-flex items-center gap-1.5 border border-border bg-field px-[9px] py-1 text-[11px] text-text-muted">
          <span
            title="End-of-day prices, updated after the market closes."
            className="cursor-help border-b border-dotted border-current"
          >
            End of day
          </span>
          {" · "}
          {formatDate(todayIso())}
        </span>
      </PageTitle>
      <StatisticsTabs />
      <div className="flex flex-col gap-px">{children}</div>
    </div>
  );
}
