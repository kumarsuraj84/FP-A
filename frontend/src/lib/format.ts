import type { MetricValue } from "@/types/cfo";

export const DASH = "—";

/** ₹ Crore with Indian-style compaction; below ₹0.10 Cr shows lakhs (so −0.84 Cr reads as −₹0.84 Cr, not 84 L). */
export function fmtCr(v: number | null | undefined, opts: { signed?: boolean; plain?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const a = Math.abs(v);
  const sign = v < 0 ? "−" : opts.signed && v > 0 ? "+" : "";
  const big = a >= 0.1 || a === 0;
  const num = big
    ? a.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : (a * 100).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return opts.plain ? `${sign}${num}` : `${sign}₹${num} ${big ? "Cr" : "L"}`;
}

export function fmtPct(v: number | null | undefined, opts: { signed?: boolean; digits?: number } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const sign = v < 0 ? "−" : opts.signed && v > 0 ? "+" : "";
  return `${sign}${Math.abs(v).toFixed(opts.digits ?? 1)}%`;
}

export function fmtBps(v: number | null | undefined): string {
  if (v === null || v === undefined) return DASH;
  return `${v < 0 ? "−" : v > 0 ? "+" : ""}${Math.abs(v)} bps`;
}

/** Absolute rupees with Indian digit grouping (ledger / voucher level). */
export function fmtRs(v: number | null | undefined): string {
  if (v === null || v === undefined) return DASH;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

export function fmtDate(iso: string): string {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00Z" : ""));
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
}

export function metricText(m: MetricValue, f: (n: number) => string): string {
  return m.value === null ? DASH : f(m.value);
}
