/**
 * Stage 3: Store Profitability contracts. Amounts are ₹ Crore; margins and growth are percentages.
 * The UI never derives a business value: quadrants, drivers, ranks and benchmark deltas are all supplied.
 */
import type { Bridge, ForecastMonth, Family, Tone } from "./cfo";

export type QuadrantId = "grow" | "fix" | "defend" | "turnaround";

export const QUADRANT_ORDER: QuadrantId[] = ["grow", "fix", "defend", "turnaround"];

/** X = revenue growth, Y = contribution margin. Right/top is better. */
export const QUADRANT_META: Record<QuadrantId, { label: string; rule: string; action: string }> = {
  grow: { label: "Grow & Protect", rule: "Growth above network, margin above network", action: "Invest, protect margin" },
  fix: { label: "Fix Economics", rule: "Growth above network, margin below network", action: "Growing, but not earning: fix cost and margin" },
  defend: { label: "Defend", rule: "Growth below network, margin above network", action: "Profitable but slowing: defend traffic" },
  turnaround: { label: "Turnaround", rule: "Growth below network, margin below network", action: "Weak on both: turnaround plan or review" },
};

export interface StoreDot {
  id: string;
  name: string;
  zone: string;
  region: string;
  cluster: string;
  format: "Large format" | "Standard format";
  /** ₹ Cr, selected period */
  revenue: number;
  /** year-on-year, % */
  revenueGrowthPct: number;
  gmPct: number;
  contributionMarginPct: number;
  contribution: number;
  /** contribution minus the selected comparison, ₹ Cr signed */
  contributionVsComparison: number;
  quadrant: QuadrantId;
}

export interface QuadrantSummary {
  id: QuadrantId;
  label: string;
  count: number;
  revenue: number;
  contribution: number;
}

export interface ProfitPortfolio {
  stores: StoreDot[];
  company: {
    revenue: number;
    revenueGrowthPct: number;
    gmPct: number;
    contributionMarginPct: number;
    contribution: number;
    contributionVsComparison: number;
  };
  /** the quadrant lines: network growth and network contribution margin */
  split: { growthPct: number; marginPct: number };
  quadrants: QuadrantSummary[];
  headline: string;
  comparisonLabel: string;
  basisNote: string;
}

/* ───────────── store workspace ───────────── */

export interface StoreKpi {
  id: "revenue" | "gm" | "opex" | "contribution" | "contributionPct";
  label: string;
  value: number;
  unit: "cr" | "pct";
  /** secondary line, e.g. "41.2% of revenue" */
  sub: string;
  /** vs comparison: ₹ Cr for cr, percentage points for pct */
  variance: number;
  tone: Tone;
}

/** Every clickable movement on the page (bridge bar, expense, driver) resolves to one of these. */
export interface StoreMovement {
  id: string;
  label: string;
  /** signed contribution impact vs the comparison, ₹ Cr (negative = adverse); totals carry their level */
  amount: number;
  family: Family;
  kind: "total" | "impact";
}

export interface ExpenseLine {
  id: string;
  label: string;
  actual: number;
  budget: number;
  /** contribution impact vs comparison, ₹ Cr (negative = overspend) */
  impact: number;
  pctOfRevenue: number;
  overPct: number;
  tone: Tone;
}

export interface TrajectoryMetric {
  id: "revenue" | "gm" | "contribution";
  label: string;
  months: ForecastMonth[];
  landing: number;
  budgetFy: number;
  /** landing minus full-year comparison, ₹ Cr signed */
  gap: number;
}

export type BenchmarkMetricId = "growth" | "gm" | "opex" | "contribution";

export interface BenchmarkCell {
  value: number;
  /** store minus benchmark, percentage points */
  delta: number;
  tone: Tone;
}

export interface BenchmarkRow {
  id: BenchmarkMetricId;
  label: string;
  store: number;
  company: BenchmarkCell;
  zone: BenchmarkCell;
  region: BenchmarkCell;
  cluster: BenchmarkCell;
  comparable: BenchmarkCell;
}

export interface BenchmarkTable {
  rows: BenchmarkRow[];
  labels: { zone: string; region: string; cluster: string; comparable: string };
  comparableCount: number;
}

export interface GapDriver {
  id: string;
  label: string;
  impact: number;
  tone: Tone;
  /** share of the contribution gap; negative means the driver offsets part of it */
  share: number;
  note: string;
}

export interface GapExplanation {
  gap: number;
  headline: string;
  drivers: GapDriver[];
  /** movements folded into the "Other" driver, so that row can be drilled without losing them */
  restIds: string[];
}

export interface StoreWorkspace {
  store: StoreDot;
  kpis: StoreKpi[];
  bridge: Bridge;
  trajectory: TrajectoryMetric[];
  expenses: ExpenseLine[];
  benchmarks: BenchmarkTable;
  why: GapExplanation;
  movements: StoreMovement[];
  /** gross margin level (₹ Cr) actual and against the comparison, used by the P&L drill */
  gm: { actual: number; budget: number };
  comparisonLabel: string;
}
