import type { CfoApi, Envelope, FreshnessInfo, QueryCtx } from "@/types/cfo";
import { ApiError } from "./mockApi";

/**
 * HTTP implementation of the same CfoApi contract. Unused until VITE_API_BASE_URL is set.
 * Every method maps to a read-only endpoint on the FP&A API (PostgreSQL finance mart).
 */
export function createHttpApi(baseUrl: string): CfoApi {
  const base = baseUrl.replace(/\/$/, "");

  async function get<T>(path: string, ctx: QueryCtx, extra: Record<string, string | number | null> = {}): Promise<T> {
    const url = new URL(`${base}/${path}`);
    url.searchParams.set("scenario", ctx.scenario);
    url.searchParams.set("period", ctx.period);
    url.searchParams.set("comparison", ctx.comparison);
    for (const [k, v] of Object.entries(extra)) if (v !== null) url.searchParams.set(k, String(v));
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new ApiError(`Request failed (${res.status})`, res.status);
    return (await res.json()) as T;
  }

  // Read-only query that needs a body (the drill path). Does not mutate anything.
  async function query<T>(path: string, ctx: QueryCtx, body: object): Promise<T> {
    const res = await fetch(`${base}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ ctx, ...body }),
    });
    if (!res.ok) throw new ApiError(`Request failed (${res.status})`, res.status);
    return (await res.json()) as T;
  }

  return {
    getFreshness: (ctx) => get<FreshnessInfo>("cfo/freshness", ctx),
    getPulse: (ctx) => get<Envelope<never>>("cfo/pulse", ctx) as never,
    getBridge: (ctx, tab) => get("cfo/bridge", ctx, { tab }),
    getLiquidity: (ctx, horizon) => get("cfo/liquidity", ctx, { horizon }),
    getWorkingCapital: (ctx) => get("cfo/working-capital", ctx),
    getRisks: (ctx) => get("cfo/risks", ctx),
    getActions: (ctx) => get("cfo/actions", ctx),
    getForecast: (ctx) => get("cfo/forecast", ctx),
    getDrillView: (ctx, origin, nodes) => query("cfo/drill", ctx, { origin, nodes }),
    getLedger: (ctx, origin, nodes) => query("cfo/ledger", ctx, { origin, nodes }),
    getVoucher: (ctx, voucherId, amount) => get("cfo/voucher", ctx, { voucherId, amount }),
    getEntityProfile: (ctx, origin, nodes) => query("cfo/profile", ctx, { origin, nodes }),
    getCreditors: (ctx) => get("cfo/creditors", ctx),
    getAgeingMigration: (ctx) => get("cfo/creditors/migration", ctx),
    getVendorConcentration: (ctx, filter) => get("cfo/creditors/concentration", ctx, { age: filter }),
    getAbnormalBalances: (ctx) => get("cfo/creditors/abnormal", ctx),
    getVendorProfile: (ctx, vendorId) => get("cfo/creditors/vendor", ctx, { vendorId }),
    getProfitPortfolio: (ctx) => get("cfo/profitability", ctx),
    getStoreWorkspace: (ctx, storeId) => get("cfo/profitability/store", ctx, { storeId }),
    getCashRoom: (ctx, horizon) => get("cfo/cash", ctx, { horizon }),
  };
}
