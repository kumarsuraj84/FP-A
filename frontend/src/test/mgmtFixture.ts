import type { MgmtEntity, MgmtAdjustment, MgmtAdjustments, MgmtBridgeStep, MgmtHeader, MgmtLine, MgmtMapping, MgmtPnl, MgmtReconciliation, MgmtReconLine, MgmtStoreRow, MgmtStores, MgmtTriple } from "@/types/mgmtLive";

/**
 * SYNTHETIC sample of the Management P&L API (/api/v1/mgmt), in INR Cr. Aug-26 and the Apr-Aug totals follow the finance MIS
 * (corporate EBITDA 3.34 and 63.63, store EBITDA 9.74 and 92.83, DC -2.22, HO -4.18, revenue 127.32); Apr-Jul months are invented so the YTD totals tie.
 * Used by the unit tests and, in dev only, by `?data=fixture`. It is never the default data source.
 */
export const RUN = "mgmt_fixture_run";
export const MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"];
export const WARNINGS = ["Citykart Ventures not in gold: stop-gap from workbook", "provisional adjustments included", "Intercompany expense and loan eliminations not loaded"];

type Leaf = "revenue" | "other_operating_income" | "material_cost" | "rent" | "employee_cost" | "power_fuel" | "advertisement" | "freight" | "other_expenses" | "dc_cost" | "ho_cost" | "one_time";
type Layer = Record<Leaf, number>;

const r4 = (n: number) => Math.round(n * 1e4) / 1e4;
const ZERO: Layer = { revenue: 0, other_operating_income: 0, material_cost: 0, rent: 0, employee_cost: 0, power_fuel: 0, advertisement: 0, freight: 0, other_expenses: 0, dc_cost: 0, ho_cost: 0, one_time: 0 };

/** MIS (total) values per month. Aug is exact to the published figures; Apr-Jul are plugged so store EBITDA, DC and HO tie to the YTD. */
const AUG: Layer = { revenue: 127.32, other_operating_income: 0.65, material_cost: -92.32, rent: -6.902, employee_cost: -9.423, power_fuel: -5.243, advertisement: -1.293, freight: -1.993, other_expenses: -1.056, dc_cost: -2.22, ho_cost: -4.18, one_time: 0 };
const TARGETS: Record<string, { revenue: number; storeEbitda: number; dc: number; ho: number; oneTime: number }> = {
  "2026-04": { revenue: 118.4, storeEbitda: 19.8, dc: -1.55, ho: -4.1, oneTime: -0.83 },
  "2026-05": { revenue: 121.15, storeEbitda: 22.6, dc: -1.7, ho: -4.05, oneTime: 0 },
  "2026-06": { revenue: 116.28, storeEbitda: 17.4, dc: -1.52, ho: -3.98, oneTime: 0 },
  "2026-07": { revenue: 128.8, storeEbitda: 23.29, dc: -1.7, ho: -4.2, oneTime: 0 },
};

function totalLayer(month: string): Layer {
  if (month === "2026-08") return AUG;
  const t = TARGETS[month];
  const k = t.revenue / AUG.revenue;
  const leaf = (key: Leaf) => r4(AUG[key] * k);
  const l: Layer = { ...ZERO, revenue: t.revenue, other_operating_income: leaf("other_operating_income"), rent: leaf("rent"), employee_cost: leaf("employee_cost"), power_fuel: leaf("power_fuel"), advertisement: leaf("advertisement"), freight: leaf("freight"), other_expenses: leaf("other_expenses"), dc_cost: t.dc, ho_cost: t.ho, one_time: t.oneTime };
  const storeExp = l.rent + l.employee_cost + l.power_fuel + l.advertisement + l.freight + l.other_expenses;
  l.material_cost = r4(t.storeEbitda - t.revenue - l.other_operating_income - storeExp); // the plug
  return l;
}

/** Management adjustments per month (the part of the MIS that is not in the books). Aug follows the portal-vs-MIS gaps in the review. */
function adjustmentLayer(month: string): Layer {
  const rev = totalLayer(month).revenue;
  if (month === "2026-08") return { ...ZERO, other_operating_income: -0.01, material_cost: -1.16, employee_cost: -0.27, advertisement: -0.33, other_expenses: 0.03, dc_cost: -1.31, ho_cost: -1.61 };
  return { ...ZERO, material_cost: r4(-0.0095 * rev), employee_cost: -0.25, advertisement: r4(-0.0026 * rev), dc_cost: -1.2, ho_cost: -1.45, one_time: 0 };
}

const sumT = (a: Triple[]): Triple => ({ book: r4(a.reduce((s, x) => s + (x.book ?? 0), 0)), adjustment: r4(a.reduce((s, x) => s + (x.adjustment ?? 0), 0)), total: r4(a.reduce((s, x) => s + (x.total ?? 0), 0)) });
type Triple = MgmtTriple;

/**
 * Entity variants. HoldCo (Citykart Ventures) carries a share of DC and HO cost and the one-time item; SubCo (Citykart Stores) carries the stores and the rest.
 * Consolidated is the MIS and is unchanged. Shares are invented.
 */
const HOLDCO_SHARE: Partial<Record<Leaf, number>> = { dc_cost: 0.4, ho_cost: 0.38, one_time: 1 };
const entityFactor = (entity: MgmtEntity, k: Leaf) => (entity === "consolidated" ? 1 : entity === "holdco" ? (HOLDCO_SHARE[k] ?? 0) : 1 - (HOLDCO_SHARE[k] ?? 0));
const scaled = (l: Layer, entity: MgmtEntity): Layer => Object.fromEntries((Object.keys(l) as Leaf[]).map((k) => [k, r4(l[k] * entityFactor(entity, k))])) as Layer;
/** Below-EBITDA information: Ventures' interest income and finance cost (about 1.96 and 0.09 Cr over Apr-Aug). */
const BELOW: Record<string, [number, number]> = { interest_income: [0.392, 0.392], finance_cost: [-0.018, -0.018] };

function monthTriples(month: string, entity: MgmtEntity = "consolidated"): Record<string, Triple> {
  const tot = scaled(totalLayer(month), entity);
  const adj = scaled(adjustmentLayer(month), entity);
  const t = {} as Record<Leaf, Triple>;
  (Object.keys(tot) as Leaf[]).forEach((k) => (t[k] = { book: r4(tot[k] - adj[k]), adjustment: adj[k], total: tot[k] }));
  const income = sumT([t.revenue, t.other_operating_income]);
  const margin = sumT([income, t.material_cost]);
  const storeExp = sumT([t.rent, t.employee_cost, t.power_fuel, t.advertisement, t.freight, t.other_expenses]);
  const storeEbitda = sumT([margin, storeExp]);
  const corpCost = sumT([t.dc_cost, t.ho_cost]);
  const corp = sumT([storeEbitda, corpCost]);
  const post = sumT([corp, t.one_time]);
  const below = entity === "subco" ? { interest_income: { book: 0, adjustment: 0, total: 0 }, finance_cost: { book: 0, adjustment: 0, total: 0 } } : { interest_income: { book: BELOW.interest_income[0], adjustment: 0, total: BELOW.interest_income[0] }, finance_cost: { book: BELOW.finance_cost[0], adjustment: 0, total: BELOW.finance_cost[0] } };
  return { ...t, ...below, total_income: income, material_margin: margin, total_store_expenses: storeExp, store_ebitda: storeEbitda, total_corporate: corpCost, corporate_ebitda: corp, ebitda_post_one_time: post };
}

const ORDER: { key: string; label: string; kind: "value" | "subtotal" }[] = [
  { key: "revenue", label: "Revenue from operations", kind: "value" },
  { key: "other_operating_income", label: "Other operating income", kind: "value" },
  { key: "total_income", label: "Total income", kind: "subtotal" },
  { key: "material_cost", label: "Material cost", kind: "value" },
  { key: "material_margin", label: "Material margin", kind: "subtotal" },
  { key: "rent", label: "Rent", kind: "value" },
  { key: "employee_cost", label: "Employee cost", kind: "value" },
  { key: "power_fuel", label: "Power and fuel", kind: "value" },
  { key: "advertisement", label: "Advertisement", kind: "value" },
  { key: "freight", label: "Freight forwarding", kind: "value" },
  { key: "other_expenses", label: "Other expenses", kind: "value" },
  { key: "total_store_expenses", label: "Total store expenses", kind: "subtotal" },
  { key: "store_ebitda", label: "Store EBITDA", kind: "subtotal" },
  { key: "dc_cost", label: "DC cost", kind: "value" },
  { key: "ho_cost", label: "HO cost", kind: "value" },
  { key: "total_corporate", label: "Total corporate cost", kind: "subtotal" },
  { key: "corporate_ebitda", label: "Corporate EBITDA", kind: "subtotal" },
  { key: "one_time", label: "One-time expense", kind: "value" },
  { key: "ebitda_post_one_time", label: "EBITDA post one-time", kind: "subtotal" },
];
const PCT_KEYS = ORDER.filter((o) => o.key !== "total_income").map((o) => o.key);

function pctTriple(num: Triple, income: Triple): Triple {
  const p = (n: number | null, d: number | null) => (n === null || !d ? null : Math.round((n / d) * 1e5) / 1e3);
  return { book: p(num.book, income.book), adjustment: p(num.adjustment, income.total), total: p(num.total, income.total) };
}

export function buildPnl(from = MONTHS[0], to = MONTHS[MONTHS.length - 1], includeProposed = true, entity: MgmtEntity = "consolidated"): MgmtPnl {
  const months = MONTHS.filter((m) => m >= from && m <= to);
  const per = Object.fromEntries(months.map((m) => [m, monthTriples(m, entity)]));
  const keys = [...ORDER.map((o) => o.key)];
  const total = (key: string) => sumT(months.map((m) => per[m][key]));
  const lines: MgmtLine[] = ORDER.map((o) => ({ key: o.key, label: o.label, kind: o.kind, values: Object.fromEntries(months.map((m) => [m, per[m][o.key]])), total: total(o.key) }));
  lines.push(
    { key: "interest_income", label: "Interest income", kind: "value", values: Object.fromEntries(months.map((m) => [m, per[m].interest_income])), total: total("interest_income") },
    { key: "finance_cost", label: "Finance cost", kind: "value", values: Object.fromEntries(months.map((m) => [m, per[m].finance_cost])), total: total("finance_cost") },
  );
  const incomeOf = (m: string) => per[m].total_income;
  for (const k of PCT_KEYS) {
    const base = ORDER.find((o) => o.key === k)!;
    lines.push({
      key: `pct_${k}`,
      label: `${base.label} % of total income`,
      kind: "pct",
      values: Object.fromEntries(months.map((m) => [m, pctTriple(per[m][k], incomeOf(m))])),
      total: pctTriple(total(k), total("total_income")),
    });
  }
  void keys;
  void includeProposed;
  return { run_id: RUN, entity, as_of_date: "2026-10-09", months, lines, store_count: entity === "holdco" ? 0 : 199, warnings: WARNINGS };
}

export const header: MgmtHeader = { run_id: RUN, as_of_date: "2026-10-09", months: MONTHS, warnings: WARNINGS };

// ---------------------------------------------------------------- stores
const TYPES = ["OLD", "OLD", "OLD", "NEW"];
const NAMES = ["Alpha Nagar", "Beta Chowk", "Gamma Plaza", "Delta Market", "Epsilon Road", "Zeta Junction", "Eta Bazaar", "Theta Square", "Iota Mall", "Kappa Street", "Lambda Heights", "Mu Colony", "Nu Park", "Xi Circle", "Omicron Gate", "Pi Crossing", "Rho Market", "Sigma Lane", "Tau Plaza", "Upsilon Point", "Phi Centre", "Chi Haat", "Psi Nagar", "Omega Plaza"];

export function buildStores(entity: MgmtEntity = "consolidated"): MgmtStores {
  const n = NAMES.length;
  const NET = 127.32;
  const weights = NAMES.map((_, i) => 1 + ((i * 37) % 11) / 5);
  const wsum = weights.reduce((a, b) => a + b, 0);
  const ns = weights.map((w) => Math.round((w / wsum) * NET * 1e4) / 1e4);
  ns[n - 1] = r4(NET - ns.slice(0, n - 1).reduce((a, b) => a + b, 0));
  const RGM = 35.65;
  const EXP = -25.91;
  const rate = 6.4 / NET; // fraction of net sales: 5.03%
  const rgmShare = ns.map((x, i) => x * (RGM / NET) * (1 + ((i % 5) - 2) * 0.02));
  const rgmScale = RGM / rgmShare.reduce((a, b) => a + b, 0);
  const expShare = ns.map((x, i) => x * (EXP / NET) * (1 + ((i % 7) - 3) * 0.03));
  const expScale = EXP / expShare.reduce((a, b) => a + b, 0);
  const rows: MgmtStoreRow[] = NAMES.map((name, i) => {
    const rgm = r4(rgmShare[i] * rgmScale);
    const exp = r4(expShare[i] * expScale);
    const four = r4(rgm + exp);
    const app = r4(-ns[i] * rate);
    return { store: name, site_code: String(1001 + i), store_type: TYPES[i % TYPES.length], net_sales: ns[i], rgm, store_expenses: exp, four_wall: four, apportioned: app, ebitda_after: r4(four + app) };
  });
  const sum = (f: (r: MgmtStoreRow) => number | null) => r4(rows.reduce((s, r) => s + (f(r) ?? 0), 0));
  if (entity === "holdco") return { run_id: RUN, entity, rate: 0, summary: { net_sales: 0, rgm: 0, store_expenses: 0, four_wall: 0, apportioned: 0, store_ebitda_after: 0, dc_total: -0.89, ho_total: -1.59, reconciles: true }, rows: [] };
  if (entity === "subco") {
    // SubCo carries the part of DC and HO cost that is not HoldCo's, spread at its own blended rate
    const dc = -1.33;
    const ho = -2.59;
    const subRate = -(dc + ho) / NET;
    const sub = rows.map((r) => ({ ...r, apportioned: r4(-(r.net_sales ?? 0) * subRate), ebitda_after: r4(r.four_wall! - (r.net_sales ?? 0) * subRate) }));
    const s2 = (f: (r: MgmtStoreRow) => number | null) => r4(sub.reduce((a, r) => a + (f(r) ?? 0), 0));
    return { run_id: RUN, entity, rate: subRate, summary: { net_sales: s2((r) => r.net_sales), rgm: s2((r) => r.rgm), store_expenses: s2((r) => r.store_expenses), four_wall: s2((r) => r.four_wall), apportioned: s2((r) => r.apportioned), store_ebitda_after: s2((r) => r.ebitda_after), dc_total: dc, ho_total: ho, reconciles: true }, rows: sub };
  }
  return {
    run_id: RUN,
    entity,
    rate,
    summary: {
      net_sales: sum((r) => r.net_sales),
      rgm: sum((r) => r.rgm),
      store_expenses: sum((r) => r.store_expenses),
      four_wall: sum((r) => r.four_wall),
      apportioned: sum((r) => r.apportioned),
      store_ebitda_after: sum((r) => r.ebitda_after),
      dc_total: -2.22,
      ho_total: -4.18,
      reconciles: true,
    },
    rows,
  };
}

// ---------------------------------------------------------------- reconciliation
const RECON_KEYS = ["revenue", "other_operating_income", "material_cost", "rent", "employee_cost", "power_fuel", "advertisement", "freight", "other_expenses", "store_ebitda", "dc_cost", "ho_cost", "corporate_ebitda"];
/** Where the published MIS carries a hard-coded override, the portal's own computation differs (portal minus MIS). */
const OVERRIDES: Record<string, Record<string, { delta: number; reason: string }>> = {
  "2026-05": {
    other_operating_income: { delta: -0.031, reason: "Hard-coded +0.031 in the MIS sheet (May other operating income)" },
    dc_cost: { delta: 0.026, reason: "Hard-coded -0.026 in the MIS sheet (May DC cost)" },
  },
  "2026-06": { other_expenses: { delta: 0.055, reason: "Hard-coded value in the MIS sheet (June other expenses)" } },
};
const CORP_FROM: Record<string, string[]> = { store_ebitda: ["other_operating_income", "other_expenses"], corporate_ebitda: ["other_operating_income", "other_expenses", "dc_cost"] };

export function buildRecon(from = MONTHS[0], to = MONTHS[MONTHS.length - 1], entity: MgmtEntity = "consolidated"): MgmtReconciliation {
  const months = MONTHS.filter((m) => m >= from && m <= to);
  const lines: MgmtReconLine[] = RECON_KEYS.map((key) => {
    const label = ORDER.find((o) => o.key === key)!.label;
    const values: MgmtReconLine["values"] = {};
    for (const m of months) {
      const mis = monthTriples(m, entity)[key].total as number;
      const ov = entity === "consolidated" ? (OVERRIDES[m] ?? {}) : {}; // the MIS sheet is consolidated: overrides are only compared there
      let delta = ov[key]?.delta ?? 0;
      let reason: string | null = ov[key]?.reason ?? null;
      if (CORP_FROM[key]) {
        const parts = CORP_FROM[key].filter((k) => ov[k]);
        delta = parts.reduce((s, k) => s + ov[k].delta, 0);
        reason = parts.length ? "Sum of the hard-coded overrides above" : null;
      }
      const variance = r4(delta);
      values[m] = { mis: r4(mis), portal: r4(mis + variance), variance, tied: Math.abs(variance) <= 0.0045, override_reason: reason };
    }
    return { key, label, values };
  });
  const status = months.map((m) => ({ month: m, status: (lines.every((l) => l.values[m].tied) ? "TIED" : "VARIANCE") as "TIED" | "VARIANCE" }));
  return { run_id: RUN, entity, months: status, lines, bridge: BRIDGE, warnings: WARNINGS };
}

export const BRIDGE: MgmtBridgeStep[] = [
  { step: "Portal Corporate EBITDA (books only)", cr: 87.29, nature: "Start", note: "gold_fpa ledger, Apr-Aug" },
  { step: "Citykart Ventures OU not in portal", cr: -14.52, nature: "Missing data", note: "CKVPL warehouses and CRPL-HO; stop-gap from the workbook" },
  { step: "COGS correction (1.0% of net sales, every month)", cr: -6.12, nature: "Management provision", note: "Shrinkage provision" },
  { step: "Gratuity provision (stores 25L + HO 5L per month)", cr: -1.5, nature: "Management provision", note: "" },
  { step: "HO quarterly incentive provision", cr: -0.79, nature: "Management provision", note: "Jun -130.5L, Aug +51.6L" },
  { step: "Audit and CSR provision (5L + 6L per month)", cr: -0.55, nature: "Management provision", note: "" },
  { step: "Advertisement HO to stores movement", cr: -0.36, nature: "Manual reallocation", note: "" },
  { step: "COGS bifurcation journal (Aug)", cr: 0.8, nature: "Manual journal", note: "Possible double count if the portal books the same journal" },
  { step: "SIS income adjustment", cr: 2.07, nature: "Management adjustment", note: "" },
  { step: "COGS table difference", cr: 0.27, nature: "Source difference", note: "" },
  { step: "Book difference (ledger grouping and site/timing)", cr: -3.75, nature: "Mapping and classification", note: "" },
  { step: "= Management workbook Corporate EBITDA", cr: 62.85, nature: "Subtotal", note: "" },
  { step: "One-time item moved below EBITDA (Apr: Authorised Share Capital)", cr: 0.83, nature: "MIS presentation rule", note: "" },
  { step: "= MIS format Corporate EBITDA (computed)", cr: 63.68, nature: "Subtotal", note: "Published 63.63; the last 0.05 is hard-coded overrides in the MIS sheet" },
];

// ---------------------------------------------------------------- adjustments and mapping
export const ADJUSTMENTS: MgmtAdjustment[] = [
  { id: 1, month: "2026-08", mis_line: "material_cost", location_type: "STORES", amount_cr: -1.16, kind: "PROVISION", rule: "COGS correction: 1% of net sales", owner: "Finance", status: "APPROVED", source: "Provision TY", note: "Shrinkage provision, every month" },
  { id: 2, month: "2026-08", mis_line: "employee_cost", location_type: "STORES", amount_cr: -0.25, kind: "PROVISION", rule: "Gratuity: 25L per month", owner: "Finance", status: "APPROVED", source: "Provision TY", note: "" },
  { id: 3, month: "2026-08", mis_line: "employee_cost", location_type: "HO", amount_cr: -0.02, kind: "PROVISION", rule: "Gratuity: HO share", owner: "Finance", status: "APPROVED", source: "Provision TY", note: "" },
  { id: 4, month: "2026-08", mis_line: "advertisement", location_type: "STORES", amount_cr: -0.33, kind: "REALLOCATION", rule: "Advertisement movement HO to stores", owner: "Marketing", status: "PROPOSED", source: "Remarks", note: "Awaiting sign-off" },
  { id: 5, month: "2026-08", mis_line: "dc_cost", location_type: "DC", amount_cr: -1.31, kind: "MISSING_ENTITY", rule: "Citykart Ventures OU (CKVPL warehouses)", owner: "Finance", status: "PROPOSED", source: "VENTURE_DATA", note: "Stop-gap from the workbook until the extract lands" },
  { id: 6, month: "2026-08", mis_line: "ho_cost", location_type: "HO", amount_cr: -1.61, kind: "MISSING_ENTITY", rule: "Citykart Ventures OU (CRPL-HO)", owner: "Finance", status: "PROPOSED", source: "VENTURE_DATA", note: "Stop-gap from the workbook until the extract lands" },
  { id: 7, month: "2026-08", mis_line: "other_expenses", location_type: "STORES", amount_cr: 0.03, kind: "JOURNAL", rule: "COGS bifurcation journal", owner: "Finance", status: "APPROVED", source: "Workbook", note: "" },
  { id: 9, month: "2026-08", mis_line: "ho_cost", location_type: "HO", amount_cr: 0.12, kind: "elimination", rule: "Intercompany recharge from HoldCo to SubCo", owner: "Finance", status: "PROPOSED", source: "Intercompany", note: "Eliminates on consolidation", counterparty: "Citykart Stores (CKSPL)", counterparty_entity: "SubCo" },
  { id: 8, month: "2026-04", mis_line: "one_time", location_type: "HO", amount_cr: -0.83, kind: "ONE_TIME", rule: "Increase in Authorised Share Capital", owner: "CFO", status: "APPROVED", source: "Workbook", note: "Shown below Corporate EBITDA" },
];
export const adjustments: MgmtAdjustments = { rows: ADJUSTMENTS };

export const mapping: MgmtMapping = {
  rows: [
    { ledger: "Sales - Retail", mgmt_group: "Net Sales", major_group: "Revenue", category: null, source: "Ledger_Mapping", note: null },
    { ledger: "Cost of goods sold", mgmt_group: "COGS Product", major_group: "Material cost", category: null, source: "Ledger_Mapping", note: null },
    { ledger: "Store rent", mgmt_group: "Rent", major_group: "Rent", category: null, source: "Ledger_Mapping", note: null },
    { ledger: "Salaries and wages", mgmt_group: "Employee Cost", major_group: "Employee cost", category: "Salaries", source: "Ledger_Mapping", note: null },
    { ledger: "Gratuity", mgmt_group: "Employee Cost", major_group: "Employee cost", category: "Provision", source: "Finance decision", note: "Portal groups this under Miscellaneous" },
    { ledger: "Electricity", mgmt_group: "Power and Fuel", major_group: "Power and fuel", category: null, source: "Ledger_Mapping", note: null },
    { ledger: "Freight outward", mgmt_group: "Freight Outward", major_group: "Freight forwarding", category: null, source: "Ledger_Mapping", note: null },
  ],
  exceptions: [
    { ledger: "MKTG-Loyalty/Communication", amount_cr: -0.97, reason: "Not in the management mapping" },
    { ledger: "Director remuneration", amount_cr: -0.95, reason: "In the workbook, missing from the portal ledger master" },
    { ledger: "Professional Charges", amount_cr: -0.54, reason: "Conflicting group: Legal vs Employee Cost" },
  ],
};

// ---------------------------------------------------------------- the stubbed API
const ent = (v: unknown): MgmtEntity => (v === "subco" || v === "holdco" ? v : "consolidated");

export function fixtureResponse(path: string, params: Record<string, string | number | boolean | undefined> = {}): unknown {
  switch (path) {
    case "current":
      return header;
    case "pnl":
      return buildPnl(params.from_month as string | undefined, params.to_month as string | undefined, params.include_proposed !== false && params.include_proposed !== "false", ent(params.entity));
    case "stores":
      return buildStores(ent(params.entity));
    case "reconciliation":
      return buildRecon(params.from_month as string | undefined, params.to_month as string | undefined, ent(params.entity));
    case "adjustments":
      return adjustments;
    case "mapping":
      return mapping;
    default:
      throw new Error(`no fixture for ${path}`);
  }
}
