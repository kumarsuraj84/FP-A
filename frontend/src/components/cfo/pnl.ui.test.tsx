import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { installPnlApi, STORES, TOTALS } from "@/test/pnlFixture";

/* The Store P&L page runs on the real P&L API. These tests serve it a SYNTHETIC API (invented stores and round numbers). */

const T = { timeout: 5000 };

function mount(href = "/pnl") {
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
  calls = installPnlApi();
});
afterEach(() => vi.unstubAllGlobals());

describe("Store P&L: the verified strip", () => {
  it("shows the headline figures exactly as the API serves them, labelled for what they are", async () => {
    mount();
    await screen.findByTestId("pnl-strip", {}, T);
    expect(exact("strip-sales-value")).toBe(TOTALS.revenue);
    expect(exact("strip-gm-value")).toBe(TOTALS.gross_margin);
    expect(exact("strip-opex-value")).toBe(TOTALS.opex);
    expect(exact("strip-contribution-value")).toBe(TOTALS.contribution);
    expect(text("strip-sales-value")).toBe("₹1,000.00 Cr");
    expect(text("strip-growth-value")).toBe("+25.0%");
    expect(screen.getByTestId("strip-growth")).toHaveTextContent("complete months");
    const note = text("strip-note");
    expect(note).toMatch(/Contribution is before other income, finance cost and head-office allocation/);
    expect(note).toMatch(/Budget: not available \(blank\)/);
    expect(note).toMatch(/COGS runs to 06 Oct 2026, the books to 07 Oct 2026/);
    expect(note).toMatch(/Provisional \(unposted sales\): Oct 26/);
    expect(note).toMatch(/2 ledgers without a finance group are excluded/);
  });

  it("states real data and the data state, and shows no inactive Period / Compare / Scenario controls", async () => {
    mount();
    await screen.findByTestId("pnl-strip", {}, T);
    expect(screen.getByTestId("demo-banner")).toHaveAttribute("data-real", "true");
    expect(text("demo-banner")).toMatch(/Store P&L shows REAL data \(verified candidate, not live\)/);
    expect(screen.getByTestId("real-asof")).toHaveTextContent("07 Oct 2026");
    expect(screen.getByTestId("real-state")).toHaveAttribute("data-state", "verified_candidate");
    expect(screen.getByTestId("real-refresh")).toBeInTheDocument();
    for (const id of ["select-period", "select-comparison", "select-scenario"]) expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("data-state")).toHaveTextContent("REAL DATA");
  });

  it("never invents a budget: the budget is a stated gap, not a figure or a variance", async () => {
    mount();
    await screen.findByTestId("unavailable-budget", {}, T);
    const room = screen.getByTestId("pnl-room");
    expect(screen.getByTestId("unavailable-budget")).toHaveTextContent(/nothing is estimated/i);
    expect(room.textContent ?? "").not.toMatch(/vs budget|budget variance|% of budget/i);
    expect(screen.getByTestId("unavailable-hierarchy")).toHaveTextContent(/No area or zone is shown or invented/);
  });
});

describe("Store P&L: bridge, trend and lines", () => {
  it("draws the bridge from the exact API totals and states that company = stores + non-store", async () => {
    mount();
    await screen.findByTestId("pnl-waterfall", {}, T);
    expect(exact("wf-revenue")).toBe(String(Number(TOTALS.revenue) / 1e7));
    expect(exact("wf-contribution")).toBe(String(Number(TOTALS.contribution) / 1e7));
    expect(exact("wf-gross_margin")).toBe(String(Number(TOTALS.gross_margin) / 1e7));
    await screen.findByTestId("bridge-reconciles", {}, T);
    expect(text("bridge-reconciles")).toMatch(/Company = stores .* \+ head office and depots/);
  });

  it("marks the partial, provisional month and hides its margin from the line", async () => {
    mount();
    await screen.findByTestId("pnl-trend", {}, T);
    expect(screen.getByTestId("tr-2026-10")).toHaveAttribute("data-partial", "1");
    expect(screen.getByTestId("tr-2026-09")).toHaveAttribute("data-partial", "0");
    expect(screen.getByTestId("mg-2026-10")).toHaveAttribute("data-open", "1");
    expect(screen.getByTestId("mg-2026-09")).not.toHaveAttribute("data-open");
    expect(screen.getByTestId("pnl-trend")).toHaveTextContent(/hollow = costs not fully booked/);
  });

  it("lists the finance groups with their amounts and shares of sales", async () => {
    mount();
    await screen.findByTestId("pnl-lines", {}, T);
    expect(exact("line-02-Employee Cost")).toBe(String(-150 * 1e7));
    expect(screen.getByTestId("line-02-Employee Cost")).toHaveTextContent("Employee Cost");
    expect(screen.getByTestId("line-02-Employee Cost")).toHaveTextContent("−15.00%");
  });
});

describe("Store P&L: the store league and the drill", () => {
  it("ranks stores by contribution, top 10 first, then the bottom 10 in the opposite order", async () => {
    mount();
    await screen.findByTestId("league-table", {}, T);
    const rowsOf = () => screen.getAllByTestId(/^league-row-/).map((r) => r.getAttribute("data-testid"));
    expect(rowsOf()).toEqual(["league-row-10", "league-row-30", "league-row-20"]);
    expect(text("league-reconciles")).toMatch(/all stores add up to/);
    fireEvent.click(screen.getByTestId("league-bottom"));
    await waitFor(() => expect(rowsOf()[0]).toBe("league-row-20"), T);
    expect(calls.some((c) => c.includes("/stores") && c.includes("order=asc") && c.includes("limit=10"))).toBe(true);
    // the bottom view numbers the worst store last, not first
    expect(within(screen.getByTestId("league-row-20")).getAllByRole("cell")[0]).toHaveTextContent("3");
  });

  it("opens a store, then the ledgers behind a group, and says each adds up", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("league-row-10", {}, T));
    await screen.findByTestId("store-reconciles", {}, T);
    expect(text("store-reconciles")).toMatch(/add up/);
    expect(screen.getByTestId("store-panel")).toHaveTextContent("ALPHA");
    fireEvent.click(within(screen.getByTestId("store-panel")).getByTestId("line-02-Employee Cost"));
    await screen.findByTestId("ledger-reconciles", {}, T);
    expect(text("ledger-reconciles")).toMatch(/adds up to the line/);
    expect(exact("ledger-77")).toBe(String(-150 * 1e7));
    expect(calls.some((c) => c.includes("/stores/10/groups/02-Employee%20Cost/ledgers"))).toBe(true);
    fireEvent.click(screen.getByTestId("store-close"));
    await waitFor(() => expect(screen.queryByTestId("store-panel")).toBeNull(), T);
  });
});

describe("Store P&L: period, filters and basis", () => {
  it("sends the chosen filters, period and basis to the API and narrows the view", async () => {
    mount();
    await screen.findByTestId("league-table", {}, T);
    fireEvent.change(await screen.findByTestId("ctl-region"), { target: { value: "R1" } });
    await waitFor(() => expect(text("strip-stores-value")).toBe("2"), T);
    expect(calls.some((c) => c.includes("/summary") && c.includes("region=R1"))).toBe(true);
    await waitFor(() => expect(screen.getAllByTestId(/^league-row-/).length).toBe(2), T);
    fireEvent.click(screen.getByTestId("basis-posted"));
    await waitFor(() => expect(calls.some((c) => c.includes("/summary") && c.includes("basis=posted"))).toBe(true), T);
    fireEvent.change(screen.getByTestId("ctl-from"), { target: { value: "2026-07" } });
    await waitFor(() => expect(calls.some((c) => c.includes("from_month=2026-07"))).toBe(true), T);
    fireEvent.click(screen.getByTestId("ctl-clear"));
    await waitFor(() => expect(text("strip-stores-value")).toBe("3"), T);
  });

  it("lists the exclusions and gaps on the reconciliation panel, with the names Finance needs", async () => {
    mount();
    await screen.findByTestId("recon-panel", {}, T);
    await screen.findByTestId("recon-excluded", {}, T);
    expect(text("recon-tieout")).toMatch(/2 of 3 store-months agree within ₹1,000/);
    expect(text("recon-excluded")).toMatch(/1 ledgers excluded/);
    expect(text("recon-excluded")).toMatch(/Mystery Fee/);
    expect(text("recon-missing")).toMatch(/1 sites have sales in the COGS table but none in the books/);
    expect(STORES.length).toBe(3);
  });
});

describe("Store P&L: failure is shown, never papered over", () => {
  it("shows that no verified run is available when the API has none", async () => {
    vi.unstubAllGlobals();
    installPnlApi({ fail: 404 });
    mount();
    await screen.findByTestId("pnl-unavailable", {}, T);
    expect(text("pnl-unavailable")).toMatch(/No verified P&L run is available/);
    expect(screen.queryByTestId("pnl-strip")).toBeNull();
    expect(screen.getByTestId("real-state")).toHaveAttribute("data-state", "error");
  });
});
