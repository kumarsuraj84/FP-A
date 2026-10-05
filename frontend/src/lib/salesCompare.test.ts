import { describe, expect, it } from "vitest";
import { aggregateStores, fmtGrowth, fmtInr, inCohort, planPeriods, reconciles, sameDateLastYear, sameWeekdayLastYear, totalsFor, trendFor, weekday, type CompareMode } from "./salesCompare";
import { SAMPLE_AS_OF, SAMPLE_STORES, buildSample } from "@/mocks/salesSample";

/* Rules for Sales Comparison, on invented sample data only. */

describe("reference dates", () => {
  it("same date is the same calendar date one year earlier", () => {
    expect(sameDateLastYear("2026-10-01")).toEqual({ date: "2025-10-01" });
  });
  it("29 Feb has no equivalent: 28 Feb is used and the note says so", () => {
    const r = sameDateLastYear("2028-02-29");
    expect(r.date).toBe("2027-02-28");
    expect(r.note).toMatch(/no last-year equivalent/);
  });
  it("same weekday is 364 days earlier and really is the same weekday", () => {
    expect(sameWeekdayLastYear("2026-10-01")).toBe("2025-10-02");
    expect(weekday("2026-10-01")).toBe(weekday("2025-10-02"));
  });
  it("rejects a start after the end and an empty reference period", () => {
    expect(planPeriods("same_dates", "2026-10-04", "2026-10-01").valid).toBe(false);
    expect(planPeriods("custom", "2026-10-01", "2026-10-04", { start: "2025-10-04", end: "2025-10-01" }).valid).toBe(false);
  });
  it("a custom period of a different length is flagged as not like-for-like", () => {
    const p = planPeriods("custom", "2026-10-01", "2026-10-04", { start: "2025-09-20", end: "2025-10-03" });
    expect(p.valid && p.unequal).toBe(true);
    expect(p.notes[0]).toMatch(/not like-for-like/);
  });
});

describe("store cohorts, missing data and reconciliation", () => {
  const rows = buildSample();
  const plan = planPeriods("same_weekdays", "2026-10-01", SAMPLE_AS_OF);
  const aggs = aggregateStores(SAMPLE_STORES, rows, plan);
  const by = (code: string) => aggs.find((a) => a.store.code === code)!;

  it("a store opened after the reference period started is new, not comparable", () => {
    expect(by("S22").status).toBe("new");
    expect(by("S22").ref).toBeNull();
    expect(by("S22").growth).toBeNull();
  });
  it("a store with missing days is a data gap, and the missing days are not counted as zero", () => {
    const s13 = by("S13");
    expect(s13.status).toBe("gap");
    expect(s13.curDays).toBe(plan.curDates.length - 2);
    expect(s13.reason).toMatch(/no data, not zero/);
  });
  it("a store that stopped trading is a data gap, not a store with zero sales", () => {
    expect(by("S09").status).toBe("gap");
  });
  it("the comparable cohort has complete data on both sides", () => {
    for (const a of aggs.filter((x) => inCohort(x, "comparable"))) {
      expect(a.curDays).toBe(plan.curDates.length);
      expect(a.refDays).toBe(plan.refDates.length);
    }
  });
  it.each(["same_dates", "same_weekdays"] as CompareMode[])("store differences add back to the total in every cohort (%s)", (mode) => {
    const p = planPeriods(mode, "2026-10-01", SAMPLE_AS_OF);
    const a = aggregateStores(SAMPLE_STORES, rows, p);
    for (const c of ["all", "comparable", "new"] as const) {
      const inc = a.filter((x) => inCohort(x, c));
      expect(reconciles(inc, totalsFor(inc)), `${mode}/${c}`).toBe(true);
    }
  });
  it("ratios are recomputed from summed components", () => {
    const t = totalsFor(aggs.filter((a) => inCohort(a, "comparable")));
    expect(t.curAsp).toBeCloseTo(t.cur / t.curUnits, 8);
    expect(t.refAsp).toBeCloseTo(t.ref / t.refUnits, 8);
  });
  it("a day with no rows at all is null in the trend, never zero", () => {
    const p = planPeriods("same_dates", "2026-10-05", "2026-10-05"); // after the as-of date: no rows exist
    const t = trendFor(aggregateStores(SAMPLE_STORES, rows, p), rows, p);
    expect(t[0].cur).toBeNull();
  });
});

describe("formatting is null-safe", () => {
  it("shows a dash, never NaN, null or undefined", () => {
    for (const s of [fmtInr(null), fmtInr(undefined), fmtInr(NaN), fmtGrowth(null), fmtGrowth(Infinity)]) expect(s).toBe("—");
  });
  it("uses lakh and crore", () => {
    expect(fmtInr(12_345_678)).toBe("₹1.23 Cr");
    expect(fmtInr(-250_000, { signed: true })).toBe("−₹2.50 L");
    expect(fmtInr(4_500)).toBe("₹4,500");
  });
});
