import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installCreditorsApi } from "@/test/creditorsFixture";
import { mockApi } from "@/api/mockApi";
import { CREDITORS_ORIGIN, ageNode, flowNode, vendorNode } from "@/lib/creditorNodes";
import { crumbsFor, drawerAllowed, initialState, reducer, routeFor, type CfoState } from "./cfoState";
import { encodeDrill, prefixNodes, resolveDrill, searchFromState, stateKey, urlKey, validateCfoSearch } from "./drillUrl";
import type { QueryCtx } from "@/types/cfo";

const ctx: QueryCtx = { scenario: "normal", period: "ytdfy27", comparison: "budget", dataState: "live" };
const room = (over: Partial<CfoState> = {}): CfoState => ({ ...initialState, origin: CREDITORS_ORIGIN, nodes: [], ...over });

describe("creditors routing state machine", () => {
  it("maps drill depth to pages: room → vendor profile → ledger → voucher", () => {
    expect(routeFor(room())).toBe("/creditors");
    expect(routeFor(room({ nodes: [ageNode("gt180")] }))).toBe("/creditors");
    const withVendor = room({ nodes: [ageNode("gt180"), vendorNode("V10003", "Bhilwara Textiles", 52.16)] });
    expect(routeFor(withVendor)).toBe("/creditors/vendor");
    const ledger = reducer(withVendor, { type: "pushNode", node: { level: "ledger", dim: "Ledger", id: "ledger", label: "GL", amount: 52.16, variance: null } });
    expect(routeFor(ledger)).toBe("/ledger");
    const voucher = reducer(ledger, { type: "pushNode", node: { level: "voucher", dim: "Voucher", id: "PV-26-000001", label: "PV-26-000001", amount: 1, variance: null } });
    expect(routeFor(voucher)).toBe("/voucher");
  });

  it("enterCreditors carries an age filter and lens, and closes the drawer", () => {
    const s = reducer({ ...initialState, drawerOpen: true }, { type: "enterCreditors", age: "gt180", lens: "concentration" });
    expect(s.origin?.scope).toBe("creditors");
    expect(s.nodes.map((n) => n.id)).toEqual(["Ageing bucket:gt180"]);
    expect(s.lens).toBe("concentration");
    expect(s.drawerOpen).toBe(false);
    expect(reducer(initialState, { type: "enterCreditors", age: "all" }).nodes).toEqual([]);
    expect(reducer(initialState, { type: "enterCreditors" }).lens).toBe("age");
  });

  it("age selection swaps the filter and never opens the drawer; flows and abnormal do", () => {
    let s = room();
    s = reducer(s, { type: "selectFilter", node: ageNode("b181_365") });
    expect(s.nodes).toHaveLength(1);
    expect(s.drawerOpen).toBe(false);
    expect(drawerAllowed(s)).toBe(false);
    s = reducer(s, { type: "selectFilter", node: ageNode("gt90") });
    expect(s.nodes.map((n) => n.id)).toEqual(["Ageing bucket:gt90"]);
    s = reducer(s, { type: "selectFilter", node: flowNode({ id: "b61_90>b91_180", fromBucket: "b61_90", toBucket: "b91_180", openingExposure: 1, movedExposure: 1, vendorCount: 1, documentCount: 1, movementType: "aged", intoRisk: true }) });
    expect(s.drawerOpen).toBe(true);
    expect(drawerAllowed(s)).toBe(true);
    expect(reducer(s, { type: "selectFilter", node: null }).nodes).toEqual([]);
    // no effect outside the creditors room
    expect(reducer(initialState, { type: "selectFilter", node: ageNode("gt90") })).toBe(initialState);
  });

  it("the lens is a view mode: it changes no path", () => {
    const s = reducer(room({ nodes: [ageNode("gt90")] }), { type: "setLens", value: "abnormal" });
    expect(s.lens).toBe("abnormal");
    expect(s.nodes).toHaveLength(1);
  });

  it("breadcrumbs keep every meaningful stage", () => {
    const s = room({ nodes: [ageNode("gt180"), vendorNode("V10003", "Bhilwara Textiles", 52.16)] });
    expect(crumbsFor(s).map((c) => c.label)).toEqual(["CityKart", "CFO Command Center", "Creditors", ">180 days", "Bhilwara Textiles"]);
  });
});

describe("creditors URL contract", () => {
  it("a bare room needs no drill param; with nodes it encodes the path", () => {
    expect(encodeDrill(room())).toBeUndefined();
    expect(encodeDrill(room({ nodes: [ageNode("gt180")] }))).toBe("creditors.room/Ageing bucket:gt180");
    expect(encodeDrill(room({ nodes: [ageNode("gt180"), vendorNode("V10003", "Bhilwara Textiles", 1)] }))).toBe("creditors.room/Ageing bucket:gt180/Vendor:V10003");
  });

  it("lens is always explicit inside the room and omitted at its default elsewhere", () => {
    expect(searchFromState(room())).toMatchObject({ lens: "age" });
    expect(searchFromState(initialState).lens).toBeUndefined();
    expect(searchFromState({ ...initialState, lens: "abnormal" }).lens).toBe("abnormal");
    expect(validateCfoSearch({ lens: "nope" }).lens).toBeUndefined();
    expect(validateCfoSearch({ lens: "movement" }).lens).toBe("movement");
  });

  it("state and URL keys agree for the same room, so they cannot loop", () => {
    const s = room({ lens: "movement", nodes: [ageNode("gt90")] });
    expect(urlKey("/creditors", searchFromState(s), initialState)).toBe(stateKey(s));
    expect(urlKey("/creditors", searchFromState(room()), initialState)).toBe(stateKey(room()));
  });

  it("recognises Back as a prefix of the current path", () => {
    const s = room({ nodes: [ageNode("gt180"), vendorNode("V10003", "Bhilwara Textiles", 1)] });
    expect(prefixNodes(s, "creditors.room/Ageing bucket:gt180")?.map((n) => n.id)).toEqual(["Ageing bucket:gt180"]);
    expect(prefixNodes(s, "creditors.room/Ageing bucket:gt90")).toBeNull();
  });
});

describe("replaying a shared creditors link (against the real Creditors API, served synthetically)", () => {
  beforeEach(() => {
    installCreditorsApi();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("resolves age / due filters and a vendor through the API", async () => {
    const r = await resolveDrill(mockApi, ctx, "30d", "creditors.room/Ageing bucket:gt180/Vendor:Vaaaaaaaaaaaa");
    expect(r!.origin.scope).toBe("creditors");
    expect(r!.nodes.map((n) => [n.dim, n.label])).toEqual([["Ageing bucket", ">180 days"], ["Vendor", "Alpha Textiles (test)"]]);
    expect(r!.nodes[1].amount).toBeCloseTo(55, 6); // ₹55 Cr, converted from exact text
    const due = await resolveDrill(mockApi, ctx, "30d", "creditors.room/Ageing bucket:due_unavailable");
    expect(due!.nodes[0]).toMatchObject({ dim: "Ageing bucket", label: "Due date unavailable" });
  });

  it("returns null for unknown vendors and buckets, and for the demo-only flow / abnormal segments", async () => {
    for (const bad of ["creditors.room/Vendor:Vdeadbeefdead", "creditors.room/Ageing bucket:nope", "creditors.room/Migration:b61_90>b91_180", "creditors.room/Abnormal:debit_balance"]) {
      expect(await resolveDrill(mockApi, ctx, "30d", bad), bad).toBeNull();
    }
  });

  it("is independent of the demo scenario (real data does not change with it)", async () => {
    for (const s of ["normal", "cash_pressure", "aged_creditors", "vendor_advance_risk", "margin_pressure"] as const) {
      expect(await resolveDrill(mockApi, { ...ctx, scenario: s }, "30d", "creditors.room/Ageing bucket:gt180/Vendor:Vaaaaaaaaaaaa"), s).not.toBeNull();
    }
  });
});
