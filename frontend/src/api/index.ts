import type { CfoApi } from "@/types/cfo";
import { createHttpApi } from "./httpApi";
import { createLiveCfoApi } from "./liveCfoApi";
import { mockApi } from "./mockApi";

const base = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "").trim();
const mode = ((import.meta.env.VITE_CFO_DATA as string | undefined) ?? "").trim().toLowerCase();

/**
 * Single switch point: components only ever see the CfoApi interface.
 *  - default: REAL data, composed from the three verified read-only APIs (P&L, Creditors, Cash);
 *  - VITE_CFO_DATA=mock: the demo service (the only way back to demo data; with VITE_API_BASE_URL set it is the HTTP service instead);
 *  - VITE_CFO_DATA=http: the HTTP service at VITE_API_BASE_URL.
 */
export type CfoDataMode = "live" | "mock" | "http";
export const cfoDataMode: CfoDataMode = mode === "http" ? "http" : mode === "mock" ? (base ? "http" : "mock") : "live";

export const cfoApi: CfoApi = cfoDataMode === "http" ? createHttpApi(base) : cfoDataMode === "mock" ? mockApi : createLiveCfoApi();
export const isMockApi = cfoDataMode === "mock";
export const isLiveCfo = cfoDataMode === "live";
export { ApiError } from "./mockApi";
