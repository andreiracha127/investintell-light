import type { Distribution } from "@/lib/api/client";

/** Inline SVG mini-histogram. Bars overlapping [min,max] get the accent class. */
export function sparklineSvg(
  dist: Pick<Distribution, "bin_edges" | "counts_normalized">,
  bounds: { min: number | null; max: number | null },
  opts: { width?: number; height?: number } = {},
): string {
  const width = opts.width ?? 64;
  const height = opts.height ?? 16;
  const n = dist.counts_normalized.length;
  if (n === 0) return "";
  const gap = 1;
  const barW = (width - gap * (n - 1)) / n;
  const bars = dist.counts_normalized
    .map((norm, i) => {
      const h = Math.max(1, Math.round(norm * (height - 1)));
      const x = i * (barW + gap);
      const lo = dist.bin_edges[i];
      const hi = dist.bin_edges[i + 1];
      const inBand =
        (bounds.min === null || hi > bounds.min) && (bounds.max === null || lo < bounds.max);
      const cls = inBand ? "ix-spark-bar ix-spark-on" : "ix-spark-bar";
      return `<rect class="${cls}" x="${x.toFixed(2)}" y="${height - h}" width="${barW.toFixed(2)}" height="${h}"/>`;
    })
    .join("");
  return `<svg class="ix-spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">${bars}</svg>`;
}
