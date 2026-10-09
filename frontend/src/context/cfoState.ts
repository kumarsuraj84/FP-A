import type { ComparisonId, DataStateId, DrillNode, DrillOrigin, Horizon, HeroTab, PeriodId, QueryCtx, ScenarioId } from "@/types/cfo";
import type { AgeFilter, Lens } from "@/types/creditors";
import { CREDITORS_ORIGIN, ageNode } from "@/lib/creditorNodes";
import { PROFIT_ORIGIN } from "@/lib/profitNodes";
import { CASH_ORIGIN } from "@/lib/cashNodes";

/**
 * Pure state for the CFO Command Center. Filters (period, comparison, scenario, data state) are
 * independent of the drill path, so navigating back never loses them.
 */
export interface CfoState {
  period: PeriodId;
  comparison: ComparisonId;
  scenario: ScenarioId;
  dataState: DataStateId;
  heroTab: HeroTab;
  horizon: Horizon;
  /** diagnostic lens on the Creditors page (a view mode, not a drill step) */
  lens: Lens;
  origin: DrillOrigin | null;
  /** drill path after the origin: driver/entity nodes, then optionally ledger → voucher or profile */
  nodes: DrillNode[];
  drawerOpen: boolean;
}

export const initialState: CfoState = {
  period: "ytdfy27",
  /* Live data has no AOP (budget) yet, so the default comparison is Last Year there; the demo (mock) service keeps Budget. */
  comparison: (import.meta.env.VITE_CFO_DATA as string | undefined) === "mock" ? "budget" : "ly",
  scenario: "normal",
  dataState: "live",
  heroTab: "profit",
  horizon: "30d",
  lens: "age",
  origin: null,
  nodes: [],
  drawerOpen: false,
};

export type CfoAction =
  | { type: "setPeriod"; value: PeriodId }
  | { type: "setComparison"; value: ComparisonId }
  | { type: "setScenario"; value: ScenarioId }
  | { type: "setDataState"; value: DataStateId }
  | { type: "setHeroTab"; value: HeroTab }
  | { type: "setHorizon"; value: Horizon }
  | { type: "setLens"; value: Lens }
  | { type: "enterCreditors"; age?: AgeFilter; lens?: Lens }
  | { type: "enterRoom"; room: "profitability" | "cashroom" }
  /** open one store's workspace (keeps a quadrant filter when already in Profitability) */
  | { type: "enterStore"; node: DrillNode }
  /** investigate a movement on the store page: replaces anything after the store node */
  | { type: "openMovement"; node: DrillNode }
  /** investigate a cash driver: replaces the whole path inside the cash workspace */
  | { type: "openCashDriver"; node: DrillNode }
  | { type: "selectFilter"; node: DrillNode | null }
  | { type: "pushNodes"; nodes: DrillNode[] }
  | { type: "openOrigin"; origin: DrillOrigin; heroTab?: HeroTab }
  | { type: "pushNode"; node: DrillNode }
  | { type: "truncate"; keep: number }
  | { type: "closeDrawer" }
  | { type: "openDrawer" }
  | { type: "home" }
  | { type: "syncRoute"; path: string }
  | { type: "hydrate"; state: Partial<CfoState> };

export type AppRoute = "/" | "/ledger" | "/voucher" | "/profile" | "/creditors" | "/creditors/vendor" | "/profitability" | "/profitability/store" | "/cash";

const DEEP_LEVELS = new Set(["ledger", "voucher", "profile"]);

/**
 * Which page the current drill path lands on. Command Center drills end in the drawer ("/") or on a deep page;
 * the Creditors room owns "/creditors" (the room) and "/creditors/vendor" (a vendor profile).
 */
export function routeFor(state: Pick<CfoState, "nodes" | "origin">): AppRoute {
  const { origin, nodes } = state;
  if (!origin) return "/";
  const last = nodes[nodes.length - 1];
  if (last?.level === "voucher") return "/voucher";
  if (last?.level === "ledger") return "/ledger";
  if (origin.scope === "creditors") {
    return last && last.level === "entity" && last.dim === "Vendor" ? "/creditors/vendor" : "/creditors";
  }
  if (last?.level === "profile") return "/profile";
  if (origin.scope === "profitability") return nodes.some((n) => n.dim === "Store") ? "/profitability/store" : "/profitability";
  if (origin.scope === "cashroom") return "/cash";
  return "/";
}

/** The investigation drawer is available on the Command Center and for flow / abnormal selections in the room. */
export function drawerAllowed(state: Pick<CfoState, "nodes" | "origin">): boolean {
  const page = routeFor(state);
  if (page === "/") return true;
  const last = state.nodes[state.nodes.length - 1];
  // the store workspace is the page itself: the drawer is for a movement chosen on it
  if (page === "/profitability/store") return last !== undefined && last.dim !== "Store" && last.dim !== "Quadrant";
  if (page === "/cash") return state.nodes.length > 0;
  if (page !== "/creditors") return false;
  return last?.dim === "Migration" || last?.dim === "Abnormal";
}

/** Drill nodes that live in the drawer (filters), i.e. excluding deep-page nodes. */
export function drawerNodes(nodes: DrillNode[]): DrillNode[] {
  return nodes.filter((n) => !DEEP_LEVELS.has(n.level));
}

export function reducer(state: CfoState, a: CfoAction): CfoState {
  switch (a.type) {
    case "setPeriod":
      return { ...state, period: a.value };
    case "setComparison":
      return { ...state, comparison: a.value };
    case "setScenario":
      return { ...state, scenario: a.value };
    case "setDataState":
      return { ...state, dataState: a.value };
    case "setHeroTab":
      return { ...state, heroTab: a.value };
    case "setHorizon":
      return { ...state, horizon: a.value };
    case "openOrigin":
      return { ...state, origin: a.origin, nodes: [], drawerOpen: true, heroTab: a.heroTab ?? state.heroTab };
    case "setLens":
      return { ...state, lens: a.value };
    case "enterCreditors":
      return {
        ...state,
        origin: CREDITORS_ORIGIN,
        nodes: a.age && a.age !== "all" ? [ageNode(a.age)] : [],
        lens: a.lens ?? state.lens,
        drawerOpen: false,
      };
    case "enterRoom":
      return { ...state, origin: a.room === "profitability" ? PROFIT_ORIGIN : CASH_ORIGIN, nodes: [], drawerOpen: false };
    case "enterStore": {
      const keep = state.origin?.scope === "profitability" ? state.nodes.filter((n) => n.dim === "Quadrant") : [];
      return { ...state, origin: PROFIT_ORIGIN, nodes: [...keep, a.node], drawerOpen: false };
    }
    case "openMovement": {
      if (state.origin?.scope !== "profitability") return state;
      const at = state.nodes.findIndex((n) => n.dim === "Store");
      if (at < 0) return state;
      return { ...state, nodes: [...state.nodes.slice(0, at + 1), a.node], drawerOpen: true };
    }
    case "openCashDriver":
      return { ...state, origin: CASH_ORIGIN, nodes: [a.node], drawerOpen: true };
    case "selectFilter":
      if (state.origin?.scope !== "creditors" && state.origin?.scope !== "profitability") return state;
      return { ...state, nodes: a.node ? [a.node] : [], drawerOpen: a.node ? a.node.dim !== "Ageing bucket" && a.node.dim !== "Quadrant" : false };
    case "pushNodes":
      return { ...state, nodes: [...state.nodes, ...a.nodes], drawerOpen: true };
    case "pushNode": {
      // a deep page replaces any earlier deep node of the same kind
      const base = DEEP_LEVELS.has(a.node.level) ? state.nodes.filter((n) => n.level !== a.node.level && n.level !== "voucher") : state.nodes;
      return { ...state, nodes: [...base, a.node], drawerOpen: true };
    }
    case "truncate":
      return { ...state, nodes: state.nodes.slice(0, Math.max(0, a.keep)), drawerOpen: true };
    case "closeDrawer":
      return { ...state, drawerOpen: false };
    case "openDrawer":
      return state.origin ? { ...state, drawerOpen: true } : state;
    case "home":
      return { ...state, origin: null, nodes: [], drawerOpen: false };
    case "syncRoute": {
      // browser Back/Forward: unwind the path until it matches the URL
      let nodes = state.nodes;
      while (nodes.length > 0 && routeFor({ origin: state.origin, nodes }) !== a.path) nodes = nodes.slice(0, -1);
      return nodes === state.nodes ? state : { ...state, nodes, drawerOpen: true };
    }
    case "hydrate":
      return { ...state, ...a.state };
    default:
      return state;
  }
}

export interface Crumb {
  label: string;
  /** number of nodes to keep when clicked; -1 = home */
  keep: number;
  current: boolean;
}

export function crumbsFor(state: Pick<CfoState, "origin" | "nodes">): Crumb[] {
  const crumbs: Crumb[] = [
    { label: "CityKart", keep: -1, current: false },
    { label: "CFO Command Center", keep: -1, current: !state.origin },
  ];
  if (state.origin) {
    crumbs.push({ label: state.origin.label, keep: 0, current: state.nodes.length === 0 });
    state.nodes.forEach((n, i) => crumbs.push({ label: n.label, keep: i + 1, current: i === state.nodes.length - 1 }));
  }
  return crumbs;
}

export function toQueryCtx(s: Pick<CfoState, "scenario" | "period" | "comparison" | "dataState">): QueryCtx {
  return { scenario: s.scenario, period: s.period, comparison: s.comparison, dataState: s.dataState };
}

export const STORAGE_KEY = "citykart-cfo-os/v1";
