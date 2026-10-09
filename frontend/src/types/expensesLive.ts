import type { MgmtEntity, MgmtMode } from "./mgmtLive";

/**
 * Shapes served by the Store / DC Expense API (/api/v1/mgmt/expenses). Money is INR Crore as a JSON number, expenses POSITIVE (a net credit is negative).
 * null means "no value" (shown as an em dash with the reason), never zero.
 */
export type ExpScope = "store" | "dc" | "ho";
export type ExpMode = MgmtMode;
export type ExpEntity = MgmtEntity;
/** The legal entity of a site: SUBCO = Citykart Stores (gold RETAIL), HOLDCO = Citykart Ventures (gold VENTURES). Site codes collide between them. */
export type SiteEntity = "SUBCO" | "HOLDCO";
export type VoucherEntity = "RETAIL" | "VENTURES";

export interface ExpTriple {
  book: number;
  adjustment: number;
  total: number;
}

export interface ExpMom {
  last_month: string;
  prev_month: string;
  last: number;
  prev: number;
  delta: number;
  delta_pct: number | null;
}

export interface ExpLy {
  total: number;
  book: number;
  delta: number;
  delta_pct: number | null;
  delta_pct_book: number | null;
  pct_ns: number | null;
  pct_ns_delta_pp: number | null;
}

export interface ExpHeadRow extends ExpTriple {
  key: string;
  label: string;
  pct_ns: ExpTriple | null;
  share_pct: number | null;
  per_site_avg: number | null;
  mom: ExpMom | null;
  ly: ExpLy | null;
}

export interface ExpControlRow {
  layer: ExpMode;
  store: number;
  dc: number;
  ho: number;
  sum_of_scopes: number;
  mgmt_pnl: number;
  variance: number;
  ok: boolean;
}

export interface ExpControlsEngine {
  tolerance_cr: number;
  basis: string;
  rows: ExpControlRow[];
  ok: boolean;
}

export interface ExpHeader {
  run_id: string;
  as_of_date: string;
  entity: ExpEntity;
  scope: ExpScope;
  scope_label: string;
  from_month: string;
  to_month: string;
  months: string[];
  currency_note?: string;
}

export interface ExpSummary extends ExpHeader {
  entity_label: string;
  net_sales: number | null;
  site_count: number | null;
  heads: ExpHeadRow[];
  total: ExpHeadRow;
  ly_available: boolean;
  ly_from_month: string | null;
  ly_to_month: string | null;
  adjustment_months: string[];
  controls: ExpControlsEngine;
  notes: string[];
  warnings: string[];
}

export interface ExpTrend extends ExpHeader {
  series: { key: string; label: string; values: Record<string, ExpTriple> }[];
  total: Record<string, ExpTriple>;
  net_sales: Record<string, number> | null;
  pct_ns: Record<string, number | null> | null;
  ly_total: Record<string, number | null>;
  note: string;
}

export interface ExpFlag {
  code: string;
  text: string;
}

export interface ExpSite {
  key: string;
  entity: SiteEntity;
  entity_label: string;
  voucher_entity: VoucherEntity;
  site_code: number;
  short_name: string | null;
  name: string | null;
  site_kind: string | null;
  store_type: string | null;
  state: string | null;
  city: string | null;
  opening_date: string | null;
  nso_ty: boolean;
  area_sqft: number | null;
  net_sales: number | null;
  months_with_sales: number | null;
  book: number;
  adjustment: number;
  total: number;
  heads: Record<string, ExpTriple>;
  pct_ns: number | null;
  pct_ns_heads: Record<string, number | null>;
  per_sqft_month: number | null;
  share_pct: number | null;
  vs_peer_pp: number | null;
  vs_peer_ratio: number | null;
  rank: number | null;
  mom_pct: number | null;
  last_month: number | null;
  prev_month: number | null;
  flags: ExpFlag[];
}

export interface ExpPeer {
  n: number;
  basis: "pct_of_net_sales" | "total_cr";
  head: string | null;
  median_pct?: number | null;
  p90_pct?: number | null;
  median_cr?: number | null;
  heads: Record<string, { median_pct: number | null; p90_pct: number | null }>;
  method: string;
  ranked_stores: number;
}

export interface ExpSites extends ExpHeader {
  head: string | null;
  head_label: string | null;
  net_sales: number | null;
  sites: ExpSite[];
  peer: ExpPeer;
  parent: { total: number };
  children_sum: { total: number };
  unallocated: { total: number; note: string };
  reconciles: boolean;
  area_note: string;
  flag_legend: Record<string, string>;
}

export interface ExpLedgerRow {
  kind: "ledger" | "site";
  amount_cr: number;
  lines: number;
  share_pct: number | null;
  months_active: number;
  ledger_code: number;
  ledger_name: string;
  head: string;
  head_label?: string;
  mgmt_group?: string;
  sites?: number;
  pct_ns?: number | null;
  site_code: number | null;
  site_entity?: SiteEntity | null;
  site_name?: string | null;
  voucher_entity: VoucherEntity | null;
}

export interface ExpAdjustmentRow {
  id: string;
  month: string;
  head: string;
  head_label: string;
  amount_cr: number;
  kind: string;
  status: string;
  rule: string;
  note: string;
  entity: string;
  provisional: boolean;
}

export interface ExpLedgers extends ExpHeader {
  head: string | null;
  head_label: string | null;
  site: number | null;
  site_entity: SiteEntity | null;
  glcode: number | null;
  grain: "ledger" | "site";
  rows: ExpLedgerRow[];
  row_count: number;
  truncated: boolean;
  adjustments: ExpAdjustmentRow[];
  allocated_adjustment: { amount_cr: number; note: string } | null;
  parent: { total: number; book: number | null };
  children_sum: { total: number };
  reconciles: boolean | null;
  voucher_note: string;
}

export interface ExpRule {
  id: string;
  title: string;
  text: string;
  count: number;
}

export interface ExpException {
  rule_id: string;
  severity: "high" | "medium" | "low";
  entity: SiteEntity;
  voucher_entity: VoucherEntity | null;
  site_code: number | null;
  site_name: string | null;
  head: string | null;
  head_label: string | null;
  ledger_code: number | null;
  ledger_name: string | null;
  month: string | null;
  amount_cr: number | null;
  metric: string;
  from_month: string;
  to_month: string;
  likely_intercompany?: boolean;
}

export interface ExpExceptions extends ExpHeader {
  rules: ExpRule[];
  counts: Record<string, number>;
  total: number;
  exceptions: ExpException[];
  truncated: boolean;
  mom_threshold: number;
  note: string;
}

export interface ExpQuery {
  scope: ExpScope;
  entity: ExpEntity;
  from_month?: string;
  to_month?: string;
}
