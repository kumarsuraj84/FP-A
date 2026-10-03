import { describe, expect, it } from "vitest";
import { mockApi } from "@/api/mockApi";
import { SCENARIO_ORDER, SCENARIOS } from "./scenarios";
import { AGE_FILTER_IDS, BUCKET_DEFS, BUCKET_IDS, CREDITORS_ORIGIN, cohortOf, flowContributors } from "./creditors";
import type { DrillNode, PeriodId, QueryCtx, ScenarioId } from "@/types/cfo";
import type { AgeFilter } from "@/types/creditors";

const ctx = (scenario: ScenarioId, period: PeriodId = "ytdfy27", over: Partial<QueryCtx> = {}): QueryCtx => ({ scenario, period, comparison: "budget", dataState: "live", ...over });
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
const PERIODS: PeriodId[] = ["sep26", "q2fy27", "ytdfy27"];
const near = (a: number, b: number, d = 3) => expect(a).toBeCloseTo(b, d);

describe("1. ageing buckets reconcile to creditor exposure", () => {
  it.each(SCENARIO_ORDER)("Σ buckets = total creditors = pulse creditors (%s)", async (s) => {
    for (const p of PERIODS) {
      const [ov, pulse] = await Promise.all([mockApi.getCreditors(ctx(s, p)), mockApi.getPulse(ctx(s, p))]);
      const o = ov.data!;
      near(sum(o.buckets.map((b) => b.exposure)), o.totalCreditors.value!, 4);
      expect(o.totalCreditors.value).toBe(SCENARIOS[s].creditors);
      expect(o.totalCreditors.value).toBe(pulse.data!.find((m) => m.id === "creditors")!.value.value);
      near(sum(o.buckets.map((b) => b.share)), 1, 6);
    }
  });

  it("header metrics are consistent with the buckets they cover", async () => {
    const o = (await mockApi.getCreditors(ctx("normal"))).data!;
    const val = (id: string) => o.headline.find((h) => h.id === id)!.value.value!;
    const bucket = (id: string) => o.buckets.find((b) => b.id === id)!.exposure;
    near(val("gt180"), bucket("b181_365") + bucket("b365p"), 4);
    near(val("gt90"), bucket("b91_180") + val("gt180"), 4);
    near(val("current") + val("overdue"), val("all"), 4);
    expect(val("gt180")).toBe(SCENARIOS.normal.creditors181);
    expect(o.buckets).toHaveLength(6);
    expect(o.buckets.map((b) => b.id)).toEqual(BUCKET_IDS);
  });
});

describe("2. vendor exposure reconciles with the selected ageing exposure", () => {
  it.each(SCENARIO_ORDER)("vendors + others = selected cohort exposure for every age filter (%s)", async (s) => {
    for (const f of AGE_FILTER_IDS) {
      const c = (await mockApi.getVendorConcentration(ctx(s), f as AgeFilter)).data!;
      near(sum(c.vendors.map((v) => v.cohortExposure)) + c.others.cohortExposure, c.scopeExposure, 3);
      const ov = (await mockApi.getCreditors(ctx(s))).data!;
      const expected = sum(ov.buckets.filter((b) => cohortOf(f as AgeFilter).buckets.includes(b.id)).map((b) => b.exposure));
      near(c.scopeExposure, expected, 4);
    }
  });

  it("concentration indicators are factual and ordered", async () => {
    const c = (await mockApi.getVendorConcentration(ctx("normal"), "all")).data!;
    const i = c.indicators;
    expect(i.top1Share).toBeLessThanOrEqual(i.top5Share);
    expect(i.top5Share).toBeLessThanOrEqual(i.top10Share);
    expect(i.top10Share).toBeLessThanOrEqual(1);
    expect(i.largest.outstanding / 214.8).toBeCloseTo(i.top1Share, 4);
    expect(c.vendors[0].cohortExposure).toBeGreaterThanOrEqual(c.vendors[1].cohortExposure);
    expect(c.vendors.every((v, n) => v.rank === n + 1)).toBe(true);
    expect(JSON.stringify(c)).not.toMatch(/excessive|dangerous|too concentrated/i);
  });
});

describe("3. ageing migration: opening + movements = closing", () => {
  it.each(SCENARIO_ORDER)("every bucket and the total reconcile (%s)", async (s) => {
    for (const p of PERIODS) {
      const [m, ov] = await Promise.all([mockApi.getAgeingMigration(ctx(s, p)), mockApi.getCreditors(ctx(s, p))]);
      const mig = m.data!;
      for (const b of mig.buckets) {
        near(b.opening + b.agedIn - b.agedOut + b.newIn - b.settled + b.adjusted, b.closing, 3);
        expect(b.opening).toBeGreaterThanOrEqual(-1e-9);
        expect(b.agedIn).toBeGreaterThanOrEqual(0);
        expect(b.agedOut).toBeGreaterThanOrEqual(0);
      }
      near(sum(mig.buckets.map((b) => b.closing)), mig.closing, 4);
      near(sum(mig.buckets.map((b) => b.opening)), mig.opening, 4);
      near(mig.closing, ov.data!.totalCreditors.value!, 3);
      // flows into a bucket from the previous one equal flows out of the previous bucket
      for (let i = 1; i < mig.buckets.length; i++) near(mig.buckets[i].agedIn, mig.buckets[i - 1].agedOut, 4);
      // total movement = new - settled + adjusted = pulse movement
      const settled = sum(mig.flows.filter((f) => f.movementType === "settled").map((f) => f.movedExposure));
      const adj = sum(mig.flows.filter((f) => f.movementType === "adjusted").map((f) => f.movedExposure));
      const nw = sum(mig.flows.filter((f) => f.movementType === "new").map((f) => f.movedExposure));
      near(mig.closing - mig.opening, nw - settled + adj, 3);
      const pulse = (await mockApi.getPulse(ctx(s, p))).data!.find((x) => x.id === "creditors")!;
      near(mig.closing - mig.opening, pulse.movement.value!, 3);
      // per-bucket movement on the overview = closing - opening
      ov.data!.buckets.forEach((b, i) => near(b.movement, mig.buckets[i].closing - mig.buckets[i].opening, 3));
    }
  });

  it("uses the contract shape: from, to, opening, moved, vendors, documents, type", async () => {
    const mig = (await mockApi.getAgeingMigration(ctx("normal"))).data!;
    const f = mig.flows.find((x) => x.id === "b61_90>b91_180")!;
    expect(f).toMatchObject({ fromBucket: "b61_90", toBucket: "b91_180", movementType: "aged", intoRisk: true });
    for (const fl of mig.flows) {
      expect(typeof fl.openingExposure).toBe("number");
      expect(fl.vendorCount).toBeGreaterThan(0);
      expect(fl.documentCount).toBeGreaterThan(0);
      expect(["aged", "settled", "new", "adjusted"]).toContain(fl.movementType);
    }
    expect(mig.summary.enteringRisk.flowIds).toEqual(["b61_90>b91_180"]);
  });

  it("the showcase flows are material in Normal (1.8 / 0.9 / 0.4 Cr per month)", async () => {
    const mig = (await mockApi.getAgeingMigration(ctx("normal", "sep26"))).data!;
    const get = (id: string) => mig.flows.find((x) => x.id === id)!.movedExposure;
    near(get("b61_90>b91_180"), 1.8, 2);
    near(get("b91_180>b181_365"), 0.9, 2);
    near(get("b181_365>b365p"), 0.4, 2);
    near(mig.summary.cleared.amount > 0 ? get("b181_365>settled") + get("b365p>settled") : 0, 0.6, 2);
  });

  it("each flow's vendors reconcile to the moved exposure", async () => {
    for (const s of SCENARIO_ORDER) {
      const mig = (await mockApi.getAgeingMigration(ctx(s))).data!;
      for (const fl of mig.flows) {
        const c = flowContributors(ctx(s), fl.id)!;
        near(sum(c.vendors.map((v) => v.amount)) + c.othersAmt, fl.movedExposure, 3);
      }
    }
  });

  it("the drawer view for a flow lists those vendors and reconciles", async () => {
    const mig = (await mockApi.getAgeingMigration(ctx("normal"))).data!;
    const fl = mig.flows.find((x) => x.id === "b61_90>b91_180")!;
    const node: DrillNode = { level: "driver", dim: "Migration", id: `Migration:${fl.id}`, label: "61–90 → 91–180", amount: fl.movedExposure, variance: null };
    const v = (await mockApi.getDrillView(ctx("normal"), CREDITORS_ORIGIN, [node])).data!;
    expect(v.amount).toBe(fl.movedExposure);
    const sp = v.splits[0];
    near(sum(sp.rows.map((r) => r.amount)) + (sp.other?.amount ?? 0), fl.movedExposure, 3);
    expect(sp.rows.every((r) => r.node.dim === "Vendor" && r.node.id.startsWith("Vendor:"))).toBe(true);
  });
});

describe("4. vendor open items reconcile to the vendor open balance", () => {
  it.each(SCENARIO_ORDER)("open items, lifecycle and ageing migration all reconcile (%s)", async (s) => {
    const c = (await mockApi.getVendorConcentration(ctx(s), "all")).data!;
    for (const row of c.vendors.slice(0, 8)) {
      const p = (await mockApi.getVendorProfile(ctx(s), row.vendorId)).data!;
      near(sum(p.openItems.map((i) => i.amount)), p.openBalance, 4);
      expect(p.strip.outstanding.value).toBe(p.openBalance);
      expect(p.openBalance).toBe(row.outstanding);
      const lc = Object.fromEntries(p.lifecycle.map((x) => [x.id, x.amount]));
      near(lc.opening + lc.liability - lc.adjustment - lc.payment, lc.open, 3);
      near(lc.open, p.openBalance, 4);
      near(sum(p.migration.map((m) => m.closing)), p.openBalance, 4);
      near(sum(p.migration.map((m) => m.opening)), lc.opening, 3);
      near(p.trend[p.trend.length - 1].outstanding, p.openBalance, 4);
      expect(p.trend).toHaveLength(12);
      expect(sum(p.paymentBehaviour.recent.map((x) => x.amount))).toBeLessThanOrEqual(lc.payment + 1e-6);
    }
  });

  it("vendor open items land in the bucket their age belongs to", async () => {
    const c = (await mockApi.getVendorConcentration(ctx("normal"), "all")).data!;
    const p = (await mockApi.getVendorProfile(ctx("normal"), c.vendors[0].vendorId)).data!;
    for (const it of p.openItems) {
      const def = BUCKET_DEFS.find((b) => b.id === it.bucket)!;
      expect(it.ageDays.value).toBeGreaterThanOrEqual(def.from);
      if (def.to !== null) expect(it.ageDays.value).toBeLessThanOrEqual(def.to);
    }
  });

  it("vendor totals + others = creditor book", async () => {
    for (const s of SCENARIO_ORDER) {
      const c = (await mockApi.getVendorConcentration(ctx(s), "all")).data!;
      near(sum(c.vendors.map((v) => v.outstanding)) + c.others.outstanding, SCENARIOS[s].creditors, 3);
    }
  });
});

describe("5 & 6. ledger and voucher reconcile", () => {
  it("vendor ledger closes on the displayed vendor balance; movement = credits − debits", async () => {
    for (const s of ["normal", "aged_creditors"] as ScenarioId[]) {
      const c = (await mockApi.getVendorConcentration(ctx(s), "all")).data!;
      const row = c.vendors[1];
      const prof = (await mockApi.getVendorProfile(ctx(s), row.vendorId)).data!;
      const vnode: DrillNode = { level: "entity", dim: "Vendor", id: `Vendor:${row.vendorId}`, label: row.name, amount: row.outstanding, variance: null };
      const l = (await mockApi.getLedger(ctx(s), CREDITORS_ORIGIN, [vnode])).data!;
      near(l.closingBalance / 1e7, row.outstanding, 6);
      const net = sum(l.entries.map((e) => e.credit - e.debit));
      expect(Math.abs(l.closingBalance - l.openingBalance - net)).toBeLessThan(2);
      near(l.openingBalance / 1e7, prof.lifecycle.find((x) => x.id === "opening")!.amount, 5);
      expect(l.balanceNote).toMatch(/credit-positive/i);
      // running balance is consistent row to row
      let bal = l.openingBalance;
      for (const e of l.entries) {
        bal += e.credit - e.debit;
        expect(e.balance).toBe(bal);
      }
    }
  });

  it("payment history and last payment come from the same postings as the ledger", async () => {
    const c = (await mockApi.getVendorConcentration(ctx("normal"), "all")).data!;
    const row = c.vendors[2];
    const p = (await mockApi.getVendorProfile(ctx("normal"), row.vendorId)).data!;
    const vnode: DrillNode = { level: "entity", dim: "Vendor", id: `Vendor:${row.vendorId}`, label: row.name, amount: row.outstanding, variance: null };
    const l = (await mockApi.getLedger(ctx("normal"), CREDITORS_ORIGIN, [vnode])).data!;
    const pv = l.entries.filter((e) => e.voucherType === "Payment Voucher").sort((a, b) => (a.date < b.date ? 1 : -1));
    expect(p.paymentBehaviour.recent.map((x) => x.date)).toEqual(pv.slice(0, 4).map((e) => e.date));
    p.paymentBehaviour.recent.forEach((x, i) => expect(x.amount).toBeCloseTo(pv[i].debit / 1e7, 3));
    expect(p.strip.lastPayment.date).toBe(pv[0].date);
    // lifecycle document counts equal the ledger postings they summarise
    const n = (type: string) => l.entries.filter((e) => e.voucherType === type).length;
    const lc = Object.fromEntries(p.lifecycle.map((s) => [s.id, s.documentCount]));
    expect(lc.liability).toBe(n("Purchase Invoice"));
    expect(lc.payment).toBe(n("Payment Voucher"));
    expect(lc.adjustment).toBe(n("Debit Note"));
    expect(p.paymentBehaviour.paymentsPerMonth.value!).toBeLessThan(10);
  });

  it("every voucher type debits what it credits", async () => {
    for (const id of ["PI-26-001234", "PV-26-004321", "DN-26-000077", "JV-26-000005", "SV-26-000009"]) {
      const v = (await mockApi.getVoucher(ctx("normal"), id, 1234567)).data!;
      expect(sum(v.lines.map((l) => l.debit))).toBe(sum(v.lines.map((l) => l.credit)));
      expect(v.total).toBe(1234567);
    }
  });
});

describe("7. missing / unmapped values never become zero", () => {
  it("undated documents and unmapped abnormal amounts stay null with a reason", async () => {
    const ov = (await mockApi.getCreditors(ctx("normal"))).data!;
    expect(ov.undated.value).toBeNull();
    expect(ov.undated.reason).toMatch(/Awaiting finance mapping/);
    expect(ov.scope).toBe("Dated documents");
    const ab = (await mockApi.getAbnormalBalances(ctx("normal"))).data!;
    for (const id of ["opening_balance", "no_ageing_date"]) {
      const cat = ab.categories.find((c) => c.id === id)!;
      expect(cat.amount.value).toBeNull();
      expect(cat.amount.reason).toBeTruthy();
    }
  });

  it("the drawer lists vendors for an unmapped category with unavailable amounts, not zeros", async () => {
    const node: DrillNode = { level: "driver", dim: "Abnormal", id: "Abnormal:opening_balance", label: "Opening balance anomalies", amount: null, variance: null };
    const v = (await mockApi.getDrillView(ctx("normal"), CREDITORS_ORIGIN, [node])).data!;
    expect(v.amount).toBeNull();
    expect(v.splits[0].rows.length).toBeGreaterThan(0);
    expect(v.splits[0].rows.every((r) => typeof r.unavailable === "string" && r.unavailable.length > 0)).toBe(true);
  });

  it("an unavailable data state returns no numbers at all", async () => {
    const bad = ctx("normal", "ytdfy27", { dataState: "unavailable" });
    for (const env of [await mockApi.getCreditors(bad), await mockApi.getAgeingMigration(bad), await mockApi.getAbnormalBalances(bad), await mockApi.getVendorConcentration(bad, "all")]) {
      expect(env.status).toBe("unavailable");
      expect(env.data).toBeUndefined();
    }
  });
});

describe("8. the ageing basis is explicit, never silently assumed", () => {
  it("overview, migration and vendor profile all state an unconfirmed basis", async () => {
    const ov = (await mockApi.getCreditors(ctx("normal"))).data!;
    expect(ov.ageingBasis).toMatchObject({ id: "unknown", confirmed: false, label: "Ageing basis awaiting finance validation" });
    expect(ov.ageingBasis.candidates).toEqual(["document_date", "due_date"]);
    const mig = (await mockApi.getAgeingMigration(ctx("normal"))).data!;
    expect(mig.ageingBasis.confirmed).toBe(false);
    const c = (await mockApi.getVendorConcentration(ctx("normal"), "all")).data!;
    const p = (await mockApi.getVendorProfile(ctx("normal"), c.vendors[0].vendorId)).data!;
    expect(p.ageingBasis.confirmed).toBe(false);
  });

  it("every open item carries both the document date and the due date", async () => {
    const c = (await mockApi.getVendorConcentration(ctx("normal"), "all")).data!;
    const p = (await mockApi.getVendorProfile(ctx("normal"), c.vendors[0].vendorId)).data!;
    for (const it of p.openItems) {
      expect(it.documentDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(it.dueDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(it.dueDate! > it.documentDate!).toBe(true);
    }
  });

  it("Overdue and Currently due are marked basis-dependent so the UI can flag them", async () => {
    const ov = (await mockApi.getCreditors(ctx("normal"))).data!;
    expect(ov.headline.find((h) => h.id === "overdue")!.basisDependent).toBe(true);
    expect(ov.headline.find((h) => h.id === "current")!.basisDependent).toBe(true);
    expect(ov.headline.find((h) => h.id === "gt180")!.basisDependent).toBe(false);
  });
});

describe("9. a debit creditor balance is NOT automatically a vendor advance", () => {
  it("vendor advance and creditor debit balance are separate fields from separate sources", async () => {
    const c = (await mockApi.getVendorConcentration(ctx("vendor_advance_risk"), "all")).data!;
    let sawDebit = false;
    let sawAdvance = false;
    for (const row of c.vendors) {
      const p = (await mockApi.getVendorProfile(ctx("vendor_advance_risk"), row.vendorId)).data!;
      if ((p.debitBalance.amount.value ?? 0) > 0) {
        sawDebit = true;
        expect(p.advancePosition.amount.value).not.toBe(p.debitBalance.amount.value);
        expect(p.debitBalance.note).toMatch(/not classified as a vendor advance/i);
      }
      if ((p.advancePosition.amount.value ?? 0) > 0) sawAdvance = true;
      expect(p.advancePosition.source).toMatch(/advance ledger/i);
      expect(p.strip.advance.value).toBe(p.advancePosition.amount.value);
      // the creditor balance never has the advance netted into it
      expect(p.strip.outstanding.value).toBe(row.outstanding);
    }
    expect(sawDebit).toBe(true);
    expect(sawAdvance).toBe(true);
  });

  it("the Vendor Advance scenario moves advances without changing the creditor book", async () => {
    const [n, a] = await Promise.all([mockApi.getCreditors(ctx("normal")), mockApi.getCreditors(ctx("vendor_advance_risk"))]);
    expect(a.data!.totalCreditors.value).toBe(n.data!.totalCreditors.value);
    expect(a.data!.buckets.map((b) => b.exposure)).toEqual(n.data!.buckets.map((b) => b.exposure));
    const [pn, pa] = await Promise.all([mockApi.getPulse(ctx("normal")), mockApi.getPulse(ctx("vendor_advance_risk"))]);
    const adv = (p: typeof pn) => p.data!.find((m) => m.id === "advances")!.value.value!;
    expect(adv(pa)).toBeGreaterThan(adv(pn));
  });

  it("abnormal categories are diagnostic labels only, never classified as advances", async () => {
    const ab = (await mockApi.getAbnormalBalances(ctx("vendor_advance_risk"))).data!;
    expect(ab.categories.every((c) => c.classification === "diagnostic")).toBe(true);
    const debit = ab.categories.find((c) => c.id === "debit_balance")!;
    expect(debit.label).toBe("Debit balance in creditor account");
    expect(debit.description).toMatch(/Not classified as vendor advance/i);
    expect(ab.note).toMatch(/not treated as a vendor advance/i);
    expect(ab.categories.map((c) => c.id)).toEqual(
      expect.arrayContaining(["debit_balance", "no_movement_90", "no_movement_180", "old_credit_notes", "opening_balance", "no_ageing_date", "manual_adjustments", "reversals", "unreconciled_items"]),
    );
  });
});

describe("Aged Creditors scenario changes the whole story", () => {
  it("total >180, river, migration, vendor ranking, risk and attention all move", async () => {
    const [n, a] = await Promise.all([mockApi.getCreditors(ctx("normal")), mockApi.getCreditors(ctx("aged_creditors"))]);
    expect(a.data!.totalCreditors.value!).toBeGreaterThan(n.data!.totalCreditors.value!);
    const g = (o: typeof n) => o.data!.headline.find((h) => h.id === "gt180")!.value.value!;
    expect(g(a)).toBeGreaterThan(g(n) * 2);
    expect(a.data!.buckets[5].exposure).toBeGreaterThan(n.data!.buckets[5].exposure * 2);
    const [mn, ma] = await Promise.all([mockApi.getAgeingMigration(ctx("normal")), mockApi.getAgeingMigration(ctx("aged_creditors"))]);
    expect(ma.data!.summary.enteringRisk.amount).toBeGreaterThan(mn.data!.summary.enteringRisk.amount);
    const [cn, ca] = await Promise.all([mockApi.getVendorConcentration(ctx("normal"), "gt180"), mockApi.getVendorConcentration(ctx("aged_creditors"), "gt180")]);
    expect(ca.data!.vendors.map((v) => v.vendorId).join()).not.toBe(cn.data!.vendors.map((v) => v.vendorId).join());
    expect(ca.data!.vendors.length).toBeGreaterThan(cn.data!.vendors.length);
    const risks = (await mockApi.getRisks(ctx("aged_creditors"))).data!;
    expect(risks.find((r) => r.id === "payables")!.severity).toBe("critical");
    expect((await mockApi.getActions(ctx("aged_creditors"))).data![0].id).toBe("creditors_181");
    const ab = (s: ScenarioId) => mockApi.getAbnormalBalances(ctx(s));
    const amt = (e: Awaited<ReturnType<typeof ab>>) => e.data!.categories.find((c) => c.id === "no_movement_180")!.amount.value!;
    expect(amt(await ab("aged_creditors"))).toBeGreaterThan(amt(await ab("normal")) * 3);
  });
});

describe("Command Center hand-off targets", () => {
  it("the Creditors pulse, Payables risk pillar and >180d action carry a target into the room", async () => {
    const pulse = (await mockApi.getPulse(ctx("normal"))).data!.find((m) => m.id === "creditors")!;
    expect(pulse.target).toEqual({ age: "all", lens: "age" });
    const risk = (await mockApi.getRisks(ctx("normal"))).data!.find((r) => r.id === "payables")!;
    expect(risk.target).toEqual({ age: "gt180", lens: "age" });
    const act = (await mockApi.getActions(ctx("aged_creditors"))).data!.find((a) => a.id === "creditors_181")!;
    expect(act.target).toEqual({ age: "gt180", lens: "age" });
    const other = (await mockApi.getPulse(ctx("normal"))).data!.find((m) => m.id === "advances")!;
    expect(other.target).toBeUndefined();
  });
});
