import { vi } from "vitest";

/**
 * SYNTHETIC responses for the three real APIs the live Command Center reads (invented stores and round numbers, nothing from the mart).
 * The three runs deliberately carry DIFFERENT as-of dates, as the real ones can.
 */
const CR = 1e7;
const f = (n: number) => n.toFixed(2);

export const PNL = { run: "PNL-T1", asOf: "2026-10-09" };
export const CRED = { run: "GOLD-T1", asOf: "2026-10-07" };
export const CASH = { run: "CASH-T1", asOf: "2026-10-08" };
export const MGMT = { run: "MGMT-T1", asOf: "2026-10-09" };

const hdr = { recon_state: "verified", publication_state: "live", data_state: "live", data_state_label: "Live", contract_version: "gold_fpa-1", source_updated_at: "2026-10-09 16:26:46+05:30" };

const money = (revenue: number, cogs: number, books: number, opex: number) => {
  const gm = revenue - cogs + books;
  const contribution = gm + opex;
  return {
    revenue: f(revenue * CR), cogs: f(cogs * CR), cogs_books: f(books * CR), gross_margin: f(gm * CR), gross_margin_pct: ((gm * 100) / revenue).toFixed(4),
    opex: f(opex * CR), opex_pct: ((-opex * 100) / revenue).toFixed(4), contribution: f(contribution * CR), contribution_pct: ((contribution * 100) / revenue).toFixed(4),
    other_income: f(5 * CR), finance_cost: f(-1 * CR),
    other_operating_income: f(5 * CR), interest_income: "0", dc_cost: f(-12 * CR), ho_cost: f(-30 * CR), total_corporate_cost: f(-42 * CR), corporate_ebitda: f((contribution - 42) * CR),
    corporate_ebitda_pct: (((contribution - 42) * 100) / revenue).toFixed(4),
  };
};

/** The Management P&L (MIS chain), consolidated: book + management adjustment = total. Same revenue as the P&L fixture; the 1% shrinkage provision and others are the adjustments. */
const tri = (book: number, adjustment: number) => ({ book, adjustment, total: book + adjustment });
export const MGMT_LINES = {
  revenue: tri(1000, 0), other_operating_income: tri(5, 0), total_income: tri(1005, 0), material_cost: tri(-590, -10), material_margin: tri(415, -10), total_store_expenses: tri(-250, -4),
  store_ebitda: tri(165, -14), dc_cost: tri(-12, 0), ho_cost: tri(-30, 2), total_corporate: tri(-42, 2), corporate_ebitda: tri(123, -12),
  pct_material_margin: tri(41.29, -0.99), pct_store_ebitda: tri(16.42, -1.4), pct_corporate_ebitda: tri(12.24, -1.2),
};
const mgmtPnl = (q: URLSearchParams) => ({
  run_id: MGMT.run, entity: q.get("entity") ?? "consolidated", as_of_date: MGMT.asOf, months: ["2026-04", "2026-10"], store_count: 3, warnings: ["Intercompany eliminations not loaded"],
  lines: Object.entries(MGMT_LINES).map(([key, total]) => ({ key, label: key, kind: key.startsWith("pct_") ? "pct" : "value", values: {}, total })),
});
export const TOTALS = money(1000, 600, 10, -250); // gm 410 (41.0%), contribution 160 (16.0%)

export const pnlHeader = { run_id: PNL.run, as_of_date: PNL.asOf, cogs_last_bill_date: "2026-10-08", ...hdr, budget: null, budget_note: "AOP (budget) is not available for FY26-27 (the FY25-26 plan ended in March 2026). It is shown blank." };

const pnlSummary = (q: URLSearchParams) => ({
  ...pnlHeader,
  scope: { from_month: q.get("from_month") ?? "2026-04", to_month: q.get("to_month") ?? "2026-10", basis: "all", basis_label: "All entries, including unposted (provisional)", filters: {}, partial_last_month: true },
  stores_in_scope: 3,
  totals: TOTALS,
  comparison: {
    period: { from_month: "2026-04", to_month: "2026-09" },
    current: money(800, 480, 8, -200),
    last_year: { ...money(640, 380, 6, -170), gross_margin_pct: "40.5000", period: { from_month: "2025-04", to_month: "2025-09" } },
    growth: { revenue_pct: "25.0000", gross_margin_pct: null, contribution_pct: null },
    note: "Compared over complete months only.",
  },
  lines: [
    { section: "REVENUE", section_label: "Revenue from operations", group_label: "01-Net Sales", group_name: "Revenue from operations", amount: TOTALS.revenue, ledgers: 1 },
    { section: "STORE_OPEX", section_label: "Store Expenses", group_label: "02-Employee Cost", group_name: "Employee Cost", amount: f(-150 * CR), ledgers: 4 },
    { section: "STORE_OPEX", section_label: "Store Expenses", group_label: "01-Rent", group_name: "Rent", amount: f(-100 * CR), ledgers: 1 },
  ],
  below_contribution: { other_income: f(5 * CR), finance_cost: f(-1 * CR), after_below_the_line: f(164 * CR) },
  excluded_unmapped: { ledgers: 2, run_ledgers: 3, label: "Unmapped / Finance classification required", net: f(-500 * CR), gross_abs: f(1500 * CR), note: "x" },
  flags: { provisional_months: ["2026-10"], cogs_through: "2026-10-08", books_through: "2026-10-09", cogs_lags_books: true, partial_last_month: true, cogs_has_no_posting_status: "COGS has no posting status.", contribution_definition: "Store EBITDA = Material Margin less Store Expenses (STORES location only). Before DC cost, HO cost, interest income and finance cost." },
});

export const STORE_ROWS = [
  { site_code: "10", store_name: "ALPHA", state: "UP", region: "R1", revenue: f(600 * CR), contribution: f(80 * CR) },
  { site_code: "20", store_name: "BRAVO", state: "BIHAR", region: "R2", revenue: f(250 * CR), contribution: f(50 * CR) },
  { site_code: "30", store_name: "CHARLIE", state: "UP", region: "R1", revenue: f(150 * CR), contribution: f(30 * CR) },
];

export const CREDIT = { credit: 400, pastDue: 240, noDue: 40, debit: 30 }; // 60% past due -> high
const credSummary = {
  extraction_run_id: CRED.run, as_of_date: CRED.asOf, ...hdr, rules_version: "extraction-gold-1",
  item_rows: 100, vendors: 50, credit_items: 80, debit_items: 20,
  credit_outstanding: f(CREDIT.credit * CR), creditor_debit_balance: f(CREDIT.debit * CR), signed_net: f(-(CREDIT.credit - CREDIT.debit) * CR),
  past_due_credit: f(CREDIT.pastDue * CR), past_due_items: 55, due_unavailable_credit: f(CREDIT.noDue * CR), due_unavailable_items: 9,
  over_90_credit: f(120 * CR), over_90_items: 30, over_180_credit: f(60 * CR), over_180_items: 12, credit_vendors: 40, debit_vendors: 10,
  credit_concentration: { top_1: "0.1000", top_5: "0.2500", top_10: "0.3500", top_20: "0.5000" },
};
const credLedgers = [
  { ledger_code: "L1", ledger_name: "Sundry Creditors for Expenses", credit_items: 50, debit_items: 5, credit_outstanding: f(250 * CR), debit_balance: f(10 * CR), signed_net: f(-240 * CR), vendors: 30, credit_vendors: 25, debit_vendors: 5, past_due_credit: f(150 * CR), due_unavailable_credit: f(30 * CR) },
  { ledger_code: "L2", ledger_name: "Sundry Creditors Trade", credit_items: 30, debit_items: 15, credit_outstanding: f(150 * CR), debit_balance: f(20 * CR), signed_net: f(-130 * CR), vendors: 20, credit_vendors: 15, debit_vendors: 5, past_due_credit: f(90 * CR), due_unavailable_credit: f(10 * CR) },
];

export const TILL = { cash: 5, negative: 1 };
const cashSummary = {
  run_id: CASH.run, as_of_date: CASH.asOf, till_balance_date: CASH.asOf, ...hdr,
  till: { label: "Store Till Cash", note: "excludes bank balances", stores: 3, store_till_cash: f(TILL.cash * CR), mtd_debit: "0", mtd_credit: "0", fytd_debit: f(50 * CR), fytd_credit: f(45 * CR), stores_negative: TILL.negative, stores_with_cash: 2, last_activity_date: "2026-10-07", largest_store: { store_name: "ALPHA", site_code: "10", cumulative_balance: f(6 * CR) } },
  bank_review: { status: "PROVISIONAL · NOT BANK-RECONCILED", source: "site_register", ledgers_total: 0 },
  creditors: { available: false, reason: "x" },
  unavailable: [
    { id: "bank_reconciled_cash", label: "Bank-reconciled cash", reason: "No bank statement or reconciliation is available from the current sources." },
    { id: "cash_forecast", label: "Cash forecast", reason: "No forecast source exists. A projection is not shown, and none is estimated." },
    { id: "inventory", label: "Inventory", reason: "No credible current stock valuation source was found." },
    { id: "receivables", label: "Receivables", reason: "A source exists but the contract is not built yet." },
    { id: "vendor_advances", label: "Vendor advances", reason: "No source has been identified." },
  ],
};
export const TILL_STORES = [
  { site_code: 10, store_name: "ALPHA", cumulative_balance: f(6 * CR), mtd_debit: "0", mtd_credit: "0", fytd_debit: "0", fytd_credit: "0", last_activity_date: "2026-10-07" },
  { site_code: 20, store_name: "BRAVO", cumulative_balance: f(0), mtd_debit: "0", mtd_credit: "0", fytd_debit: "0", fytd_credit: "0", last_activity_date: null },
  { site_code: 30, store_name: "CHARLIE", cumulative_balance: f(-1 * CR), mtd_debit: "0", mtd_credit: "0", fytd_debit: "0", fytd_credit: "0", last_activity_date: "2026-10-06" },
];

interface Opts {
  /** HTTP status to fail a whole source with: pnl | cash | cred */
  fail?: Partial<Record<"pnl" | "cash" | "cred" | "mgmt", number>>;
}

export function installLiveSources(opts: Opts = {}) {
  const calls: string[] = [];
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      calls.push(url.pathname + url.search);
      const p = url.pathname;
      const q = url.searchParams;
      if (p.startsWith("/pnl-api/")) {
        if (opts.fail?.pnl) return json({ detail: "boom" }, opts.fail.pnl);
        const path = p.slice("/pnl-api/".length);
        if (path === "current") return json(pnlHeader);
        if (path === `runs/${PNL.run}/summary`) return json(pnlSummary(q));
        if (path === `runs/${PNL.run}/stores`) return json({ ...pnlHeader, stores_total: 3, returned: 3, limit: 10, offset: 0, stores: STORE_ROWS.map((s) => ({ ...s, cogs: "0", cogs_books: "0", gross_margin: "0", gross_margin_pct: null, opex: "0", opex_pct: null, contribution_pct: null, other_income: "0", finance_cost: "0" })) });
        if (path === `runs/${PNL.run}/reconciliation`) return json({ ...pnlHeader, excluded_unmapped: { label: "Unmapped", run_ledgers: 3, explanation: "Ledgers the finance mapping does not know.", count: 2, net: f(-500 * CR), gross_abs: f(1500 * CR), ledgers: [{ glcode: "900", ledger_name: "Stock Transfer", net: f(-400 * CR), debit: f(400 * CR), credit: "0", sites: 3 }, { glcode: "901", ledger_name: "Purchase IGST", net: f(-100 * CR), debit: f(100 * CR), credit: "0", sites: 2 }] } });
        return json({}, 404);
      }
      if (p.startsWith("/mgmt-api/")) {
        if (opts.fail?.mgmt) return json({ detail: "boom" }, opts.fail.mgmt);
        const path = p.slice("/mgmt-api/".length);
        if (path === "pnl") return json(mgmtPnl(q));
        return json({}, 404);
      }
      if (p.startsWith("/cash-api/")) {
        if (opts.fail?.cash) return json({ detail: "boom" }, opts.fail.cash);
        const path = p.slice("/cash-api/".length);
        if (path === "current") return json({ run_id: CASH.run, as_of_date: CASH.asOf, till_balance_date: CASH.asOf, ...hdr });
        if (path === `runs/${CASH.run}/summary`) return json(cashSummary);
        if (path === `runs/${CASH.run}/store-till`) {
          const asc = q.get("order") === "asc";
          const stores = [...TILL_STORES].sort((a, b) => (asc ? Number(a.cumulative_balance) - Number(b.cumulative_balance) : Number(b.cumulative_balance) - Number(a.cumulative_balance)));
          return json({ run_id: CASH.run, returned: stores.length, limit: 100, offset: 0, stores });
        }
        return json({}, 404);
      }
      if (p.startsWith("/creditors-api/")) {
        if (opts.fail?.cred) return json({ detail: "boom" }, opts.fail.cred);
        const path = p.slice("/creditors-api/".length);
        if (path === "current") return json({ extraction_run_id: CRED.run, as_of_date: CRED.asOf, ...hdr, rules_version: "extraction-gold-1" });
        if (path === `runs/${CRED.run}/summary`) return json(credSummary);
        if (path === `runs/${CRED.run}/ledgers`) return json({ extraction_run_id: CRED.run, ledgers: credLedgers });
        return json({}, 404);
      }
      return json({}, 404);
    }),
  );
  return calls;
}
