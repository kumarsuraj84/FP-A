import type {
  AbnormalCategory,
  AbnormalControl,
  AgeCohort,
  AgeFilter,
  AgeingBasis,
  AgeingBucket,
  AgeingMigration,
  AgeingMovement,
  BucketId,
  CreditorsOverview,
  ExposureMetric,
  LifecycleStage,
  MigrationBucketRow,
  VendorConcentration,
  VendorExposureRow,
  VendorOpenItem,
  VendorProfile,
} from "@/types/creditors";
import type { DrillNode, DrillOrigin, DrillRow, DrillView, LedgerEntry, LedgerView, QueryCtx } from "@/types/cfo";
import { cashFlowsFor, params } from "./builders";
import { VENDORS, hashStr, rng, weightedSplit } from "./seed";

const r4 = (n: number) => Math.round(n * 1e4) / 1e4;
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

/* ───────────── static definitions ───────────── */

export const BUCKET_DEFS: { id: BucketId; label: string; from: number; to: number | null }[] = [
  { id: "b0_30", label: "0–30 days", from: 0, to: 30 },
  { id: "b31_60", label: "31–60 days", from: 31, to: 60 },
  { id: "b61_90", label: "61–90 days", from: 61, to: 90 },
  { id: "b91_180", label: "91–180 days", from: 91, to: 180 },
  { id: "b181_365", label: "181–365 days", from: 181, to: 365 },
  { id: "b365p", label: ">365 days", from: 366, to: null },
];
export const BUCKET_IDS = BUCKET_DEFS.map((b) => b.id);
const bi = (id: BucketId) => BUCKET_IDS.indexOf(id);
export const bucketLabel = (id: BucketId) => BUCKET_DEFS[bi(id)].label;

/** Ageing basis is NOT confirmed. The mock provisionally places documents by document date and says so. */
export const AGEING_BASIS: AgeingBasis = {
  id: "unknown",
  confirmed: false,
  label: "Ageing basis awaiting finance validation",
  provisional: "document_date",
  candidates: ["document_date", "due_date"],
};

export const COHORTS: AgeCohort[] = [
  { id: "all", label: "All creditors", buckets: [...BUCKET_IDS], basisDependent: false },
  { id: "current", label: "Currently due", buckets: ["b0_30"], basisDependent: true },
  { id: "overdue", label: "Overdue", buckets: ["b31_60", "b61_90", "b91_180", "b181_365", "b365p"], basisDependent: true },
  { id: "gt90", label: ">90 days", buckets: ["b91_180", "b181_365", "b365p"], basisDependent: false },
  { id: "gt180", label: ">180 days", buckets: ["b181_365", "b365p"], basisDependent: false },
  ...BUCKET_DEFS.map((b) => ({ id: b.id as AgeFilter, label: b.label, buckets: [b.id], basisDependent: false })),
];
export const cohortOf = (id: AgeFilter): AgeCohort => COHORTS.find((c) => c.id === id) ?? COHORTS[0];
export const AGE_FILTER_IDS = COHORTS.map((c) => c.id);

export { CREDITORS_ORIGIN } from "@/lib/creditorNodes";

const ASOF = "2026-10-03";
const DAY = 86400000;
const isoDaysAgo = (d: number) => new Date(Date.UTC(2026, 9, 3) - d * DAY).toISOString().slice(0, 10);
const isoPlus = (iso: string, d: number) => new Date(Date.parse(iso + "T00:00:00Z") + d * DAY).toISOString().slice(0, 10);

/* ───────────── the book ───────────── */

interface VendorRec {
  id: string;
  name: string;
  code: string;
  terms: number;
  per: Record<BucketId, number>;
  openPer: Record<BucketId, number>;
  outstanding: number;
  opening: number;
  mv: number;
  advance: number;
  debit: number;
  items: VendorOpenItem[];
  oldestDays: number | null;
  oldestRef: string | null;
}

interface Others {
  count: number;
  per: Record<BucketId, number>;
  outstanding: number;
  mv: number;
}

interface Flow extends AgeingMovement {
  /** vendors listed first, highest contribution first, plus remainder (for the drawer) */
  src: BucketId | "new";
}

export interface Book {
  total: number;
  k: number;
  buckets: AgeingBucket[];
  vendors: VendorRec[];
  others: Others;
  migration: AgeingMigration;
  flows: Flow[];
  abnormal: { cat: AbnormalCategory; vendors: { id: string; amount: number | null }[] }[];
  totalMv: number;
}

const cache = new Map<string, Book>();

const emptyPer = (): Record<BucketId, number> => ({ b0_30: 0, b31_60: 0, b61_90: 0, b91_180: 0, b181_365: 0, b365p: 0 });

export function creditorBook(ctx: QueryCtx): Book {
  const key = `${ctx.scenario}|${ctx.period}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const { S, k } = params(ctx);
  const shape = S.creditorsShape;
  const pm = k / 0.16; // months in the period relative to a month

  /* 1. closing exposure by bucket (4dp, sums exactly to the creditor total) */
  const total = S.creditors;
  const over180 = S.creditors181;
  const young = total - over180;
  const raw = [
    ...shape.youngShares.map((s) => young * s),
    over180 * shape.over180Split,
    over180 * (1 - shape.over180Split),
  ].map(r4);
  raw[0] = r4(raw[0] + (total - sum(raw)));
  const E = raw;

  /* 2. cohort flows (₹ Cr) solved so that opening + flows = closing in every bucket, and total movement = pulse movement */
  const totalMv = r4(cashFlowsFor(S, k).creditors);
  let f = 1;
  let a: number[] = [];
  let s: number[] = [];
  let adj: number[] = [];
  let mv: number[] = [];
  let n0 = 0;
  for (let attempt = 0; attempt < 14; attempt++) {
    a = shape.monthlyAged.map((x) => r4(x * pm * f));
    s = shape.monthlySettled.map((x) => r4(x * pm * f));
    adj = shape.monthlyAdj.map((x) => r4(x * pm * f));
    mv = BUCKET_IDS.map((_, i) => (i === 0 ? 0 : r4((a[i - 1] ?? 0) - (a[i] ?? 0) - s[i] + adj[i])));
    mv[0] = r4(totalMv - sum(mv.slice(1)));
    n0 = r4(mv[0] + a[0] + s[0] - adj[0]);
    const openingOk = E.every((e, i) => e - mv[i] >= -1e-9);
    if (openingOk && n0 >= 0) break;
    f *= 0.8;
  }
  const O = E.map((e, i) => r4(e - mv[i]));

  /* 3. vendor counts / documents per bucket */
  const V = shape.vendorsTotal;
  const counts = [Math.round(V * 0.85), Math.round(V * 0.78), Math.round(V * 0.55), Math.round(V * 0.3), S.creditors181Vendors, Math.max(2, Math.round(S.creditors181Vendors * 0.4))];
  const docs = E.map((e, i) => Math.max(1, Math.round(e * shape.docsPerCr * (0.9 + (i % 3) * 0.05))));

  const buckets: AgeingBucket[] = BUCKET_DEFS.map((b, i) => ({
    id: b.id,
    label: b.label,
    fromDays: b.from,
    toDays: b.to,
    exposure: E[i],
    share: E[i] / total,
    vendorCount: counts[i],
    documentCount: docs[i],
    movement: mv[i],
  }));

  /* 4. vendors: listed named vendors + an "others" remainder */
  const R = rng(`book|${ctx.scenario}`);
  const order = VENDORS.map((_, i) => i)
    .map((i) => ({ i, o: R() }))
    .sort((x, y) => x.o - y.o)
    .map((x) => x.i);
  const weight = new Array(VENDORS.length).fill(0);
  order.forEach((vi, rank) => (weight[vi] = 1 / Math.pow(rank + 1, 1.05)));

  const vendors: VendorRec[] = VENDORS.map((name, i) => ({
    id: `V${10001 + i}`,
    name,
    code: `V${10001 + i}`,
    terms: [30, 45, 60, 90][hashStr(name) % 4],
    per: emptyPer(),
    openPer: emptyPer(),
    outstanding: 0,
    opening: 0,
    mv: 0,
    advance: 0,
    debit: 0,
    items: [],
    oldestDays: null,
    oldestRef: null,
  }));
  const others: Others = { count: 0, per: emptyPer(), outstanding: 0, mv: 0 };

  BUCKET_IDS.forEach((bid, bIdx) => {
    const rb = rng(`alloc|${ctx.scenario}|${bid}`);
    const n = counts[bIdx];
    const listedPresent = Math.min(n, VENDORS.length);
    const score = vendors.map((_, vi) => ({ vi, sc: weight[vi] * (0.35 + rb()) }));
    const present = score.sort((x, y) => y.sc - x.sc).slice(0, listedPresent);
    const othersN = Math.max(0, n - VENDORS.length);
    const othersAmt = othersN > 0 ? r4(E[bIdx] * Math.min(0.38, 0.5 * (othersN / n))) : 0;
    const w = present.map((p) => Math.pow(weight[p.vi], 1.15) * (0.55 + rb()));
    const parts = weightedSplit(r4(E[bIdx] - othersAmt), w);
    present.forEach((p, j) => (vendors[p.vi].per[bid] = parts[j]));
    others.per[bid] = othersAmt;
    others.count = Math.max(others.count, othersN);
  });

  vendors.forEach((v) => (v.outstanding = r4(sum(BUCKET_IDS.map((b) => v.per[b])))));
  others.outstanding = r4(sum(BUCKET_IDS.map((b) => others.per[b])));

  /* vendor movement and opening: proportional to the vendor's share of each bucket, so everything reconciles */
  const share = (amt: number, bIdx: number) => (E[bIdx] === 0 ? 0 : amt / E[bIdx]);
  vendors.forEach((v) => {
    BUCKET_IDS.forEach((bid, bIdx) => {
      const m = r4(mv[bIdx] * share(v.per[bid], bIdx));
      v.openPer[bid] = r4(v.per[bid] - m);
      v.mv = r4(v.mv + m);
    });
    v.opening = r4(sum(BUCKET_IDS.map((b) => v.openPer[b])));
  });
  others.mv = r4(totalMv - sum(vendors.map((v) => v.mv)));

  /* advances and debit balances stay separate fields, never derived from each other */
  const ra = rng(`adv|${ctx.scenario}`);
  const advWeights = vendors.map((v) => (ra() > 0.4 ? weight[vendors.indexOf(v)] * (0.5 + ra()) : 0));
  const advParts = weightedSplit(r4(S.advances * 0.8), advWeights.map((x) => x + 1e-9));
  vendors.forEach((v, i) => (v.advance = advWeights[i] > 0 ? advParts[i] : 0));
  const debitScale = shape.abnormalScale.debit_balance ?? 1;
  const rd = rng(`debit|${ctx.scenario}`);
  vendors.forEach((v) => {
    if (rd() > 0.78) v.debit = r4((0.04 + rd() * 0.28) * debitScale);
  });

  /* open items per vendor: exact split of each bucket amount, ages inside the bucket, both dates carried */
  vendors.forEach((v) => {
    const ri = rng(`items|${ctx.scenario}|${v.id}`);
    let seq = 0;
    BUCKET_DEFS.forEach((b) => {
      const amt = v.per[b.id];
      if (amt <= 0) return;
      const nDocs = amt < 0.05 ? 1 : Math.min(4, 1 + Math.floor(ri() * 4));
      const parts = weightedSplit(amt, Array.from({ length: nDocs }, () => 0.4 + ri()));
      parts.forEach((p) => {
        seq += 1;
        const hi = b.to ?? 520;
        const age = Math.round(b.from + ri() * (hi - b.from));
        const docDate = isoDaysAgo(age);
        v.items.push({
          documentRef: `PI-26-${String(10000 + (hashStr(v.id + seq) % 89999))}`,
          documentType: "Purchase invoice",
          documentDate: docDate,
          dueDate: isoPlus(docDate, v.terms),
          ageDays: { value: age },
          bucket: b.id,
          amount: p,
        });
      });
    });
    v.items.sort((x, y) => (y.ageDays.value ?? 0) - (x.ageDays.value ?? 0));
    v.oldestDays = v.items[0]?.ageDays.value ?? null;
    v.oldestRef = v.items[0]?.documentRef ?? null;
  });

  vendors.sort((x, y) => y.outstanding - x.outstanding);

  /* 5. migration: flows between buckets, settlements, new and adjusted */
  const flows: Flow[] = [];
  const vendorsFor = (bucket: BucketId | "new", moved: number, opening: number) => {
    const src = bucket === "new" ? "b0_30" : bucket;
    const n = counts[bi(src)];
    return Math.max(1, Math.round(n * Math.sqrt(Math.min(1, moved / (opening + 1e-9)))));
  };
  for (let i = 0; i < 5; i++) {
    const from = BUCKET_IDS[i];
    const to = BUCKET_IDS[i + 1];
    flows.push({
      id: `${from}>${to}`,
      fromBucket: from,
      toBucket: to,
      openingExposure: O[i],
      movedExposure: a[i],
      vendorCount: vendorsFor(from, a[i], O[i]),
      documentCount: Math.max(1, Math.round(a[i] * shape.docsPerCr)),
      movementType: "aged",
      intoRisk: i + 1 === 3,
      src: from,
    });
  }
  BUCKET_IDS.forEach((from, i) => {
    if (s[i] > 0) {
      flows.push({
        id: `${from}>settled`,
        fromBucket: from,
        toBucket: "settled",
        openingExposure: O[i],
        movedExposure: s[i],
        vendorCount: vendorsFor(from, s[i], O[i]),
        documentCount: Math.max(1, Math.round(s[i] * shape.docsPerCr)),
        movementType: "settled",
        intoRisk: false,
        src: from,
      });
    }
    if (Math.abs(adj[i]) > 0) {
      flows.push({
        id: `${from}>adjusted`,
        fromBucket: from,
        toBucket: "adjusted",
        openingExposure: O[i],
        movedExposure: adj[i],
        vendorCount: Math.max(1, Math.round(counts[i] * 0.1)),
        documentCount: Math.max(1, Math.round(Math.abs(adj[i]) * shape.docsPerCr * 4)),
        movementType: "adjusted",
        intoRisk: false,
        src: from,
      });
    }
  });
  flows.push({
    id: "new>b0_30",
    fromBucket: "new",
    toBucket: "b0_30",
    openingExposure: 0,
    movedExposure: n0,
    vendorCount: counts[0],
    documentCount: Math.max(1, Math.round(n0 * shape.docsPerCr)),
    movementType: "new",
    intoRisk: false,
    src: "new",
  });

  const rows: MigrationBucketRow[] = BUCKET_IDS.map((id, i) => ({
    id,
    opening: O[i],
    agedIn: i === 0 ? 0 : a[i - 1],
    agedOut: i < 5 ? a[i] : 0,
    newIn: i === 0 ? n0 : 0,
    settled: s[i],
    adjusted: adj[i],
    closing: E[i],
  }));
  const item = (label: string, ids: string[]) => {
    const fl = flows.filter((x) => ids.includes(x.id));
    return { label, amount: r4(sum(fl.map((x) => x.movedExposure))), vendorCount: Math.max(0, ...fl.map((x) => x.vendorCount)), flowIds: ids };
  };
  const migration: AgeingMigration = {
    ageingBasis: AGEING_BASIS,
    windowLabel: ctx.period === "sep26" ? "Sep 2026" : ctx.period === "q2fy27" ? "Q2 FY27 (Jul–Sep)" : "YTD FY27 (Apr – Oct, month to date)",
    opening: r4(sum(O)),
    closing: r4(sum(E)),
    buckets: rows,
    flows,
    summary: {
      enteringRisk: item("Entering >90 days", ["b61_90>b91_180"]),
      gettingOlder: item("Getting older (already >90)", ["b91_180>b181_365", "b181_365>b365p"]),
      cleared: item("Cleared (settled)", BUCKET_IDS.map((b) => `${b}>settled`).filter((id) => flows.some((x) => x.id === id))),
      newlyCreated: item("Newly created", ["new>b0_30"]),
      adjusted: item("Adjusted", BUCKET_IDS.map((b) => `${b}>adjusted`).filter((id) => flows.some((x) => x.id === id))),
    },
  };

  /* 6. abnormal categories: diagnostic labels only */
  const sc = shape.abnormalScale;
  const num = (v: number) => ({ value: v });
  const unavailable = { value: null, reason: "Awaiting finance mapping" };
  const cat = (
    id: string,
    label: string,
    description: string,
    vendorsN: number | null,
    docsN: number | null,
    amount: number | null,
    caveat?: string,
  ): AbnormalCategory => ({
    id,
    label,
    description,
    vendorCount: vendorsN === null ? unavailable : num(vendorsN),
    documentCount: docsN === null ? unavailable : num(docsN),
    amount: amount === null ? unavailable : num(r4(amount * (sc[id] ?? 1))),
    classification: "diagnostic",
    caveat,
  });
  const debitTotal = r4(sum(vendors.map((v) => v.debit)) + 0.18 * (sc.debit_balance ?? 1));
  const cats: AbnormalCategory[] = [
    {
      ...cat("debit_balance", "Debit balance in creditor account", "Vendor accounts carrying a debit balance. Not classified as vendor advance.", 0, 0, 0),
      vendorCount: num(vendors.filter((v) => v.debit > 0).length + 1),
      documentCount: num(14),
      amount: num(debitTotal),
      caveat: "Shown as found in the creditor ledger. Whether any of it is an advance needs a finance classification.",
    },
    cat("no_movement_90", "No movement >90 days", "Open balances with no posting in more than 90 days.", Math.round(counts[3] * 0.55), 41, 6.2),
    cat("no_movement_180", "No movement >180 days", "Open balances with no posting in more than 180 days.", Math.round(counts[4] * 0.75), 23, 2.9),
    cat("old_credit_notes", "Old credit notes not adjusted", "Credit notes older than 90 days not adjusted against an invoice.", 7, 19, 0.88),
    cat("opening_balance", "Opening balance anomalies", "Vendors whose opening balance differs from the prior-year closing.", 4, 4, null, "Amount awaiting finance mapping."),
    {
      ...cat("no_ageing_date", "Documents without a usable ageing date", "Documents with a missing or invalid date; excluded from ageing buckets.", 8, 38, null, "Amount awaiting finance mapping."),
    },
    cat("manual_adjustments", "Large manual adjustments", "Manual journal adjustments above the review threshold.", 5, 11, 1.12),
    cat("reversals", "Unusual balance reversals", "Balances that changed sign during the period.", 3, 6, 0.41),
    cat("unreconciled_items", "Unreconciled vendor items", "Vendor items not yet matched in reconciliation.", 12, 33, 2.7),
  ];
  const ab = rng(`abn|${ctx.scenario}`);
  const abnormal = cats.map((c) => {
    const n = Math.min(c.vendorCount.value ?? 0, vendors.length);
    const pick = vendors
      .map((v) => ({ v, o: ab() }))
      .sort((x, y) => y.o * (1 / (1 + y.v.outstanding)) - x.o * (1 / (1 + x.v.outstanding)))
      .slice(0, n)
      .map((x) => x.v);
    if (c.id === "debit_balance") {
      return { cat: c, vendors: vendors.filter((v) => v.debit > 0).map((v) => ({ id: v.id, amount: v.debit as number | null })) };
    }
    const amt = c.amount.value;
    if (amt === null || pick.length === 0) return { cat: c, vendors: pick.map((v) => ({ id: v.id, amount: null as number | null })) };
    const parts = weightedSplit(amt, pick.map((v) => v.outstanding + 0.05));
    return { cat: c, vendors: pick.map((v, i) => ({ id: v.id, amount: parts[i] as number | null })) };
  });

  const book: Book = { total, k, buckets, vendors, others, migration, flows, abnormal, totalMv };
  cache.set(key, book);
  return book;
}

/* ───────────── overview ───────────── */

const sumBuckets = (b: AgeingBucket[], ids: BucketId[]) => r4(sum(b.filter((x) => ids.includes(x.id)).map((x) => x.exposure)));
const sumMovement = (b: AgeingBucket[], ids: BucketId[]) => r4(sum(b.filter((x) => ids.includes(x.id)).map((x) => x.movement)));

export function buildCreditorsOverview(ctx: QueryCtx): CreditorsOverview {
  const bk = creditorBook(ctx);
  const head = (id: AgeFilter, label?: string): ExposureMetric => {
    const c = cohortOf(id);
    return {
      id,
      label: label ?? c.label,
      value: { value: sumBuckets(bk.buckets, c.buckets) },
      movement: { value: sumMovement(bk.buckets, c.buckets) },
      basisDependent: c.basisDependent,
    };
  };
  return {
    asOf: ASOF,
    ageingBasis: AGEING_BASIS,
    scope: "Dated documents",
    totalCreditors: { value: r4(sum(bk.buckets.map((b) => b.exposure))) },
    headline: [head("all", "Total creditors"), head("current"), head("overdue"), head("gt90"), head("gt180"), head("b365p", ">365 days")],
    cohorts: COHORTS,
    buckets: bk.buckets,
    undated: { value: null, reason: "Awaiting finance mapping" },
    undatedDocuments: { value: 38 },
    vendorsTotal: bk.vendors.filter((v) => v.outstanding > 0).length + bk.others.count,
    documentsTotal: sum(bk.buckets.map((b) => b.documentCount)),
  };
}

export function buildMigration(ctx: QueryCtx): AgeingMigration {
  return creditorBook(ctx).migration;
}

export function buildAbnormal(ctx: QueryCtx): AbnormalControl {
  return {
    categories: creditorBook(ctx).abnormal.map((a) => a.cat),
    note: "Diagnostic categories only. No accounting classification has been applied; a debit balance in a creditor account is not treated as a vendor advance.",
  };
}

/* ───────────── concentration ───────────── */

function cohortExposureOf(per: Record<BucketId, number>, f: AgeFilter): number {
  return r4(sum(cohortOf(f).buckets.map((b) => per[b])));
}

export function buildConcentration(ctx: QueryCtx, filter: AgeFilter): VendorConcentration {
  const bk = creditorBook(ctx);
  const cohort = cohortOf(filter);
  const scope = sumBuckets(bk.buckets, cohort.buckets);
  const rows: VendorExposureRow[] = bk.vendors
    .map((v) => ({
      vendorId: v.id,
      name: v.name,
      rank: 0,
      outstanding: v.outstanding,
      cohortExposure: cohortExposureOf(v.per, filter),
      over90: cohortExposureOf(v.per, "gt90"),
      over180: cohortExposureOf(v.per, "gt180"),
      shareOfBook: v.outstanding / bk.total,
      oldestItemDays: v.oldestDays === null ? { value: null, reason: "No usable ageing date" } : { value: v.oldestDays },
      mtdMovement: v.mv,
      byBucket: { ...v.per },
    }))
    .filter((r) => r.cohortExposure > 0)
    .sort((x, y) => y.cohortExposure - x.cohortExposure)
    .map((r, i) => ({ ...r, rank: i + 1 }));
  const byBook = [...bk.vendors].sort((x, y) => y.outstanding - x.outstanding);
  const share = (n: number) => sum(byBook.slice(0, n).map((v) => v.outstanding)) / bk.total;
  return {
    filter,
    filterLabel: cohort.label,
    scopeExposure: scope,
    vendors: rows,
    others: {
      count: bk.others.count,
      outstanding: bk.others.outstanding,
      cohortExposure: cohortExposureOf(bk.others.per, filter),
    },
    indicators: {
      top1Share: share(1),
      top5Share: share(5),
      top10Share: share(10),
      largest: { vendorId: byBook[0].id, name: byBook[0].name, outstanding: byBook[0].outstanding },
      vendorCount: bk.vendors.filter((v) => v.outstanding > 0).length + bk.others.count,
    },
  };
}

/* ───────────── vendor profile ───────────── */

const MONTHS = ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"];

export function findVendor(ctx: QueryCtx, vendorId: string): VendorRec | undefined {
  return creditorBook(ctx).vendors.find((v) => v.id === vendorId);
}

interface Lifecycle {
  opening: number;
  invoiced: number;
  adjustments: number;
  payments: number;
  invoiceCount: number;
  paymentCount: number;
  cnCount: number;
}

/** Postings per kind, shared by the lifecycle, the vendor ledger and the payment history so they always agree. */
function postingCounts(v: VendorRec, payments: number) {
  const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));
  return {
    inv: clamp(Math.round(v.items.length * 1.3), 6, 26),
    pay: clamp(Math.round(payments / Math.max(0.5, v.outstanding * 0.25)), 3, 10),
    cn: 2,
  };
}

export function lifecycleOf(ctx: QueryCtx, v: VendorRec): Lifecycle {
  const pm = params(ctx).k / 0.16;
  const invoiced = r4(Math.max(v.outstanding * 0.5 * pm, Math.abs(v.mv) * 2 + 0.02));
  const adjustments = r4(invoiced * 0.04);
  // opening + invoiced - adjustments - payments = outstanding  (identity the tests check)
  const payments = r4(v.opening + invoiced - adjustments - v.outstanding);
  const n = postingCounts(v, payments);
  return { opening: v.opening, invoiced, adjustments, payments, invoiceCount: n.inv, paymentCount: n.pay, cnCount: n.cn };
}

interface Posting {
  date: string;
  kind: "PI" | "PV" | "DN";
  /** integer rupees */
  rs: number;
  voucherId: string;
}

/** The vendor's postings for the period: the single source for ledger rows, payment history and last payment. */
function ledgerPlan(ctx: QueryCtx, v: VendorRec): { postings: Posting[]; openingRs: number } {
  const lc = lifecycleOf(ctx, v);
  const r = rng(`cledger|${ctx.scenario}|${ctx.period}|${v.id}`);
  const toRs = (cr: number) => Math.round(cr * 1e7);
  const raws: Omit<Posting, "voucherId">[] = [];
  const spread = (total: number, n: number, kind: Posting["kind"]) => {
    if (total <= 0) return;
    const parts = weightedSplit(toRs(total), Array.from({ length: n }, () => 0.4 + r()));
    parts.forEach((p) => raws.push({ date: isoDaysAgo(Math.floor(r() * 150) + 3), kind, rs: Math.round(p) }));
  };
  spread(lc.invoiced, lc.invoiceCount, "PI");
  spread(lc.payments, lc.paymentCount, "PV");
  spread(lc.adjustments, lc.cnCount, "DN");
  const rsInv = sum(raws.filter((x) => x.kind === "PI").map((x) => x.rs));
  const rsOut = sum(raws.filter((x) => x.kind !== "PI").map((x) => x.rs));
  const openingRs = toRs(v.outstanding) - (rsInv - rsOut);
  raws.sort((x, y) => (x.date < y.date ? -1 : x.date > y.date ? 1 : 0));
  const postings = raws.map((x, i) => ({ ...x, voucherId: `${x.kind}-26-${String(10000 + (hashStr(v.id + i + x.kind) % 89999)).padStart(6, "0")}` }));
  return { postings, openingRs };
}

export function buildVendorProfile(ctx: QueryCtx, vendorId: string): VendorProfile | null {
  const bk = creditorBook(ctx);
  const v = bk.vendors.find((x) => x.id === vendorId);
  if (!v) return null;
  const lc = lifecycleOf(ctx, v);
  const r = rng(`profile|${ctx.scenario}|${v.id}`);
  const overdue = r4(sum(cohortOf("overdue").buckets.map((b) => v.per[b])));
  const over90 = r4(sum(cohortOf("gt90").buckets.map((b) => v.per[b])));

  /* trend: 12 months ending at the current balance */
  const walk: number[] = [];
  let x = 1;
  for (let i = 0; i < 12; i++) {
    x *= 0.93 + r() * 0.16;
    walk.push(x);
  }
  const scale = v.outstanding / walk[11];
  const trend = walk.map((w, i) => ({ label: MONTHS[i], outstanding: i === 11 ? v.outstanding : r4(w * scale) }));

  /* payments: the most recent postings from the same plan the ledger uses */
  const plan = ledgerPlan(ctx, v);
  const pay = plan.postings.filter((x) => x.kind === "PV").sort((x, y) => (x.date < y.date ? 1 : -1));
  const recent = pay.slice(0, 4).map((x) => ({ date: x.date, amount: r4(x.rs / 1e7), daysElapsed: v.terms + Math.round((r() - 0.3) * 40) }));
  const abn = bk.abnormal.flatMap((a) => {
    const hit = a.vendors.find((x) => x.id === v.id);
    return hit ? [{ categoryId: a.cat.id, label: a.cat.label, amount: hit.amount === null ? ({ value: null, reason: "Awaiting finance mapping" } as const) : { value: hit.amount }, documentRef: v.items[0]?.documentRef ?? null }] : [];
  });

  return {
    vendorId: v.id,
    name: v.name,
    code: v.code,
    paymentTerms: `${v.terms} days`,
    ageingBasis: AGEING_BASIS,
    strip: {
      outstanding: { value: v.outstanding },
      overdue: { value: overdue },
      over90: { value: over90 },
      advance: { value: v.advance },
      oldestItem: v.oldestDays === null ? { value: null, reason: "No usable ageing date" } : { value: v.oldestDays },
      oldestItemRef: v.oldestRef,
      lastPayment: { date: recent[0]?.date ?? null, amount: recent[0] ? { value: recent[0].amount } : { value: null, reason: "No payment in period" } },
    },
    lifecycle: [
      { id: "opening", label: "Opening balance", amount: lc.opening, documentCount: 0, direction: "start" },
      { id: "liability", label: "Purchase / liability creation (invoiced)", amount: lc.invoiced, documentCount: lc.invoiceCount, direction: "increase" },
      { id: "adjustment", label: "Credit notes / adjustments", amount: lc.adjustments, documentCount: lc.cnCount, direction: "decrease" },
      { id: "payment", label: "Payments", amount: lc.payments, documentCount: lc.paymentCount, direction: "decrease" },
      { id: "open", label: "Open balance", amount: v.outstanding, documentCount: v.items.length, direction: "result" },
    ] satisfies LifecycleStage[],
    trend,
    migration: BUCKET_DEFS.map((b) => ({ bucket: b.id, label: b.label, opening: v.openPer[b.id], closing: v.per[b.id] })),
    paymentBehaviour: {
      paymentsPerMonth: { value: Math.round((lc.paymentCount / Math.max(1, params(ctx).k / 0.16)) * 10) / 10 },
      avgDaysToPay: { value: Math.round(recent.reduce((a, p) => a + p.daysElapsed, 0) / Math.max(1, recent.length)) },
      recent,
    },
    advancePosition: {
      amount: { value: v.advance },
      source: "Vendor advance ledger (separate account)",
      note: "Advances are shown separately from the creditor balance.",
    },
    debitBalance: {
      amount: { value: v.debit },
      note: "A debit balance in the creditor account. Not classified as a vendor advance unless finance classifies it.",
    },
    abnormal: abn,
    openItems: v.items,
    openBalance: v.outstanding,
  };
}

/* ───────────── drawer drill for flows and abnormal categories ───────────── */

const money = (n: number) => {
  const a = Math.abs(n);
  return a >= 0.1 ? `₹${a.toFixed(2)} Cr` : `₹${(a * 100).toFixed(1)} L`;
};

function contributors(bk: Book, bucket: BucketId | "new", moved: number, vendorCountWanted: number) {
  const src = bucket === "new" ? "b0_30" : bucket;
  const cands = bk.vendors.filter((v) => v.per[src] > 0).sort((x, y) => y.per[src] - x.per[src]);
  const take = cands.slice(0, Math.min(vendorCountWanted, cands.length));
  const othersN = Math.max(0, vendorCountWanted - take.length);
  const othersAmt = othersN > 0 ? r4(moved * Math.min(0.4, 0.5 * (othersN / vendorCountWanted))) : 0;
  const parts = weightedSplit(r4(moved - othersAmt), take.map((v) => v.per[src]));
  return { take, parts, othersN, othersAmt };
}

function vendorRow(v: VendorRec, amount: number | null, share: number, reason?: string): DrillRow {
  return {
    node: { level: "entity", dim: "Vendor", id: `Vendor:${v.id}`, label: v.name, amount: v.outstanding, variance: null },
    amount: amount ?? 0,
    share,
    delta: amount ?? 0,
    tone: "neutral",
    sublabel: v.code,
    unavailable: amount === null ? reason ?? "Awaiting finance mapping" : undefined,
  };
}

export function buildCreditorDrill(ctx: QueryCtx, origin: DrillOrigin, nodes: DrillNode[]): DrillView {
  const bk = creditorBook(ctx);
  const filter = nodes[0];
  const empty: DrillView = {
    title: origin.label,
    levelLabel: "Creditors",
    amount: null,
    variance: null,
    variancePct: null,
    comparisonLabel: "vs period opening",
    tone: "neutral",
    explanation: "Select a migration flow or abnormal category to see the vendors behind it.",
    concentration: { headline: "", topShares: [] },
    splits: [],
    supportingDrivers: [],
    terminal: false,
    entityKind: "other",
    facts: [],
  };
  if (!filter) return empty;

  if (filter.dim === "Migration") {
    const fl = bk.flows.find((x) => x.id === filter.id.slice("Migration:".length));
    if (!fl) return empty;
    const { take, parts, othersN, othersAmt } = contributors(bk, fl.fromBucket, fl.movedExposure, fl.vendorCount);
    const rows = take.map((v, i) => vendorRow(v, parts[i], fl.movedExposure === 0 ? 0 : Math.abs(parts[i] / fl.movedExposure)));
    const top2 = sum(rows.slice(0, 2).map((r) => r.share));
    const to = fl.toBucket === "settled" || fl.toBucket === "adjusted" ? fl.toBucket : bucketLabel(fl.toBucket);
    const from = fl.fromBucket === "new" ? "New invoices" : bucketLabel(fl.fromBucket);
    return {
      title: filter.label,
      levelLabel: `Migration · ${fl.movementType}`,
      amount: fl.movedExposure,
      variance: null,
      variancePct: null,
      comparisonLabel: "over the selected period",
      tone: fl.intoRisk ? "bad" : fl.movementType === "settled" ? "good" : "neutral",
      explanation: `${money(fl.movedExposure)} moved ${from} → ${to} across ${fl.vendorCount} vendors and ${fl.documentCount} documents. Placement uses the provisional ageing basis; the basis is awaiting finance validation.`,
      concentration: { headline: `${Math.round(top2 * 100)}% from top 2 vendors`, topShares: rows.slice(0, 5).map((r) => r.share) },
      splits: [
        {
          dim: "Vendor",
          rows,
          other: othersN > 0 ? { count: othersN, amount: othersAmt, delta: othersAmt } : undefined,
        },
      ],
      supportingDrivers: [],
      terminal: false,
      entityKind: "other",
      facts: [],
    };
  }

  if (filter.dim === "Abnormal") {
    const entry = bk.abnormal.find((a) => a.cat.id === filter.id.slice("Abnormal:".length));
    if (!entry) return empty;
    const c = entry.cat;
    const rows = entry.vendors
      .map((x) => ({ x, v: bk.vendors.find((vv) => vv.id === x.id)! }))
      .filter((y) => y.v)
      .sort((p, q) => (q.x.amount ?? -1) - (p.x.amount ?? -1))
      .map(({ x, v }) => vendorRow(v, x.amount, c.amount.value ? Math.abs((x.amount ?? 0) / c.amount.value) : 0, c.amount.reason));
    const listed = sum(entry.vendors.map((x) => x.amount ?? 0));
    const remaining = c.amount.value === null ? 0 : r4(c.amount.value - listed);
    const nTotal = c.vendorCount.value ?? 0;
    return {
      title: c.label,
      levelLabel: "Abnormal · diagnostic",
      amount: c.amount.value,
      variance: null,
      variancePct: null,
      comparisonLabel: "diagnostic category",
      tone: "warn",
      explanation: `${c.description} This is a diagnostic label only; no accounting classification has been applied.${c.caveat ? " " + c.caveat : ""}`,
      concentration: { headline: c.amount.value === null ? "Amount unavailable: awaiting finance mapping" : `${nTotal} vendors flagged`, topShares: rows.slice(0, 5).map((r) => r.share) },
      splits: [
        {
          dim: "Vendor",
          rows,
          other: remaining > 0.0001 && nTotal > rows.length ? { count: nTotal - rows.length, amount: remaining, delta: remaining } : undefined,
        },
      ],
      supportingDrivers: [],
      terminal: false,
      entityKind: "other",
      facts: [],
    };
  }
  return empty;
}

/** Vendors behind a flow / abnormal category, exposed for tests and the deep-link resolver. */
export function flowContributors(ctx: QueryCtx, flowId: string) {
  const bk = creditorBook(ctx);
  const fl = bk.flows.find((x) => x.id === flowId);
  if (!fl) return null;
  const c = contributors(bk, fl.fromBucket, fl.movedExposure, fl.vendorCount);
  return { flow: fl, vendors: c.take.map((v, i) => ({ id: v.id, amount: c.parts[i] })), othersAmt: c.othersAmt };
}

/* ───────────── ledger / voucher for a vendor ───────────── */

export function buildCreditorLedger(ctx: QueryCtx, nodes: DrillNode[]): LedgerView | null {
  const vnode = nodes.find((n) => n.dim === "Vendor");
  if (!vnode) return null;
  const v = findVendor(ctx, vnode.id.slice("Vendor:".length));
  if (!v) return null;
  const { postings, openingRs } = ledgerPlan(ctx, v);
  const r = rng(`crecon|${ctx.scenario}|${ctx.period}|${v.id}`);
  let bal = openingRs; // credit-positive: amount owed to the vendor
  const entries: LedgerEntry[] = postings.map((x, i) => {
    const credit = x.kind === "PI" ? x.rs : 0;
    const debit = x.kind === "PI" ? 0 : x.rs;
    bal += credit - debit;
    const recon: LedgerEntry["recon"] = r() > 0.88 ? "exception" : r() > 0.55 ? "pending" : "matched";
    return {
      id: `E${i + 1}`,
      date: x.date,
      voucherId: x.voucherId,
      voucherType: x.kind === "PI" ? "Purchase Invoice" : x.kind === "PV" ? "Payment Voucher" : "Debit Note",
      account: "2100",
      accountName: "Trade Creditors",
      narration: `${v.name} — ${x.kind === "PI" ? "Invoice posted" : x.kind === "PV" ? "Payment made" : "Credit note / adjustment"}`,
      debit,
      credit,
      balance: bal,
      source: x.kind === "PV" ? "Ginesys Payments" : "Ginesys AP",
      recon,
    };
  });
  return {
    title: `GL 2100 · Trade Creditors · ${v.name}`,
    subtitle: ["Creditors", ...nodes.filter((n) => n.level === "driver" || n.level === "entity").map((n) => n.label)].join(" › "),
    openingBalance: openingRs,
    closingBalance: bal,
    entries,
    balanceNote: "Credit-positive: the balance is the amount owed to the vendor.",
  };
}
