/* ═══════════ Cash: the real (verified-mart) contract ═══════════
 * Shapes of the read-only Cash API. Money is EXACT DECIMAL TEXT, converted only for display. `data_state` is decided by the API.
 * Three kinds of figure, never blended: Store Till Cash (excludes bank balances), the bank ledger BOOK position (provisional, not
 * bank-reconciled), and creditor obligations (read from the creditors mart).
 */
import type { DataState, Money } from "./creditorsLive";

export interface CashHeader {
  run_id: string;
  as_of_date: string;
  till_balance_date: string;
  recon_state: string;
  publication_state: string;
  data_state: DataState;
  data_state_label: string;
  contract_version: string;
  source_updated_at: string;
}

export interface CashTill {
  label: string;
  note: string;
  stores: number;
  store_till_cash: Money;
  mtd_debit: Money;
  mtd_credit: Money;
  fytd_debit: Money;
  fytd_credit: Money;
  stores_negative: number;
  stores_with_cash: number;
  last_activity_date: string | null;
  largest_store: { store_name: string | null; site_code: string; cumulative_balance: Money } | null;
}

export interface BankLedger {
  ledger_code: string;
  ledger_name: string;
  gl_type: string | null;
  nature: string | null;
  extinct: string | null;
  has_movement: boolean;
  opening_balance: Money;
  posted_dr: Money;
  posted_cr: Money;
  posted_closing: Money;
  unposted_dr: Money;
  unposted_cr: Money;
  unposted_movement: Money;
  including_unposted: Money;
  future_net: Money;
  last_posted_date: string | null;
  last_entry_date: string | null;
  register_report_date: string | null;
  sites: number | null;
}

export interface BankReview {
  status: string;
  source: string;
  register_report_date: string | null;
  last_posted_date: string | null;
  totals: { opening_balance: Money; posted_closing: Money; unposted_movement: Money; including_unposted: Money };
  ledgers_total: number;
  ledgers_with_movement: number;
  ledgers_without_movement: number;
  driver: { ledger_code: string; ledger_name: string; posted_closing: Money; including_unposted: Money } | null;
  ledgers: BankLedger[];
  cross_check: { gl_register_posted_closing: Money; gl_register_including_unposted: Money; gl_register_report_date: string | null; posted_agrees_with_gl_register: boolean };
  opening_ties_to_prior_year_closing: { ledgers_checked: number; ledgers_not_tying: number };
}

export type CreditorObligations =
  | { available: false; reason: string }
  | {
      available: true;
      creditors_run_id: string;
      as_of_date: string;
      data_state: DataState;
      credit_outstanding: Money;
      creditor_debit_balance: Money;
      signed_net: Money;
      past_due_credit: Money;
      not_yet_due_credit: Money;
      due_unavailable_credit: Money;
      credit_items: number;
      credit_vendors: number;
    };

export interface CashSummary extends CashHeader {
  till: CashTill;
  bank_review: BankReview;
  creditors: CreditorObligations;
  unavailable: { id: string; label: string; reason: string }[];
}

export interface TillStore {
  site_code: string;
  store_name: string | null;
  cumulative_balance: Money;
  mtd_debit: Money;
  mtd_credit: Money;
  fytd_debit: Money;
  fytd_credit: Money;
  last_activity_date: string | null;
}

export interface TillPage {
  returned: number;
  limit: number;
  offset: number;
  stores: TillStore[];
}
