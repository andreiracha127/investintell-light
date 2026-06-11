"use client";

/**
 * Rolling/trailing window input shared by the correlation tools.
 *
 * Bounds mirror the backend contract (10..252 trading days, default 63);
 * `parseWindow` is the one place the raw text becomes a request value.
 */
import { LABEL_CLASS } from "@/components/statistics/ui";

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
    <label className={`w-[96px] ${LABEL_CLASS}`}>
      Window
      <span
        className={`flex h-[34px] items-center border-b bg-field focus-within:border-b-2 focus-within:border-accent ${
          invalid ? "border-loss" : "border-border-strong"
        }`}
      >
        <input
          type="number"
          min={WINDOW_MIN}
          max={WINDOW_MAX}
          step={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label={`Rolling window in trading days (${WINDOW_MIN}-${WINDOW_MAX})`}
          aria-invalid={invalid}
          className="h-full w-full border-0 bg-transparent py-0 pl-2 pr-1 text-right text-[13px] font-normal normal-case tracking-normal tabular-nums text-text-primary outline-none"
        />
        <span className="px-2 text-[11px] font-normal normal-case tracking-normal text-text-muted">
          d
        </span>
      </span>
    </label>
  );
}
