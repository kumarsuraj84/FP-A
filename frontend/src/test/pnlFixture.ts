import { vi } from "vitest";

/** A SYNTHETIC P&L API for the UI tests: invented stores and round numbers, nothing from Oracle or the mart. Amounts are exact decimal text, as the real API serves them. */
export const PNL_RUN = "run_20261007_900";
const money = (revenue: number, cogs: number, opex: number, cogsBooks = 0) => {
  const gm = revenue - cogs + cogsBooks;
  const contribution = gm + opex;
  const f = (n: number) => n.toFixed(4);
  const p = (a: number, b: number) => (b ? ((a * 100) / b).toFixed(4) : null);
  return { revenue: f(revenue), cogs: f(cogs), cogs_books: f(cogsBooks), gross_margin: f(gm), gross_margin_pct: p(gm, revenue), opex: f(opex), opex_pct: p(-opex, revenue), contribution: f(contribution), contribution_pct: p(contribution, revenue), other_income: f(0), finance_cost: f(0) };
};
const CR = 1e7;
export const TOTALS = money(1000 * CR, 600 * CR, -250 * CR, 10 * CR);
export const HEADER = { run_id: PNL_RUN, as_of_date: "2026-10-07", cogs_last_bill_date: "2026-10-06", recon_state: "verified", publication_state: "unpublished", data_state: "verified_candidate", data_state_label: "Verified candidate (not published)", contract_version: "pl-actuals-1.0", source_updated_at: "2026-10-07T09:52:41+05:30", budget: null, budget_note: "Budget is not available for FY26-27 (the FY25-26 plan ended in March 2026). It is shown blank." };
const FLAGS = { provisional_months: ["2026-10"], cogs_through: "2026-10-06", books_through: "2026-10-07", cogs_lags_books: true, partial_last_month: true, cogs_has_no_posting_status: "COGS comes from the COGS table, which has no posted / unposted split: it is the same in both bases.", contribution_definition: "Gross margin + store operating expenses. Before other income, finance cost and any head-office allocation." };
const SCOPE = (q: URLSearchParams) => ({ from_month: q.get("from_month") ?? "2026-04", to_month: q.get("to_month") ?? "2026-10", basis: q.get("basis") ?? "all", basis_label: q.get("basis") === "posted" ? "Posted entries only" : "All entries, including unposted (provisional)", filters: Object.fromEntries(["region", "cluster", "state", "vintage", "status"].flatMap((k) => (q.get(k) ? [[k, q.get(k)]] : []))), partial_last_month: true });

export const STORES = [
  { site_code: "10", store_name: "ALPHA", region: "R1", cluster: "C1", state: "UP", vintage: "SAME STORE", status: "ACTIVE", ...money(120 * CR, 70 * CR, -20 * CR), growth_pct: "12.5000", last_year_revenue: String(100 * CR), last_year_contribution: String(20 * CR) },
  { site_code: "20", store_name: "BRAVO", region: "R2", cluster: "C2", state: "BIHAR", vintage: "NEW STORE", status: "ACTIVE", ...money(60 * CR, 40 * CR, -25 * CR), growth_pct: null, last_year_revenue: null, last_year_contribution: null },
  { site_code: "30", store_name: "CHARLIE", region: "R1", cluster: "C1", state: "UP", vintage: "SAME STORE", status: "ACTIVE", ...money(90 * CR, 50 * CR, -22 * CR), growth_pct: "-3.0000", last_year_revenue: String(93 * CR), last_year_contribution: String(19 * CR) },
].map((s, i, all) => ({ ...s, rank: i + 1, stores_total: all.length }));

export const LEDGERS = { glcode: "77", ledger_name: "Salary", amount: String(-150 * CR), lines: 40, months: [{ month: "2026-09", amount: String(-150 * CR) }] };

interface Opts {
  fail?: number;
}

export function installPnlApi(opts: Opts = {}) {
  const calls: string[] = [];
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      calls.push(url.pathname + url.search);
      if (!url.pathname.startsWith("/pnl-api/")) return json({}, 404);
      if (opts.fail) return json({ detail: "boom" }, opts.fail);
      const path = url.pathname.slice("/pnl-api/".length);
      const q = url.searchParams;
      if (path === "current") return json(HEADER);
      const m = path.match(/^runs\/([^/]+)\/(.*)$/);
      if (!m) return json({}, 404);
      if (m[1] !== PNL_RUN) return json({ detail: "not found" }, 404);
      const rest = m[2];
      const filtered = !!(q.get("region") || q.get("cluster") || q.get("state") || q.get("vintage"));
      if (rest === "summary")
        return json({
          ...HEADER, scope: SCOPE(q), stores_in_scope: filtered ? 2 : 3, totals: TOTALS,
          comparison: { period: { from_month: "2026-04", to_month: "2026-09" }, current: TOTALS, last_year: { ...money(800 * CR, 500 * CR, -230 * CR), period: { from_month: "2025-04", to_month: "2025-09" } }, growth: { revenue_pct: "25.0000", gross_margin_pct: "20.0000", contribution_pct: "30.0000" }, note: "Compared over complete months only." },
          lines: [
            { section: "REVENUE", section_label: "Net sales (ex-GST)", group_label: "01-Net Sales", amount: TOTALS.revenue, ledgers: 1 },
            { section: "STORE_OPEX", section_label: "Store operating expenses", group_label: "02-Employee Cost", amount: String(-150 * CR), ledgers: 4 },
            { section: "STORE_OPEX", section_label: "Store operating expenses", group_label: "01-Rent", amount: String(-100 * CR), ledgers: 2 },
          ],
          below_contribution: { other_income: "0", finance_cost: "0", after_below_the_line: TOTALS.contribution },
          excluded_unmapped: { ledgers: 2, run_ledgers: 3, label: "Unmapped / Finance classification required", net: String(-500 * CR), gross_abs: String(1500 * CR), note: "x" }, flags: FLAGS,
          ...(filtered ? {} : { reconciliation: { parent: { revenue: TOTALS.revenue, contribution: TOTALS.contribution }, children_sum: { revenue: TOTALS.revenue, contribution: TOTALS.contribution }, stores: money(900 * CR, 550 * CR, -230 * CR), non_store: money(100 * CR, 50 * CR, -20 * CR), reconciles: true } }),
        });
      if (rest === "trend") {
        const months = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"].map((month, i) => ({ month, ...money((140 - i * 5) * CR, 85 * CR, -35 * CR), provisional: month === "2026-10", partial: month === "2026-10", last_year: { month: `2025-${month.slice(5)}`, ...money(100 * CR, 62 * CR, -30 * CR) }, growth_revenue_pct: month === "2026-10" ? null : "30.0000" }));
        return json({ ...HEADER, scope: SCOPE(q), months, parent: { revenue: TOTALS.revenue, contribution: TOTALS.contribution }, children_sum: { revenue: TOTALS.revenue, contribution: TOTALS.contribution }, reconciles: true, flags: FLAGS });
      }
      if (rest === "hierarchy") {
        const o = (value: string, stores: number) => ({ value, stores, revenue: String(stores * 100 * CR), contribution: String(stores * 20 * CR) });
        return json({ ...HEADER, options: { region: [o("R1", 2), o("R2", 1)], cluster: [o("C1", 2), o("C2", 1)], state: [o("UP", 2), o("BIHAR", 1)], vintage: [o("SAME STORE", 2), o("NEW STORE", 1)], status: [o("ACTIVE", 3)] }, stores: 3 });
      }
      if (rest === "stores") {
        const order = q.get("order") ?? "desc";
        let list = [...STORES].filter((s) => (!q.get("region") || s.region === q.get("region")) && (!q.get("vintage") || s.vintage === q.get("vintage")));
        const key = ({ gross_margin_pct: "gross_margin_pct", opex_pct: "opex_pct", growth: "growth_pct", contribution_pct: "contribution_pct", revenue: "revenue" } as Record<string, string>)[q.get("sort") ?? ""] ?? "contribution";
        const floor = Number(q.get("min_revenue") ?? 0);
        list = list.filter((s) => Number(s.revenue) >= floor);
        const val = (s: Record<string, unknown>) => (s[key] === null || s[key] === undefined ? null : Number(s[key]));
        list.sort((a, b) => {
          const x = val(a), y = val(b);
          if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;   // missing values always last
          return order === "desc" ? y - x : x - y;
        });
        list = list.map((s, i) => ({ ...s, rank: i + 1 }));
        const limit = Number(q.get("limit") ?? 50);
        const total = list.reduce((a, s) => a + Number(s.contribution), 0);
        return json({ ...HEADER, scope: SCOPE(q), stores_total: list.length, returned: Math.min(limit, list.length), limit, offset: 0, sort: q.get("sort") ?? "contribution", order, stores: list.slice(0, limit), growth_basis: { from_month: "2026-04", to_month: "2026-09", note: "x" },
          parent: { revenue: "0", contribution: total.toFixed(4) }, children_sum: { revenue: "0", contribution: total.toFixed(4) }, reconciles: true, flags: FLAGS });
      }
      const st = rest.match(/^stores\/([^/]+)$/);
      if (st) {
        const s = STORES.find((x) => x.site_code === st[1]);
        if (!s) return json({ detail: "unknown site" }, 404);
        return json({ ...HEADER, scope: SCOPE(q), site: { site_code: s.site_code, store_name: s.store_name, region: s.region, cluster: s.cluster, state: s.state, vintage: s.vintage, status: s.status, opening_date: "2020-01-01", last_bill_date: "2026-10-06", is_store: true },
          totals: money(Number(s.revenue), Number(s.cogs), Number(s.opex)), comparison: null, months: [{ month: "2026-09", ...money(Number(s.revenue), Number(s.cogs), Number(s.opex)) }],
          lines: [{ section: "REVENUE", section_label: "Net sales (ex-GST)", group_label: "01-Net Sales", amount: s.revenue, ledgers: 1 }, { section: "STORE_OPEX", section_label: "Store operating expenses", group_label: "02-Employee Cost", amount: s.opex, ledgers: 1 }],
          reconciles: true, flags: FLAGS });
      }
      const gl = rest.match(/^stores\/([^/]+)\/groups\/([^/]+)\/ledgers$/);
      if (gl) return json({ ...HEADER, site_code: gl[1], group_label: decodeURIComponent(gl[2]), ledgers: [LEDGERS], parent: { amount: LEDGERS.amount }, children_sum: { amount: LEDGERS.amount }, reconciles: true });
      if (rest === "reconciliation")
        return json({ ...HEADER, tolerance_rupees: "1000.0000", sales_tieout: { basis: "x", months: [{ month: "2026-09-01", site_months: 3, tied: 2, books_sales: "1", table_sales: "1", difference: "0", max_abs_difference: "0" }], site_months: 3, tied: 2, not_tied: 1, largest_gaps: [] },
          excluded_unmapped: { label: "Unmapped / Finance classification required", run_ledgers: 3, explanation: "x", count: 1, net: String(-5 * CR), gross_abs: String(5 * CR), ledgers: [{ glcode: "9", ledger_name: "Mystery Fee", net: String(-5 * CR), debit: "1", credit: "0", sites: 1 }] },
          sites_without_books_sales: { count: 1, sales_ex_gst: String(2 * CR), sites: [{ site_code: "96", store_name: "HO", sales_ex_gst: String(2 * CR), cogs: "1" }] }, flags: FLAGS });
      return json({}, 404);
    }),
  );
  return calls;
}
