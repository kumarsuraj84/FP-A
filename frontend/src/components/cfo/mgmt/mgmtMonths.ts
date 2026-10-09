/**
 * Partial-month rules shared by the expense pages and the store league.
 * A month is PARTIAL when the run's as-of date falls before the last day of that month (the data stops part-way through it).
 * Without an as-of date nothing is treated as partial.
 */
export function isPartialMonth(month: string, asOf?: string | null): boolean {
  if (!asOf || !/^\d{4}-\d{2}/.test(month) || !/^\d{4}-\d{2}-\d{2}/.test(asOf)) return false;
  const y = Number(month.slice(0, 4));
  const m = Number(month.slice(5, 7));
  const lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return asOf.slice(0, 10) < `${month.slice(0, 7)}-${String(lastDay).padStart(2, "0")}`;
}

/** The latest month that is not partial; the latest month when every month is partial or the as-of date is unknown. */
export function lastCompleteMonth(months: string[], asOf?: string | null): string {
  for (let i = months.length - 1; i >= 0; i--) if (!isPartialMonth(months[i], asOf)) return months[i];
  return months[months.length - 1] ?? "";
}
