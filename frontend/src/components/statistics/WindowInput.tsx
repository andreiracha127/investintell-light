"use client";

/**
 * Rolling/trailing window input shared by the correlation tools.
 *
 * Bounds mirror the backend contract (10..252 trading days, default 63);
 * `parseWindow` is the one place the raw text becomes a request value.
 */
import { INPUT_CLASS, LABEL_CLASS } from "@/components/statistics/ui";

export const WINDOW_MIN = 10;
export const WINDOW_MAX = 252;

/** Parse the window text into an in-bounds integer, or null when invalid. */
export function parseWindow(text: string): number | null {
  const value = Number(text.trim());
  return Number.isInteger(value) && value >= WINDOW_MIN && value <= WINDOW_MAX
    ? value
    : null;
}

export function WindowInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (text: string) => void;
}) {
  const invalid = parseWindow(value) === null;
  return (
    <label className={LABEL_CLASS}>
      Window
      <input
        type="number"
        min={WINDOW_MIN}
        max={WINDOW_MAX}
        step={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={`Rolling window in trading days (${WINDOW_MIN}-${WINDOW_MAX})`}
        aria-invalid={invalid}
        className={`w-[80px] tabular-nums ${INPUT_CLASS} ${
          invalid ? "border-[var(--color-loss)]" : ""
        }`}
      />
      <span className="text-[11px] text-text-muted">trading days</span>
    </label>
  );
}
