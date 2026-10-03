import type { CfoApi, ComparisonId, DataStateId, DrillNode, DrillOrigin, Horizon, HeroTab, PeriodId, QueryCtx, ScenarioId } from "@/types/cfo";
import { originFromBridgeItem, originFromLiquidity, originFromWcRow } from "@/lib/origins";
import { initialState, routeFor, type CfoState } from "./cfoState";

/**
 * The analytical state lives in the URL so an investigation can be shared, refreshed and navigated
 * with the browser Back button:
 *
 *   /ledger?period=ytdfy27&compare=budget&scenario=normal&drill=hero:profit.gm_impact/Department:Menswear/Region:North/Store:Rohini/ledger
 *
 * `drill` is `<scope>.<originId>` followed by one segment per drill node. Amounts are NOT in the URL:
 * a link is resolved by replaying the path through the API, so a shared link always shows current numbers.
 */
export interface CfoSearch {
  period?: PeriodId;
  compare?: ComparisonId;
  scenario?: ScenarioId;
  tab?: HeroTab;
  horizon?: Horizon;
  data?: DataStateId;
  drill?: string;
}

const PERIODS: PeriodId[] = ["sep26", "q2fy27", "ytdfy27"];
const COMPARES: ComparisonId[] = ["budget", "ly", "forecast"];
const SCENARIOS: ScenarioId[] = ["normal", "cash_pressure", "aged_creditors", "vendor_advance_risk", "margin_pressure"];
const TABS: HeroTab[] = ["profit", "cash", "workingCapital"];
const HORIZONS: Horizon[] = ["today", "7d", "15d", "30d"];
const DATA: DataStateId[] = ["live", "stale", "unavailable", "error", "empty"];

function oneOf<T extends string>(v: unknown, allowed: T[]): T | undefined {
  return typeof v === "string" && (allowed as string[]).includes(v) ? (v as T) : undefined;
}

/** Router `validateSearch`: unknown / malformed values are dropped, never thrown. */
export function validateCfoSearch(raw: Record<string, unknown>): CfoSearch {
  const drill = typeof raw.drill === "string" && raw.drill.length > 0 && raw.drill.length < 2000 ? raw.drill : undefined;
  return {
    period: oneOf(raw.period, PERIODS),
    compare: oneOf(raw.compare, COMPARES),
    scenario: oneOf(raw.scenario, SCENARIOS),
    tab: oneOf(raw.tab, TABS),
    horizon: oneOf(raw.horizon, HORIZONS),
    data: oneOf(raw.data, DATA),
    drill,
  };
}

type Filters = Pick<CfoState, "period" | "comparison" | "scenario" | "heroTab" | "horizon" | "dataState">;

/** Filters from the URL; anything absent keeps `fallback` (defaults on first load, current state in-app). */
export function filtersFromSearch(s: CfoSearch, fallback: Filters = initialState): Filters {
  return {
    period: s.period ?? fallback.period,
    comparison: s.compare ?? fallback.comparison,
    scenario: s.scenario ?? fallback.scenario,
    heroTab: s.tab ?? fallback.heroTab,
    horizon: s.horizon ?? fallback.horizon,
    dataState: s.data ?? fallback.dataState,
  };
}

const esc = (s: string) => s.replace(/%/g, "%25").replace(/\//g, "%2F");
const unesc = (s: string) => s.replace(/%2F/g, "/").replace(/%25/g, "%");

export function segmentsFor(state: Pick<CfoState, "origin" | "nodes">): string[] {
  if (!state.origin) return [];
  const o = state.origin;
  const segs = [esc(`${o.scope ?? o.source}.${o.id}`)];
  for (const n of state.nodes) {
    segs.push(esc(n.level === "ledger" ? "ledger" : n.level === "profile" ? "profile" : n.level === "voucher" ? `voucher:${n.id}` : n.id));
  }
  return segs;
}

export function encodeDrill(state: Pick<CfoState, "origin" | "nodes">): string | undefined {
  const segs = segmentsFor(state);
  return segs.length ? segs.join("/") : undefined;
}

/** Cleanest search object for a state: always explicit about the filters, drill only when present. */
export function searchFromState(s: CfoState): CfoSearch {
  const out: CfoSearch = { period: s.period, compare: s.comparison, scenario: s.scenario };
  if (s.heroTab !== initialState.heroTab) out.tab = s.heroTab;
  if (s.horizon !== initialState.horizon) out.horizon = s.horizon;
  if (s.dataState !== initialState.dataState) out.data = s.dataState;
  const drill = encodeDrill(s);
  if (drill) out.drill = drill;
  return out;
}

/** Canonical comparison key shared by state and URL, so the two never fight (no history loops). */
export function stateKey(s: CfoState): string {
  return JSON.stringify([routeFor(s), s.period, s.comparison, s.scenario, s.heroTab, s.horizon, s.dataState, encodeDrill(s) ?? ""]);
}

export function urlKey(path: string, search: CfoSearch, fallback: CfoState): string {
  const f = filtersFromSearch(search, fallback);
  return JSON.stringify([path, f.period, f.comparison, f.scenario, f.heroTab, f.horizon, f.dataState, search.drill ?? ""]);
}

export function searchIsComplete(s: CfoSearch): boolean {
  return Boolean(s.period && s.compare && s.scenario);
}

export interface ResolvedDrill {
  origin: DrillOrigin;
  nodes: DrillNode[];
  heroTab?: HeroTab;
}

const ok = <T,>(env: { status: string; data?: T }): T | null => (env.data !== undefined && env.status !== "unavailable" && env.status !== "empty" ? env.data : null);

async function resolveOrigin(api: CfoApi, ctx: QueryCtx, horizon: Horizon, scope: string, id: string): Promise<{ origin: DrillOrigin; heroTab?: HeroTab } | null> {
  if (scope.startsWith("hero:")) {
    const tab = scope.slice(5) as HeroTab;
    const bridge = ok(await api.getBridge(ctx, tab));
    const item = bridge?.items.find((i) => i.id === id);
    return bridge && item ? { origin: originFromBridgeItem(bridge, item, scope), heroTab: tab } : null;
  }
  switch (scope) {
    case "forecast": {
      const f = ok(await api.getForecast(ctx));
      const item = f?.bridge.items.find((i) => i.id === id);
      return f && item ? { origin: originFromBridgeItem(f.bridge, item, "forecast") } : null;
    }
    case "wc": {
      const w = ok(await api.getWorkingCapital(ctx));
      const row = w?.rows.find((r) => r.id === id);
      return row ? { origin: originFromWcRow(row) } : null;
    }
    case "liquidity": {
      const l = ok(await api.getLiquidity(ctx, horizon));
      return l && ["inflows", "obligations", "projected", "current"].includes(id) ? { origin: originFromLiquidity(id as "inflows", l) } : null;
    }
    case "pulse": {
      const p = ok(await api.getPulse(ctx));
      const m = p?.find((x) => x.origin.id === id);
      return m ? { origin: m.origin, heroTab: m.heroTab } : null;
    }
    case "risk": {
      const r = ok(await api.getRisks(ctx));
      const p = r?.find((x) => x.origin.id === id);
      return p ? { origin: p.origin } : null;
    }
    case "action": {
      const a = ok(await api.getActions(ctx));
      const x = a?.find((y) => y.origin.id === id);
      return x ? { origin: x.origin } : null;
    }
  }
  return null;
}

/**
 * Rebuilds the origin and nodes for a `drill` value by replaying it through the API.
 * Returns null if any step no longer exists (e.g. scenario changed), so the caller can fall back safely.
 */
export async function resolveDrill(api: CfoApi, ctx: QueryCtx, horizon: Horizon, drill: string): Promise<ResolvedDrill | null> {
  try {
    const [first, ...rest] = drill.split("/").map(unesc);
    const dot = first.lastIndexOf(".");
    if (dot < 1) return null;
    const res = await resolveOrigin(api, ctx, horizon, first.slice(0, dot), first.slice(dot + 1));
    if (!res) return null;
    const { origin } = res;
    const nodes: DrillNode[] = [];
    const filters: DrillNode[] = [];
    for (const seg of rest) {
      const last = filters[filters.length - 1];
      const amount = last?.amount ?? origin.amount;
      const variance = last?.variance ?? origin.variance;
      if (seg === "ledger") {
        nodes.push({ level: "ledger", dim: "Ledger", id: "ledger", label: "GL", amount, variance });
      } else if (seg === "profile") {
        const label = last?.dim === "Store" ? "Store profile" : last?.dim === "Vendor" ? "Vendor profile" : "Profile";
        nodes.push({ level: "profile", dim: "Profile", id: "profile", label, amount, variance });
      } else if (seg.startsWith("voucher:")) {
        const voucherId = seg.slice(8);
        const ledger = ok(await api.getLedger(ctx, origin, filters));
        const entry = ledger?.entries.find((e) => e.voucherId === voucherId);
        if (!entry) return null;
        nodes.push({ level: "voucher", dim: "Voucher", id: voucherId, label: voucherId, amount: (entry.debit || entry.credit) / 1e7, variance: null });
      } else {
        const view = ok(await api.getDrillView(ctx, origin, filters));
        const rows = view ? [...view.splits.flatMap((s) => s.rows), ...view.supportingDrivers] : [];
        const row = rows.find((r) => r.node.id === seg);
        if (!row) return null;
        nodes.push(row.node);
        filters.push(row.node);
      }
    }
    return { origin, nodes, heroTab: res.heroTab };
  } catch {
    return null;
  }
}

/** If `next` is just a shorter version of the current path (Back / breadcrumb), no refetch is needed. */
export function prefixNodes(current: Pick<CfoState, "origin" | "nodes">, nextDrill: string | undefined): DrillNode[] | null {
  if (!current.origin || !nextDrill) return null;
  const cur = segmentsFor(current);
  const nxt = nextDrill.split("/");
  if (nxt.length > cur.length || nxt.some((s, i) => s !== cur[i])) return null;
  return current.nodes.slice(0, nxt.length - 1);
}
