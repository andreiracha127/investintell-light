"use client";

import type { ReactNode } from "react";

import { InfoDot } from "@/components/ui/panels";

export interface UsedConstraints {
  cap: number | null;
  min_weight: number | null;
}

export function TabSkeleton({ label }: { label: string }) {
  return (
    <div
      aria-busy="true"
      aria-label={label}
      className="flex animate-pulse flex-col gap-px"
    >
      <div className="h-[84px] bg-surface-2" />
      <div className="h-[320px] bg-surface-2" />
    </div>
  );
}

/**
 * Result chart block (Claude Design): a hairline-bordered card with a titled
 * header band — uppercase tracked title, an optional muted sub-label and an
 * optional `i` tooltip — over a padded body. Used by every Builder result tab
 * so charts read consistently with the rest of the cockpit.
 */
export function ChartCard({
  title,
  subtitle,
  tip,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  tip?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="border border-border bg-surface-2">
      <div className="flex items-center justify-between gap-2.5 border-b border-border px-[var(--ix-pad)] py-2.5">
        <h3 className="ix-label m-0 flex items-center gap-1.5">
          {title}
          {subtitle && (
            <span className="font-normal normal-case tracking-normal text-text-secondary">
              · {subtitle}
            </span>
          )}
          {tip && <InfoDot tip={tip} />}
        </h3>
        {actions}
      </div>
      <div className="p-2.5">{children}</div>
    </section>
  );
}
