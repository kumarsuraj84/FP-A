import { describe, expect, it } from "vitest";
import type { ComparisonId, DrillNode, PeriodId, QueryCtx, ScenarioId } from "@/types/cfo";
import { QUADRANT_ORDER } from "@/types/profitability";
import { profitBridge } from "./builders";
import { buildCashRoom } from "./cash";
import { buildDrill, buildLedger } from "./drill";
import { STORE_IDS, buildProfitDrill, buildProfitLedger, buildProfitPortfolio, buildStoreWorkspace } from "./profitability";
import { SCENARIO_ORDER } from "./scenarios";
import { PROFIT_ORIGIN, movementNode, storeNode } from "@/lib/profitNodes";
import { CASH_ORIGIN, cashNode } from "@/lib/cashNodes";

const ctxOf = (scenario: ScenarioId = "normal", period: PeriodId = "ytdfy27", comparison: ComparisonId = "budget"): QueryCtx => ({ scenario, period, comparison, dataState: "live" });
const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
const PERIODS: PeriodId[] = ["sep26", "q2fy27", "ytdfy27"];
const COMPARES: ComparisonId[] = ["budget", "ly", "forecast"];
const near = (a: number, b: number, tol = 5e-4) => expect(Math.abs(a - b)).toBeLessThanOrEqual(tol);

describe("Store Profitability reconciles to the Command Center", () => {
  it("store contribution variances add up to the Command Center operating-profit bridge, in every scenario, period and comparison", () => {
    for (const s of SCENARIO_ORDER)
      for (const p of PERIODS)
        for (const c of COMPARES) {
          const ctx = ctxOf(s, p, c);
          const pf = buildProfitPortfolio(ctx);
          const cc = profitBridge(ctx).items.filter((i) => i.kind === "delta");
          near(pf.company.contributionVsComparison, sum(cc.map((i) => i.value)), 0.02);
          near(sum(pf.stores.map((x) => x.contribution)), pf.company.contribution, 1e-6);
          expect(pf.stores).toHaveLength(24);
        }
  });

  it("every store sits in exactly one quadrant and each quadrant has at least one store in the default story", () => {
    const pf = buildProfitPortfolio(ctxOf());
    expect(pf.quadrants.map((q) => q.id)).toEqual(QUADRANT_ORDER);
    expect(sum(pf.quadrants.map((q) => q.count))).toBe(24);
    for (const q of pf.quadrants) expect(q.count, q.id).toBeGreaterThan(0);
    for (const s of pf.stores) {
      const hiG = s.revenueGrowthPct >= pf.split.growthPct;
      const hiM = s.contributionMarginPct >= pf.split.marginPct;
      expect(s.quadrant).toBe(hiG && hiM ? "grow" : hiG ? "fix" : hiM ? "defend" : "turnaround");
    }
  });

  it("Rohini is the largest contributor to the North margin gap, as in the Command Center drill", () => {
    const pf = buildProfitPortfolio(ctxOf());
    const north = pf.stores.filter((s) => ["Rohini", "Karol Bagh", "Sector 18 Noida", "Gurugram MG Road", "Ludhiana Model Town", "Jaipur C-Scheme"].includes(s.name));
    const ws = north.map((s) => ({ s, gm: buildStoreWorkspace(ctxOf(), s.id)!.movements.find((m) => m.id === "gm_var")!.amount }));
    ws.sort((a, b) => a.gm - b.gm);
    expect(ws[0].s.name).toBe("Rohini");
    const total = sum(ws.map((x) => x.gm));
    near(total / 0.38 / 1, -1.42, 0.001); // North holds 38% of the −1.42 Cr company GM variance
  });
});

describe("Store workspace", () => {
  const ctx = ctxOf();
  const ws = buildStoreWorkspace(ctx, "rohini")!;

  it("the bridge adds up exactly from the comparison to the actual contribution", () => {
    const items = ws.bridge.items;
    near(items[0].value + sum(items.filter((i) => i.kind === "delta").map((i) => i.value)), items[items.length - 1].value, 1e-9);
    expect(items.map((i) => i.id)).toEqual(["budget_contribution", "sales_var", "gm_var", "payroll", "rent", "electricity", "logistics", "other_opex", "actual_contribution"]);
  });

  it("header strip, expenses and gap drivers all tie to the same numbers", () => {
    const contribution = ws.kpis.find((k) => k.id === "contribution")!;
    near(contribution.value, ws.bridge.items[ws.bridge.items.length - 1].value, 1e-9);
    near(ws.kpis.find((k) => k.id === "gm")!.value - ws.kpis.find((k) => k.id === "opex")!.value, contribution.value, 5e-4);
    near(sum(ws.expenses.map((e) => e.actual)), ws.kpis.find((k) => k.id === "opex")!.value, 5e-4);
    near(sum(ws.why.drivers.map((d) => d.impact)), ws.why.gap, 1e-9);
    near(ws.why.gap, contribution.variance, 1e-9);
    for (let i = 1; i < ws.expenses.length; i++) expect(ws.expenses[i - 1].impact).toBeLessThanOrEqual(ws.expenses[i].impact);
    expect(ws.why.drivers.length).toBeLessThanOrEqual(5);
  });

  it("every clickable movement exists in the catalogue the URL replays from", () => {
    const ids = new Set(ws.movements.map((m) => m.id));
    for (const i of ws.bridge.items) expect(ids.has(i.id), i.id).toBe(true);
    for (const e of ws.expenses) expect(ids.has(e.id), e.id).toBe(true);
    for (const d of ws.why.drivers) expect(ids.has(d.id), d.id).toBe(true);
  });

  it("monthly trajectory covers the year; actual months add up to the year-to-date figure", () => {
    for (const t of ws.trajectory) {
      expect(t.months).toHaveLength(12);
      const act = t.months.filter((m) => m.actual !== null).map((m) => m.actual as number);
      expect(act).toHaveLength(6);
      expect(t.months.slice(6).every((m) => m.forecast !== null && m.actual === null)).toBe(true);
    }
    const rev = ws.trajectory.find((t) => t.id === "revenue")!;
    near(sum(rev.months.filter((m) => m.actual !== null).map((m) => m.actual as number)), buildStoreWorkspace(ctxOf("normal", "ytdfy27"), "rohini")!.kpis[0].value, 1e-6);
  });

  it("network comparison covers company, zone, region, cluster and comparable stores for four metrics", () => {
    expect(ws.benchmarks.rows.map((r) => r.id)).toEqual(["growth", "gm", "opex", "contribution"]);
    for (const r of ws.benchmarks.rows) for (const c of [r.company, r.zone, r.region, r.cluster, r.comparable]) expect(Number.isFinite(c.value)).toBe(true);
  });

  it("an unknown store is not invented", () => {
    expect(buildStoreWorkspace(ctx, "no-such-store")).toBeNull();
  });
});

describe("Store drill: movement → driver → GL account → ledger", () => {
  const ctx = ctxOf();
  const ws = buildStoreWorkspace(ctx, "rohini")!;
  const store = storeNode(ws.store);

  it("every movement drills to GL accounts, and every split reconciles to its parent", () => {
    for (const m of ws.movements) {
      const mv = movementNode(m);
      let nodes: DrillNode[] = [store, mv];
      for (let depth = 0; depth < 4; depth++) {
        const view = buildProfitDrill(ctx, PROFIT_ORIGIN, nodes);
        if (view.terminal) {
          expect(view.entityKind).toBe("account");
          const ledger = buildProfitLedger(ctx, nodes);
          expect(ledger.entries.length).toBeGreaterThan(0);
          const closing = ledger.openingBalance + sum(ledger.entries.map((e) => e.debit - e.credit));
          near(closing, ledger.closingBalance, 1);
          break;
        }
        expect(view.splits.length).toBeGreaterThan(0);
        for (const sp of view.splits) {
          near(sum(sp.rows.map((r) => r.amount)), view.amount ?? 0, 6e-4);
          for (const r of sp.rows) expect(Number.isFinite(r.delta)).toBe(true);
        }
        nodes = [...nodes, view.splits[0].rows[0].node];
        if (depth === 3) throw new Error(`${m.id} never reached a GL account`);
      }
    }
  });

  it("goes through the generic dispatcher in drill.ts and ledgers too", () => {
    const view = buildDrill(ctx, PROFIT_ORIGIN, [store, movementNode(ws.movements.find((m) => m.id === "payroll")!)]);
    expect(view.title).toBe("Payroll");
    expect(view.splits[0].dim).toBe("Payroll head");
    const acct = view.splits[1].rows[0].node;
    const ledger = buildLedger(ctx, PROFIT_ORIGIN, [store, movementNode(ws.movements.find((m) => m.id === "payroll")!), acct]);
    expect(ledger.title).toContain("GL 61");
  });

  it("a total opens the P&L lines, which reconcile exactly to the contribution", () => {
    const total = ws.movements.find((m) => m.id === "actual_contribution")!;
    const view = buildProfitDrill(ctx, PROFIT_ORIGIN, [store, movementNode(total)]);
    expect(view.splits[0].dim).toBe("Line");
    near(sum(view.splits[0].rows.map((r) => r.amount)), total.amount, 1e-9);
    near(sum(view.splits[0].rows.map((r) => r.delta)), ws.why.gap, 5e-4);
  });

  it("the Other driver drills into exactly the movements folded into it", () => {
    const other = ws.movements.find((m) => m.id === "other_drivers")!;
    const view = buildProfitDrill(ctx, PROFIT_ORIGIN, [store, movementNode(other)]);
    expect(view.splits[0].rows.map((r) => r.node.id.slice(5)).sort()).toEqual([...ws.why.restIds].sort());
    near(sum(view.splits[0].rows.map((r) => r.amount)), other.amount, 1e-9);
  });
});

describe("Cash & Working Capital Control", () => {
  it("the bridge adds up from opening cash to forecast closing cash for every horizon and scenario", () => {
    for (const s of SCENARIO_ORDER)
      for (const h of ["today", "7d", "15d", "30d"] as const) {
        const room = buildCashRoom(ctxOf(s), h);
        const items = room.bridge.items;
        near(items[0].value + sum(items.filter((i) => i.kind === "delta").map((i) => i.value)), items[items.length - 1].value, 1e-9);
        expect(items[0].value).toBe(room.openingCash);
      }
  });

  it("steps cover today, 7, 15 and 30 days; the 30-day step ties to the Command Center projection", () => {
    const room = buildCashRoom(ctxOf("cash_pressure"), "30d");
    expect(room.steps.map((s) => s.horizon)).toEqual(["today", "7d", "15d", "30d"]);
    expect(room.breachDay).not.toBeNull();
    expect(room.steps.some((s) => s.breach)).toBe(true);
    near(room.steps[3].closing, room.forecastClosing, 1e-9);
  });

  it("capex is missing, not zero", () => {
    const room = buildCashRoom(ctxOf(), "30d");
    expect(room.capex.value).toBeNull();
    expect(room.capex.reason).toBeTruthy();
  });

  it("working-capital drivers add up to the net impact and have six monthly values that add up to each driver", () => {
    const room = buildCashRoom(ctxOf(), "30d");
    near(sum(room.drivers.map((d) => d.cashImpact)), room.netCashImpact, 1e-9);
    for (const d of room.drivers) {
      expect(d.monthly).toHaveLength(6);
      near(sum(d.monthly), d.cashImpact, 1e-9);
    }
    expect(room.drivers.map((d) => d.id)).toEqual(["inventory", "creditors", "vendor_advances", "receivables", "other_wc"]);
  });

  it("a cash driver drills exactly like its Command Center counterpart and reaches a ledger", () => {
    const ctx = ctxOf();
    const room = buildCashRoom(ctx, "30d");
    const inv = room.drivers.find((d) => d.id === "inventory")!;
    const node = cashNode("inventory", inv.label, inv.cashImpact);
    const view = buildDrill(ctx, CASH_ORIGIN, [node]);
    expect(view.title).toBe("Inventory");
    expect(view.splits[0].dim).toBe("Department");
    near(sum(view.splits[0].rows.map((r) => r.amount)), inv.cashImpact, 1e-3);
    const ledger = buildLedger(ctx, CASH_ORIGIN, [node]);
    expect(ledger.entries.length).toBeGreaterThan(0);
  });

  it("obligation categories drill with their own chains", () => {
    const ctx = ctxOf();
    const room = buildCashRoom(ctx, "30d");
    for (const it of room.bridge.items.filter((i) => i.id.startsWith("obl_"))) {
      const v = buildDrill(ctx, CASH_ORIGIN, [cashNode(it.id as "obl_vendor", it.label, it.value)]);
      expect(v.splits.length, it.id).toBeGreaterThan(0);
    }
  });

  it("STORE_IDS are unique slugs", () => {
    expect(new Set(STORE_IDS).size).toBe(STORE_IDS.length);
  });

  it("the decision strip is supplied by the service and every target exists on the page", () => {
    for (const sc of SCENARIO_ORDER)
      for (const h of ["today", "7d", "15d", "30d"] as const) {
        const room = buildCashRoom(ctxOf(sc), h);
        const d = room.decision;
        const known = new Set([...room.bridge.items.map((i) => i.id), ...room.drivers.map((x) => x.id)]);
        for (const key of [d.absorption?.key, d.obligation?.key, d.action?.key]) if (key) expect(known.has(key), `${sc}/${h}/${key}`).toBe(true);
        expect(d.horizonLine.length).toBeGreaterThan(0);
      }
    const pressure = buildCashRoom(ctxOf("cash_pressure"), "30d").decision;
    expect(pressure.tone).toBe("bad");
    expect(pressure.action?.key).toBe("obl_vendor");
    expect(buildCashRoom(ctxOf(), "30d").decision.absorption?.label).toBe("Inventory");
  });
});
