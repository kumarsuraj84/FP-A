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

function installRelated(loans: unknown = NOT_LOADED, fail?: number) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    if (!url.pathname.startsWith("/related-api/")) return json({}, 404);
    if (fail) return json({ detail: "x" }, fail);
    if (url.pathname === "/related-api/summary") return json(SUMMARY(loans));
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

  it("says loans are not loaded (never zeros) when the table is absent", async () => {
    installRelated();
    mount("/related-party");
    await screen.findByTestId("loans-unavailable", {}, T);
    expect(screen.getByTestId("loans-unavailable")).toHaveTextContent("Intercompany loan data not loaded in gold_fpa yet");
    expect(screen.queryByTestId("loans-table")).toBeNull();
  });

  it("shows loan rows generically when available", async () => {
    installRelated({ available: true, reason: null, tables: [{ table: "intercompany_loan", returned: 1, columns: ["lender", "amount"] }], rows: [{ _table: "intercompany_loan", lender: "HoldCo", amount: "5.00" }] });
    mount("/related-party");
    const t = await screen.findByTestId("loans-table", {}, T);
    expect(t).toHaveTextContent("HoldCo");
    expect(t).toHaveTextContent("5.00");
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
