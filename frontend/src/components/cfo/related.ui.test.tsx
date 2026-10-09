import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { installCreditorsApi } from "@/test/creditorsFixture";

/* Related Party Transactions runs on a SYNTHETIC Related Party API (invented parties, round numbers). */

const T = { timeout: 5000 };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const zero = { D0_30: "0.00", D31_60: "0.00", D61_90: "0.00", D91_180: "0.00", D181_365: "0.00", D365_PLUS: "0.00", UNCLASSIFIED: "0.00" };
const NOT_LOADED = { available: false, reason: "Intercompany loan data not loaded in gold_fpa yet", tables: [], rows: [] };
const LEDGER_LOANS = { available: true, reason: null, source: "ledger", tables: [], rows: [], net_movement_cr: "153.7177", subco_balance_cr: "153.7177", holdco_balance_cr: "141.2342", full_history: true };

const fy = (name: string, h: string, sc: string, d: string, ok: boolean, one: boolean) => ({ fy: name, holdco_net_cr: h, subco_net_cr: sc, difference_cr: d, matches: ok, one_sided: one });
const mon = (month: string, d: string) => ({ month, holdco_dr_cr: "0.0000", holdco_cr_cr: "6.9975", subco_dr_cr: "6.6675", subco_cr_cr: "0.0000", holdco_net_cr: "6.9975", subco_net_cr: "6.6675", difference_cr: d, matches: false });
const side = { ledgers: [], net_cr: "0", dr_cr: "0", cr_cr: "0" };
const INTERCOMPANY = (full: boolean) => ({
  as_of_date: "2026-10-09", coverage_from: "2025-04-01",
  sources: { voucher_lines: "cost-tagged lines since 2025-04, a partial view", full_ledger: { table: "gold_fpa.related_party_gl_lines", present: full, columns: [], used: full, note: full ? "Used for every ledger it carries." : "Not in gold_fpa yet." }, loan: full ? "related_party_gl_lines" : "voucher_lines", interest: "voucher_lines", service: "voucher_lines" },
  reported_by_ledger: { source: "silver", note: "To be reconciled: full ledger detail is being added to gold_fpa (related_party_gl_lines).", ledgers: [{ entity: "VENTURES", side: "holdco", glcode: 1140, glname: "Unsecured Loan", lines: 90, amount_cr: "141.2342", drcr: "Dr", last_entry: "2026-09-29", approx: false, note: "" }], loan_difference_cr: "12.4835", after_old_debit_cr: "-4.9765" },
  pairs: [
    { pair_id: "LOAN", source: full ? "related_party_gl_lines" : "voucher_lines", label: "Intercompany loan (HoldCo lends to SubCo)", configured: true, holdco: side, subco: side, totals: { holdco_net_cr: "141.2342", subco_net_cr: "153.7177", difference_cr: "-12.4835", mirrors: false }, monthly: [],
      by_fy: [fy("FY2018", "0.0000", "3.6405", "-3.6405", false, true), fy("FY2020", "6.0000", "6.0000", "0.0000", true, false)], notes: [] },
    { pair_id: "SERVICE", source: "voucher_lines", label: "Quarterly service charges (HoldCo bills SubCo)", configured: true, holdco: side, subco: side, totals: { holdco_net_cr: "40.9911", subco_net_cr: "39.3447", difference_cr: "1.6463", mirrors: false }, monthly: [mon("2025-07", "0.3300")], by_fy: [], notes: [] },
  ],
  loan: {
    net_movement_cr: full ? "153.7177" : "46.1684", drawn_cr: "169.4000", repaid_cr: "123.2316", by_month: [], balance_note: "Opening balance before 2025-04 is not in the data, so only the movement since 2025-04 is shown",
    full_history: full, holdco_balance_cr: "141.2342", subco_balance_cr: "153.7177", carried_years_mirror: true, carried_years_variance_cr: "0.0000", by_fy: [],
    not_carried: { pre_carry_gap_cr: "-12.4835", pre_carry_years: ["FY2015", "FY2019"], after_uncarried_difference_cr: "4.9765", note: "Shown, not eliminated.", ledger: { glcode: 1114925831, glname: "Unsecured Loan", dr_cr: "17.4600", cr_cr: "0.0000", net_cr: "-17.4600", lines: 3 } },
    basis: full ? "Full ledger history from gold_fpa.related_party_gl_lines" : "Cost-tagged voucher lines since Apr-2025, a partial view: this is a movement, not the loan balance", source: full ? "related_party_gl_lines" : "voucher_lines", mirrors: !full, variance_cr: "0.0000",
    interest: { accrued_holdco_cr: "-1.0605", payable_subco_cr: "-1.0605", expense_subco_cr: "32.1240", payable_credited_cr: "0.0000", payable_debited_cr: "1.0605", mirrors: true, note: "" },
  },
  service: { billed_holdco_cr: "40.9911", charged_subco_cr: "39.3447", unmatched_cr: "1.6463", billings: 5, by_quarter: [{ month: "2025-07", holdco_cr: "6.9975", subco_cr: "6.6675", difference_cr: "0.3300", matches: false }], other_months: { months: [], difference_cr: "0" }, constant_difference: true, notes: [] },
  flags: [{ ledger: "Management Stewardship and other related service (SubCo, ledger 1114927935)", reason: "Debits and credits are equal (11.9182 Cr each), so it nets to nil: to be explained" }],
  candidates: [{ entity: "RETAIL", glcode: 139, glname: "Vehicle Loan", ledger_type: "Liability", lines: 5, dr_cr: "0.01", cr_cr: "0.15", net_cr: "-0.1353", reason: "Name matches loan; NOT included" }],
  effect_on_ebitda: { note: "n", consolidated_cr: "0.0000", subco_standalone_cr: "-39.3447", holdco_standalone_cr: "40.9911", reason: "Neither side is in the Management P&L today, so consolidated EBITDA is unaffected." },
  controls: { loan_mirror_variance_cr: "-12.4835", service_unmatched_cr: "1.6463", interest_variance_cr: "0.0000", loan_mirrors: false, loan_carried_years_variance_cr: "0.0000", loan_carried_years_mirror: true, loan_pre_carry_gap_cr: "-12.4835" },
});
const zt = { entries: 2, lines: 2, debit: "100.00", credit: "40.00", net: "60.00", debit_cr: "0.0000", credit_cr: "0.0000", net_cr: "0.0000" };
const GL = (full: boolean) => ({
  as_of_date: "2026-10-09", filters: { entity: null, from_month: null, to_month: null, basis: "all", limit: 50, offset: 0 }, total_entries: 2, returned: 2,
  entries: [
    { entcode: "E1", entity: "VENTURES", entno: null, entdt: "2026-09-29", entry_type: "Voucher", ledgers: ["Unsecured Loan"], party: "CITYKART STORES PVT. LTD. (Delhi)", counterparty_entity: "SUBCO", debit: "5000000.00", credit: "0", debit_cr: "0.5000", credit_cr: "0.0000", release_status: "P", narration: "Loan", reason: "party", register_status: "proposed", balances: [{ ledger: "Unsecured Loan", party: "x", running_balance: "1000000000", running_balance_cr: "141.2342" }] },
    { entcode: "E2", entity: "RETAIL", entno: null, entdt: "2026-07-30", entry_type: "Journal", ledgers: ["Trademark License Fee"], party: null, counterparty_entity: "HOLDCO", debit: "1000000.00", credit: "0", debit_cr: "0.1000", credit_cr: "0.0000", release_status: "P", narration: null, reason: "ledger:service_charge", register_status: "proposed" },
  ],
  summary: [], by_entity: { RETAIL: zt, VENTURES: { ...zt, entries: 5 } }, same_company: { ...zt, entries: 121, credit: "47965737.08" },
  mirror: { holdco_books: zt, subco_books: zt, debit_vs_credit_cr: "-31.0556", credit_vs_debit_cr: "-9.4069", mirrors: false, note: "" }, ledger_mirror: [{ pair_id: "LOAN", label: "Loan", holdco_net_cr: "1", subco_net_cr: "1", difference_cr: "0.0000", mirrors: true }],
  register: [{ books_of_entity: "RETAIL", party_pattern: "^citykart retail pvt", counterparty_entity: "HOLDCO", status: "proposed", note: "" }, { books_of_entity: "VENTURES", party_pattern: "^citykart stores pvt", counterparty_entity: "SUBCO", status: "confirmed", note: "" }],
  party_register: { path_exists: true, patterns: 2, proposed: 1, confirmed: 1 },
  source: { entries: full ? "related_party_gl_lines" : "voucher_lines", full_ledger: { table: "gold_fpa.related_party_gl_lines", present: full, columns: [], used: full, note: "" }, control: full ? { ok: true, by_entity: [] } : null },
});

function party(code: number, name: string, status: "proposed" | "confirmed", payable: number, debit: number) {
  return {
    sub_ledger_code: code, party_name: name, group_entity: "Test HoldCo", relationship: "group company", status, basis: "name", note: "",
    payable: `${payable}.00`, debit_balance: `${debit}.00`, net: `${payable - debit}.00`, payable_cr: "0", debit_balance_cr: "0", net_cr: "0",
    items: 2, oldest_doc: "2025-01-22", max_age_days: 625, ageing: { ...zero, D365_PLUS: `${payable}.00` },
  };
}

const SUMMARY = (loans: unknown) => ({
  as_of_date: "2026-10-04", extraction_run_id: "GOLD-20261004", currency: "INR", register: { path_exists: true, parties: 2, proposed: 1, confirmed: 1 },
  creditors: {
    payable: "600000000.00", debit_balance: "100000000.00", net: "500000000.00", payable_cr: "60.0000", debit_balance_cr: "10.0000", net_cr: "50.0000", parties: 2, items: 4,
    by_party: [party(111, "Alpha Group Co (test)", "confirmed", 400000000, 100000000), party(222, "Beta Cross Charge (test)", "proposed", 200000000, 0)],
    by_age: [], by_due_status: [],
  },
  loans,
  related_party_gl: { source: "related_party_gl_lines", entries: 2942, by_entity: { RETAIL: { ...zt, entries: 2036 }, VENTURES: { ...zt, entries: 785 } }, same_company: { ...zt, entries: 121, credit: "47965737.08" }, mirror_mirrors: false, mirror_debit_vs_credit_cr: "-31.0556", mirror_credit_vs_debit_cr: "-9.4069" },
  candidates: [
    { sub_ledger_code: 333, party_name: "Gamma Group Stores (test)", class_name: "Supplier-Expenses", is_extinct: false, open_items: 3, payable: "5000000.00", debit_balance: "0", reason: "Name looks like a group entity; not in the register" },
    { sub_ledger_code: 444, party_name: "Delta Group Branch (test)", class_name: "Customer", is_extinct: false, open_items: 0, payable: "0", debit_balance: "0", reason: "no open creditor items" },
  ],
  controls: {
    main_plus_related_equals_all: true, variance: "0.00", variance_cr: "0.0000", debit_variance: "0.00", net_variance: "0.00", main_payable: "3000000000.00", related_payable: "600000000.00",
    all_payable: "3600000000.00", main_payable_cr: "300.0000", related_payable_cr: "60.0000", all_payable_cr: "360.0000", main_debit_balance: "0", related_debit_balance: "0", all_debit_balance: "0",
  },
});

const ITEM = {
  item_ref: "9001", ledger_code: "1", ledger_name: "Sundry Creditors for Expenses", drcr: "Cr", amount: "-100.00", adjusted: null, pending: "-100.00", document_type: "Purchase Service", due_date_basis: "E",
  document_date: "2025-01-22", due_date: "2025-01-22", entry_date: "2025-01-22", document_age_days: 625, document_age_bucket: "D365_PLUS", overdue_days: 625, due_status: "PAST_DUE_OR_DUE_TODAY",
  date_quality_status: "OK", classification_status: "CLASSIFIED", document_code: "DOC1", document_no: "42", document_initial: "PS", ref_no: null, ref_date: null,
};

function installRelated(loans: unknown = LEDGER_LOANS, fail?: number, full = true) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    if (!url.pathname.startsWith("/related-api/")) return json({}, 404);
    if (fail) return json({ detail: "x" }, fail);
    if (url.pathname === "/related-api/summary") return json(SUMMARY(loans));
    if (url.pathname === "/related-api/intercompany") return json(INTERCOMPANY(full));
    if (url.pathname === "/related-api/gl-entries") return json(GL(full));
    if (url.pathname === "/related-api/items") {
      return json({ as_of_date: "2026-10-04", sub_ledger_code: Number(url.searchParams.get("sub_ledger_code")), party_name: "x", total_items: 1, returned: 1, limit: 500, offset: 0, items: [ITEM] });
    }
    return json({}, 404);
  }));
}

function mount(href: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [href] }), context: { queryClient } });
  render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);
  return router;
}
afterEach(() => vi.unstubAllGlobals());

describe("Related Party Transactions page", () => {
  it("states that the balances are intercompany and excluded, and shows exact summary cards", async () => {
    installRelated();
    mount("/related-party");
    await screen.findByTestId("related-page", {}, T);
    expect(screen.getByTestId("related-note")).toHaveTextContent(/excluded from Creditors, Cash and the Command Center/);
    expect(screen.getByTestId("related-note")).toHaveTextContent(/eliminated on consolidation/);
    const payable = await screen.findByTestId("rp-payable", {}, T);
    expect(payable.querySelector("[data-exact]")).toHaveAttribute("data-exact", "600000000.00");
    expect(payable).toHaveTextContent("₹60.00 Cr");
    expect(screen.getByTestId("rp-debit")).toHaveTextContent("₹10.00 Cr");
    expect(screen.getByTestId("rp-net")).toHaveTextContent("₹50.00 Cr");
    expect(screen.getByTestId("rp-parties")).toHaveTextContent("1 proposed · 1 confirmed");
  });

  it("lists parties with status pills, drills to open bills with the Voucher button, and shows the reconciliation", async () => {
    installRelated();
    mount("/related-party");
    const row = await screen.findByTestId("party-111", {}, T);
    expect(within(row).getByTestId("status-confirmed")).toBeInTheDocument();
    expect(within(screen.getByTestId("party-222")).getByTestId("status-proposed")).toBeInTheDocument();
    fireEvent.click(row);
    await screen.findByTestId("bills-111", {}, T);
    expect(screen.getByTestId("bill-9001")).toBeInTheDocument();
    expect(screen.getByTestId("bill-voucher-9001")).toHaveTextContent("Voucher");
    const recon = screen.getByTestId("recon-strip");
    expect(recon).toHaveAttribute("data-ok", "true");
    expect(recon).toHaveTextContent("₹300.00 Cr");
    expect(recon).toHaveTextContent("₹360.00 Cr");
  });

  it("lists candidates as to-be-confirmed and never as excluded", async () => {
    installRelated();
    mount("/related-party");
    await screen.findByTestId("candidates", {}, T);
    expect(within(screen.getByTestId("candidates-with-balance")).getByTestId("candidate-333")).toBeInTheDocument();
    expect(screen.getByTestId("candidates")).toHaveTextContent(/NOT excluded/);
  });

  it("shows the loan balance per ledger, the by-year mirror and what the other side does not carry (full table)", async () => {
    installRelated();
    mount("/related-party");
    await screen.findByTestId("ic-cards", {}, T);
    expect(screen.getByTestId("ic-basis")).toHaveTextContent(/Full ledger history/);
    expect(screen.getByTestId("ic-loan-net")).toHaveTextContent("₹153.18 Cr".replace("153.18", "153.72"));
    expect(screen.getByTestId("ic-loan-net")).toHaveTextContent(/HoldCo ledger ₹141\.23 Cr/);
    expect(screen.getByTestId("ic-loan-mirror")).toHaveAttribute("data-ok", "true");
    expect(screen.getByTestId("fy-LOAN-FY2018")).toHaveTextContent(/one side only/);
    expect(screen.getByTestId("fy-LOAN-FY2020")).toHaveTextContent("₹6.00 Cr");
    expect(screen.getByTestId("ic-not-carried")).toHaveTextContent(/1114925831/);
    expect(screen.getByTestId("ic-not-carried")).toHaveTextContent(/not carried|Not carried/);
    expect(screen.queryByTestId("ic-reported")).toBeNull();
  });

  it("flags the unmatched service difference, explains the EBITDA effect, lists flags and candidates", async () => {
    installRelated();
    mount("/related-party");
    await screen.findByTestId("ic-service", {}, T);
    expect(screen.getByTestId("ic-service-net")).toHaveTextContent("₹40.99 Cr");
    expect(screen.getByTestId("ic-service-net")).toHaveTextContent(/unmatched \+₹1\.65 Cr/);
    expect(screen.getByTestId("ic-service-flag")).toHaveTextContent(/higher by ₹0\.33 Cr every quarter/);
    expect(screen.getByTestId("ic-effect")).toHaveTextContent(/consolidated EBITDA is unaffected/);
    expect(screen.getByTestId("ic-flags")).toHaveTextContent(/nets to nil/);
    expect(screen.getByTestId("ic-candidates")).toHaveTextContent("Vehicle Loan");
    expect(screen.queryByTestId("loans-unavailable")).toBeNull();
  });

  it("on the fallback source it says cost-tagged lines, a partial view, never a balance", async () => {
    installRelated({ ...LEDGER_LOANS, full_history: false }, undefined, false);
    mount("/related-party");
    await screen.findByTestId("ic-cards", {}, T);
    expect(screen.getByTestId("ic-basis")).toHaveTextContent(/partial view/);
    expect(screen.getByTestId("ic-loan-net")).toHaveTextContent(/partial view/);
    expect(screen.getByTestId("ic-loan-net")).toHaveTextContent("+₹46.17 Cr");
    expect(screen.getByTestId("ic-reported")).toHaveTextContent(/Reported by the ledger \(silver\)/);
  });

  it("lists every GL entry with group companies, filterable, each linking to its voucher in the right books", async () => {
    installRelated();
    mount("/related-party");
    await screen.findByTestId("gl-table", {}, T);
    expect(screen.getByTestId("rp-gl-entries")).toHaveTextContent("2,942");
    expect(screen.getByTestId("rp-gl-isd")).toHaveTextContent(/not a counterparty/);
    expect(screen.getByTestId("gl-same")).toHaveTextContent(/Same-company registration \(ISD\)/);
    const hold = screen.getByTestId("gl-open-VENTURES-E1");
    expect(hold.getAttribute("href")).toMatch(/^\/entry\?/);
    expect(hold.getAttribute("href")).toContain("entity=VENTURES");
    expect(hold.getAttribute("href")).toContain("ref=E1");
    expect(screen.getByTestId("gl-open-RETAIL-E2").getAttribute("href")).not.toContain("entity=");
    expect(screen.getByTestId("gl-bal-VENTURES-E1")).toHaveTextContent("₹141.23 Cr");
    expect(screen.getByTestId("gl-register")).toHaveTextContent("^citykart stores pvt");
    expect(screen.getByTestId("gl-ledger-mirror")).toHaveTextContent(/related_party_gl_lines/);
    expect(screen.getByTestId("gl-control")).toHaveAttribute("data-ok", "true");
    fireEvent.change(screen.getByLabelText("Matched by"), { target: { value: "party" } });
    await screen.findByTestId("gl-table", {}, T);
    const urls = (globalThis.fetch as unknown as { mock: { calls: [RequestInfo][] } }).mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("gl-entries") && u.includes("basis=party"))).toBe(true);
  });

  it("states when the loans block has no ledger list configured (not zeros)", async () => {
    installRelated({ available: false, reason: "Intercompany loan data not loaded in gold_fpa yet", tables: [], rows: [] });
    mount("/related-party");
    await screen.findByTestId("related-page", {}, T);
    await screen.findByTestId("ic-cards", {}, T);
    expect(screen.queryByTestId("loans-table")).toBeNull();
  });

  it("an API failure is shown, not papered over", async () => {
    installRelated(undefined, 401);
    mount("/related-party");
    expect(await screen.findByTestId("state-error", {}, T)).toHaveTextContent(/Finance access is required/);
  });

  it("the side nav marks Related Party as the current page", async () => {
    installRelated();
    const router = mount("/related-party");
    await screen.findByTestId("related-page", {}, T);
    expect(screen.getByTestId("nav-related")).toHaveAttribute("aria-current", "page");
    expect(router.state.location.pathname).toBe("/related-party");
  });
});

describe("the exclusion note on the Creditors page", () => {
  function installWithExcluded(withNote: boolean) {
    installCreditorsApi();
    const base = globalThis.fetch;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const res = await base(input, init);
      if (!new URL(String(input), "http://localhost").pathname.endsWith("/summary")) return res;
      const body = await res.json();
      if (withNote) body.related_party_excluded = { payable_cr: "60.9914", debit_balance_cr: "46.9367", parties: 5, items: 211 };
      return json(body);
    }));
  }

  it("shows the excluded payable with a link to /related-party", async () => {
    installWithExcluded(true);
    mount("/creditors");
    const note = await screen.findByTestId("related-excluded-note", {}, T);
    expect(note).toHaveTextContent(/Related-party balances of ₹60\.99 Cr payable are excluded/);
    expect(screen.getByTestId("related-excluded-note-link")).toHaveAttribute("href", "/related-party");
  });

  it("is hidden when the API reports no exclusion", async () => {
    installWithExcluded(false);
    mount("/creditors");
    await screen.findByTestId("exposure-strip", {}, T);
    expect(screen.queryByTestId("related-excluded-note")).toBeNull();
  });
});
