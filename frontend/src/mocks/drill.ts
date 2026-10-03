import type {
  DrillNode,
  DrillOrigin,
  DrillRow,
  DrillSplit,
  DrillView,
  EntityProfile,
  Family,
  LedgerEntry,
  LedgerView,
  QueryCtx,
  Tone,
  VoucherEvidence,
} from "@/types/cfo";
import { COMPARISONS } from "./scenarios";
import { AGEING_BUCKETS, ALL_STORES, DEPARTMENTS, REGIONS, STORES, VENDORS, rng, splitAmount } from "./seed";

const r2 = (n: number) => Math.round(n * 100) / 100;
const r4 = (n: number) => Math.round(n * 1e4) / 1e4;

/** Dimensions that end the drill: an entity worth a deep page. */
const TERMINAL_DIMS = new Set(["Store", "Vendor", "Account"]);
const DRIVER_DIMS = new Set(["Department", "Ageing bucket", "Driver", "Payroll head", "Occupancy head", "Power head", "Inflow source", "Obligation", "Settlement channel", "Source system"]);

export function levelForDim(dim: string): DrillNode["level"] {
  return DRIVER_DIMS.has(dim) ? "driver" : "entity";
}

/** Which dimensions each investigation walks through. */
export function chainFor(origin: DrillOrigin): string[] {
  switch (origin.id) {
    case "payroll":
      return ["Payroll head", "Region", "Store"];
    case "occupancy":
      return ["Occupancy head", "Region", "Store"];
    case "electricity":
      return ["Power head", "Region", "Store"];
    case "inventory":
      return ["Department", "Region", "Store"];
    case "creditors":
    case "creditors_181":
      return ["Ageing bucket", "Vendor"];
    case "vendor_advances":
    case "advances_90":
      return ["Ageing bucket", "Vendor"];
    case "receivables":
      return ["Settlement channel", "Store"];
    case "other_wc":
      return ["Account"];
  }
  const byFamily: Record<Family, string[]> = {
    margin: ["Department", "Region", "Store"],
    volume: ["Region", "Store", "Department"],
    cost: ["Payroll head", "Region", "Store"],
    cash: ["Inflow source", "Obligation", "Account"],
    payables: ["Ageing bucket", "Vendor"],
    advances: ["Ageing bucket", "Vendor"],
    recon: ["Source system", "Account"],
    forecast: ["Department", "Region", "Store"],
  };
  return byFamily[origin.family];
}

const POOLS: Record<string, string[]> = {
  Department: DEPARTMENTS,
  Region: REGIONS,
  "Ageing bucket": AGEING_BUCKETS,
  Vendor: VENDORS,
  "Payroll head": ["Store staff", "Supervisors", "Contract labour", "Incentives", "Head office"],
  "Occupancy head": ["Rent", "CAM charges", "Property tax", "Security & housekeeping"],
  "Power head": ["Grid power", "DG fuel", "AC load", "Lighting"],
  "Inflow source": ["Store collections", "Card settlements", "UPI settlements", "Franchise receipts"],
  Obligation: ["Vendor payment run", "Payroll", "GST & statutory", "Rent & CAM"],
  "Settlement channel": ["Card acquirer", "UPI", "Franchise", "B2B"],
  "Source system": ["Ginesys POS", "Bank statements", "Card settlements", "Vendor ledger"],
  Account: ["Bank – HDFC Current", "Bank – ICICI Collection", "Card settlement clearing", "GST input credit", "Security deposits", "Prepaid expenses"],
  Driver: [],
};

const DIM_PLURAL: Record<string, string> = {
  Department: "departments",
  Region: "regions",
  Store: "stores",
  Vendor: "vendors",
  "Ageing bucket": "ageing buckets",
};

const BAD_WHEN_UP = new Set<Family>(["payables", "advances", "recon"]);

function toneFor(delta: number, family: Family): Tone {
  if (Math.abs(delta) < 0.0049) return "neutral";
  return BAD_WHEN_UP.has(family) ? (delta > 0 ? "bad" : "good") : delta > 0 ? "good" : "bad";
}

function seedKey(ctx: QueryCtx, origin: DrillOrigin, nodes: DrillNode[], extra = ""): string {
  return `${ctx.scenario}|${ctx.period}|${origin.id}|${nodes.map((n) => n.id).join(">")}|${extra}`;
}

function filterNodes(nodes: DrillNode[]): DrillNode[] {
  return nodes.filter((n) => n.level === "driver" || n.level === "entity");
}

function candidatePool(dim: string, nodes: DrillNode[]): { name: string; sub?: string }[] {
  if (dim === "Store") {
    const region = nodes.find((n) => n.dim === "Region")?.label;
    if (region) return STORES[region].map((name) => ({ name, sub: region }));
    return ALL_STORES.map((s) => ({ name: s.name, sub: s.region }));
  }
  const pool = POOLS[dim] ?? [];
  if (dim === "Vendor") {
    const bucket = nodes.find((n) => n.dim === "Ageing bucket");
    return pool.slice(0, bucket ? 8 : 12).map((name) => ({ name, sub: bucket?.label }));
  }
  return pool.map((name) => ({ name }));
}

/**
 * Showcase weights for the margin investigation so the demo story is material:
 * Menswear leads (−0.84 of −1.42 Cr), North leads regions, Rohini leads North's stores.
 * Weights sum to 1, so every split still reconciles exactly to its parent.
 */
const MARGIN_DEPT_WEIGHTS: Record<string, number> = {
  Menswear: 0.84 / 1.42,
  Womenswear: 0.29 / 1.42,
  Kidswear: 0.18 / 1.42,
  Footwear: 0.06 / 1.42,
  Accessories: 0.03 / 1.42,
  "Home & Living": 0.02 / 1.42,
};
const MARGIN_REGION_WEIGHTS: Record<string, number> = { North: 0.38, West: 0.27, South: 0.22, East: 0.13 };
const NORTH_STORE_WEIGHTS: Record<string, number> = {
  Rohini: 0.34,
  "Karol Bagh": 0.22,
  "Sector 18 Noida": 0.17,
  "Gurugram MG Road": 0.13,
  "Ludhiana Model Town": 0.08,
  "Jaipur C-Scheme": 0.06,
};

function fixedWeights(origin: DrillOrigin, dim: string, nodes: DrillNode[], names: string[]): number[] | null {
  if (origin.family !== "margin") return null;
  let table: Record<string, number> | null = null;
  if (dim === "Department") table = MARGIN_DEPT_WEIGHTS;
  else if (dim === "Region") table = MARGIN_REGION_WEIGHTS;
  else if (dim === "Store" && nodes.find((n) => n.dim === "Region")?.label === "North") table = NORTH_STORE_WEIGHTS;
  if (!table || !names.every((n) => n in table!)) return null;
  const w = names.map((n) => table![n]);
  const s = w.reduce((a, b) => a + b, 0);
  return w.map((x) => x / s);
}

/** Splits `total` by weights; 4dp rounding with the drift put on the largest part so parts sum exactly. */
function weightedSplit(total: number, weights: number[]): number[] {
  const parts = weights.map((w) => Math.round(total * w * 1e4) / 1e4);
  const drift = Math.round((total - parts.reduce((a, b) => a + b, 0)) * 1e4) / 1e4;
  const big = weights.indexOf(Math.max(...weights));
  parts[big] = Math.round((parts[big] + drift) * 1e4) / 1e4;
  return parts;
}

function buildSplit(
  ctx: QueryCtx,
  origin: DrillOrigin,
  nodes: DrillNode[],
  dim: string,
  amount: number,
  variance: number,
): DrillSplit {
  const cand = candidatePool(dim, nodes);
  const seed = seedKey(ctx, origin, nodes, dim);
  const fixed = fixedWeights(origin, dim, nodes, cand.map((c) => c.name));
  const amounts = fixed ? weightedSplit(amount, fixed) : splitAmount(amount, cand.length, seed);
  const vWeights = fixed ? weightedSplit(variance, fixed) : splitAmount(variance, cand.length, seed + "|v", 1.6);
  const isDeltaOrigin = origin.source === "bridge" && origin.variance !== null && origin.amount === origin.variance;
  const rows: DrillRow[] = cand.map((c, i) => {
    const delta = isDeltaOrigin ? amounts[i] : vWeights[i];
    return {
      node: {
        level: levelForDim(dim),
        dim,
        id: `${dim}:${c.name}`,
        label: c.name,
        amount: amounts[i],
        variance: r4(delta),
      },
      amount: amounts[i],
      share: amount === 0 ? 0 : Math.abs(amounts[i] / amount),
      delta: r4(delta),
      tone: toneFor(delta, origin.family),
      sublabel: c.sub,
    };
  });
  rows.sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));
  const regionFiltered = nodes.some((n) => n.dim === "Region");
  const limit = dim === "Store" ? (regionFiltered ? rows.length : 5) : dim === "Vendor" ? 8 : rows.length;
  const shown = rows.slice(0, limit);
  const rest = rows.slice(limit);
  const other = rest.length
    ? { count: rest.length, amount: r4(rest.reduce((a, r) => a + r.amount, 0)), delta: r4(rest.reduce((a, r) => a + r.delta, 0)) }
    : undefined;
  return { dim, rows: shown, other };
}

const DRIVER_TEMPLATES: Record<Family, string[]> = {
  margin: ["Markdown depth", "Mix shift to lower-margin lines", "Shrinkage and damages"],
  volume: ["Footfall softness", "Conversion rate", "Average bill value"],
  cost: ["Headcount vs plan", "Contract rate changes", "Overtime and incentives"],
  cash: ["Timing of vendor runs", "Collection delays", "Capex phasing"],
  payables: ["Payment holds on disputed GRNs", "Credit-term extensions", "Debit-note adjustments pending"],
  advances: ["Supplies not yet received", "Advances not adjusted against invoices", "Season-start advance cover"],
  recon: ["Card settlement timing", "Bank statement mismatches", "Unmapped GL accounts"],
  forecast: ["Festive sell-through assumption", "Markdown calendar", "Cost run-rate"],
};

function buildDrivers(ctx: QueryCtx, origin: DrillOrigin, nodes: DrillNode[], amount: number, variance: number): DrillRow[] {
  const names = DRIVER_TEMPLATES[origin.family];
  const seed = seedKey(ctx, origin, nodes, "drivers");
  const parts = splitAmount(amount * 0.88, names.length, seed, 1.4);
  const isDeltaOrigin = origin.source !== "pulse" && origin.variance !== null && origin.amount === origin.variance;
  const vparts = isDeltaOrigin ? parts : splitAmount(variance * 0.88, names.length, seed + "|v", 1.4);
  return names.map((name, i) => ({
    node: { level: "driver" as const, dim: "Driver", id: `Driver:${name}`, label: name, amount: parts[i], variance: r4(vparts[i]) },
    amount: parts[i],
    share: amount === 0 ? 0 : Math.abs(parts[i] / amount),
    delta: r4(vparts[i]),
    tone: toneFor(vparts[i], origin.family),
  }));
}

function money(n: number): string {
  const a = Math.abs(n);
  return a >= 0.1 ? `₹${a.toFixed(2)} Cr` : `₹${(a * 100).toFixed(1)} L`;
}

function explain(origin: DrillOrigin, label: string, amount: number, variance: number, top: DrillRow[], family: Family): string {
  const t1 = top[0]?.node.label;
  const t2 = top[1]?.node.label;
  const lead = t1 && t2 ? `${t1} and ${t2} account for ${Math.round(((Math.abs(top[0].amount) + Math.abs(top[1].amount)) / Math.max(Math.abs(amount), 1e-9)) * 100)}% of it.` : "";
  const dir = variance < 0 ? "below" : "above";
  switch (family) {
    case "margin":
      return `${label} is ${money(variance)} ${dir} the comparison. Deeper markdowns and a mix shift toward lower-margin lines explain most of the movement. ${lead}`;
    case "cost":
      return `${label} is ${money(variance)} ${variance < 0 ? "adverse" : "favourable"} to the comparison, driven by headcount and contract-rate changes. ${lead}`;
    case "volume":
      return `${label} moved ${money(variance)} ${dir} the comparison. Footfall and conversion are the main drivers. ${lead}`;
    case "payables":
      return `${label} stands at ${money(amount)}. Disputed receipts and extended credit terms keep balances open beyond terms. ${lead}`;
    case "advances":
      return `${label} stands at ${money(amount)}. Most of the balance sits with vendors whose supplies are not yet received or adjusted. ${lead}`;
    case "recon":
      return `${label} stands at ${money(amount)} awaiting reconciliation. Card-settlement timing and unmapped accounts dominate. Source mapping is still pending. ${lead}`;
    case "cash":
      return `${label} is ${money(amount)}. Timing of vendor payment runs against inflows drives the movement. ${lead}`;
    default:
      return `${label} is ${money(variance)} ${dir} budget. ${lead}`;
  }
}

export function buildDrill(ctx: QueryCtx, origin: DrillOrigin, allNodes: DrillNode[]): DrillView {
  const nodes = filterNodes(allNodes);
  const last = nodes[nodes.length - 1];
  const amount = last?.amount ?? origin.amount ?? 0;
  const variance = last?.variance ?? origin.variance ?? 0;
  const chain = chainFor(origin);
  const used = new Set(nodes.map((n) => n.dim));
  const remaining = chain.filter((d) => !used.has(d));
  const terminal = remaining.length === 0 || (last ? TERMINAL_DIMS.has(last.dim) : false);
  const cmp = COMPARISONS[ctx.comparison];

  const splits: DrillSplit[] = terminal ? [] : remaining.slice(0, 3).map((d) => buildSplit(ctx, origin, nodes, d, amount, variance));
  const primary = splits[0]?.rows ?? [];
  const label = last?.label ?? origin.label;
  const shares = primary.map((r) => r.share);
  const top2 = shares.slice(0, 2).reduce((a, b) => a + b, 0);
  const dimName = splits[0] ? (DIM_PLURAL[splits[0].dim] ?? splits[0].dim.toLowerCase()) : "";
  const drivers = terminal || used.has("Driver") ? [] : buildDrivers(ctx, origin, nodes, amount, variance);
  const entityKind: DrillView["entityKind"] = last?.dim === "Store" ? "store" : last?.dim === "Vendor" ? "vendor" : last?.dim === "Account" ? "account" : "other";
  const base = Math.abs(origin.base ?? 0) || Math.abs(amount - variance) || Math.abs(amount) || 1;
  const rr = rng(seedKey(ctx, origin, nodes, "facts"));

  let facts: DrillView["facts"] = [];
  if (terminal) {
    if (entityKind === "store") {
      const region = nodes.find((n) => n.dim === "Region")?.label ?? ALL_STORES.find((s) => s.name === last?.label)?.region ?? "—";
      facts = [
        { label: "Region", value: region },
        { label: "Format", value: rr() > 0.5 ? "Large format" : "Standard format" },
        { label: "Trading area", value: `${Math.round(4500 + rr() * 5000).toLocaleString("en-IN")} sq ft` },
        { label: "Open since", value: String(2011 + Math.floor(rr() * 12)) },
      ];
    } else if (entityKind === "vendor") {
      facts = [
        { label: "Vendor code", value: `V${String(10000 + Math.floor(rr() * 8999))}` },
        { label: "Payment terms", value: `${[30, 45, 60, 90][Math.floor(rr() * 4)]} days` },
        { label: "Open invoices", value: String(6 + Math.floor(rr() * 40)) },
        { label: "Last payment", value: `${1 + Math.floor(rr() * 27)} Sep 2026` },
      ];
    } else {
      facts = [
        { label: "GL account", value: String(1000 + Math.floor(rr() * 8000)) },
        { label: "Mapping status", value: "Awaiting finance mapping" },
      ];
    }
  }

  return {
    title: label,
    levelLabel: !last ? "Movement" : `${last.level === "driver" ? "Driver" : "Entity"} · ${last.dim}`,
    amount,
    variance,
    variancePct: r2((variance / base) * 100),
    comparisonLabel: cmp.label,
    tone: toneFor(variance, origin.family),
    explanation: explain(origin, label, amount, variance, primary, origin.family),
    concentration: {
      headline: terminal ? "Single entity — open its ledger or profile for evidence" : `${Math.round(top2 * 100)}% from top 2 ${dimName}`,
      topShares: shares.slice(0, 5),
    },
    splits,
    supportingDrivers: drivers,
    terminal,
    entityKind,
    facts,
  };
}

/* ───────────── ledger / voucher / profile ───────────── */

function accountFor(origin: DrillOrigin): { code: string; name: string; side: "debit" | "credit" } {
  switch (origin.family) {
    case "payables":
      return { code: "2100", name: "Trade Creditors", side: "credit" };
    case "advances":
      return { code: "1450", name: "Advances to Vendors", side: "debit" };
    case "recon":
      return { code: "1900", name: "Clearing – Unreconciled", side: "debit" };
    case "cash":
      return { code: "1010", name: "Bank – Operating", side: "debit" };
    case "cost":
      return origin.id === "occupancy"
        ? { code: "6200", name: "Rent & Occupancy", side: "debit" }
        : origin.id === "electricity"
          ? { code: "6240", name: "Power & Fuel", side: "debit" }
          : { code: "6100", name: "Salaries & Wages", side: "debit" };
    case "volume":
      return { code: "4100", name: "Sales – Retail", side: "credit" };
    default:
      return { code: "5100", name: "Cost of Goods Sold", side: "debit" };
  }
}

const VTYPES = [
  { p: "JV", name: "Journal Voucher", src: "Ginesys Finance" },
  { p: "PV", name: "Payment Voucher", src: "Ginesys AP" },
  { p: "SV", name: "Sales Voucher", src: "Ginesys POS" },
  { p: "DN", name: "Debit Note", src: "Ginesys AP" },
];

export function buildLedger(ctx: QueryCtx, origin: DrillOrigin, allNodes: DrillNode[]): LedgerView {
  const nodes = filterNodes(allNodes);
  const last = nodes[nodes.length - 1];
  const amountRs = Math.abs((last?.amount ?? origin.amount ?? 1) * 1e7);
  const acct = accountFor(origin);
  const r = rng(seedKey(ctx, origin, nodes, "ledger"));
  const n = 12;
  const opp = [2, 5, 9];
  const mainParts = splitAmount(amountRs * 1.35, n - opp.length, seedKey(ctx, origin, nodes, "lm"), 1.5);
  const oppParts = splitAmount(amountRs * 0.35, opp.length, seedKey(ctx, origin, nodes, "lo"), 1.2);
  let mi = 0;
  let oi = 0;
  const opening = Math.round(amountRs * (0.6 + r() * 0.5));
  let bal = opening;
  const entries: LedgerEntry[] = [];
  for (let i = 0; i < n; i++) {
    const isOpp = opp.includes(i);
    const val = Math.round(isOpp ? oppParts[oi++] : mainParts[mi++]);
    const side = isOpp ? (acct.side === "debit" ? "credit" : "debit") : acct.side;
    const vt = VTYPES[Math.floor(r() * VTYPES.length)];
    const day = 1 + Math.floor((i / n) * 160 + r() * 10);
    const date = new Date(Date.UTC(2026, 3, 1 + day));
    const debit = side === "debit" ? val : 0;
    const credit = side === "credit" ? val : 0;
    bal += debit - credit;
    const recon: LedgerEntry["recon"] = r() > 0.82 ? "exception" : r() > 0.5 ? "pending" : "matched";
    entries.push({
      id: `E${i + 1}`,
      date: date.toISOString().slice(0, 10),
      voucherId: `${vt.p}-26-${String(4000 + Math.floor(r() * 5900)).padStart(6, "0")}`,
      voucherType: vt.name,
      account: acct.code,
      accountName: acct.name,
      narration: `${last?.label ?? origin.label} — ${["Month-end accrual", "Invoice posting", "Settlement", "Adjustment", "Provision release"][Math.floor(r() * 5)]}`,
      debit,
      credit,
      balance: bal,
      source: vt.src,
      recon,
    });
  }
  return {
    title: `GL ${acct.code} · ${acct.name}`,
    subtitle: [origin.label, ...nodes.map((x) => x.label)].join(" › "),
    openingBalance: opening,
    closingBalance: bal,
    entries,
  };
}

export function buildVoucher(ctx: QueryCtx, voucherId: string, amount: number | null): VoucherEvidence {
  const r = rng(`${ctx.scenario}|v|${voucherId}`);
  const prefix = voucherId.split("-")[0];
  const vt = VTYPES.find((v) => v.p === prefix) ?? VTYPES[0];
  const total = Math.round(amount !== null ? Math.abs(amount) : 50000 + r() * 3e6);
  const split1 = Math.round(total * (0.55 + r() * 0.2));
  const lines = [
    { account: "5100", accountName: "Cost of Goods Sold", costCenter: "Merchandise", debit: split1, credit: 0 },
    { account: "2150", accountName: "GST Input Credit", costCenter: "Statutory", debit: total - split1, credit: 0 },
    { account: "2100", accountName: "Trade Creditors", costCenter: "Accounts Payable", debit: 0, credit: total },
  ];
  const day = 1 + Math.floor(r() * 150);
  const date = new Date(Date.UTC(2026, 3, 1 + day));
  return {
    voucherId,
    voucherType: vt.name,
    date: date.toISOString().slice(0, 10),
    postedBy: ["R. Mehta", "S. Iyer", "A. Khanna", "P. Desai"][Math.floor(r() * 4)],
    sourceSystem: vt.src,
    documentRef: `DOC/${String(100000 + Math.floor(r() * 899999))}`,
    narration: "Posted from source document; supporting invoice and GRN attached",
    status: "Posted · reconciliation pending",
    total,
    lines,
    evidence: {
      sourceObject: "Source object not yet confirmed (registry: UNVERIFIED)",
      extractionBatch: `DEMO-${String(Math.floor(r() * 9000) + 1000)}`,
      rowHash: Array.from({ length: 16 }, () => Math.floor(r() * 16).toString(16)).join(""),
      mappingStatus: "Awaiting finance mapping",
      attachments: [
        { name: `${voucherId}-invoice.pdf`, kind: "Supplier invoice", size: "184 KB" },
        { name: `${voucherId}-grn.pdf`, kind: "Goods receipt note", size: "92 KB" },
        { name: `${voucherId}-approval.png`, kind: "Approval trail", size: "61 KB" },
      ],
      trail: [
        { at: "02 Sep 2026 10:14", by: "System", action: "Extracted from source (demo)" },
        { at: "02 Sep 2026 11:40", by: "Finance ops", action: "Mapped to GL (pending confirmation)" },
        { at: "03 Sep 2026 09:05", by: "Approver", action: "Approved for posting" },
      ],
    },
  };
}

export function buildProfile(ctx: QueryCtx, origin: DrillOrigin, allNodes: DrillNode[]): EntityProfile {
  const nodes = filterNodes(allNodes);
  const last = nodes[nodes.length - 1];
  const r = rng(seedKey(ctx, origin, nodes, "profile"));
  const kind: EntityProfile["kind"] = last?.dim === "Store" ? "store" : last?.dim === "Vendor" ? "vendor" : "account";
  const amount = Math.abs(last?.amount ?? origin.amount ?? 1);
  const trend = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"].map((m, i) => ({ label: m, value: r2(amount * (0.7 + r() * 0.6) * (1 + i * 0.03)) }));
  const base = buildDrill(ctx, origin, allNodes);
  if (kind === "store") {
    return {
      title: `${last?.label ?? "Store"} — store profile`,
      kind,
      facts: base.facts,
      kpis: [
        { label: "Sales (YTD)", value: { value: r2(amount * 14) }, unit: "cr", tone: "neutral" },
        { label: "Gross margin", value: { value: r2(38 + r() * 6) }, unit: "pct", tone: "neutral" },
        { label: "Contribution", value: { value: r2(amount * 1.8) }, unit: "cr", tone: "good" },
        { label: "Rent as % of sales", value: { value: r2(6 + r() * 4) }, unit: "pct", tone: "warn" },
        { label: "Stock cover", value: { value: Math.round(70 + r() * 60) }, unit: "days", tone: "neutral" },
        { label: "Unreconciled", value: { value: null, reason: "Awaiting finance mapping" }, unit: "cr", tone: "neutral" },
      ],
      trend,
      trendLabel: "Contribution by month, ₹ Cr",
    };
  }
  return {
    title: `${last?.label ?? "Entity"} — ${kind === "vendor" ? "vendor profile" : "account profile"}`,
    kind,
    facts: base.facts,
    kpis: [
      { label: "Open balance", value: { value: r2(amount) }, unit: "cr", tone: "neutral" },
      { label: "Overdue > 90 days", value: { value: r2(amount * (0.2 + r() * 0.4)) }, unit: "cr", tone: "bad" },
      { label: "Advances outstanding", value: { value: r2(amount * r() * 0.5) }, unit: "cr", tone: "warn" },
      { label: "Average days to pay", value: { value: Math.round(48 + r() * 80) }, unit: "days", tone: "neutral" },
      { label: "Open invoices", value: { value: Math.round(6 + r() * 40) }, unit: "count", tone: "neutral" },
      { label: "Disputed amount", value: { value: null, reason: "Awaiting finance mapping" }, unit: "cr", tone: "neutral" },
    ],
    trend,
    trendLabel: "Open balance by month, ₹ Cr",
  };
}
