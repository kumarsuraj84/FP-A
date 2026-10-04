import type { AgeBucketRow, ControlTally, DueStateRow, ItemPage, LedgerRow, LiveSummary, LiveVendor, RunHeader, RunStatus, VendorPage } from "@/types/creditorsLive";
import type { AgeFilter, BucketId } from "@/types/creditors";

/**
 * Client for the read-only Creditors API (the verified FP&A mart). Only `/creditors` uses it; every other module stays on its demo service.
 * The base path is same-origin: the dev server proxies it to the API and adds the Finance bearer token SERVER-SIDE, so no token ever
 * reaches the browser bundle. If Finance access is not available the vendor routes fall back to the masked ones (vendor_ref only).
 */
const BASE = (((import.meta.env.VITE_CREDITORS_API as string | undefined) ?? "/creditors-api").trim() || "/creditors-api").replace(/\/$/, "");

export class LiveApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const res = await fetch(`${BASE}/${path}${qs.size ? `?${qs}` : ""}`, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new LiveApiError(res.status === 404 ? "No verified creditor run is available" : `Creditors API request failed (${res.status})`, res.status);
  return (await res.json()) as T;
}

/** Finance route first (names); masked route if Finance access is not granted here (401 / 503) so the page still works, with vendor_ref only. */
async function named<T extends { named?: boolean }>(runPath: string, path: string, params: Record<string, string | number | undefined>): Promise<T> {
  try {
    const r = await get<T>(`runs/${runPath}/finance/${path}`, params);
    return { ...r, named: true };
  } catch (e) {
    if (!(e instanceof LiveApiError) || (e.status !== 401 && e.status !== 503)) throw e;
    const { q: _q, ...rest } = params;
    const r = await get<T>(`runs/${runPath}/${path}`, rest);
    return { ...r, named: false };
  }
}

export const liveCreditors = {
  current: () => get<RunHeader>("current"),
  status: (run: string) => get<RunStatus>(`runs/${run}`),
  summary: (run: string) => get<LiveSummary>(`runs/${run}/summary`),
  documentAge: async (run: string) => (await get<{ buckets: AgeBucketRow[] }>(`runs/${run}/document-age`)).buckets,
  dueStatus: async (run: string) => (await get<{ states: DueStateRow[] }>(`runs/${run}/due-status`)).states,
  ledgers: async (run: string) => (await get<{ ledgers: LedgerRow[] }>(`runs/${run}/ledgers`)).ledgers,
  controls: (run: string) => get<ControlTally>(`runs/${run}/controls`),
  vendors: (run: string, p: { cohort?: string; sort?: string; order?: "asc" | "desc"; limit?: number; offset?: number; q?: string; ledger_code?: string }) =>
    named<VendorPage>(`${run}`, "vendors", { limit: 100, ...p }),
  vendor: async (run: string, ref: string): Promise<{ vendor: LiveVendor; named: boolean }> => {
    const r = await named<{ vendor: LiveVendor; named: boolean }>(run, `vendors/${encodeURIComponent(ref)}`, {});
    return { vendor: r.vendor, named: r.named };
  },
  items: (run: string, ref: string, p: { drcr?: "Cr" | "Dr"; limit?: number; offset?: number } = {}) => named<ItemPage>(run, `vendors/${encodeURIComponent(ref)}/items`, { limit: 500, ...p }),
};

/* ───────────── presentation helpers (display only: the API values stay exact text) ───────────── */

/** ₹ Crore for display from exact decimal text. */
export const toCr = (m: string | null | undefined): number | null => (m === null || m === undefined || m === "" ? null : Number(m) / 1e7);

/** Exact rupees (two decimals, Indian grouping) from decimal text. */
export function fmtRupees(m: string | null | undefined): string {
  if (m === null || m === undefined || m === "") return "—";
  const n = Number(m);
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? "−" : ""}₹${s}`;
}

/** Absolute value of decimal text (the mart stores Cr as negative; the page shows the side in its own column). */
export const absText = (m: string): string => (m.startsWith("-") ? m.slice(1) : m);

export const num = (m: string | number | null | undefined): number => (m === null || m === undefined ? 0 : Number(m));

export const vendorLabel = (v: Pick<LiveVendor, "vendor_ref" | "vendor_name">): string => v.vendor_name?.trim() || `Vendor ${v.vendor_ref}`;

/* ───────────── room filter ⇄ API vocabulary ───────────── */

export const BUCKET_TO_API: Record<BucketId, string> = { b0_30: "D0_30", b31_60: "D31_60", b61_90: "D61_90", b91_180: "D91_180", b181_365: "D181_365", b365p: "D365_PLUS" };
export const API_TO_BUCKET: Record<string, BucketId> = Object.fromEntries(Object.entries(BUCKET_TO_API).map(([k, v]) => [v, k as BucketId]));

/** The `cohort` the vendor list is ranked by for a room filter; undefined = the whole credit book. */
export function cohortFor(f: AgeFilter): string | undefined {
  if (f === "all") return undefined;
  if (f in BUCKET_TO_API) return BUCKET_TO_API[f as BucketId];
  if (f === "overdue") return "past_due"; // legacy link ids from the demo Command Center
  if (f === "current") return "not_yet_due";
  return f; // gt90, gt180, past_due, not_yet_due, due_unavailable, due_invalid
}
