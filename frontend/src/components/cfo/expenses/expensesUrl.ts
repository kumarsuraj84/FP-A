import { useNavigate, useRouterState } from "@tanstack/react-router";
import type { ExpMode, ExpQuery, ExpScope, SiteEntity } from "@/types/expensesLive";
import { parseEntity } from "../mgmt/mgmtEntity";
import { lastCompleteMonth } from "../mgmt/mgmtMonths";

/**
 * URL state of the Store / DC Expense pages, so a view can be shared and survives a refresh:
 *   entity=subco|holdco (absent = consolidated, DC page only)  from / to = YYYY-MM  mode=book|adjustment (absent = total)
 *   head = the expense head open in the drill, gl = a ledger code opened by site, site / se / sn = a site (code, entity, name) opened in the drill.
 * Anything unknown is dropped, never thrown.
 */
export interface ExpSearch {
  entity?: "subco" | "holdco";
  from?: string;
  to?: string;
  mode?: "book" | "adjustment";
  head?: string;
  /** numbers, not strings: the router writes a numeric-looking string into the address with quotes */
  gl?: number;
  site?: number;
  se?: SiteEntity;
  sn?: string;
}

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

const pick = (v: unknown, re: RegExp): string | undefined => {
  const s = v === undefined || v === null ? "" : String(v);
  return re.test(s) ? s : undefined;
};

export function validateExpSearch(raw: Record<string, unknown>): ExpSearch {
  const e = parseEntity(raw.entity);
  const out: ExpSearch = {};
  if (e !== "consolidated") out.entity = e;
  const from = pick(raw.from, MONTH);
  const to = pick(raw.to, MONTH);
  if (from) out.from = from;
  if (to) out.to = to;
  if (raw.mode === "book" || raw.mode === "adjustment") out.mode = raw.mode;
  const head = pick(raw.head, /^[a-z_]{1,24}$/);
  if (head) out.head = head;
  const gl = pick(raw.gl, /^\d{1,15}$/);
  if (gl) out.gl = Number(gl);
  const site = pick(raw.site, /^\d{1,9}$/);
  if (site) out.site = Number(site);
  if (raw.se === "SUBCO" || raw.se === "HOLDCO") out.se = raw.se;
  if (raw.sn !== undefined && raw.sn !== null && String(raw.sn)) out.sn = String(raw.sn).slice(0, 60);
  return out;
}

export const useExpSearch = (): ExpSearch => validateExpSearch(useRouterState({ select: (s) => s.location.search as Record<string, unknown> }));

/** Merge a patch into the page address (undefined removes a key). */
export function useSetExp() {
  const navigate = useNavigate();
  return (patch: Partial<Record<keyof ExpSearch, string | number | undefined>>) =>
    navigate({ search: ((p: Record<string, unknown>) => ({ ...p, ...patch })) as never });
}

export const modeOf = (s: ExpSearch): ExpMode => s.mode ?? "total";

/** FY year-to-date by default: from April of the financial year, through the LAST COMPLETE month (a partial current month is selectable but never the default). */
export function defaultPeriod(months: string[], asOf?: string | null): { from: string; to: string } {
  const last = lastCompleteMonth(months, asOf);
  if (!last) return { from: "", to: "" };
  const y = Number(last.slice(0, 4)) - (Number(last.slice(5, 7)) < 4 ? 1 : 0);
  const start = `${y}-04`;
  return { from: months.find((m) => m >= start) ?? months[0], to: last };
}

export function resolvePeriod(months: string[], s: ExpSearch, asOf?: string | null): { from: string; to: string } {
  const d = defaultPeriod(months, asOf);
  let from = s.from && months.includes(s.from) ? s.from : d.from;
  const to = s.to && months.includes(s.to) ? s.to : d.to;
  if (from > to) from = to;
  return { from, to };
}

export function queryOf(scope: ExpScope, entity: "consolidated" | "subco" | "holdco", months: string[], s: ExpSearch, asOf?: string | null): ExpQuery {
  const { from, to } = resolvePeriod(months, s, asOf);
  return { scope, entity, from_month: from, to_month: to };
}
