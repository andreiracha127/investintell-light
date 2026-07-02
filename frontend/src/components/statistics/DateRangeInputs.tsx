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

/**
 * Whether a start/end pair is a usable range: either side may be blank
 * (callers gate that separately), but when BOTH are filled, start must not
 * be after end. Shared by every tool's `canRun` so a backwards range is
 * caught before the request goes out instead of surfacing as a raw 422.
 */
export function isDateRangeValid(start: string, end: string): boolean {
  if (start === "" || end === "") return true;
  return start <= end;
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
  const invalid = !isDateRangeValid(start, end);
  // Inline style (not a `border-loss` class) so the override always wins over
  // INPUT_CLASS's baked-in border-border-strong regardless of Tailwind's
  // generated rule order — same pattern as ErrorPanel's borderLeftColor.
  const invalidStyle = invalid ? { borderColor: "var(--color-loss)" } : undefined;
  return (
    <>
      <label className={LABEL_CLASS}>
        Start
        <input
          type="date"
          value={start}
          onChange={(e) => onStartChange(e.target.value)}
          aria-label="Start date"
          aria-invalid={invalid || undefined}
          style={invalidStyle}
          className={`w-[140px] tabular-nums ${INPUT_CLASS}`}
        />
      </label>
      <label className={LABEL_CLASS}>
        End
        <input
          type="date"
          value={end}
          onChange={(e) => onEndChange(e.target.value)}
          aria-label="End date"
          aria-invalid={invalid || undefined}
          style={invalidStyle}
          className={`w-[140px] tabular-nums ${INPUT_CLASS}`}
        />
      </label>
      {invalid && (
        <span className="ix-fs self-end pb-[7px] text-loss">
          Start must be on or before end.
        </span>
      )}
    </>
  );
}
