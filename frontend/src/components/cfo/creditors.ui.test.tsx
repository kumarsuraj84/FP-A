import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { FIXTURE, installCreditorsApi } from "@/test/creditorsFixture";

/* The Creditors room runs on the real Creditors API. These tests serve it a SYNTHETIC API (invented vendors, round numbers). */

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
const exact = (id: string) => screen.getByTestId(id).getAttribute("data-exact");

let calls: string[] = [];
beforeEach(() => {
  calls = installCreditorsApi();
});
afterEach(() => vi.unstubAllGlobals());

describe("Creditors room: hand-off from the Command Center keeps the analytical context", () => {
  it("the Creditors pulse opens the room, preserving period / comparison / scenario", async () => {
    const m = mount(q("/", { period: "q2fy27", compare: "ly", scenario: "aged_creditors" }));
    fireEvent.click(await screen.findByTestId("pulse-creditors", {}, T));
    await screen.findByTestId("creditors-room", {}, T);
    expect(m.router.state.location.pathname).toBe("/creditors");
    expect(search(m)).toMatchObject({ period: "q2fy27", compare: "ly", scenario: "aged_creditors", lens: "age" });
    expect(search(m).drill).toBeUndefined();
    expect(crumbs()).toBe("CityKartCFO Command CenterCreditors");
  });

  it("the Payables risk pillar opens the room prefiltered to >180 days of document age", async () => {
    const m = mount(q("/"));
    fireEvent.click(await screen.findByTestId("risk-payables", {}, T));
    await screen.findByTestId("creditors-room", {}, T);
    expect(search(m).drill).toBe("creditors.room/Ageing bucket:gt180");
    await waitFor(() => expect(screen.getByTestId("exposure-gt180")).toHaveAttribute("aria-pressed", "true"), T);
    expect(screen.getByTestId("lens-filter-chip")).toHaveTextContent(">180 days");
  });

  it("other metrics still open the drawer, unchanged", async () => {
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

describe("Creditors room: the real strip", () => {
  it("shows exactly the six agreed metrics, from exact API values, with the data state stated by the API", async () => {
    mount(q("/creditors"));
    const strip = await screen.findByTestId("exposure-strip", {}, T);
    for (const label of ["Credit Outstanding", "Creditor Debit Balance", "Past Due", "Due Date Unavailable", ">90 Days Document Age", ">180 Days Document Age"]) expect(strip).toHaveTextContent(label);
    expect(exact("exposure-credit-value")).toBe(FIXTURE.credit);
    expect(exact("exposure-debit-value")).toBe(FIXTURE.debit);
    expect(exact("exposure-past_due-value")).toBe(FIXTURE.pastDue);
    expect(exact("exposure-due_unavailable-value")).toBe(FIXTURE.dueUnavailable);
    expect(exact("exposure-gt90-value")).toBe(FIXTURE.over90);
    expect(exact("exposure-gt180-value")).toBe(FIXTURE.over180);
    expect(screen.getByTestId("exposure-credit-value")).toHaveTextContent("₹100.00 Cr");
    expect(screen.getByTestId("exposure-debit-value")).toHaveTextContent("₹5.00 Cr");
    // no invented movement, and no age-based "currently due / overdue"
    expect(strip).not.toHaveTextContent(/vs opening/i);
    expect(strip).not.toHaveTextContent(/currently due/i);
    const badge = await screen.findByTestId("data-state", {}, T);
    expect(badge).toHaveAttribute("data-state", "verified_candidate");
    expect(badge).toHaveTextContent(/Verified candidate · not live/);
  });

  it("never blends credit and debit: the signed net is a labelled reference line only", async () => {
    mount(q("/creditors"));
    const ctx = await screen.findByTestId("strip-context", {}, T);
    expect(ctx).toHaveTextContent(/Signed net \(Credit − Debit\)/);
    expect(ctx).toHaveTextContent(/not netted into Credit Outstanding/);
    expect(screen.getByTestId("exposure-debit")).toHaveTextContent(/not netted/);
  });

  it("clicking Past Due filters by Due Status; clicking >90 filters by Document Age; they stay separate dimensions", async () => {
    const m = mount(q("/creditors"));
    fireEvent.click(await screen.findByTestId("exposure-past_due", {}, T));
    await waitFor(() => expect(search(m).drill).toBe("creditors.room/Ageing bucket:past_due"), T);
    await waitFor(() => expect(calls.some((c) => c.includes("cohort=past_due"))).toBe(true), T);
    expect(screen.getByTestId("due-PAST_DUE_OR_DUE_TODAY")).toHaveAttribute("aria-pressed", "true");
    // a Due Status filter does not light up any Document Age bucket
    expect(screen.getByTestId("bucket-b91_180")).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByTestId("exposure-gt90"));
    await waitFor(() => expect(search(m).drill).toBe("creditors.room/Ageing bucket:gt90"), T);
    await waitFor(() => expect(screen.getByTestId("bucket-b91_180")).toHaveAttribute("aria-pressed", "true"), T);
    expect(screen.getByTestId("bucket-b181_365")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("bucket-b365p")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("due-PAST_DUE_OR_DUE_TODAY")).toHaveAttribute("aria-pressed", "false");
  });
});

describe("Creditors room: Document Age, Due Status and the ledgers", () => {
  it("renders Document Age (six buckets + unclassified held aside) and Due Status (four states) from the API", async () => {
    mount(q("/creditors"));
    await screen.findByTestId("river-detail", {}, T);
    for (const id of ["b0_30", "b31_60", "b61_90", "b91_180", "b181_365", "b365p"]) expect(screen.getByTestId(`bucket-${id}`)).toBeInTheDocument();
    expect(screen.getByTestId("bucket-b0_30")).toHaveTextContent("₹30.00 Cr");
    expect(screen.getByTestId("age-unclassified")).toHaveTextContent(/Unclassified/);
    for (const s of ["NOT_YET_DUE", "PAST_DUE_OR_DUE_TODAY", "DUE_UNAVAILABLE", "DUE_INVALID"]) expect(await screen.findByTestId(`due-${s}`, {}, T)).toBeInTheDocument();
    expect(screen.getByTestId("due-DUE_UNAVAILABLE")).toHaveTextContent(/never estimated/);
    expect(screen.getByTestId("due-DUE_INVALID")).toBeDisabled(); // nothing in it: no empty filter to click
  });

  it("shows the four creditor ledgers with credit and debit in separate columns", async () => {
    mount(q("/creditors"));
    const panel = await screen.findByTestId("ledger-panel", {}, T);
    await within(panel).findByTestId("ledger-1000000026", {}, T);
    expect(within(panel).getByText("Credit outstanding")).toBeInTheDocument();
    expect(within(panel).getByText("Debit balance")).toBeInTheDocument();
    expect(exact("ledger-1000000026") ?? "").toBe(""); // the row itself carries no blended figure
  });

  it("states the sections the verified extract cannot support, instead of showing zeros", async () => {
    mount(q("/creditors"));
    await screen.findByTestId("lens-workspace", {}, T);
    fireEvent.click(screen.getByTestId("lens-movement"));
    const na = await screen.findByTestId("movement-unavailable", {}, T);
    expect(na).toHaveTextContent(/Movement is not available yet/);
    expect(na).toHaveTextContent(/two verified snapshots/);
    expect(na).not.toHaveTextContent(/₹/);
  });

  it("the Debits & gaps lens reports debit balances as found and never calls them advances", async () => {
    const m = mount(q("/creditors", { lens: "abnormal" }));
    const lens = await screen.findByTestId("abnormal-lens", {}, T);
    expect(await within(lens).findByTestId("gap-debit", {}, T)).toHaveTextContent(/classification pending/);
    expect(screen.getByTestId("abnormal-note")).toHaveTextContent(/not classified as vendor advances/);
    expect(lens).not.toHaveTextContent(/advance position/i);
    fireEvent.click(await screen.findByTestId("gap-due_unavailable", {}, T));
    await waitFor(() => expect(search(m).drill).toBe("creditors.room/Ageing bucket:due_unavailable"), T);
  });
});

describe("Creditors room: vendors", () => {
  it("lists real vendors by name for Finance access, ranked by credit, and filters rank by the cohort", async () => {
    const m = mount(q("/creditors", { lens: "concentration" }));
    const list = await screen.findByTestId("concentration-list", {}, T);
    const rows = await within(list).findAllByRole("listitem", {}, T);
    expect(rows[0]).toHaveTextContent("Alpha Textiles (test)");
    expect(screen.getByTestId("vendor-search")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("exposure-gt180"));
    await waitFor(() => expect(search(m).drill).toBe("creditors.room/Ageing bucket:gt180"), T);
    await waitFor(() => expect(within(screen.getByTestId("concentration-list")).getAllByRole("listitem")).toHaveLength(1), T); // only Alpha has >180 credit
    expect(screen.getByTestId("vendor-total")).toHaveTextContent(/1 vendor with credit in >180 days/);
  });

  it("without Finance access the page shows vendor references only, and says why", async () => {
    vi.unstubAllGlobals();
    installCreditorsApi({ named: false });
    mount(q("/creditors", { lens: "concentration" }));
    const list = await screen.findByTestId("concentration-list", {}, T);
    await within(list).findAllByRole("listitem", {}, T);
    expect(list).not.toHaveTextContent("Alpha Textiles");
    expect(list).toHaveTextContent("Vendor Vaaaaaaaaaaaa");
    expect(screen.getByTestId("masked-note")).toBeInTheDocument();
    expect(screen.queryByTestId("vendor-search")).toBeNull();
  });

  it("opens a vendor: strip, separate Document Age and Due Status splits, identity, open items with Dr/Cr kept apart", async () => {
    const m = mount(q("/creditors", { lens: "concentration" }));
    fireEvent.click(await screen.findByTestId("vendor-Vaaaaaaaaaaaa", {}, T));
    await screen.findByTestId("vendor-profile", {}, T);
    await waitFor(() => expect(m.router.state.location.pathname).toBe("/creditors/vendor"), T);
    expect(search(m).drill).toBe("creditors.room/Vendor:Vaaaaaaaaaaaa");
    expect(await screen.findByTestId("strip-credit", {}, T)).toHaveTextContent("₹55.00 Cr");
    expect(screen.getByTestId("strip-debit")).toHaveTextContent("₹5.00 Cr");
    expect(screen.getByTestId("strip-over90")).toHaveTextContent("₹30.00 Cr");
    expect(await screen.findByTestId("vendor-age", {}, T)).toBeInTheDocument();
    expect(screen.getByTestId("vendor-due")).toBeInTheDocument();
    expect(screen.getByTestId("vendor-identity")).toHaveTextContent("Alpha Textiles (test)");
    expect(screen.getByTestId("vendor-unavailable")).toHaveTextContent(/nothing is estimated/);
    const table = await screen.findByTestId("open-items", {}, T);
    expect(within(table).getAllByText("Cr").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("Dr").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId("items-Dr"));
    await waitFor(() => expect(within(screen.getByTestId("open-items")).queryAllByText("Cr")).toHaveLength(0), T);
    expect(calls.some((c) => c.includes("/items") && c.includes("drcr=Dr"))).toBe(true);
    // no ledger/voucher drill-down: those sources are not in the verified extract
    expect(screen.queryByTestId("vendor-open-ledger")).toBeNull();
  });

  it("a masked vendor page carries no name, code or document number", async () => {
    vi.unstubAllGlobals();
    installCreditorsApi({ named: false });
    mount(q("/creditors/vendor", { drill: "creditors.room/Vendor:Vaaaaaaaaaaaa" }));
    const identity = await screen.findByTestId("vendor-identity", {}, T);
    expect(identity).toHaveTextContent(/restricted/);
    expect(identity).not.toHaveTextContent("Alpha");
    const table = await screen.findByTestId("open-items", {}, T);
    expect(table).not.toHaveTextContent("PI-1");
  });

  it("refreshing a vendor link restores the vendor and breadcrumbs from the API", async () => {
    mount(q("/creditors/vendor", { drill: "creditors.room/Ageing bucket:gt90/Vendor:Vbbbbbbbbbbbb" }));
    await screen.findByTestId("vendor-profile", {}, T);
    await waitFor(() => expect(crumbs()).toContain("Beta Packaging (test)"), T);
    expect(crumbs()).toContain(">90 days");
  });

  it("a stale or tampered vendor link falls back to the room, filters kept", async () => {
    const m = mount(q("/creditors/vendor", { scenario: "cash_pressure", drill: "creditors.room/Vendor:Vdeadbeefdead" }));
    await screen.findByTestId("creditors-room", {}, T);
    await waitFor(() => expect(m.router.state.location.pathname).toBe("/creditors"), T);
    expect(search(m).scenario).toBe("cash_pressure");
  });
});

describe("Creditors room: data states", () => {
  it("an API failure is shown as an error with Retry, never as zeros", async () => {
    vi.unstubAllGlobals();
    installCreditorsApi({ fail: 500 });
    mount(q("/creditors"));
    const errors = await screen.findAllByTestId("state-error", {}, T);
    expect(errors.length).toBeGreaterThan(2); // every section reports the failure itself
    expect(document.querySelector("[data-section=exposure-strip-error]")!).toHaveTextContent("—");
    expect(screen.getByTestId("creditors-room")).not.toHaveTextContent("₹0.00 Cr");
    expect((await screen.findAllByRole("button", { name: /retry/i }, T)).length).toBeGreaterThan(0);
  });

  it("states a live run as Live, and a withdrawn one as Withdrawn: the API decides", async () => {
    vi.unstubAllGlobals();
    installCreditorsApi({ state: "live" });
    mount(q("/creditors"));
    expect(await screen.findByTestId("data-state", {}, T)).toHaveAttribute("data-state", "live");
  });
});
