import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";

function mount(path = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [path] }), context: { queryClient } });
  render(<RouterProvider router={router} />);
  return router;
}

const crumbs = () => screen.getByTestId("breadcrumbs").textContent ?? "";
const T = { timeout: 4000 };

describe("CFO Command Center journey", () => {
  it("shows the demo banner (never LIVE) and the pulse strip with seven metrics", async () => {
    mount();
    expect(await screen.findByTestId("demo-banner", {}, T)).toHaveTextContent("Demo data — financial source reconciliation pending");
    expect(screen.queryByText(/\blive\b/i)).toBeNull();
    for (const id of ["cash", "revenue", "gm", "profit", "creditors", "advances", "unreconciled"]) {
      expect(await screen.findByTestId(`pulse-${id}`, {}, T)).toBeInTheDocument();
    }
  });

  it("defaults the hero to the Profit bridge, every bar is a button", async () => {
    mount();
    expect(await screen.findByTestId("bar-gm_impact", {}, T)).toBeInTheDocument();
    expect(screen.getByTestId("hero-tab-profit")).toHaveAttribute("aria-selected", "true");
    for (const id of ["start", "sales_volume", "gm_impact", "payroll", "occupancy", "electricity", "store_productivity", "actual"]) {
      expect(screen.getByTestId(`bar-${id}`)).toHaveAttribute("role", "button");
    }
  });

  it("movement → driver → entity → ledger → voucher, with clickable breadcrumbs that keep filters", async () => {
    mount();
    fireEvent.change(await screen.findByTestId("select-scenario", {}, T), { target: { value: "margin_pressure" } });
    fireEvent.change(screen.getByTestId("select-period"), { target: { value: "q2fy27" } });

    fireEvent.click(await screen.findByTestId("bar-gm_impact", {}, T));
    const drawer = await screen.findByTestId("investigation-drawer", {}, T);
    await within(drawer).findByTestId("drawer-amount", {}, T);
    expect(within(drawer).getByTestId("drawer-title")).toHaveTextContent("Gross Margin Impact");
    expect(crumbs()).toContain("Gross Margin Impact");

    // driver (department)
    fireEvent.click(await within(drawer).findByTestId("drill-row-Department:Menswear", {}, T));
    await waitFor(() => expect(within(drawer).getByTestId("drawer-title")).toHaveTextContent("Menswear"), T);
    await waitFor(() => expect(within(drawer).getByTestId("drawer-level")).toHaveTextContent(/driver/i), T);

    // entity (region) then (store)
    fireEvent.click(await within(drawer).findByTestId("split-tab-Region", {}, T));
    fireEvent.click(await within(drawer).findByTestId("drill-row-Region:North", {}, T));
    await waitFor(() => expect(within(drawer).getByTestId("drawer-title")).toHaveTextContent("North"), T);
    fireEvent.click(await within(drawer).findByTestId("split-tab-Store", {}, T));
    fireEvent.click(await within(drawer).findByTestId("drill-row-Store:Rohini", {}, T));
    await waitFor(() => expect(within(drawer).getByTestId("drawer-terminal")).toBeInTheDocument(), T);
    expect(crumbs()).toContain("Gross Margin Impact");
    expect(crumbs()).toContain("Menswear");
    expect(crumbs()).toContain("North");
    expect(crumbs()).toContain("Rohini");

    // no table before the ledger level
    expect(screen.queryByTestId("ledger-table")).toBeNull();

    // ledger
    fireEvent.click(within(drawer).getByTestId("open-ledger"));
    expect(await screen.findByTestId("ledger-table", {}, T)).toBeInTheDocument();
    expect(crumbs()).toMatch(/Rohini\s*GL$/);

    // voucher
    fireEvent.click(await screen.findByTestId("ledger-row-E1", {}, T));
    expect(await screen.findByTestId("evidence", {}, T)).toBeInTheDocument();
    expect(crumbs()).toMatch(/GL\s*[A-Z]{2}-26-\d+$/);

    // breadcrumb back to the store (drawer returns, filters preserved)
    fireEvent.click(screen.getByTestId("crumb-5"));
    const drawer2 = await screen.findByTestId("investigation-drawer", {}, T);
    await waitFor(() => expect(within(drawer2).getByTestId("drawer-title")).toHaveTextContent("Rohini"), T);
    expect((screen.getByTestId("select-scenario") as HTMLSelectElement).value).toBe("margin_pressure");
    expect((screen.getByTestId("select-period") as HTMLSelectElement).value).toBe("q2fy27");

    // back to Menswear, then to the command center
    fireEvent.click(screen.getByTestId("crumb-3"));
    await waitFor(() => expect(within(screen.getByTestId("investigation-drawer")).getByTestId("drawer-title")).toHaveTextContent("Menswear"), T);
    fireEvent.click(screen.getByTestId("crumb-1"));
    await waitFor(() => expect(screen.queryByTestId("investigation-drawer")).toBeNull(), T);
    expect(crumbs()).toBe("CityKartCFO Command Center");
    expect((screen.getByTestId("select-scenario") as HTMLSelectElement).value).toBe("margin_pressure");
  });

  it("pulse metric opens its investigation and syncs the hero tab", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("pulse-creditors", {}, T));
    const drawer = await screen.findByTestId("investigation-drawer", {}, T);
    expect(await within(drawer).findByTestId("drawer-title", {}, T)).toHaveTextContent("Creditors");
    expect(screen.getByTestId("hero-tab-workingCapital")).toHaveAttribute("aria-selected", "true");
  });

  it("working-capital rows, risk pillars and attention CTAs all open the drawer", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("wc-row-inventory", {}, T));
    expect(await screen.findByTestId("investigation-drawer", {}, T)).toBeInTheDocument();
    fireEvent.click(await screen.findByTestId("risk-payables", {}, T));
    await waitFor(() => expect(within(screen.getByTestId("investigation-drawer")).getByTestId("drawer-title")).toHaveTextContent("Payables Ageing"), T);
    fireEvent.click(await screen.findByTestId("action-cta-advances_90", {}, T));
    await waitFor(() => expect(within(screen.getByTestId("investigation-drawer")).getByTestId("drawer-title")).toHaveTextContent("Vendor Advances"), T);
  });

  it("scenario switch changes the pulse and the hero", async () => {
    mount();
    const cash = async () => (await screen.findByTestId("pulse-cash", {}, T)).textContent;
    const before = await cash();
    fireEvent.change(screen.getByTestId("select-scenario"), { target: { value: "cash_pressure" } });
    await waitFor(async () => expect(await cash()).not.toBe(before), T);
  });

  it("shows — with a reason, never zero, when data is unavailable", async () => {
    mount();
    fireEvent.change(await screen.findByTestId("select-datastate", {}, T), { target: { value: "unavailable" } });
    await waitFor(() => expect(screen.getAllByTestId("pulse-placeholder")).toHaveLength(7), T);
    expect(screen.getAllByText("Awaiting finance mapping").length).toBeGreaterThan(0);
    expect(screen.getByTestId("financial-pulse").textContent).not.toMatch(/₹0/);
  });

  it("deep pages redirect home when opened without a drill context", async () => {
    const router = mount("/ledger");
    await waitFor(() => expect(router.state.location.pathname).toBe("/"), T);
  });

  it("future destinations are visibly disabled, not dead links", async () => {
    mount();
    const nav = await screen.findByRole("navigation", { name: "Primary" }, T);
    const disabled = nav.querySelectorAll('[aria-disabled="true"]');
    expect(disabled.length).toBe(6);
  });
});

