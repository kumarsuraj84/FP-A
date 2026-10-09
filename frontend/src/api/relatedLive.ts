import type { GlEntries, GlQuery, Intercompany, RelatedItems, RelatedSummary } from "@/types/relatedParty";

/** Client for the read-only Related Party API (same-origin through the dev proxy, which adds the Finance token server-side). Always calls the API. */
const BASE = (((import.meta.env.VITE_RELATED_API as string | undefined) ?? "/related-api").trim() || "/related-api").replace(/\/$/, "");

export class RelatedApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const res = await fetch(`${BASE}/${path}${qs.size ? `?${qs}` : ""}`, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new RelatedApiError(res.status === 401 || res.status === 503 ? "Finance access is required for Related Party Transactions" : `Related Party API request failed (${res.status})`, res.status);
  return (await res.json()) as T;
}

export const relatedLive = {
  summary: () => get<RelatedSummary>("summary"),
  intercompany: () => get<Intercompany>("intercompany"),
  glEntries: (q: GlQuery) => get<GlEntries>("gl-entries", { entity: q.entity, from_month: q.from_month, to_month: q.to_month, basis: q.basis, offset: q.offset || undefined, limit: 50 }),
  items: (subLedgerCode: number) => get<RelatedItems>("items", { sub_ledger_code: subLedgerCode, limit: 500 }),
};
