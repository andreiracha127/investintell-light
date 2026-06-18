/**
 * Shared presentational primitives — Investintell Cockpit (Carbon-inspired).
 * Flat square tiles, hairline borders, uppercase tracked section labels,
 * tabular numerals on every value. Pure markup, no hooks, no data fetching.
 * Design source: /design/investintell-cockpit/InvestintellCockpit.dc.html
 */

/**
 * Inline "i" help dot with a native tooltip. Square-system circle, hairline
 * border, muted glyph — hover/focus reveals `tip`. Accessible via title + label.
 */
export function InfoDot({ tip }: { tip: string }) {
  return (
    <span
      title={tip}
      aria-label={tip}
      tabIndex={0}
      className="inline-flex h-[13px] w-[13px] flex-none cursor-help items-center justify-center rounded-full border border-border-strong text-[8px] font-bold leading-none text-text-muted"
    >
      i
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
      <div className={`mt-1.5 text-[19px] font-bold tabular-nums ${tone}`}>{value}</div>
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
