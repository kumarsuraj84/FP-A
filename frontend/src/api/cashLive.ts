import type { CashHeader, CashSummary, TillPage } from "@/types/cashLive";

/** Client for the read-only Cash API (same-origin through the dev proxy). Only `/cash` uses it. */
const BASE = (((import.meta.env.VITE_CASH_API as string | undefined) ?? "/cash-api").trim() || "/cash-api").replace(/\/$/, "");

export class CashApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const res = await fetch(`${BASE}/${path}${qs.size ? `?${qs}` : ""}`, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new CashApiError(res.status === 404 ? "No verified cash run is available" : `Cash API request failed (${res.status})`, res.status);
  return (await res.json()) as T;
}

export const liveCash = {
  current: () => get<CashHeader>("current"),
  summary: (run: string) => get<CashSummary>(`runs/${run}/summary`),
  stores: (run: string, p: { sort?: string; order?: "asc" | "desc"; limit?: number; offset?: number } = {}) => get<TillPage>(`runs/${run}/store-till`, { limit: 100, ...p }),
};
