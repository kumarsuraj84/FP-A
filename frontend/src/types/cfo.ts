/**
 * Typed contracts for the CFO Command Center.
 * Amounts are ₹ Crore unless a field says otherwise. The UI never computes business values;
 * every number, tone and sign below is supplied by the (mock, later HTTP) service.
 */

import type { CashRoom } from "./cash";
import type { ProfitPortfolio, StoreWorkspace } from "./profitability";
import type { AbnormalControl, AgeFilter, AgeingMigration, CreditorsOverview, CreditorsTarget, VendorConcentration, VendorProfile } from "./creditors";

export type ScenarioId =
  | "normal"
  | "cash_pressure"
  | "aged_creditors"
  | "vendor_advance_risk"
  | "margin_pressure";

export type PeriodId = "sep26" | "q2fy27" | "ytdfy27";
export type ComparisonId = "budget" | "ly" | "forecast";

/** Simulated data availability (demo control) — drives every section's state UI. */
export type DataStateId = "live" | "stale" | "unavailable" | "error" | "empty";

export interface QueryCtx {
  scenario: ScenarioId;
  period: PeriodId;
  comparison: ComparisonId;
  dataState: DataStateId;
}

export type Tone = "good" | "bad" | "neutral" | "warn";
export type Severity = "low" | "medium" | "high" | "critical";
/** "unrated" = there is no real source to rate this on (live data): it is shown as "Not rated", never as low. */
export type LiveSeverity = Severity | "unrated";

/**
 * Where a real figure comes from. Every live figure carries its OWN run id and as-of date: the three real sources
 * (P&L, Management P&L, Creditors, Cash) are separate runs and are never presented as one synchronized position.
 */
export type SourceId = "pnl" | "mgmt" | "creditors" | "cash";
export interface SourceStamp {
  id: SourceId;
  label: string;
  runId: string | null;
  /** the run's own as-of date (YYYY-MM-DD); null when the source could not be read */
  asOf: string | null;
  state: string;
  stateLabel: string;
  ok: boolean;
  /** why the source could not be read */
  reason?: string;
}

/** A jump from a real drill to the dedicated live page that owns the detail. */
export interface DrillLink {
  label: string;
  room: "profitability" | "cashroom" | "creditors";
  age?: AgeFilter;
}

/** Envelope: lets every section render loading / stale / unavailable / empty honestly. */
export interface Envelope<T> {
  status: "ok" | "stale" | "unavailable" | "empty";
  data?: T;
  reason?: string;
  asOf: string; // ISO
  staleSince?: string;
}

/** A value that may legitimately be missing. null renders as "—" with `reason`. */
export interface MetricValue {
  value: number | null;
  reason?: string;
}

/* ───────────── drill model ───────────── */

/** Metric families decide which dimensions a drill walks through. */
export type Family = "margin" | "cost" | "volume" | "cash" | "payables" | "advances" | "recon" | "forecast";

export type DrillLevel = "movement" | "driver" | "entity" | "ledger" | "voucher" | "profile";

export interface DrillOrigin {
  /** where the investigation started */
  source: "bridge" | "pulse" | "liquidity" | "workingCapital" | "risk" | "action" | "forecast";
  id: string;
  /** disambiguates the same id appearing in several sections, e.g. hero:cash vs hero:workingCapital */
  scope?: string;
  label: string;
  family: Family;
  /** amount shown on the clicked object (₹ Cr, signed) */
  amount: number | null;
  /** movement vs the selected comparison (₹ Cr signed); for bridge deltas this equals the amount */
  variance: number | null;
  /** level the variance is measured against (e.g. opening profit), used for % variance */
  base?: number | null;
}

export interface DrillNode {
  level: DrillLevel;
  /** dimension this node filters on, e.g. Department, Region, Store, Vendor */
  dim: string;
  id: string;
  label: string;
  amount: number | null;
  variance: number | null;
}

export interface DrillRow {
  node: DrillNode;
  amount: number;
  /** share of parent amount, 0–1 */
  share: number;
  /** movement vs comparison, ₹ Cr signed */
  delta: number;
  tone: Tone;
  sublabel?: string;
  /** set when the amount is genuinely unavailable: render "—" with this reason, never zero */
  unavailable?: string;
}

export interface DrillSplit {
  dim: string;
  rows: DrillRow[];
  /** remainder not listed as rows (long lists); keeps the visible total reconciling to the parent */
  other?: { count: number; amount: number; delta: number };
}

export interface DrillView {
  title: string;
  levelLabel: string;
  amount: number | null;
  /** variance vs the selected comparison, ₹ Cr signed */
  variance: number | null;
  variancePct: number | null;
  comparisonLabel: string;
  tone: Tone;
  explanation: string;
  concentration: { headline: string; topShares: number[] };
  splits: DrillSplit[];
  supportingDrivers: DrillRow[];
  /** terminal entity: no more splits, offer deep pages */
  terminal: boolean;
  entityKind: "store" | "vendor" | "account" | "other";
  facts: { label: string; value: string }[];
  /** live data: the real source(s) behind this view */
  sources?: SourceStamp[];
  /** live data: dedicated pages that own the detail (replaces the demo ledger / profile buttons) */
  links?: DrillLink[];
}

export interface LedgerEntry {
  id: string;
  date: string;
  voucherId: string;
  voucherType: string;
  account: string;
  accountName: string;
  narration: string;
  debit: number;
  credit: number;
  balance: number;
  source: string;
  recon: "matched" | "pending" | "exception";
}

export interface LedgerView {
  title: string;
  subtitle: string;
  openingBalance: number;
  closingBalance: number;
  entries: LedgerEntry[];
  /** how to read the running balance, e.g. credit-positive for a creditor account */
  balanceNote?: string;
}

export interface VoucherLine {
  account: string;
  accountName: string;
  costCenter: string;
  debit: number;
  credit: number;
}

export interface VoucherEvidence {
  voucherId: string;
  voucherType: string;
  date: string;
  postedBy: string;
  sourceSystem: string;
  documentRef: string;
  narration: string;
  status: string;
  total: number;
  lines: VoucherLine[];
  evidence: {
    sourceObject: string;
    extractionBatch: string;
    rowHash: string;
    mappingStatus: string;
    attachments: { name: string; kind: string; size: string }[];
    trail: { at: string; by: string; action: string }[];
  };
}

export interface EntityProfile {
  title: string;
  kind: "store" | "vendor" | "account" | "other";
  facts: { label: string; value: string }[];
  kpis: { label: string; value: MetricValue; unit: "cr" | "pct" | "days" | "count"; tone: Tone; note?: string }[];
  trend: { label: string; value: number }[];
  trendLabel: string;
}

/* ───────────── command-center sections ───────────── */

export type PulseId = "cash" | "revenue" | "gm" | "profit" | "corp" | "creditors" | "advances" | "unreconciled";

export interface PulseMetric {
  id: PulseId;
  label: string;
  value: MetricValue;
  unit: "cr" | "pct";
  comparisonLabel: string;
  /** movement vs comparison: ₹ Cr for cr metrics, percentage points for pct */
  movement: MetricValue;
  movementUnit: "cr" | "bps" | "pct";
  status: string;
  tone: Tone;
  family: Family;
  heroTab: HeroTab;
  origin: DrillOrigin;
  /** when set, the click navigates to a dedicated workspace instead of opening the drawer */
  target?: CreditorsTarget;
  /** live data: the source run this figure comes from */
  source?: SourceStamp;
}

export type HeroTab = "profit" | "cash" | "workingCapital";

export interface BridgeItem {
  id: string;
  label: string;
  kind: "total" | "delta";
  /** total: absolute level; delta: signed movement (₹ Cr) */
  value: number;
  tone: Tone;
  family: Family;
}

export interface Bridge {
  id: string;
  title: string;
  subtitle: string;
  unitNote: string;
  items: BridgeItem[];
  /** live data: replaces the variance "net movement" readout for a composition bridge (set by the service, never computed in the UI) */
  readout?: { label: string; value: string; note: string };
  /** live data: the basis of the EBITDA figures (label only), so the books fallback is not mistaken for the management total */
  basis?: "books" | "mgmt_total";
  sources?: SourceStamp[];
}

export interface LiquidityPoint {
  label: string;
  /** projected cash ₹ Cr */
  cash: number;
  actual: boolean;
}

export type Horizon = "today" | "7d" | "15d" | "30d";

export interface LiquiditySummary {
  currentCash: MetricValue;
  projectedCash: MetricValue;
  /** null = no operating minimum has been set in any source */
  operatingMinimum: number | null;
  expectedInflows: MetricValue;
  upcomingObligations: MetricValue;
  breachDay: string | null;
  series: LiquidityPoint[];
  headline: string;
  tone: Tone;
  sources?: SourceStamp[];
}

export interface WorkingCapitalRow {
  id: string;
  label: string;
  /** cash impact ₹ Cr: negative = absorbed, positive = released */
  cashImpact: number;
  direction: "absorbed" | "released";
  tone: Tone;
  note: string;
  family: Family;
}

/** A working-capital line of the live service: the movement may be unavailable (null), in which case the balance (or its reason) is shown. */
export interface WorkingCapitalLine extends Omit<WorkingCapitalRow, "cashImpact"> {
  cashImpact: number | null;
  balance?: MetricValue;
}

export interface WorkingCapitalSummary {
  rows: WorkingCapitalLine[];
  netCashImpact: number | null;
  headline: string;
  sources?: SourceStamp[];
}

export interface RiskPillar {
  id: "liquidity" | "gm" | "payables" | "advances" | "recon";
  label: string;
  exposure: MetricValue;
  movement: MetricValue;
  severity: LiveSeverity;
  diagnosticLabel: string;
  diagnosticValue: string;
  /** live data: overrides the fixed caption under the exposure figure */
  exposureLabel?: string;
  family: Family;
  origin: DrillOrigin;
  target?: CreditorsTarget;
  source?: SourceStamp;
}

export interface CfoAction {
  id: string;
  problem: string;
  amount: MetricValue;
  driver: string;
  concentration: string;
  age: string;
  cta: string;
  severity: LiveSeverity;
  family: Family;
  origin: DrillOrigin;
  target?: CreditorsTarget;
  /** live data: the real facts this action rests on (source run, as-of and the field it is read from) */
  evidence?: string;
}

export interface ForecastMonth {
  month: string;
  budget: number;
  actual: number | null;
  forecast: number | null;
}

export interface ForecastTrajectory {
  months: ForecastMonth[];
  landing: MetricValue;
  budgetFy: MetricValue;
  gap: MetricValue;
  headline: string;
  bridge: Bridge;
}

export interface FreshnessInfo {
  asOf: string;
  stale: boolean;
  label: string;
  /** live data: one stamp per real source, each with its own run and as-of date */
  sources?: SourceStamp[];
}

export interface CfoApi {
  getFreshness(ctx: QueryCtx): Promise<FreshnessInfo>;
  getPulse(ctx: QueryCtx): Promise<Envelope<PulseMetric[]>>;
  getBridge(ctx: QueryCtx, tab: HeroTab): Promise<Envelope<Bridge>>;
  getLiquidity(ctx: QueryCtx, horizon: Horizon): Promise<Envelope<LiquiditySummary>>;
  getWorkingCapital(ctx: QueryCtx): Promise<Envelope<WorkingCapitalSummary>>;
  getRisks(ctx: QueryCtx): Promise<Envelope<RiskPillar[]>>;
  getActions(ctx: QueryCtx): Promise<Envelope<CfoAction[]>>;
  getForecast(ctx: QueryCtx): Promise<Envelope<ForecastTrajectory>>;
  getDrillView(ctx: QueryCtx, origin: DrillOrigin, nodes: DrillNode[]): Promise<Envelope<DrillView>>;
  getLedger(ctx: QueryCtx, origin: DrillOrigin, nodes: DrillNode[]): Promise<Envelope<LedgerView>>;
  getVoucher(ctx: QueryCtx, voucherId: string, amount: number | null): Promise<Envelope<VoucherEvidence>>;
  getEntityProfile(ctx: QueryCtx, origin: DrillOrigin, nodes: DrillNode[]): Promise<Envelope<EntityProfile>>;
  /* Stage 2: Creditors / Payables Control Room */
  getCreditors(ctx: QueryCtx): Promise<Envelope<CreditorsOverview>>;
  getAgeingMigration(ctx: QueryCtx): Promise<Envelope<AgeingMigration>>;
  getVendorConcentration(ctx: QueryCtx, filter: AgeFilter): Promise<Envelope<VendorConcentration>>;
  getAbnormalBalances(ctx: QueryCtx): Promise<Envelope<AbnormalControl>>;
  getVendorProfile(ctx: QueryCtx, vendorId: string): Promise<Envelope<VendorProfile>>;
  /* Stage 3: Store Profitability */
  getProfitPortfolio(ctx: QueryCtx): Promise<Envelope<ProfitPortfolio>>;
  getStoreWorkspace(ctx: QueryCtx, storeId: string): Promise<Envelope<StoreWorkspace>>;
  /* Stage 4: Cash & Working Capital Control */
  getCashRoom(ctx: QueryCtx, horizon: Horizon): Promise<Envelope<CashRoom>>;
}
