import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { billKey, liveEntry } from "@/api/entryLive";
import { crumbHref, entryHref, ledgerListHref, parseEntrySearch, parseListSearch, pushTrail, safePath, tillHref } from "@/lib/entryLinks";
import { installCreditorsApi } from "@/test/creditorsFixture";
import { E1, E2, ENTRY_RUN, installEntryApi } from "@/test/entryFixture";
import { installPnlApi } from "@/test/pnlFixture";

/* The voucher drill runs on the real Entry API. These tests serve it a SYNTHETIC API (invented vouchers, round numbers). */

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
const trailOf = (items: { l: string; h: string }[]) => JSON.stringify(items);

afterEach(() => vi.unstubAllGlobals());

describe("entry links: the URL carries the state and cannot send the user off-site", () => {
  it("only same-app paths are accepted into a trail", () => {
    expect(safePath("/creditors/vendor?x=1")).toBe("/creditors/vendor?x=1");
    for (const bad of ["//evil.example", "https://evil.example/x", "javascript:alert(1)", "/a\\b", "", "creditors"]) expect(safePath(bad)).toBeUndefined();
    const p = parseEntrySearch({ ref: 9000000001, trail: [{ l: "ok", h: "/cash" }, { l: "bad", h: "//evil.example" }, { l: "", h: "/cash" }] });
    expect(p.ref).toBe("9000000001");
    expect(p.trail).toEqual([{ l: "ok", h: "/cash" }]);
  });

  it("round-trips a voucher list address and a crumb carries the steps before it", () => {
    const trail = pushTrail(pushTrail([], "Profitability", "/profitability?ps=10"), "Salary · Alpha", "/entry/list?site=10&glcode=77");
    const href = entryHref("9000000001", trail, "I555");
    const url = new URL(href, "http://x");
    expect(url.pathname).toBe("/entry");
    const back = parseEntrySearch(Object.fromEntries([...url.searchParams].map(([k, v]) => [k, k === "trail" ? JSON.parse(v) : v])));
    expect(back).toMatchObject({ ref: "9000000001", bill: "I555" });
    expect(back.trail).toHaveLength(2);
    const list = new URL(crumbHref(back.trail, 1), "http://x");
    expect(list.pathname).toBe("/entry/list");
    expect(JSON.parse(list.searchParams.get("trail")!)).toEqual([{ l: "Profitability", h: "/profitability?ps=10" }]);
    expect(parseListSearch(Object.fromEntries(new URL(ledgerListHref({ site: "10", glcode: "77", from_month: "2026-04", to_month: "2026-09", basis: "posted", offset: 100 }), "http://x").searchParams))).toMatchObject({ site: "10", glcode: "77", from_month: "2026-04", basis: "posted", offset: 100 });
    expect(tillHref(439, [], "Alpha")).toBe("/entry/till?site=439&name=Alpha");
  });

  it("a creditors item id maps to the bare postcode the link table is keyed by", () => {
    expect(billKey("I1115181905")).toBe("1115181905");
    expect(billKey("555")).toBe("555");
  });
});

describe("Entry client", () => {
  it("falls back to the masked route when Finance access is not granted, and says so", async () => {
    const calls = installEntryApi({ named: false });
    const r = await liveEntry.entry(ENTRY_RUN, E1.ref);
    expect(r.named).toBe(false);
    expect(calls).toEqual([`/entry-api/runs/${ENTRY_RUN}/finance/entry/${E1.ref}`, `/entry-api/runs/${ENTRY_RUN}/entry/${E1.ref}`]);
  });
  it("uses the Finance route when granted, and never sends an Authorization header from the browser", async () => {
    installEntryApi();
    const f = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const r = await liveEntry.entry(ENTRY_RUN, E1.ref);
    expect(r.named).toBe(true);
    expect(JSON.stringify(f.mock.calls[0][1] ?? {})).not.toMatch(/authorization|bearer/i);
  });
});

describe("Voucher page", () => {
  it("shows the header, ALL lines with ledger, group, party, site, debit and credit, and a balanced indicator", async () => {
    installEntryApi();
    mount(`/entry?ref=${E1.ref}`);
    await screen.findByTestId("entry-strip", {}, T);
    expect(text("fact-type")).toMatch(/CSM/);
    expect(text("fact-type")).toMatch(/Retail Sale/);
    expect(text("fact-number")).toBe("Entry number47675");
    expect(text("fact-date")).toBe("Entry date05 Oct 2026");
    expect(text("fact-site")).toMatch(/68/);
    expect(screen.getByTestId("release-status")).toHaveAttribute("data-status", "Unposted");
    await screen.findByText("Paytm (test)", {}, T);
    for (let n = 1; n <= 5; n++) expect(screen.getByTestId(`entry-line-${n}`)).toBeInTheDocument();
    const l2 = screen.getByTestId("entry-line-2");
    expect(l2).toHaveTextContent("Mob Wallet Receivable");
    expect(l2).toHaveTextContent("UNMAPPED");
    expect(l2).toHaveTextContent("JGR");
    expect(l2).toHaveTextContent("₹41,796.00");
    expect(screen.getByTestId("entry-line-1")).toHaveTextContent("Auto created till entry");
    expect(screen.getByTestId("entry-line-3").querySelector("[data-exact='64031.59']")).not.toBeNull();
    expect(exact("total-dr")).toBe("68344");
    expect(exact("total-cr")).toBe("68344.00");
    expect(screen.getByTestId("balance-badge")).toHaveAttribute("data-balanced", "true");
    expect(screen.queryByTestId("gap-note")).toBeNull();
  });

  it("flags an unbalanced voucher as a gap in the gold extract, with the difference, not as a posting error", async () => {
    installEntryApi();
    mount(`/entry?ref=${E2.ref}`);
    await screen.findByTestId("entry-balance", {}, T);
    expect(screen.getByTestId("balance-badge")).toHaveAttribute("data-balanced", "false");
    expect(text("balance-difference")).toMatch(/₹1,000\.00/);
    expect(text("gap-note")).toMatch(/cost-tag lines/);
    expect(text("gap-note")).toMatch(/About 9%/);
    expect(text("gap-note")).toMatch(/not a posting error/);
    expect(text("fact-number")).toBe("Entry numberJV-12");
  });

  it("masked view: pseudonymous party reference, no narration, no entry number, and says it is masked", async () => {
    installEntryApi({ named: false });
    mount(`/entry?ref=${E1.ref}`);
    await screen.findByTestId("entry-lines", {}, T);
    expect(screen.getByTestId("entry-line-2")).toHaveTextContent("Vabc123def456");
    expect(screen.getByTestId("entry-page").textContent).not.toMatch(/Auto created till entry|Paytm|47675/);
    expect(text("fact-number")).toBe(`Voucher key${E1.ref}`);
    expect(screen.getByTestId("entry-page")).toHaveTextContent(/Masked view/);
    expect(screen.queryByText("Narration")).toBeNull();
  });

  it("evidence panel: source, run, as-of, coverage, attachment status and the bills pointing at the voucher", async () => {
    installEntryApi();
    mount(`/entry?ref=${E1.ref}`);
    await screen.findByTestId("entry-evidence", {}, T);
    const ev = text("entry-evidence");
    expect(ev).toMatch(/gold_fpa\.voucher_lines/);
    expect(ev).toMatch(/ENTRY-TEST/);
    expect(ev).toMatch(/09 Oct 2026/);
    expect(ev).toMatch(/01 Apr 2025/);
    expect(text("entry-attachment")).toMatch(/No verified attachment source available/);
    expect(text("entry-linked-bills")).toMatch(/bill 555/);
    expect(screen.getByTestId("data-state")).toHaveAttribute("data-state", "live");
  });

  it("breadcrumb shows where the user came from and goes back to it, with the earlier steps kept", async () => {
    installEntryApi();
    const trail = [{ l: "Profitability · Alpha", h: "/profitability?ps=10" }, { l: "Salary · Alpha", h: "/entry/list?site=10&glcode=77" }];
    const m = mount(`/entry?ref=${E1.ref}&trail=${encodeURIComponent(trailOf(trail))}`);
    await screen.findByTestId("entry-strip", {}, T);
    expect(text("entry-crumbs")).toBe("CityKartProfitability · AlphaSalary · AlphaCSM · 47675");
    fireEvent.click(screen.getByTestId("entry-crumb-1"));
    await screen.findByTestId("entry-list-page", {}, T);
    expect(m.router.state.location.pathname).toBe("/entry/list");
    expect(m.router.state.location.search).toMatchObject({ site: 10, glcode: 77, trail: [{ l: "Profitability · Alpha", h: "/profitability?ps=10" }] });
  });

  it("says plainly when there is no voucher in the address, and when the API fails", async () => {
    installEntryApi();
    mount("/entry");
    expect(await screen.findByTestId("entry-no-ref", {}, T)).toHaveTextContent(/Find a voucher/);
    expect(screen.getByTestId("finder-open")).toBeDisabled();                       // a landing the user can act on, not a dead end
    fireEvent.change(screen.getByLabelText("Voucher key"), { target: { value: "424242" } });
    expect(screen.getByTestId("finder-open")).toBeEnabled();
    vi.unstubAllGlobals();
    installEntryApi({ fail: 500 });
    mount(`/entry?ref=${E1.ref}`);
    expect((await screen.findAllByTestId("state-error", {}, T)).length).toBeGreaterThan(0);
  });

  it("an unknown voucher is reported as not found", async () => {
    installEntryApi();
    mount("/entry?ref=424242");
    const box = await screen.findByTestId("entry-not-in-extract", {}, T);
    expect(box).toHaveTextContent(/not in the loaded finance extract/);
    expect(within(box).getByTestId("try-other-books")).toHaveTextContent(/HoldCo/);          // the other company's books are one click away
  });
});

describe("Ledger to vouchers list (P&L drill)", () => {
  const list = (extra = "") => `/entry/list?site=10&glcode=77&from_month=2026-04&to_month=2026-09&title=${encodeURIComponent("Salary · Alpha")}${extra}`;

  it("lists one row per voucher, newest first, with the parent figure and whether the rows add up", async () => {
    const calls = installEntryApi();
    mount(list());
    await screen.findByTestId("list-table", {}, T);
    expect(calls.some((c) => c.includes("ledger-entries") && c.includes("site=10") && c.includes("glcode=77") && c.includes("from_month=2026-04") && c.includes("to_month=2026-09"))).toBe(true);
    expect(exact("list-vouchers-value")).toBe("230");
    expect(exact("list-net-value")).toBe("-230000");
    expect(screen.getAllByTestId(/^list-row-/)).toHaveLength(100);
    expect(text("list-pager")).toMatch(/Vouchers 1 to 100 of 230/);
    expect(text("list-reconciles")).toMatch(/Showing 100 of 230/);
    expect(screen.getByTestId("entry-list-page").querySelector("h1 + div")?.textContent).toMatch(/Apr 2026 to Sep/);
  });

  it("pages with the address (offset), and a short list reconciles to the ledger figure", async () => {
    installEntryApi();
    mount(list("&offset=200"));
    await screen.findByTestId("list-table", {}, T);
    expect(screen.getAllByTestId(/^list-row-/)).toHaveLength(30);
    expect(text("list-pager")).toMatch(/Vouchers 201 to 230 of 230/);
    expect(screen.queryByTestId("list-next")).toBeNull();
    expect(screen.getByTestId("list-prev")).toBeInTheDocument();
  });

  it("opens a voucher with the list as the way back", async () => {
    installEntryApi();
    const m = mount(`${list()}&trail=${encodeURIComponent(trailOf([{ l: "Profitability · Alpha", h: "/profitability?ps=10" }]))}`);
    await screen.findByTestId("list-table", {}, T);
    fireEvent.click(screen.getByTestId("open-entry-9100000000"));
    await waitFor(() => expect(m.router.state.location.pathname).toBe("/entry"), T);
    const s = m.router.state.location.search as { ref: unknown; trail: { l: string; h: string }[] };
    expect(String(s.ref)).toBe("9100000000");
    expect(s.trail.map((t) => t.l)).toEqual(["Profitability · Alpha", "Salary · Alpha"]);
    expect(s.trail[1].h).toContain("/entry/list?");
  });

  it("asks for nothing without a ledger or a store", async () => {
    installEntryApi();
    mount("/entry/list");
    expect(await screen.findByTestId("entry-list-empty", {}, T)).toBeInTheDocument();
  });
});

describe("Store till: stores, days, vouchers", () => {
  it("lists days with the parent balance and reconciliation, and opens a day's vouchers on the Cash Drawer ledger", async () => {
    const calls = installEntryApi();
    const m = mount("/entry/till?site=439&name=Alpha");
    await screen.findByTestId("till-days-table", {}, T);
    expect(text("till-reconciles")).toMatch(/Days: rows add up/);
    expect(screen.getByTestId("till-reconciles")).toHaveAttribute("data-ok", "true");
    expect(text("till-day-2026-03-31")).toMatch(/opening balance/);
    expect(screen.queryByTestId("till-day-open-2026-03-31")).toBeNull();
    expect(calls.some((c) => c.includes("/till/stores/439/days") && c.includes(`cash_run=CASH-TEST`))).toBe(true);
    fireEvent.click(screen.getByTestId("till-day-open-2026-10-07"));
    await screen.findByTestId("list-table", {}, T);
    expect(m.router.state.location.pathname).toBe("/entry/list");
    expect(calls.some((c) => c.includes("ledger-entries") && c.includes("glcode=1000000008") && c.includes("site=439") && c.includes("from_date=2026-10-07") && c.includes("to_date=2026-10-07"))).toBe(true);
    expect(text("entry-list-page")).toMatch(/Cash Drawer · Alpha · 07 Oct 2026/);
    expect(text("entry-crumbs")).toMatch(/Till · Alpha/);
  });

  it("shows a red failure state, not a quiet mismatch, when the days do not add up", async () => {
    installEntryApi({ tillBroken: true });
    mount("/entry/till?site=439");
    await screen.findByTestId("till-days-table", {}, T);
    expect(screen.getByTestId("till-reconciles")).toHaveAttribute("data-ok", "false");
    expect(text("till-reconciles")).toMatch(/do NOT add up/);
  });

  it("without a store it lists the stores and opens one", async () => {
    installEntryApi();
    const m = mount("/entry/till");
    await screen.findByTestId("till-stores-table", {}, T);
    expect(text("till-reconciles")).toMatch(/Stores: rows add up/);
    fireEvent.click(screen.getByTestId("till-store-439"));
    await screen.findByTestId("till-days-table", {}, T);
    expect(m.router.state.location.search).toMatchObject({ site: 439 });
  });
});

describe("Entry points", () => {
  it("Creditors vendor profile: a bill asks for its link on demand, STRONG opens the voucher with the bill carried along", async () => {
    installCreditorsApi();
    const calls = installEntryApi();
    const m = mount(`/creditors/vendor?${new URLSearchParams({ period: "ytdfy27", compare: "budget", scenario: "normal", drill: "creditors.room/Vendor:Vaaaaaaaaaaaa" })}`);
    const table = await screen.findByTestId("open-items", {}, T);
    expect(calls.some((c) => c.includes("/link"))).toBe(false); // nothing is asked until the user asks
    const btn = within(table).getAllByRole("button", { name: /Voucher/ })[0];
    expect(btn.getAttribute("data-testid")).toMatch(/^bill-voucher-/);
    // the fixture's item ids are not link-table keys: the API answers NOT_LINKED with a reason
    fireEvent.click(btn);
    const cell = await screen.findByTestId(btn.getAttribute("data-testid")!, {}, T);
    await waitFor(() => expect(cell).toHaveTextContent(/Not linked/), T);
    expect(cell).toHaveTextContent(/No voucher in the register carries this bill's document code/);
    expect(cell.querySelector("a")).toBeNull();
    expect(calls.some((c) => c.includes("/creditors/items/") && c.includes("creditors_run=GOLD-TEST"))).toBe(true);
    expect(m.router.state.location.pathname).toBe("/creditors/vendor");
  });

  it("a linked bill (STRONG) opens the voucher, and the voucher page shows the link evidence and a way back to the vendor", async () => {
    installEntryApi();
    const trail = [{ l: "Creditors · Alpha", h: "/creditors/vendor?drill=creditors.room%2FVendor%3AVaaaaaaaaaaaa" }];
    mount(`/entry?ref=${E1.ref}&bill=I555&trail=${encodeURIComponent(trailOf(trail))}`);
    const ev = await screen.findByTestId("bill-evidence", {}, T);
    await waitFor(() => expect(within(ev).getByTestId("link-status")).toHaveAttribute("data-status", "STRONG"), T);
    expect(ev).toHaveTextContent(/document code/);
    expect(screen.getByTestId("bill-amount-note")).toHaveTextContent(/cannot be checked/);
    expect(screen.getByTestId("entry-crumb-0")).toHaveAttribute("href", "/creditors/vendor?drill=creditors.room%2FVendor%3AVaaaaaaaaaaaa");
  });

  it("a bill older than the register says why it has no voucher", async () => {
    installEntryApi();
    mount(`/entry?ref=${E1.ref}&bill=I777`);
    const ev = await screen.findByTestId("bill-evidence", {}, T);
    await waitFor(() => expect(within(ev).getByTestId("link-status")).toHaveAttribute("data-status", "NOT_LINKED"), T);
    expect(ev).toHaveTextContent(/does not reach back/);
  });

  it("P&L: a ledger line has a Vouchers link carrying the store, ledger and period, with the P&L view as the way back", async () => {
    installPnlApi();
    installEntryApi();
    mount("/profitability?ps=10&pg=02-Employee%20Cost&pf=2026-04&pe=2026-09");
    const a = await screen.findByTestId("ledger-vouchers-77", {}, T);
    const href = new URL(a.getAttribute("href")!, "http://x");
    expect(href.pathname).toBe("/entry/list");
    expect(href.searchParams.get("site")).toBe("10");
    expect(href.searchParams.get("glcode")).toBe("77");
    expect(href.searchParams.get("from_month")).toBe("2026-04");
    expect(href.searchParams.get("to_month")).toBe("2026-09");
    const trail = JSON.parse(href.searchParams.get("trail")!) as { l: string; h: string }[];
    expect(trail).toHaveLength(1);
    expect(trail[0].h).toBe("/profitability?ps=10&pg=02-Employee+Cost&pf=2026-04&pe=2026-09");
    expect(screen.getByTestId("store-panel")).toBeInTheDocument();
  });

  it("P&L: a normal visit (no state in the address) is unchanged: no store open", async () => {
    installPnlApi();
    mount("/profitability");
    await screen.findByTestId("pnl-strip", {}, T);
    expect(screen.queryByTestId("store-panel")).toBeNull();
  });

  it("Cash: each till store links to its days with the Cash page as the way back", async () => {
    installCreditorsApi();
    installEntryApi();
    mount("/cash");
    const a = await screen.findByTestId("till-drill-100", {}, T);
    const href = new URL(a.getAttribute("href")!, "http://x");
    expect(href.pathname).toBe("/entry/till");
    expect(href.searchParams.get("site")).toBe("100");
    expect(href.searchParams.get("name")).toBe("Test Store 01");
    expect((JSON.parse(href.searchParams.get("trail")!) as { l: string }[])[0].l).toBe("Liquidity & Working Capital");
  });
});
