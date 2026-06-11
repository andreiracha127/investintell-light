"use client";

/**
 * Shared start/end date inputs for the Statistics tools.
 *
 * Values are ISO `YYYY-MM-DD` strings — exactly what `<input type="date">`
 * emits and what the API expects, so no parsing or conversion happens here.
 */
import { INPUT_CLASS, LABEL_CLASS } from "@/components/statistics/ui";

/** Local-time ISO date (YYYY-MM-DD) — date inputs are local by nature. */
function toIsoDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** Default window: end = today, start = one year ago. */
export function defaultDateRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 1);
  return { start: toIsoDate(start), end: toIsoDate(end) };
}

export function DateRangeInputs({
  start,
  end,
  onStartChange,
  onEndChange,
}: {
  start: string;
  end: string;
  onStartChange: (value: string) => void;
  onEndChange: (value: string) => void;
}) {
  return (
    <>
      <label className={LABEL_CLASS}>
        Start
        <input
          type="date"
          value={start}
          onChange={(e) => onStartChange(e.target.value)}
          aria-label="Start date"
          className={`tabular-nums ${INPUT_CLASS}`}
        />
      </label>
      <label className={LABEL_CLASS}>
        End
        <input
          type="date"
          value={end}
          onChange={(e) => onEndChange(e.target.value)}
          aria-label="End date"
          className={`tabular-nums ${INPUT_CLASS}`}
        />
      </label>
    </>
  );
}
