import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { installExpensesApi } from "@/test/expensesFixture";
import { entryHref, ledgerListHref, parseEntrySearch, parseListSearch } from "@/lib/entryLinks";
import { defaultPeriod, resolvePeriod, validateExpSearch } from "./expenses/expensesUrl";

/* The Store / DC Expense pages run on the real /api/v1/mgmt/expenses API. These tests serve them a SYNTHETIC API (test/expensesFixture.ts). */

const T = { timeout: 5000 };

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
const text = (id: string) => screen.getByTestId(id).textContent ?? "";
const exact = (id: string) => screen.getByTestId(id).getAttribute("data-exact");

afterEach(() => vi.unstubAllGlobals());

describe("Store Expenses page", () => {
  it("shows the MIS heads for the period with the Aug-26 store figures and the MIS labels", async () => {
    const calls = installExpensesApi();
    mount("/mgmt/store-expenses?from=2026-08&to=2026-08");
    await screen.findByTestId("exp-heads-table", {}, T);
    const table = screen.getByTestId("exp-heads-table");
    for (const l of ["Rent", "Employee Cost", "Power and Fuel", "Advertisement", "Freight Forwarding", "Other expenses", "Store expenses"]) expect(table).toHaveTextContent(l);
    expect(text("head-rent-value")).toBe("6.90");
    expect(text("head-employee_cost-value")).toBe("9.42");
    expect(text("head-power_fuel-value")).toBe("5.24");
    expect(text("head-advertisement-value")).toBe("1.29");
    expect(text("head-freight-value")).toBe("1.99");
    expect(text("head-other_expenses-value")).toBe("1.06");
    // the API is asked for the store scope, SubCo only, the chosen month
    const sum = calls.find((c) => c.includes("expenses/summary"))!;
    expect(sum).toContain("scope=store");
    expect(sum).toContain("entity=subco");
    expect(sum).toContain("from_month=2026-08");
    expect(screen.getByTestId("exp-entity-note")).toHaveTextContent(/Stores belong to SubCo only/);
    expect(screen.getByTestId("mgmt-tab-store-exp")).toHaveAttribute("aria-current", "page");
  });

  it("toggles Book / Adjustment / Total and marks the heads that carry an adjustment", async () => {
    installExpensesApi();
    mount("/mgmt/store-expenses?from=2026-08&to=2026-08");
    await screen.findByTestId("exp-heads-table", {}, T);
    expect(screen.getByTestId("exp-heads-table")).toHaveAttribute("data-mode", "total");
    expect(screen.getByTestId("head-employee_cost-value")).toHaveAttribute("data-adjusted", "true");
    expect(screen.getByTestId("head-rent-value")).toHaveAttribute("data-adjusted", "false");
    fireEvent.click(screen.getByTestId("exp-mode-book"));
    await waitFor(() => expect(screen.getByTestId("exp-heads-table")).toHaveAttribute("data-mode", "book"), T);
    expect(text("head-employee_cost-value")).toBe("9.17");
    fireEvent.click(screen.getByTestId("exp-mode-adjustment"));
    await waitFor(() => expect(text("head-employee_cost-value")).toBe("0.25"), T);
    expect(text("head-rent-value")).toBe("0.00");
    fireEvent.click(screen.getByTestId("exp-mode-total"));
    await waitFor(() => expect(text("head-employee_cost-value")).toBe("9.42"), T);
  });

  it("shows the KPI strip: total, % of net sales, vs last year and month on month", async () => {
    installExpensesApi();
    mount("/mgmt/store-expenses?from=2026-08&to=2026-08");
    await screen.findByTestId("exp-kpis", {}, T);
    expect(text("kpi-total-value")).toBe("25.91 Cr");
    expect(text("kpi-pct-value")).toBe("20.3%");
    expect(text("kpi-ly-value")).not.toBe("—");
    expect(text("kpi-mom-value")).not.toBe("—");
    expect(screen.getByTestId("exp-controls-badge")).toHaveAttribute("data-ok", "true");
    expect(screen.getByTestId("exp-controls-badge")).toHaveTextContent("Store + DC + HO = Management P&L");
    expect(screen.getByTestId("exp-notes")).toHaveTextContent(/Management adjustments in the period/);
  });

  it("keeps the view in the address: month range, mode and the open head", async () => {
    const calls = installExpensesApi();
    const { router } = mount("/mgmt/store-expenses?from=2026-05&to=2026-07&mode=book");
    await screen.findByTestId("exp-heads-table", {}, T);
    expect(screen.getByTestId("exp-mode-book")).toHaveAttribute("aria-pressed", "true");
    expect(calls.some((c) => c.includes("expenses/summary") && c.includes("from_month=2026-05") && c.includes("to_month=2026-07"))).toBe(true);
    fireEvent.click(screen.getByTestId("open-head-rent"));
    await screen.findByTestId("exp-drill", {}, T);
    expect(router.state.location.search).toMatchObject({ head: "rent", from: "2026-05", to: "2026-07", mode: "book" });
  });

  it("defaults to FY year-to-date", async () => {
    const calls = installExpensesApi();
    mount("/mgmt/store-expenses");
    await screen.findByTestId("exp-heads-table", {}, T);
    expect(calls.find((c) => c.includes("expenses/summary"))).toContain("from_month=2026-04");
    expect(calls.find((c) => c.includes("expenses/summary"))).toContain("to_month=2026-08");
  });
});

describe("The drill to the last leg", () => {
  it("head -> ledgers -> sites -> vouchers link with the way back in the trail", async () => {
    installExpensesApi();
    const { history } = mount("/mgmt/store-expenses?from=2026-04&to=2026-08");
    await screen.findByTestId("exp-heads-table", {}, T);
    fireEvent.click(screen.getByTestId("open-head-rent"));
    const drill = await screen.findByTestId("exp-drill", {}, T);
    await within(drill).findByTestId("exp-drill-row-1000000002", {}, T);
    expect(drill).toHaveTextContent("Rent: the ledgers behind this head");
    expect(screen.getByTestId("exp-drill-reconciles")).toHaveAttribute("data-ok", "true");
    expect(exact("exp-drill-total")).toBe("6.8983");
    // ledger -> sites
    fireEvent.click(screen.getByTestId("exp-by-site-1000000002"));
    await screen.findByTestId("exp-drill-row-SUBCO:5", {}, T);
    expect(screen.getByTestId("exp-drill")).toHaveTextContent("Sites posting ledger 1000000002");
    // site -> vouchers: a real link to /entry/list with the site, ledger, period and the trail back to this drill
    const link = screen.getByTestId("exp-vouchers-1000000002-5") as HTMLAnchorElement;
    const url = new URL(link.getAttribute("href")!, "http://x");
    expect(url.pathname).toBe("/entry/list");
    expect(url.searchParams.get("site")).toBe("5");
    expect(url.searchParams.get("glcode")).toBe("1000000002");
    expect(url.searchParams.get("from_month")).toBe("2026-04");
    expect(url.searchParams.get("to_month")).toBe("2026-08");
    expect(url.searchParams.get("entity")).toBeNull(); // SubCo = the default RETAIL list
    const trail = JSON.parse(url.searchParams.get("trail")!);
    expect(trail).toHaveLength(1);
    expect(trail[0].l).toContain("Store Expenses");
    expect(trail[0].h).toContain("/mgmt/store-expenses");
    expect(trail[0].h).toContain("head=rent");
    expect(trail[0].h).toContain("gl=1000000002");
    fireEvent.click(link);
    await waitFor(() => expect(history.location.pathname).toBe("/entry/list"), T);
  });

  it("a site row opens the ledgers at that site, with the allocated adjustment and a reconciling total", async () => {
    installExpensesApi();
    mount("/mgmt/store-expenses?from=2026-04&to=2026-08");
    await screen.findByTestId("sites-table", {}, T);
    fireEvent.click(screen.getByTestId("open-site-SUBCO:5"));
    const drill = await screen.findByTestId("exp-drill", {}, T);
    await within(drill).findByTestId("exp-drill-row-1000000002", {}, T);
    expect(drill).toHaveTextContent("Ledgers at ALC");
    expect(screen.getByTestId("exp-adj-allocated")).toBeInTheDocument();
    expect(screen.getByTestId("exp-vouchers-1000000052-5")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("exp-drill-close"));
    await waitFor(() => expect(screen.queryByTestId("exp-drill")).toBeNull(), T);
  });
});

describe("Sites table", () => {
  it("ranks stores, searches, filters by flag and sorts", async () => {
    installExpensesApi();
    mount("/mgmt/store-expenses?from=2026-04&to=2026-08");
    await screen.findByTestId("sites-table", {}, T);
    const order = () => [...screen.getByTestId("sites-table").querySelectorAll("tbody tr[data-testid^='site-']")].map((r) => r.getAttribute("data-testid"));
    expect(order()).toEqual(["site-SUBCO:5", "site-SUBCO:3", "site-SUBCO:401"]); // expense, highest first
    expect(order()).toHaveLength(3);
    // flags: NSO TY, above peers, MoM jump
    expect(screen.getByTestId("site-SUBCO:401")).toHaveAttribute("data-flags", expect.stringContaining("nso_ty"));
    fireEvent.change(screen.getByTestId("sites-flag"), { target: { value: "above_peer" } });
    expect(order()).toEqual(["site-SUBCO:5"]);
    fireEvent.change(screen.getByTestId("sites-flag"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("sites-search"), { target: { value: "lad" } });
    expect(order()).toEqual(["site-SUBCO:3"]);
    fireEvent.change(screen.getByTestId("sites-search"), { target: { value: "nothing" } });
    expect(screen.getByTestId("sites-empty")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("sites-search"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("sites-sort-name"));
    expect(order()).toEqual(["site-SUBCO:5", "site-SUBCO:3", "site-SUBCO:401"]); // ALC, LAD, NEW
    fireEvent.click(screen.getByTestId("sites-sort-name"));
    expect(order()).toEqual(["site-SUBCO:401", "site-SUBCO:3", "site-SUBCO:5"]);
    // a store without area shows a dash with the reason in the title, never a zero
    const cells = screen.getByTestId("site-SUBCO:401").querySelectorAll("td");
    expect([...cells].some((c) => c.textContent === "—" && (c.getAttribute("title") ?? "").length > 10)).toBe(true);
    expect(screen.getByTestId("sites-peer")).toHaveTextContent("Peer median 19.0% of net sales");
    expect(screen.getByTestId("sites-reconciles")).toHaveAttribute("data-ok", "true");
  });
});

describe("Exceptions", () => {
  it("lists the exceptions with the rule text and filters by rule", async () => {
    installExpensesApi();
    mount("/mgmt/store-expenses?from=2026-04&to=2026-08");
    await screen.findByTestId("exc-table", {}, T);
    expect(screen.getAllByTestId("exc-row")).toHaveLength(3);
    expect(screen.getByTestId("exc-rule-text")).toHaveTextContent("95th percentile of the stores that book that ledger");
    fireEvent.click(screen.getByTestId("exc-rule-DUPLICATE_BOOKING"));
    expect(screen.getAllByTestId("exc-row")).toHaveLength(1);
    expect(screen.getByTestId("exc-rule-text")).not.toHaveTextContent("95th percentile");
    // the duplicate narrows the voucher list to its month
    const link = screen.getByTestId("exc-vouchers-DUPLICATE_BOOKING-312-151-2026-07") as HTMLAnchorElement;
    const url = new URL(link.getAttribute("href")!, "http://x");
    expect(url.searchParams.get("from_month")).toBe("2026-07");
    expect(url.searchParams.get("to_month")).toBe("2026-07");
    expect(url.searchParams.get("glcode")).toBe("151");
  });
});

describe("DC Expenses page", () => {
  it("offers SubCo / HoldCo / Consolidated and asks the API for the chosen entity", async () => {
    const calls = installExpensesApi();
    mount("/mgmt/dc-expenses?from=2026-08&to=2026-08");
    await screen.findByTestId("exp-heads-table", {}, T);
    expect(screen.getByTestId("exp-entity")).toHaveAttribute("data-entity", "consolidated");
    expect(screen.getByTestId("mgmt-tab-dc-exp")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("exp-heads")).toHaveTextContent("DC cost by head");
    expect(text("head-total-value")).toBe("2.22");
    expect(screen.getByTestId("kpi-pct")).toHaveTextContent("Per DC site");
    fireEvent.click(screen.getByTestId("exp-entity-holdco"));
    await waitFor(() => expect(screen.getByTestId("exp-entity")).toHaveAttribute("data-entity", "holdco"), T);
    await waitFor(() => expect(calls.some((c) => c.includes("expenses/summary") && c.includes("entity=holdco") && c.includes("scope=dc"))).toBe(true), T);
    await waitFor(() => expect(text("head-total-value")).toBe("1.38"), T);
    // the site list now holds the HoldCo warehouse only, and its vouchers are the VENTURES ones
    await waitFor(() => expect(screen.queryByTestId("site-SUBCO:123")).toBeNull(), T);
    fireEvent.click(screen.getByTestId("open-site-HOLDCO:3"));
    const drill = await screen.findByTestId("exp-drill", {}, T);
    await within(drill).findByTestId("exp-drill-row-1000000002", {}, T);
    const link = screen.getByTestId("exp-vouchers-1000000002-3") as HTMLAnchorElement;
    expect(new URL(link.getAttribute("href")!, "http://x").searchParams.get("entity")).toBe("VENTURES");
    expect(calls.some((c) => c.includes("expenses/ledgers") && c.includes("site_entity=holdco") && c.includes("site=3"))).toBe(true);
  });
});

describe("States and navigation", () => {
  it("says so when the API is down, instead of a number", async () => {
    installExpensesApi({ fail: 500 });
    mount("/mgmt/store-expenses");
    await screen.findByTestId("state-error", {}, T);
    expect(screen.queryByTestId("exp-heads-table")).toBeNull();
  });

  it("puts Store Expenses and DC Expenses in the side navigation, each highlighted on its own page", async () => {
    installExpensesApi();
    mount("/mgmt/dc-expenses");
    await screen.findByTestId("exp-heads-table", {}, T);
    expect(screen.getByTestId("nav-store-expenses")).toHaveAttribute("href", expect.stringContaining("/mgmt/store-expenses"));
    expect(screen.getByTestId("nav-dc-expenses")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("nav-mgmt")).not.toHaveAttribute("aria-current");
  });
});

describe("URL state helpers", () => {
  it("drops what it does not understand and resolves the period", () => {
    expect(validateExpSearch({ entity: "bogus", from: "2026-13", to: "2026-08", mode: "x", head: "Rent!", site: "5", se: "HOLDCO" })).toEqual({ to: "2026-08", site: 5, se: "HOLDCO" });
    const months = ["2025-12", "2026-01", "2026-04", "2026-05", "2026-08"];
    expect(defaultPeriod(months)).toEqual({ from: "2026-04", to: "2026-08" });
    expect(defaultPeriod(["2026-01", "2026-02"])).toEqual({ from: "2026-01", to: "2026-02" }); // FY started the April before the data
    expect(resolvePeriod(months, { from: "2026-08", to: "2026-05" })).toEqual({ from: "2026-05", to: "2026-05" });
    expect(resolvePeriod(months, { from: "1999-01" })).toEqual({ from: "2026-04", to: "2026-08" });
  });

  it("carries the HoldCo entity through the voucher links and reads it back; the default stays RETAIL", () => {
    const list = ledgerListHref({ site: "3", glcode: "1242", from_month: "2026-08", to_month: "2026-08", entity: "VENTURES" });
    expect(parseListSearch(Object.fromEntries(new URL(list, "http://x").searchParams))).toMatchObject({ site: "3", glcode: "1242", entity: "VENTURES" });
    expect(ledgerListHref({ site: "3", glcode: "1242" })).not.toContain("entity");
    const e = entryHref("V1", [], undefined, "VENTURES");
    expect(parseEntrySearch(Object.fromEntries(new URL(e, "http://x").searchParams))).toMatchObject({ ref: "V1", entity: "VENTURES" });
    expect(entryHref("V1")).toBe("/entry?ref=V1");
    expect(parseEntrySearch({ ref: "V1", entity: "RETAIL" }).entity).toBeUndefined();
  });
});
