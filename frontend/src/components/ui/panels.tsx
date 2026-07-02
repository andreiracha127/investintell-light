/**
 * Shared presentational primitives — Investintell Cockpit (Carbon-inspired).
 * Flat square tiles, hairline borders, uppercase tracked section labels,
 * tabular numerals on every value. Pure markup, no hooks, no data fetching.
 * Design source: /design/investintell-cockpit/InvestintellCockpit.dc.html
 */

/**
 * Canonical page container — every routed view wraps its content in this exact
 * frame so width, gutters and vertical rhythm are identical across pages.
 * Append layout extras (`flex flex-col`, `animate-pulse`) as needed.
 */
export const PAGE_CONTAINER_CLASS =
  "mx-auto w-full max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5";

/**
 * Inline "i" help dot with a styled hover/focus popover. Square-system circle,
 * hairline border, muted glyph; hover or keyboard focus reveals `tip` in a
 * token-styled popover above the dot (matching the .dc.html `.ix-pop`).
 * Accessible via aria-label + a focusable, role=tooltip popover.
 */
export function InfoDot({ tip }: { tip: string }) {
  return (
    <span
      aria-label={tip}
      tabIndex={0}
      className="group/info relative inline-flex h-[13px] w-[13px] flex-none cursor-help items-center justify-center rounded-full border border-border-strong text-[8px] font-bold leading-none text-text-muted"
    >
      i
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 hidden w-[230px] -translate-x-1/2 whitespace-normal border border-border-strong bg-surface-2 p-2 text-left text-[11.5px] font-normal normal-case leading-[1.45] tracking-normal text-text-secondary shadow-lg group-hover/info:block group-focus/info:block"
      >
        {tip}
      </span>
    </span>
  );
}

export function Card({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="ix-pad border border-border bg-surface-2">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <h2 className="ix-label m-0">
          {title}
          {subtitle && (
            <span className="ml-2 font-normal normal-case tracking-normal text-text-secondary">
              {subtitle}
            </span>
          )}
        </h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function StatRow({
  label,
  value,
  tone = "text-text-primary",
  detail,
  tip,
}: {
  label: string;
  value: string;
  tone?: string;
  detail?: string;
  tip?: string;
}) {
  return (
    <div className="ix-cell flex items-baseline justify-between gap-3 border-b border-border last:border-b-0">
      <dt className="ix-fs flex items-center gap-1.5 text-text-secondary">
        <span>{label}</span>
        {tip && <InfoDot tip={tip} />}
      </dt>
      <dd className="m-0 text-right">
        <span className={`ix-fs tabular-nums font-bold ${tone}`}>{value}</span>
        {detail && (
          <span className="block tabular-nums text-[10px] text-text-muted">{detail}</span>
        )}
      </dd>
    </div>
  );
}

/**
 * Carbon-style KPI tile — used inside a 1px-gap grid:
 *   <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
 */
export function KpiTile({
  label,
  value,
  tone = "text-text-primary",
  detail,
  detailTone = "text-text-muted",
  tip,
}: {
  label: string;
  value: string;
  tone?: string;
  detail?: string;
  detailTone?: string;
  tip?: string;
}) {
  return (
    <div className="ix-pad bg-surface-2">
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.08em] text-text-muted">
        <span>{label}</span>
        {tip && <InfoDot tip={tip} />}
      </div>
      <div className={`mt-1.5 text-[20px] font-bold tabular-nums ${tone}`}>{value}</div>
      {detail && <div className={`text-[11px] tabular-nums ${detailTone}`}>{detail}</div>}
    </div>
  );
}

/** Serif page title with the short accent rule underneath. */
export function PageTitle({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3.5">
      <div>
        <h1 className="ix-title m-0 text-[clamp(22px,3.5vw,28px)]">{title}</h1>
        <div className="mb-1.5 mt-2 h-[3px] w-[34px] bg-accent" />
        {meta && <div className="text-[12px] text-text-secondary">{meta}</div>}
      </div>
      {children}
    </div>
  );
}

/** Gain/loss/neutral text tone for a signed value. */
export function valueTone(value: number): string {
  if (value > 0) return "text-gain";
  if (value < 0) return "text-loss";
  return "text-neutral-value";
}

/**
 * Standard inline error panel — left accent rule in loss color, retry button.
 * Used by data-loading views so every failure renders identically.
 */
export function ErrorPanel({
  title,
  message,
  onRetry,
  retryLabel = "Retry",
}: {
  title: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div
      role="alert"
      className="ix-pad bg-surface-2 border border-border border-l-[3px]"
      style={{ borderLeftColor: "var(--color-loss)" }}
    >
      <h2 className="mb-1 text-sm font-semibold text-loss">{title}</h2>
      <p className="break-words whitespace-pre-wrap text-[13px] text-text-secondary">
        {message}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 h-[28px] border border-accent bg-accent px-4 text-[12px] font-bold text-on-accent transition-colors hover:bg-accent-muted"
        >
          {retryLabel}
        </button>
      )}
    </div>
  );
}
