import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The Command Center's DEFAULT is real data. (The shared test setup selects the demo service for the older suites; this suite opts back in.)
vi.hoisted(() => vi.stubEnv("VITE_CFO_DATA", "live"));

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { isLiveCfo, isMockApi } from "@/api";
import { CASH, CRED, PNL, installLiveSources } from "@/test/cfoLiveFixture";

/* The Command Center on REAL data (synthetic API responses): per-source stamps, honest gaps, no demo controls. */

const T = { timeout: 5000 };
function mount(href = "/") {
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

beforeEach(() => {
  installLiveSources();
});
afterEach(() => vi.unstubAllGlobals());

describe("Command Center on real data", () => {
  it("defaults to the live source", () => {
    expect(isLiveCfo).toBe(true);
    expect(isMockApi).toBe(false);
  });

  it("the banner says real, per-source as-of, not one synchronized position, and there are no demo controls", async () => {
    mount();
    await screen.findByTestId("pulse-revenue", {}, T);
    const banner = screen.getByTestId("demo-banner");
    expect(banner).toHaveAttribute("data-source-mode", "live");
    expect(text("demo-banner")).toMatch(/Real data, per-source as-of/);
    expect(text("demo-banner")).toMatch(/not one synchronized CFO position/);
    expect(text("demo-banner")).not.toMatch(/Demo data/);
    expect(screen.queryByTestId("select-datastate")).toBeNull();
    expect(screen.queryByTestId("select-scenario")).toBeNull();
    expect(screen.getByTestId("scenario-live-note")).toHaveTextContent(/demo only/i);
    const compare = screen.getByTestId("select-comparison") as HTMLSelectElement;
    expect(within(compare).getByRole("option", { name: /Budget.*not available/ })).toBeInTheDocument();
    expect(within(compare).getByRole("option", { name: /Forecast.*not available/ })).toBeInTheDocument();
  });

  it("the top bar names each source with its own as-of date", async () => {
    mount();
    await screen.findByTestId("freshness-pnl", {}, T);
    expect(text("freshness-pnl")).toBe("P&L 09 Oct 2026");
    expect(text("freshness-creditors")).toBe("Creditors 07 Oct 2026");
    expect(text("freshness-cash")).toBe("Cash 08 Oct 2026");
  });

  it("each pulse figure shows its OWN run id and as-of date", async () => {
    mount();
    await screen.findByTestId("pulse-revenue", {}, T);
    expect(text("pulse-revenue")).toMatch(/₹1,000\.00 Cr/);
    expect(text("pulse-source-revenue")).toBe(`P&L · ${PNL.run} · 09 Oct 2026`);
    expect(text("pulse-source-creditors")).toBe(`Creditors · ${CRED.run} · 07 Oct 2026`);
    expect(text("pulse-source-cash")).toBe(`Cash · ${CASH.run} · 08 Oct 2026`);
    expect(text("pulse-cash")).toMatch(/Store till cash/);
    expect(text("pulse-creditors")).toMatch(/₹400\.00 Cr/);
    // no source: an em dash with its reason, never zero
    expect(text("pulse-advances")).toMatch(/—/);
    expect(text("pulse-advances")).toMatch(/No source has been identified/);
    expect(text("pulse-advances")).not.toMatch(/₹0/);
  });

  it("budget is not available: the default comparison shows an em dash with the reason", async () => {
    mount();
    await screen.findByTestId("pulse-revenue", {}, T);
    expect(text("pulse-revenue")).toMatch(/—/);
    expect(text("pulse-revenue")).toMatch(/Budget not available/);
  });

  it("the hero bridge is the real P&L composition, with its source line", async () => {
    mount();
    await screen.findByTestId("waterfall", {}, T);
    expect(text("hero-title")).toMatch(/net sales become store contribution/);
    await waitFor(() => expect(screen.getByTestId("hero").textContent).toMatch(new RegExp(`${PNL.run} · as of 09 Oct 2026`)));
    fireEvent.click(screen.getByTestId("hero-tab-cash"));
    await within(screen.getByTestId("hero")).findByTestId("state-unavailable", {}, T);
    expect(screen.getByTestId("hero")).toHaveTextContent(/No opening-cash or cash-flow source exists/);
  });

  it("liquidity shows real till cash and states why there is no projection; working capital shows only the creditors balance", async () => {
    mount();
    await screen.findByTestId("liquidity-no-projection", {}, T);
    expect(text("liq-current")).toMatch(/₹5\.00 Cr/);
    expect(text("liq-projected")).toBe("Projected—");
    expect(text("liq-min")).toMatch(/—/);
    expect(text("liquidity-no-projection")).toMatch(/No forecast source exists/);
    await screen.findByTestId("wc-row-creditors", {}, T);
    expect(text("wc-row-creditors")).toMatch(/₹400\.00 Cr/);
    expect(text("wc-row-inventory")).toMatch(/—/);
    expect(text("wc-net")).toMatch(/—/);
    expect(text("wc-net")).not.toMatch(/₹0/);
  });

  it("risks are rated only where a real fact exists; actions cite their evidence; the forecast is unavailable", async () => {
    mount();
    await screen.findByTestId("risk-payables", {}, T);
    expect(text("risk-sev-payables")).toBe("High");
    expect(text("risk-sev-advances")).toBe("Not rated");
    await screen.findByTestId("action-past_due", {}, T);
    expect(text("action-evidence-past_due")).toMatch(new RegExp(`Creditors · ${CRED.run} · as of 07 Oct 2026`));
    expect(text("action-unmapped_ledgers")).toMatch(/2 P&L ledgers need Finance mapping/);
    const forecast = await screen.findByTestId("forecast", {}, T);
    await waitFor(() => expect(within(forecast).getByTestId("state-unavailable")).toBeInTheDocument());
    expect(forecast).toHaveTextContent(/No forecast source exists/);
  });

  it("a bridge bar opens a real drill with its sources and a way to the page that owns the detail", async () => {
    const { router } = mount();
    await screen.findByTestId("pulse-revenue", {}, T);
    fireEvent.click(screen.getByTestId("pulse-revenue"));
    const drawer = await screen.findByTestId("investigation-drawer", {}, T);
    await within(drawer).findByTestId("drill-rows", {}, T);
    expect(within(drawer).getByTestId("drill-row-Top store:10")).toHaveTextContent("ALPHA");
    expect(within(drawer).getByTestId("source-lines")).toHaveTextContent(`P&L · ${PNL.run} · as of 09 Oct 2026`);
    expect(within(drawer).queryByTestId("open-ledger")).toBeNull();
    fireEvent.click(within(drawer).getByTestId("open-live-page"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/profitability"));
  });

  it("vendor advances open an honest unavailable drawer, not a made-up breakdown", async () => {
    mount();
    await screen.findByTestId("pulse-advances", {}, T);
    fireEvent.click(screen.getByTestId("pulse-advances"));
    const drawer = await screen.findByTestId("investigation-drawer", {}, T);
    await within(drawer).findByTestId("state-unavailable", {}, T);
    expect(drawer).toHaveTextContent(/vendor advances/i);
  });

  it("the real pages' banner states the same per-source truth", async () => {
    mount("/profitability");
    await screen.findByTestId("demo-banner", {}, T);
    expect(text("demo-banner")).toMatch(/Profitability shows REAL data from its own verified run/);
    expect(text("demo-banner")).toMatch(/real, per-source as-of, not one synchronized CFO position/);
  });
});
