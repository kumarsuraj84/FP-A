/** Shapes served by the P&L REVIEW endpoints. Money and percentages are exact decimal TEXT; only the display converts them. */
import type { PnlHeader, PnlScope } from "./pnlLive";

export interface ReviewMoney {
  revenue: string;
  cogs: string;
  cogs_books: string;
  gross_margin: string;
  gross_margin_pct: string | null;
  opex: string;
  opex_pct: string | null;
  contribution: string;
  contribution_pct: string | null;
  other_income: string;
  finance_cost: string;
}

export interface ComparisonWindow {
  id: "mtd" | "qtd" | "ytd";
  label: string;
  from_month: string;
  to_month: string;
  day_aligned: boolean;
  ty: ReviewMoney;
  ly: ReviewMoney | null;
  growth: { revenue_pct: string | null; gross_margin_pct: string | null; contribution_pct: string | null; gm_bps: string | null; opex_bps: string | null; contribution_bps: string | null } | null;
}
export interface PnlComparisonResponse extends PnlHeader {
  scope: PnlScope;
  mode: "stores" | "company";
  as_of: string;
  partial_month: boolean;
  aligned_days: number | null;
  windows: ComparisonWindow[];
  note: string;
}

export interface PivotColumn {
  id: string;
  label: string;
  kind: "month" | "quarter" | "ytd";
  partial: boolean;
  from_month: string;
  to_month: string;
}
export interface PivotRow {
  id: string;
  label: string;
  kind: "line" | "subtotal" | "group" | "memo";
  level: number;
  group: string | null;
  cells: Record<string, string | null>;
  ly_ytd: string | null;
  variance: string | null;
  variance_pct: string | null;
}
export interface PnlPivot extends PnlHeader {
  scope: PnlScope;
  mode: "stores" | "company";
  stores: number;
  columns: PivotColumn[];
  rows: PivotRow[];
  ly_ytd_available: boolean;
  ly_ytd_note: string;
  unmapped_note: string;
}
export interface PivotLedger {
  glcode: string;
  ledger_name: string;
  cells: Record<string, string>;
  ly_ytd: string;
}
export interface PnlPivotLedgers extends PnlHeader {
  group: string;
  ledgers: PivotLedger[];
}

export interface ExpenseLine {
  group: string;
  label: string;
  cost: string;
  pct_of_sales: string | null;
  ly_cost: string | null;
  ly_pct_of_sales: string | null;
  bps: string | null;
  psf: string | null;
  ly_psf: string | null;
  psf_stores: number;
  trend: { month: string; cost: string; pct_of_sales: string | null }[];
}
export interface PnlExpenses extends PnlHeader {
  scope: PnlScope;
  months: string[];
  ly_months: string[] | null;
  revenue?: string;
  ly_revenue?: string | null;
  stores: number;
  stores_with_area: number;
  lines: ExpenseLine[];
  psf_note: string;
  note?: string;
}

export interface HeatRow {
  rank: number;
  site_code: string;
  store_name: string | null;
  region: string | null;
  cluster: string | null;
  state: string | null;
  vintage: string | null;
  area: string | null;
  opportunity: string | null;
  peer_basis: string;
  revenue: string;
  gross_margin_pct: string | null;
  opex_pct: string | null;
  contribution: string;
  contribution_pct: string | null;
  growth_pct: string | null;
  sales_psf: string | null;
  payroll_psf: string | null;
  rent_psf: string | null;
  power_psf: string | null;
  ly_contribution_pct: string | null;
  contribution_bps: string | null;
  gm_bps: string | null;
  opex_bps: string | null;
}
export interface HeatScale {
  p10?: string | null;
  p50?: string | null;
  p90?: string | null;
  n: number;
  higher_is_better?: boolean;
}
export interface PnlHeatmap extends PnlHeader {
  scope: PnlScope;
  sorts: string[];
  stores_total: number;
  returned: number;
  sort: string;
  stores: HeatRow[];
  scales: Record<string, HeatScale>;
  months: string[];
  note: string;
}

export interface PeerMetric {
  metric: string;
  store: string | null;
  peer_median: string | null;
  top_quartile: string | null;
  bottom_quartile: string | null;
  peers_with_value: number;
  position: "top quartile" | "middle" | "bottom quartile" | null;
  vs_median: string | null;
}
export interface PeerGroup {
  dimension: string;
  basis: string;
  requested: string;
  peers: number;
  metrics: PeerMetric[];
}
export interface PnlPeers extends PnlHeader {
  site_code: string;
  keys: Record<string, string | null>;
  groups: PeerGroup[];
  rules: { peers: string };
}

export type Severity = "Critical" | "High" | "Medium";
export interface ExpenseException {
  severity: Severity;
  site_code: string;
  store_name: string | null;
  region: string | null;
  state: string | null;
  group: string;
  label: string;
  month: string;
  current: string;
  expected: string;
  variance: string;
  variance_pct: string | null;
  pct_of_sales: string | null;
  psf: string | null;
  peer_pct_of_sales: string | null;
  peer_psf: string | null;
  flags: string[];
  why: string;
  impact: string;
  provisional_month: boolean;
}
export interface RevenueException {
  severity: Severity;
  site_code: string;
  store_name: string | null;
  region: string | null;
  state: string | null;
  month: string;
  revenue: string;
  baseline_revenue: string | null;
  growth_pct: string | null;
  gross_margin_pct: string | null;
  contribution: string;
  sales_psf: string | null;
  flags: string[];
  why: string;
  impact: string;
  provisional_month: boolean;
}
export interface PnlExceptions<T> extends PnlHeader {
  scope: PnlScope;
  month: string | null;
  total: number;
  by_severity: Partial<Record<Severity, number>>;
  exceptions: T[];
  rules: Record<string, string>;
  provisional_month?: boolean;
  note?: string;
}

export interface PnlQuality extends PnlHeader {
  stores: number;
  stores_without_area: { count: number; sites: { site_code: string; store_name: string | null }[]; effect: string };
  stores_with_placeholder_opening_date: { count: number; effect: string };
  closed_stores_without_a_closing_date: { count: number; sites: { site_code: string; store_name: string | null; status: string }[]; effect: string };
  effective_area_reasons: { reason: string; n: number }[];
  cogs_pct_by_month: { month: string; cogs_pct_of_sales: string | null; outlier: boolean }[];
  cogs_typical_pct: string | null;
  area_units_note: string;
}
