/**
 * Sales Comparison: pure rules, no I/O. Used by the Operations prototype on SAMPLE data and written so the same rules can later sit over the real store-day source.
 *
 * Rules fixed by the Phase 0 review (docs/sales/PHASE0_DATA_UNDERSTANDING.md):
 *  - same dates, same weekdays and custom periods are separate modes; the reference dates are always returned so the screen can show them;
 *  - a store-day with no row is "no data", never zero;
 *  - a comparable store is open before the reference period starts and has data on every day of BOTH periods;
 *  - ratios are recomputed from summed components, never averaged;
 *  - the sum of the store differences equals the total difference (checked by `reconciles`).
 */
export type CompareMode = "same_dates" | "same_weekdays" | "custom";
export type CohortFilter = "all" | "comparable" | "new";
export type StoreStatus = "comparable" | "new" | "gap";

export const DASH = "—";
const DAY_MS = 86_400_000;

export const toDate = (iso: string) => new Date(`${iso}T00:00:00Z`);
export const toIso = (d: Date) => d.toISOString().slice(0, 10);
export const addDays = (iso: string, n: number) => toIso(new Date(toDate(iso).getTime() + n * DAY_MS));

export function dateRange(start: string, end: string): string[] {
  const out: string[] = [];
  if (!start || !end || start > end) return out;
  for (let d = start; d <= end; d = addDays(d, 1)) out.push(d);
  return out;
}

/** Same calendar date one year earlier. 29 Feb has no equivalent: 28 Feb is used and the note says so. */
export function sameDateLastYear(iso: string): { date: string; note?: string } {
  const d = toDate(iso);
  const y = d.getUTCFullYear() - 1;
  const m = d.getUTCMonth();
  const day = d.getUTCDate();
  const candidate = new Date(Date.UTC(y, m, day));
  if (candidate.getUTCMonth() !== m) return { date: toIso(new Date(Date.UTC(y, m, day - 1))), note: `${iso} (29 Feb) has no last-year equivalent; 28 Feb used` };
  return { date: toIso(candidate) };
}

/** Same weekday: 364 days earlier (52 whole weeks). */
export const sameWeekdayLastYear = (iso: string) => addDays(iso, -364);

export interface PeriodPlan {
  curDates: string[];
  refDates: string[];
  /** current date and its reference date, only where both sides exist (equal-length plans) */
  pairs: { cur: string; ref: string }[];
  notes: string[];
  unequal: boolean;
  valid: boolean;
  problem?: string;
}

export function planPeriods(mode: CompareMode, start: string, end: string, custom?: { start: string; end: string }): PeriodPlan {
  const curDates = dateRange(start, end);
  if (!curDates.length) return { curDates, refDates: [], pairs: [], notes: [], unequal: false, valid: false, problem: "Choose a start date on or before the end date." };
  if (mode === "custom") {
    const refDates = custom ? dateRange(custom.start, custom.end) : [];
    if (!refDates.length) return { curDates, refDates, pairs: [], notes: [], unequal: false, valid: false, problem: "Choose a reference period (start on or before end)." };
    const n = Math.min(curDates.length, refDates.length);
    const unequal = curDates.length !== refDates.length;
    return {
      curDates,
      refDates,
      pairs: Array.from({ length: n }, (_, i) => ({ cur: curDates[i], ref: refDates[i] })),
      notes: unequal ? [`The periods have ${curDates.length} and ${refDates.length} days. Totals are not like-for-like; sales per store-day with data is shown beside them.`] : [],
      unequal,
      valid: true,
    };
  }
  const notes: string[] = [];
  const pairs = curDates.map((cur) => {
    if (mode === "same_weekdays") return { cur, ref: sameWeekdayLastYear(cur) };
    const r = sameDateLastYear(cur);
    if (r.note) notes.push(r.note);
    return { cur, ref: r.date };
  });
  return { curDates, refDates: pairs.map((p) => p.ref), pairs, notes, unequal: false, valid: true };
}

export interface Store {
  code: string;
  name: string;
  region: string;
  opened: string;
}
export interface DayRow {
  sales: number;
  units: number;
}
/** key = `${store code}|${date}`; a missing key is "no data" */
export type DayTable = Map<string, DayRow>;
export const dayKey = (code: string, date: string) => `${code}|${date}`;

export interface StoreAgg {
  store: Store;
  status: StoreStatus;
  reason: string;
  cur: number | null;
  ref: number | null;
  curUnits: number | null;
  refUnits: number | null;
  curDays: number;
  refDays: number;
  delta: number;
  growth: number | null;
}

function sumDays(rows: DayTable, code: string, dates: string[]) {
  let sales = 0;
  let units = 0;
  let days = 0;
  for (const d of dates) {
    const r = rows.get(dayKey(code, d));
    if (!r) continue;
    sales += r.sales;
    units += r.units;
    days += 1;
  }
  return { sales: days ? sales : null, units: days ? units : null, days };
}

export function aggregateStores(stores: Store[], rows: DayTable, plan: PeriodPlan): StoreAgg[] {
  const refStart = plan.refDates.length ? [...plan.refDates].sort()[0] : "";
  return stores
    .map((store): StoreAgg => {
      const c = sumDays(rows, store.code, plan.curDates);
      const r = sumDays(rows, store.code, plan.refDates);
      let status: StoreStatus = "comparable";
      let reason = "Open before the reference period and data on every day of both periods";
      if (refStart && store.opened > refStart) {
        status = "new";
        reason = `Opened ${store.opened}, after the reference period started`;
      } else if (c.days < plan.curDates.length || r.days < plan.refDates.length) {
        status = "gap";
        const missCur = plan.curDates.length - c.days;
        const missRef = plan.refDates.length - r.days;
        reason = `No data on ${missCur} current and ${missRef} reference day${missCur + missRef === 1 ? "" : "s"} (no data, not zero)`;
      }
      const delta = (c.sales ?? 0) - (r.sales ?? 0);
      const growth = status !== "new" && c.sales != null && r.sales ? delta / r.sales : null;
      return { store, status, reason, cur: c.sales, ref: r.sales, curUnits: c.units, refUnits: r.units, curDays: c.days, refDays: r.days, delta, growth };
    })
    .filter((a) => a.curDays > 0 || a.refDays > 0);
}

export function inCohort(a: StoreAgg, cohort: CohortFilter) {
  return cohort === "all" ? true : cohort === "comparable" ? a.status === "comparable" : a.status === "new";
}

export interface Totals {
  cur: number;
  ref: number;
  curUnits: number;
  refUnits: number;
  delta: number;
  growth: number | null;
  curAsp: number | null;
  refAsp: number | null;
  stores: number;
  /** store-days that actually have a row; the denominator for sales per included trading day (missing days are never counted as zero) */
  curStoreDays: number;
  refStoreDays: number;
  curPerStoreDay: number | null;
  refPerStoreDay: number | null;
}
const ratio = (a: number, b: number) => (b > 0 ? a / b : null);

export function totalsFor(aggs: StoreAgg[]): Totals {
  const t = aggs.reduce(
    (s, a) => ({ cur: s.cur + (a.cur ?? 0), ref: s.ref + (a.ref ?? 0), curUnits: s.curUnits + (a.curUnits ?? 0), refUnits: s.refUnits + (a.refUnits ?? 0) }),
    { cur: 0, ref: 0, curUnits: 0, refUnits: 0 },
  );
  const delta = t.cur - t.ref;
  const curStoreDays = aggs.reduce((n, a) => n + a.curDays, 0);
  const refStoreDays = aggs.reduce((n, a) => n + a.refDays, 0);
  return {
    ...t,
    delta,
    growth: ratio(delta, t.ref),
    curAsp: ratio(t.cur, t.curUnits),
    refAsp: ratio(t.ref, t.refUnits),
    stores: aggs.length,
    curStoreDays,
    refStoreDays,
    curPerStoreDay: ratio(t.cur, curStoreDays),
    refPerStoreDay: ratio(t.ref, refStoreDays),
  };
}

/** The contributions must add back to the total difference; the screen shows a failure instead of a number if they do not. */
export function reconciles(aggs: StoreAgg[], totals: Totals): boolean {
  const sum = aggs.reduce((s, a) => s + a.delta, 0);
  return Math.abs(sum - totals.delta) < 0.005;
}

export interface TrendPoint {
  index: number;
  curDate: string | null;
  refDate: string | null;
  cur: number | null;
  ref: number | null;
}

export function trendFor(aggs: StoreAgg[], rows: DayTable, plan: PeriodPlan): TrendPoint[] {
  const n = Math.max(plan.curDates.length, plan.refDates.length);
  const dayTotal = (date: string | undefined) => {
    if (!date) return null;
    let s = 0;
    let any = false;
    for (const a of aggs) {
      const r = rows.get(dayKey(a.store.code, date));
      if (r) {
        s += r.sales;
        any = true;
      }
    }
    return any ? s : null;
  };
  return Array.from({ length: n }, (_, i) => ({
    index: i + 1,
    curDate: plan.curDates[i] ?? null,
    refDate: plan.refDates[i] ?? null,
    cur: dayTotal(plan.curDates[i]),
    ref: dayTotal(plan.refDates[i]),
  }));
}

/* ───────────── formatting: null-safe, Indian lakh / crore ───────────── */

export function fmtInr(v: number | null | undefined, opts: { signed?: boolean } = {}): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const sign = v < 0 ? "−" : opts.signed && v > 0 ? "+" : "";
  const a = Math.abs(v);
  const body = a >= 1e7 ? `₹${(a / 1e7).toFixed(2)} Cr` : a >= 1e5 ? `₹${(a / 1e5).toFixed(2)} L` : `₹${Math.round(a).toLocaleString("en-IN")}`;
  return `${sign}${body}`;
}
export function fmtNum(v: number | null | undefined, opts: { signed?: boolean } = {}): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const sign = v < 0 ? "−" : opts.signed && v > 0 ? "+" : "";
  return `${sign}${Math.round(Math.abs(v)).toLocaleString("en-IN")}`;
}
export function fmtGrowth(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return `${v < 0 ? "−" : v > 0 ? "+" : ""}${Math.abs(v * 100).toFixed(1)}%`;
}
export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return DASH;
  return toDate(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
}
export function fmtRange(dates: string[]): string {
  if (!dates.length) return DASH;
  const s = [...dates].sort();
  return s.length === 1 ? fmtDay(s[0]) : `${fmtDay(s[0])} to ${fmtDay(s[s.length - 1])}`;
}
export const weekday = (iso: string) => toDate(iso).toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });

/* ───────────── rules shown on screen, coverage, detail rows, worked example ───────────── */

export function mappingRule(mode: CompareMode): string {
  if (mode === "same_weekdays") return "Same weekday: each current date D is compared with D − 364 days (52 whole weeks), so the weekday is identical. There is no adjustment for festivals or holidays.";
  if (mode === "same_dates") return "Same date: each current date D is compared with the same day and month one year earlier. 29 Feb has no equivalent, so 28 Feb is used and a note is shown. The weekday can differ.";
  return "Custom period: you choose both periods. Days are paired in order. If the lengths differ, totals are not like-for-like and sales per store-day with data is shown beside them.";
}

export interface Coverage {
  stores: number;
  curExpected: number;
  curPresent: number;
  refExpected: number;
  refPresent: number;
}
/** How many store-days the selection expects on each side and how many have a row. A missing store-day is "no data". */
export function coverageFor(aggs: StoreAgg[], plan: PeriodPlan): Coverage {
  return {
    stores: aggs.length,
    curExpected: aggs.length * plan.curDates.length,
    curPresent: aggs.reduce((n, a) => n + a.curDays, 0),
    refExpected: aggs.length * plan.refDates.length,
    refPresent: aggs.reduce((n, a) => n + a.refDays, 0),
  };
}

export interface DetailDay {
  index: number;
  curDate: string | null;
  refDate: string | null;
  cur: DayRow | null;
  ref: DayRow | null;
}
/** One store, day by day. A side with no row is null (shown as a dash), never zero. */
export function storeDaily(rows: DayTable, code: string, plan: PeriodPlan): DetailDay[] {
  const n = Math.max(plan.curDates.length, plan.refDates.length);
  return Array.from({ length: n }, (_, i) => {
    const curDate = plan.curDates[i] ?? null;
    const refDate = plan.refDates[i] ?? null;
    return { index: i + 1, curDate, refDate, cur: curDate ? rows.get(dayKey(code, curDate)) ?? null : null, ref: refDate ? rows.get(dayKey(code, refDate)) ?? null : null };
  });
}

export interface BillsAbvBridge {
  salesRef: number;
  salesCur: number;
  delta: number;
  billsEffect: number;
  abvEffect: number;
  exact: boolean;
}
/**
 * Bills → ABV bridge, in this fixed order: the bills effect is valued at the reference ABV, then the ABV effect at the current bills.
 *   bills effect = (bills_cur − bills_ref) × abv_ref
 *   ABV effect   = (abv_cur − abv_ref) × bills_cur
 * The two add exactly to (bills_cur × abv_cur) − (bills_ref × abv_ref). `exact` is false if floating-point error exceeds half a paisa.
 */
export function billsAbvBridge(billsRef: number, abvRef: number, billsCur: number, abvCur: number): BillsAbvBridge {
  const salesRef = billsRef * abvRef;
  const salesCur = billsCur * abvCur;
  const billsEffect = (billsCur - billsRef) * abvRef;
  const abvEffect = (abvCur - abvRef) * billsCur;
  const delta = salesCur - salesRef;
  return { salesRef, salesCur, delta, billsEffect, abvEffect, exact: Math.abs(billsEffect + abvEffect - delta) < 0.005 };
}
