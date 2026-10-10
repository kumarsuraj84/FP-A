import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { installPnlApi, STORES, TOTALS } from "@/test/pnlFixture";

/* The Store P&L page runs on the real P&L API. These tests serve it a SYNTHETIC API (invented stores and round numbers). */

const T = { timeout: 5000 };

function mount(href = "/profitability") {
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
async function mountTab(tab: string) {
  mount();
  await screen.findByTestId("pnl-strip", {}, T);
  fireEvent.click(screen.getByTestId(`tab-${tab}`));
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
    expect(note).toMatch(/Books basis, before management adjustments; see Management P&L/);
    expect(note).toMatch(/Store EBITDA is Material Margin less Store Expenses \(STORES location only\), before DC cost, HO cost, interest income and finance cost/);
    expect(note).toMatch(/AOP: not available \(blank\)/);
    expect(note).toMatch(/Material Cost runs to 06 Oct 2026, the books to 07 Oct 2026/);
    // the MIS names, not the old ones
    expect(text("pnl-strip")).toMatch(/Revenue from operations/);
    expect(text("strip-gm")).toMatch(/Material Margin/);
    expect(text("strip-opex")).toMatch(/Store Expenses/);
    expect(text("strip-contribution")).toMatch(/Store EBITDA/);
    expect(text("strip-corporate")).toMatch(/Corporate EBITDA/);
    expect(text("strip-growth")).toMatch(/Y-o-Y Growth vs LY/);
    expect(text("strip-note")).toMatch(/AOP/);
    expect(text("pnl-strip")).not.toMatch(/Net sales|Gross margin|Store opex|Contribution/);
    expect(note).toMatch(/Provisional \(unposted sales\): Oct 26/);
    expect(note).toMatch(/2 ledgers are Unmapped \/ Finance classification required/);
  });

  it("states real data and the data state, and shows no inactive Period / Compare / Scenario controls", async () => {
    mount();
    await screen.findByTestId("pnl-strip", {}, T);
    expect(screen.getByTestId("demo-banner")).toHaveAttribute("data-real", "true");
    expect(text("demo-banner")).toMatch(/Profitability shows REAL data \(verified candidate, not live\)/);
    expect(text("demo-banner")).toMatch(/Command Center is still demo data and waits for a synchronized run/);
    expect(screen.getByTestId("real-asof")).toHaveTextContent("07 Oct 2026");
    expect(screen.getByTestId("real-state")).toHaveAttribute("data-state", "verified_candidate");
    expect(screen.getByTestId("real-refresh")).toBeInTheDocument();
    for (const id of ["select-period", "select-comparison", "select-scenario"]) expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("data-state")).toHaveTextContent(/Verified candidate/);
  });

  it("never invents a budget: the budget is a stated gap, not a figure or a variance", async () => {
    mount();
    await screen.findByTestId("unavailable-budget", {}, T);
    await screen.findByTestId("strip-note", {}, T);
    expect(screen.queryByTestId("strip-budget")).toBeNull();                                // no empty AOP tile: it is in the note and the data-status list
    expect(text("strip-note")).toMatch(/AOP/);
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
    expect(text("bridge-reconciles")).toMatch(/Company Store EBITDA = stores .* \+ virtual and other non-store sites/);
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
    await mountTab("stores");
    await screen.findByTestId("league-table", {}, T);
    const rowsOf = () => screen.getAllByTestId(/^league-row-/).map((r) => r.getAttribute("data-testid"));
    expect(rowsOf()).toEqual(["league-row-10", "league-row-30", "league-row-20"]);
    expect(text("league-reconciles")).toMatch(/all stores add up to/);
    fireEvent.click(screen.getByTestId("league-bottom"));
    await waitFor(() => expect(rowsOf()[0]).toBe("league-row-20"), T);
    expect(calls.some((c) => c.includes("/stores") && c.includes("order=asc") && c.includes("limit=10"))).toBe(true);
    expect(within(screen.getByTestId("league-row-20")).getAllByRole("cell")[0]).toHaveTextContent("1");   // rank 1 of this view: the weakest store
  });

  it("opens a store, then the ledgers behind a group, and says each adds up", async () => {
    await mountTab("stores");
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

describe("Profitability: the CFO league views", () => {
  const tabs = ["top", "bottom", "gm_high", "gm_low", "opex_high", "grow_fast", "grow_down", "all"];
  it("offers top and bottom 4-Wall EBITDA, highest and lowest GM %, highest store expenses %, fastest growth and biggest decline", async () => {
    await mountTab("stores");
    await screen.findByTestId("league-table", {}, T);
    for (const t of tabs) expect(screen.getByTestId(`league-${t}`)).toBeInTheDocument();
    expect(screen.getByTestId("league-tabs")).toHaveTextContent(/Top 4-Wall EBITDA.*Bottom 4-Wall EBITDA.*Highest GM %.*Lowest GM %.*Highest store expenses %.*Fastest growth.*Biggest decline/);
  });

  it("each view asks the API for the right ranking, and percentage and growth rankings apply a small-store floor", async () => {
    await mountTab("stores");
    await screen.findByTestId("league-table", {}, T);
    const last = () => calls.filter((c) => c.includes("/stores?")).at(-1) ?? "";
    for (const [tab, sort, order] of [["gm_high", "gross_margin_pct", "desc"], ["gm_low", "gross_margin_pct", "asc"], ["opex_high", "opex_pct", "desc"], ["grow_fast", "growth", "desc"], ["grow_down", "growth", "asc"]]) {
      fireEvent.click(screen.getByTestId(`league-${tab}`));
      await waitFor(() => expect(last()).toContain(`sort=${sort}`), T);
      expect(last()).toContain(`order=${order}`);
      expect(last()).toContain("min_revenue=10000000");                         // the default floor: ₹1 Cr of net sales
      expect(screen.getByTestId("league-floor")).toBeInTheDocument();
    }
    fireEvent.click(screen.getByTestId("league-top"));
    await waitFor(() => expect(screen.getByTestId("league-table")).toHaveAttribute("data-view", "top"), T);
    expect(screen.queryByTestId("league-floor")).toBeNull();                    // an absolute ranking needs no floor
  });

  it("puts stores with no comparable last year last in a growth ranking, never first", async () => {
    await mountTab("stores");
    await screen.findByTestId("league-table", {}, T);
    fireEvent.click(screen.getByTestId("league-grow_down"));
    await waitFor(() => expect(screen.getAllByTestId(/^league-row-/).map((r) => r.getAttribute("data-testid"))).toEqual(["league-row-30", "league-row-10", "league-row-20"]), T);   // -3.0%, +12.5%, then the store with no last year
  });
});

describe("Profitability: growth × contribution margin", () => {
  it("plots stores against the view's own growth and margin, names the quadrants, and says how many are not plotted", async () => {
    mount();
    await screen.findByTestId("pnl-quadrant", {}, T);
    for (const id of ["strong", "scale", "mature", "turnaround"]) expect(screen.getByTestId(`quad-${id}`)).toBeInTheDocument();
    // like-for-like reference of the two plotted stores: growth = (100 x 1.125 + 93 x 0.97) / 193 - 1 = 5.03%, margin = (30 + 18) / (120 + 90) = 22.86%
    expect(Number(screen.getByTestId("ref-growth").getAttribute("data-value"))).toBeCloseTo(5.0311, 3);
    expect(Number(screen.getByTestId("ref-margin").getAttribute("data-value"))).toBeCloseTo(22.8571, 3);
    expect(screen.getByTestId("dot-10")).toHaveAttribute("data-quad", "strong");                 // 12.5% growth above 5.03%, 25% margin above 22.86%
    expect(screen.getByTestId("dot-30")).toHaveAttribute("data-quad", "turnaround");             // -3% growth below, 20% margin below
    expect(screen.queryByTestId("dot-20")).toBeNull();                                           // a new store has no comparable last year
    expect(screen.getByTestId("quadrant-unplotted")).toHaveTextContent("1 stores are not plotted");
    expect(screen.getByTestId("quad-strong")).toHaveAttribute("data-count", "1");
    expect(screen.getByTestId("quad-turnaround")).toHaveAttribute("data-count", "1");
    expect(screen.getByTestId("quad-mature")).toHaveAttribute("data-count", "0");
  });

  it("opens the store when its dot is clicked", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("dot-10", {}, T));
    await screen.findByTestId("store-reconciles", {}, T);
    expect(screen.getByTestId("store-panel")).toHaveTextContent("ALPHA");
  });
});

describe("Store P&L: period, filters and basis", () => {
  it("sends the chosen filters, period and basis to the API and narrows the view", async () => {
    await mountTab("stores");
    await screen.findByTestId("league-table", {}, T);
    fireEvent.change(await screen.findByTestId("ctl-region"), { target: { value: "R1" } });
    await waitFor(() => expect(text("strip-stores-value")).toBe("2"), T);
    expect(calls.some((c) => c.includes("/summary") && c.includes("region=R1"))).toBe(true);
    await waitFor(() => expect(screen.getAllByTestId(/^league-row-/).length).toBe(2), T);
    fireEvent.click(screen.getByTestId("basis-posted"));
    await waitFor(() => expect(calls.some((c) => c.includes("/summary") && c.includes("basis=posted"))).toBe(true), T);
    fireEvent.change(screen.getByTestId("ctl-from"), { target: { value: "2026-07" } });
    await waitFor(() => expect(calls.some((c) => c.includes("from_month=2026-07"))).toBe(true), T);
    await waitFor(() => expect(text("strip-stores-value")).toBe("3"), T);
  });

  it("lists the exclusions and gaps on the reconciliation panel, with the names Finance needs", async () => {
    await mountTab("quality");
    await screen.findByTestId("recon-panel", {}, T);
    await screen.findByTestId("recon-excluded", {}, T);
    expect(text("recon-tieout")).toMatch(/2 of 3 store-months agree within ₹1,000/);
    expect(text("recon-excluded")).toMatch(/Unmapped \/ Finance classification required: 1 ledgers in this period \(3 across the run/);
    expect(text("recon-excluded")).toMatch(/None is assigned automatically/);
    expect(text("recon-excluded")).toMatch(/Mystery Fee/);
    expect(text("recon-missing")).toMatch(/1 sites have sales in the Material Cost table but none in the books/);
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

describe("P&L Review: tabs", () => {
  const open = async (tab: string) => {
    mount();
    await screen.findByTestId("pnl-strip", {}, T);
    fireEvent.click(screen.getByTestId(`tab-${tab}`));
  };

  it("has the nine review tabs", async () => {
    mount();
    await screen.findByTestId("pnl-strip", {}, T);
    for (const id of ["overview", "pivot", "comparison", "stores", "heatmap", "expense-exceptions", "revenue-exceptions", "peers", "quality"]) expect(screen.getByTestId(`tab-${id}`)).toBeInTheDocument();
  });

  it("pivot: shows the exact cells, a day-aligned last-year YTD, and expands a group to its ledgers", async () => {
    await open("pivot");
    await screen.findByTestId("pivot-table", {}, T);
    expect(screen.getByTestId("pv-revenue-ytd").getAttribute("data-exact")).toBe(String(240 * 1e7));
    expect(screen.getByTestId("pv-col-ytd")).toBeInTheDocument();
    expect(text("pivot-note")).toMatch(/day aligned/i);
    expect(text("pivot-note")).toMatch(/Unmapped \/ Finance classification required/);
    fireEvent.click(screen.getByTestId("pv-row-g:02-Employee Cost"));
    await screen.findByTestId("pv-ledger-77", {}, T);
    fireEvent.click(screen.getByTestId("mode-company"));
    await waitFor(() => expect(calls.some((c) => c.includes("pivot") && c.includes("mode=company"))).toBe(true), T);
  });

  it("MTD / QTD / YTD: three windows compared day aligned, never against a whole last-year month", async () => {
    await open("comparison");
    await screen.findByTestId("comparison-table", {}, T);
    for (const w of ["mtd", "qtd", "ytd"]) expect(screen.getByTestId(`cmp-head-${w}`)).toBeInTheDocument();
    expect(text("comparison-note")).toMatch(/same days of last year/);
  });

  it("heat map: re-sorts through the API and keeps colours relative, not target based", async () => {
    await open("heatmap");
    await screen.findByTestId("heat-table", {}, T);
    expect(screen.getByTestId("heat-table")).toHaveAttribute("data-sort", "worst_contribution_pct");
    expect(text("heat-note")).toMatch(/never to a target/);
    fireEvent.change(screen.getByTestId("heat-sort"), { target: { value: "biggest_opportunity" } });
    await waitFor(() => expect(screen.getByTestId("heat-table")).toHaveAttribute("data-sort", "biggest_opportunity"), T);
    expect(calls.some((c) => c.includes("sort=biggest_opportunity"))).toBe(true);
  });

  it("peers: states the peer basis and positions the store against median and quartiles", async () => {
    await open("peers");
    await screen.findByTestId("peer-table", {}, T);
    expect(text("peer-basis")).toMatch(/region \+ vintage/);
    expect(screen.getByTestId("peer-power_psf")).toHaveTextContent(/bottom quartile/);
    expect(screen.getByTestId("peer-contribution_pct")).toHaveTextContent(/top quartile/);
  });

  it("expense exceptions: ranked with the reason written out, filterable by severity", async () => {
    await open("expense-exceptions");
    await screen.findByTestId("expense-exceptions-table", {}, T);
    expect(screen.getByTestId("sev-Critical")).toHaveAttribute("data-count", "1");
    expect(screen.getByTestId("exc-10-03-Power and Fuel Expenses")).toHaveTextContent(/3-month average/);
    fireEvent.click(screen.getByTestId("sev-High"));
    await waitFor(() => expect(screen.queryByTestId("exc-10-03-Power and Fuel Expenses")).toBeNull(), T);
    expect(screen.getByTestId("exc-30-01-Rent")).toBeInTheDocument();
  });

  it("revenue exceptions: lists the sales drop with its reason", async () => {
    await open("revenue-exceptions");
    await screen.findByTestId("revenue-exceptions-table", {}, T);
    expect(screen.getByTestId("rexc-20")).toHaveTextContent(/3-month average/);
  });

  it("data quality: names the stores without an area and the COGS months that stand out", async () => {
    await open("quality");
    await screen.findByTestId("quality-area", {}, T);
    expect(text("quality-area")).toMatch(/CHARLIE/);
    expect(text("quality-area")).toMatch(/never given an average area/);
    expect(text("quality-dates")).toMatch(/1 closed stores have no closing date/);
    expect(text("quality-cogs")).toMatch(/Aug 26/);
  });
});

describe("No day-aligned last year (P-05)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    calls = installPnlApi({ noLy: true });
  });

  it("MTD / QTD / YTD: no 'null', says LY is not available, and hides the empty LY and Growth columns", async () => {
    await mountTab("comparison");
    await screen.findByTestId("comparison-table", {}, T);
    const panel = screen.getByTestId("comparison-panel");
    expect(panel.textContent).not.toMatch(/null|undefined|NaN/);
    expect(text("comparison-ly-unavailable")).toMatch(/Last-year aligned comparison is not available for this period/);
    expect(screen.getByTestId("comparison-table").textContent).not.toMatch(/days 1 to/);
    expect(screen.queryByTestId("cmp-revenue-mtd-ly")).toBeNull();
    const headers = [...screen.getByTestId("comparison-table").querySelectorAll("thead th")].map((h) => h.textContent);
    expect(headers).not.toContain("LY");
    expect(headers).not.toContain("Growth");
    expect(text("comparison-note")).not.toMatch(/day null/);
    expect(exact("cmp-revenue-mtd-ty")).not.toBe("");
  });

  it("Pivot: hides the LY YTD, Var and Var % columns and states the reason", async () => {
    await mountTab("pivot");
    await screen.findByTestId("pivot-table", {}, T);
    const headers = [...screen.getByTestId("pivot-table").querySelectorAll("thead th")].map((h) => h.textContent ?? "");
    expect(headers.some((h) => /LY YTD/.test(h))).toBe(false);
    expect(headers.some((h) => /^Var/.test(h))).toBe(false);
    expect(text("pivot-ly-unavailable")).toMatch(/Last-year aligned comparison is not available for this period/);
    expect(screen.getByTestId("pivot-table").textContent).not.toMatch(/null/);
  });
});
