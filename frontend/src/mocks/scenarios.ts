import type { ComparisonId, PeriodId, ScenarioId, Severity } from "@/types/cfo";

/** All ₹ values are Crore. Base numbers describe YTD FY26-27 vs Budget; periods scale flows by `k`. */
export interface ScenarioParams {
  label: string;
  blurb: string;
  cash: number;
  cashPlanDelta: number; // actual cash minus plan cash (YTD)
  cashMin: number;
  inflow30: number;
  events: { day: number; amount: number; label: string }[];
  revenue: number;
  revDelta: number;
  gmPct: number;
  gmBps: number; // vs plan, negative = below
  budgetProfit: number;
  deltas: { salesVolume: number; gm: number; payroll: number; occupancy: number; electricity: number; productivity: number };
  cashFlows: { opEarnings: number; inventory: number; creditors: number; advances: number; receivables: number; otherWc: number; capex: number };
  creditors: number;
  creditors181: number;
  creditors181Vendors: number;
  creditorsOldest: number;
  advances: number;
  adv90: number;
  advVendors: number;
  advOldest: number;
  advMtd: number;
  unrec: number;
  unrecMtd: number;
  unrecAccounts: number;
  unrecOldest: number;
  gmImpactEst: number;
  gmTop2: number;
  fcBudgetFy: number;
  fcSales: number;
  fcMargin: number;
  fcCost: number;
  fcRecovery: number;
  sev: { liquidity: Severity; gm: Severity; payables: Severity; advances: Severity; recon: Severity };
}

const normal: ScenarioParams = {
  label: "Normal",
  blurb: "Balanced position: modest margin leakage, healthy liquidity",
  cash: 48.6,
  cashPlanDelta: -3.4,
  cashMin: 30,
  inflow30: 62.0,
  events: [
    { day: 2, amount: 9.8, label: "Payroll run" },
    { day: 9, amount: 14.5, label: "Vendor payment run" },
    { day: 17, amount: 8.6, label: "GST & statutory" },
    { day: 24, amount: 12.4, label: "Vendor payment run" },
    { day: 28, amount: 6.0, label: "Rent & CAM" },
  ],
  revenue: 612.4,
  revDelta: 10.9,
  gmPct: 41.2,
  gmBps: -120,
  budgetProfit: 42.1,
  deltas: { salesVolume: -0.85, gm: -1.42, payroll: -0.64, occupancy: 0.31, electricity: -0.22, productivity: 0.88 },
  cashFlows: { opEarnings: 38.9, inventory: -21.6, creditors: 16.4, advances: -9.8, receivables: -2.1, otherWc: -1.9, capex: -12.5 },
  creditors: 214.8,
  creditors181: 18.4,
  creditors181Vendors: 12,
  creditorsOldest: 341,
  advances: 27.4,
  adv90: 3.2,
  advVendors: 8,
  advOldest: 287,
  advMtd: 1.1,
  unrec: 6.8,
  unrecMtd: 0.9,
  unrecAccounts: 14,
  unrecOldest: 46,
  gmImpactEst: 1.7,
  gmTop2: 62,
  fcBudgetFy: 103.9,
  fcSales: -2.2,
  fcMargin: -3.1,
  fcCost: -1.3,
  fcRecovery: 1.6,
  sev: { liquidity: "low", gm: "medium", payables: "medium", advances: "medium", recon: "medium" },
};

export const SCENARIOS: Record<ScenarioId, ScenarioParams> = {
  normal,
  cash_pressure: {
    ...normal,
    label: "Cash Pressure",
    blurb: "Inventory build and payment runs pull cash below the operating minimum",
    cash: 34.2,
    cashPlanDelta: -14.8,
    inflow30: 44.0,
    events: [
      { day: 2, amount: 9.8, label: "Payroll run" },
      { day: 9, amount: 18.2, label: "Vendor payment run" },
      { day: 17, amount: 8.6, label: "GST & statutory" },
      { day: 24, amount: 12.4, label: "Vendor payment run" },
      { day: 28, amount: 6.0, label: "Rent & CAM" },
    ],
    deltas: { salesVolume: -1.9, gm: -1.6, payroll: -0.64, occupancy: 0.31, electricity: -0.22, productivity: 0.2 },
    cashFlows: { opEarnings: 36.1, inventory: -27.9, creditors: 6.2, advances: -9.8, receivables: -3.4, otherWc: -2.6, capex: -14.4 },
    creditors: 196.2,
    unrec: 7.4,
    sev: { liquidity: "critical", gm: "medium", payables: "medium", advances: "medium", recon: "medium" },
    fcSales: -4.4,
    fcMargin: -3.6,
  },
  aged_creditors: {
    ...normal,
    label: "Aged Creditors",
    blurb: "Payables stretched; a long tail of 181+ day balances",
    cash: 55.8,
    cashPlanDelta: 2.1,
    cashFlows: { opEarnings: 38.9, inventory: -21.6, creditors: 29.3, advances: -9.8, receivables: -2.1, otherWc: -1.9, capex: -12.5 },
    creditors: 268.4,
    creditors181: 46.3,
    creditors181Vendors: 31,
    creditorsOldest: 412,
    unrec: 8.1,
    sev: { liquidity: "medium", gm: "medium", payables: "critical", advances: "medium", recon: "medium" },
  },
  vendor_advance_risk: {
    ...normal,
    label: "Vendor Advance Risk",
    blurb: "Old vendor advances not adjusted against supplies",
    cash: 38.9,
    cashPlanDelta: -9.6,
    cashFlows: { opEarnings: 38.9, inventory: -21.6, creditors: 16.4, advances: -17.7, receivables: -2.1, otherWc: -1.9, capex: -12.5 },
    advances: 41.9,
    adv90: 11.6,
    advVendors: 19,
    advOldest: 412,
    advMtd: 4.8,
    sev: { liquidity: "medium", gm: "medium", payables: "medium", advances: "critical", recon: "medium" },
  },
  margin_pressure: {
    ...normal,
    label: "Margin Pressure",
    blurb: "Markdown depth and mix shift erode gross margin",
    gmPct: 37.9,
    gmBps: -310,
    deltas: { salesVolume: -0.6, gm: -3.84, payroll: -0.64, occupancy: 0.31, electricity: -0.22, productivity: 0.4 },
    gmImpactEst: 5.1,
    gmTop2: 71,
    revDelta: 4.2,
    cash: 44.1,
    cashPlanDelta: -7.9,
    sev: { liquidity: "medium", gm: "critical", payables: "medium", advances: "medium", recon: "medium" },
    fcMargin: -9.2,
    fcRecovery: 1.1,
  },
};

export const SCENARIO_ORDER: ScenarioId[] = ["normal", "cash_pressure", "aged_creditors", "vendor_advance_risk", "margin_pressure"];

export const PERIODS: Record<PeriodId, { label: string; short: string; k: number }> = {
  sep26: { label: "Sep 2026 (month)", short: "Sep 26", k: 0.16 },
  q2fy27: { label: "Q2 FY27 (Jul–Sep)", short: "Q2 FY27", k: 0.46 },
  ytdfy27: { label: "YTD FY27 (Apr – 3 Oct)", short: "YTD FY27", k: 1 },
};

export const COMPARISONS: Record<ComparisonId, { label: string; short: string; c: number; startLabel: string }> = {
  budget: { label: "vs Budget", short: "Budget", c: 1, startLabel: "Budget Profit" },
  ly: { label: "vs Last Year", short: "Last Year", c: 0.7, startLabel: "Last Year Profit" },
  forecast: { label: "vs Last Forecast", short: "Last Forecast", c: 0.35, startLabel: "Last Forecast Profit" },
};

export const PERIOD_ORDER: PeriodId[] = ["sep26", "q2fy27", "ytdfy27"];
export const COMPARISON_ORDER: ComparisonId[] = ["budget", "ly", "forecast"];
