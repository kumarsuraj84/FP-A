import type {
  BillLinkResponse,
  EntryResponse,
  EntryRunHeader,
  LedgerEntriesPage,
  LineDetailResponse,
  TillDaysResponse,
  TillStoresResponse,
} from "@/types/entryLive";

/**
 * Client for the read-only Entry API (voucher drill). Same-origin: the dev server proxies `/entry-api` to the API and adds the Finance bearer
 * token SERVER-SIDE for `/finance/` routes, so no token ever reaches the browser bundle. When Finance access is not granted (401 / 503) the
 * masked route is used instead (pseudonymous sub-ledger refs, no narration, no party name).
 */
const BASE = (((import.meta.env.VITE_ENTRY_API as string | undefined) ?? "/entry-api").trim() || "/entry-api").replace(/\/$/, "");

export class EntryApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

type Params = Record<string, string | number | undefined | null>;

async function get<T>(path: string, params: Params = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const res = await fetch(`${BASE}/${path}${qs.size ? `?${qs}` : ""}`, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    const msg =
      res.status === 404 ? (path === "current" ? "No verified entry run is available" : "That voucher or list was not found in this run")
      : res.status === 409 ? "The entry run and the page's run do not match; refresh the page"
      : res.status === 422 ? "That filter is not valid"
      : `Entry API request failed (${res.status})`;
    throw new EntryApiError(msg, res.status);
  }
  return (await res.json()) as T;
}

/** Finance route first (narration, party name); masked route if Finance access is not granted here, so the page still works. */
async function named<T>(runPath: string, path: string, params: Params = {}): Promise<T & { named: boolean }> {
  try {
    return { ...(await get<T>(`runs/${runPath}/finance/${path}`, params)), named: true };
  } catch (e) {
    if (!(e instanceof EntryApiError) || (e.status !== 401 && e.status !== 503)) throw e;
    return { ...(await get<T>(`runs/${runPath}/${path}`, params)), named: false };
  }
}

export interface LedgerEntriesQuery {
  /** HoldCo (Citykart Ventures) vouchers; absent = RETAIL (SubCo), the API default */
  entity?: "RETAIL" | "VENTURES";
  site?: string | number;
  glcode?: string | number;
  from_month?: string;
  to_month?: string;
  from_date?: string;
  to_date?: string;
  basis?: "all" | "posted";
  limit?: number;
  offset?: number;
}

export const liveEntry = {
  current: () => get<EntryRunHeader>("current"),
  entry: (run: string, ref: string, entity?: string) => named<EntryResponse>(run, `entry/${encodeURIComponent(ref)}`, { entity }),
  lineDetail: (run: string, ref: string, entity?: string) => named<LineDetailResponse>(run, `entry/${encodeURIComponent(ref)}/line-detail`, { entity }),
  ledgerEntries: (run: string, q: LedgerEntriesQuery) => named<LedgerEntriesPage>(run, "ledger-entries", { limit: 100, ...q }),
  billLink: (run: string, creditorsRun: string, itemRef: string) =>
    get<BillLinkResponse>(`runs/${run}/creditors/items/${encodeURIComponent(billKey(itemRef))}/link`, { creditors_run: creditorsRun }),
  tillStores: (run: string, cashRun: string) => get<TillStoresResponse>(`runs/${run}/till/stores`, { cash_run: cashRun }),
  tillDays: (run: string, cashRun: string, site: string | number) => get<TillDaysResponse>(`runs/${run}/till/stores/${encodeURIComponent(String(site))}/days`, { cash_run: cashRun }),
};

/** The creditors API names an open item `I<postcode>`; the entry link table is keyed by the bare postcode. */
export const billKey = (itemRef: string): string => (/^I\d+$/.test(itemRef) ? itemRef.slice(1) : itemRef);
