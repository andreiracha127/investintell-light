/**
 * Group layout for the Statistics tools: the shared serif page title plus the
 * Carbon content switcher (Scenario | Beta | Correlation | Stock Correlation)
 * above the tool content. Pure layout — no hooks, no data fetching.
 */
import { PageTitle } from "@/components/ui/panels";
import { StatisticsTabs } from "@/components/statistics/StatisticsTabs";

export function StatisticsShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      <PageTitle title="Statistics" />
      <StatisticsTabs />
      <div className="flex flex-col gap-px">{children}</div>
    </div>
  );
}
