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
const FLAGS = { provisional_months: ["2026-10"], cogs_through: "2026-10-06", books_through: "2026-10-07", cogs_lags_books: true, partial_last_month: true, cogs_has_no_posting_status: "Material Cost comes from the COGS table, which has no posted / unposted split: it is the same in both bases.", contribution_definition: "Store EBITDA = Material Margin less Store Expenses (STORES location only). Before DC cost, HO cost, interest income and finance cost." };
const SCOPE = (q: URLSearchParams) => ({ from_month: q.get("from_month") ?? "2026-04", to_month: q.get("to_month") ?? "2026-10", basis: q.get("basis") ?? "all", basis_label: q.get("basis") === "posted" ? "Posted entries only" : "All entries, including unposted (provisional)", filters: Object.fromEntries(["region", "cluster", "state", "vintage", "status"].flatMap((k) => (q.get(k) ? [[k, q.get(k)]] : []))), partial_last_month: true });

export const STORES = [
  { site_code: "10", store_name: "ALPHA", region: "R1", cluster: "C1", state: "UP", vintage: "SAME STORE", status: "ACTIVE", ...money(120 * CR, 70 * CR, -20 * CR), growth_pct: "12.5000", last_year_revenue: String(100 * CR), last_year_contribution: String(20 * CR) },
  { site_code: "20", store_name: "BRAVO", region: "R2", cluster: "C2", state: "BIHAR", vintage: "NEW STORE", status: "ACTIVE", ...money(60 * CR, 40 * CR, -25 * CR), growth_pct: null, last_year_revenue: null, last_year_contribution: null },
  { site_code: "30", store_name: "CHARLIE", region: "R1", cluster: "C1", state: "UP", vintage: "SAME STORE", status: "ACTIVE", ...money(90 * CR, 50 * CR, -22 * CR), growth_pct: "-3.0000", last_year_revenue: String(93 * CR), last_year_contribution: String(19 * CR) },
].map((s, i, all) => ({ ...s, rank: i + 1, stores_total: all.length }));

export const LEDGERS = { glcode: "77", ledger_name: "Salary", amount: String(-150 * CR), lines: 40, months: [{ month: "2026-09", amount: String(-150 * CR) }] };

interface Opts {
  fail?: number;
  /** the live gold state today: no day-aligned last year (aligned_days null, empty ly, ly_ytd_available false) */
  noLy?: boolean;
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
            { section: "REVENUE", section_label: "Revenue from operations", group_label: "01-Net Sales", group_name: "Revenue from operations", amount: TOTALS.revenue, ledgers: 1 },
            { section: "STORE_OPEX", section_label: "Store Expenses", group_label: "02-Employee Cost", group_name: "Employee Cost", amount: String(-150 * CR), ledgers: 4 },
            { section: "STORE_OPEX", section_label: "Store Expenses", group_label: "01-Rent", group_name: "Rent", amount: String(-100 * CR), ledgers: 2 },
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
          lines: [{ section: "REVENUE", section_label: "Revenue from operations", group_label: "01-Net Sales", group_name: "Revenue from operations", amount: s.revenue, ledgers: 1 }, { section: "STORE_OPEX", section_label: "Store Expenses", group_label: "02-Employee Cost", group_name: "Employee Cost", amount: s.opex, ledgers: 1 }],
          reconciles: true, flags: FLAGS });
      }
      const gl = rest.match(/^stores\/([^/]+)\/groups\/([^/]+)\/ledgers$/);
      if (gl) return json({ ...HEADER, site_code: gl[1], group_label: decodeURIComponent(gl[2]), ledgers: [LEDGERS], parent: { amount: LEDGERS.amount }, children_sum: { amount: LEDGERS.amount }, reconciles: true });
      // ───── the review layer ─────
      if (rest === "pivot") {
        const mode = q.get("mode") ?? "stores";
        if (q.get("group")) return json({ ...HEADER, group: q.get("group"), ledgers: [{ glcode: "77", ledger_name: "Salary", cells: { "2026-04": String(-20 * CR), "2026-05": String(-22 * CR), ytd: String(-42 * CR) }, ly_ytd: String(-30 * CR) }] });
        const cols = [["2026-04", "Apr 26", "month", false], ["2026-05", "May 26", "month", false], ["2026-10", "Oct 26", "month", true], ["q1", "Q1", "quarter", false], ["qtd", "Q3 to date", "quarter", true], ["ytd", "YTD", "ytd", true]] as const;
        const val = (id: string, c: string): string => {
          const k = c === "2026-04" ? 1 : c === "2026-05" ? 1.1 : c === "2026-10" ? 0.3 : c === "q1" ? 1 : c === "qtd" ? 0.3 : 2.4;
          const base: Record<string, number> = { revenue: 100, cogs: -60, cogs_books: 1, gross_margin: 41, "g:02-Employee Cost": -20, "g:01-Rent": -12, store_opex: -32, contribution: 9, other_income: 1, finance_cost: 0 };
          return String(Math.round(base[id] * k * CR));
        };
        const defs: [string, string, string, number, string | null][] = [["revenue", "Revenue from operations", "line", 0, null], ["cogs", "Material Cost (COGS table)", "line", 0, null], ["cogs_books", "Other material cost items (books)", "line", 0, null], ["gross_margin", mode === "company" ? "Material Margin" : "Gross Margin", "subtotal", 0, null],
          ["g:02-Employee Cost", "Employee Cost", "group", 1, "02-Employee Cost"], ["g:01-Rent", "Rent", "group", 1, "01-Rent"], ["store_opex", "Store Expenses", "subtotal", 0, null],
          ["contribution", mode === "company" ? "Store EBITDA (before DC cost, HO cost, interest income and finance cost)" : "4-Wall EBITDA (Gross Margin less store expenses)", "subtotal", 0, null], ["other_income", "Other operating income and interest income (memo)", "memo", 0, null], ["finance_cost", "Finance cost", "memo", 0, null]];
        return json({ ...HEADER, scope: SCOPE(q), mode, stores: 3, ly_ytd_available: !opts.noLy, ly_ytd_note: "LY's YTD is day aligned: complete months, plus days 1 to N of the same month.", unmapped_note: "Ledgers without a finance group are Unmapped / Finance classification required: they are in no row or total.",
          columns: cols.map(([id, label, kind, partial]) => ({ id, label, kind, partial, from_month: "2026-04", to_month: "2026-10" })),
          rows: defs.map(([id, label, kind, level, group]) => { const cells = Object.fromEntries(cols.map(([c]) => [c, val(id, c)])); const ly = String(Math.round(Number(cells.ytd) * 0.8)); return { id, label, kind, level, group, cells, ly_ytd: ly, variance: String(Number(cells.ytd) - Number(ly)), variance_pct: "25.0000" }; }) });
      }
      if (rest === "comparison") {
        const mm = (r: number) => money(r * CR, r * 0.6 * CR, -r * 0.3 * CR, 0);
        const w = (id: string, label: string, k: number, from: string, to: string) => ({ id, label, from_month: from, to_month: to, day_aligned: true, ty: mm(100 * k), ly: opts.noLy ? null : mm(80 * k), growth: opts.noLy ? null : { revenue_pct: "25.0000", gross_margin_pct: "25.0000", contribution_pct: "25.0000", gm_bps: "120.0000", opex_bps: "-35.0000", contribution_bps: "85.0000" } });
        return json({ ...HEADER, scope: SCOPE(q), mode: q.get("mode") ?? "stores", as_of: "2026-10-07", partial_month: true, aligned_days: opts.noLy ? null : 7, windows: [w("mtd", "Month to date", 0.3, "2026-10", "2026-10"), w("qtd", "Quarter to date", 0.3, "2026-10", "2026-10"), w("ytd", "Year to date", 2.4, "2026-04", "2026-10")], note: "Day aligned: the current month is compared with the same days of last year, never with a whole month. Percent measures compare in basis points." });
      }
      if (rest === "expenses") {
        const line = (group: string, label: string, cost: number, ps: number) => ({ group, label, cost: String(cost * CR), pct_of_sales: ((cost / 100) * 100).toFixed(4), ly_cost: String(cost * 0.9 * CR), ly_pct_of_sales: (cost / 100 * 90).toFixed(4), bps: "30.0000", psf: ps.toFixed(4), ly_psf: (ps * 0.9).toFixed(4), psf_stores: 2,
          trend: ["2026-04", "2026-05", "2026-06"].map((month, i) => ({ month, cost: String((cost / 3) * CR), pct_of_sales: (cost / 100 * 100 + i * 0.1).toFixed(4) })) });
        return json({ ...HEADER, scope: SCOPE(q), months: ["2026-04", "2026-05", "2026-06"], ly_months: ["2025-04", "2025-05", "2025-06"], revenue: String(300 * CR), ly_revenue: String(240 * CR), stores: 3, stores_with_area: 2, lines: [line("01-Rent", "Rent", 18.4, 41.6), line("02-Employee Cost", "Employee Cost", 26.8, 60.5), line("03-Power and Fuel Expenses", "Power and Fuel Expenses", 9.1, 20.6)], psf_note: "₹ per sq ft per month = cost / effective area (area x active days / calendar days), over the stores that have an area." });
      }
      if (rest === "heatmap") {
        const sort = q.get("sort") ?? "worst_contribution_pct";
        const rows = STORES.map((s) => ({ site_code: s.site_code, store_name: s.store_name, region: s.region, cluster: s.cluster, state: s.state, vintage: s.vintage, area: "8000", opportunity: s.site_code === "20" ? String(2 * CR) : "0", peer_basis: "region + vintage", revenue: s.revenue, gross_margin_pct: s.gross_margin_pct, opex_pct: s.opex_pct,
          contribution: s.contribution, contribution_pct: s.contribution_pct, growth_pct: s.growth_pct, sales_psf: "150.0000", payroll_psf: "10.0000", rent_psf: "12.0000", power_psf: "4.0000", ly_contribution_pct: "18.0000", contribution_bps: s.site_code === "20" ? "-400.0000" : "150.0000", gm_bps: "10.0000", opex_bps: s.site_code === "20" ? "300.0000" : "-20.0000" }));
        const key = ({ worst_contribution_pct: ["contribution_pct", 1], best_contribution_pct: ["contribution_pct", -1], largest_decline_bps: ["contribution_bps", 1], highest_opex_pct: ["opex_pct", -1], largest_loss: ["contribution", 1], worst_opex_deterioration: ["opex_bps", -1], biggest_opportunity: ["opportunity", -1], name: ["store_name", 1] } as Record<string, [string, number]>)[sort] ?? ["contribution_pct", 1];
        const sorted = [...rows].sort((a, b) => key[1] * (Number((a as never)[key[0]]) - Number((b as never)[key[0]]))).map((r, i) => ({ ...r, rank: i + 1 }));
        const sc = (p10: string, p50: string, p90: string, hib = true) => ({ p10, p50, p90, n: 3, higher_is_better: hib });
        return json({ ...HEADER, scope: SCOPE(q), sorts: ["worst_contribution_pct"], stores_total: sorted.length, returned: sorted.length, sort, stores: sorted, months: ["2026-04", "2026-05", "2026-06"], note: "Colours are relative to the stores listed (10th to 90th percentile), never to a target. PSF is ₹ per sq ft per month; a store without an area has no PSF.",
          scales: { growth_pct: sc("-3", "5", "12.5"), gross_margin_pct: sc("30", "35", "42"), opex_pct: sc("15", "22", "30", false), contribution_pct: sc("5", "18", "26"), contribution: sc(String(10 * CR), String(18 * CR), String(30 * CR)), sales_psf: sc("100", "150", "200"), payroll_psf: sc("8", "10", "12", false), rent_psf: sc("10", "12", "14", false), power_psf: sc("3", "4", "5", false), contribution_bps: sc("-400", "50", "150") } });
      }
      const pe = rest.match(/^stores\/([^/]+)\/peers$/);
      if (pe) {
        const metric = (m: string, store: string, med: string, top: string, bot: string, pos: string) => ({ metric: m, store, peer_median: med, top_quartile: top, bottom_quartile: bot, peers_with_value: 8, position: pos, vs_median: (Number(store) - Number(med)).toFixed(4) });
        const metrics = [metric("growth_pct", "12.5", "6", "10", "2", "top quartile"), metric("gross_margin_pct", "41.7", "40", "42", "38", "middle"), metric("contribution_pct", "25", "18", "22", "12", "top quartile"), metric("opex_pct", "16.7", "21", "18", "25", "top quartile"),
          metric("sales_psf", "150", "140", "160", "120", "middle"), metric("payroll_psf", "10", "11", "9", "13", "middle"), metric("rent_psf", "12", "12", "10", "14", "middle"), metric("power_psf", "6", "4", "3", "5", "bottom quartile")];
        const g = (dimension: string, basis: string, requested: string, peers: number) => ({ dimension, basis, requested, peers, metrics });
        return json({ ...HEADER, site_code: pe[1], keys: { region: "R1", state: "UP", cluster: "C1", vintage: "SAME STORE", size_band: "7,000 to 9,000", network: "all" }, groups: [g("default", "region + vintage", "region + vintage", 8), g("state", "state", "state", 12), g("region", "region", "region", 14), g("cluster", "cluster", "cluster", 6), g("vintage", "vintage", "vintage", 20), g("size_band", "size_band", "size_band", 9), g("network", "whole network", "network", 30)], rules: { peers: "same region and vintage; fewer than 5 qualifying stores falls back to the same state, then the whole network" } });
      }
      if (rest === "exceptions/expenses") {
        const e = (site: string, name: string, group: string, label: string, severity: string, cur: number, exp: number, flags: string[], why: string) => ({ severity, site_code: site, store_name: name, region: "R1", state: "UP", group, label, month: "2026-09", current: String(cur), expected: String(exp), variance: String(cur - exp), variance_pct: (((cur - exp) / exp) * 100).toFixed(4), pct_of_sales: "2.1000", psf: "31.0000", peer_pct_of_sales: "1.2000", peer_psf: "18.0000", flags, why, impact: String(Math.abs(cur - exp)), provisional_month: false });
        const list = [e("10", "ALPHA", "03-Power and Fuel Expenses", "Power and Fuel Expenses", "Critical", 840000, 510000, ["SUDDEN_INCREASE", "PEER"], "₹8.4 L against a 3-month average of ₹5.1 L (+65%); 1.8 times the peer median share of sales"), e("30", "CHARLIE", "01-Rent", "Rent", "High", 40000, 250000, ["SUDDEN_DECREASE"], "₹0.4 L against a 3-month average of ₹2.5 L (-84%): check for a missing posting"), e("20", "BRAVO", "02-Employee Cost", "Employee Cost", "Medium", 300000, 200000, ["SHARE_OF_SALES"], "7.3% of sales against its usual 4.8%")];
        return json({ ...HEADER, scope: SCOPE(q), month: "2026-09", total: list.length, by_severity: { Critical: 1, High: 1, Medium: 1 }, exceptions: list, provisional_month: false, rules: { baseline: "the average of the 3 complete months before the month reviewed", sudden_increase: "cost at least 30% above baseline and at least ₹25,000 above it", severity: "Critical: ..." } });
      }
      if (rest === "exceptions/revenue") {
        const list = [{ severity: "High", site_code: "20", store_name: "BRAVO", region: "R2", state: "BIHAR", month: "2026-09", revenue: String(40 * CR), baseline_revenue: String(70 * CR), growth_pct: "-12.0000", gross_margin_pct: "30.0000", contribution: String(3 * CR), sales_psf: "90.0000", flags: ["SALES_DROP", "SALES_PSF_DROP"], why: "sales ₹4,000.0 L against a 3-month average of ₹7,000.0 L (-43%)", impact: String(30 * CR), provisional_month: false }];
        return json({ ...HEADER, scope: SCOPE(q), month: "2026-09", total: 1, by_severity: { High: 1 }, exceptions: list, provisional_month: false, rules: { sales_drop: "sales at least 25% below the average of the prior 3 complete months" } });
      }
      if (rest === "quality")
        return json({ ...HEADER, stores: 3, stores_without_area: { count: 1, sites: [{ site_code: "30", store_name: "CHARLIE" }], effect: "no per-sq-ft measure for these stores; they are left out of every PSF average (never given an average area)" },
          stores_with_placeholder_opening_date: { count: 2, effect: "treated as open for the whole window (reason OPENING_DATE_PLACEHOLDER)" }, closed_stores_without_a_closing_date: { count: 1, sites: [{ site_code: "40", store_name: "DELTA", status: "CLOSED" }], effect: "the last bill date is not a real date, so the store is treated as open every month" },
          effective_area_reasons: [{ reason: "FULL_MONTH", n: 40 }, { reason: "OPENED_IN_MONTH", n: 2 }], cogs_pct_by_month: [{ month: "2026-07", cogs_pct_of_sales: "65.2000", outlier: false }, { month: "2026-08", cogs_pct_of_sales: "72.2000", outlier: true }, { month: "2026-09", cogs_pct_of_sales: "77.6000", outlier: true }], cogs_typical_pct: "65.2000", area_units_note: "AREA in the site master has no comment: the figures read as square feet. Finance to confirm the unit." });
      if (rest === "reconciliation")
        return json({ ...HEADER, tolerance_rupees: "1000.0000", sales_tieout: { basis: "x", months: [{ month: "2026-09-01", site_months: 3, tied: 2, books_sales: "1", table_sales: "1", difference: "0", max_abs_difference: "0" }], site_months: 3, tied: 2, not_tied: 1, largest_gaps: [] },
          excluded_unmapped: { label: "Unmapped / Finance classification required", run_ledgers: 3, explanation: "x", count: 1, net: String(-5 * CR), gross_abs: String(5 * CR), ledgers: [{ glcode: "9", ledger_name: "Mystery Fee", net: String(-5 * CR), debit: "1", credit: "0", sites: 1 }] },
          sites_without_books_sales: { count: 1, sales_ex_gst: String(2 * CR), sites: [{ site_code: "96", store_name: "HO", sales_ex_gst: String(2 * CR), cogs: "1" }] }, flags: FLAGS });
      return json({}, 404);
    }),
  );
  return calls;
}
