/* ═══════════ Entry / voucher drill: the real (gold) contract ═══════════
 * Shapes of the read-only Entry API (`/api/v1/entries`). Money is EXACT DECIMAL TEXT, converted only for display.
 * The data state and the link status are decided by the API; the UI only displays them.
 */
import type { DataState, Money } from "./creditorsLive";

export interface EntryRunHeader {
  entry_run_id: string;
  register_report_date: string;
  till_balance_date: string;
  cash_run_id: string;
  creditors_run_id: string;
  coverage_from: string;
  recon_state: string;
  publication_state: string;
  data_state: DataState;
  data_state_label: string;
  source_updated_at: string;
}

export interface EntryLineText {
  sub_ledger_code: string | null;
  narration: string | null;
  reference_no: string | null;
  reference_date: string | null;
  cheque_no: string | null;
  cheque_date: string | null;
  counter_ledgers: string | null;
  prepared_by: string | null;
  prepared_on: string | null;
  modified_by: string | null;
  modified_on: string | null;
  released_by: string | null;
  released_on: string | null;
}

export interface EntryLine {
  line_no: number;
  ledger_code: string;
  ledger_name: string;
  ledger_nature: string | null;
  sub_ledger_ref: string | null;
  debit: Money;
  credit: Money;
  release_status: string;
  cube_name: string | null;
  /** Finance route only */
  text?: EntryLineText;
}

/** From `/line-detail`: columns the entry layer does not carry. Party name is Finance only. */
export interface EntryLineDetail {
  line_no: number;
  fin_group: string | null;
  fin_major_group: string | null;
  site_code: number | null;
  store_name: string | null;
  site_kind: string | null;
  profit_effect: Money | null;
  vendor_name?: string | null;
  vendor_class?: string | null;
}

export interface LinkedBill {
  item_ref: string;
  link_status: string;
  coverage: string;
}

export interface EntryIdentity {
  site_code: string;
  entry_type_short: string;
  entry_no: string;
  created_by_site: string | null;
}

export interface Entry {
  entry_ref: string;
  site_code: string | null;
  entry_type_short: string;
  entry_type_long: string;
  entry_date: string;
  release_status: "Posted" | "Unposted" | "Mixed" | string;
  line_count: number;
  total_dr: Money;
  total_cr: Money;
  selections: string[];
  lines: EntryLine[];
  balanced: boolean;
  linked_bills: LinkedBill[];
  attachment: { available: boolean; message: string };
  /** Finance route only */
  identity?: EntryIdentity;
}

export interface EntryResponse extends EntryRunHeader {
  entry: Entry;
  named: boolean;
}

export interface LineDetailResponse extends EntryRunHeader {
  entry_ref: string;
  named: boolean;
  lines: EntryLineDetail[];
}

export interface LedgerEntryRow {
  entry_ref: string;
  entry_date: string;
  entry_type_short: string;
  entry_type_long: string;
  release_status: string;
  /** matching lines on the ledger (not all lines of the voucher) */
  lines: number;
  debit: Money;
  credit: Money;
  /** credit - debit, the P&L sign */
  net: Money;
  /** Finance route only */
  narration?: string | null;
}

export interface LedgerEntriesScope {
  entity?: "RETAIL" | "VENTURES";
  site: number | null;
  glcode: number | null;
  ledger_name: string | null;
  from_month: string | null;
  to_month: string | null;
  from_date: string | null;
  to_date: string | null;
  basis: "all" | "posted";
}

export interface LedgerEntriesPage extends EntryRunHeader {
  scope: LedgerEntriesScope;
  parent: { net: Money; debit: Money; credit: Money; lines: number };
  children_sum: { net: Money };
  /** null while the list is only partly loaded: the parent is the whole range, the children are the rows shown */
  reconciles: boolean | null;
  total: { entries: number; lines: number; debit: Money; credit: Money; net: Money };
  returned: number;
  limit: number;
  offset: number;
  named: boolean;
  entries: LedgerEntryRow[];
}

export interface TillStoreRow {
  site_code: number;
  balance: Money;
  total_debit: Money;
  total_credit: Money;
  active_days: number;
}
export interface TillStoresResponse extends EntryRunHeader {
  label: string;
  note: string;
  balance_date: string;
  parent: { store_till_cash: Money; stores: number };
  children_sum: { store_till_cash: Money; stores: number };
  reconciles: boolean;
  stores: TillStoreRow[];
}

export interface TillDay {
  day: string;
  debit: Money;
  credit: Money;
  cumulative_balance: Money;
}
export interface TillDaysResponse extends EntryRunHeader {
  site_code: string;
  balance_date: string;
  parent: { balance: Money };
  children_sum: { balance: Money };
  reconciles: boolean;
  deepest_level: string;
  note: string;
  days: TillDay[];
}

export type LinkStatus = "STRONG" | "EXACT" | "AMBIGUOUS" | "NOT_LINKED" | string;

export interface BillLink {
  item_ref: string;
  creditors_run_id: string;
  ledger_code: string;
  bill_amount: Money;
  link_status: LinkStatus;
  not_linked_reason: string | null;
  key_used: string;
  matched_entries: number;
  entry_ref: string | null;
  entry_net_amount: Money | null;
  amount_agrees: boolean | null;
  coverage: string;
  message?: string;
}
export interface BillLinkResponse extends EntryRunHeader {
  link: BillLink;
  attachment: { available: boolean; message: string };
}
