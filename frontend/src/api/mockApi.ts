import type { CfoApi, DataStateId, Envelope, FreshnessInfo, QueryCtx } from "@/types/cfo";
import {
  buildActions,
  buildForecast,
  buildLiquidity,
  buildPulse,
  buildRisks,
  buildWorkingCapital,
  cashBridge,
  profitBridge,
  workingCapitalBridge,
} from "@/mocks/builders";
import { buildDrill, buildLedger, buildProfile, buildVoucher } from "@/mocks/drill";
import { buildCashRoom } from "@/mocks/cash";
import { buildProfitPortfolio, buildStoreWorkspace } from "@/mocks/profitability";
import { buildAbnormal, buildConcentration, buildCreditorsOverview, buildMigration, buildVendorProfile } from "@/mocks/creditors";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 500) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const LIVE_AS_OF = "2026-10-03T06:00:00+05:30";
const STALE_AS_OF = "2026-09-30T23:00:00+05:30";
export const UNAVAILABLE_REASON = "Awaiting finance mapping";

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));
const latency = (state: DataStateId) => (state === "live" ? 140 : 220);

/** Applies the simulated data state to any payload. */
async function respond<T>(ctx: QueryCtx, build: () => T): Promise<Envelope<T>> {
  await delay(latency(ctx.dataState));
  switch (ctx.dataState) {
    case "error":
      throw new ApiError("Finance service returned an error (simulated)", 502);
    case "unavailable":
      return { status: "unavailable", reason: UNAVAILABLE_REASON, asOf: LIVE_AS_OF };
    case "empty":
      return { status: "empty", reason: "No records for this selection", asOf: LIVE_AS_OF };
    case "stale":
      return { status: "stale", data: build(), asOf: STALE_AS_OF, staleSince: STALE_AS_OF, reason: "Last successful refresh 30 Sep 2026" };
    default:
      return { status: "ok", data: build(), asOf: LIVE_AS_OF };
  }
}

export const mockApi: CfoApi = {
  async getFreshness(ctx): Promise<FreshnessInfo> {
    await delay(60);
    if (ctx.dataState === "stale") return { asOf: STALE_AS_OF, stale: true, label: "Stale · last refresh 30 Sep 2026, 23:00 IST" };
    if (ctx.dataState === "unavailable") return { asOf: LIVE_AS_OF, stale: true, label: "Unavailable · awaiting finance mapping" };
    return { asOf: LIVE_AS_OF, stale: false, label: "Data as of 03 Oct 2026, 06:00 IST" };
  },
  getPulse: (ctx) => respond(ctx, () => buildPulse(ctx)),
  getBridge: (ctx, tab) => respond(ctx, () => (tab === "profit" ? profitBridge(ctx) : tab === "cash" ? cashBridge(ctx) : workingCapitalBridge(ctx))),
  getLiquidity: (ctx, horizon) => respond(ctx, () => buildLiquidity(ctx, horizon)),
  getWorkingCapital: (ctx) => respond(ctx, () => buildWorkingCapital(ctx)),
  getRisks: (ctx) => respond(ctx, () => buildRisks(ctx)),
  getActions: (ctx) => respond(ctx, () => buildActions(ctx)),
  getForecast: (ctx) => respond(ctx, () => buildForecast(ctx)),
  getDrillView: (ctx, origin, nodes) => respond(ctx, () => buildDrill(ctx, origin, nodes)),
  getLedger: (ctx, origin, nodes) => respond(ctx, () => buildLedger(ctx, origin, nodes)),
  getVoucher: (ctx, voucherId, amount) => respond(ctx, () => buildVoucher(ctx, voucherId, amount)),
  getEntityProfile: (ctx, origin, nodes) => respond(ctx, () => buildProfile(ctx, origin, nodes)),
  getCreditors: (ctx) => respond(ctx, () => buildCreditorsOverview(ctx)),
  getAgeingMigration: (ctx) => respond(ctx, () => buildMigration(ctx)),
  getVendorConcentration: (ctx, filter) => respond(ctx, () => buildConcentration(ctx, filter)),
  getAbnormalBalances: (ctx) => respond(ctx, () => buildAbnormal(ctx)),
  getVendorProfile: (ctx, vendorId) =>
    respond(ctx, () => {
      const p = buildVendorProfile(ctx, vendorId);
      if (!p) throw new ApiError(`Vendor ${vendorId} not found`, 404);
      return p;
    }),
  getProfitPortfolio: (ctx) => respond(ctx, () => buildProfitPortfolio(ctx)),
  getStoreWorkspace: (ctx, storeId) =>
    respond(ctx, () => {
      const w = buildStoreWorkspace(ctx, storeId);
      if (!w) throw new ApiError(`Store ${storeId} not found`, 404);
      return w;
    }),
  getCashRoom: (ctx, horizon) => respond(ctx, () => buildCashRoom(ctx, horizon)),
};
