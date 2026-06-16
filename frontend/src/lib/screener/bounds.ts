import { parseDecimal } from "@/lib/parse";

/** API value -> input text. Percent fractions display as 0-100. */
export function toDisplayText(value: number | null, isPercent: boolean): string {
  if (value === null) return "";
  return String(isPercent ? value * 100 : value);
}

/** Input text -> API value: "" = unbounded (null); invalid = undefined (no commit). */
export function parseBound(text: string, isPercent: boolean): number | null | undefined {
  if (text.trim() === "") return null;
  const v = parseDecimal(text);
  if (!Number.isFinite(v)) return undefined;
  return isPercent ? v / 100 : v;
}
