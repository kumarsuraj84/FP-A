import { describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";

const T = { timeout: 4000 };
const DRILL = "hero:profit.gm_impact/Department:Menswear/Region:North/Store:Rohini";
const url = (path: string, params: Record<string, string>) => `${path}?${new URLSearchParams(params).toString()}`;
const FILTERS = { period: "q2fy27", compare: "ly", scenario: "margin_pressure" };

function mount(href: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  const history = createMemoryHistory({ initialEntries: [href] });
  const router = createRouter({ routeTree, history, context: { queryClient } });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, history, view };
}

const crumbs = () => screen.getByTestId("breadcrumbs").textContent ?? "";
const drillParam = (r: ReturnType<typeof mount>["router"]) => (r.state.location.search as { drill?: string }).drill;
const title = () => within(screen.getByTestId("investigation-drawer")).getByTestId("drawer-title");

describe("URL-addressable investigation state", () => {
  it("opening a shared deep link restores filters, drill path, drawer and breadcrumbs", async () => {
    const { router } = mount(url("/", { ...FILTERS, drill: DRILL }));
    await screen.findByTestId("drawer-terminal", {}, T);
    await waitFor(() => expect(title()).toHaveTextContent("Rohini"), T);
    expect(crumbs()).toBe("CityKartCFO Command CenterGross Margin ImpactMenswearNorthRohini");
    expect((screen.getByTestId("select-scenario") as HTMLSelectElement).value).toBe("margin_pressure");
    expect((screen.getByTestId("select-period") as HTMLSelectElement).value).toBe("q2fy27");
    expect((screen.getByTestId("select-comparison") as HTMLSelectElement).value).toBe("ly");
    expect(drillParam(router)).toBe(DRILL);
    expect(router.state.location.pathname).toBe("/");
  });

  it("a deep link to the ledger and to a voucher page restores those pages (no redirect home)", async () => {
    const m = mount(url("/ledger", { ...FILTERS, drill: `${DRILL}/ledger` }));
    expect(await screen.findByTestId("ledger-table", {}, T)).toBeInTheDocument();
    expect(m.router.state.location.pathname).toBe("/ledger");
    const firstVoucher = within(screen.getByTestId("ledger-row-E3")).getAllByRole("cell")[1].textContent!;
    cleanup();

    const v = mount(url("/voucher", { ...FILTERS, drill: `${DRILL}/ledger/voucher:${firstVoucher}` }));
    expect(await screen.findByTestId("evidence", {}, T)).toBeInTheDocument();
    expect(v.router.state.location.pathname).toBe("/voucher");
    expect(crumbs()).toContain(firstVoucher);
  });

  it("refresh: the URL written after a drill reopens the same investigation", async () => {
    const first = mount(url("/", FILTERS));
    fireEvent.click(await screen.findByTestId("bar-gm_impact", {}, T));
    await screen.findByTestId("drawer-amount", {}, T);
    fireEvent.click(await screen.findByTestId("drill-row-Department:Menswear", {}, T));
    await waitFor(() => expect(drillParam(first.router)).toBe("hero:profit.gm_impact/Department:Menswear"), T);
    const href = first.router.state.location.href;
    expect(href).toContain("scenario=margin_pressure");
    cleanup();

    // "refresh" = a brand new app instance at the same URL
    const second = mount(href);
    await waitFor(() => expect(title()).toHaveTextContent("Menswear"), T);
    expect(crumbs()).toContain("Gross Margin ImpactMenswear");
    expect(drillParam(second.router)).toBe("hero:profit.gm_impact/Department:Menswear");
  });

  it("browser Back unwinds the drill one step at a time and Forward replays it", async () => {
    const { router } = mount(url("/", FILTERS));
    fireEvent.click(await screen.findByTestId("bar-gm_impact", {}, T));
    fireEvent.click(await screen.findByTestId("drill-row-Department:Menswear", {}, T));
    await waitFor(() => expect(title()).toHaveTextContent("Menswear"), T);
    fireEvent.click(await screen.findByTestId("split-tab-Region", {}, T));
    fireEvent.click(await screen.findByTestId("drill-row-Region:North", {}, T));
    await waitFor(() => expect(title()).toHaveTextContent("North"), T);
    expect(drillParam(router)).toBe("hero:profit.gm_impact/Department:Menswear/Region:North");

    act(() => router.history.back());
    await waitFor(() => expect(title()).toHaveTextContent("Menswear"), T);
    expect(drillParam(router)).toBe("hero:profit.gm_impact/Department:Menswear");
    expect(crumbs()).toBe("CityKartCFO Command CenterGross Margin ImpactMenswear");

    act(() => router.history.back());
    await waitFor(() => expect(title()).toHaveTextContent("Gross Margin Impact"), T);
    expect(drillParam(router)).toBe("hero:profit.gm_impact");

    act(() => router.history.back());
    await waitFor(() => expect(screen.queryByTestId("investigation-drawer")).toBeNull(), T);
    expect(drillParam(router)).toBeUndefined();

    act(() => router.history.forward());
    await waitFor(() => expect(screen.getByTestId("investigation-drawer")).toBeInTheDocument(), T);
    expect(drillParam(router)).toBe("hero:profit.gm_impact");
  });

  it("browser Back from the voucher page returns to the ledger, then to the drawer", async () => {
    const { router } = mount(url("/", { ...FILTERS, drill: DRILL }));
    fireEvent.click(await screen.findByTestId("open-ledger", {}, T));
    await screen.findByTestId("ledger-table", {}, T);
    fireEvent.click(await screen.findByTestId("ledger-row-E2", {}, T));
    await screen.findByTestId("evidence", {}, T);
    expect(router.state.location.pathname).toBe("/voucher");

    router.history.back();
    await screen.findByTestId("ledger-table", {}, T);
    expect(router.state.location.pathname).toBe("/ledger");
    router.history.back();
    await screen.findByTestId("drawer-terminal", {}, T);
    expect(router.state.location.pathname).toBe("/");
    expect(title()).toHaveTextContent("Rohini");
  });

  it("breadcrumb Back keeps the URL consistent and filters intact", async () => {
    const { router } = mount(url("/", { ...FILTERS, drill: DRILL }));
    await screen.findByTestId("drawer-terminal", {}, T);
    fireEvent.click(screen.getByTestId("crumb-3")); // Menswear
    await waitFor(() => expect(drillParam(router)).toBe("hero:profit.gm_impact/Department:Menswear"), T);
    await waitFor(() => expect(title()).toHaveTextContent("Menswear"), T);
    expect(crumbs()).toBe("CityKartCFO Command CenterGross Margin ImpactMenswear");
    expect((router.state.location.search as { scenario?: string }).scenario).toBe("margin_pressure");
    fireEvent.click(screen.getByTestId("crumb-1")); // CFO Command Center
    await waitFor(() => expect(drillParam(router)).toBeUndefined(), T);
    expect(screen.queryByTestId("investigation-drawer")).toBeNull();
    expect((router.state.location.search as { period?: string }).period).toBe("q2fy27");
  });

  it("changing period / comparison / scenario updates the URL by replacing, not stacking, history", async () => {
    const { router, history } = mount(url("/", { ...FILTERS, drill: DRILL }));
    await screen.findByTestId("drawer-terminal", {}, T);
    const before = history.length;
    fireEvent.change(screen.getByTestId("select-comparison"), { target: { value: "forecast" } });
    await waitFor(() => expect((router.state.location.search as { compare?: string }).compare).toBe("forecast"), T);
    fireEvent.change(screen.getByTestId("select-period"), { target: { value: "sep26" } });
    await waitFor(() => expect((router.state.location.search as { period?: string }).period).toBe("sep26"), T);
    expect(history.length).toBe(before); // replace, no new entries
    expect(drillParam(router)).toBe(DRILL); // the investigation survives a filter change
    await waitFor(() => expect(title()).toHaveTextContent("Rohini"), T);
  });

  it("does not loop: an idle app stays on a single stable history entry", async () => {
    const { history } = mount("/");
    await screen.findByTestId("bar-gm_impact", {}, T);
    await new Promise((r) => setTimeout(r, 600));
    expect(history.length).toBe(1);
    fireEvent.click(screen.getByTestId("bar-gm_impact"));
    await screen.findByTestId("drawer-amount", {}, T);
    await new Promise((r) => setTimeout(r, 600));
    expect(history.length).toBe(2);
  });

  it("a stale or tampered link falls back to the command center and keeps the filters", async () => {
    const { router } = mount(url("/", { ...FILTERS, drill: "hero:profit.gm_impact/Department:Atlantis" }));
    await waitFor(() => expect(drillParam(router)).toBeUndefined(), T);
    expect(screen.queryByTestId("investigation-drawer")).toBeNull();
    expect((screen.getByTestId("select-scenario") as HTMLSelectElement).value).toBe("margin_pressure");
  });

  it("a /ledger link with no resolvable drill redirects home", async () => {
    const { router } = mount(url("/ledger", { ...FILTERS, drill: "hero:profit.nonsense/ledger" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"), T);
  });

  it("the drawer's Axis note and exact tooltip values are present", async () => {
    mount("/");
    expect(await screen.findByTestId("axis-truncated", {}, T)).toHaveTextContent("Axis truncated for variance visibility");
    fireEvent.mouseEnter(await screen.findByTestId("bar-gm_impact"));
    expect(await screen.findByTestId("waterfall-tooltip")).toHaveTextContent("−₹1.42 Cr");
  });
});
