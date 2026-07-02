"use client";

/**
 * Carbon-style content switcher shared by the four Statistics tools.
 * Items are plain links; the active one derives from the pathname.
 * Design source: /design/investintell-cockpit/InvestintellCockpit.dc.html
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

const TOOLS = [
  { href: "/statistics/scenario", label: "Scenario" },
  { href: "/statistics/beta", label: "Beta" },
  { href: "/statistics/correlation", label: "Correlation" },
  { href: "/statistics/stock-correlation", label: "Stock Correlation" },
  { href: "/statistics/correlation-regime", label: "Correlation Regime" },
] as const;

export function StatisticsTabs() {
  const pathname = usePathname();

  return (
    <nav aria-label="Statistics tools" className="mb-px flex">
      {TOOLS.map((tool, index) => {
        const active = pathname === tool.href;
        return (
          <Link
            key={tool.href}
            href={tool.href}
            aria-current={active ? "page" : undefined}
            className={`flex h-[40px] flex-1 items-center justify-center whitespace-nowrap border border-border-strong px-3.5 text-[12.5px] no-underline transition-colors ${
              index > 0 ? "border-l-0" : ""
            } ${
              active
                ? "bg-accent font-bold text-on-accent"
                : "bg-field font-medium text-text-secondary hover:bg-layer-hover"
            }`}
          >
            {tool.label}
          </Link>
        );
      })}
    </nav>
  );
}
