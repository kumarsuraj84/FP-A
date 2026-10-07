import { DASH, fmtCr, fmtPct } from "@/lib/format";

/** Display helpers for the P&L review components. Every input is exact decimal text from the API; only the display converts it. */
export const crOf = (m: string | null | undefined): number | null => (m === null || m === undefined || m === "" ? null : Number(m) / 1e7);
export const cr = (m: string | null | undefined) => (m === null || m === undefined ? DASH : fmtCr(Number(m) / 1e7));
/** Crore with two decimals and no symbol: for dense tables whose header says ₹ Cr. */
export const cr2 = (m: string | null | undefined) => {
  if (m === null || m === undefined || m === "") return DASH;
  const v = Number(m) / 1e7;
  if (Math.abs(v) < 0.005 && v !== 0) return v < 0 ? "−0.00" : "0.00";
  return `${v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};
export const lakh = (m: string | null | undefined) => (m === null || m === undefined ? DASH : `${Number(m) < 0 ? "−" : ""}₹${(Math.abs(Number(m)) / 1e5).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} L`);
export const pct = (m: string | null | undefined, signed = false, digits = 1) => (m === null || m === undefined ? DASH : fmtPct(Number(m), { signed, digits }));
export const bps = (m: string | null | undefined) => (m === null || m === undefined ? DASH : `${Number(m) < 0 ? "−" : Number(m) > 0 ? "+" : ""}${Math.abs(Math.round(Number(m))).toLocaleString("en-IN")} bps`);
export const psf = (m: string | null | undefined) => (m === null || m === undefined ? DASH : `₹${Number(m).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`);
export const tone = (m: string | null | undefined) => (m !== null && m !== undefined && Number(m) < 0 ? "tone-bad" : "");
export const monthShort = (m: string) => new Date(`${m.slice(0, 7)}-01T00:00:00Z`).toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });

/** A heat-map colour: red to green across the 10th to 90th percentile of the column (reversed when lower is better). No target is implied. */
export function heat(v: string | null | undefined, p10?: string | null, p90?: string | null, higherIsBetter = true): string | undefined {
  if (v === null || v === undefined || p10 === null || p10 === undefined || p90 === null || p90 === undefined) return undefined;
  const lo = Number(p10);
  const hi = Number(p90);
  if (!(hi > lo)) return undefined;
  let t = (Number(v) - lo) / (hi - lo);
  t = Math.max(0, Math.min(1, t));
  if (!higherIsBetter) t = 1 - t;
  const hue = 25 + t * 130;                         // 25 = red, 155 = green
  const alpha = 0.1 + Math.abs(t - 0.5) * 0.5;      // the middle stays pale
  return `oklch(0.78 ${0.1 + Math.abs(t - 0.5) * 0.12} ${hue} / ${alpha.toFixed(2)})`;
}

export const SEVERITY_STYLE: Record<string, string> = {
  Critical: "bg-[oklch(0.58_0.2_25)] text-white",
  High: "bg-[oklch(0.8_0.14_70)] text-[oklch(0.25_0.05_70)]",
  Medium: "bg-[oklch(0.92_0.04_95)] text-[oklch(0.35_0.06_90)]",
};

export const FLAG_LABEL: Record<string, string> = {
  SUDDEN_INCREASE: "Sudden increase",
  SUDDEN_DECREASE: "Sudden decrease",
  SHARE_OF_SALES: "% of sales anomaly",
  PEER: "Peer anomaly",
  PSF: "PSF anomaly",
  TREND_BREAK: "Trend break",
  SALES_DROP: "Sales drop",
  SALES_PSF_DROP: "Sales PSF decline",
  GROWTH_MARGIN_FALL: "Growth, falling GM",
  GROWTH_NO_PROFIT: "Growth, no profit growth",
  COST_DETERIORATION: "Growth, cost deterioration",
  NEW_STORE_BELOW_RAMP: "New store below ramp-up",
  SAME_STORE_BELOW_PEER: "Same store below peers",
};

export const METRIC_LABEL: Record<string, { label: string; kind: "pct" | "psf"; higher: boolean }> = {
  growth_pct: { label: "Sales growth", kind: "pct", higher: true },
  gross_margin_pct: { label: "Gross margin %", kind: "pct", higher: true },
  contribution_pct: { label: "Contribution %", kind: "pct", higher: true },
  opex_pct: { label: "Store opex % of sales", kind: "pct", higher: false },
  sales_psf: { label: "Sales per sq ft / month", kind: "psf", higher: true },
  payroll_psf: { label: "Payroll per sq ft / month", kind: "psf", higher: false },
  rent_psf: { label: "Rent per sq ft / month", kind: "psf", higher: false },
  power_psf: { label: "Electricity per sq ft / month", kind: "psf", higher: false },
};
