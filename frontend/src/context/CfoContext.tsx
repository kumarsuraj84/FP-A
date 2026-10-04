import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { cfoApi } from "@/api";
import type { DrillNode, DrillOrigin, HeroTab, QueryCtx } from "@/types/cfo";
import type { CreditorsTarget } from "@/types/creditors";
import { crumbsFor, drawerAllowed, initialState, reducer, routeFor, toQueryCtx, type CfoAction, type CfoState, type Crumb } from "./cfoState";
import {
  encodeDrill,
  filtersFromSearch,
  prefixNodes,
  resolveDrill,
  searchFromState,
  searchIsComplete,
  roomForDrill,
  roomOriginForPath,
  ROOM_PATHS,
  stateKey,
  urlKey,
  type CfoSearch,
} from "./drillUrl";

interface CfoContextValue {
  state: CfoState;
  /** always true now: filters come from the URL on first render */
  ready: boolean;
  /** true while a drill from a shared / refreshed URL is being replayed */
  resolving: boolean;
  queryCtx: QueryCtx;
  crumbs: Crumb[];
  dispatch: (a: CfoAction) => void;
  openOrigin: (origin: DrillOrigin, heroTab?: HeroTab) => void;
  /** hand-off into the Creditors room, carrying an age filter and lens */
  enterCreditors: (target?: CreditorsTarget) => void;
  /** hand-off into the Profitability or Cash & Working Capital workspace */
  enterRoom: (room: "profitability" | "cashroom") => void;
  /** open a store's workspace from anywhere */
  enterStore: (node: DrillNode) => void;
  /** investigate a store movement (bridge bar, expense, driver) */
  openMovement: (node: DrillNode) => void;
  /** investigate a cash driver */
  openCashDriver: (node: DrillNode) => void;
  /** select / clear the room's age, flow or abnormal filter */
  selectFilter: (node: DrillNode | null) => void;
  pushNodes: (nodes: DrillNode[]) => void;
  pushNode: (node: DrillNode) => void;
  goToCrumb: (crumb: Crumb) => void;
  back: () => void;
  closeDrawer: () => void;
}

const Ctx = createContext<CfoContextValue | null>(null);
const APP_PATHS = ["/", "/ledger", "/voucher", "/profile", "/creditors", "/creditors/vendor", "/profitability", "/profitability/store", "/cash"];

/** The drill value looks like a single room-level filter (age bucket or quadrant), or none: these swaps replace history. */
function isFilterSelectionOnly(drill: string): boolean {
  if (!drill) return true;
  const segs = drill.split("/");
  if (!roomForDrill(segs[0])) return false;
  return segs.length === 1 || (segs.length === 2 && (segs[1].startsWith("Ageing bucket:") || segs[1].startsWith("Quadrant:")));
}

export function CfoProvider({ children, initial }: { children: ReactNode; initial?: Partial<CfoState> }) {
  const loc = useRouterState({ select: (s) => ({ path: s.location.pathname, search: s.location.search as CfoSearch }) });
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(reducer, undefined, () => ({
    ...initialState,
    ...filtersFromSearch(loc.search),
    // a workspace path implies its room even with no drill param
    ...(roomOriginForPath(loc.path) && !loc.search.drill ? { origin: roomOriginForPath(loc.path), nodes: [] } : {}),
    ...initial,
  }));
  // drill in the first URL has to be replayed before we may write the URL from state
  const [resolving, setResolving] = useState(() => Boolean(loc.search.drill));
  const applying = useRef(Boolean(loc.search.drill));
  const token = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;
  const locRef = useRef(loc);
  locRef.current = loc;

  /* URL → state: first load, shared link, browser Back/Forward, in-app links */
  const locKey = loc.path + JSON.stringify(loc.search);
  useEffect(() => {
    if (!APP_PATHS.includes(loc.path)) return;
    const st = stateRef.current;
    if (urlKey(loc.path, loc.search, st) === stateKey(st)) {
      if (applying.current) {
        applying.current = false;
        setResolving(false);
      }
      return;
    }
    const filters = filtersFromSearch(loc.search, st);
    const drill = loc.search.drill;
    const my = ++token.current;

    if (!drill) {
      applying.current = false;
      setResolving(false);
      dispatch({ type: "hydrate", state: { ...filters, origin: roomOriginForPath(loc.path), nodes: [], drawerOpen: false } });
      return;
    }
    // Back / breadcrumb: the new path is a prefix of the current one, no refetch needed
    const kept = filters.scenario === st.scenario && filters.period === st.period && filters.comparison === st.comparison ? prefixNodes(st, drill) : null;
    if (kept) {
      applying.current = false;
      setResolving(false);
      dispatch({ type: "hydrate", state: { ...filters, nodes: kept, drawerOpen: drawerAllowed({ origin: st.origin, nodes: kept }) } });
      return;
    }
    applying.current = true;
    setResolving(true);
    dispatch({ type: "hydrate", state: filters });
    resolveDrill(cfoApi, { scenario: filters.scenario, period: filters.period, comparison: filters.comparison, dataState: filters.dataState }, filters.horizon, drill).then((r) => {
      if (my !== token.current) return; // a newer URL superseded this one
      applying.current = false;
      setResolving(false);
      if (r) {
        dispatch({ type: "hydrate", state: { origin: r.origin, nodes: r.nodes, heroTab: r.heroTab ?? filters.heroTab, drawerOpen: drawerAllowed(r) } });
      } else {
        // the linked investigation no longer exists: land on its home (room or command center), same filters
        const room = roomForDrill(drill);
        const origin = room?.origin ?? null;
        dispatch({ type: "hydrate", state: { origin, nodes: [], drawerOpen: false } });
        navigate({ to: room?.path ?? "/", search: searchFromState({ ...stateRef.current, origin, nodes: [] }) as never, replace: true });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locKey]);

  /* state → URL: pushes a history entry per drill change, replaces for filter-only changes */
  useEffect(() => {
    if (applying.current) return;
    const { path, search } = locRef.current;
    if (!APP_PATHS.includes(path)) return;
    const want = routeFor(state);
    const same = urlKey(path, search, state) === stateKey(state);
    // the horizon is part of what a shared link must reproduce, so a bare horizon change is written to the URL too
    const horizonSynced = (search.horizon ?? initialState.horizon) === state.horizon;
    if (same && horizonSynced && searchIsComplete(search)) return;
    const prevDrill = search.drill ?? "";
    const nextDrill = encodeDrill(state) ?? "";
    // selecting an age bucket or quadrant in a room is a filter, not a step: replace instead of stacking history
    const ageOnly = want === path && ROOM_PATHS.includes(path) && isFilterSelectionOnly(prevDrill) && isFilterSelectionOnly(nextDrill);
    const push = !ageOnly && (path !== want || prevDrill !== nextDrill);
    navigate({ to: want, search: searchFromState(state) as never, replace: !push });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.period, state.comparison, state.scenario, state.heroTab, state.horizon, state.dataState, state.lens, state.origin, state.nodes]);

  const openOrigin = useCallback((origin: DrillOrigin, heroTab?: HeroTab) => dispatch({ type: "openOrigin", origin, heroTab }), []);
  const pushNode = useCallback((node: DrillNode) => dispatch({ type: "pushNode", node }), []);
  const closeDrawer = useCallback(() => dispatch({ type: "closeDrawer" }), []);
  const enterCreditors = useCallback((t?: CreditorsTarget) => dispatch({ type: "enterCreditors", age: t?.age, lens: t?.lens }), []);
  const enterRoom = useCallback((room: "profitability" | "cashroom") => dispatch({ type: "enterRoom", room }), []);
  const enterStore = useCallback((node: DrillNode) => dispatch({ type: "enterStore", node }), []);
  const openMovement = useCallback((node: DrillNode) => dispatch({ type: "openMovement", node }), []);
  const openCashDriver = useCallback((node: DrillNode) => dispatch({ type: "openCashDriver", node }), []);
  const selectFilter = useCallback((node: DrillNode | null) => dispatch({ type: "selectFilter", node }), []);
  const pushNodes = useCallback((nodes: DrillNode[]) => dispatch({ type: "pushNodes", nodes }), []);
  const goToCrumb = useCallback((c: Crumb) => dispatch(c.keep < 0 ? { type: "home" } : { type: "truncate", keep: c.keep }), []);
  const back = useCallback(() => {
    if (stateRef.current.nodes.length > 0) dispatch({ type: "truncate", keep: stateRef.current.nodes.length - 1 });
    else dispatch({ type: "home" });
  }, []);

  const queryCtx = useMemo(() => toQueryCtx(state), [state.scenario, state.period, state.comparison, state.dataState]);
  const crumbs = useMemo(() => crumbsFor(state), [state.origin, state.nodes]);

  const value = useMemo<CfoContextValue>(
    () => ({ state, ready: true, resolving, queryCtx, crumbs, dispatch, openOrigin, enterCreditors, enterRoom, enterStore, openMovement, openCashDriver, selectFilter, pushNodes, pushNode, goToCrumb, back, closeDrawer }),
    [state, resolving, queryCtx, crumbs, openOrigin, enterCreditors, enterRoom, enterStore, openMovement, openCashDriver, selectFilter, pushNodes, pushNode, goToCrumb, back, closeDrawer],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCfo(): CfoContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCfo must be used inside <CfoProvider>");
  return v;
}
