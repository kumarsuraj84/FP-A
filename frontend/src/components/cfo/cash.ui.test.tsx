import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { FIXTURE, installCreditorsApi } from "@/test/creditorsFixture";

/* The Cash page runs on the real Cash API. These tests serve it a SYNTHETIC API (invented stores, ledgers and round numbers). */

const T = { timeout: 5000 };
const q = (path: string, params: Record<string, string> = {}) => `${path}?${new URLSearchParams({ period: "ytdfy27", compare: "budget", scenario: "normal", ...params }).toString()}`;

function mount(href: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  const history = createMemoryHistory({ initialEntries: [href] });
  const router = createRouter({ routeTree, history, context: { queryClient } });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, history };
}
const exact = (id: string) => screen.getByTestId(id).getAttribute("data-exact");
const text = (id: string) => screen.getByTestId(id).textContent ?? "";

let calls: string[] = [];
beforeEach(() => {
  calls = installCreditorsApi();
});
afterEach(() => vi.unstubAllGlobals());

describe("Liquidity & Working Capital Control: the verified strip", () => {
  it("shows exactly the four verified figures, from exact API values, labelled for what they are", async () => {
    mount(q("/cash"));
    await screen.findByTestId("cash-strip", {}, T);
    const strip = screen.getByTestId("cash-strip");
    for (const label of ["Store Till Cash", "Credit Outstanding", "Past Due Creditors", "Creditor Debit Balances"]) expect(strip).toHaveTextContent(label);
    expect(screen.getByTestId("strip-till")).toHaveTextContent("excludes bank balances");
    expect(exact("strip-till-value")).toBe("3000000.0000");
    expect(text("strip-till-value")).toBe("₹0.30 Cr");
    expect(exact("strip-credit-value")).toBe(FIXTURE.credit);
    expect(exact("strip-pastdue-value")).toBe(FIXTURE.pastDue);
    expect(exact("strip-debit-value")).toBe(FIXTURE.debit);
    expect(screen.getByTestId("strip-note")).toHaveTextContent("Bank position not yet included.");
    expect(screen.getByTestId("strip-note")).toHaveTextContent(/not a cash position and are not added together/);
  });

  it("never offers a cash position, a forecast or a 7/15/30-day horizon", async () => {
    mount(q("/cash"));
    await screen.findByTestId("cash-strip", {}, T);
    const room = screen.getByTestId("cash-room");
    for (const phrase of [/Cash today/i, /Cash in 7/i, /Cash in 15/i, /Cash in 30/i, /Cash Available/i, /Operating minimum/i, /above minimum/i, /projected cash/i]) {
      expect(room.textContent ?? "", String(phrase)).not.toMatch(phrase);
    }
    expect(room.querySelector('[data-testid="cash-chart"], [data-testid="cash-minimum"], [data-testid^="step-"]')).toBeNull();
    expect(screen.getByTestId("unavailable-cash_forecast")).toHaveTextContent(/none is estimated/i);
  });

  it("states the data state and the real-data banner; Command Center stays demo", async () => {
    mount(q("/cash"));
    const badge = await screen.findByTestId("data-state", {}, T);
    expect(badge).toHaveAttribute("data-state", "verified_candidate");
    expect(badge).toHaveTextContent(/REAL DATA/);
    expect(screen.getByTestId("demo-banner")).toHaveTextContent(/Liquidity shows REAL data/);
    expect(screen.getByTestId("demo-banner")).toHaveTextContent(/Command Center and Profitability are still demo data/);
  });
});

describe("Liquidity & Working Capital Control: Store Till Cash and creditors", () => {
  it("lists stores by till cash and pages in more", async () => {
    mount(q("/cash"));
    const table = await screen.findByTestId("till-table", {}, T);
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBe(16), T); // header + 15
    expect(table).toHaveTextContent("Test Store 01");
    expect(screen.getByTestId("till-panel")).toHaveTextContent(/excludes bank balances/);
    fireEvent.click(screen.getByTestId("till-more"));
    await waitFor(() => expect(within(screen.getByTestId("till-table")).getAllByRole("row").length).toBe(25), T);
    expect(calls.some((c) => c.includes("store-till") && c.includes("limit=65"))).toBe(true);
  });

  it("shows creditor obligations by Due Status from the creditors figures, with the run and a link to the Creditors page", async () => {
    const m = mount(q("/cash"));
    const panel = await screen.findByTestId("creditors-panel", {}, T);
    expect(panel).toHaveTextContent(/run_test_001/);
    expect(panel).toHaveTextContent(/verified candidate, not live/);
    expect(panel).toHaveTextContent(/Creditor debit balances .* separate and not netted/);
    expect(screen.getByTestId("obligation-past_due").querySelector("[data-exact]")?.getAttribute("data-exact")).toBe(FIXTURE.pastDue);
    fireEvent.click(screen.getByTestId("open-creditors"));
    await screen.findByTestId("creditors-room", {}, T);
    expect(m.router.state.location.pathname).toBe("/creditors");
  });

  it("when the creditors figures are unavailable the page says so, never zero", async () => {
    vi.unstubAllGlobals();
    installCreditorsApi({ noCreditors: true });
    mount(q("/cash"));
    await screen.findByTestId("cash-strip", {}, T);
    expect(screen.getByTestId("strip-credit-value")).toHaveTextContent("—");
    expect(screen.getByTestId("creditors-panel")).toHaveTextContent(/not available/i);
    expect(screen.getByTestId("cash-strip")).not.toHaveTextContent("₹0.00 Cr");
  });
});

describe("Liquidity & Working Capital Control: the Finance review card", () => {
  it("segregates the bank ledger-book position, labelled PROVISIONAL · NOT BANK-RECONCILED, with all four figures", async () => {
    mount(q("/cash"));
    const card = await screen.findByTestId("bank-card", {}, T);
    expect(within(card).getByTestId("bank-status")).toHaveTextContent("PROVISIONAL · NOT BANK-RECONCILED");
    expect(card).toHaveTextContent(/Finance review/);
    for (const label of ["Opening balance", "Posted closing", "Unposted movement", "Indicative incl. unposted"]) expect(card).toHaveTextContent(label);
    expect(exact("bank-posted-value")).toBe("-823000000.0000".replace("-823000000", String(-830000000 + 7000000 + 190000)) );
    expect(Number(exact("bank-indicative-value"))).toBe(Number(exact("bank-posted-value")) + Number(exact("bank-unposted-value")));
    expect(text("bank-posted-value")).toMatch(/^−₹/); // a negative figure is shown as negative, not hidden
    expect(screen.getByTestId("bank-note")).toHaveTextContent(/Not bank-reconciled/);
    expect(screen.getByTestId("bank-note")).toHaveTextContent(/Not added to Store Till Cash, and no liquidity, headroom or coverage is derived/);
  });

  it("names the driver of the negative posted balance and does not guess why", async () => {
    mount(q("/cash"));
    const d = await screen.findByTestId("bank-driver", {}, T);
    expect(d).toHaveTextContent("TEST BANK ALPHA");
    expect(d).toHaveTextContent(/drives the negative posted balance/);
    expect(d).toHaveTextContent(/cannot be told from the books alone/);
  });

  it("is kept out of the verified strip and out of Store Till Cash", async () => {
    mount(q("/cash"));
    await screen.findByTestId("bank-card", {}, T);
    const strip = screen.getByTestId("cash-strip");
    expect(strip.querySelector('[data-testid="bank-card"]')).toBeNull();
    expect(strip).not.toHaveTextContent(/bank ledger|posted closing/i);
    expect(Number(exact("strip-till-value"))).toBe(3000000); // till cash is the stores' tills only
  });

  it("lists the ledgers with movement, most negative first, with last posted dates", async () => {
    mount(q("/cash"));
    const table = await screen.findByTestId("bank-table", {}, T);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("TEST BANK ALPHA");
    expect(rows[0]).toHaveTextContent(/30 Sep/);
    expect(screen.getByTestId("bank-note")).toHaveTextContent(/3 of 5 bank and cash ledgers have entries; 2 have none/);
  });
});

describe("Liquidity & Working Capital Control: unavailable, states and failures", () => {
  it("lists every unavailable component with its reason and a dash, never a number", async () => {
    mount(q("/cash"));
    await screen.findByTestId("unavailable-panel", {}, T);
    for (const id of ["bank_reconciled_cash", "consolidated_cash", "cash_forecast", "inventory", "receivables", "vendor_advances", "payroll", "statutory", "capex"]) {
      const row = screen.getByTestId(`unavailable-${id}`);
      expect(row).toHaveTextContent("—");
      expect(row).not.toHaveTextContent("₹");
    }
  });

  it("an API failure is shown as an error with Retry, never as zeros", async () => {
    vi.unstubAllGlobals();
    installCreditorsApi({ fail: 500 });
    mount(q("/cash"));
    expect(await screen.findByTestId("state-error", {}, T)).toBeInTheDocument();
    expect(screen.getByTestId("cash-room")).not.toHaveTextContent("₹0.00 Cr");
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("when no verified cash run exists the page says so", async () => {
    vi.unstubAllGlobals();
    installCreditorsApi({ noCash: true });
    mount(q("/cash"));
    expect(await screen.findByTestId("state-error", {}, T)).toHaveTextContent(/No verified cash run is available/);
  });

  it("a live run is stated as Live: the API decides", async () => {
    vi.unstubAllGlobals();
    installCreditorsApi({ state: "live" });
    mount(q("/cash"));
    expect(await screen.findByTestId("data-state", {}, T)).toHaveAttribute("data-state", "live");
  });
});
