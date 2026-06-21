/**
 * Custom "fan-in" entrance animation for pie/donut series — slices sweep in one
 * after another from the start angle, then data labels fade in. Ported from the
 * Highcharts "pie-custom-entrance-animation" demo.
 *
 * Registered once against the live Highcharts instance (browser-only; touches
 * the SVG renderer). Idempotent: safe to call on every chart mount.
 */
import type Highcharts from "highcharts";

let registered = false;

/* eslint-disable @typescript-eslint/no-explicit-any */
export function registerPieEntrance(H: typeof Highcharts): void {
  if (registered) return;
  const pieProto = (H as any).seriesTypes?.pie?.prototype;
  if (!pieProto) return;
  registered = true;

  pieProto.animate = function (init: boolean) {
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    const series = this;
    const points = series.points as any[];
    const duration =
      (series.options.animation && (series.options.animation as any).duration) || 1000;
    const startAngleRad = series.startAngleRad as number;

    const fan = (point: any, fromAngle: number): void => {
      const graphic = point?.graphic;
      const args = point?.shapeArgs;
      if (!graphic || !args) return;
      graphic
        .attr({ start: fromAngle, end: fromAngle, opacity: 1 })
        .animate(
          { start: args.start, end: args.end },
          { duration: duration / Math.max(points.length, 1) },
          () => {
            const next = points[point.index + 1];
            if (next) {
              fan(next, args.end);
            } else if (series.dataLabelsGroup) {
              series.dataLabelsGroup.animate({ opacity: 1 });
            }
          },
        );
    };

    if (init) {
      points.forEach((point) => point?.graphic?.attr({ opacity: 0 }));
      series.dataLabelsGroup?.attr({ opacity: 0 });
    } else if (points[0]) {
      fan(points[0], startAngleRad);
    }
  };
}
