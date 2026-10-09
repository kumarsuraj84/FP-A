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
  candidates: RelatedCandidate[];
  controls: RelatedControls;
}

export type RelatedItems = Omit<ItemPage, "vendor_ref" | "named"> & { as_of_date: string; sub_ledger_code: number; party_name: string };
