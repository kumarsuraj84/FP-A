import type { PnlComparisonResponse, PnlExceptions, ExpenseException, PnlExpenses, PnlHeatmap, PnlPeers, PnlPivot, PnlPivotLedgers, PnlQuality, RevenueException } from "@/types/pnlReview";
import type { PnlGroupLedgers, PnlHeader, PnlHierarchy, PnlQuery, PnlReconciliation, PnlStore, PnlStorePage, PnlSummary, PnlTrend } from "@/types/pnlLive";

/** Client for the read-only store P&L actuals API (same-origin through the dev proxy). Only `/pnl` uses it. */
const BASE = (((import.meta.env.VITE_PNL_API as string | undefined) ?? "/pnl-api").trim() || "/pnl-api").replace(/\/$/, "");

export class PnlApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const res = await fetch(`${BASE}/${path}${qs.size ? `?${qs}` : ""}`, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new PnlApiError(res.status === 404 ? "No verified P&L run is available" : res.status === 422 ? "That period or filter is not valid" : `P&L API request failed (${res.status})`, res.status);
  return (await res.json()) as T;
}

const q = (p: PnlQuery) => ({ from_month: p.from_month, to_month: p.to_month, basis: p.basis, region: p.region, cluster: p.cluster, state: p.state, vintage: p.vintage, status: p.status });

export const livePnl = {
  current: () => get<PnlHeader>("current"),
  summary: (run: string, p: PnlQuery) => get<PnlSummary>(`runs/${run}/summary`, q(p)),
  trend: (run: string, p: PnlQuery) => get<PnlTrend>(`runs/${run}/trend`, q(p)),
  stores: (run: string, p: PnlQuery, o: { sort: string; order: "asc" | "desc"; limit: number; offset?: number; min_revenue?: number }) => get<PnlStorePage>(`runs/${run}/stores`, { ...q(p), ...o }),
  store: (run: string, site: string, p: PnlQuery) => get<PnlStore>(`runs/${run}/stores/${encodeURIComponent(site)}`, { from_month: p.from_month, to_month: p.to_month, basis: p.basis }),
  ledgers: (run: string, site: string, group: string, p: PnlQuery) => get<PnlGroupLedgers>(`runs/${run}/stores/${encodeURIComponent(site)}/groups/${encodeURIComponent(group)}/ledgers`, { from_month: p.from_month, to_month: p.to_month, basis: p.basis }),
  hierarchy: (run: string, p: PnlQuery) => get<PnlHierarchy>(`runs/${run}/hierarchy`, { from_month: p.from_month, to_month: p.to_month, basis: p.basis }),
  reconciliation: (run: string, p: PnlQuery) => get<PnlReconciliation>(`runs/${run}/reconciliation`, { from_month: p.from_month, to_month: p.to_month, basis: p.basis }),
  // the review layer
  pivot: (run: string, p: PnlQuery, mode: "stores" | "company") => get<PnlPivot>(`runs/${run}/pivot`, { ...q(p), mode }),
  pivotLedgers: (run: string, p: PnlQuery, mode: "stores" | "company", group: string) => get<PnlPivotLedgers>(`runs/${run}/pivot`, { ...q(p), mode, group }),
  comparison: (run: string, p: PnlQuery, mode: "stores" | "company") => get<PnlComparisonResponse>(`runs/${run}/comparison`, { ...q(p), mode }),
  expenses: (run: string, p: PnlQuery) => get<PnlExpenses>(`runs/${run}/expenses`, q(p)),
  heatmap: (run: string, p: PnlQuery, sort: string, minRevenueCr?: number) => get<PnlHeatmap>(`runs/${run}/heatmap`, { ...q(p), sort, limit: 500, min_revenue_cr: minRevenueCr }),
  peers: (run: string, site: string, p: PnlQuery) => get<PnlPeers>(`runs/${run}/stores/${encodeURIComponent(site)}/peers`, { from_month: p.from_month, to_month: p.to_month, basis: p.basis }),
  expenseExceptions: (run: string, p: PnlQuery) => get<PnlExceptions<ExpenseException>>(`runs/${run}/exceptions/expenses`, { ...q(p), limit: 500 }),
  revenueExceptions: (run: string, p: PnlQuery) => get<PnlExceptions<RevenueException>>(`runs/${run}/exceptions/revenue`, { ...q(p), limit: 500 }),
  quality: (run: string, p: PnlQuery) => get<PnlQuality>(`runs/${run}/quality`, { from_month: p.from_month, to_month: p.to_month, basis: p.basis }),
};
