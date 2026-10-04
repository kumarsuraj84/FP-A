import type { Bridge, BridgeItem, DrillNode, DrillOrigin, DrillRow, DrillSplit, DrillView, ForecastMonth, LedgerEntry, LedgerView, QueryCtx, Tone } from "@/types/cfo";
import {
  QUADRANT_META,
  QUADRANT_ORDER,
  type BenchmarkCell,
  type BenchmarkMetricId,
  type BenchmarkRow,
  type ExpenseLine,
  type GapDriver,
  type ProfitPortfolio,
  type QuadrantId,
  type StoreDot,
  type StoreKpi,
  type StoreMovement,
  type StoreWorkspace,
  type TrajectoryMetric,
} from "@/types/profitability";
import { fmtCr } from "@/lib/format";
import { slugStore } from "@/lib/profitNodes";
import { COMPARISONS, PERIODS, SCENARIOS } from "./scenarios";
import { ALL_STORES, DEPARTMENTS, rng, weightedSplit } from "./seed";

/**
 * Stage 3 mock service for Store Profitability.
 *
 * The 24 stores reconcile to the Command Center: their contribution variances add up to the same bridge
 * (sales volume, GM, payroll, occupancy, electricity, productivity), so a CFO who moves from the Command
 * Center into a store sees the same story at store level. All values are deterministic.
 */

const r4 = (n: number) => Math.round(n * 1e4) / 1e4;
const r2 = (n: number) => Math.round(n * 100) / 100;
const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
const toneOf = (v: number): Tone => (Math.abs(v) < 0.00049 ? "neutral" : v > 0 ? "good" : "bad");
const money = (n: number) => fmtCr(Math.abs(n));

type Format = "Large format" | "Standard format";
/** region, cluster, format */
const META: Record<string, [string, string, Format]> = {
  Rohini: ["Delhi NCR", "Delhi", "Large format"],
  "Karol Bagh": ["Delhi NCR", "Delhi", "Standard format"],
  "Sector 18 Noida": ["Delhi NCR", "Noida–Gurugram", "Large format"],
  "Gurugram MG Road": ["Delhi NCR", "Noida–Gurugram", "Large format"],
  "Ludhiana Model Town": ["Punjab & Rajasthan", "Punjab & Rajasthan", "Standard format"],
  "Jaipur C-Scheme": ["Punjab & Rajasthan", "Punjab & Rajasthan", "Standard format"],
  Koramangala: ["Karnataka", "Bengaluru–Mysuru", "Large format"],
  "Mysuru Devaraja": ["Karnataka", "Bengaluru–Mysuru", "Standard format"],
  "T Nagar": ["Tamil Nadu", "Chennai–Coimbatore", "Large format"],
  "Coimbatore RS Puram": ["Tamil Nadu", "Chennai–Coimbatore", "Standard format"],
  "Banjara Hills": ["Telangana & Kerala", "Hyderabad–Kochi", "Large format"],
  "Kochi Edappally": ["Telangana & Kerala", "Hyderabad–Kochi", "Standard format"],
  "Salt Lake": ["West Bengal", "Kolkata", "Large format"],
  "Park Street": ["West Bengal", "Kolkata", "Standard format"],
  "Patna Boring Road": ["Bihar & Jharkhand", "Bihar & Jharkhand", "Standard format"],
  "Ranchi Main Road": ["Bihar & Jharkhand", "Bihar & Jharkhand", "Standard format"],
  "Bhubaneswar Saheed Nagar": ["Odisha & Northeast", "Odisha & Northeast", "Standard format"],
  "Guwahati GS Road": ["Odisha & Northeast", "Odisha & Northeast", "Standard format"],
  "Andheri West": ["Maharashtra", "Mumbai–Pune", "Large format"],
  "Pune FC Road": ["Maharashtra", "Mumbai–Pune", "Large format"],
  "Surat Adajan": ["Gujarat", "Gujarat", "Standard format"],
  "Ahmedabad CG Road": ["Gujarat", "Gujarat", "Large format"],
  "Indore Vijay Nagar": ["Central India", "Central India", "Standard format"],
  "Nagpur Sitabuldi": ["Central India", "Central India", "Standard format"],
};

type Comp = "sales" | "gm" | "payroll" | "rent" | "electricity" | "logistics" | "security" | "repairs" | "other";
const COMPS: Comp[] = ["sales", "gm", "payroll", "rent", "electricity", "logistics", "security", "repairs", "other"];
const OPEX: Comp[] = ["payroll", "rent", "electricity", "logistics", "security", "repairs", "other"];

interface Base {
  id: string;
  name: string;
  zone: string;
  region: string;
  cluster: string;
  format: Format;
  revRaw: number;
  bMul: number;
  gb: number;
  growth: number;
  w: Record<Comp, number>;
  opexSplit: number[];
}

/** The margin investigation in the Command Center weights regions and North's stores; the stores here use the same table. */
const REGION_W: Record<string, number> = { North: 0.38, West: 0.27, South: 0.22, East: 0.13 };
const NORTH_W: Record<string, number> = { Rohini: 0.34, "Karol Bagh": 0.22, "Sector 18 Noida": 0.17, "Gurugram MG Road": 0.13, "Ludhiana Model Town": 0.08, "Jaipur C-Scheme": 0.06 };

const BASES: Base[] = (() => {
  const raw = ALL_STORES.map((s) => {
    const r = rng(`pstore|${s.name}`);
    const [region, cluster, format] = META[s.name];
    const rohini = s.name === "Rohini";
    const gmW = s.region === "North" ? REGION_W.North * NORTH_W[s.name] : 0.6 + r() * 0.8;
    const signed = (boost = 0) => r() - 0.32 + boost;
    const w: Record<Comp, number> = {
      gm: gmW,
      sales: signed(rohini ? 0.5 : 0),
      payroll: signed(rohini ? 0.45 : 0),
      rent: signed(),
      electricity: signed(rohini ? 0.4 : 0),
      logistics: signed(),
      security: signed(),
      repairs: signed(),
      other: signed(),
    };
    const g3 = r() + r() + r() - 1.5;
    return {
      id: slugStore(s.name),
      name: s.name,
      zone: s.region,
      region,
      cluster,
      format,
      revRaw: rohini ? 1.45 : 0.55 + r() * 1.2,
      bMul: rohini ? 0.95 : 0.45 + r() * 1.15,
      gb: rohini ? 0.405 : 0.395 + r() * 0.045,
      growth: rohini ? 3.1 : 12 + g3 * 14,
      w,
      opexSplit: [0.38, 0.28, 0.08, 0.1, 0.04, 0.04, 0.08].map((x) => x * (0.85 + r() * 0.3)),
    } satisfies Base;
  });
  // each region's GM weights add up to the region's share (North is already exact), so regions tie to the Command Center table
  for (const region of Object.keys(REGION_W)) {
    if (region === "North") continue;
    const inRegion = raw.filter((b) => b.zone === region);
    const total = sum(inRegion.map((b) => b.w.gm));
    inRegion.forEach((b) => (b.w.gm = (b.w.gm / total) * REGION_W[region]));
  }
  return raw;
})();

export const STORE_IDS = BASES.map((b) => b.id);

interface Model {
  base: Base;
  dot: StoreDot;
  rev: number;
  revBudget: number;
  prevRev: number;
  gmA: number;
  gmB: number;
  contribA: number;
  contribB: number;
  opexA: number;
  opexB: number;
  imp: Record<Comp, number>;
  linesA: number[];
  linesB: number[];
}

interface Network {
  models: Model[];
  split: { growthPct: number; marginPct: number };
  company: ProfitPortfolio["company"];
}

const cache = new Map<string, Network>();

function network(ctx: QueryCtx): Network {
  const key = `${ctx.scenario}|${ctx.period}|${ctx.comparison}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const S = SCENARIOS[ctx.scenario];
  const k = PERIODS[ctx.period].k;
  const c = COMPARISONS[ctx.comparison].c;
  const d = S.deltas;

  const R = weightedSplit(S.revenue * k, BASES.map((b) => b.revRaw));
  const B = weightedSplit(S.budgetProfit * k, BASES.map((b) => b.revRaw * b.bMul));
  const totals: Record<Comp, number> = {
    sales: d.salesVolume * k * c,
    gm: d.gm * k * c,
    payroll: d.payroll * k * c,
    rent: d.occupancy * k * c,
    electricity: d.electricity * k * c,
    logistics: d.productivity * k * c * 0.4,
    security: d.productivity * k * c * 0.1,
    repairs: d.productivity * k * c * 0.2,
    other: d.productivity * k * c * 0.3,
  };
  const impAll = Object.fromEntries(COMPS.map((comp) => [comp, weightedSplit(totals[comp], BASES.map((b) => b.w[comp]))])) as Record<Comp, number[]>;

  const models: Model[] = BASES.map((b, i) => {
    const imp = Object.fromEntries(COMPS.map((comp) => [comp, impAll[comp][i]])) as Record<Comp, number>;
    const revBudget = r4(R[i] - imp.sales / b.gb);
    const gmB = r4(revBudget * b.gb);
    const opexB = r4(gmB - B[i]);
    const linesB = weightedSplit(opexB, b.opexSplit);
    const gmA = r4(gmB + imp.sales + imp.gm);
    const contribA = r4(B[i] + imp.sales + imp.gm + sum(OPEX.map((o) => imp[o])));
    const opexA = r4(gmA - contribA);
    const first6 = OPEX.slice(0, 6).map((o, j) => r4(linesB[j] - imp[o]));
    const linesA = [...first6, r4(opexA - sum(first6))];
    const dot: StoreDot = {
      id: b.id,
      name: b.name,
      zone: b.zone,
      region: b.region,
      cluster: b.cluster,
      format: b.format,
      revenue: R[i],
      revenueGrowthPct: r2(b.growth),
      gmPct: r2((gmA / R[i]) * 100),
      contributionMarginPct: r2((contribA / R[i]) * 100),
      contribution: contribA,
      contributionVsComparison: r4(contribA - B[i]),
      quadrant: "turnaround",
    };
    return { base: b, dot, rev: R[i], revBudget, prevRev: R[i] / (1 + b.growth / 100), gmA, gmB, contribA, contribB: B[i], opexA, opexB, imp, linesA, linesB };
  });

  const rev = sum(models.map((m) => m.rev));
  const prev = sum(models.map((m) => m.prevRev));
  const contrib = sum(models.map((m) => m.contribA));
  const gm = sum(models.map((m) => m.gmA));
  const split = { growthPct: r2((rev / prev - 1) * 100), marginPct: r2((contrib / rev) * 100) };
  models.forEach((m) => {
    const hiG = m.dot.revenueGrowthPct >= split.growthPct;
    const hiM = m.dot.contributionMarginPct >= split.marginPct;
    m.dot.quadrant = hiG && hiM ? "grow" : hiG ? "fix" : hiM ? "defend" : "turnaround";
  });
  const company = {
    revenue: r4(rev),
    revenueGrowthPct: split.growthPct,
    gmPct: r2((gm / rev) * 100),
    contributionMarginPct: split.marginPct,
    contribution: r4(contrib),
    contributionVsComparison: r4(sum(models.map((m) => m.dot.contributionVsComparison))),
  };
  const net = { models, split, company };
  cache.set(key, net);
  return net;
}

/* ───────────── portfolio ───────────── */

export function buildProfitPortfolio(ctx: QueryCtx): ProfitPortfolio {
  const n = network(ctx);
  const cmp = COMPARISONS[ctx.comparison];
  const stores = n.models.map((m) => m.dot);
  const quadrants = QUADRANT_ORDER.map((id) => {
    const inQ = stores.filter((s) => s.quadrant === id);
    return { id, label: QUADRANT_META[id].label, count: inQ.length, revenue: r4(sum(inQ.map((s) => s.revenue))), contribution: r4(sum(inQ.map((s) => s.contribution))) };
  });
  const need = stores.filter((s) => s.quadrant === "fix" || s.quadrant === "turnaround");
  const worst = [...stores].sort((a, b) => a.contributionVsComparison - b.contributionVsComparison)[0];
  const gap = n.company.contributionVsComparison;
  return {
    stores,
    company: n.company,
    split: n.split,
    quadrants,
    headline: `${need.length} of ${stores.length} stores earn below the network margin of ${n.split.marginPct.toFixed(1)}%; largest shortfall is ${worst.name} (${fmtCr(worst.contributionVsComparison, { signed: true })} ${cmp.label.toLowerCase()})`,
    comparisonLabel: cmp.label,
    basisNote: `Store contribution before head-office costs · network ${gap >= 0 ? "ahead of" : "behind"} ${cmp.short.toLowerCase()} by ${money(gap)}`,
  };
}

/* ───────────── store workspace ───────────── */

const MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"];
const SHARE = [0.06, 0.065, 0.06, 0.062, 0.07, 0.08, 0.105, 0.125, 0.11, 0.09, 0.08, 0.093];
const SH6 = SHARE.slice(0, 6).reduce((a, b) => a + b, 0);

function trajectory(id: TrajectoryMetric["id"], label: string, actualYtd: number, budgetYtd: number, seed: string): TrajectoryMetric {
  const r = rng(seed);
  const aM = weightedSplit(actualYtd, SHARE.slice(0, 6).map((s) => s * (0.93 + 0.14 * r())));
  const bM = weightedSplit(budgetYtd, SHARE.slice(0, 6));
  const fy = budgetYtd / SH6;
  const trend = Math.sqrt(Math.max(budgetYtd !== 0 ? actualYtd / budgetYtd : 1, 0.01));
  const months: ForecastMonth[] = MONTHS.map((month, i) =>
    i < 6 ? { month, budget: bM[i], actual: aM[i], forecast: i === 5 ? aM[5] : null } : { month, budget: r4(fy * SHARE[i]), actual: null, forecast: r4(fy * SHARE[i] * trend) },
  );
  const landing = r4(actualYtd + sum(months.filter((_, i) => i >= 6).map((m) => m.forecast ?? 0)));
  return { id, label, months, landing, budgetFy: r4(fy), gap: r4(landing - fy) };
}

const LINE_LABEL: Record<Comp, string> = {
  sales: "Sales Variance",
  gm: "GM Variance",
  payroll: "Payroll",
  rent: "Rent",
  electricity: "Electricity",
  logistics: "Logistics",
  security: "Security",
  repairs: "Repairs & maintenance",
  other: "Other",
};
const ID_OF: Record<Comp, string> = { sales: "sales_var", gm: "gm_var", payroll: "payroll", rent: "rent", electricity: "electricity", logistics: "logistics", security: "security", repairs: "repairs", other: "other_exp" };

function group(models: Model[]) {
  const rev = sum(models.map((m) => m.rev));
  const prev = sum(models.map((m) => m.prevRev));
  const gm = sum(models.map((m) => m.gmA));
  const opex = sum(models.map((m) => m.opexA));
  const contrib = sum(models.map((m) => m.contribA));
  return {
    growth: (rev / prev - 1) * 100,
    gm: (gm / rev) * 100,
    opex: (opex / rev) * 100,
    contribution: (contrib / rev) * 100,
  };
}

export function buildStoreWorkspace(ctx: QueryCtx, storeId: string): StoreWorkspace | null {
  const net = network(ctx);
  const m = net.models.find((x) => x.base.id === storeId);
  if (!m) return null;
  const cmp = COMPARISONS[ctx.comparison];
  const per = PERIODS[ctx.period];
  const { dot, imp } = m;

  /* header strip */
  const opexPct = (m.opexA / m.rev) * 100;
  const cmB = (m.contribB / m.revBudget) * 100;
  const kpis: StoreKpi[] = [
    { id: "revenue", label: "Revenue", value: m.rev, unit: "cr", sub: `${dot.revenueGrowthPct >= 0 ? "+" : "−"}${Math.abs(dot.revenueGrowthPct).toFixed(1)}% year on year`, variance: r4(m.rev - m.revBudget), tone: toneOf(m.rev - m.revBudget) },
    { id: "gm", label: "Gross Margin", value: m.gmA, unit: "cr", sub: `${dot.gmPct.toFixed(1)}% of revenue`, variance: r4(m.gmA - m.gmB), tone: toneOf(m.gmA - m.gmB) },
    { id: "opex", label: "Opex", value: m.opexA, unit: "cr", sub: `${opexPct.toFixed(1)}% of revenue`, variance: r4(-(m.opexA - m.opexB)), tone: toneOf(-(m.opexA - m.opexB)) },
    { id: "contribution", label: "Contribution", value: m.contribA, unit: "cr", sub: `${dot.contributionMarginPct.toFixed(1)}% of revenue`, variance: dot.contributionVsComparison, tone: toneOf(dot.contributionVsComparison) },
    { id: "contributionPct", label: "Contribution %", value: dot.contributionMarginPct, unit: "pct", sub: `network ${net.split.marginPct.toFixed(1)}%`, variance: r2(dot.contributionMarginPct - cmB), tone: toneOf(dot.contributionMarginPct - cmB) },
  ];

  /* bridge: comparison contribution → sales → GM → opex lines → actual */
  const otherOpex = r4(imp.security + imp.repairs + imp.other);
  const impactItems: [string, string, number, BridgeItem["family"]][] = [
    ["sales_var", "Sales Variance", imp.sales, "volume"],
    ["gm_var", "GM Variance", imp.gm, "margin"],
    ["payroll", "Payroll", imp.payroll, "cost"],
    ["rent", "Rent", imp.rent, "cost"],
    ["electricity", "Electricity", imp.electricity, "cost"],
    ["logistics", "Logistics", imp.logistics, "cost"],
    ["other_opex", "Other Opex", otherOpex, "cost"],
  ];
  const startLabel = cmp.startLabel.replace("Profit", "Contribution");
  const bridgeItems: BridgeItem[] = [
    { id: "budget_contribution", label: startLabel, kind: "total", value: m.contribB, tone: "neutral", family: "margin" },
    ...impactItems.map(([id, label, v, family]) => ({ id, label, kind: "delta" as const, value: v, tone: toneOf(v), family })),
    { id: "actual_contribution", label: "Actual Contribution", kind: "total", value: m.contribA, tone: "neutral", family: "margin" },
  ];
  const gap = r4(m.contribA - m.contribB);
  const bridge: Bridge = {
    id: `store-${dot.id}`,
    title: `Why is ${dot.name} contribution ${gap >= 0 ? "ahead of" : "behind"} ${cmp.short.toLowerCase()}?`,
    subtitle: `${per.label} · Store contribution · ${cmp.label}`,
    unitNote: "₹ Cr · axis truncated for variance visibility",
    items: bridgeItems,
  };

  /* expenses ranked by adverse variance */
  const expenses: ExpenseLine[] = OPEX.map((o, j) => ({
    id: ID_OF[o],
    label: LINE_LABEL[o],
    actual: m.linesA[j],
    budget: m.linesB[j],
    impact: imp[o],
    pctOfRevenue: r2((m.linesA[j] / m.rev) * 100),
    overPct: m.linesB[j] === 0 ? 0 : r2(((m.linesA[j] - m.linesB[j]) / m.linesB[j]) * 100),
    tone: toneOf(imp[o]),
  })).sort((a, b) => a.impact - b.impact);

  /* why: deterministic gap drivers, most adverse first (most favourable first when ahead) */
  const comps = COMPS.map((c) => ({
    id: ID_OF[c],
    label: c === "sales" ? (imp.sales < 0 ? "Revenue shortfall" : "Revenue ahead") : c === "gm" ? "GM" : LINE_LABEL[c],
    impact: imp[c],
  })).sort((a, b) => (gap < 0 ? a.impact - b.impact : b.impact - a.impact));
  const top = comps.slice(0, 4);
  const rest = comps.slice(4);
  const share = (v: number) => (gap === 0 ? 0 : r2(v / gap));
  const drivers: GapDriver[] = [...top.map((x) => ({ id: x.id, label: x.label, impact: x.impact, tone: toneOf(x.impact), share: share(x.impact), note: WHY_TEXT[x.id] ?? "" }))];
  if (rest.length) {
    const o = r4(sum(rest.map((x) => x.impact)));
    drivers.push({ id: "other_drivers", label: "Other", impact: o, tone: toneOf(o), share: share(o), note: WHY_TEXT.other_drivers });
  }

  /* trajectory is the full-year view, independent of the period selector */
  const fy = network({ ...ctx, period: "ytdfy27" }).models.find((x) => x.base.id === storeId)!;
  const traj: TrajectoryMetric[] = [
    trajectory("revenue", "Revenue", fy.rev, fy.revBudget, `${storeId}|rev|${ctx.scenario}`),
    trajectory("gm", "Gross Margin", fy.gmA, fy.gmB, `${storeId}|gm|${ctx.scenario}`),
    trajectory("contribution", "Contribution", fy.contribA, fy.contribB, `${storeId}|ct|${ctx.scenario}`),
  ];

  /* benchmarks */
  const all = net.models;
  const sameZone = all.filter((x) => x.base.zone === m.base.zone);
  const sameRegion = all.filter((x) => x.base.region === m.base.region);
  const sameCluster = all.filter((x) => x.base.cluster === m.base.cluster);
  const comparable = all.filter((x) => x.base.format === m.base.format && x.base.id !== m.base.id);
  const mine = group([m]);
  const groups = { company: group(all), zone: group(sameZone), region: group(sameRegion), cluster: group(sameCluster), comparable: group(comparable) };
  const higherBetter: Record<BenchmarkMetricId, boolean> = { growth: true, gm: true, opex: false, contribution: true };
  const cell = (id: BenchmarkMetricId, v: number): BenchmarkCell => {
    const delta = r2(mine[id] - v);
    return { value: r2(v), delta, tone: Math.abs(delta) < 0.05 ? "neutral" : delta > 0 === higherBetter[id] ? "good" : "bad" };
  };
  const row = (id: BenchmarkMetricId, label: string): BenchmarkRow => ({
    id,
    label,
    store: r2(mine[id]),
    company: cell(id, groups.company[id]),
    zone: cell(id, groups.zone[id]),
    region: cell(id, groups.region[id]),
    cluster: cell(id, groups.cluster[id]),
    comparable: cell(id, groups.comparable[id]),
  });

  const movements: StoreMovement[] = [
    { id: "budget_contribution", label: startLabel, amount: m.contribB, family: "margin", kind: "total" },
    { id: "actual_contribution", label: "Actual Contribution", amount: m.contribA, family: "margin", kind: "total" },
    ...impactItems.map(([id, label, v, family]) => ({ id, label, amount: v, family, kind: "impact" as const })),
    { id: "security", label: "Security", amount: imp.security, family: "cost", kind: "impact" },
    { id: "repairs", label: "Repairs & maintenance", amount: imp.repairs, family: "cost", kind: "impact" },
    { id: "other_exp", label: "Other expenses", amount: imp.other, family: "cost", kind: "impact" },
    { id: "other_drivers", label: "Other drivers", amount: r4(sum(rest.map((x) => x.impact))), family: "cost", kind: "impact" },
  ];

  return {
    store: dot,
    kpis,
    bridge,
    trajectory: traj,
    expenses,
    benchmarks: {
      rows: [row("growth", "Revenue growth"), row("gm", "GM %"), row("opex", "Opex %"), row("contribution", "Contribution %")],
      labels: { zone: `${m.base.zone} zone`, region: m.base.region, cluster: m.base.cluster, comparable: `${m.base.format} stores` },
      comparableCount: comparable.length,
    },
    why: {
      gap,
      headline: gap < 0 ? `Contribution gap ${fmtCr(gap)}` : gap > 0 ? `Contribution ahead ${fmtCr(gap, { signed: true })}` : "Contribution on plan",
      drivers,
      restIds: rest.map((x) => x.id),
    },
    movements,
    gm: { actual: m.gmA, budget: m.gmB },
    comparisonLabel: cmp.label,
  };
}

/* ───────────── drill (drawer) ───────────── */

const CHAIN: Record<string, string[]> = {
  sales_var: ["Department", "Account"],
  gm_var: ["Department", "Account"],
  payroll: ["Payroll head", "Account"],
  rent: ["Occupancy head", "Account"],
  electricity: ["Power head", "Account"],
  logistics: ["Logistics head", "Account"],
  security: ["Account"],
  repairs: ["Account"],
  other_exp: ["Account"],
};

const HEADS: Record<string, string[]> = {
  Department: DEPARTMENTS,
  "Payroll head": ["Store staff", "Supervisors", "Contract labour", "Incentives"],
  "Occupancy head": ["Base rent", "CAM charges", "Property tax"],
  "Power head": ["Grid power", "DG fuel", "AC & lighting"],
  "Logistics head": ["Inbound freight", "Inter-store transfers", "Courier & last mile"],
};

const ACCOUNTS: Record<string, [string, string][]> = {
  sales_var: [["4101", "Sales – Retail"], ["4102", "Sales returns"], ["4103", "Gift card redemptions"]],
  gm_var: [["5101", "Purchases – merchandise"], ["5102", "Markdown & discounts"], ["5103", "Shrinkage & damages"], ["5104", "Freight inward"]],
  payroll: [["6101", "Salaries & wages"], ["6102", "Overtime"], ["6103", "Incentives"], ["6104", "PF / ESI contribution"], ["6105", "Contract labour"]],
  rent: [["6201", "Store rent"], ["6202", "CAM charges"], ["6203", "Property tax"]],
  electricity: [["6241", "Grid power"], ["6242", "DG fuel"], ["6243", "AC & lighting"]],
  logistics: [["6301", "Inbound freight"], ["6302", "Transfers & handling"], ["6303", "Courier charges"]],
  security: [["6251", "Security guards"], ["6252", "CCTV & alarm maintenance"]],
  repairs: [["6351", "Building repairs"], ["6352", "Equipment AMC"], ["6353", "Fixtures & fittings"]],
  other_exp: [["6401", "Printing & stationery"], ["6402", "Communication"], ["6403", "Bank & card charges"], ["6404", "Housekeeping"]],
};

const GROUPS = new Set(["actual_contribution", "budget_contribution", "other_opex", "other_drivers"]);

interface Line {
  id: string;
  label: string;
  amount: number;
  delta: number;
}

/** P&L lines of a group movement. Rows reconcile exactly to the parent (the last cost line balances rounding). */
function linesOf(ws: StoreWorkspace, groupId: string): { lines: Line[]; levelBased: boolean } {
  const by = (id: string) => ws.movements.find((x) => x.id === id)!;
  const exp = (id: string) => ws.expenses.find((x) => x.id === id)!;
  if (groupId === "other_opex" || groupId === "other_drivers") {
    const ids = groupId === "other_opex" ? ["security", "repairs", "other_exp"] : ws.why.restIds;
    return { lines: ids.map((id) => ({ id, label: by(id).label, amount: by(id).amount, delta: by(id).amount })), levelBased: false };
  }
  const actual = groupId === "actual_contribution";
  const gmLevel = actual ? ws.gm.actual : ws.gm.budget;
  const costIds = ["payroll", "rent", "electricity", "logistics", "security", "repairs"];
  const costs = costIds.map((id) => ({ id, label: by(id).label, amount: -(actual ? exp(id).actual : exp(id).budget), delta: actual ? by(id).amount : 0 }));
  const total = actual ? by("actual_contribution").amount : by("budget_contribution").amount;
  const other = { id: "other_exp", label: "Other expenses", amount: r4(total - gmLevel - sum(costs.map((c) => c.amount))), delta: actual ? by("other_exp").amount : 0 };
  const gm = { id: "gm_var", label: "Gross margin", amount: gmLevel, delta: actual ? r4(by("sales_var").amount + by("gm_var").amount) : 0 };
  return { lines: [gm, ...costs, other], levelBased: true };
}

function rowsFor(dim: string, items: { id: string; label: string; sub?: string }[], amount: number, variance: number, impactBased: boolean, seed: string, level: DrillNode["level"]): DrillRow[] {
  const r = rng(seed);
  const w = items.map(() => Math.pow(0.15 + r(), 2.2));
  const w2 = items.map(() => Math.pow(0.15 + r(), 1.6));
  const amounts = weightedSplit(amount, w);
  const deltas = impactBased ? amounts : weightedSplit(variance, w2);
  return items
    .map((it, i) => ({
      node: { level, dim, id: `${dim}:${it.id}`, label: it.label, amount: amounts[i], variance: deltas[i] },
      amount: amounts[i],
      share: amount === 0 ? 0 : Math.min(1, Math.abs(amounts[i] / amount)),
      delta: deltas[i],
      tone: toneOf(deltas[i]),
      sublabel: it.sub,
    }))
    .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));
}

function emptyView(label: string): DrillView {
  return { title: "Store", levelLabel: "Movement", amount: null, variance: null, variancePct: null, comparisonLabel: label, tone: "neutral", explanation: "This store is not in the current network.", concentration: { headline: "—", topShares: [] }, splits: [], supportingDrivers: [], terminal: false, entityKind: "other", facts: [] };
}

const WHY_TEXT: Record<string, string> = {
  sales_var: "Footfall and conversion differ from plan; the effect is valued at budget gross margin.",
  gm_var: "Markdown depth, mix and shrinkage move gross margin away from plan.",
  payroll: "Headcount, overtime and incentive payout against the staffing plan.",
  rent: "Base rent and CAM against the lease schedule.",
  electricity: "Grid tariff, DG running hours and AC load against plan.",
  logistics: "Inbound freight and inter-store transfers against plan.",
  security: "Guarding and CCTV maintenance against plan.",
  repairs: "Repairs, AMC and fixture replacement against plan.",
  other_exp: "Printing, communication, card charges and housekeeping.",
  other_opex: "Security, repairs and other expenses together.",
  other_drivers: "The smaller drivers not listed individually.",
  actual_contribution: "Gross margin less store operating costs.",
  budget_contribution: "The comparison baseline for this store.",
};

export function buildProfitDrill(ctx: QueryCtx, _origin: DrillOrigin, nodes: DrillNode[]): DrillView {
  const cmpLabel = COMPARISONS[ctx.comparison].label;
  const si = nodes.findIndex((n) => n.dim === "Store");
  if (si < 0) return emptyView(cmpLabel);
  const ws = buildStoreWorkspace(ctx, nodes[si].id.slice("Store:".length));
  if (!ws) return emptyView(cmpLabel);
  const after = nodes.slice(si + 1);
  const mi = after.findIndex((n) => n.dim === "Movement");
  const mv = ws.movements.find((x) => x.id === (mi >= 0 ? after[mi].id.slice("Movement:".length) : "actual_contribution")) ?? ws.movements[1];
  const rest = mi >= 0 ? after.slice(mi + 1) : after;
  const last = rest[rest.length - 1];

  const isImpact = mv.kind === "impact";
  const gap = ws.why.gap;
  const baseAmount = mv.amount;
  const baseVariance = isImpact ? mv.amount : mv.id === "actual_contribution" ? gap : 0;
  const amount = last?.amount ?? baseAmount;
  const variance = last?.variance ?? baseVariance;

  let key = mv.id;
  let used: string[] = rest.map((n) => n.dim);
  let remaining: string[];
  if (GROUPS.has(mv.id)) {
    const lineNode = rest.find((n) => n.dim === "Line");
    if (lineNode) {
      key = lineNode.id.slice("Line:".length);
      used = rest.slice(rest.indexOf(lineNode) + 1).map((n) => n.dim);
      remaining = (CHAIN[key] ?? ["Account"]).filter((d) => !used.includes(d));
    } else {
      remaining = ["Line"];
    }
  } else {
    remaining = (CHAIN[key] ?? ["Account"]).filter((d) => !used.includes(d));
  }
  // a GL account is always the end of the road, even when it was chosen before the intermediate driver
  const terminal = remaining.length === 0 || last?.dim === "Account";
  const seed = `${ctx.scenario}|${ctx.period}|${ctx.comparison}|${nodes.map((n) => n.id).join(">")}`;

  /* the amount is a variance only while we are still on an impact path; level-based lines keep amount and delta apart */
  const lineMode = GROUPS.has(mv.id) && !rest.some((n) => n.dim === "Line") ? linesOf(ws, mv.id) : null;
  const impactBased = amount === variance;

  const splits: DrillSplit[] = terminal
    ? []
    : remaining.slice(0, 2).map((d) => {
        if (d === "Line" && lineMode) {
          const denom = lineMode.levelBased ? Math.abs(lineMode.lines[0].amount) : sum(lineMode.lines.map((l) => Math.abs(l.amount))) || 1;
          const rows: DrillRow[] = lineMode.lines.map((l) => ({
            node: { level: "driver", dim: "Line", id: `Line:${l.id}`, label: l.label, amount: l.amount, variance: l.delta },
            amount: l.amount,
            share: Math.min(1, Math.abs(l.amount) / denom),
            delta: l.delta,
            tone: toneOf(l.delta),
          }));
          rows.sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));
          return { dim: "Line", rows };
        }
        if (d === "Account") {
          const acc = ACCOUNTS[key] ?? ACCOUNTS.other_exp;
          return { dim: d, rows: rowsFor("Account", acc.map(([code, name]) => ({ id: code, label: `${code} · ${name}` })), amount, variance, impactBased, `${seed}|Account`, "entity") };
        }
        return { dim: d, rows: rowsFor(d, (HEADS[d] ?? []).map((name) => ({ id: name, label: name })), amount, variance, impactBased, `${seed}|${d}`, "driver") };
      });

  const primary = splits[0]?.rows ?? [];
  const shares = primary.map((r) => r.share);
  const top2 = shares.slice(0, 2).reduce((a, b) => a + b, 0);
  const label = last?.label ?? mv.label;
  const base = Math.abs(amount - variance) || Math.abs(ws.kpis[3].value - gap) || 1;
  const lead = primary.length >= 2 ? ` ${primary[0].node.label} and ${primary[1].node.label} account for ${Math.round(top2 * 100)}% of it.` : "";
  const dirWord = variance < 0 ? "adverse" : "favourable";
  const explanation = `${label} at ${ws.store.name}: ${money(variance)} ${dirWord} ${cmpLabel.toLowerCase()}. ${WHY_TEXT[key] ?? ""}${lead}`.trim();

  const acct = last?.dim === "Account" ? last.label.split(" · ") : null;
  return {
    title: label,
    levelLabel: rest.length === 0 ? "Movement" : `${last!.level === "entity" ? "Entity" : "Driver"} · ${last!.dim}`,
    amount,
    variance,
    variancePct: r2((variance / base) * 100),
    comparisonLabel: cmpLabel,
    tone: toneOf(variance),
    explanation,
    concentration: { headline: terminal ? "Single GL account — open its ledger for postings and voucher evidence" : `${Math.round(top2 * 100)}% from top 2 ${splits[0]?.dim.toLowerCase() ?? "items"}`, topShares: shares.slice(0, 5) },
    splits,
    supportingDrivers: [],
    terminal,
    entityKind: terminal ? "account" : "other",
    facts: terminal
      ? [
          { label: "Store", value: ws.store.name },
          { label: "GL account", value: acct ? acct[0] : "—" },
          { label: "Account name", value: acct ? acct[1] : label },
          { label: "Mapping status", value: "Awaiting finance mapping" },
        ]
      : [],
  };
}

/* ───────────── ledger ───────────── */

const NARR = ["Month-end accrual", "Invoice posting", "Vendor payment", "Reclassification", "Provision release"];

export function buildProfitLedger(ctx: QueryCtx, nodes: DrillNode[]): LedgerView {
  const si = nodes.findIndex((n) => n.dim === "Store");
  const storeName = si >= 0 ? nodes[si].label : "Store";
  const accNode = [...nodes].reverse().find((n) => n.dim === "Account");
  const mvNode = nodes.find((n) => n.dim === "Movement");
  const mvKey = mvNode ? mvNode.id.slice("Movement:".length) : "other_exp";
  const fallback = (ACCOUNTS[mvKey] ?? ACCOUNTS.other_exp)[0];
  const [code, name] = accNode ? accNode.label.split(" · ") : fallback;
  const credit = code.startsWith("4");
  const last = nodes[nodes.length - 1];
  const amountRs = Math.max(Math.abs((last?.amount ?? 0.01) * 1e7), 50000);
  const seed = `${ctx.scenario}|${ctx.period}|${storeName}|${code}`;
  const r = rng(seed);
  const n = 12;
  const opp = [3, 8];
  const main = weightedSplit(amountRs * 1.3, Array.from({ length: n - opp.length }, () => Math.pow(0.15 + r(), 1.5)));
  const oppAmt = weightedSplit(amountRs * 0.3, opp.map(() => 0.5 + r()));
  let mi = 0;
  let oi = 0;
  const opening = Math.round(amountRs * (0.6 + r() * 0.5));
  let bal = opening;
  const entries: LedgerEntry[] = [];
  for (let i = 0; i < n; i++) {
    const isOpp = opp.includes(i);
    const val = Math.round(isOpp ? oppAmt[oi++] : main[mi++]);
    const side = isOpp ? (credit ? "debit" : "credit") : credit ? "credit" : "debit";
    const prefix = credit ? "SV" : isOpp ? "JV" : "EJ";
    const date = new Date(Date.UTC(2026, 3, 1 + Math.floor((i / n) * 160 + r() * 10)));
    const debit = side === "debit" ? val : 0;
    const cr = side === "credit" ? val : 0;
    bal += debit - cr;
    entries.push({
      id: `E${i + 1}`,
      date: date.toISOString().slice(0, 10),
      voucherId: `${prefix}-26-${String(4000 + Math.floor(r() * 5900)).padStart(6, "0")}`,
      voucherType: prefix === "SV" ? "Sales Voucher" : prefix === "EJ" ? "Expense Journal" : "Journal Voucher",
      account: code,
      accountName: name,
      narration: `${storeName} — ${NARR[Math.floor(r() * NARR.length)]}`,
      debit,
      credit: cr,
      balance: bal,
      source: prefix === "SV" ? "Ginesys POS" : "Ginesys Finance",
      recon: r() > 0.82 ? "exception" : r() > 0.5 ? "pending" : "matched",
    });
  }
  return { title: `GL ${code} · ${name}`, subtitle: ["Profitability", ...nodes.filter((x) => x.dim !== "Quadrant").map((x) => x.label)].join(" › "), openingBalance: opening, closingBalance: bal, entries };
}

export type { QuadrantId };
