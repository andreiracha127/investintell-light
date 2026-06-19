/**
 * Shared presentational bits for the Statistics tool pages — pure markup,
 * no hooks, no data fetching. Carbon-style fields: flat, square, hairline
 * bottom border that thickens in the accent color on focus.
 */

export const INPUT_CLASS =
  "h-[34px] px-2 bg-field border-0 border-b border-border-strong " +
  "text-[13px] font-normal normal-case tracking-normal text-text-primary " +
  "placeholder:text-text-muted outline-none " +
  "focus:border-b-2 focus:border-accent";

/** Column field wrapper: 10px uppercase label text above the control. */
export const LABEL_CLASS =
  "flex flex-col gap-[5px] text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted";

/** Reference-picker panel that wraps each tool's form controls. */
export function ParamsPanel({ children }: { children: React.ReactNode }) {
  return (
    <section className="ix-pad border border-border bg-surface-2">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">{children}</div>
    </section>
  );
}

/** Primary submit button shared by all four tool forms. */
export function RunButton({
  pending,
  disabled,
  onClick,
}: {
  pending: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || pending}
      className={`ml-auto h-[34px] bg-accent px-5 text-[12.5px] font-bold text-on-accent transition-colors hover:bg-accent-muted disabled:cursor-not-allowed disabled:opacity-40 ${
        pending ? "opacity-70" : ""
      }`}
    >
      {pending ? "Running…" : "Run"}
    </button>
  );
}

/**
 * Diverging heatmap gradient legend (−1.0 → 0 → +1.0) for a Card's `actions`
 * slot. Mirrors the diverging colorAxis the Statistics correlation matrix
 * draws: loss at −1, the chart surface at 0, accent at +1.
 */
export function HeatmapLegend() {
  return (
    <span className="flex items-center gap-2 text-[10.5px] tabular-nums text-text-muted">
      −1.0
      <span className="h-[9px] w-[120px] bg-[linear-gradient(90deg,var(--color-loss),var(--color-surface-3),var(--color-accent))]" />
      +1.0
    </span>
  );
}

/** Fail-loud error panel: renders the backend `detail` verbatim. */
export function ErrorPanel({ title, message }: { title: string; message: string }) {
  return (
    <div
      role="alert"
      className="ix-pad border-l-[3px] border-loss bg-surface-2"
    >
      <h2 className="mb-1 text-sm font-bold text-loss">{title}</h2>
      <p className="ix-fs whitespace-pre-wrap break-words text-text-secondary">
        {message}
      </p>
    </div>
  );
}
