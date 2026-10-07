import { useQuery } from "@tanstack/react-query";
import { livePnl } from "./pnlLive";
import type { PnlQuery } from "@/types/pnlLive";

export const usePnlRun = () => useQuery({ queryKey: ["pnl", "run"], queryFn: livePnl.current, retry: false, staleTime: 60_000 });

/** A query over the serving run: waits for the run, and shows the run's own failure if there is none. */
function useRunQuery<T>(key: string, fn: (run: string) => Promise<T>, extra: unknown[] = [], enabledExtra = true) {
  const run = usePnlRun();
  const id = run.data?.run_id;
  const q = useQuery({ queryKey: ["pnl", key, id, ...extra], queryFn: () => fn(id as string), enabled: !!id && enabledExtra, retry: false, staleTime: 60_000, placeholderData: (prev) => prev });
  if (run.isError) return { ...q, isPending: false, isError: true, error: run.error, data: undefined, refetch: run.refetch } as typeof q;
  if (run.isPending) return { ...q, isPending: true } as typeof q;
  return q;
}

export const usePnlSummary = (p: PnlQuery) => useRunQuery("summary", (run) => livePnl.summary(run, p), [p]);
export const usePnlTrend = (p: PnlQuery) => useRunQuery("trend", (run) => livePnl.trend(run, p), [p]);
export const usePnlStores = (p: PnlQuery, sort: string, order: "asc" | "desc", limit: number, minRevenueRupees?: number) =>
  useRunQuery("stores", (run) => livePnl.stores(run, p, { sort, order, limit, min_revenue: minRevenueRupees }), [p, sort, order, limit, minRevenueRupees]);
export const usePnlStore = (site: string | null, p: PnlQuery) => useRunQuery("store", (run) => livePnl.store(run, site as string, p), [site, p.from_month, p.to_month, p.basis], !!site);
export const usePnlLedgers = (site: string | null, group: string | null, p: PnlQuery) =>
  useRunQuery("ledgers", (run) => livePnl.ledgers(run, site as string, group as string, p), [site, group, p.from_month, p.to_month, p.basis], !!site && !!group);
export const usePnlHierarchy = (p: PnlQuery) => useRunQuery("hierarchy", (run) => livePnl.hierarchy(run, p), [p.from_month, p.to_month, p.basis]);
export const usePnlPivot = (p: PnlQuery, mode: "stores" | "company") => useRunQuery("pivot", (run) => livePnl.pivot(run, p, mode), [p, mode]);
export const usePnlPivotLedgers = (p: PnlQuery, mode: "stores" | "company", group: string | null) =>
  useRunQuery("pivotLedgers", (run) => livePnl.pivotLedgers(run, p, mode, group as string), [p, mode, group], !!group);
export const usePnlComparison = (p: PnlQuery, mode: "stores" | "company") => useRunQuery("comparison", (run) => livePnl.comparison(run, p, mode), [p, mode]);
export const usePnlExpenses = (p: PnlQuery) => useRunQuery("expenses", (run) => livePnl.expenses(run, p), [p]);
export const usePnlHeatmap = (p: PnlQuery, sort: string, minRevenueCr?: number) => useRunQuery("heatmap", (run) => livePnl.heatmap(run, p, sort, minRevenueCr), [p, sort, minRevenueCr]);
export const usePnlPeers = (site: string | null, p: PnlQuery) => useRunQuery("peers", (run) => livePnl.peers(run, site as string, p), [site, p.from_month, p.to_month, p.basis], !!site);
export const usePnlExpenseExceptions = (p: PnlQuery) => useRunQuery("exc-exp", (run) => livePnl.expenseExceptions(run, p), [p]);
export const usePnlRevenueExceptions = (p: PnlQuery) => useRunQuery("exc-rev", (run) => livePnl.revenueExceptions(run, p), [p]);
export const usePnlQuality = (p: PnlQuery) => useRunQuery("quality", (run) => livePnl.quality(run, p), [p.from_month, p.to_month, p.basis]);
export const usePnlReconciliation = (p: PnlQuery) => useRunQuery("recon", (run) => livePnl.reconciliation(run, p), [p.from_month, p.to_month, p.basis]);
