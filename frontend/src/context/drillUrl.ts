import type { CfoApi, ComparisonId, DataStateId, DrillNode, DrillOrigin, Horizon, HeroTab, PeriodId, QueryCtx, ScenarioId } from "@/types/cfo";
import { originFromBridgeItem, originFromLiquidity, originFromWcRow } from "@/lib/origins";
import { CREDITORS_ORIGIN, abnormalNode, ageNode, flowNode, isCreditors, vendorNode } from "@/lib/creditorNodes";
import { AGE_FILTER_LABELS, type AgeFilter, type Lens } from "@/types/creditors";
import { CASH_ORIGIN, cashNode, isCashKey, isCashRoom, type CashKey } from "@/lib/cashNodes";
import { PROFIT_ORIGIN, isProfitability, movementNode, quadrantNode, storeIdOf, storeNode } from "@/lib/profitNodes";
import { QUADRANT_ORDER, type QuadrantId } from "@/types/profitability";
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
  lens?: Lens;
  drill?: string;
}

const PERIODS: PeriodId[] = ["sep26", "q2fy27", "ytdfy27"];
const COMPARES: ComparisonId[] = ["budget", "ly", "forecast"];
const SCENARIOS: ScenarioId[] = ["normal", "cash_pressure", "aged_creditors", "vendor_advance_risk", "margin_pressure"];
const TABS: HeroTab[] = ["profit", "cash", "workingCapital"];
const HORIZONS: Horizon[] = ["today", "7d", "15d", "30d"];
const DATA: DataStateId[] = ["live", "stale", "unavailable", "error", "empty"];
const LENSES: Lens[] = ["age", "concentration", "movement", "abnormal"];

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
    lens: oneOf(raw.lens, LENSES),
    drill,
  };
}

type Filters = Pick<CfoState, "period" | "comparison" | "scenario" | "heroTab" | "horizon" | "dataState" | "lens">;

/** Filters from the URL; anything absent keeps `fallback` (defaults on first load, current state in-app). */
export function filtersFromSearch(s: CfoSearch, fallback: Filters = initialState): Filters {
  return {
    period: s.period ?? fallback.period,
    comparison: s.compare ?? fallback.comparison,
    scenario: s.scenario ?? fallback.scenario,
    heroTab: s.tab ?? fallback.heroTab,
    horizon: s.horizon ?? fallback.horizon,
    dataState: s.data ?? fallback.dataState,
    lens: s.lens ?? fallback.lens,
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

/** The workspaces that own a path of their own. Their bare form is implied by the path, so it needs no drill param. */
export function roomOriginForPath(path: string): DrillOrigin | null {
  if (path.startsWith("/creditors")) return CREDITORS_ORIGIN;
  if (path.startsWith("/profitability")) return PROFIT_ORIGIN;
  if (path === "/cash") return CASH_ORIGIN;
  return null;
}

export const ROOM_PATHS = ["/creditors", "/profitability", "/cash"];

/** Which workspace a (possibly stale) drill value belongs to, and where its home is. */
export function roomForDrill(drill: string): { origin: DrillOrigin; path: string } | null {
  if (drill.startsWith("creditors.room")) return { origin: CREDITORS_ORIGIN, path: "/creditors" };
  if (drill.startsWith("profitability.portfolio")) return { origin: PROFIT_ORIGIN, path: "/profitability" };
  if (drill.startsWith("cashroom.room")) return { origin: CASH_ORIGIN, path: "/cash" };
  return null;
}

export const isRoomOrigin = (o: DrillOrigin | null | undefined): boolean => isCreditors(o) || isProfitability(o) || isCashRoom(o);

export function encodeDrill(state: Pick<CfoState, "origin" | "nodes">): string | undefined {
  if (isRoomOrigin(state.origin) && state.nodes.length === 0) return undefined;
  const segs = segmentsFor(state);
  return segs.length ? segs.join("/") : undefined;
}

/** Cleanest search object for a state: always explicit about the filters, drill only when present. */
export function searchFromState(s: CfoState): CfoSearch {
  const out: CfoSearch = { period: s.period, compare: s.comparison, scenario: s.scenario };
  if (s.heroTab !== initialState.heroTab) out.tab = s.heroTab;
  if (s.horizon !== initialState.horizon) out.horizon = s.horizon;
  if (s.dataState !== initialState.dataState) out.data = s.dataState;
  if (isCreditors(s.origin) || s.lens !== initialState.lens) out.lens = s.lens;
  const drill = encodeDrill(s);
  if (drill) out.drill = drill;
  return out;
}

/** Canonical comparison key shared by state and URL, so the two never fight (no history loops). */
export function stateKey(s: CfoState): string {
  return JSON.stringify([routeFor(s), s.period, s.comparison, s.scenario, s.heroTab, s.horizon, s.dataState, s.lens, encodeDrill(s) ?? ""]);
}

export function urlKey(path: string, search: CfoSearch, fallback: CfoState): string {
  const f = filtersFromSearch(search, fallback);
  return JSON.stringify([path, f.period, f.comparison, f.scenario, f.heroTab, f.horizon, f.dataState, f.lens, search.drill ?? ""]);
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
    case "creditors":
      return id === "room" ? { origin: CREDITORS_ORIGIN } : null;
    case "profitability":
      return id === "portfolio" ? { origin: PROFIT_ORIGIN } : null;
    case "cashroom":
      return id === "room" ? { origin: CASH_ORIGIN } : null;
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

/** Rebuilds one creditors-room node (age filter, migration flow, abnormal category, vendor) from its URL segment. */
async function resolveCreditorNode(api: CfoApi, ctx: QueryCtx, seg: string): Promise<DrillNode | null> {
  if (seg.startsWith("Ageing bucket:")) {
    const age = seg.slice("Ageing bucket:".length) as AgeFilter;
    return age in AGE_FILTER_LABELS ? ageNode(age) : null;
  }
  if (seg.startsWith("Migration:")) {
    const m = ok(await api.getAgeingMigration(ctx));
    const f = m?.flows.find((x) => x.id === seg.slice("Migration:".length));
    return f ? flowNode(f) : null;
  }
  if (seg.startsWith("Abnormal:")) {
    const a = ok(await api.getAbnormalBalances(ctx));
    const c = a?.categories.find((x) => x.id === seg.slice("Abnormal:".length));
    return c ? abnormalNode(c) : null;
  }
  if (seg.startsWith("Vendor:")) {
    const p = ok(await api.getVendorProfile(ctx, seg.slice("Vendor:".length)));
    return p ? vendorNode(p.vendorId, p.name, p.openBalance) : null;
  }
  return null;
}

/** Rebuilds one Profitability node (quadrant filter, store, store movement) from its URL segment. */
async function resolveProfitNode(api: CfoApi, ctx: QueryCtx, seg: string, filters: DrillNode[]): Promise<DrillNode | null> {
  if (seg.startsWith("Quadrant:")) {
    const q = seg.slice("Quadrant:".length) as QuadrantId;
    return QUADRANT_ORDER.includes(q) ? quadrantNode(q) : null;
  }
  if (seg.startsWith("Store:")) {
    const ws = ok(await api.getStoreWorkspace(ctx, seg.slice("Store:".length)));
    return ws ? storeNode(ws.store) : null;
  }
  if (seg.startsWith("Movement:")) {
    const sid = storeIdOf(filters.find((n) => n.dim === "Store"));
    const ws = sid ? ok(await api.getStoreWorkspace(ctx, sid)) : null;
    const m = ws?.movements.find((x) => x.id === seg.slice("Movement:".length));
    return m ? movementNode(m) : null;
  }
  return null;
}

/** Rebuilds the cash driver node that starts an investigation in the Cash & Working Capital workspace. */
async function resolveCashNode(api: CfoApi, ctx: QueryCtx, horizon: Horizon, seg: string): Promise<DrillNode | null> {
  if (!seg.startsWith("CashDriver:")) return null;
  const key = seg.slice("CashDriver:".length);
  if (!isCashKey(key)) return null;
  const room = ok(await api.getCashRoom(ctx, horizon));
  if (!room) return null;
  const item = room.bridge.items.find((i) => i.id === key);
  if (item) return cashNode(key as CashKey, item.label, item.value);
  const drv = room.drivers.find((d) => d.id === key);
  return drv ? cashNode(key as CashKey, drv.label, drv.cashImpact) : null;
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
        if (entry) {
          nodes.push({ level: "voucher", dim: "Voucher", id: voucherId, label: voucherId, amount: (entry.debit || entry.credit) / 1e7, variance: null });
        } else if (isCreditors(origin)) {
          // an open item opened straight from the vendor profile is not necessarily a ledger row
          const vid = filters.find((n) => n.dim === "Vendor")?.id.slice("Vendor:".length);
          const prof = vid ? ok(await api.getVendorProfile(ctx, vid)) : null;
          const item = prof?.openItems.find((i) => i.documentRef === voucherId);
          if (!item) return null;
          nodes.push({ level: "voucher", dim: "Voucher", id: voucherId, label: voucherId, amount: item.amount, variance: null });
        } else {
          return null;
        }
      } else if (isProfitability(origin) && /^(Quadrant|Store|Movement):/.test(seg)) {
        const node = await resolveProfitNode(api, ctx, seg, filters);
        if (!node) return null;
        nodes.push(node);
        filters.push(node);
      } else if (isCashRoom(origin) && filters.length === 0) {
        const node = await resolveCashNode(api, ctx, horizon, seg);
        if (!node) return null;
        nodes.push(node);
        filters.push(node);
      } else if (isCreditors(origin)) {
        const node = await resolveCreditorNode(api, ctx, seg);
        if (!node) return null;
        nodes.push(node);
        filters.push(node);
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
