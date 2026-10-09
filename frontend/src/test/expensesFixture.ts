import { vi } from "vitest";
import type { ExpException, ExpExceptions, ExpHeadRow, ExpLedgerRow, ExpLedgers, ExpScope, ExpSite, ExpSites, ExpSummary, ExpTrend, ExpTriple } from "@/types/expensesLive";

/**
 * SYNTHETIC sample of the Store / DC Expense API (/api/v1/mgmt/expenses), INR Cr, expenses positive.
 * Aug-26 store heads follow the finance MIS store lines (Rent 6.90, Employee 9.42, Power 5.24, Advertisement 1.29, Freight 1.99, Other 1.06). Nothing here is real data.
 */
const MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"];
const tri = (book: number, adjustment = 0): ExpTriple => ({ book, adjustment, total: Math.round((book + adjustment) * 1e4) / 1e4 });

const head = (key: string, label: string, t: ExpTriple, ns: number | null, grand: number, sites: number | null, ly: number, prev: number): ExpHeadRow => ({
  key, label, ...t,
  pct_ns: ns ? { book: (t.book / ns) * 100, adjustment: (t.adjustment / ns) * 100, total: (t.total / ns) * 100 } : null,
  share_pct: (t.total / grand) * 100,
  per_site_avg: sites ? t.total / sites : null,
  mom: { last_month: "2026-08", prev_month: "2026-07", last: t.total, prev, delta: t.total - prev, delta_pct: ((t.total - prev) / prev) * 100 },
  ly: { total: ly, book: ly, delta: t.total - ly, delta_pct: ((t.total - ly) / ly) * 100, delta_pct_book: ((t.book - ly) / ly) * 100, pct_ns: ns ? (ly / 100) * 100 : null, pct_ns_delta_pp: ns ? -1.2 : null },
});

const STORE_HEADS: [string, string, ExpTriple, number, number][] = [
  ["rent", "Rent", tri(6.8983), 6.9491, 5.1],
  ["employee_cost", "Employee Cost", tri(9.169, 0.25), 8.9, 7.3],
  ["power_fuel", "Power and Fuel", tri(5.2443), 4.6, 4.2],
  ["advertisement", "Advertisement", tri(0.833, 0.4577), 0.62, 0.9],
  ["freight", "Freight Forwarding", tri(1.9934), 1.8, 1.7],
  ["other_expenses", "Other expenses", tri(1.0618), 0.99, 0.9],
];
const DC_HEADS: Record<"consolidated" | "holdco" | "subco", [string, string, ExpTriple, number, number][]> = {
  consolidated: [["rent", "Rent", tri(0.3854), 0.38, 0.3], ["employee_cost", "Employee Cost", tri(1.0203), 0.9, 0.8], ["power_fuel", "Power and Fuel", tri(0.0281), 0.03, 0.02], ["advertisement", "Advertisement", tri(0.0708, -0.0708), 0.07, 0.05], ["freight", "Freight Forwarding", tri(0.0013), 0.001, 0.001], ["other_expenses", "Other expenses", tri(0.785), 0.7, 0.6]],
  holdco: [["rent", "Rent", tri(0.3854), 0.38, 0.3], ["employee_cost", "Employee Cost", tri(0.9546), 0.9, 0.8], ["power_fuel", "Power and Fuel", tri(0.021), 0.03, 0.02], ["advertisement", "Advertisement", tri(0), 0, 0.01], ["freight", "Freight Forwarding", tri(0), 0, 0.01], ["other_expenses", "Other expenses", tri(0.0159), 0.02, 0.01]],
  subco: [["rent", "Rent", tri(0), 0, 0.01], ["employee_cost", "Employee Cost", tri(0.0657), 0.06, 0.05], ["power_fuel", "Power and Fuel", tri(0.0072), 0.01, 0.01], ["advertisement", "Advertisement", tri(0.0708, -0.0708), 0.07, 0.05], ["freight", "Freight Forwarding", tri(0.0013), 0.001, 0.001], ["other_expenses", "Other expenses", tri(0.7691), 0.7, 0.6]],
};

const base = (scope: ExpScope, entity: "consolidated" | "subco" | "holdco", from = "2026-04", to = "2026-08") => ({
  run_id: "MGMT-20261009", as_of_date: "2026-10-09", entity, scope, scope_label: scope === "store" ? "Store expenses" : "DC cost", from_month: from, to_month: to,
  months: MONTHS.filter((m) => m >= from && m <= to),
});

const controls = (ok = true) => ({
  tolerance_cr: 0.005, basis: "Store + DC + HO expense against the management P&L",
  rows: (["book", "adjustment", "total"] as const).map((layer) => ({ layer, store: 115.26, dc: 4.46, ho: 22.66, sum_of_scopes: 142.39, mgmt_pnl: 142.39, variance: ok ? 0.0002 : 0.2, ok })),
  ok,
});

export function buildSummary(scope: ExpScope, entity: "consolidated" | "subco" | "holdco", from?: string, to?: string): ExpSummary {
  const rows = scope === "store" ? STORE_HEADS : DC_HEADS[entity];
  const ns = scope === "store" ? 127.3152 : null;
  const sites = scope === "store" ? null : entity === "holdco" ? 4 : 8;
  const tot = rows.reduce((t, r) => ({ book: t.book + r[2].book, adj: t.adj + r[2].adjustment }), { book: 0, adj: 0 });
  const grand = tot.book + tot.adj;
  const heads = rows.map(([k, l, t, prev, ly]) => head(k, l, t, ns, grand, sites, ly, prev));
  const totalRow = head("total", scope === "store" ? "Store expenses" : "DC cost", tri(tot.book, tot.adj), ns, grand, sites, rows.reduce((s, r) => s + r[4], 0), rows.reduce((s, r) => s + r[3], 0));
  return {
    ...base(scope, entity, from, to), entity_label: entity === "holdco" ? "HoldCo (Citykart Ventures)" : entity === "subco" ? "SubCo (Citykart Stores)" : "Consolidated",
    net_sales: ns, site_count: sites, heads, total: totalRow, ly_available: true, ly_from_month: "2025-04", ly_to_month: "2025-08", adjustment_months: ["2026-08"], controls: controls(),
    notes: scope === "store" ? ["Store expenses are Citykart Stores (SubCo) only; HoldCo has no stores.", "Management adjustments in the period: 2026-08."] : ["Management adjustments in the period: 2026-08."], warnings: [],
  };
}

export function buildTrend(scope: ExpScope, entity: "consolidated" | "subco" | "holdco", from = "2026-04", to = "2026-08"): ExpTrend {
  const months = MONTHS.filter((m) => m >= from && m <= to);
  const rows = scope === "store" ? STORE_HEADS : DC_HEADS[entity];
  return {
    ...base(scope, entity, from, to), months,
    series: rows.map(([k, l, t]) => ({ key: k, label: l, values: Object.fromEntries(months.map((m, i) => [m, tri(t.book * (0.9 + i * 0.025), t.adjustment)])) })),
    total: Object.fromEntries(months.map((m, i) => [m, tri(20 + i, 0.2)])),
    net_sales: scope === "store" ? Object.fromEntries(months.map((m) => [m, 120])) : null, pct_ns: scope === "store" ? Object.fromEntries(months.map((m) => [m, 17.5])) : null,
    ly_total: Object.fromEntries(months.map((m) => [m, m === "2026-04" ? null : 18])), note: "Months before 2026-04 are books only: the management adjustment layer starts in 2026-04.",
  };
}

const site = (o: Partial<ExpSite> & Pick<ExpSite, "key" | "entity" | "site_code" | "total">): ExpSite => ({
  entity_label: o.entity === "HOLDCO" ? "HoldCo (Citykart Ventures)" : "SubCo (Citykart Stores)", voucher_entity: o.entity === "HOLDCO" ? "VENTURES" : "RETAIL", short_name: null, name: null, site_kind: "STORE",
  store_type: "OLD STORE", state: null, city: null, opening_date: "2019-05-01", nso_ty: false, area_sqft: 8000, net_sales: 5.6, months_with_sales: 5, book: o.total, adjustment: 0,
  heads: { rent: tri(o.total * 0.3), employee_cost: tri(o.total * 0.4), power_fuel: tri(o.total * 0.2), advertisement: tri(0), freight: tri(o.total * 0.05), other_expenses: tri(o.total * 0.05) },
  pct_ns: (o.total / 5.6) * 100, pct_ns_heads: { rent: ((o.total * 0.3) / 5.6) * 100, employee_cost: ((o.total * 0.4) / 5.6) * 100, power_fuel: ((o.total * 0.2) / 5.6) * 100, advertisement: 0, freight: 1, other_expenses: 1 },
  per_sqft_month: 150, share_pct: 1, vs_peer_pp: 0.5, vs_peer_ratio: 1.03, rank: 10, mom_pct: 4, last_month: 0.2, prev_month: 0.19, flags: [], ...o,
});

export function buildSites(scope: ExpScope, entity: "consolidated" | "subco" | "holdco"): ExpSites {
  const sites: ExpSite[] =
    scope === "store"
      ? [
          site({ key: "SUBCO:5", entity: "SUBCO", site_code: 5, short_name: "ALC", name: "ALC Store", total: 1.266, pct_ns: 22.6, rank: 3, flags: [{ code: "above_peer", text: "Expense is 22.6% of net sales against a peer median of 19.0%" }], vs_peer_pp: 3.6 }),
          site({ key: "SUBCO:3", entity: "SUBCO", site_code: 3, short_name: "LAD", name: "LAD Store", total: 1.141, pct_ns: 20.5, rank: 9, store_type: "NEW STORE" }),
          site({ key: "SUBCO:401", entity: "SUBCO", site_code: 401, short_name: "NEW", name: "New Store", total: 0.5, pct_ns: 30, rank: 1, nso_ty: true, opening_date: "2026-06-10", area_sqft: null, per_sqft_month: null, flags: [{ code: "nso_ty", text: "NSO TY: opened this financial year" }, { code: "mom_jump", text: "Latest month is 80.0% above the month before" }], mom_pct: 80 }),
        ]
      : [
          site({ key: "HOLDCO:3", entity: "HOLDCO", site_code: 3, short_name: "CKVPL-WH-KHETAWAS", name: "CITYKART VENTURES PVT. LTD. (CKVPL-WH-KHETAWAS)", total: 3.7341, net_sales: null, pct_ns: null, pct_ns_heads: {}, area_sqft: null, per_sqft_month: null, rank: 1, vs_peer_pp: null, site_kind: "WAREHOUSE", store_type: null }),
          site({ key: "SUBCO:123", entity: "SUBCO", site_code: 123, short_name: "CKSPL-WH-KHETAWAS", name: "CKSPL-WH-KHETAWAS", total: 0.2, net_sales: null, pct_ns: null, pct_ns_heads: {}, rank: 2, vs_peer_pp: null, site_kind: "WAREHOUSE", store_type: null }),
        ].filter((s) => entity === "consolidated" || (entity === "holdco" ? s.entity === "HOLDCO" : s.entity === "SUBCO"));
  const sum = sites.reduce((t, s) => t + s.total, 0);
  return {
    ...base(scope, entity), head: null, head_label: null, net_sales: scope === "store" ? 127.3 : null, sites,
    peer: { n: 3, basis: scope === "store" ? "pct_of_net_sales" : "total_cr", head: null, median_pct: scope === "store" ? 19.02 : undefined, p90_pct: scope === "store" ? 27.68 : undefined, median_cr: scope === "store" ? undefined : 0.34,
      heads: { rent: { median_pct: 5.43, p90_pct: 10.02 } }, method: "Median and 90th percentile (linear interpolation) of expense as % of net sales across the peer stores.", ranked_stores: 3 },
    parent: { total: sum }, children_sum: { total: sum }, unallocated: { total: 0, note: "Management adjustments that are not attributable to one site." }, reconciles: true,
    area_note: "Per sq ft is INR per sq ft per month on the area in the store master; not computed where the master has no area or the site is Citykart Ventures.",
    flag_legend: {},
  };
}

const lrow = (o: Partial<ExpLedgerRow> & Pick<ExpLedgerRow, "kind" | "ledger_code" | "ledger_name" | "head" | "amount_cr">): ExpLedgerRow => ({ lines: 10, share_pct: 50, months_active: 5, site_code: null, voucher_entity: "RETAIL", ...o });

export function buildLedgers(p: Record<string, string | undefined>): ExpLedgers {
  const entity = (p.entity as "subco" | "holdco" | undefined) ?? "consolidated";
  const scope = (p.scope as ExpScope) ?? "store";
  const head = p.head ?? null;
  const hold = entity === "holdco" || p.site_entity === "holdco";
  const voucher_entity = hold ? "VENTURES" : "RETAIL";
  const common = { ...base(scope, entity), head, head_label: head === "rent" ? "Rent" : head, voucher_note: "Each ledger row opens the voucher list for the ledger at the site.", truncated: false };
  if (p.glcode) {
    const rows = [
      lrow({ kind: "site", ledger_code: Number(p.glcode), ledger_name: "Rent", head: head ?? "rent", amount_cr: 0.115, site_code: 5, site_entity: hold ? "HOLDCO" : "SUBCO", site_name: "ALC", voucher_entity, lines: 4 }),
      lrow({ kind: "site", ledger_code: Number(p.glcode), ledger_name: "Rent", head: head ?? "rent", amount_cr: 0.0942, site_code: 3, site_entity: hold ? "HOLDCO" : "SUBCO", site_name: "LAD", voucher_entity, lines: 7 }),
    ];
    return { ...common, site: null, site_entity: null, glcode: Number(p.glcode), grain: "site", rows, row_count: 2, adjustments: [], allocated_adjustment: null, parent: { total: 0.2092, book: null }, children_sum: { total: 0.2092 }, reconciles: true };
  }
  if (p.site) {
    const rows = [
      lrow({ kind: "ledger", ledger_code: 1000000002, ledger_name: "Rent", head: "rent", head_label: "Rent", amount_cr: 0.115, site_code: Number(p.site), voucher_entity, site_entity: hold ? "HOLDCO" : "SUBCO" }),
      lrow({ kind: "ledger", ledger_code: 1000000052, ledger_name: "Electricity Exps.", head: "power_fuel", head_label: "Power and Fuel", amount_cr: 0.05, site_code: Number(p.site), voucher_entity, site_entity: hold ? "HOLDCO" : "SUBCO" }),
    ];
    return { ...common, site: Number(p.site), site_entity: hold ? "HOLDCO" : "SUBCO", glcode: null, grain: "ledger", rows, row_count: 2, adjustments: [], allocated_adjustment: { amount_cr: 0.0287, note: "Management adjustments allocated to this site pro rata to its share of store net sales." },
      parent: { total: 0.1937, book: null }, children_sum: { total: 0.1937 }, reconciles: true };
  }
  const rows = [
    lrow({ kind: "ledger", ledger_code: 1000000002, ledger_name: "Rent", head: head ?? "rent", head_label: "Rent", amount_cr: 6.8983, sites: 188, pct_ns: 5.4, voucher_entity, share_pct: 100, lines: 432 }),
  ];
  return { ...common, site: null, site_entity: null, glcode: null, grain: "ledger", rows, row_count: 1, adjustments: [], allocated_adjustment: null, parent: { total: 6.8983, book: 6.8983 }, children_sum: { total: 6.8983 }, reconciles: true };
}

export function buildExceptions(scope: ExpScope, entity: "consolidated" | "subco" | "holdco"): ExpExceptions {
  const ex: ExpException[] = [
    { rule_id: "SITE_ABOVE_PEER", severity: "high", entity: "SUBCO", voucher_entity: "RETAIL", site_code: 264, site_name: "SNP", head: "power_fuel", head_label: "Power and Fuel", ledger_code: 1000000139, ledger_name: "Generator Running Exps.", month: null, amount_cr: 0.4198, metric: "26.6% of net sales against a peer median of 0.5%", from_month: "2026-04", to_month: "2026-08" },
    { rule_id: "DUPLICATE_BOOKING", severity: "medium", entity: scope === "dc" && entity === "holdco" ? "HOLDCO" : "SUBCO", voucher_entity: scope === "dc" && entity === "holdco" ? "VENTURES" : "RETAIL", site_code: 312, site_name: "CKSPL-ISD", head: "other_expenses", head_label: "Other expenses", ledger_code: 151, ledger_name: "Software Expense", month: "2026-07", amount_cr: 0.5636, metric: "Two vouchers post Rs 5,636,349 on Software Expense at the same site in 2026-07", from_month: "2026-04", to_month: "2026-08" },
    { rule_id: "UNMAPPED_LEDGER", severity: "medium", entity: "SUBCO", voucher_entity: "RETAIL", site_code: 5, site_name: "ALC", head: null, head_label: null, ledger_code: 9001, ledger_name: "Trademark License Fee", month: null, amount_cr: -0.05, metric: "no management group", from_month: "2026-04", to_month: "2026-08", likely_intercompany: true },
  ];
  return {
    ...base(scope, entity), rules: [
      { id: "SITE_ABOVE_PEER", title: "Store ledger above its peers", text: "A store's ledger expense, as % of net sales, is above the 95th percentile of the stores that book that ledger.", count: 1 },
      { id: "DUPLICATE_BOOKING", title: "Same ledger booked twice in a month", text: "Two different vouchers post the same amount on the same ledger at the same site in the same month.", count: 1 },
      { id: "UNMAPPED_LEDGER", title: "Ledger with no management group", text: "A ledger posted at a site of this scope that is not in the management ledger map.", count: 1 },
    ], counts: { SITE_ABOVE_PEER: 1, DUPLICATE_BOOKING: 1, UNMAPPED_LEDGER: 1 }, total: 3, exceptions: ex, truncated: false, mom_threshold: 0.5, note: "Exceptions are review prompts from stated rules, not findings of error.",
  };
}

/** Serve the expense API plus the management run header through a stubbed fetch (tests only). `fail` makes the expense calls fail with that status. */
export function installExpensesApi(opts: { fail?: number; months?: string[] } = {}) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      calls.push(url.pathname + url.search);
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      if (!url.pathname.startsWith("/mgmt-api/")) return json({}, 404);
      const path = url.pathname.slice("/mgmt-api/".length);
      const p = Object.fromEntries(url.searchParams.entries());
      const entity = (p.entity === "subco" || p.entity === "holdco" ? p.entity : "consolidated") as "consolidated" | "subco" | "holdco";
      if (path === "current") return json({ run_id: "MGMT-20261009", as_of_date: "2026-10-09", months: opts.months ?? MONTHS, months_available: opts.months ?? MONTHS, warnings: [] });
      if (opts.fail) return json({ detail: "boom" }, opts.fail);
      const scope = (p.scope as ExpScope) ?? "store";
      switch (path) {
        case "expenses/summary": return json(buildSummary(scope, entity, p.from_month, p.to_month));
        case "expenses/trend": return json(buildTrend(scope, entity, p.from_month, p.to_month));
        case "expenses/sites": return json(buildSites(scope, entity));
        case "expenses/ledgers": return json(buildLedgers({ ...p, entity: p.entity }));
        case "expenses/exceptions": return json(buildExceptions(scope, entity));
        default: return json({}, 404);
      }
    }),
  );
  return calls;
}
