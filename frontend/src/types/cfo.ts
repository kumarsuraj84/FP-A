/**
 * Typed contracts for the CFO Command Center.
 * Amounts are ₹ Crore unless a field says otherwise. The UI never computes business values;
 * every number, tone and sign below is supplied by the (mock, later HTTP) service.
 */

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

export type PulseId = "cash" | "revenue" | "gm" | "profit" | "creditors" | "advances" | "unreconciled";

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
  operatingMinimum: number;
  expectedInflows: MetricValue;
  upcomingObligations: MetricValue;
  breachDay: string | null;
  series: LiquidityPoint[];
  headline: string;
  tone: Tone;
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

export interface WorkingCapitalSummary {
  rows: WorkingCapitalRow[];
  netCashImpact: number;
  headline: string;
}

export interface RiskPillar {
  id: "liquidity" | "gm" | "payables" | "advances" | "recon";
  label: string;
  exposure: MetricValue;
  movement: MetricValue;
  severity: Severity;
  diagnosticLabel: string;
  diagnosticValue: string;
  family: Family;
  origin: DrillOrigin;
}

export interface CfoAction {
  id: string;
  problem: string;
  amount: MetricValue;
  driver: string;
  concentration: string;
  age: string;
  cta: string;
  severity: Severity;
  family: Family;
  origin: DrillOrigin;
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
}
