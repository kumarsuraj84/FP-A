/**
 * SAMPLE data for the Sales Comparison prototype. Every store, number and date pattern here is invented and deterministic.
 * Nothing in this file comes from CityKart systems, and the screen says so wherever it is used.
 */
import { addDays, dateRange, dayKey, toDate, type DayRow, type DayTable, type Store } from "@/lib/salesCompare";

export const SAMPLE_AS_OF = "2026-10-04";
export const SAMPLE_FIRST_DAY = "2025-09-01";

function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const REGIONS = ["North", "South", "East", "West"];

/** 24 invented stores: 3 opened in 2026 (new), 1 stopped trading on 28 Sep 2026, 1 has a two-day data gap on 2 and 3 Oct 2026. */
export const SAMPLE_STORES: Store[] = Array.from({ length: 24 }, (_, i) => {
  const n = i + 1;
  const opened = n >= 22 ? ["2026-06-10", "2026-07-20", "2026-08-15"][n - 22] : n <= 6 ? "2022-04-01" : n <= 14 ? "2023-10-01" : "2025-02-01";
  return { code: `S${String(n).padStart(2, "0")}`, name: `Sample Store ${String(n).padStart(2, "0")}`, region: REGIONS[i % 4], opened };
});
const CLOSED = { code: "S09", after: "2026-09-28" };
const GAP = { code: "S13", days: ["2026-10-02", "2026-10-03"] };

export function buildSample(): DayTable {
  const rows: DayTable = new Map();
  const days = dateRange(SAMPLE_FIRST_DAY, SAMPLE_AS_OF);
  for (const [idx, store] of SAMPLE_STORES.entries()) {
    const r = rng(1000 + idx * 17);
    const base = 190_000 + r() * 230_000;
    const growth = -0.12 + r() * 0.27; // store trend this year versus last
    const asp = 380 + r() * 140;
    for (const d of days) {
      if (d < store.opened) continue;
      if (store.code === CLOSED.code && d > CLOSED.after) continue;
      if (store.code === GAP.code && GAP.days.includes(d)) continue;
      const dow = toDate(d).getUTCDay();
      const weekend = dow === 0 || dow === 6 ? 1.28 : dow === 5 ? 1.1 : 0.95;
      const yearFactor = d >= "2026-04-01" ? 1 + growth : 1;
      const noise = 0.85 + r() * 0.3;
      const sales = Math.round(base * weekend * yearFactor * noise);
      const units = Math.max(1, Math.round(sales / (asp * (0.96 + r() * 0.08))));
      const row: DayRow = { sales, units };
      rows.set(dayKey(store.code, d), row);
    }
  }
  return rows;
}

export const SAMPLE_LAST_YEAR_START = addDays(SAMPLE_AS_OF, -364);
