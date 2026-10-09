/* ═══════════ Creditors: the real (verified-mart) contract ═══════════
 * Shapes of the read-only Creditors API (docs/creditors_pilot/API_CONTRACT.md). Money arrives as EXACT DECIMAL TEXT and is converted
 * only for display. Credit, debit and net are separate fields and are never blended. `data_state` is decided by the API.
 */

export type Money = string;

export type DataState = "live" | "verified_candidate" | "superseded" | "withdrawn";

export interface RunHeader {
  extraction_run_id: string;
  as_of_date: string;
  recon_state: string;
  publication_state: string;
  data_state: DataState;
  data_state_label: string;
  contract_version: string;
  rules_version: string;
}

export interface LiveSummary extends RunHeader {
  item_rows: number;
  vendors: number;
  credit_items: number;
  debit_items: number;
  credit_outstanding: Money;
  creditor_debit_balance: Money;
  signed_net: Money;
  past_due_credit: Money;
  past_due_items: number;
  due_unavailable_credit: Money;
  due_unavailable_items: number;
  over_90_credit: Money;
  over_90_items: number;
  over_180_credit: Money;
  over_180_items: number;
  credit_vendors: number;
  debit_vendors: number;
  credit_concentration: { top_1: Money; top_5: Money; top_10: Money; top_20: Money };
  /** Intercompany balances left out of the figures above (present only when a related-party register is loaded) */
  related_party_excluded?: RelatedPartyExcluded;
}

export interface RelatedPartyExcluded {
  payable_cr: Money; // crore, decimal text
  debit_balance_cr: Money;
  payable_inr?: Money;
  debit_balance_inr?: Money;
  parties: number;
  items: number;
}

export interface Split {
  credit_items: number;
  debit_items: number;
  credit_outstanding: Money;
  debit_balance: Money;
  signed_net: Money;
}

export interface AgeBucketRow extends Split {
  bucket: string; // D0_30 … D365_PLUS | UNCLASSIFIED
  label: string;
  reasons?: { reason: string; credit_items: number; debit_items: number; credit_outstanding: Money; debit_balance: Money }[];
}

export interface DueStateRow extends Split {
  state: "NOT_YET_DUE" | "PAST_DUE_OR_DUE_TODAY" | "DUE_UNAVAILABLE" | "DUE_INVALID";
  label: string;
}

export interface LedgerRow {
  ledger_code: string;
  ledger_name: string;
  credit_items: number;
  debit_items: number;
  credit_outstanding: Money;
  debit_balance: Money;
  signed_net: Money;
  vendors: number;
  credit_vendors: number;
  debit_vendors: number;
  past_due_credit: Money;
  due_unavailable_credit: Money;
}

export interface LiveVendor {
  vendor_ref: string;
  vendor_name?: string; // Finance access only
  slid?: string;
  sub_ledger_code?: string;
  credit_days?: number | null;
  party_class: string | null;
  party_class_type: string | null;
  ledger_codes: string[];
  items: number;
  credit_items: number;
  debit_items: number;
  credit_outstanding: Money;
  debit_balance: Money;
  signed_net: Money;
  past_due_credit: Money;
  due_unavailable_credit: Money;
  oldest_credit_age_days: number | null;
  share_of_credit: string;
  credit_by_document_age: Record<string, Money>;
  credit_by_due_status: Record<string, Money>;
  cohort_credit?: Money;
}

export interface VendorPage {
  total: { vendors: number; credit_outstanding: Money; debit_balance: Money; signed_net: Money; cohort_credit?: Money };
  returned: number;
  limit: number;
  offset: number;
  vendors: LiveVendor[];
  /** true when the Finance (named) route served this page */
  named: boolean;
}

export interface LiveItem {
  item_ref: string;
  ledger_code: string;
  ledger_name: string;
  drcr: "Cr" | "Dr";
  amount: Money;
  adjusted: Money;
  pending: Money;
  document_type: string | null;
  document_date: string | null;
  due_date: string | null;
  entry_date: string | null;
  document_age_days: number | null;
  document_age_bucket: string;
  overdue_days: number | null;
  due_status: string;
  date_quality_status: string;
  classification_status: string;
  // Finance only
  document_code?: string;
  document_no?: string;
  document_initial?: string;
  ref_no?: string;
  ref_date?: string | null;
}

export interface ItemPage {
  vendor_ref: string;
  total_items: number;
  returned: number;
  items: LiveItem[];
  named: boolean;
}

export interface ControlTally {
  layers: { from: string; to: string; controls: number; passed: number; failed: number; max_abs_variance: Money }[];
  total: number;
  passed: number;
  failed: number;
}

export interface RunStatus extends RunHeader {
  expected_rows: number;
  expected_identity_rows: number;
  controls: ControlTally;
}
