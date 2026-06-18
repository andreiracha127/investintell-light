"use client";

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
