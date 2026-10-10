import { afterEach, describe, expect, it, vi } from "vitest";
import { createLiveCfoApi } from "./liveCfoApi";
import { mockApi } from "./mockApi";
import { CASH, CRED, CREDIT, MGMT, PNL, TILL, TOTALS, installLiveSources } from "@/test/cfoLiveFixture";
import type { DrillOrigin, QueryCtx } from "@/types/cfo";

/* The live Command Center adapter, against SYNTHETIC responses of the three real APIs (see test/cfoLiveFixture.ts). */

const ctx = (over: Partial<QueryCtx> = {}): QueryCtx => ({ scenario: "normal", period: "ytdfy27", comparison: "ly", dataState: "live", ...over });
const api = () => createLiveCfoApi({ ttlMs: 0 });
const CR = 1e7;
const origin = (scope: string, id: string, family: DrillOrigin["family"] = "margin"): DrillOrigin => ({ source: "pulse", scope, id, label: id, family, amount: 1, variance: null });

afterEach(() => vi.unstubAllGlobals());

describe("live adapter: freshness and per-source stamps", () => {
  it("reports each source with its OWN run id and as-of date, never one synchronized date", async () => {
    installLiveSources();
    const f = await api().getFreshness(ctx());
    const by = Object.fromEntries((f.sources ?? []).map((s) => [s.id, s]));
    expect(by.pnl).toMatchObject({ runId: PNL.run, asOf: PNL.asOf, ok: true });
    expect(by.mgmt).toMatchObject({ runId: MGMT.run, asOf: MGMT.asOf, ok: true, label: "Management P&L" });
    expect(by.creditors).toMatchObject({ runId: CRED.run, asOf: CRED.asOf, ok: true });
    expect(by.cash).toMatchObject({ runId: CASH.run, asOf: CASH.asOf, ok: true });
    expect(new Set([PNL.asOf, CRED.asOf, CASH.asOf]).size).toBe(3);
    expect(f.label).toMatch(/per source/);
    expect(f.label).toMatch(/P&L 09 Oct 2026/);
    expect(f.label).toMatch(/Creditors 07 Oct 2026/);
    expect(f.label).toMatch(/Cash 08 Oct 2026/);
    expect(f.stale).toBe(false);
    expect(f.asOf).toBe(CRED.asOf); // the oldest, never a made-up newer date
  });

  it("marks a source that cannot be read, and the page stays up on the others", async () => {
    installLiveSources({ fail: { cash: 500 } });
    const a = api();
    const f = await a.getFreshness(ctx());
    expect(f.stale).toBe(true);
    expect(f.label).toMatch(/not read: Cash/);
    const pulse = await a.getPulse(ctx());
    expect(pulse.status).toBe("ok");
    const cash = pulse.data!.find((m) => m.id === "cash")!;
    expect(cash.value.value).toBeNull();
    expect(cash.value.reason).toMatch(/Cash source could not be read/);
    expect(pulse.data!.find((m) => m.id === "revenue")!.value.value).toBeCloseTo(1000, 6);
  });

  it("raises an error (with Retry in the UI) when every real source is down", async () => {
    installLiveSources({ fail: { cash: 500, pnl: 500, cred: 500, mgmt: 500 } });
    await expect(api().getPulse(ctx())).rejects.toThrow(/could not be read/);
  });
});

describe("live adapter: pulse", () => {
  it("carries real figures, each stamped with its own source", async () => {
    installLiveSources();
    const p = (await api().getPulse(ctx())).data!;
    const m = (id: string) => p.find((x) => x.id === id)!;
    expect(p.map((x) => x.id)).toEqual(["revenue", "gm", "profit", "corp", "creditors", "cash"]);
    // the P&L tiles are the MIS chain from the Management P&L: book + management adjustments
    expect(m("revenue").value.value).toBeCloseTo(1000, 6);
    expect(m("gm").value.value).toBeCloseTo(40.3, 6);
    expect(m("profit").value.value).toBeCloseTo(151, 6);
    expect(m("revenue").label).toBe("Revenue from operations");
    expect(m("gm").label).toBe("Material Margin");
    expect(m("profit").label).toBe("Store EBITDA");
    expect(m("profit").status).toMatch(/includes management adjustments/);
    expect(m("gm").status).toMatch(/includes management adjustments/);
    expect(m("creditors").value.value).toBeCloseTo(CREDIT.credit, 6);
    expect(m("cash").value.value).toBeCloseTo(TILL.cash, 6);
    expect(m("revenue").source).toMatchObject({ id: "mgmt", runId: MGMT.run, asOf: MGMT.asOf });
    expect(m("creditors").source).toMatchObject({ id: "creditors", runId: CRED.run, asOf: CRED.asOf });
    expect(m("cash").source).toMatchObject({ id: "cash", runId: CASH.run, asOf: CASH.asOf });
    expect(m("cash").label).toBe("Store till cash"); // not "Cash": a till is not the company's cash
    expect(m("creditors").target).toEqual({ age: "all" });
  });

  it("compares with LAST YEAR only; budget and forecast are stated gaps, never a number", async () => {
    installLiveSources();
    const a = api();
    const ly = (await a.getPulse(ctx({ comparison: "ly" }))).data!;
    expect(ly.find((x) => x.id === "revenue")!.movement.value).toBeCloseTo(160, 6);
    expect(ly.find((x) => x.id === "gm")!.movement.value).toBe(50);
    expect(ly.find((x) => x.id === "gm")!.movementUnit).toBe("bps");
    expect(ly.find((x) => x.id === "profit")!.movement.value).toBeCloseTo(32, 6);
    for (const comparison of ["budget", "forecast"] as const) {
      const p = (await a.getPulse(ctx({ comparison }))).data!;
      for (const id of ["revenue", "gm", "profit"]) {
        const x = p.find((y) => y.id === id)!;
        expect(x.movement.value).toBeNull();
        expect(x.movement.reason).toBeTruthy();
      }
      expect(p.find((x) => x.id === "revenue")!.comparisonLabel).toMatch(/not available/);
    }
    const budget = (await a.getPulse(ctx({ comparison: "budget" }))).data!;
    expect(budget.find((x) => x.id === "revenue")!.movement.reason).toMatch(/AOP .*is not available/);
  });

  it("falls back to the P&L actuals, books basis, when the Management P&L cannot be read", async () => {
    installLiveSources({ fail: { mgmt: 500 } });
    const a = api();
    const p = (await a.getPulse(ctx())).data!;
    const m = (id: string) => p.find((x) => x.id === id)!;
    expect(m("revenue").source).toMatchObject({ id: "pnl", runId: PNL.run });
    expect(m("gm").value.value).toBeCloseTo(41, 6);
    expect(m("profit").value.value).toBeCloseTo(160, 6);
    expect(m("profit").status).toMatch(/Management P&L not read/);
    const b = (await a.getBridge(ctx(), "profit")).data!;
    expect(b.subtitle).toMatch(/Management P&L not read/);
    expect(b.unitNote).toMatch(/Books basis, before management adjustments; see Management P&L/);
    expect(b.basis).toBe("books"); // P-04: the fallback is tagged Books, never passed off as the management total
    expect(b.items.map((i) => i.id)).toEqual(["net_sales", "cogs", "cogs_books", "other_operating_income", "gross_margin", "store_opex", "contribution", "dc_cost", "ho_cost", "corporate_ebitda"]);
    const f = await a.getFreshness(ctx());
    expect(f.stale).toBe(true);
    expect(f.label).toMatch(/not read: Management P&L/);
  });

  it("has no tile for what no source supplies (vendor advances, bank reconciliation) rather than a zero or an empty tile", async () => {
    installLiveSources();
    const p = (await api().getPulse(ctx())).data!;
    expect(p.find((x) => x.id === "advances")).toBeUndefined();
    expect(p.find((x) => x.id === "unreconciled")).toBeUndefined();
    expect(p.find((x) => x.id === "corp")!.label).toBe("Corporate EBITDA");
  });

  it("the period control reaches the P&L only", async () => {
    const calls = installLiveSources();
    await api().getPulse(ctx({ period: "sep26" }));
    const summary = calls.find((c) => c.includes("/summary") && c.startsWith("/pnl-api"))!;
    expect(summary).toMatch(/from_month=2026-09/);
    expect(summary).toMatch(/to_month=2026-09/);
    const mg = calls.find((c) => c.startsWith("/mgmt-api/pnl"))!;
    expect(mg).toMatch(/from_month=2026-09/);
    expect(mg).toMatch(/entity=consolidated/);
    expect(calls.filter((c) => c.startsWith("/creditors-api") || c.startsWith("/cash-api")).every((c) => !/month/.test(c))).toBe(true);
  });
});

describe("live adapter: bridges", () => {
  it("profit bridge runs the MIS chain, revenue from operations to Corporate EBITDA, and reconciles to the pulse", async () => {
    installLiveSources();
    const a = api();
    const [b, pulse] = await Promise.all([a.getBridge(ctx(), "profit"), a.getPulse(ctx())]);
    const items = b.data!.items;
    expect(items.map((i) => i.id)).toEqual(["net_sales", "other_operating_income", "cogs", "gross_margin", "store_opex", "contribution", "dc_cost", "ho_cost", "corporate_ebitda"]);
    expect(items.map((i) => i.label)).toEqual(["Revenue from operations", "Other operating income", "Material Cost", "Material Margin", "Store Expenses", "Store EBITDA", "DC cost", "HO cost", "Corporate EBITDA"]);
    expect(items[0].value).toBeCloseTo(1000, 1);
    expect(items[0].value + items[1].value + items[2].value).toBeCloseTo(items[3].value, 1);
    expect(items[3].value + items[4].value).toBeCloseTo(items[5].value, 1);
    expect(items[5].value + items[6].value + items[7].value).toBeCloseTo(items[8].value, 1);
    expect(items[5].value).toBeCloseTo(pulse.data!.find((m) => m.id === "profit")!.value.value!, 1);
    expect(items[8].value).toBeCloseTo(111, 1);
    expect(b.data!.readout).toMatchObject({ label: "Corporate EBITDA margin", value: "11.0%" });
    expect(b.data!.readout!.note).toMatch(/includes management adjustments/);
    expect(b.data!.unitNote).toMatch(/books plus management adjustments/);
    expect(b.data!.subtitle).toMatch(new RegExp(`${MGMT.run} · as of 09 Oct 2026`));
    expect(b.data!.sources![0]).toMatchObject({ id: "mgmt", runId: MGMT.run });
  });

  it("cash bridge is unavailable with a reason; it is not drawn from a balance", async () => {
    installLiveSources();
    const b = await api().getBridge(ctx(), "cash");
    expect(b.status).toBe("unavailable");
    expect(b.reason).toMatch(/no opening-cash or cash-flow source/i);
    expect(b.data).toBeUndefined();
  });

  it("working-capital tab shows the creditors position, and it adds up", async () => {
    installLiveSources();
    const b = (await api().getBridge(ctx(), "workingCapital")).data!;
    const v = Object.fromEntries(b.items.map((i) => [i.id, i.value]));
    expect(v.not_yet_due + v.past_due + v.due_unavailable).toBeCloseTo(v.credit_outstanding, 1);
    expect(v.credit_outstanding).toBeCloseTo(CREDIT.credit, 1);
    expect(v.credit_outstanding + v.debit_balances).toBeCloseTo(v.net_payable, 1);
    expect(b.subtitle).toMatch(/inventory, receivables and vendor advances are not available/);
    expect(b.sources![0]).toMatchObject({ id: "creditors", runId: CRED.run, asOf: CRED.asOf });
  });
});

describe("live adapter: liquidity and working capital", () => {
  it("liquidity: real till cash, everything else an explicit gap (no zero, no series, no minimum)", async () => {
    installLiveSources();
    const l = (await api().getLiquidity(ctx(), "30d")).data!;
    expect(l.currentCash.value).toBeCloseTo(TILL.cash, 6);
    expect(l.currentCash.reason).toMatch(/excludes bank/);
    for (const m of [l.projectedCash, l.expectedInflows, l.upcomingObligations]) {
      expect(m.value).toBeNull();
      expect(m.reason).toMatch(/\S/);
    }
    expect(l.projectedCash.reason).toMatch(/No forecast source exists/);
    expect(l.operatingMinimum).toBeNull();
    expect(l.series).toEqual([]);
    expect(l.breachDay).toBeNull();
    expect(l.headline).toMatch(/Store till cash is ₹5\.00 Cr across 3 stores/);
    expect(l.sources![0]).toMatchObject({ id: "cash", runId: CASH.run, asOf: CASH.asOf });
  });

  it("working capital: creditors balance only; movement, inventory, receivables and advances are unavailable", async () => {
    installLiveSources();
    const w = (await api().getWorkingCapital(ctx())).data!;
    expect(w.netCashImpact).toBeNull();
    expect(w.rows.every((r) => r.cashImpact === null)).toBe(true);
    const by = Object.fromEntries(w.rows.map((r) => [r.id, r]));
    expect(by.creditors.balance!.value).toBeCloseTo(CREDIT.credit, 6);
    for (const id of ["inventory", "receivables", "vendor_advances"]) {
      expect(by[id].balance!.value).toBeNull();
      expect(by[id].balance!.reason).toMatch(/\S/);
    }
    expect(by.inventory.balance!.reason).toMatch(/stock valuation/);
  });

  it("forecast is unavailable (no source), with the budget gap stated", async () => {
    installLiveSources();
    const fc = await api().getForecast(ctx());
    expect(fc.status).toBe("unavailable");
    expect(fc.data).toBeUndefined();
    expect(fc.reason).toMatch(/No forecast source exists/);
    expect(fc.reason).toMatch(/AOP .*is not available/);
  });
});

describe("live adapter: risks and actions are derived only from real facts", () => {
  it("rates payables on the real past-due share, and leaves unsourced pillars unrated", async () => {
    installLiveSources();
    const r = (await api().getRisks(ctx())).data!;
    const by = Object.fromEntries(r.map((x) => [x.id, x]));
    expect(r.map((x) => x.id)).toEqual(["liquidity", "gm", "payables", "advances", "recon"]);
    expect(by.payables.severity).toBe("high"); // 240 of 400 = 60% past due
    expect(by.payables.exposure.value).toBeCloseTo(60, 6); // owed over 180 days
    expect(by.payables.target).toEqual({ age: "gt180" });
    expect(by.advances.severity).toBe("unrated");
    expect(by.advances.exposure.value).toBeNull();
    expect(by.gm.exposure.value).toBeNull(); // no margin-at-risk estimate exists
    expect(by.gm.movement.value).toBe(50);
    expect(by.gm.severity).toBe("low");
    expect(by.recon.severity).toBe("medium");
    expect(by.recon.diagnosticValue).toBe("2 of 3");
    expect(by.liquidity.severity).toBe("medium"); // one store has a negative till
    expect(by.payables.source).toMatchObject({ runId: CRED.run });
  });

  it("every action cites its evidence (source, run, as-of, field) and rests on a real fact", async () => {
    installLiveSources();
    const a = (await api().getActions(ctx())).data!;
    const by = Object.fromEntries(a.map((x) => [x.id, x]));
    expect(a.map((x) => x.id).sort()).toEqual(["due_missing", "negative_till", "past_due", "unmapped_ledgers"]);
    expect(by.past_due.amount.value).toBeCloseTo(CREDIT.pastDue, 6);
    expect(by.past_due.target).toEqual({ age: "past_due" });
    expect(by.past_due.severity).toBe("high");
    expect(by.due_missing.amount.value).toBeCloseTo(CREDIT.noDue, 6);
    expect(by.due_missing.target).toEqual({ age: "due_unavailable" });
    expect(by.unmapped_ledgers.problem).toBe("2 P&L ledgers need Finance mapping");
    expect(by.unmapped_ledgers.amount.value).toBeNull(); // no honest single amount
    expect(by.negative_till.amount.value).toBeCloseTo(-1, 6);
    expect(by.past_due.evidence).toMatch(new RegExp(`Creditors · ${CRED.run} · as of 07 Oct 2026 · past_due_credit`));
    expect(by.unmapped_ledgers.evidence).toMatch(new RegExp(`P&L · ${PNL.run} · as of 09 Oct 2026`));
    expect(by.negative_till.evidence).toMatch(new RegExp(`Cash · ${CASH.run} · as of 08 Oct 2026`));
    for (const x of a) expect(x.evidence).toMatch(/\S/);
    expect(a[0].severity).toBe("high"); // worst first
  });
});

describe("live adapter: drill", () => {
  it("revenue from operations splits by real stores and the visible rows plus 'other' reconcile to the parent", async () => {
    installLiveSources();
    const v = (await api().getDrillView(ctx(), origin("pulse", "revenue", "volume"), [])).data!;
    expect(v.amount).toBeCloseTo(1000, 6);
    expect(v.splits[0].dim).toBe("Top store");
    expect(v.splits[0].rows.map((r) => r.node.label)).toEqual(["ALPHA", "BRAVO", "CHARLIE"]);
    expect(v.sources!.map((s) => s.id)).toEqual(["mgmt", "pnl"]);
    expect(v.sources![1]).toMatchObject({ runId: PNL.run });
    expect(v.facts.find((f) => f.label === "Management P&L total")).toBeTruthy();
    expect(v.links![0].room).toBe("profitability");
    const shown = v.splits[0].rows.reduce((s, r) => s + r.amount, 0);
    expect(shown + (v.splits[0].other?.amount ?? 0)).toBeCloseTo(1000, 1);
  });

  it("Store Expenses split by expense group (MIS names, the raw code kept as the id); a group opens to its own facts", async () => {
    installLiveSources();
    const a = api();
    const o = origin("hero:profit", "store_opex", "cost");
    const v = (await a.getDrillView(ctx(), o, [])).data!;
    expect(v.splits[0].rows.map((r) => r.node.label)).toEqual(["Employee Cost", "Rent"]);
    expect(v.splits[0].rows.map((r) => r.node.id)).toEqual(["Expense group:02-Employee Cost", "Expense group:01-Rent"]);
    expect(v.title).toBe("Store Expenses");
    expect(v.splits[0].rows[0].amount).toBeCloseTo(150, 6);
    const g = (await a.getDrillView(ctx(), o, [v.splits[0].rows[0].node])).data!;
    expect(g.terminal).toBe(true);
    expect(g.facts.find((f) => f.label === "Ledgers")!.value).toBe("4");
    expect(g.links).toBeTruthy(); // so the ledger / profile buttons of the demo are not offered
  });

  it("creditors split by due status and ledger, with the Creditors page as the way on", async () => {
    installLiveSources();
    const v = (await api().getDrillView(ctx(), origin("action", "past_due", "payables"), [])).data!;
    expect(v.splits.map((s) => s.dim)).toEqual(["Due status", "Ledger"]);
    const notYet = v.splits[0].rows.find((r) => r.node.id === "Due status:not_yet_due")!;
    expect(notYet.amount).toBeCloseTo(CREDIT.credit - CREDIT.pastDue - CREDIT.noDue, 1);
    expect(v.links![0]).toMatchObject({ room: "creditors", age: "past_due" });
  });

  it("unmapped P&L ledgers are listed from the real reconciliation", async () => {
    installLiveSources();
    const v = (await api().getDrillView(ctx(), origin("action", "unmapped_ledgers", "recon"), [])).data!;
    expect(v.splits[0].rows.map((r) => r.node.label)).toEqual(["Stock Transfer", "Purchase IGST"]);
    expect(v.explanation).toMatch(/Finance classification/);
  });

  it("till cash drills to real stores", async () => {
    installLiveSources();
    const v = (await api().getDrillView(ctx(), origin("pulse", "cash", "cash"), [])).data!;
    expect(v.splits[0].rows[0].node.label).toBe("ALPHA");
    expect(v.links![0].room).toBe("cashroom");
  });

  it("what has no source (vendor advances, projections) is an unavailable envelope with a reason", async () => {
    installLiveSources();
    const a = api();
    const adv = await a.getDrillView(ctx(), origin("pulse", "advances", "advances"), []);
    expect(adv.status).toBe("unavailable");
    expect(adv.reason).toMatch(/vendor advances/i);
    const proj = await a.getDrillView(ctx(), origin("liquidity", "projected", "cash"), []);
    expect(proj.status).toBe("unavailable");
    expect(proj.reason).toMatch(/No forecast source exists/);
  });

  it("ledger, voucher and profile of a Command Center drill are unavailable; the live pages' own drawers are untouched", async () => {
    installLiveSources();
    const a = api();
    const o = origin("pulse", "revenue", "volume");
    expect((await a.getLedger(ctx(), o, [])).status).toBe("unavailable");
    expect((await a.getEntityProfile(ctx(), o, [])).status).toBe("unavailable");
    // the rooms keep the existing behaviour (delegated unchanged)
    const room: DrillOrigin = { source: "pulse", scope: "cashroom", id: "room", label: "Liquidity", family: "cash", amount: null, variance: null };
    const mine = await a.getDrillView(ctx(), room, []);
    const theirs = await mockApi.getDrillView(ctx(), room, []);
    expect(mine.status).toBe(theirs.status);
    expect(mine.data?.title).toBe(theirs.data?.title);
  });
});
