import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";

const T = { timeout: 6000 };
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
type M = ReturnType<typeof mount>;
const search = (m: M) => m.router.state.location.search as Record<string, string | undefined>;
const path = (m: M) => m.router.state.location.pathname;
const crumbs = () => screen.getByTestId("breadcrumbs").textContent ?? "";
const drawer = () => screen.getByTestId("investigation-drawer");

describe("Navigation: one operating system", () => {
  it("groups the live destinations and keeps the future modules visibly disabled", async () => {
    mount(q("/"));
    const nav = await screen.findByRole("navigation", { name: "Primary" }, T);
    for (const group of ["Command", "Performance", "Liquidity", "Exposure", "Upcoming"]) expect(nav).toHaveTextContent(group);
    for (const id of ["nav-command-center", "nav-profitability", "nav-cash", "nav-creditors"]) expect(within(nav).getByTestId(id)).toBeInTheDocument();
    const disabled = [...nav.querySelectorAll('[aria-disabled="true"]')].map((e) => e.textContent);
    expect(disabled).toEqual(expect.arrayContaining([expect.stringContaining("AOP & Forecast"), expect.stringContaining("Vendor Advances"), expect.stringContaining("Reconciliation"), expect.stringContaining("Balance Sheet")]));
    expect(disabled).toHaveLength(4);
  });

  it("each destination opens its workspace and keeps period, comparison and scenario", async () => {
    const m = mount(q("/", { period: "q2fy27", compare: "ly", scenario: "margin_pressure" }));
    fireEvent.click(await screen.findByTestId("nav-profitability", {}, T));
    await screen.findByTestId("pnl-room", {}, T);
    await waitFor(() => expect(path(m)).toBe("/profitability"), T);
    await waitFor(() => expect(search(m)).toMatchObject({ period: "q2fy27", compare: "ly", scenario: "margin_pressure" }), T);
    expect(screen.getByTestId("nav-profitability")).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByTestId("nav-cash"));
    await screen.findByTestId("cash-room", {}, T);
    await waitFor(() => expect(path(m)).toBe("/cash"), T);
    await waitFor(() => expect(search(m)).toMatchObject({ period: "q2fy27", compare: "ly", scenario: "margin_pressure" }), T);
    fireEvent.click(screen.getByTestId("nav-creditors"));
    await screen.findByTestId("creditors-room", {}, T);
    fireEvent.click(screen.getByTestId("nav-command-center"));
    await screen.findByTestId("command-center", {}, T);
    expect(path(m)).toBe("/");
  });
});

describe("Stage 3: Store Profitability", () => {
  it("store → movement → driver → GL → ledger → voucher, then Back all the way", async () => {
    const m = mount(q("/profitability/store", { drill: "profitability.portfolio/Store:rohini" }));

    // store workspace: header strip, dominant bridge, trajectory, expense pressure, network comparison, why
    await screen.findByTestId("store-workspace", {}, T);
    expect(path(m)).toBe("/profitability/store");
    expect(search(m).drill).toBe("profitability.portfolio/Store:rohini");
    await waitFor(() => expect(screen.getByTestId("store-title")).toHaveTextContent("Rohini"), T);
    for (const k of ["revenue", "gm", "opex", "contribution", "contributionPct"]) expect(await screen.findByTestId(`kpi-${k}`, {}, T)).toBeInTheDocument();
    for (const id of ["budget_contribution", "sales_var", "gm_var", "payroll", "rent", "electricity", "logistics", "other_opex", "actual_contribution"]) expect(screen.getByTestId(`bar-${id}`)).toHaveAttribute("role", "button");
    for (const id of ["store-trajectory", "expense-pressure", "network-comparison", "why-gap"]) expect(screen.getByTestId(id)).toBeInTheDocument();
    expect(screen.queryByTestId("investigation-drawer")).toBeNull();
    expect(crumbs()).toBe("CityKartCFO Command CenterProfitabilityRohini");

    // movement opens the drawer on the same page
    fireEvent.click(screen.getByTestId("bar-gm_var"));
    await within(await screen.findByTestId("investigation-drawer", {}, T)).findByTestId("drawer-amount", {}, T);
    expect(path(m)).toBe("/profitability/store");
    expect(within(drawer()).getByTestId("drawer-title")).toHaveTextContent("GM Variance");
    expect(search(m).drill).toBe("profitability.portfolio/Store:rohini/Movement:gm_var");

    // driver then GL account (terminal)
    fireEvent.click(await within(drawer()).findByTestId("drill-row-Department:Menswear", {}, T));
    await waitFor(() => expect(within(drawer()).getByTestId("drawer-title")).toHaveTextContent("Menswear"), T);
    fireEvent.click(await within(drawer()).findByTestId("split-tab-Account", {}, T));
    const acct = await within(drawer()).findAllByTestId(/^drill-row-Account:/, {}, T);
    fireEvent.click(acct[0]);
    await within(drawer()).findByTestId("drawer-terminal", {}, T);
    expect(within(drawer()).queryByTestId("open-profile")).toBeNull();
    expect(screen.queryByTestId("ledger-table")).toBeNull();

    // ledger → voucher
    fireEvent.click(within(drawer()).getByTestId("open-ledger"));
    expect(await screen.findByTestId("ledger-table", {}, T)).toBeInTheDocument();
    expect(path(m)).toBe("/ledger");
    fireEvent.click(await screen.findByTestId("ledger-row-E2", {}, T));
    expect(await screen.findByTestId("evidence", {}, T)).toBeInTheDocument();
    expect(path(m)).toBe("/voucher");

    // Back, Back returns to the GL account, then to the store page
    fireEvent.click(screen.getByTestId("deep-back"));
    await screen.findByTestId("ledger-table", {}, T);
    fireEvent.click(screen.getByTestId("deep-back"));
    await screen.findByTestId("investigation-drawer", {}, T);
    expect(path(m)).toBe("/profitability/store");
    // close the drill step by step
    for (let i = 0; i < 4; i++) {
      const back = screen.queryByTestId("drawer-back");
      if (!back) break;
      fireEvent.click(back);
      await new Promise((r) => setTimeout(r, 30));
    }
    await waitFor(() => expect(screen.queryByTestId("investigation-drawer")).toBeNull(), T);
    expect(await screen.findByTestId("store-title", {}, T)).toHaveTextContent("Rohini");

    // Back leaves the demo store workspace for the real Profitability page
    fireEvent.click(screen.getByTestId("store-back"));
    await screen.findByTestId("pnl-room", {}, T);
    expect(path(m)).toBe("/profitability");
  });

  it("every driver, expense and bridge bar opens a drawer for that movement", async () => {
    mount(q("/profitability/store", { drill: "profitability.portfolio/Store:rohini" }));
    await screen.findByTestId("bar-gm_var", {}, T);
    const why = screen.getAllByTestId(/^why-(?!gap)/);
    expect(why.length).toBeGreaterThanOrEqual(2);
    fireEvent.click(why[0]);
    await within(await screen.findByTestId("investigation-drawer", {}, T)).findByTestId("drawer-amount", {}, T);
    const firstWhy = why[0].getAttribute("data-testid")!.replace("why-", "");
    expect(drawer()).toBeInTheDocument();
    expect(firstWhy).toBeTruthy();
    fireEvent.click(screen.getAllByTestId(/^expense-/)[0]);
    await waitFor(() => expect(within(drawer()).getByTestId("drawer-title")).not.toHaveTextContent(/^$/), T);
  });

  it("a shared store link replays to the same drawer, with current numbers", async () => {
    mount(q("/profitability/store", { drill: "profitability.portfolio/Store:rohini/Movement:payroll/Payroll head:Store staff" }));
    const d = await screen.findByTestId("investigation-drawer", {}, T);
    await waitFor(() => expect(within(d).getByTestId("drawer-title")).toHaveTextContent("Store staff"), T);
    expect(crumbs()).toBe("CityKartCFO Command CenterProfitabilityRohiniPayrollStore staff");
  });

  it("a store that no longer exists falls back to the portfolio, same filters", async () => {
    const m = mount(q("/profitability/store", { scenario: "cash_pressure", drill: "profitability.portfolio/Store:no-such-store" }));
    await screen.findByTestId("pnl-room", {}, T);
    expect(path(m)).toBe("/profitability");
    expect(search(m).scenario).toBe("cash_pressure");
  });

  it("the store page without any drill context returns to the portfolio", async () => {
    const m = mount(q("/profitability/store"));
    await screen.findByTestId("pnl-room", {}, T);
    expect(path(m)).toBe("/profitability");
  });

  it("a store reached from the Command Center margin drill opens its profitability workspace", async () => {
    const m = mount(q("/"));
    fireEvent.click(await screen.findByTestId("bar-gm_impact", {}, T));
    const d = await screen.findByTestId("investigation-drawer", {}, T);
    fireEvent.click(await within(d).findByTestId("drill-row-Department:Menswear", {}, T));
    fireEvent.click(await within(d).findByTestId("split-tab-Region", {}, T));
    fireEvent.click(await within(d).findByTestId("drill-row-Region:North", {}, T));
    fireEvent.click(await within(d).findByTestId("split-tab-Store", {}, T));
    fireEvent.click(await within(d).findByTestId("drill-row-Store:Rohini", {}, T));
    fireEvent.click(await within(d).findByTestId("open-store-workspace", {}, T));
    expect(await screen.findByTestId("store-workspace", {}, T)).toBeInTheDocument();
    expect(path(m)).toBe("/profitability/store");
    expect(await screen.findByTestId("store-title", {}, T)).toHaveTextContent("Rohini");
  });

});

// Stage 4 (Cash) is now served from the verified cash mart: see cash.ui.test.tsx

describe("Polish: evidence wording, terminology, map emphasis", () => {
  it("voucher evidence leads with the unverified reconciliation block and labels sample content as such", async () => {
    mount(q("/ledger", { drill: "profitability.portfolio/Store:rohini/Movement:payroll/Account:6101/ledger" }));
    fireEvent.click(await screen.findByTestId("ledger-row-E2", {}, T));
    const ev = await screen.findByTestId("evidence", {}, T);
    expect(within(ev).getByTestId("evidence-unverified")).toHaveTextContent("Unverified");
    expect(within(ev).getByTestId("evidence-illustrative")).toHaveTextContent(/not source evidence/i);
    for (const k of ["Source system", "Source object", "Source record key", "Extraction run", "Mart record key", "Reconciliation status", "Source last updated"]) expect(ev).toHaveTextContent(k);
    expect(ev).toHaveTextContent("Sample attachments");
    expect(ev).toHaveTextContent("Sample audit trail");
  });
});
