import { describe, expect, it } from "vitest";
import { aggregateStores, billsAbvBridge, coverageFor, dayKey, fmtGrowth, inCohort, mappingRule, planPeriods, storeDaily, totalsFor, type DayTable } from "./salesCompare";
import { SAMPLE_AS_OF, SAMPLE_STORES, buildSample } from "@/mocks/salesSample";

/* Exact rules, coverage, per-store-day averages, zero or missing reference, and the Bills → ABV worked example. Invented sample data only. */

describe("exact rules, coverage and per-store-day averages", () => {
  const rows = buildSample();

  it("states the exact same-weekday rule", () => {
    expect(mappingRule("same_weekdays")).toMatch(/D − 364 days \(52 whole weeks\)/);
    expect(mappingRule("same_dates")).toMatch(/29 Feb has no equivalent/);
  });

  it("coverage counts store-days with data on each side and never counts a missing day as zero", () => {
    const plan = planPeriods("same_weekdays", "2026-10-01", SAMPLE_AS_OF);
    const gap = aggregateStores(SAMPLE_STORES, rows, plan).filter((a) => a.store.code === "S13");
    const cov = coverageFor(gap, plan);
    expect(cov.curExpected).toBe(plan.curDates.length);
    expect(cov.curPresent).toBe(plan.curDates.length - 2);
    expect(cov.refPresent).toBe(plan.refDates.length);
  });

  it("sales per included store-day divide by the store-days that have data, not by the days planned", () => {
    const plan = planPeriods("custom", "2026-10-01", SAMPLE_AS_OF, { start: "2025-09-20", end: "2025-10-03" });
    const all = aggregateStores(SAMPLE_STORES, rows, plan).filter((a) => inCohort(a, "all"));
    const t = totalsFor(all);
    expect(plan.unequal).toBe(true);
    expect(t.curPerStoreDay).toBeCloseTo(t.cur / t.curStoreDays, 6);
    expect(t.refPerStoreDay).toBeCloseTo(t.ref / t.refStoreDays, 6);
    expect(t.curStoreDays).toBeLessThan(all.length * plan.curDates.length); // the gap and closed stores have fewer store-days than planned
  });

  it("a reference period with no data gives no growth, not infinity or 0%", () => {
    const plan = planPeriods("custom", "2026-10-01", "2026-10-04", { start: "2020-01-01", end: "2020-01-04" });
    const all = aggregateStores(SAMPLE_STORES, rows, plan);
    const t = totalsFor(all);
    expect(t.ref).toBe(0);
    expect(t.growth).toBeNull();
    expect(fmtGrowth(t.growth)).toBe("—");
    expect(coverageFor(all, plan).refPresent).toBe(0);
  });

  it("a reference that is really zero also gives no growth", () => {
    const zero: DayTable = new Map();
    const plan = planPeriods("same_dates", "2026-10-01", "2026-10-01");
    const store = { code: "Z1", name: "Z", region: "North", opened: "2020-01-01" };
    zero.set(dayKey("Z1", "2026-10-01"), { sales: 5000, units: 10 });
    zero.set(dayKey("Z1", "2025-10-01"), { sales: 0, units: 0 });
    const [a] = aggregateStores([store], zero, plan);
    expect(a.ref).toBe(0);
    expect(a.growth).toBeNull();
  });

  it("store detail shows a missing day as null, not zero", () => {
    const plan = planPeriods("same_weekdays", "2026-10-01", SAMPLE_AS_OF);
    const d = storeDaily(rows, "S13", plan);
    expect(d.filter((x) => x.cur === null).length).toBe(2);
    expect(d.every((x) => x.cur === null || x.cur.sales > 0)).toBe(true);
  });
});

describe("Bills → ABV worked example (invented figures)", () => {
  it("adds exactly to the sales difference, in the stated order", () => {
    const b = billsAbvBridge(1000, 1000, 900, 1050);
    expect(b.salesRef).toBe(1_000_000);
    expect(b.salesCur).toBe(945_000);
    expect(b.delta).toBe(-55_000);
    expect(b.billsEffect).toBe(-100_000);
    expect(b.abvEffect).toBe(45_000);
    expect(b.billsEffect + b.abvEffect).toBe(b.delta);
    expect(b.exact).toBe(true);
  });

  it("reconciles for other inputs", () => {
    for (const [b0, a0, b1, a1] of [
      [1234, 812.5, 1301, 799.25],
      [10, 3, 0, 0],
      [500, 1000, 600, 900],
    ] as const) {
      expect(billsAbvBridge(b0, a0, b1, a1).exact).toBe(true);
    }
  });
});
