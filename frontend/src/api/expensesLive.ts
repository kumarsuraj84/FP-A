import type { ExpExceptions, ExpLedgers, ExpQuery, ExpSites, ExpSummary, ExpTrend, SiteEntity } from "@/types/expensesLive";
import { MgmtApiError } from "./mgmtLive";

/** Client for the read-only Store / DC Expense API: the same `/mgmt-api` proxy as the Management P&L (it maps to /api/v1/mgmt, so `/mgmt-api/expenses/...`). */
const BASE = (((import.meta.env.VITE_MGMT_API as string | undefined) ?? "/mgmt-api").trim() || "/mgmt-api").replace(/\/$/, "");

async function get<T>(path: string, params: Record<string, string | number | boolean | undefined | null>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  let res: Response;
  try {
    res = await fetch(`${BASE}/expenses/${path}${qs.size ? `?${qs}` : ""}`, { headers: { Accept: "application/json" } });
  } catch {
    throw new MgmtApiError("The expense API did not respond", 0);
  }
  if (!res.ok) throw new MgmtApiError(res.status === 422 ? "That period or filter is not valid" : res.status === 503 ? "The expense review needs the gold source" : `Expense API request failed (${res.status})`, res.status);
  return (await res.json()) as T;
}

const base = (q: ExpQuery) => ({ scope: q.scope, entity: q.entity === "consolidated" ? undefined : q.entity, from_month: q.from_month, to_month: q.to_month });

export interface LedgersQuery extends ExpQuery {
  head?: string;
  site?: number;
  site_entity?: SiteEntity;
  glcode?: number;
}

export const liveExpenses = {
  summary: (q: ExpQuery) => get<ExpSummary>("summary", base(q)),
  trend: (q: ExpQuery) => get<ExpTrend>("trend", base(q)),
  sites: (q: ExpQuery, head?: string) => get<ExpSites>("sites", { ...base(q), head }),
  ledgers: (q: LedgersQuery) => get<ExpLedgers>("ledgers", { ...base(q), head: q.head, site: q.site, site_entity: q.site_entity?.toLowerCase(), glcode: q.glcode }),
  exceptions: (q: ExpQuery) => get<ExpExceptions>("exceptions", base(q)),
};
