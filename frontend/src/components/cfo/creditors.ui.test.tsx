import { describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";

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
type M = ReturnType<typeof mount>;
const search = (m: M) => m.router.state.location.search as Record<string, string | undefined>;
const crumbs = () => screen.getByTestId("breadcrumbs").textContent ?? "";
const drawerTitle = () => within(screen.getByTestId("investigation-drawer")).getByTestId("drawer-title");

describe("Stage 2: Command Center → Creditors hand-off keeps the analytical context", () => {
  it("the Creditors pulse opens the room, preserving period / comparison / scenario", async () => {
    const m = mount(q("/", { period: "q2fy27", compare: "ly", scenario: "aged_creditors" }));
    fireEvent.click(await screen.findByTestId("pulse-creditors", {}, T));
    await screen.findByTestId("creditors-room", {}, T);
    expect(m.router.state.location.pathname).toBe("/creditors");
    expect(search(m)).toMatchObject({ period: "q2fy27", compare: "ly", scenario: "aged_creditors", lens: "age" });
    expect(search(m).drill).toBeUndefined();
    expect(crumbs()).toBe("CityKartCFO Command CenterCreditors");
    expect((screen.getByTestId("select-scenario") as HTMLSelectElement).value).toBe("aged_creditors");
  });

  it("the Payables risk pillar opens the room prefiltered to >180 days", async () => {
    const m = mount(q("/"));
    fireEvent.click(await screen.findByTestId("risk-payables", {}, T));
    await screen.findByTestId("creditors-room", {}, T);
    expect(search(m).drill).toBe("creditors.room/Ageing bucket:gt180");
    await waitFor(() => expect(screen.getByTestId("exposure-gt180")).toHaveAttribute("aria-pressed", "true"), T);
    expect(crumbs()).toBe("CityKartCFO Command CenterCreditors>180 days");
    expect(screen.getByTestId("lens-filter-chip")).toHaveTextContent(">180 days");
  });

  it("the CFO-focus action '>180 Days' opens the room with the same context", async () => {
    const m = mount(q("/", { scenario: "aged_creditors" }));
    fireEvent.click(await screen.findByTestId("action-cta-creditors_181", {}, T));
    await screen.findByTestId("creditors-room", {}, T);
    expect(search(m).drill).toBe("creditors.room/Ageing bucket:gt180");
    expect(search(m).scenario).toBe("aged_creditors");
  });

  it("other metrics still open the Stage 1 drawer, unchanged", async () => {
    const m = mount(q("/"));
    fireEvent.click(await screen.findByTestId("pulse-advances", {}, T));
    await screen.findByTestId("investigation-drawer", {}, T);
    expect(m.router.state.location.pathname).toBe("/");
  });

  it("the side nav has a live Creditors Control destination", async () => {
    const m = mount(q("/"));
    fireEvent.click(await screen.findByTestId("nav-creditors", {}, T));
    await screen.findByTestId("creditors-room", {}, T);
    expect(m.router.state.location.pathname).toBe("/creditors");
  });
});

describe("Stage 2: the room's structure and ordering", () => {
  it("shows exposure → age → movement → diagnosis, and no table above the fold", async () => {
    mount(q("/creditors", { lens: "age" }));
    await screen.findByTestId("river-b0_30", {}, T);
    const order = ["exposure-strip", "river-section", "migration", "lens-workspace"].map((id) => screen.getByTestId(id));
    for (let i = 0; i < order.length - 1; i++) expect(order[i].compareDocumentPosition(order[i + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.querySelectorAll("table").length).toBe(0);
    for (const id of ["current", "overdue", "gt90", "gt180", "b365p", "all"]) expect(screen.getByTestId(`exposure-${id}`)).toBeInTheDocument();
  });

  it("states the unconfirmed ageing basis in the header, river, migration and vendor profile", async () => {
    mount(q("/creditors"));
    await screen.findByTestId("river-b0_30", {}, T);
    await waitFor(() => expect(screen.getAllByTestId("ageing-basis-note").length).toBeGreaterThanOrEqual(3), T);
    for (const el of screen.getAllByTestId("ageing-basis-note")) expect(el).toHaveTextContent("Ageing basis awaiting finance validation");
    expect(screen.getAllByTestId("basis-dot").length).toBe(2); // Currently due, Overdue
  });

  it("a bare /creditors visit fills in the URL without adding history", async () => {
    const m = mount("/creditors");
    await screen.findByTestId("river-b0_30", {}, T);
    await waitFor(() => expect(search(m).period).toBe("ytdfy27"), T);
    expect(search(m).lens).toBe("age");
    expect(m.history.length).toBe(1);
    expect(crumbs()).toBe("CityKartCFO Command CenterCreditors");
  });
});

describe("Stage 2: ageing river, strip and lenses are URL-addressable filters", () => {
  it("clicking a river bucket selects it, updates the URL and replaces history", async () => {
    const m = mount(q("/creditors", { lens: "age" }));
    fireEvent.click(await screen.findByTestId("river-b181_365", {}, T));
    await waitFor(() => expect(search(m).drill).toBe("creditors.room/Ageing bucket:b181_365"), T);
    expect(screen.getByTestId("bucket-b181_365")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("bucket-b0_30")).toHaveAttribute("aria-pressed", "false");
    expect(m.history.length).toBe(1);
    fireEvent.click(screen.getByTestId("river-b91_180"));
    await waitFor(() => expect(search(m).drill).toBe("creditors.room/Ageing bucket:b91_180"), T);
    expect(m.history.length).toBe(1);
    fireEvent.click(screen.getByTestId("clear-age-filter"));
    await waitFor(() => expect(search(m).drill).toBeUndefined(), T);
  });

  it("clicking a strip value filters the whole page; the lens workspace follows", async () => {
    const m = mount(q("/creditors", { lens: "concentration" }));
    fireEvent.click(await screen.findByTestId("exposure-gt90", {}, T));
    await waitFor(() => expect(search(m).drill).toBe("creditors.room/Ageing bucket:gt90"), T);
    await waitFor(() => expect(screen.getByTestId("lens-filter-chip")).toHaveTextContent(">90 days"), T);
    const rowsFiltered = (await screen.findByTestId("concentration-list", {}, T)).querySelectorAll("li").length;
    fireEvent.click(screen.getByTestId("exposure-all"));
    await waitFor(() => expect(search(m).drill).toBeUndefined(), T);
    await waitFor(() => expect((screen.getByTestId("concentration-list").querySelectorAll("li").length)).toBeGreaterThanOrEqual(rowsFiltered), T);
  });

  it("switching lens updates the URL (replace) and swaps the workspace", async () => {
    const m = mount(q("/creditors", { lens: "age" }));
    await screen.findByTestId("age-lens", {}, T);
    for (const lens of ["concentration", "movement", "abnormal", "age"]) {
      fireEvent.click(screen.getByTestId(`lens-${lens}`));
      await waitFor(() => expect(search(m).lens).toBe(lens), T);
    }
    expect(m.history.length).toBe(1);
    fireEvent.click(screen.getByTestId("lens-concentration"));
    expect(await screen.findByTestId("concentration-indicators", {}, T)).toBeInTheDocument();
    for (const id of ["ind-top1", "ind-top5", "ind-top10", "ind-largest"]) expect(screen.getByTestId(id)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("lens-movement"));
    expect(await screen.findByTestId("movement-lens", {}, T)).toBeInTheDocument();
  });

  it("the abnormal lens lists diagnostic categories, never calls a debit balance an advance, never shows missing as zero", async () => {
    mount(q("/creditors", { lens: "abnormal", scenario: "vendor_advance_risk" }));
    const lens = await screen.findByTestId("abnormal-lens", {}, T);
    expect(within(lens).getByTestId("abnormal-note")).toHaveTextContent(/not treated as a vendor advance/i);
    const debit = within(lens).getByTestId("abnormal-debit_balance");
    expect(debit).toHaveTextContent("Debit balance in creditor account");
    expect(debit).toHaveTextContent(/Not classified as vendor advance/i);
    for (const id of ["opening_balance", "no_ageing_date"]) {
      const row = within(lens).getByTestId(`abnormal-${id}`);
      expect(row).toHaveTextContent("—");
      expect(row).toHaveTextContent("Awaiting finance mapping");
      expect(row.textContent).not.toMatch(/₹0\.00/);
    }
    expect(lens.querySelectorAll('[data-testid^="abnormal-"]:not([data-testid="abnormal-note"])').length).toBe(9);
  });
});

describe("Stage 2: migration → vendors → vendor profile → ledger → voucher", () => {
  it("a migration flow opens the drawer with the vendors behind it, then a vendor, ledger and voucher", async () => {
    const m = mount(q("/creditors"));
    fireEvent.click(await screen.findByTestId("flow-b61_90>b91_180", {}, T));
    await screen.findByTestId("investigation-drawer", {}, T);
    await waitFor(() => expect(drawerTitle()).toHaveTextContent("61–90 → 91–180"), T);
    expect(search(m).drill).toBe("creditors.room/Migration:b61_90>b91_180");
    const rows = await within(screen.getByTestId("investigation-drawer")).findByTestId("drill-rows", {}, T);
    const first = rows.querySelector("button") as HTMLButtonElement;
    fireEvent.click(first);

    await screen.findByTestId("vendor-profile", {}, T);
    expect(m.router.state.location.pathname).toBe("/creditors/vendor");
    expect(screen.queryByTestId("investigation-drawer")).toBeNull();
    expect(crumbs()).toMatch(/^CityKartCFO Command CenterCreditors61–90 → 91–180.+$/);
    await screen.findByTestId("lifecycle", {}, T);

    fireEvent.click(screen.getByTestId("vendor-open-ledger"));
    await screen.findByTestId("ledger-table", {}, T);
    expect(m.router.state.location.pathname).toBe("/ledger");
    expect(screen.getByTestId("ledger-balance-note")).toHaveTextContent(/credit-positive/i);
    fireEvent.click(await screen.findByTestId("ledger-row-E1", {}, T));
    await screen.findByTestId("evidence", {}, T);
    expect(m.router.state.location.pathname).toBe("/voucher");
    expect(crumbs()).toMatch(/GL(PI|PV|DN)-26-\d+$/);
  });

  it("a vendor opened from the concentration lens keeps the age filter in the breadcrumb", async () => {
    const m = mount(q("/creditors", { lens: "concentration", drill: "creditors.room/Ageing bucket:gt180" }));
    const first = await waitFor(() => {
      const el = document.querySelector('[data-testid^="vendor-V"]') as HTMLElement | null;
      if (!el) throw new Error("no vendor yet");
      return el;
    }, T);
    fireEvent.click(first);
    await screen.findByTestId("vendor-profile", {}, T);
    expect(search(m).drill).toMatch(/^creditors\.room\/Ageing bucket:gt180\/Vendor:V\d+$/);
    expect(crumbs()).toMatch(/Creditors>180 days.+/);
  });

  it("open items open a voucher straight from the vendor profile, and Back returns", async () => {
    const m = mount(q("/creditors/vendor", { drill: "creditors.room/Vendor:V10003" }));
    await screen.findByTestId("vendor-open-items", {}, T);
    const item = (await screen.findByTestId("open-items", {}, T)).querySelector("tbody tr") as HTMLElement;
    fireEvent.click(item);
    await screen.findByTestId("evidence", {}, T);
    expect(m.router.state.location.pathname).toBe("/voucher");
    m.router.history.back();
    await screen.findByTestId("vendor-profile", {}, T);
    expect(m.router.state.location.pathname).toBe("/creditors/vendor");
  });
});

describe("Stage 2: vendor profile content and finance rules", () => {
  it("shows the six-part strip, lifecycle, trend, migration, behaviour; advance and debit are separate", async () => {
    mount(q("/creditors/vendor", { drill: "creditors.room/Vendor:V10003" }));
    const strip = await screen.findByTestId("vendor-strip", {}, T);
    for (const id of ["outstanding", "overdue", "over90", "advance", "oldest", "lastpay"]) expect(within(strip).getByTestId(`strip-${id}`)).toBeInTheDocument();
    expect(within(strip).getByTestId("strip-advance")).toHaveTextContent(/separate from creditor balance/i);
    for (const id of ["opening", "liability", "adjustment", "payment", "open"]) expect(screen.getByTestId(`lifecycle-${id}`)).toBeInTheDocument();
    expect(screen.getByTestId("vendor-trend")).toBeInTheDocument();
    expect(screen.getByTestId("vendor-migration")).toBeInTheDocument();
    expect(screen.getByTestId("payment-behaviour")).toBeInTheDocument();
    expect(screen.getByTestId("advance-position")).toHaveTextContent(/separate from the creditor balance/i);
    expect(screen.getByTestId("debit-balance")).toHaveTextContent(/not classified as a vendor advance/i);
    // open items are last: after the lifecycle, trend, behaviour and diagnostics
    const after = (a: string, b: string) => screen.getByTestId(a).compareDocumentPosition(screen.getByTestId(b)) & Node.DOCUMENT_POSITION_FOLLOWING;
    expect(after("vendor-lifecycle", "vendor-open-items")).toBeTruthy();
    expect(after("vendor-abnormal", "vendor-open-items")).toBeTruthy();
  });

  it("open items carry both dates and a provisional age with the basis called out", async () => {
    mount(q("/creditors/vendor", { drill: "creditors.room/Vendor:V10003" }));
    const table = await screen.findByTestId("open-items", {}, T);
    const heads = Array.from(table.querySelectorAll("th")).map((h) => h.textContent);
    expect(heads).toEqual(expect.arrayContaining(["Document date", "Due date", "Age (provisional)"]));
    expect(within(screen.getByTestId("vendor-open-items")).getAllByTestId("ageing-basis-note").length).toBeGreaterThan(0);
  });
});

describe("Stage 2: browser Back, breadcrumb Back and refresh", () => {
  const DEEP = "creditors.room/Ageing bucket:gt180/Vendor:V10003";

  it("refreshing a deep vendor link restores the vendor, breadcrumbs and filters", async () => {
    const m = mount(q("/creditors/vendor", { scenario: "aged_creditors", period: "q2fy27", lens: "movement", drill: DEEP }));
    await screen.findByTestId("vendor-profile", {}, T);
    await waitFor(() => expect(crumbs()).toMatch(/Creditors>180 daysBhilwara Textiles|Creditors>180 days.+/), T);
    expect((screen.getByTestId("select-scenario") as HTMLSelectElement).value).toBe("aged_creditors");
    expect((screen.getByTestId("select-period") as HTMLSelectElement).value).toBe("q2fy27");
    expect(search(m).lens).toBe("movement");
    const href = m.router.state.location.href;
    cleanup();
    const again = mount(href);
    await screen.findByTestId("vendor-profile", {}, T);
    expect(again.router.state.location.pathname).toBe("/creditors/vendor");
    expect(search(again).drill).toBe(DEEP);
  });

  it("refreshing a flow link reopens the drawer; a ledger link reopens the ledger", async () => {
    mount(q("/creditors", { lens: "age", drill: "creditors.room/Migration:b91_180>b181_365" }));
    await screen.findByTestId("investigation-drawer", {}, T);
    await waitFor(() => expect(drawerTitle()).toHaveTextContent("91–180 → 181–365"), T);
    cleanup();
    const m = mount(q("/ledger", { lens: "age", drill: `${DEEP}/ledger` }));
    expect(await screen.findByTestId("ledger-table", {}, T)).toBeInTheDocument();
    expect(m.router.state.location.pathname).toBe("/ledger");
  });

  it("browser Back unwinds voucher → ledger → vendor → room, and Forward replays", async () => {
    const m = mount(q("/creditors", { drill: "creditors.room/Ageing bucket:gt180" }));
    const first = await waitFor(() => {
      fireEvent.click(screen.getByTestId("lens-concentration"));
      const el = document.querySelector('[data-testid^="vendor-V"]') as HTMLElement | null;
      if (!el) throw new Error("no vendor yet");
      return el;
    }, T);
    fireEvent.click(first);
    await screen.findByTestId("vendor-profile", {}, T);
    fireEvent.click(screen.getByTestId("vendor-open-ledger"));
    await screen.findByTestId("ledger-table", {}, T);
    fireEvent.click(await screen.findByTestId("ledger-row-E1", {}, T));
    await screen.findByTestId("evidence", {}, T);

    m.router.history.back();
    await screen.findByTestId("ledger-table", {}, T);
    m.router.history.back();
    await screen.findByTestId("vendor-profile", {}, T);
    m.router.history.back();
    await screen.findByTestId("creditors-room", {}, T);
    expect(m.router.state.location.pathname).toBe("/creditors");
    expect(search(m).drill).toBe("creditors.room/Ageing bucket:gt180");
    m.router.history.forward();
    await screen.findByTestId("vendor-profile", {}, T);
  });

  it("breadcrumb Back keeps filters and lens, and each level is clickable", async () => {
    const m = mount(q("/creditors/vendor", { scenario: "aged_creditors", lens: "abnormal", drill: "creditors.room/Ageing bucket:gt180/Vendor:V10011" }));
    await screen.findByTestId("vendor-profile", {}, T);
    await waitFor(() => expect(screen.getByTestId("crumb-3")).toBeInTheDocument(), T); // the deep link is still replaying
    fireEvent.click(screen.getByTestId("crumb-3")); // >180 days
    await screen.findByTestId("creditors-room", {}, T);
    expect(search(m).drill).toBe("creditors.room/Ageing bucket:gt180");
    expect(search(m).scenario).toBe("aged_creditors");
    expect(search(m).lens).toBe("abnormal");
    fireEvent.click(screen.getByTestId("crumb-2")); // Creditors
    await waitFor(() => expect(search(m).drill).toBeUndefined(), T);
    expect(m.router.state.location.pathname).toBe("/creditors");
    fireEvent.click(screen.getByTestId("crumb-1")); // CFO Command Center
    await screen.findByTestId("command-center", {}, T);
    expect(search(m).scenario).toBe("aged_creditors");
  });

  it("a stale or tampered creditors link falls back to the room, filters kept", async () => {
    const m = mount(q("/creditors/vendor", { scenario: "cash_pressure", drill: "creditors.room/Vendor:V99999" }));
    await screen.findByTestId("creditors-room", {}, T);
    await waitFor(() => expect(m.router.state.location.pathname).toBe("/creditors"), T);
    expect(search(m).scenario).toBe("cash_pressure");
  });
});

describe("Stage 2: scenarios and data states", () => {
  it("Aged Creditors materially changes what the room shows", async () => {
    mount(q("/creditors", { scenario: "normal" }));
    const read = async () => (await screen.findByTestId("exposure-gt180", {}, T)).textContent ?? "";
    await waitFor(async () => expect(await read()).toContain("18.40"), T);
    fireEvent.change(screen.getByTestId("select-scenario"), { target: { value: "aged_creditors" } });
    await waitFor(async () => expect(await read()).toContain("46.30"), T);
    expect(screen.getByTestId("exposure-all")).toHaveTextContent("268.40");
  });

  it("unavailable shows — with a reason, never zero; stale is flagged; error offers retry", async () => {
    mount(q("/creditors", { data: "unavailable" }));
    const strip = (await screen.findByTestId("exposure-strip-state", {}, T).catch(() => null)) ?? (await screen.findAllByTestId("state-unavailable", {}, T))[0];
    expect(strip).toHaveTextContent("—");
    expect(strip).toHaveTextContent("Awaiting finance mapping");
    expect(strip.textContent).not.toMatch(/₹0/);
    cleanup();
    mount(q("/creditors", { data: "stale" }));
    await screen.findByTestId("exposure-strip", {}, T);
    expect((await screen.findAllByTestId("stale-chip", {}, T)).length).toBeGreaterThan(0);
    cleanup();
    mount(q("/creditors", { data: "error" }));
    expect((await screen.findAllByTestId("state-error", {}, T)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Retry", {}, T)).length).toBeGreaterThan(0);
  });
});
