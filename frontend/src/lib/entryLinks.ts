/**
 * URL state of the voucher drill (`/entry`, `/entry/list`, `/entry/till`).
 *
 * Everything needed to reproduce a page is in its URL, so a link can be shared or refreshed. Amounts are NOT in the URL: a link is resolved
 * by asking the API again. `trail` is the way back: the pages the user came through, oldest first, each as [label, href] where href is
 * that page's own URL (without its trail). Hrefs are same-app paths only: anything else is dropped, so a crafted link cannot send the user off-site.
 * (The router's default search parser turns numeric text into numbers and JSON text into arrays: every reader here coerces.)
 */

export interface TrailItem {
  l: string;
  h: string;
}

export type EntrySrc = "creditors" | "pnl" | "cash";

export interface EntryParams {
  ref?: string;
  /** creditors open item (`I<postcode>`), when the voucher was reached from a bill: asks the API for the link evidence */
  bill?: string;
  trail: TrailItem[];
}

export interface ListParams {
  site?: string;
  glcode?: string;
  from_month?: string;
  to_month?: string;
  from_date?: string;
  to_date?: string;
  basis: "all" | "posted";
  offset: number;
  /** what the list is about, for the heading ("Salary · Rohini") */
  title?: string;
  trail: TrailItem[];
}

export interface TillParams {
  site?: string;
  /** store name for the heading, when the page that links here knows it */
  name?: string;
  trail: TrailItem[];
}

const MAX_TRAIL = 5;

/** A same-app path (+ query) only. */
export function safePath(h: unknown): string | undefined {
  if (typeof h !== "string" || h.length === 0 || h.length > 1800) return undefined;
  if (!h.startsWith("/") || h.startsWith("//") || h.includes("\\") || /[\u0000-\u001f]/.test(h)) return undefined;
  return h;
}

function parseTrail(raw: unknown): TrailItem[] {
  let v: unknown = raw;
  if (typeof v === "string") {
    try {
      v = JSON.parse(v);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(v)) return [];
  const out: TrailItem[] = [];
  for (const x of v.slice(0, MAX_TRAIL)) {
    const l = typeof x?.l === "string" ? x.l.slice(0, 120) : "";
    const h = safePath(x?.h);
    if (l && h) out.push({ l, h });
  }
  return out;
}

const text = (v: unknown, max = 64): string | undefined => (v === undefined || v === null || v === "" ? undefined : String(v).slice(0, max));
const id = (v: unknown): string | undefined => {
  const s = text(v);
  return s && /^[A-Za-z0-9_-]+$/.test(s) ? s : undefined;
};
const month = (v: unknown): string | undefined => {
  const s = text(v, 7);
  return s && /^\d{4}-(0[1-9]|1[0-2])$/.test(s) ? s : undefined;
};
const day = (v: unknown): string | undefined => {
  const s = text(v, 10);
  return s && /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : undefined;
};

export function parseEntrySearch(raw: Record<string, unknown>): EntryParams {
  return { ref: id(raw.ref), bill: id(raw.bill), trail: parseTrail(raw.trail) };
}

export function parseListSearch(raw: Record<string, unknown>): ListParams {
  const offset = Number(raw.offset);
  return {
    site: id(raw.site),
    glcode: id(raw.glcode),
    from_month: month(raw.from_month),
    to_month: month(raw.to_month),
    from_date: day(raw.from_date),
    to_date: day(raw.to_date),
    basis: raw.basis === "posted" ? "posted" : "all",
    offset: Number.isFinite(offset) && offset > 0 ? Math.floor(offset) : 0,
    title: text(raw.title, 160),
    trail: parseTrail(raw.trail),
  };
}

export function parseTillSearch(raw: Record<string, unknown>): TillParams {
  return { site: id(raw.site), name: text(raw.name, 80), trail: parseTrail(raw.trail) };
}

function qs(o: Record<string, string | number | undefined | null | TrailItem[]>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) {
      if (v.length) p.set(k, JSON.stringify(v));
    } else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Where the user is now, to hand to the next page as one more step of the way back. `here` is the current page's own href WITHOUT trail. */
export function pushTrail(trail: TrailItem[], label: string, here: string): TrailItem[] {
  const h = safePath(here);
  return h ? [...trail, { l: label, h }].slice(-MAX_TRAIL) : trail;
}

/** The current location with its `trail` removed (what a child page records as "back to here"). */
export function hereWithoutTrail(href: string): string {
  const i = href.indexOf("?");
  if (i < 0) return href;
  const p = new URLSearchParams(href.slice(i + 1));
  p.delete("trail");
  const s = p.toString();
  return s ? `${href.slice(0, i)}?${s}` : href.slice(0, i);
}

/** Open a voucher. `trail` already ends with the page the user is leaving. */
export const entryHref = (ref: string, trail: TrailItem[] = [], bill?: string) => `/entry${qs({ ref, bill, trail })}`;

export type LedgerListQuery = Partial<Omit<ListParams, "trail" | "offset" | "basis">> & { basis?: "all" | "posted"; offset?: number };
export const ledgerListHref = (q: LedgerListQuery, trail: TrailItem[] = []) =>
  `/entry/list${qs({ site: q.site, glcode: q.glcode, from_month: q.from_month, to_month: q.to_month, from_date: q.from_date, to_date: q.to_date, basis: q.basis && q.basis !== "all" ? q.basis : undefined, offset: q.offset || undefined, title: q.title, trail })}`;

export const tillHref = (site: string | number, trail: TrailItem[] = [], name?: string | null) => `/entry/till${qs({ site, name: name ?? undefined, trail })}`;

/** The Cash Drawer ledger: the till. */
export const TILL_LEDGER = "1000000008";

/** The `back` href for a crumb: that page with the trail up to (not including) it. */
export function crumbHref(trail: TrailItem[], i: number): string {
  const item = trail[i];
  const earlier = trail.slice(0, i);
  const [path, query = ""] = item.h.split("?");
  const p = new URLSearchParams(query);
  p.delete("trail");
  if (earlier.length) p.set("trail", JSON.stringify(earlier));
  const s = p.toString();
  return s ? `${path}?${s}` : path;
}
