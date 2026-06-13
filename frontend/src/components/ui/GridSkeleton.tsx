/**
 * Grid-shaped loading skeleton — a pulsing silhouette of the dense Highcharts
 * Grid Pro table (square, hairline, zebra). A header bar row over `cols` cells,
 * then `rows` body rows, all separated by 1px gaps (`bg-border` showing through
 * `gap-px`) to read as a grid. Pure presentational; matches the skeleton idiom
 * in StockAnalysisView (bars over bg-surface-2, hairline gaps, flat Carbon look).
 *
 * Decorative only: the wrapping isPending branch carries aria-busy/aria-label,
 * so the bars themselves are aria-hidden.
 */
export function GridSkeleton({
  rows = 8,
  cols = 6,
  className,
}: {
  rows?: number;
  cols?: number;
  className?: string;
}) {
  return (
    <div
      aria-hidden="true"
      className={`flex animate-pulse flex-col gap-px border border-border bg-border ${className ?? ""}`}
    >
      {/* Header row — slightly taller, denser fill. */}
      <div className="flex gap-px">
        {Array.from({ length: cols }, (_, c) => (
          <div key={c} className="h-9 flex-1 bg-field" />
        ))}
      </div>
      {/* Body rows — zebra-ish bars over bg-surface-2. */}
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex flex-1 gap-px">
          {Array.from({ length: cols }, (_, c) => (
            <div key={c} className="flex-1 bg-surface-2" />
          ))}
        </div>
      ))}
    </div>
  );
}
