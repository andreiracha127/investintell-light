/**
 * Shared presentational primitives for analysis pages — pure markup, no
 * hooks, no data fetching. Used by the stock and portfolio views.
 */

export function Card({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-surface-2 border border-border rounded-xl p-4">
      <h2 className="text-[11px] font-semibold tracking-[0.06em] uppercase text-text-muted mb-3">
        {title}
        {subtitle && (
          <>
            {" "}
            <span className="ml-1.5 normal-case tracking-normal font-normal text-text-muted">
              {subtitle}
            </span>
          </>
        )}
      </h2>
      {children}
    </section>
  );
}

export function StatRow({
  label,
  value,
  tone = "text-text-primary",
  detail,
}: {
  label: string;
  value: string;
  tone?: string;
  detail?: string;
}) {
  return (
    <div className="flex items-baseline justify-between py-2 border-b border-border last:border-b-0">
      <dt className="text-[13px] text-text-secondary">{label}</dt>
      <dd className="text-right">
        <span className={`tabular-nums text-[13px] font-semibold ${tone}`}>
          {value}
        </span>
        {detail && (
          <span className="block tabular-nums text-[11px] text-text-muted">
            {detail}
          </span>
        )}
      </dd>
    </div>
  );
}

/** Gain/loss/neutral text tone for a signed value. */
export function valueTone(value: number): string {
  if (value > 0) return "text-gain";
  if (value < 0) return "text-loss";
  return "text-neutral-value";
}
