/**
 * Shapes served by the Management P&L API (/api/v1/mgmt). Money is INR Crore as a JSON number; null means "no value", never zero.
 * Sign convention (as the finance MIS): income positive, cost negative.
 */
export type MgmtLineKind = "value" | "subtotal" | "pct";
export type MgmtMode = "book" | "adjustment" | "total";
/** The layers of the Management P&L page: the expense pages do not carry a reclass layer yet. */
export type MgmtPnlMode = MgmtMode | "reclass";
/** Which legal entity the figures are for. Consolidated is what the finance MIS shows; HoldCo is Citykart Ventures, SubCo is Citykart Stores (CKSPL). */
export type MgmtEntity = "consolidated" | "subco" | "holdco";
export const MGMT_ENTITIES: { id: MgmtEntity; label: string; short: string }[] = [
  { id: "consolidated", label: "Consolidated", short: "Consolidated" },
  { id: "subco", label: "SubCo - Citykart Stores", short: "SubCo" },
  { id: "holdco", label: "HoldCo - Citykart Ventures", short: "HoldCo" },
];

/** One figure in three layers: what the books say, what management adjusts, and the sum (the MIS number). */
export interface MgmtTriple {
  book: number | null;
  /** Net-zero movement of active line corrections (group and expense month). Absent on older servers. Total = book + reclass + adjustment. */
  reclass?: number | null;
  adjustment: number | null;
  total: number | null;
}

export interface MgmtLine {
  key: string;
  label: string;
  kind: MgmtLineKind;
  values: Record<string, MgmtTriple>;
  total: MgmtTriple;
}

export interface MgmtHeader {
  run_id: string;
  as_of_date: string;
  months: string[];
  warnings: string[];
}

export interface MgmtPnl {
  run_id: string;
  entity?: MgmtEntity;
  as_of_date: string;
  months: string[];
  lines: MgmtLine[];
  store_count: number | null;
  warnings: string[];
}

export interface MgmtPnlQuery {
  from_month?: string;
  to_month?: string;
  include_proposed: boolean;
  entity: MgmtEntity;
}

export interface MgmtStoreRow {
  store: string;
  site_code: string;
  store_type: string | null;
  net_sales: number | null;
  rgm: number | null;
  store_expenses: number | null;
  four_wall: number | null;
  apportioned: number | null;
  ebitda_after: number | null;
}

export interface MgmtStoreSummary {
  net_sales: number;
  rgm: number;
  store_expenses: number;
  four_wall: number;
  apportioned: number;
  store_ebitda_after: number;
  dc_total: number;
  ho_total: number;
  reconciles: boolean;
}

export interface MgmtStores {
  run_id: string;
  entity?: MgmtEntity;
  /** DC + HO cost as a share of net sales. A fraction (0.0503) is expected; a value above 1 is read as a percentage (5.03). */
  rate: number;
  summary: MgmtStoreSummary;
  rows: MgmtStoreRow[];
}

export interface MgmtReconCell {
  mis: number | null;
  portal: number | null;
  variance: number | null;
  tied: boolean;
  override_reason: string | null;
}

export interface MgmtReconLine {
  key: string;
  label: string;
  values: Record<string, MgmtReconCell>;
}

export interface MgmtBridgeStep {
  step: string;
  cr: number | null;
  nature: string;
  note: string;
}

export interface MgmtReconciliation {
  run_id: string;
  entity?: MgmtEntity;
  months: { month: string; status: "TIED" | "VARIANCE" }[];
  lines: MgmtReconLine[];
  bridge: MgmtBridgeStep[];
  warnings: string[];
}

export interface MgmtAdjustment {
  id: string | number;
  month: string;
  mis_line: string;
  location_type: string;
  amount_cr: number;
  kind: string;
  rule: string;
  owner: string;
  status: string;
  source: string;
  note: string;
  /** Set on intercompany eliminations (kind "elimination"). */
  counterparty?: string | null;
  counterparty_entity?: string | null;
}

export interface MgmtAdjustments {
  rows: MgmtAdjustment[];
}

export interface MgmtMappingRow {
  ledger: string;
  mgmt_group: string;
  major_group: string;
  category: string | null;
  source: string;
  note: string | null;
}

export interface MgmtMappingException {
  ledger: string;
  amount_cr: number;
  reason: string;
}

export interface MgmtMapping {
  rows: MgmtMappingRow[];
  exceptions: MgmtMappingException[];
}
