import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useState, type ReactNode } from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import type { DrillNode, DrillOrigin, HeroTab, QueryCtx } from "@/types/cfo";
import { STORAGE_KEY, crumbsFor, initialState, reducer, routeFor, toQueryCtx, type CfoAction, type CfoState, type Crumb } from "./cfoState";

interface CfoContextValue {
  state: CfoState;
  /** false until persisted filters have been restored (avoids double fetches on first paint) */
  ready: boolean;
  queryCtx: QueryCtx;
  crumbs: Crumb[];
  dispatch: (a: CfoAction) => void;
  openOrigin: (origin: DrillOrigin, heroTab?: HeroTab) => void;
  pushNode: (node: DrillNode) => void;
  goToCrumb: (crumb: Crumb) => void;
  back: () => void;
  closeDrawer: () => void;
}

const Ctx = createContext<CfoContextValue | null>(null);

export function CfoProvider({ children, initial }: { children: ReactNode; initial?: Partial<CfoState> }) {
  const [state, dispatch] = useReducer(reducer, { ...initialState, ...initial });
  const [ready, setReady] = useState(false);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  // restore persisted filters + drill context (survives reloads and deep-page round trips)
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw) dispatch({ type: "hydrate", state: JSON.parse(raw) as Partial<CfoState> });
    } catch {
      /* storage unavailable: start from defaults */
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* ignore */
    }
  }, [state, ready]);

  // state → URL
  const want = routeFor(state);
  useEffect(() => {
    if (!ready) return;
    if (pathname !== want && ["/", "/ledger", "/voucher", "/profile"].includes(pathname)) navigate({ to: want });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.nodes, state.origin, ready]);

  // URL → state (browser Back/Forward)
  useEffect(() => {
    if (!ready) return;
    if (["/", "/ledger", "/voucher", "/profile"].includes(pathname)) dispatch({ type: "syncRoute", path: pathname });
  }, [pathname, ready]);

  const openOrigin = useCallback((origin: DrillOrigin, heroTab?: HeroTab) => dispatch({ type: "openOrigin", origin, heroTab }), []);
  const pushNode = useCallback((node: DrillNode) => dispatch({ type: "pushNode", node }), []);
  const closeDrawer = useCallback(() => dispatch({ type: "closeDrawer" }), []);
  const goToCrumb = useCallback((c: Crumb) => dispatch(c.keep < 0 ? { type: "home" } : { type: "truncate", keep: c.keep }), []);
  const back = useCallback(() => {
    if (state.nodes.length > 0) dispatch({ type: "truncate", keep: state.nodes.length - 1 });
    else dispatch({ type: "home" });
  }, [state.nodes.length]);

  const queryCtx = useMemo(() => toQueryCtx(state), [state.scenario, state.period, state.comparison, state.dataState]);
  const crumbs = useMemo(() => crumbsFor(state), [state.origin, state.nodes]);

  const value = useMemo<CfoContextValue>(
    () => ({ state, ready, queryCtx, crumbs, dispatch, openOrigin, pushNode, goToCrumb, back, closeDrawer }),
    [state, ready, queryCtx, crumbs, openOrigin, pushNode, goToCrumb, back, closeDrawer],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCfo(): CfoContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCfo must be used inside <CfoProvider>");
  return v;
}
