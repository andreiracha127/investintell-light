import type { SeriesPoint } from "@/lib/api/client";
import { formatDate } from "@/lib/format";
import type { XAxisOptions } from "highcharts";

export const DAY_MS = 24 * 60 * 60 * 1000;

export function dateToUtcMs(date: string): number {
  const isoDay = /^(\d{4})-(\d{2})-(\d{2})/.exec(date);
  if (isoDay) {
    const [, year, month, day] = isoDay;
    return Date.UTC(Number(year), Number(month) - 1, Number(day));
  }

  const parsed = Date.parse(date);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function toDatetimeData(points: SeriesPoint[]): Array<[number, number]> {
  return points.map(([date, value]) => [dateToUtcMs(date), value]);
}

export function formatTimestampDate(value: number | string | undefined): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return formatDate(new Date(value).toISOString().slice(0, 10));
  }
  if (typeof value === "string") return formatDate(value.slice(0, 10));
  return formatDate(undefined);
}

export function compactDatetimeXAxis(overrides: XAxisOptions = {}): XAxisOptions {
  return {
    type: "datetime",
    crosshair: true,
    tickWidth: 0,
    minPadding: 0,
    maxPadding: 0.01,
    tickPixelInterval: 82,
    dateTimeLabelFormats: {
      day: { main: "%e %b" },
      week: { main: "%e %b" },
      month: { main: "%b '%y" },
      year: { main: "%Y" },
    },
    ...overrides,
    labels: {
      format: "{value:%b '%y}",
      rotation: 0,
      ...(overrides.labels ?? {}),
    },
  };
}
