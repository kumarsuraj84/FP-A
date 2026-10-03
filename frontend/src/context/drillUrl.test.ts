import { describe, expect, it } from "vitest";
import { mockApi } from "@/api/mockApi";
import { reducer, initialState, type CfoState } from "./cfoState";
import { encodeDrill, filtersFromSearch, prefixNodes, resolveDrill, searchFromState, stateKey, urlKey, validateCfoSearch } from "./drillUrl";
import { originFromBridgeItem } from "@/lib/origins";
import type { DrillNode, DrillOrigin, QueryCtx } from "@/types/cfo";

const ctx: QueryCtx = { scenario: "normal", period: "ytdfy27", comparison: "budget", dataState: "live" };
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

async function gmOrigin(c: QueryCtx = ctx): Promise<DrillOrigin> {
  const bridge = (await mockApi.getBridge(c, "profit")).data!;
  return originFromBridgeItem(bridge, bridge.items.find((i) => i.id === "gm_impact")!, "hero:profit");
}

/** Walks the same clicks a user would: Department → Region → Store. */
async function clickPath(origin: DrillOrigin, picks: [string, string][]): Promise<DrillNode[]> {
  const nodes: DrillNode[] = [];
  for (const [dim, label] of picks) {
    const view = (await mockApi.getDrillView(ctx, origin, nodes)).data!;
    const row = view.splits.find((s) => s.dim === dim)!.rows.find((r) => r.node.label === label)!;
    nodes.push(row.node);
  }
  return nodes;
}

describe("URL state encoding", () => {
  it("drops unknown or malformed params instead of throwing", () => {
    expect(validateCfoSearch({ period: "nope", compare: 4, scenario: "cash_pressure", drill: "" })).toEqual({
      period: undefined,
      compare: undefined,
      scenario: "cash_pressure",
      tab: undefined,
      horizon: undefined,
      data: undefined,
      drill: undefined,
    });
  });

  it("encodes the drill hierarchy readably", async () => {
    const origin = await gmOrigin();
    const nodes = await clickPath(origin, [["Department", "Menswear"], ["Region", "North"], ["Store", "Rohini"]]);
    const s: CfoState = { ...initialState, origin, nodes };
    expect(encodeDrill(s)).toBe("hero:profit.gm_impact/Department:Menswear/Region:North/Store:Rohini");
    expect(searchFromState(s)).toMatchObject({ period: "ytdfy27", compare: "budget", scenario: "normal", drill: encodeDrill(s) });
  });

  it("keeps clean URLs: tab/horizon/data only when not default", () => {
    const base = searchFromState(initialState);
    expect(base).toEqual({ period: "ytdfy27", compare: "budget", scenario: "normal" });
    const s = reducer(reducer(initialState, { type: "setHeroTab", value: "cash" }), { type: "setDataState", value: "stale" });
    expect(searchFromState(s)).toMatchObject({ tab: "cash", data: "stale" });
  });

  it("state and URL agree on a canonical key, so they cannot loop", async () => {
    const origin = await gmOrigin();
    const nodes = await clickPath(origin, [["Department", "Menswear"]]);
    let s: CfoState = { ...initialState, origin, nodes };
    s = reducer(s, { type: "setScenario", value: "margin_pressure" });
    const search = searchFromState(s);
    expect(urlKey("/", search, initialState)).toBe(stateKey(s));
    expect(urlKey("/ledger", search, initialState)).not.toBe(stateKey(s));
  });

  it("filtersFromSearch keeps the fallback for anything absent (in-app links)", () => {
    const current = { ...initialState, scenario: "cash_pressure" as const };
    expect(filtersFromSearch({ period: "sep26" }, current)).toMatchObject({ period: "sep26", scenario: "cash_pressure" });
  });
});

describe("resolving a shared link", () => {
  it("replays Department → Region → Store to exactly the nodes a user would click", async () => {
    const origin = await gmOrigin();
    const picks: [string, string][] = [["Department", "Menswear"], ["Region", "North"], ["Store", "Rohini"]];
    const clicked = await clickPath(origin, picks);
    const r = await resolveDrill(mockApi, ctx, "30d", "hero:profit.gm_impact/Department:Menswear/Region:North/Store:Rohini");
    expect(r).not.toBeNull();
    expect(r!.origin).toEqual(origin);
    expect(r!.nodes).toEqual(clicked);
    expect(r!.heroTab).toBe("profit");
  });

  it("replays through ledger and voucher", async () => {
    const r = await resolveDrill(mockApi, ctx, "30d", "hero:profit.gm_impact/Department:Menswear/Region:North/Store:Rohini/ledger");
    expect(r!.nodes.at(-1)).toMatchObject({ level: "ledger", label: "GL" });
    const ledger = (await mockApi.getLedger(ctx, r!.origin, r!.nodes.filter((n) => n.level === "entity" || n.level === "driver"))).data!;
    const vid = ledger.entries[3].voucherId;
    const v = await resolveDrill(mockApi, ctx, "30d", `hero:profit.gm_impact/Department:Menswear/Region:North/Store:Rohini/ledger/voucher:${vid}`);
    expect(v!.nodes.at(-1)).toMatchObject({ level: "voucher", id: vid });
    expect(v!.nodes.at(-1)!.amount).toBeCloseTo((ledger.entries[3].debit || ledger.entries[3].credit) / 1e7, 6);
  });

  it("resolves every origin family: pulse, risk, action, wc, liquidity, forecast, cash bridge", async () => {
    for (const d of ["pulse.profit", "pulse.gm", "risk.creditors_181", "action.advances_90", "wc.inventory", "liquidity.projected", "forecast.margin_risk", "hero:cash.creditors"]) {
      const r = await resolveDrill(mockApi, ctx, "30d", d);
      expect(r, d).not.toBeNull();
      expect(r!.nodes).toEqual([]);
    }
  });

  it("returns null (safe fallback) for stale or tampered links", async () => {
    expect(await resolveDrill(mockApi, ctx, "30d", "hero:profit.not_a_bar")).toBeNull();
    expect(await resolveDrill(mockApi, ctx, "30d", "hero:profit.gm_impact/Department:Atlantis")).toBeNull();
    expect(await resolveDrill(mockApi, ctx, "30d", "garbage")).toBeNull();
    expect(await resolveDrill(mockApi, { ...ctx, dataState: "unavailable" }, "30d", "hero:profit.gm_impact")).toBeNull();
    expect(await resolveDrill(mockApi, { ...ctx, dataState: "error" }, "30d", "hero:profit.gm_impact")).toBeNull();
  });

  it("recognises a shorter path as a prefix (Back / breadcrumb) without refetching", async () => {
    const origin = await gmOrigin();
    const nodes = await clickPath(origin, [["Department", "Menswear"], ["Region", "North"]]);
    const cur = { origin, nodes };
    expect(prefixNodes(cur, "hero:profit.gm_impact/Department:Menswear")).toEqual(nodes.slice(0, 1));
    expect(prefixNodes(cur, "hero:profit.gm_impact")).toEqual([]);
    expect(prefixNodes(cur, "hero:profit.gm_impact/Department:Kidswear")).toBeNull();
    expect(prefixNodes(cur, "hero:profit.payroll")).toBeNull();
  });
});

describe("demo materiality: the showcase margin investigation", () => {
  it("Gross Margin Impact is −₹1.42 Cr and Menswear is clearly the lead driver", async () => {
    const origin = await gmOrigin();
    expect(origin.amount).toBe(-1.42);
    const dept = (await mockApi.getDrillView(ctx, origin, [])).data!.splits[0];
    expect(dept.dim).toBe("Department");
    const by = Object.fromEntries(dept.rows.map((r) => [r.node.label, r.amount]));
    expect(dept.rows[0].node.label).toBe("Menswear");
    expect(by.Menswear).toBeCloseTo(-0.84, 2);
    expect(by.Womenswear).toBeCloseTo(-0.29, 2);
    expect(by.Kidswear).toBeCloseTo(-0.18, 2);
    expect(by.Footwear + by.Accessories + by["Home & Living"]).toBeCloseTo(-0.11, 2);
    expect(Math.abs(by.Menswear) / 1.42).toBeGreaterThan(0.55);
  });

  it("reconciles exactly down department → region → store", async () => {
    const origin = await gmOrigin();
    const v0 = (await mockApi.getDrillView(ctx, origin, [])).data!;
    expect(sum(v0.splits[0].rows.map((r) => r.amount))).toBeCloseTo(-1.42, 4);

    const menswear = v0.splits[0].rows.find((r) => r.node.label === "Menswear")!;
    const v1 = (await mockApi.getDrillView(ctx, origin, [menswear.node])).data!;
    const regions = v1.splits.find((s) => s.dim === "Region")!;
    expect(sum(regions.rows.map((r) => r.amount))).toBeCloseTo(menswear.amount, 4);
    expect(regions.rows[0].node.label).toBe("North");

    const north = regions.rows[0];
    const v2 = (await mockApi.getDrillView(ctx, origin, [menswear.node, north.node])).data!;
    const stores = v2.splits.find((s) => s.dim === "Store")!;
    expect(sum(stores.rows.map((r) => r.amount))).toBeCloseTo(north.amount, 4);
    expect(stores.rows[0].node.label).toBe("Rohini");
    expect(stores.rows).toHaveLength(6); // all of North's stores are listed, so nothing is hidden
    expect(stores.other).toBeUndefined();

    // unfiltered long lists keep reconciling through the explicit "other" line
    const all = v1.splits.find((s) => s.dim === "Store")!;
    expect(all.rows).toHaveLength(5);
    expect(sum(all.rows.map((r) => r.amount)) + all.other!.amount).toBeCloseTo(menswear.amount, 4);
  });

  it("is deterministic and holds in other scenarios (scaled)", async () => {
    const a = (await mockApi.getDrillView(ctx, await gmOrigin(), [])).data!;
    const b = (await mockApi.getDrillView(ctx, await gmOrigin(), [])).data!;
    expect(a).toEqual(b);
    const mp: QueryCtx = { ...ctx, scenario: "margin_pressure" };
    const o = await gmOrigin(mp);
    const d = (await mockApi.getDrillView(mp, o, [])).data!.splits[0];
    expect(d.rows[0].node.label).toBe("Menswear");
    expect(sum(d.rows.map((r) => r.amount))).toBeCloseTo(o.amount!, 4);
  });
});
