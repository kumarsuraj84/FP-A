import { describe, expect, it } from "vitest";
import { mockApi, ApiError } from "@/api/mockApi";
import { SCENARIO_ORDER } from "./scenarios";
import type { BridgeItem, DrillNode, DrillOrigin, QueryCtx, ScenarioId } from "@/types/cfo";

const ctx = (scenario: ScenarioId, over: Partial<QueryCtx> = {}): QueryCtx => ({ scenario, period: "ytdfy27", comparison: "budget", dataState: "live", ...over });
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

describe("bridges reconcile", () => {
  it.each(SCENARIO_ORDER)("profit bridge adds up in %s", async (s) => {
    const env = await mockApi.getBridge(ctx(s), "profit");
    const items = env.data!.items;
    const start = items[0].value;
    const end = items[items.length - 1].value;
    expect(start + sum(items.filter((i) => i.kind === "delta").map((i) => i.value))).toBeCloseTo(end, 1);
  });

  it.each(SCENARIO_ORDER)("cash bridge closes on the pulse cash figure in %s", async (s) => {
    const [bridge, pulse] = await Promise.all([mockApi.getBridge(ctx(s), "cash"), mockApi.getPulse(ctx(s))]);
    const items = bridge.data!.items;
    expect(items[0].value + sum(items.filter((i) => i.kind === "delta").map((i) => i.value))).toBeCloseTo(items[items.length - 1].value, 1);
    expect(items[items.length - 1].value).toBe(pulse.data!.find((m) => m.id === "cash")!.value.value);
  });

  it("working-capital panel nets to the sum of its rows", async () => {
    const env = await mockApi.getWorkingCapital(ctx("normal"));
    expect(env.data!.netCashImpact).toBeCloseTo(sum(env.data!.rows.map((r) => r.cashImpact ?? 0)), 2);
  });

  it("operating profit on the pulse equals the profit bridge actual", async () => {
    const [bridge, pulse] = await Promise.all([mockApi.getBridge(ctx("normal"), "profit"), mockApi.getPulse(ctx("normal"))]);
    expect(bridge.data!.items.at(-1)!.value).toBe(pulse.data!.find((m) => m.id === "profit")!.value.value);
  });
});

describe("scenarios change the story", () => {
  it("Normal vs each stress scenario differ in the section it should stress", async () => {
    const n = ctx("normal");
    const [pulseN, risksN, liqN] = await Promise.all([mockApi.getPulse(n), mockApi.getRisks(n), mockApi.getLiquidity(n, "30d")]);
    const cash = await Promise.all([mockApi.getPulse(ctx("cash_pressure")), mockApi.getLiquidity(ctx("cash_pressure"), "30d"), mockApi.getRisks(ctx("cash_pressure"))]);
    expect(cash[0].data!.find((m) => m.id === "cash")!.value.value!).toBeLessThan(pulseN.data!.find((m) => m.id === "cash")!.value.value!);
    expect(liqN.data!.breachDay).toBeNull();
    expect(cash[1].data!.breachDay).not.toBeNull();
    expect(cash[2].data!.find((r) => r.id === "liquidity")!.severity).toBe("critical");
    expect(risksN.data!.find((r) => r.id === "liquidity")!.severity).not.toBe("critical");

    const aged = await mockApi.getRisks(ctx("aged_creditors"));
    expect(aged.data!.find((r) => r.id === "payables")!.severity).toBe("critical");
    const adv = await mockApi.getRisks(ctx("vendor_advance_risk"));
    expect(adv.data!.find((r) => r.id === "advances")!.severity).toBe("critical");
    const gm = await Promise.all([mockApi.getPulse(ctx("margin_pressure")), mockApi.getForecast(ctx("margin_pressure")), mockApi.getForecast(n)]);
    expect(gm[0].data!.find((m) => m.id === "gm")!.value.value!).toBeLessThan(pulseN.data!.find((m) => m.id === "gm")!.value.value!);
    expect(gm[1].data!.landing.value!).toBeLessThan(gm[2].data!.landing.value!);
  });

  it("needs-your-attention leads with the scenario's biggest problem", async () => {
    const lead = async (s: ScenarioId) => (await mockApi.getActions(ctx(s))).data![0].id;
    expect(await lead("cash_pressure")).toBe("liquidity");
    expect(await lead("aged_creditors")).toBe("creditors_181");
    expect(await lead("vendor_advance_risk")).toBe("advances_90");
    expect(await lead("margin_pressure")).toBe("gm_gap");
  });

  it("period and comparison materially change the bridge", async () => {
    const a = (await mockApi.getBridge(ctx("normal"), "profit")).data!;
    const b = (await mockApi.getBridge(ctx("normal", { period: "sep26" }), "profit")).data!;
    const c = (await mockApi.getBridge(ctx("normal", { comparison: "ly" }), "profit")).data!;
    expect(b.items.at(-1)!.value).toBeLessThan(a.items.at(-1)!.value);
    expect(c.items[0].label).toBe("Last Year Profit");
    expect(c.items[0].value).not.toBe(a.items[0].value);
  });
});

const origin = async (id: string): Promise<DrillOrigin> => {
  const bridge = (await mockApi.getBridge(ctx("normal"), "profit")).data!;
  const item = bridge.items.find((i) => i.id === id) as BridgeItem;
  return { source: "bridge", scope: "hero:profit", id, label: item.label, family: item.family, amount: item.value, variance: item.value, base: bridge.items[0].value };
};

describe("drill engine", () => {
  it("each split adds up to its parent and rows are clickable nodes", async () => {
    const o = await origin("gm_impact");
    const v = (await mockApi.getDrillView(ctx("normal"), o, [])).data!;
    expect(v.terminal).toBe(false);
    expect(v.splits.map((s) => s.dim)).toEqual(["Department", "Region", "Store"]);
    const dept = v.splits[0].rows;
    expect(sum(dept.map((r) => r.amount))).toBeCloseTo(o.amount!, 2);
    expect(v.variancePct).not.toBe(-100);
    expect(v.supportingDrivers.length).toBeGreaterThan(0);
    for (const r of [...dept, ...v.supportingDrivers]) expect(r.node.id).toBeTruthy();
  });

  it("walks movement → department → region → store and ends terminal", async () => {
    const o = await origin("gm_impact");
    const nodes: DrillNode[] = [];
    let v = (await mockApi.getDrillView(ctx("normal"), o, nodes)).data!;
    for (const dim of ["Department", "Region", "Store"]) {
      const row = v.splits.find((s) => s.dim === dim)!.rows[0];
      nodes.push(row.node);
      v = (await mockApi.getDrillView(ctx("normal"), o, nodes)).data!;
    }
    expect(v.terminal).toBe(true);
    expect(v.entityKind).toBe("store");
    expect(v.splits).toHaveLength(0);
  });

  it("is deterministic for the same path", async () => {
    const o = await origin("payroll");
    const a = (await mockApi.getDrillView(ctx("normal"), o, [])).data!;
    const b = (await mockApi.getDrillView(ctx("normal"), o, [])).data!;
    expect(a).toEqual(b);
  });

  it("creditors walk ageing bucket → vendor and reach a vendor entity", async () => {
    const cash = (await mockApi.getBridge(ctx("normal"), "cash")).data!;
    const item = cash.items.find((i) => i.id === "creditors")!;
    const o: DrillOrigin = { source: "bridge", scope: "hero:cash", id: "creditors", label: item.label, family: "payables", amount: item.value, variance: item.value, base: cash.items[0].value };
    const v1 = (await mockApi.getDrillView(ctx("normal"), o, [])).data!;
    expect(v1.splits[0].dim).toBe("Ageing bucket");
    const v2 = (await mockApi.getDrillView(ctx("normal"), o, [v1.splits[0].rows[0].node])).data!;
    const vendor = v2.splits[0].rows[0].node;
    const v3 = (await mockApi.getDrillView(ctx("normal"), o, [v1.splits[0].rows[0].node, vendor])).data!;
    expect(v3.entityKind).toBe("vendor");
    expect(v3.terminal).toBe(true);
  });

  it("ledger entries net to the entity amount and link to vouchers with evidence", async () => {
    const o = await origin("gm_impact");
    const node: DrillNode = { level: "entity", dim: "Store", id: "Store:Rohini", label: "Rohini", amount: -0.25, variance: -0.25 };
    const l = (await mockApi.getLedger(ctx("normal"), o, [node])).data!;
    expect(Math.abs(l.closingBalance - l.openingBalance)).toBeCloseTo(0.25 * 1e7, -3);
    const e = l.entries[2];
    const v = (await mockApi.getVoucher(ctx("normal"), e.voucherId, e.debit || e.credit)).data!;
    expect(v.total).toBe(e.debit || e.credit);
    expect(sum(v.lines.map((x) => x.debit))).toBe(sum(v.lines.map((x) => x.credit)));
    expect(v.evidence.mappingStatus).toMatch(/Awaiting finance mapping/);
  });
});

describe("data states never fake numbers", () => {
  it("unavailable returns no data and a reason, not zeros", async () => {
    const env = await mockApi.getPulse(ctx("normal", { dataState: "unavailable" }));
    expect(env.status).toBe("unavailable");
    expect(env.data).toBeUndefined();
    expect(env.reason).toBe("Awaiting finance mapping");
  });
  it("empty returns no data", async () => {
    const env = await mockApi.getActions(ctx("normal", { dataState: "empty" }));
    expect(env.status).toBe("empty");
    expect(env.data).toBeUndefined();
  });
  it("stale returns data flagged stale", async () => {
    const env = await mockApi.getRisks(ctx("normal", { dataState: "stale" }));
    expect(env.status).toBe("stale");
    expect(env.data).toBeDefined();
  });
  it("error rejects", async () => {
    await expect(mockApi.getForecast(ctx("normal", { dataState: "error" }))).rejects.toBeInstanceOf(ApiError);
  });
});
