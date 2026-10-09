import { DASH, fmtPct } from "@/lib/format";

/** Display helpers for the Management P&L pages. Money arrives as INR Cr numbers; null is "no value" and always shows an em dash. */

/** Crore with two decimals and no symbol: the table header says INR Cr. Tiny non-zero values keep their sign. */
export function cr2(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  if (Math.abs(v) < 0.005) return v < 0 ? "−0.00" : "0.00";
  return `${v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** A signed variance: a plus sign on positives so the direction is never a guess. */
export function cr2s(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v > 0.005 ? `+${cr2(v)}` : cr2(v);
}

/** Three decimals for variances that are a few paise (override differences). */
export function cr3(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return `${v < 0 ? "−" : v > 0 ? "+" : ""}${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 3, maximumFractionDigits: 3 })}`;
}

export const pct1 = (v: number | null | undefined) => (v === null || v === undefined || Number.isNaN(v) ? DASH : fmtPct(v, { digits: 1 }));

export const monthShort = (m: string) => new Date(`${m.slice(0, 7)}-01T00:00:00Z`).toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });

export const toneOf = (v: number | null | undefined) => (v !== null && v !== undefined && v < 0 ? "tone-bad" : "");

/** Why a figure is blank, for the title of the em dash. */
export function dashReason(kind: "pct" | "value", detail?: string): string {
  if (detail) return detail;
  return kind === "pct" ? "Not computed: total income is zero or missing for this period" : "The API returned no value for this period";
}

/** One CSV field, quoted. */
export const csvField = (x: unknown) => `"${String(x ?? "").replace(/"/g, '""')}"`;

export function downloadCsv(name: string, rows: unknown[][]) {
  const url = URL.createObjectURL(new Blob([rows.map((r) => r.map(csvField).join(",")).join("\n")], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** The blended DC+HO rate as a percentage: the API gives a fraction (0.0503); a value above 1 is taken to be a percentage already. */
export const ratePct = (rate: number) => (rate > 1 ? rate : rate * 100);
