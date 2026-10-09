/* Related Party Transactions (intercompany): shapes of GET /api/v1/related-party/summary and /items. Money is exact decimal text in RUPEES; `*_cr` is crore. */
import type { AgeBucketRow, DueStateRow, ItemPage, Money } from "./creditorsLive";

export type RelatedStatus = "proposed" | "confirmed";

export interface RelatedParty {
  sub_ledger_code: number;
  party_name: string;
  group_entity: string;
  relationship: string; // group company | cross charge
  status: RelatedStatus;
  basis: string;
  note: string;
  payable: Money;
  debit_balance: Money;
  net: Money;
  payable_cr: Money;
  debit_balance_cr: Money;
  net_cr: Money;
  items: number;
  oldest_doc: string | null;
  max_age_days: number | null;
  ageing: Record<string, Money>; // D0_30 … D365_PLUS, UNCLASSIFIED
}

export interface RelatedCandidate {
  sub_ledger_code: number;
  party_name: string;
  class_name: string | null;
  is_extinct: boolean;
  open_items: number;
  payable: Money;
  debit_balance: Money;
  reason: string;
}

export interface RelatedLoans {
  available: boolean;
  reason: string | null;
  tables: { table: string; returned: number; columns: string[] }[];
  rows: Record<string, unknown>[];
  /** "ledger" when derived from the ledger lists (voucher_lines). The headline numbers are cost-tagged lines since 2025-04, a partial view, NOT the loan balance. */
  source?: "ledger" | "none";
  basis?: string;
  net_movement_cr?: Money;
  drawn_cr?: Money;
  repaid_cr?: Money;
  mirrors?: boolean;
  variance_cr?: Money;
  balance_note?: string;
  coverage_from?: string | null;
  balance_source?: string;
  full_history?: boolean;
  holdco_balance_cr?: Money;
  subco_balance_cr?: Money;
}

export interface RelatedGlSideTotals {
  entries: number;
  lines: number;
  debit: Money;
  credit: Money;
  net: Money;
  debit_cr: Money;
  credit_cr: Money;
  net_cr: Money;
}

export interface RelatedGlHeadline {
  source?: string;
  entries: number;
  by_entity: { RETAIL: RelatedGlSideTotals; VENTURES: RelatedGlSideTotals };
  same_company: RelatedGlSideTotals;
  mirror_mirrors: boolean;
  mirror_debit_vs_credit_cr: Money;
  mirror_credit_vs_debit_cr: Money;
}

export interface RelatedControls {
  main_plus_related_equals_all: boolean;
  variance: Money;
  variance_cr: Money;
  debit_variance: Money;
  net_variance: Money;
  main_payable: Money;
  related_payable: Money;
  all_payable: Money;
  main_payable_cr: Money;
  related_payable_cr: Money;
  all_payable_cr: Money;
  main_debit_balance: Money;
  related_debit_balance: Money;
  all_debit_balance: Money;
}

export interface RelatedSummary {
  as_of_date: string;
  extraction_run_id: string;
  currency: string;
  register: { path_exists: boolean; parties: number; proposed: number; confirmed: number };
  creditors: {
    payable: Money;
    debit_balance: Money;
    net: Money;
    payable_cr: Money;
    debit_balance_cr: Money;
    net_cr: Money;
    parties: number;
    items: number;
    by_party: RelatedParty[];
    by_age: AgeBucketRow[];
    by_due_status: DueStateRow[];
  };
  loans: RelatedLoans;
  related_party_gl?: RelatedGlHeadline;
  candidates: RelatedCandidate[];
  controls: RelatedControls;
}

export type RelatedItems = Omit<ItemPage, "vendor_ref" | "named"> & { as_of_date: string; sub_ledger_code: number; party_name: string };

/* ---- GET /intercompany (derived from the ledger) ---- */
export interface IcLedger {
  glcode: number;
  glname: string;
  role: string;
  side: string;
  status: RelatedStatus;
  note: string;
  compared: boolean;
  lines: number;
  dr_cr: Money;
  cr_cr: Money;
  net_cr: Money;
}

export interface IcMonth {
  month: string;
  holdco_dr_cr: Money;
  holdco_cr_cr: Money;
  subco_dr_cr: Money;
  subco_cr_cr: Money;
  holdco_net_cr: Money;
  subco_net_cr: Money;
  difference_cr: Money;
  matches: boolean;
}

export interface IcSide {
  ledgers: IcLedger[];
  net_cr: Money;
  dr_cr: Money;
  cr_cr: Money;
}

export interface IcFy {
  fy: string;
  holdco_net_cr: Money;
  subco_net_cr: Money;
  difference_cr: Money;
  matches: boolean;
  one_sided: boolean;
}

export interface IcPair {
  pair_id: string;
  source: string | null;
  by_fy: IcFy[];
  label: string;
  configured: boolean;
  holdco: IcSide;
  subco: IcSide;
  totals: { holdco_net_cr: Money; subco_net_cr: Money; difference_cr: Money; mirrors: boolean };
  monthly: IcMonth[];
  notes: string[];
}

export interface IcReportedLedger {
  entity: string;
  side: string;
  glcode: number;
  glname: string;
  lines: number | null;
  amount_cr: Money | null;
  drcr: "Dr" | "Cr" | null;
  last_entry: string | null;
  approx: boolean;
  note: string;
}

export interface IcFullLedgerSource {
  table: string;
  present: boolean;
  columns: string[];
  used: boolean;
  note: string;
}

export interface IcCandidate {
  entity: string;
  glcode: number;
  glname: string;
  ledger_type: string | null;
  lines: number;
  dr_cr: Money;
  cr_cr: Money;
  net_cr: Money;
  reason: string;
}

export interface IcQuarter {
  month: string;
  holdco_cr: Money;
  subco_cr: Money;
  difference_cr: Money;
  matches: boolean;
}

export interface Intercompany {
  as_of_date: string | null;
  coverage_from: string | null;
  sources: { voucher_lines: string; full_ledger: IcFullLedgerSource | null; loan: string | null; interest: string | null; service: string | null };
  reported_by_ledger: { source: string; note: string; ledgers: IcReportedLedger[]; loan_difference_cr: Money | null; after_old_debit_cr: Money | null };
  pairs: IcPair[];
  loan: {
    net_movement_cr: Money;
    drawn_cr: Money;
    repaid_cr: Money;
    by_month: { month: string; drawn_cr: Money; repaid_cr: Money; net_cr: Money; cumulative_cr: Money; mirrors: boolean }[];
    balance_note: string;
    full_history: boolean;
    holdco_balance_cr: Money;
    subco_balance_cr: Money;
    carried_years_mirror: boolean;
    carried_years_variance_cr: Money;
    by_fy: IcFy[];
    not_carried: { pre_carry_gap_cr: Money; pre_carry_years: string[]; after_uncarried_difference_cr: Money | null; note: string; ledger: { glcode: number; glname: string; dr_cr: Money; cr_cr: Money; net_cr: Money; lines: number } | null };
    basis: string;
    source: string;
    mirrors: boolean;
    variance_cr: Money;
    interest: { accrued_holdco_cr: Money; payable_subco_cr: Money; expense_subco_cr: Money; payable_credited_cr: Money; payable_debited_cr: Money; mirrors: boolean; note: string };
  };
  service: { billed_holdco_cr: Money; charged_subco_cr: Money; unmatched_cr: Money; billings: number; by_quarter: IcQuarter[]; other_months: { months: string[]; difference_cr: Money }; constant_difference: boolean; notes: string[] };
  flags: { ledger: string; reason: string }[];
  candidates: IcCandidate[];
  effect_on_ebitda: { note: string; consolidated_cr: Money; subco_standalone_cr: Money; holdco_standalone_cr: Money; reason: string };
  controls: { loan_mirror_variance_cr: Money; service_unmatched_cr: Money; interest_variance_cr: Money; loan_mirrors: boolean; loan_carried_years_variance_cr: Money; loan_carried_years_mirror: boolean; loan_pre_carry_gap_cr: Money };
}

/* ---- GET /gl-entries ---- */
export type GlCounterparty = "HOLDCO" | "SUBCO" | "SAME_COMPANY";

export interface GlEntry {
  entcode: string;
  entity: "RETAIL" | "VENTURES";
  entno: string | null;
  entdt: string | null;
  entry_type: string | null;
  ledgers: string[];
  party: string | null;
  counterparty_entity: GlCounterparty;
  debit: Money;
  credit: Money;
  debit_cr: Money;
  credit_cr: Money;
  release_status: string;
  narration: string | null;
  reason: string;
  register_status: RelatedStatus;
  balances?: { ledger: string; party: string | null; running_balance: Money; running_balance_cr: Money }[];
}

export interface GlSummaryRow {
  entity: "RETAIL" | "VENTURES";
  counterparty_entity: GlCounterparty;
  glcode: number;
  glname: string;
  month: string;
  entries: number;
  debit_cr: Money;
  credit_cr: Money;
}

export interface GlEntries {
  as_of_date: string | null;
  filters: { entity: string | null; from_month: string | null; to_month: string | null; basis: string; limit: number; offset: number };
  total_entries: number;
  returned: number;
  entries: GlEntry[];
  summary: GlSummaryRow[];
  by_entity: { RETAIL: RelatedGlSideTotals; VENTURES: RelatedGlSideTotals };
  same_company: RelatedGlSideTotals;
  mirror: { holdco_books: RelatedGlSideTotals; subco_books: RelatedGlSideTotals; debit_vs_credit_cr: Money; credit_vs_debit_cr: Money; mirrors: boolean; note: string };
  ledger_mirror: { pair_id: string; label: string; holdco_net_cr: Money; subco_net_cr: Money; difference_cr: Money; mirrors: boolean }[];
  register: { books_of_entity: string; party_pattern: string; counterparty_entity: GlCounterparty; status: RelatedStatus; note: string }[];
  party_register: { path_exists: boolean; patterns: number; proposed: number; confirmed: number };
  source: { entries: string; full_ledger: IcFullLedgerSource; control: { ok: boolean; by_entity: { entity: string; control_rows: number | null; table_rows: number; ok: boolean }[] } | null };
}

export interface GlQuery {
  entity?: "RETAIL" | "VENTURES";
  from_month?: string;
  to_month?: string;
  basis: "all" | "party" | "ledger";
  offset: number;
}
