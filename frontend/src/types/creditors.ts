import type { MetricValue } from "./cfo";

/* ═══════════════ Stage 2: Creditors / Payables Control Room ═══════════════
 * Finance-definition rules encoded in these contracts:
 *  - The ageing-date basis is NOT confirmed. It is an explicit field wherever ageing is shown; documents carry both
 *    the document date and the due date; nothing here treats either as authoritative.
 *  - A debit balance in a creditor account is NOT a vendor advance. They are separate fields with separate sources.
 *  - Abnormal categories are diagnostic labels only; they carry no accounting conclusion.
 *  - Missing / unmapped values are `MetricValue { value: null, reason }`, never zero.
 *  - All accounting meaning (what moved, what is overdue) is computed by the service, never by React components.
 */

export type BucketId = "b0_30" | "b31_60" | "b61_90" | "b91_180" | "b181_365" | "b365p";

/** A selectable slice of the creditor book: one bucket, a cumulative cohort, or everything. */
export type AgeFilter = BucketId | "all" | "current" | "overdue" | "gt90" | "gt180";

export type Lens = "age" | "concentration" | "movement" | "abnormal";

/** Presentation labels for the selectors. Which buckets a cohort covers always comes from `CreditorsOverview.cohorts`. */
export const BUCKET_LABELS: Record<BucketId, string> = {
  b0_30: "0–30 days",
  b31_60: "31–60 days",
  b61_90: "61–90 days",
  b91_180: "91–180 days",
  b181_365: "181–365 days",
  b365p: ">365 days",
};
export const AGE_FILTER_LABELS: Record<AgeFilter, string> = {
  all: "All creditors",
  current: "Currently due",
  overdue: "Overdue",
  gt90: ">90 days",
  gt180: ">180 days",
  ...BUCKET_LABELS,
};
export const LENSES: { id: Lens; label: string; hint: string }[] = [
  { id: "age", label: "Age", hint: "Where old balances sit" },
  { id: "concentration", label: "Concentration", hint: "Which vendors dominate" },
  { id: "movement", label: "Movement", hint: "What is increasing, ageing, clearing" },
  { id: "abnormal", label: "Abnormal", hint: "Anomalies worth a look" },
];

/** Where a Command Center click lands inside the Creditors room. */
export interface CreditorsTarget {
  age?: AgeFilter;
  lens?: Lens;
}

export interface AgeingBasis {
  /** "unknown" until Oracle discovery and finance confirm which date ageing is measured from */
  id: "document_date" | "due_date" | "unknown";
  confirmed: boolean;
  label: string;
  /** what the mock provisionally uses to place documents in buckets while unconfirmed */
  provisional?: "document_date" | "due_date";
  candidates: ("document_date" | "due_date")[];
}

export interface AgeCohort {
  id: AgeFilter;
  label: string;
  buckets: BucketId[];
  /** true when the cohort's meaning depends on the (unconfirmed) ageing basis, e.g. "Overdue" */
  basisDependent: boolean;
}

export interface AgeingBucket {
  id: BucketId;
  label: string;
  fromDays: number;
  toDays: number | null;
  /** ₹ Cr owed in this bucket */
  exposure: number;
  /** share of dated creditor exposure, 0-1 */
  share: number;
  vendorCount: number;
  documentCount: number;
  /** change in exposure vs period opening, ₹ Cr signed */
  movement: number;
}

export interface ExposureMetric {
  id: AgeFilter;
  label: string;
  value: MetricValue;
  /** change vs period opening, ₹ Cr signed */
  movement: MetricValue;
  basisDependent: boolean;
}

export interface CreditorsOverview {
  asOf: string;
  ageingBasis: AgeingBasis;
  /** what the totals cover, e.g. "Dated documents" */
  scope: string;
  totalCreditors: MetricValue;
  headline: ExposureMetric[];
  cohorts: AgeCohort[];
  buckets: AgeingBucket[];
  /** documents with no usable ageing date: excluded from buckets and reported separately */
  undated: MetricValue;
  undatedDocuments: MetricValue;
  vendorsTotal: number;
  documentsTotal: number;
}

export type MovementType = "aged" | "settled" | "new" | "adjusted";

/** One cohort movement between two buckets (or into/out of the book) over the selected period. */
export interface AgeingMovement {
  id: string;
  fromBucket: BucketId | "new";
  toBucket: BucketId | "settled" | "adjusted";
  /** exposure of the source cohort at period opening, ₹ Cr */
  openingExposure: number;
  /** exposure that moved, ₹ Cr */
  movedExposure: number;
  vendorCount: number;
  documentCount: number;
  movementType: MovementType;
  /** crossed into the >90 day risk zone (service-defined, not computed in React) */
  intoRisk: boolean;
}

export interface MigrationBucketRow {
  id: BucketId;
  opening: number;
  agedIn: number;
  agedOut: number;
  newIn: number;
  settled: number;
  adjusted: number;
  closing: number;
}

export interface MigrationSummaryItem {
  label: string;
  amount: number;
  vendorCount: number;
  flowIds: string[];
}

export interface AgeingMigration {
  ageingBasis: AgeingBasis;
  windowLabel: string;
  opening: number;
  closing: number;
  buckets: MigrationBucketRow[];
  flows: AgeingMovement[];
  summary: {
    enteringRisk: MigrationSummaryItem;
    gettingOlder: MigrationSummaryItem;
    cleared: MigrationSummaryItem;
    newlyCreated: MigrationSummaryItem;
    adjusted: MigrationSummaryItem;
  };
}

export interface VendorExposureRow {
  vendorId: string;
  name: string;
  rank: number;
  /** total outstanding creditor balance, ₹ Cr */
  outstanding: number;
  /** exposure inside the selected age filter, ₹ Cr */
  cohortExposure: number;
  over90: number;
  over180: number;
  /** share of the whole creditor book, 0-1 */
  shareOfBook: number;
  oldestItemDays: MetricValue;
  /** change vs period opening, ₹ Cr signed */
  mtdMovement: number;
  /** closing exposure per ageing bucket, ₹ Cr; sums to `outstanding` */
  byBucket: Record<BucketId, number>;
}

export interface VendorConcentration {
  filter: AgeFilter;
  filterLabel: string;
  scopeExposure: number;
  vendors: VendorExposureRow[];
  others: { count: number; outstanding: number; cohortExposure: number };
  indicators: {
    top1Share: number;
    top5Share: number;
    top10Share: number;
    largest: { vendorId: string; name: string; outstanding: number };
    vendorCount: number;
  };
}

export interface AbnormalCategory {
  id: string;
  label: string;
  /** diagnostic wording only; never an accounting conclusion */
  description: string;
  vendorCount: MetricValue;
  documentCount: MetricValue;
  amount: MetricValue;
  /** always "diagnostic": the service has not classified these accounting-wise */
  classification: "diagnostic";
  caveat?: string;
}

export interface AbnormalControl {
  categories: AbnormalCategory[];
  note: string;
}

export interface VendorOpenItem {
  documentRef: string;
  documentType: string;
  /** both dates are always carried so either basis can be applied once confirmed */
  documentDate: string | null;
  dueDate: string | null;
  /** age under the provisional basis; null when there is no usable date, never zero */
  ageDays: MetricValue;
  bucket: BucketId | null;
  /** ₹ Cr */
  amount: number;
}

export interface LifecycleStage {
  id: "opening" | "liability" | "adjustment" | "payment" | "open";
  label: string;
  /** ₹ Cr, always positive; `direction` says how it moves the balance */
  amount: number;
  documentCount: number;
  direction: "start" | "increase" | "decrease" | "result";
}

export interface VendorProfile {
  vendorId: string;
  name: string;
  code: string;
  paymentTerms: string;
  ageingBasis: AgeingBasis;
  strip: {
    outstanding: MetricValue;
    overdue: MetricValue;
    over90: MetricValue;
    advance: MetricValue;
    oldestItem: MetricValue;
    oldestItemRef: string | null;
    lastPayment: { date: string | null; amount: MetricValue };
  };
  lifecycle: LifecycleStage[];
  trend: { label: string; outstanding: number }[];
  migration: { bucket: BucketId; label: string; opening: number; closing: number }[];
  paymentBehaviour: {
    paymentsPerMonth: MetricValue;
    avgDaysToPay: MetricValue;
    recent: { date: string; amount: number; daysElapsed: number }[];
  };
  advancePosition: { amount: MetricValue; source: string; note: string };
  /** a debit balance in the creditor account, kept separate from advances unless finance classifies it */
  debitBalance: { amount: MetricValue; note: string };
  abnormal: { categoryId: string; label: string; amount: MetricValue; documentRef: string | null }[];
  openItems: VendorOpenItem[];
  openBalance: number;
}
