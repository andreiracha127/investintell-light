/**
 * Pure emptiness check for a Highcharts Grid `Options` object. Used by the
 * `DataGrid` wrapper to decide whether to show a "no matches" overlay, since
 * the grid itself renders a blank body with no message when there are no rows.
 *
 * The local data provider stores rows column-oriented as
 * `{ providerType: "local"; columns: Record<string, Array<…>> }`, so the row
 * count is the length of the first column array.
 */
import type { Options } from "@highcharts/grid-pro";

export function gridRowCount(options: Options): number {
  const data = options.data;
  const columns = data && "columns" in data ? data.columns : undefined;
  if (!columns) return 0;
  const first = Object.values(columns)[0];
  return Array.isArray(first) ? first.length : 0;
}
