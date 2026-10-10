import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The Command Center's DEFAULT is real data. (The shared test setup selects the demo service for the older suites; this suite opts back in.)
vi.hoisted(() => vi.stubEnv("VITE_CFO_DATA", "live"));

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { isLiveCfo, isMockApi } from "@/api";
import { CASH, CRED, MGMT, PNL, installLiveSources } from "@/test/cfoLiveFixture";

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

  it("one data-status chip replaces the banner: per-source truth lives in its drawer, and there are no demo controls", async () => {
    mount();
    await screen.findByTestId("pulse-revenue", {}, T);
    expect(screen.queryByTestId("demo-banner")).toBeNull();
    fireEvent.click(screen.getByTestId("real-state"));
    const drawer = await screen.findByTestId("data-status-drawer", {}, T);
    expect(within(drawer).getByTestId("data-notes")).toHaveTextContent(/not one synchronised CFO position/);
    expect(within(drawer).getByTestId("not-yet-available")).toHaveTextContent(/AOP and forecast/);
    expect(screen.queryByTestId("select-datastate")).toBeNull();
    expect(screen.queryByTestId("select-scenario")).toBeNull();
    expect(screen.getByTestId("scenario-live-note")).toHaveTextContent(/demo only/i);
    const compare = screen.getByTestId("select-comparison") as HTMLSelectElement;
    expect(within(compare).getByRole("option", { name: /AOP.*not available/ })).toBeInTheDocument();
    expect(within(compare).getByRole("option", { name: /Forecast.*not available/ })).toBeInTheDocument();
  });

  it("the data-status drawer names each source with its own as-of date", async () => {
    mount();
    await screen.findByTestId("pulse-revenue", {}, T);
    fireEvent.click(screen.getByTestId("real-state"));
    await screen.findByTestId("freshness-pnl", {}, T);
    expect(text("freshness-pnl")).toMatch(/^P&L 09 Oct 2026/);
    expect(text("freshness-creditors")).toMatch(/^Creditors 07 Oct 2026/);
    expect(text("freshness-cash")).toMatch(/^Cash 08 Oct 2026/);
  });

  it("each pulse figure shows its OWN run id and as-of date", async () => {
    mount();
    await screen.findByTestId("pulse-revenue", {}, T);
    expect(text("pulse-revenue")).toMatch(/₹1,000\.00 Cr/);
    expect(text("pulse-source-revenue")).toBe(`Management P&L · ${MGMT.run} · 09 Oct 2026`);
    expect(text("pulse-source-creditors")).toBe(`Creditors · ${CRED.run} · 07 Oct 2026`);
    expect(text("pulse-source-cash")).toBe(`Cash · ${CASH.run} · 08 Oct 2026`);
    expect(text("pulse-cash")).toMatch(/Store till cash/);
    expect(text("pulse-creditors")).toMatch(/₹400\.00 Cr/);
    // no source: an em dash with its reason, never zero
    expect(text("pulse-advances")).toMatch(/—/);
    expect(text("pulse-advances")).toMatch(/No source has been identified/);
    expect(text("pulse-advances")).not.toMatch(/₹0/);
  });

  it("live data defaults to the Last Year comparison, so movements are shown", async () => {
    mount();
    await screen.findByTestId("pulse-revenue", {}, T);
    expect(text("pulse-revenue")).not.toMatch(/AOP not available/);
  });

  it("AOP is not available: choosing it shows an em dash with the reason", async () => {
    mount("/?compare=budget");
    await screen.findByTestId("pulse-revenue", {}, T);
    expect(text("pulse-revenue")).toMatch(/—/);
    expect(text("pulse-revenue")).toMatch(/Revenue from operations/);
    expect(text("pulse-gm")).toMatch(/Material Margin/);
    expect(text("pulse-gm")).toMatch(/includes management adjustments/);
    expect(text("pulse-profit")).toMatch(/Store EBITDA/);
    expect(text("pulse-profit")).toMatch(/includes management adjustments/);
    expect(text("pulse-revenue")).toMatch(/AOP not available/);
  });

  it("the hero bridge is the real P&L composition, with its source line", async () => {
    mount();
    await screen.findByTestId("waterfall", {}, T);
    expect(text("hero-title")).toMatch(/revenue from operations become Corporate EBITDA/);
    await waitFor(() => expect(screen.getByTestId("hero").textContent).toMatch(new RegExp(`${MGMT.run} · as of 09 Oct 2026`)));
    expect(screen.getByTestId("hero").textContent).toMatch(/Corporate EBITDA/);
    expect(screen.getByTestId("hero").textContent).toMatch(/includes management adjustments/);
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
    expect(within(drawer).getByTestId("source-lines")).toHaveTextContent(`Management P&L · ${MGMT.run} · as of 09 Oct 2026`);
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

  it("the real pages use the same data-status chip, with their own as-of", async () => {
    mount("/profitability");
    await screen.findByTestId("real-state", {}, T);
    expect(screen.queryByTestId("demo-banner")).toBeNull();
    fireEvent.click(screen.getByTestId("real-state"));
    expect((await screen.findByTestId("data-notes", {}, T)).textContent).toMatch(/not one synchronised CFO position/);
  });
});

describe("Quick fixes on the live app", () => {
  it("P-01: the store workspace is labelled Demo data - not real, never real, with no real-data badge", async () => {
    mount("/profitability/store?drill=profitability.portfolio/Store:rohini");
    const banner = await screen.findByTestId("demo-banner", {}, T);
    expect(banner).toHaveAttribute("data-real", "false");
    expect(banner.textContent).toMatch(/Demo data - not real/);
    expect(banner.textContent).not.toMatch(/Real data|REAL data/);
    expect(await screen.findByTestId("demo-chip", {}, T)).toHaveTextContent("Demo data - not real");
    expect(await screen.findByTestId("store-demo-chip", {}, T)).toHaveTextContent("Demo data - not real");
    expect(screen.queryByTestId("freshness")).toBeNull();
    expect(screen.queryByTestId("real-controls")).toBeNull();
  });

  it("P-03: no unqualified 'Current cash' or 'Cash' stat; the till figure says it excludes the bank ledger book", async () => {
    mount();
    await screen.findByTestId("liquidity-no-projection", {}, T);
    expect(screen.getByTestId("liq-current").textContent).toMatch(/^Store till cash/);
    expect(text("liq-current")).toMatch(/excludes bank ledger book \(provisional\)/);
    expect(screen.getByTestId("pulse-cash").textContent).toMatch(/^Store till cash/);
    expect(text("pulse-cash")).toMatch(/excludes bank ledger book \(provisional\)/);
    await screen.findByTestId("risk-liquidity", {}, T);
    expect(text("risk-liquidity")).toMatch(/Store till cash/);
    expect(text("risk-liquidity")).not.toMatch(/Cash on hand/);
    const bare = [...document.querySelectorAll("span, div, button")].filter((e) => e.children.length === 0 && /^(Current cash|Cash)$/.test((e.textContent ?? "").trim()) && !e.closest('[role="tablist"]'));
    expect(bare.map((e) => e.textContent)).toEqual([]);
  });

  it("P-04: the Command Center bridge is tagged 'Management total' (the books fallback is tagged in liveCfoApi.test.ts)", async () => {
    mount();
    await screen.findByTestId("waterfall", {}, T);
    expect(within(screen.getByTestId("hero")).getByTestId("basis-tag")).toHaveTextContent("Management total");
  });

  it("P-04: Profitability tags its Corporate EBITDA 'Books'", async () => {
    mount("/profitability");
    await screen.findByTestId("strip-corporate", {}, T);
    expect(within(screen.getByTestId("strip-corporate")).getByTestId("basis-tag")).toHaveTextContent("Books");
  });

  it("P-11: Landing chips come from the run headers, not literals", async () => {
    mount("/home");
    await waitFor(() => expect(text("tone-profitability")).toBe("Real data · live"), T);
    expect(text("tone-creditors")).toBe("Real data · live");
    expect(text("tone-cash")).toBe("Real data · live");
    // the management and related-party APIs are not served by this fixture: the chip says so instead of claiming real data
    await waitFor(() => expect(text("tone-mgmt")).toBe("Not available"), T);
    expect(text("tone-related")).toBe("Not available");
  });

  it("P-11: a source that cannot be read shows 'Not available'", async () => {
    vi.unstubAllGlobals();
    installLiveSources({ fail: { cash: 500 } });
    mount("/home");
    await waitFor(() => expect(text("tone-cash")).toBe("Not available"), T);
    await waitFor(() => expect(text("tone-profitability")).toBe("Real data · live"), T);
  });
});
