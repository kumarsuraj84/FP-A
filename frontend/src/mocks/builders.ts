import type {
  Bridge,
  BridgeItem,
  CfoAction,
  ForecastTrajectory,
  Horizon,
  LiquidityPoint,
  LiquiditySummary,
  PulseMetric,
  QueryCtx,
  RiskPillar,
  Severity,
  Tone,
  WorkingCapitalSummary,
} from "@/types/cfo";
import { COMPARISONS, PERIODS, SCENARIOS, type ScenarioParams } from "./scenarios";
import { rng } from "./seed";

const r2 = (n: number) => Math.round(n * 100) / 100;
const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
const tone = (v: number, goodWhenUp = true): Tone => (Math.abs(v) < 0.005 ? "neutral" : (v > 0) === goodWhenUp ? "good" : "bad");

export function params(ctx: QueryCtx) {
  const S = SCENARIOS[ctx.scenario];
  const k = PERIODS[ctx.period].k;
  const c = COMPARISONS[ctx.comparison].c;
  return { S, k, c, cmp: COMPARISONS[ctx.comparison], per: PERIODS[ctx.period] };
}

/* ───────────── bridges ───────────── */

export function profitBridge(ctx: QueryCtx): Bridge {
  const { S, k, c, cmp, per } = params(ctx);
  const d = S.deltas;
  const deltas: [string, string, number, BridgeItem["family"]][] = [
    ["sales_volume", "Sales Volume", d.salesVolume, "volume"],
    ["gm_impact", "Gross Margin Impact", d.gm, "margin"],
    ["payroll", "Payroll", d.payroll, "cost"],
    ["occupancy", "Occupancy", d.occupancy, "cost"],
    ["electricity", "Electricity", d.electricity, "cost"],
    ["store_productivity", "Store Productivity", d.productivity, "volume"],
  ];
  const actual = r2(k * (S.budgetProfit + sum(Object.values(d))));
  const scaled = deltas.map(([id, label, v, family]) => ({ id, label, value: r2(v * k * c), family }));
  const start = r2(actual - sum(scaled.map((x) => x.value)));
  const items: BridgeItem[] = [
    { id: "start", label: cmp.startLabel, kind: "total", value: start, tone: "neutral", family: "margin" },
    ...scaled.map((x) => ({ id: x.id, label: x.label, kind: "delta" as const, value: x.value, tone: tone(x.value), family: x.family })),
    { id: "actual", label: "Actual Profit", kind: "total", value: actual, tone: "neutral", family: "margin" },
  ];
  return {
    id: "profit",
    title: `Why is operating profit ${actual >= start ? "ahead of" : "behind"} ${cmp.short.toLowerCase()}?`,
    subtitle: `${per.label} · Operating profit / contribution · ${cmp.label}`,
    unitNote: "₹ Cr · axis truncated for variance visibility",
    items,
  };
}

export function cashFlowsFor(S: ScenarioParams, k: number) {
  const f = S.cashFlows;
  return {
    opEarnings: r2(f.opEarnings * k),
    inventory: r2(f.inventory * k),
    creditors: r2(f.creditors * k),
    advances: r2(f.advances * k),
    receivables: r2(f.receivables * k),
    otherWc: r2(f.otherWc * k),
    capex: r2(f.capex * k),
  };
}

export function cashBridge(ctx: QueryCtx): Bridge {
  const { S, k, per } = params(ctx);
  const f = cashFlowsFor(S, k);
  const net = r2(sum(Object.values(f)));
  const opening = r2(S.cash - net);
  const mk = (id: string, label: string, v: number, goodUp = true, family: BridgeItem["family"] = "cash"): BridgeItem => ({
    id,
    label,
    kind: "delta",
    value: v,
    tone: tone(v, goodUp),
    family,
  });
  return {
    id: "cash",
    title: "Where did cash come from, and where did it go?",
    subtitle: `${per.label} · Opening to closing cash`,
    unitNote: "₹ Cr · axis truncated for variance visibility",
    items: [
      { id: "opening_cash", label: "Opening Cash", kind: "total", value: opening, tone: "neutral", family: "cash" },
      mk("op_earnings", "Operating Earnings", f.opEarnings, true, "cash"),
      mk("inventory", "Inventory", f.inventory, true, "volume"),
      mk("creditors", "Creditors", f.creditors, true, "payables"),
      mk("vendor_advances", "Vendor Advances", f.advances, true, "advances"),
      mk("receivables", "Receivables", f.receivables, true, "cash"),
      mk("other_wc", "Other Working Capital", f.otherWc, true, "cash"),
      mk("capex", "Capex & Other", f.capex, true, "cash"),
      { id: "closing_cash", label: "Closing Cash", kind: "total", value: S.cash, tone: "neutral", family: "cash" },
    ],
  };
}

export function workingCapitalBridge(ctx: QueryCtx): Bridge {
  const { S, k, per } = params(ctx);
  const f = cashFlowsFor(S, k);
  // NWC increases when cash is absorbed: delta NWC = -cash impact
  const nwc = { inventory: -f.inventory, creditors: -f.creditors, advances: -f.advances, receivables: -f.receivables, otherWc: -f.otherWc };
  const change = r2(sum(Object.values(nwc)));
  const closing = r2(96.4 + (S.cashFlows.inventory + S.cashFlows.creditors + S.cashFlows.advances + S.cashFlows.receivables + S.cashFlows.otherWc) * -1);
  const opening = r2(closing - change);
  const mk = (id: string, label: string, v: number, family: BridgeItem["family"]): BridgeItem => ({
    id,
    label,
    kind: "delta",
    value: r2(v),
    tone: tone(v, false), // NWC up = cash absorbed = bad
    family,
  });
  return {
    id: "workingCapital",
    title: "What moved net working capital?",
    subtitle: `${per.label} · Net working capital, opening to closing`,
    unitNote: "₹ Cr · NWC increase = cash absorbed · axis truncated for variance visibility",
    items: [
      { id: "opening_nwc", label: "Opening NWC", kind: "total", value: opening, tone: "neutral", family: "cash" },
      mk("inventory", "Inventory", nwc.inventory, "volume"),
      mk("creditors", "Creditors", nwc.creditors, "payables"),
      mk("vendor_advances", "Vendor Advances", nwc.advances, "advances"),
      mk("receivables", "Receivables", nwc.receivables, "cash"),
      mk("other_wc", "Other WC", nwc.otherWc, "cash"),
      { id: "closing_nwc", label: "Closing NWC", kind: "total", value: closing, tone: "neutral", family: "cash" },
    ],
  };
}

/* ───────────── pulse ───────────── */

export function buildPulse(ctx: QueryCtx): PulseMetric[] {
  const { S, k, c, cmp, per } = params(ctx);
  const dsum = sum(Object.values(S.deltas));
  const profit = r2(k * (S.budgetProfit + dsum));
  const profitMove = r2(k * dsum * c);
  const revenue = r2(S.revenue * k);
  const revMove = r2(S.revDelta * k * c);
  const gmMove = Math.round(S.gmBps * c);
  const f = cashFlowsFor(S, k);
  const credMove = r2(f.creditors);
  const advMove = r2(-f.advances);
  const unrecMove = r2(S.unrecMtd * (ctx.period === "sep26" ? 1 : ctx.period === "q2fy27" ? 2 : 3));
  const cashMove = r2(S.cashPlanDelta * c);
  const sign = (v: number) => (v >= 0 ? "Ahead of" : "Behind");

  return [
    {
      id: "cash",
      label: "Cash",
      value: { value: S.cash },
      unit: "cr",
      comparisonLabel: `${cmp.label}`,
      movement: { value: cashMove },
      movementUnit: "cr",
      status: S.cash < S.cashMin + 8 ? `Within ₹${r2(S.cash - S.cashMin)} Cr of operating minimum` : `${sign(cashMove)} plan · ₹${S.cashMin} Cr minimum held`,
      tone: S.cash < S.cashMin + 8 ? "bad" : tone(cashMove),
      family: "cash",
      heroTab: "cash",
      origin: { source: "pulse", scope: "pulse", id: "cash", label: "Cash", family: "cash", amount: S.cash, variance: cashMove },
    },
    {
      id: "revenue",
      label: "Revenue",
      value: { value: revenue },
      unit: "cr",
      comparisonLabel: cmp.label,
      movement: { value: revMove },
      movementUnit: "cr",
      status: `${sign(revMove)} ${cmp.short.toLowerCase()} · ${r2((revMove / Math.max(revenue - revMove, 1)) * 100)}%`,
      tone: tone(revMove),
      family: "volume",
      heroTab: "profit",
      origin: { source: "pulse", scope: "pulse", id: "revenue", label: "Revenue", family: "volume", amount: revenue, variance: revMove },
    },
    {
      id: "gm",
      label: "Gross Margin",
      value: { value: S.gmPct },
      unit: "pct",
      comparisonLabel: cmp.label,
      movement: { value: gmMove },
      movementUnit: "bps",
      status: gmMove < -200 ? "Material margin gap" : gmMove < 0 ? "Below plan" : "At or above plan",
      tone: gmMove < -200 ? "bad" : gmMove < 0 ? "warn" : "good",
      family: "margin",
      heroTab: "profit",
      origin: { source: "pulse", scope: "pulse", id: "gm", label: "Gross Margin Variance", family: "margin", amount: r2(S.deltas.gm * k * c), variance: r2(S.deltas.gm * k * c) },
    },
    {
      id: "profit",
      label: "Operating Profit",
      value: { value: profit },
      unit: "cr",
      comparisonLabel: cmp.label,
      movement: { value: profitMove },
      movementUnit: "cr",
      status: `${sign(profitMove)} ${cmp.short.toLowerCase()} · ${per.short}`,
      tone: tone(profitMove),
      family: "margin",
      heroTab: "profit",
      origin: { source: "pulse", scope: "pulse", id: "profit", label: "Operating Profit", family: "margin", amount: profit, variance: profitMove },
    },
    {
      id: "creditors",
      label: "Creditors",
      value: { value: S.creditors },
      unit: "cr",
      comparisonLabel: "vs period opening",
      movement: { value: credMove },
      movementUnit: "cr",
      status: `₹${S.creditors181} Cr over 180 days · ${S.creditors181Vendors} vendors`,
      tone: S.creditors181 > 30 ? "bad" : S.creditors181 > 15 ? "warn" : "neutral",
      family: "payables",
      heroTab: "workingCapital",
      origin: { source: "pulse", scope: "pulse", id: "creditors", label: "Creditors", family: "payables", amount: S.creditors, variance: credMove },
      target: { age: "all", lens: "age" },
    },
    {
      id: "advances",
      label: "Vendor Advances",
      value: { value: S.advances },
      unit: "cr",
      comparisonLabel: "vs period opening",
      movement: { value: advMove },
      movementUnit: "cr",
      status: `₹${S.adv90} Cr older than 90 days`,
      tone: S.adv90 > 8 ? "bad" : S.adv90 > 2 ? "warn" : "neutral",
      family: "advances",
      heroTab: "workingCapital",
      origin: { source: "pulse", scope: "pulse", id: "vendor_advances", label: "Vendor Advances", family: "advances", amount: S.advances, variance: advMove },
    },
    {
      id: "unreconciled",
      label: "Unreconciled",
      value: { value: S.unrec },
      unit: "cr",
      comparisonLabel: "vs period opening",
      movement: { value: unrecMove },
      movementUnit: "cr",
      status: `${S.unrecAccounts} accounts · oldest ${S.unrecOldest} days`,
      tone: S.unrec > 7.5 ? "bad" : "warn",
      family: "recon",
      heroTab: "cash",
      origin: { source: "pulse", scope: "pulse", id: "unreconciled", label: "Unreconciled", family: "recon", amount: S.unrec, variance: unrecMove },
    },
  ];
}

/* ───────────── liquidity ───────────── */

const HORIZON_DAYS: Record<Horizon, number> = { today: 1, "7d": 7, "15d": 15, "30d": 30 };
const MONTH = ["Oct", "Oct", "Oct"];

function dayLabel(offset: number): string {
  const d = new Date(Date.UTC(2026, 9, 3 + offset));
  return `${d.getUTCDate()} ${d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" })}`;
}

export function buildLiquidity(ctx: QueryCtx, horizon: Horizon): LiquiditySummary {
  const { S } = params(ctx);
  const H = HORIZON_DAYS[horizon];
  const daily = S.inflow30 / 30;
  const rand = rng(`liq-${ctx.scenario}`);
  const series: LiquidityPoint[] = [];
  // 7 actual history days, shaped to land exactly on current cash
  const hist: number[] = [];
  let level = S.cash;
  for (let i = 0; i > -7; i--) {
    hist.unshift(level);
    level = r2(level - (rand() - 0.45) * 2.6);
  }
  hist.forEach((v, i) => series.push({ label: dayLabel(i - 6), cash: r2(v), actual: true }));
  let cash = S.cash;
  let inflows = 0;
  let oblig = 0;
  let breachDay: string | null = null;
  for (let d = 1; d <= H; d++) {
    const ev = S.events.find((e) => e.day === d);
    cash += daily;
    inflows += daily;
    if (ev) {
      cash -= ev.amount;
      oblig += ev.amount;
    }
    if (breachDay === null && cash < S.cashMin) breachDay = dayLabel(d);
    series.push({ label: dayLabel(d), cash: r2(cash), actual: false });
  }
  const horizonWord = horizon === "today" ? "by tomorrow" : `in ${H} days`;
  const projected = r2(cash);
  return {
    currentCash: { value: S.cash },
    projectedCash: { value: projected },
    operatingMinimum: S.cashMin,
    expectedInflows: { value: r2(inflows) },
    upcomingObligations: { value: r2(oblig) },
    breachDay,
    series,
    headline: breachDay
      ? `Cash falls below the ₹${S.cashMin} Cr operating minimum on ${breachDay}`
      : `Cash stays above the ₹${S.cashMin} Cr minimum; ₹${projected.toFixed(2)} Cr ${horizonWord}`,
    tone: breachDay ? "bad" : projected - S.cashMin < 8 ? "warn" : "good",
  };
}

/* ───────────── working capital ───────────── */

export function buildWorkingCapital(ctx: QueryCtx): WorkingCapitalSummary {
  const { S, k } = params(ctx);
  const f = cashFlowsFor(S, k);
  const mk = (id: string, label: string, v: number, note: string, family: BridgeItem["family"]) => ({
    id,
    label,
    cashImpact: v,
    direction: (v < 0 ? "absorbed" : "released") as "absorbed" | "released",
    tone: tone(v),
    note,
    family,
  });
  const rows = [
    mk("inventory", "Inventory", f.inventory, "Stock build ahead of festive season", "volume"),
    mk("creditors", "Creditors", f.creditors, `${S.creditors181Vendors} vendors over 180 days`, "payables"),
    mk("vendor_advances", "Vendor Advances", f.advances, `₹${S.adv90} Cr older than 90 days`, "advances"),
    mk("receivables", "Receivables", f.receivables, "Card and franchise settlements", "cash"),
    mk("other_wc", "Other Working Capital", f.otherWc, "Deposits, GST input, prepaid", "cash"),
  ];
  const net = r2(sum(rows.map((x) => x.cashImpact)));
  return {
    rows,
    netCashImpact: net,
    headline: net < 0 ? `Working capital absorbed ₹${Math.abs(net).toFixed(2)} Cr of cash` : `Working capital released ₹${net.toFixed(2)} Cr of cash`,
  };
}

/* ───────────── risks ───────────── */

export function buildRisks(ctx: QueryCtx): RiskPillar[] {
  const { S, k, c } = params(ctx);
  const f = cashFlowsFor(S, k);
  const liq = buildLiquidity(ctx, "30d");
  const minHeadroom = r2(Math.min(...liq.series.filter((p) => !p.actual).map((p) => p.cash)) - S.cashMin);
  return [
    {
      id: "liquidity",
      label: "Liquidity",
      exposure: { value: minHeadroom < 0 ? r2(-minHeadroom) : S.cash },
      movement: { value: r2(S.cashPlanDelta * c) },
      severity: S.sev.liquidity,
      diagnosticLabel: minHeadroom < 0 ? "Shortfall vs minimum" : "30-day low headroom",
      diagnosticValue: minHeadroom < 0 ? `₹${r2(-minHeadroom)} Cr` : `₹${minHeadroom} Cr`,
      family: "cash",
      origin: { source: "risk", scope: "risk", id: "liquidity", label: "Liquidity", family: "cash", amount: minHeadroom < 0 ? -r2(-minHeadroom) : S.cash, variance: r2(S.cashPlanDelta * c) },
    },
    {
      id: "gm",
      label: "Gross Margin",
      exposure: { value: r2(S.gmImpactEst) },
      movement: { value: Math.round(S.gmBps * c) },
      severity: S.sev.gm,
      diagnosticLabel: "Share from top 2 departments",
      diagnosticValue: `${S.gmTop2}%`,
      family: "margin",
      origin: { source: "risk", scope: "risk", id: "gm", label: "GM Variance", family: "margin", amount: -S.gmImpactEst, variance: -S.gmImpactEst },
    },
    {
      id: "payables",
      label: "Payables Ageing",
      exposure: { value: S.creditors181 },
      movement: { value: r2(f.creditors) },
      severity: S.sev.payables,
      diagnosticLabel: "Oldest open balance",
      diagnosticValue: `${S.creditorsOldest} days`,
      family: "payables",
      origin: { source: "risk", scope: "risk", id: "creditors_181", label: "Payables Ageing", family: "payables", amount: S.creditors181, variance: r2(f.creditors) },
      target: { age: "gt180", lens: "age" },
    },
    {
      id: "advances",
      label: "Vendor Advances",
      exposure: { value: S.adv90 },
      movement: { value: S.advMtd },
      severity: S.sev.advances,
      diagnosticLabel: "Vendors with advances >90d",
      diagnosticValue: `${S.advVendors}`,
      family: "advances",
      origin: { source: "risk", scope: "risk", id: "advances_90", label: "Vendor Advances", family: "advances", amount: S.adv90, variance: S.advMtd },
    },
    {
      id: "recon",
      label: "Reconciliation",
      exposure: { value: S.unrec },
      movement: { value: S.unrecMtd },
      severity: S.sev.recon,
      diagnosticLabel: "Oldest unreconciled item",
      diagnosticValue: `${S.unrecOldest} days`,
      family: "recon",
      origin: { source: "risk", scope: "risk", id: "recon", label: "Reconciliation", family: "recon", amount: S.unrec, variance: S.unrecMtd },
    },
  ];
}

/* ───────────── actions ───────────── */

const SEV_W: Record<Severity, number> = { critical: 4, high: 3, medium: 2, low: 1 };

export function buildActions(ctx: QueryCtx): CfoAction[] {
  const { S } = params(ctx);
  const liq = buildLiquidity(ctx, "30d");
  const nextRun = S.events.filter((e) => e.label.includes("Vendor"))[0];
  const all: CfoAction[] = [
    {
      id: "advances_90",
      problem: `₹${S.adv90} Cr Vendor Advances >90 Days`,
      amount: { value: S.adv90 },
      driver: `${S.advVendors} vendors`,
      concentration: `Top 3 vendors hold ${Math.min(88, 52 + S.advVendors)}% of the balance`,
      age: `Oldest ${S.advOldest} days · ₹${S.advMtd} Cr increase MTD`,
      cta: `Review ${S.advVendors} Vendors`,
      severity: S.sev.advances,
      family: "advances",
      origin: { source: "action", scope: "action", id: "advances_90", label: "Vendor Advances >90d", family: "advances", amount: S.adv90, variance: S.advMtd },
    },
    {
      id: "gm_gap",
      problem: `GM ${Math.abs(S.gmBps)} bps Below Plan`,
      amount: { value: -S.gmImpactEst },
      driver: "Markdown depth and mix shift",
      concentration: `${S.gmTop2}% from 2 departments`,
      age: `Est. FY impact ₹${S.gmImpactEst} Cr`,
      cta: "Diagnose Margin Gap",
      severity: S.sev.gm,
      family: "margin",
      origin: { source: "action", scope: "action", id: "gm_gap", label: "GM Variance", family: "margin", amount: -S.gmImpactEst, variance: -S.gmImpactEst },
    },
    {
      id: "creditors_181",
      problem: `₹${S.creditors181} Cr Creditors >180 Days`,
      amount: { value: S.creditors181 },
      driver: `${S.creditors181Vendors} vendors past terms`,
      concentration: `Top 5 vendors hold ${Math.min(81, 38 + S.creditors181Vendors)}%`,
      age: `Oldest ${S.creditorsOldest} days`,
      cta: `Review ${S.creditors181Vendors} Vendors`,
      severity: S.sev.payables,
      family: "payables",
      origin: { source: "action", scope: "action", id: "creditors_181", label: "Creditors >180d", family: "payables", amount: S.creditors181, variance: S.creditors181 },
      target: { age: "gt180", lens: "age" },
    },
    {
      id: "liquidity",
      problem: liq.breachDay ? `Cash Below Minimum by ${liq.breachDay}` : `₹${nextRun?.amount ?? 0} Cr Vendor Payment Run Due`,
      amount: { value: liq.breachDay ? r2(S.cashMin - Math.min(...liq.series.filter((p) => !p.actual).map((p) => p.cash))) : (nextRun?.amount ?? 0) },
      driver: liq.breachDay ? "Payment runs ahead of inflows" : "Scheduled supplier settlement",
      concentration: `${S.events.length} obligations in next 30 days`,
      age: `Operating minimum ₹${S.cashMin} Cr`,
      cta: "Open Liquidity Plan",
      severity: S.sev.liquidity,
      family: "cash",
      origin: { source: "action", scope: "action", id: "liquidity", label: "Liquidity Obligations", family: "cash", amount: -(nextRun?.amount ?? 0), variance: -(nextRun?.amount ?? 0) },
    },
    {
      id: "recon",
      problem: `₹${S.unrec} Cr Unreconciled`,
      amount: { value: S.unrec },
      driver: `${S.unrecAccounts} accounts`,
      concentration: "Bank and card-settlement clearing hold most of it",
      age: `Oldest ${S.unrecOldest} days · ₹${S.unrecMtd} Cr increase MTD`,
      cta: "Review Reconciliation Items",
      severity: S.sev.recon,
      family: "recon",
      origin: { source: "action", scope: "action", id: "recon", label: "Unreconciled Items", family: "recon", amount: S.unrec, variance: S.unrecMtd },
    },
  ];
  return all.map((a, i) => ({ a, i })).sort((x, y) => SEV_W[y.a.severity] - SEV_W[x.a.severity] || x.i - y.i).map((x) => x.a).slice(0, 4);
}

/* ───────────── forecast ───────────── */

const MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"];
const SHARE = [0.06, 0.065, 0.06, 0.062, 0.07, 0.08, 0.105, 0.125, 0.11, 0.09, 0.08, 0.093];

export function buildForecast(ctx: QueryCtx): ForecastTrajectory {
  const { S } = params(ctx);
  const dsum = sum(Object.values(S.deltas));
  const risk = S.fcSales + S.fcMargin + S.fcCost;
  const landing = r2(S.fcBudgetFy + risk + S.fcRecovery);
  const ytdBudget = S.budgetProfit;
  const ytdActual = S.budgetProfit + dsum;
  const ratio = ytdActual / ytdBudget;
  let cumB = 0;
  const months = MONTHS.map((m, i) => {
    cumB += SHARE[i] * S.fcBudgetFy;
    return { m, i, cumB: r2(cumB) };
  });
  const cumB6 = months[5].cumB;
  const actual6 = r2(cumB6 * ratio);
  const out = months.map(({ m, i, cumB }) => {
    const actual = i <= 5 ? r2(cumB * ratio) : null;
    const fShare = i >= 5 ? (cumB - cumB6) / (S.fcBudgetFy - cumB6) : 0;
    const forecast = i >= 5 ? r2(actual6 + (landing - actual6) * fShare) : null;
    return { month: m, budget: cumB, actual, forecast };
  });
  const gap = r2(landing - S.fcBudgetFy);
  return {
    months: out,
    landing: { value: landing },
    budgetFy: { value: S.fcBudgetFy },
    gap: { value: gap },
    headline: `Landing ₹${landing.toFixed(2)} Cr vs budget ₹${S.fcBudgetFy.toFixed(2)} Cr (${gap >= 0 ? "+" : "−"}₹${Math.abs(gap).toFixed(2)} Cr)`,
    bridge: {
      id: "forecast",
      title: "Where are we landing, and why?",
      subtitle: "FY 2026-27 · Budget to latest forecast · cumulative operating profit",
      unitNote: "₹ Cr · axis truncated for variance visibility",
      items: [
        { id: "budget_fy", label: "Budget FY Profit", kind: "total", value: S.fcBudgetFy, tone: "neutral", family: "forecast" },
        { id: "sales_risk", label: "Sales Risk", kind: "delta", value: S.fcSales, tone: tone(S.fcSales), family: "volume" },
        { id: "margin_risk", label: "Margin Risk", kind: "delta", value: S.fcMargin, tone: tone(S.fcMargin), family: "margin" },
        { id: "cost_risk", label: "Cost Risk", kind: "delta", value: S.fcCost, tone: tone(S.fcCost), family: "cost" },
        { id: "recovery", label: "Recovery", kind: "delta", value: S.fcRecovery, tone: tone(S.fcRecovery), family: "forecast" },
        { id: "latest_forecast", label: "Latest Forecast", kind: "total", value: landing, tone: "neutral", family: "forecast" },
      ],
    },
  };
}

void MONTH;
