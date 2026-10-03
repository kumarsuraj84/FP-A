import type { CfoApi } from "@/types/cfo";
import { createHttpApi } from "./httpApi";
import { mockApi } from "./mockApi";

const base = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "").trim();

/** Single switch point: components only ever see the CfoApi interface. */
export const cfoApi: CfoApi = base ? createHttpApi(base) : mockApi;
export const isMockApi = !base;
export { ApiError } from "./mockApi";
