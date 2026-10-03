import type { ComparisonId, DataStateId, DrillNode, DrillOrigin, Horizon, HeroTab, PeriodId, QueryCtx, ScenarioId } from "@/types/cfo";

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
  origin: DrillOrigin | null;
  /** drill path after the origin: driver/entity nodes, then optionally ledger → voucher or profile */
  nodes: DrillNode[];
  drawerOpen: boolean;
}

export const initialState: CfoState = {
  period: "ytdfy27",
  comparison: "budget",
  scenario: "normal",
  dataState: "live",
  heroTab: "profit",
  horizon: "30d",
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
  | { type: "openOrigin"; origin: DrillOrigin; heroTab?: HeroTab }
  | { type: "pushNode"; node: DrillNode }
  | { type: "truncate"; keep: number }
  | { type: "closeDrawer" }
  | { type: "openDrawer" }
  | { type: "home" }
  | { type: "syncRoute"; path: string }
  | { type: "hydrate"; state: Partial<CfoState> };

export type AppRoute = "/" | "/ledger" | "/voucher" | "/profile";

const DEEP_LEVELS = new Set(["ledger", "voucher", "profile"]);

/** Which full page (if any) the current drill path lands on. */
export function routeFor(state: Pick<CfoState, "nodes" | "origin">): AppRoute {
  const last = state.nodes[state.nodes.length - 1];
  if (!state.origin || !last) return "/";
  if (last.level === "voucher") return "/voucher";
  if (last.level === "ledger") return "/ledger";
  if (last.level === "profile") return "/profile";
  return "/";
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
