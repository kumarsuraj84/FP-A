import type { BridgeItem, Horizon, QueryCtx, Tone } from "@/types/cfo";
import type { CashDecision, CashObligation, CashRoom, CashStep, WcDriver } from "@/types/cash";
import { HORIZON_DAYS, buildLiquidity, buildWorkingCapital, dayLabel, params } from "./builders";
import { fmtCr } from "@/lib/format";
import { weightedSplit } from "./seed";

const r2 = (n: number) => Math.round(n * 100) / 100;
const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
const tone = (v: number, goodWhenUp = true): Tone => (Math.abs(v) < 0.005 ? "neutral" : (v > 0) === goodWhenUp ? "good" : "bad");

const KIND_OF = (label: string): CashObligation["kind"] => (label.includes("Vendor") ? "vendor" : label.includes("Payroll") ? "payroll" : label.includes("GST") ? "statutory" : "occupancy");

const STEPS: { horizon: Horizon; label: string }[] = [
  { horizon: "today", label: "Today" },
  { horizon: "7d", label: "7 days" },
  { horizon: "15d", label: "15 days" },
  { horizon: "30d", label: "30 days" },
];

/** Cash & Working Capital Control: reuses the Command Center liquidity and working-capital model, so the numbers match. */
export function buildCashRoom(ctx: QueryCtx, horizon: Horizon): CashRoom {
  const { S, k } = params(ctx);
  const H = HORIZON_DAYS[horizon];
  const liq = buildLiquidity(ctx, horizon);
  const opening = S.cash;
  const closing = liq.projectedCash.value ?? opening;

  const inH = S.events.filter((e) => e.day <= H);
  const by = (kind: CashObligation["kind"]) => r2(sum(inH.filter((e) => KIND_OF(e.label) === kind).map((e) => e.amount)));
  const vendor = by("vendor");
  const payroll = by("payroll");
  const statutory = by("statutory");
  const occupancy = by("occupancy");
  // derive inflows from the rounded parts so the bridge adds up exactly to the closing figure
  const inflows = r2(closing - opening + vendor + payroll + statutory + occupancy);

  const mk = (id: string, label: string, v: number, family: BridgeItem["family"] = "cash"): BridgeItem => ({ id, label, kind: "delta", value: v, tone: tone(v), family });
  const items: BridgeItem[] = [
    { id: "current", label: "Opening Cash", kind: "total", value: opening, tone: "neutral", family: "cash" },
    mk("inflows", "Expected Inflows", inflows),
    ...(vendor ? [mk("obl_vendor", "Vendor Payments", -vendor, "payables")] : []),
    ...(payroll ? [mk("obl_payroll", "Payroll", -payroll, "cost")] : []),
    ...(statutory ? [mk("obl_statutory", "Statutory", -statutory)] : []),
    ...(occupancy ? [mk("obl_other", "Rent & Other", -occupancy)] : []),
    { id: "projected", label: "Forecast Closing Cash", kind: "total", value: closing, tone: "neutral", family: "cash" },
  ];

  // the trajectory always runs to 30 days; the selected horizon only decides which step the bridge explains
  const full = buildLiquidity(ctx, "30d");
  const steps: CashStep[] = STEPS.map(({ horizon: h, label }) => {
    if (h === "today") return { horizon: h, label, dayLabel: dayLabel(0), closing: opening, headroom: r2(opening - S.cashMin), breach: opening < S.cashMin };
    const l = buildLiquidity(ctx, h);
    const c = l.projectedCash.value ?? opening;
    return { horizon: h, label, dayLabel: dayLabel(HORIZON_DAYS[h]), closing: c, headroom: r2(c - S.cashMin), breach: l.breachDay !== null };
  });

  const obligations: CashObligation[] = S.events
    .map((e) => ({ id: `${e.label}-${e.day}`, dayLabel: dayLabel(e.day), daysAway: e.day, label: e.label, amount: e.amount, kind: KIND_OF(e.label), inHorizon: e.day <= H }))
    .sort((a, b) => a.daysAway - b.daysAway);

  const wc = buildWorkingCapital(ctx);
  const wcMeta: Record<string, { label: string; unit: "days" | "cr"; base: number; factor: number; goodWhenUp: boolean }> = {
    inventory: { label: "Inventory days", unit: "days", base: 71, factor: -0.45, goodWhenUp: false },
    creditors: { label: "Creditor days", unit: "days", base: 58, factor: 0.35, goodWhenUp: true },
    vendor_advances: { label: "Open advances", unit: "cr", base: S.advances, factor: -1, goodWhenUp: false },
    receivables: { label: "Receivable days", unit: "days", base: 4.5, factor: -0.3, goodWhenUp: false },
    other_wc: { label: "Deposits & prepaid", unit: "cr", base: 24.1, factor: -1, goodWhenUp: false },
  };
  const drivers: WcDriver[] = wc.rows.map((r) => {
    const m = wcMeta[r.id];
    const change = r2((r.cashImpact / k) * m.factor * (m.unit === "cr" ? k : 1));
    const monthly = weightedSplit(r.cashImpact, [1, 1.1, 1.2, 1.35, 1.5, 1.7]);
    return {
      id: r.id,
      label: r.label,
      cashImpact: r.cashImpact,
      direction: r.direction,
      tone: r.tone,
      note: r.note,
      family: r.family,
      measure: { label: m.label, value: r2(m.base + (m.unit === "days" ? change : 0)), unit: m.unit, change },
      monthly,
      deteriorating: r.tone === "bad",
    };
  });

  const sel = steps.find((x) => x.horizon === horizon) ?? steps[steps.length - 1];
  const absorbing = [...drivers].filter((d) => d.cashImpact < 0).sort((a, b) => a.cashImpact - b.cashImpact)[0];
  const biggest = obligations.filter((o) => o.inHorizon).sort((a, b) => b.amount - a.amount)[0];
  const decision: CashDecision = {
    horizonLabel: horizon === "today" ? "Today" : `Next ${sel.label}`,
    horizonLine: `${fmtCr(sel.closing)} closing · ${sel.headroom < 0 ? `${fmtCr(-sel.headroom)} below minimum` : `${fmtCr(sel.headroom)} headroom`} · ${liq.breachDay ? `Breach ${liq.breachDay}` : "No breach"}`,
    tone: liq.breachDay || sel.headroom < 0 ? "bad" : sel.headroom < 8 ? "warn" : "good",
    absorption: absorbing ? { label: absorbing.label, amount: absorbing.cashImpact, key: absorbing.id } : null,
    obligation: biggest ? { label: biggest.label, amount: biggest.amount, dayLabel: biggest.dayLabel, key: `obl_${biggest.kind === "occupancy" ? "other" : biggest.kind}` } : null,
    action: liq.breachDay
      ? biggest
        ? { text: `Review ${biggest.label.toLowerCase()} timing`, key: `obl_${biggest.kind === "occupancy" ? "other" : biggest.kind}` }
        : { text: "Review projected cash", key: "projected" }
      : absorbing
        ? { text: `Review ${absorbing.label.toLowerCase()} build-up`, key: absorbing.id }
        : null,
  };

  return {
    decision,
    horizon,
    openingCash: opening,
    forecastClosing: closing,
    operatingMinimum: S.cashMin,
    breachDay: liq.breachDay,
    headline: liq.headline,
    tone: liq.tone,
    steps,
    bridge: {
      id: "cashroom",
      title: horizon === "today" ? "What happens to cash in the next 24 hours?" : `What happens to cash over the next ${H} days?`,
      subtitle: `Opening cash to forecast closing cash · ${STEPS.find((s) => s.horizon === horizon)?.label}`,
      unitNote: "₹ Cr · axis truncated for variance visibility",
      items,
    },
    capex: { value: null, reason: "Awaiting capex commitment register" },
    series: full.series,
    obligations,
    obligationTotals: { all: r2(sum(S.events.map((e) => e.amount))), inHorizon: r2(sum(inH.map((e) => e.amount))) },
    drivers,
    netCashImpact: wc.netCashImpact,
    wcHeadline: wc.headline,
  };
}
