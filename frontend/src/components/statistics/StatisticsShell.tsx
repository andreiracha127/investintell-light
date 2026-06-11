"use client";

/**
 * Group layout for the Statistics tools: a horizontal sub-nav
 * (Scenario | Beta | Correlation | Stock Correlation) above the tool content.
 * Active state derives from the pathname.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

const TOOLS = [
  { href: "/statistics/scenario", label: "Scenario" },
  { href: "/statistics/beta", label: "Beta" },
  { href: "/statistics/correlation", label: "Correlation" },
  { href: "/statistics/stock-correlation", label: "Stock Correlation" },
] as const;

export function StatisticsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="px-6 py-5 max-w-[1400px] mx-auto flex flex-col gap-5">
      <nav
        aria-label="Statistics tools"
        className="flex flex-wrap items-center gap-1 border-b border-border pb-3"
      >
        {TOOLS.map((tool) => {
          const active = pathname === tool.href;
          return (
            <Link
              key={tool.href}
              href={tool.href}
              aria-current={active ? "page" : undefined}
              className={`px-3 py-1.5 rounded-[6px] text-[13px] font-medium no-underline transition-colors ${
                active
                  ? "bg-surface-3 text-accent"
                  : "text-text-secondary hover:bg-surface-2 hover:text-text-primary"
              }`}
            >
              {tool.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
