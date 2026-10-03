import { describe, expect, it } from "vitest";
import { crumbsFor, drawerNodes, initialState, reducer, routeFor, type CfoState } from "./cfoState";
import type { DrillNode, DrillOrigin } from "@/types/cfo";

const origin: DrillOrigin = { source: "bridge", scope: "hero:profit", id: "gm_impact", label: "GM Variance", family: "margin", amount: -1.42, variance: -1.42 };
const node = (level: DrillNode["level"], dim: string, label: string): DrillNode => ({ level, dim, id: `${dim}:${label}`, label, amount: -0.2, variance: -0.2 });

function journey(): CfoState {
  let s = reducer(initialState, { type: "openOrigin", origin });
  s = reducer(s, { type: "pushNode", node: node("driver", "Department", "Menswear") });
  s = reducer(s, { type: "pushNode", node: node("entity", "Region", "North") });
  s = reducer(s, { type: "pushNode", node: node("entity", "Store", "Rohini") });
  return s;
}

describe("drill journey state", () => {
  it("builds breadcrumbs for movement → driver → entity → store", () => {
    const labels = crumbsFor(journey()).map((c) => c.label);
    expect(labels).toEqual(["CityKart", "CFO Command Center", "GM Variance", "Menswear", "North", "Rohini"]);
  });

  it("routes to ledger then voucher, and back", () => {
    let s = journey();
    expect(routeFor(s)).toBe("/");
    s = reducer(s, { type: "pushNode", node: node("ledger", "Ledger", "GL") });
    expect(routeFor(s)).toBe("/ledger");
    s = reducer(s, { type: "pushNode", node: node("voucher", "Voucher", "JV-26-000001") });
    expect(routeFor(s)).toBe("/voucher");
    expect(crumbsFor(s).map((c) => c.label).slice(-3)).toEqual(["Rohini", "GL", "JV-26-000001"]);
    s = reducer(s, { type: "truncate", keep: 3 });
    expect(routeFor(s)).toBe("/");
    expect(s.drawerOpen).toBe(true);
    expect(s.nodes.map((n) => n.label)).toEqual(["Menswear", "North", "Rohini"]);
  });

  it("clicking a breadcrumb preserves period, comparison, scenario and filters", () => {
    let s = journey();
    s = reducer(s, { type: "setPeriod", value: "q2fy27" });
    s = reducer(s, { type: "setComparison", value: "ly" });
    s = reducer(s, { type: "setScenario", value: "cash_pressure" });
    s = reducer(s, { type: "setHorizon", value: "7d" });
    s = reducer(s, { type: "truncate", keep: 1 });
    expect(s.nodes.map((n) => n.label)).toEqual(["Menswear"]);
    expect([s.period, s.comparison, s.scenario, s.horizon]).toEqual(["q2fy27", "ly", "cash_pressure", "7d"]);
    s = reducer(s, { type: "home" });
    expect(s.origin).toBeNull();
    expect([s.period, s.comparison, s.scenario, s.horizon]).toEqual(["q2fy27", "ly", "cash_pressure", "7d"]);
  });

  it("changing scenario keeps the drill context", () => {
    const s = reducer(journey(), { type: "setScenario", value: "margin_pressure" });
    expect(s.nodes).toHaveLength(3);
    expect(s.origin?.id).toBe("gm_impact");
  });

  it("opening a new origin resets the path but keeps filters", () => {
    let s = reducer(journey(), { type: "setPeriod", value: "sep26" });
    s = reducer(s, { type: "openOrigin", origin: { ...origin, id: "payroll", label: "Payroll" }, heroTab: "profit" });
    expect(s.nodes).toEqual([]);
    expect(s.period).toBe("sep26");
    expect(s.drawerOpen).toBe(true);
  });

  it("browser Back unwinds deep pages to match the URL", () => {
    let s = reducer(journey(), { type: "pushNode", node: node("ledger", "Ledger", "GL") });
    s = reducer(s, { type: "pushNode", node: node("voucher", "Voucher", "V1") });
    s = reducer(s, { type: "syncRoute", path: "/ledger" });
    expect(routeFor(s)).toBe("/ledger");
    s = reducer(s, { type: "syncRoute", path: "/" });
    expect(routeFor(s)).toBe("/");
    expect(drawerNodes(s.nodes)).toHaveLength(3);
  });

  it("closing the drawer keeps the context so the crumb can reopen it", () => {
    const s = reducer(journey(), { type: "closeDrawer" });
    expect(s.drawerOpen).toBe(false);
    expect(s.nodes).toHaveLength(3);
    expect(reducer(s, { type: "openDrawer" }).drawerOpen).toBe(true);
  });
});
