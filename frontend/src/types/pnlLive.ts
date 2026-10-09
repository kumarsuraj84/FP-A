/** Shapes served by the read-only P&L actuals API. Money and percentages are exact decimal TEXT; only the display converts them. */
export type PnlDataState = "verified_candidate" | "live" | "superseded" | "withdrawn";
export type Basis = "all" | "posted";

export interface PnlHeader {
  run_id: string;
  as_of_date: string;
  cogs_last_bill_date: string;
  recon_state: string;
  publication_state: string;
  data_state: PnlDataState;
  data_state_label: string;
  contract_version: string;
  source_updated_at: string;
  budget: null;
  budget_note: string;
}

export interface PnlMoney {
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
  /** MIS chain extras (books basis): Other operating income is inside gross_margin; DC and HO cost are outside the stores. Optional so older payloads still parse. */
  other_operating_income?: string;
  interest_income?: string;
  dc_cost?: string;
  ho_cost?: string;
  total_corporate_cost?: string;
  corporate_ebitda?: string;
  corporate_ebitda_pct?: string | null;
}

export interface PnlScope {
  from_month: string;
  to_month: string;
  basis: Basis;
  basis_label: string;
  filters: Record<string, string>;
  partial_last_month: boolean;
}

export interface PnlFlags {
  provisional_months: string[];
  cogs_through: string;
  books_through: string;
  cogs_lags_books: boolean;
  partial_last_month: boolean;
  cogs_has_no_posting_status: string;
  contribution_definition: string;
  basis_note?: string;
  chain?: string;
  sites_with_cogs_sales_but_no_books_sales?: number;
}

export interface PnlLine {
  section: "REVENUE" | "COGS_BOOKS" | "STORE_OPEX" | "DC_COST" | "HO_COST" | "OTHER_INCOME" | "FINANCE_COST";
  section_label: string;
  group_label: string;
  /** MIS display name of the group, and the MIS line it rolls up to (the raw group_label stays for tooltips and drills) */
  group_name?: string;
  mis_line?: string | null;
  amount: string;
  ledgers: number;
}

export interface PnlComparison {
  period: { from_month: string; to_month: string };
  current: PnlMoney;
  last_year: (PnlMoney & { period: { from_month: string; to_month: string } }) | null;
  growth: { revenue_pct: string | null; gross_margin_pct: string | null; contribution_pct: string | null } | null;
  note: string;
}

export interface PnlSummary extends PnlHeader {
  scope: PnlScope;
  stores_in_scope: number;
  totals: PnlMoney;
  comparison: PnlComparison | null;
  lines: PnlLine[];
  below_contribution: { other_income: string; finance_cost: string; after_below_the_line: string; interest_income?: string; corporate_ebitda?: string };
  excluded_unmapped: { ledgers: number; run_ledgers: number; label: string; net: string; gross_abs: string; note: string; inventory_flow_ledgers?: number; inventory_flow_net?: string };
  flags: PnlFlags;
  reconciliation?: {
    parent: { revenue: string; contribution: string };
    children_sum: { revenue: string; contribution: string };
    stores: PnlMoney;
    non_store: PnlMoney;
    reconciles: boolean;
  };
}

export interface PnlTrendRow extends PnlMoney {
  month: string;
  provisional: boolean;
  partial: boolean;
  last_year: ({ month: string } & PnlMoney) | null;
  growth_revenue_pct: string | null;
}

export interface PnlTrend extends PnlHeader {
  scope: PnlScope;
  months: PnlTrendRow[];
  parent: { revenue: string; contribution: string };
  children_sum: { revenue: string; contribution: string };
  reconciles: boolean;
  flags: PnlFlags;
}

export interface PnlStoreRow extends PnlMoney {
  site_code: string;
  store_name: string | null;
  region: string | null;
  cluster: string | null;
  state: string | null;
  vintage: string | null;
  status: string | null;
  rank: number;
  last_year_revenue: string | null;
  last_year_contribution: string | null;
  growth_pct: string | null;
}

export interface PnlStorePage extends PnlHeader {
  scope: PnlScope;
  stores_total: number;
  returned: number;
  limit: number;
  offset: number;
  sort: string;
  order: "asc" | "desc";
  stores: PnlStoreRow[];
  growth_basis: { from_month: string; to_month: string; note: string };
  parent: { revenue: string; contribution: string };
  children_sum: { revenue: string; contribution: string };
  reconciles: boolean;
  flags: PnlFlags;
}

export interface PnlStore extends PnlHeader {
  scope: PnlScope;
  site: { site_code: string; store_name: string | null; region: string | null; cluster: string | null; state: string | null; vintage: string | null; status: string | null; opening_date: string | null; last_bill_date: string | null; is_store: boolean };
  totals: PnlMoney;
  comparison: PnlComparison | null;
  months: ({ month: string } & PnlMoney)[];
  lines: PnlLine[];
  reconciles: boolean;
  flags: PnlFlags;
}

export interface PnlGroupLedgers extends PnlHeader {
  /** the period and basis the amounts are for (the voucher list must use the same) */
  scope?: { from_month: string; to_month: string; basis: Basis };
  site_code: string;
  group_label: string;
  ledgers: { glcode: string; ledger_name: string; amount: string; lines: number; months: { month: string; amount: string }[] }[];
  parent: { amount: string };
  children_sum: { amount: string };
  reconciles: boolean;
}

export interface PnlOption {
  value: string;
  stores: number;
  revenue: string;
  contribution: string;
}
export interface PnlHierarchy extends PnlHeader {
  options: { region: PnlOption[]; cluster: PnlOption[]; state: PnlOption[]; vintage: PnlOption[]; status: PnlOption[] };
  stores: number;
}

export interface PnlReconciliation extends PnlHeader {
  tolerance_rupees: string;
  sales_tieout: {
    basis: string;
    months: { month: string; site_months: number; tied: number; books_sales: string; table_sales: string; difference: string; max_abs_difference: string }[];
    site_months: number;
    tied: number;
    not_tied: number;
    largest_gaps: { site_code: string; store_name: string | null; month: string; books_sales: string; cogs_table_sales_ex_gst: string; difference: string }[];
  };
  excluded_unmapped: { label: string; run_ledgers: number; explanation: string; count: number; net: string; gross_abs: string; inventory_flow_ledgers?: number; inventory_flow_net?: string; ledgers: { glcode: string; ledger_name: string; net: string; debit: string; credit: string; sites: number }[] };
  sites_without_books_sales: { count: number; sales_ex_gst: string; sites: { site_code: string; store_name: string | null; sales_ex_gst: string; cogs: string }[] };
  flags: PnlFlags;
}

export interface PnlQuery {
  from_month?: string;
  to_month?: string;
  basis: Basis;
  region?: string;
  cluster?: string;
  state?: string;
  vintage?: string;
  status?: string;
}
