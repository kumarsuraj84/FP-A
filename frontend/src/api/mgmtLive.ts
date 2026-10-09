import type { MgmtAdjustments, MgmtEntity, MgmtHeader, MgmtMapping, MgmtPnl, MgmtPnlQuery, MgmtReconciliation, MgmtStores } from "@/types/mgmtLive";

/** Client for the read-only Management P&L API (same-origin through the dev proxy). The default ALWAYS calls the API. */
const BASE = (((import.meta.env.VITE_MGMT_API as string | undefined) ?? "/mgmt-api").trim() || "/mgmt-api").replace(/\/$/, "");

export class MgmtApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/**
 * DEV ONLY: `?data=fixture` on the page address serves the typed sample from test/mgmtFixture.ts while the API is being built.
 * It is compiled out of production builds (import.meta.env.DEV is false there) and is never the default.
 */
function fixtureRequested(): boolean {
  if (!import.meta.env.DEV || typeof window === "undefined") return false;
  try {
    if (new URLSearchParams(window.location.search).get("data") === "fixture") window.sessionStorage.setItem("mgmt-data", "fixture");
    return window.sessionStorage.getItem("mgmt-data") === "fixture";
  } catch {
    return false;
  }
}

async function get<T>(path: string, params: Record<string, string | number | boolean | undefined> = {}): Promise<T> {
  if (fixtureRequested()) {
    const { fixtureResponse } = await import("@/test/mgmtFixture");
    return fixtureResponse(path, params) as T;
  }
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  let res: Response;
  try {
    res = await fetch(`${BASE}/${path}${qs.size ? `?${qs}` : ""}`, { headers: { Accept: "application/json" } });
  } catch {
    throw new MgmtApiError("The Management P&L API did not respond", 0);
  }
  if (!res.ok) throw new MgmtApiError(res.status === 404 ? "No management P&L run is available" : res.status === 422 ? "That period is not valid" : `Management P&L API request failed (${res.status})`, res.status);
  return (await res.json()) as T;
}

export const liveMgmt = {
  current: () => get<MgmtHeader>("current"),
  pnl: (p: MgmtPnlQuery) => get<MgmtPnl>("pnl", { from_month: p.from_month, to_month: p.to_month, include_proposed: p.include_proposed, entity: p.entity }),
  stores: (month: string | undefined, toMonth: string | undefined, entity: MgmtEntity) => get<MgmtStores>("stores", { month, to_month: toMonth, entity }),
  reconciliation: (from: string | undefined, to: string | undefined, entity: MgmtEntity) => get<MgmtReconciliation>("reconciliation", { from_month: from, to_month: to, entity }),
  adjustments: () => get<MgmtAdjustments>("adjustments"),
  mapping: () => get<MgmtMapping>("mapping"),
};
