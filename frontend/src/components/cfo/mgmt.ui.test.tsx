import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";
import { buildPnl, buildStores } from "@/test/mgmtFixture";
import { installMgmtApi } from "@/test/mgmtApi";
import { checkStores } from "./mgmt/MgmtStoresPage";

/* The Management P&L pages run on the real /api/v1/mgmt API. These tests serve them a SYNTHETIC API (test/mgmtFixture.ts). */

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
const cellText = (id: string) => screen.getByTestId(id).textContent ?? "";
const exact = (id: string) => screen.getByTestId(id).getAttribute("data-exact");

afterEach(() => vi.unstubAllGlobals());

const MIS_ORDER = ["revenue", "other_operating_income", "total_income", "material_cost", "material_margin", "rent", "employee_cost", "power_fuel", "advertisement", "freight", "other_expenses", "total_store_expenses", "store_ebitda", "dc_cost", "ho_cost", "total_corporate", "corporate_ebitda", "one_time", "ebitda_post_one_time"];

describe("Management P&L: the MIS table", () => {
  it("lists the MIS lines in order, then the % of income block, with the fixture totals", async () => {
    installMgmtApi();
    mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    const rows = [...screen.getByTestId("mgmt-table").querySelectorAll("tbody tr[data-testid^='row-']")].map((r) => r.getAttribute("data-testid")!.slice(4));
    expect(rows.slice(0, MIS_ORDER.length)).toEqual(MIS_ORDER);
    expect(rows.slice(MIS_ORDER.length).every((k) => k.startsWith("pct_"))).toBe(true);
    expect(rows).toContain("pct_corporate_ebitda");
    expect(screen.getByTestId("pct-block-head")).toHaveTextContent(/% of total income/i);
    // labels as the finance team writes them
    for (const l of ["Revenue from operations", "Other operating income", "Total income", "Material cost", "Material margin", "Power and fuel", "Freight forwarding", "Total store expenses", "Store EBITDA", "DC cost", "HO cost", "Total corporate cost", "Corporate EBITDA", "One-time expense", "EBITDA post one-time"]) {
      expect(screen.getByTestId("mgmt-table")).toHaveTextContent(l);
    }
    // Aug-26 as published
    expect(cellText("cell-revenue-2026-08")).toBe("127.32");
    expect(cellText("cell-material_cost-2026-08")).toBe("−92.32");
    expect(cellText("cell-store_ebitda-2026-08")).toBe("9.74");
    expect(cellText("cell-dc_cost-2026-08")).toBe("−2.22");
    expect(cellText("cell-ho_cost-2026-08")).toBe("−4.18");
    expect(cellText("cell-corporate_ebitda-2026-08")).toBe("3.34");
    // Apr-Aug totals
    expect(cellText("cell-revenue-total")).toBe("611.95");
    expect(cellText("cell-store_ebitda-total")).toBe("92.83");
    expect(cellText("cell-corporate_ebitda-total")).toBe("63.63");
    expect(cellText("cell-ebitda_post_one_time-total")).toBe("62.80");
    expect(cellText("cell-corporate_ebitda-2026-08".replace("2026-08", "2026-04"))).not.toBe("—");
    expect(screen.getByTestId("strip-corp-value")).toHaveTextContent("63.63");
    expect(cellText("cell-pct_corporate_ebitda-2026-08")).toBe("2.6%");
    expect(screen.getByTestId("real-state")).toHaveTextContent(/Management view/);
  });

  it("toggles Book / Adjustment / Total and highlights the cells that carry an adjustment", async () => {
    installMgmtApi();
    mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    expect(screen.getByTestId("mgmt-table")).toHaveAttribute("data-mode", "total");
    expect(screen.getByTestId("mode-total")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("cell-material_cost-2026-08")).toHaveAttribute("data-adjusted", "true");
    expect(screen.getByTestId("cell-revenue-2026-08")).toHaveAttribute("data-adjusted", "false");
    fireEvent.click(screen.getByTestId("mode-book"));
    expect(cellText("cell-material_cost-2026-08")).toBe("−91.16");
    expect(screen.getByTestId("mgmt-table")).toHaveAttribute("data-mode", "book");
    fireEvent.click(screen.getByTestId("mode-adjustment"));
    expect(cellText("cell-material_cost-2026-08")).toBe("−1.16");
    expect(cellText("cell-dc_cost-2026-08")).toBe("−1.31");
    expect(cellText("cell-revenue-2026-08")).toBe("0.00");
    fireEvent.click(screen.getByTestId("mode-total"));
    expect(cellText("cell-material_cost-2026-08")).toBe("−92.32");
    // book + adjustment = total, to the exact value
    const c = screen.getByTestId("cell-material_cost-2026-08");
    expect(Number(c.getAttribute("data-exact"))).toBeCloseTo(-92.32, 4);
  });

  it("offers a Reclass layer only when approved corrections move something, and Total = book + reclass + adjustment", async () => {
    installMgmtApi();
    mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    expect(screen.queryByTestId("mode-reclass")).toBeNull();                       // no correction in the fixture: no extra layer
    cleanup();
    vi.unstubAllGlobals();
    installMgmtApi({
      pnl: (u) => {
        const r = buildPnl(u.searchParams.get("from_month") ?? undefined, u.searchParams.get("to_month") ?? undefined);
        for (const l of r.lines) {
          const add = (t: { book: number | null; reclass?: number | null; adjustment: number | null; total: number | null }, rc: number) => { t.reclass = rc; t.total = (t.book ?? 0) + rc + (t.adjustment ?? 0); };
          if (l.kind === "pct") continue;
          for (const m of Object.keys(l.values)) add(l.values[m], l.key === "rent" ? 0.2 : l.key === "other_expenses" ? -0.2 : 0);
          add(l.total, l.key === "rent" ? 0.2 : l.key === "other_expenses" ? -0.2 : 0);
        }
        return r;
      },
    });
    mount("/mgmt");
    await screen.findByTestId("mode-reclass", {}, T);
    fireEvent.click(screen.getByTestId("mode-reclass"));
    expect(cellText("cell-rent-2026-08")).toBe("0.20");
    expect(cellText("cell-other_expenses-2026-08")).toBe("−0.20");
    expect(screen.getByTestId("mgmt-table")).toHaveAttribute("data-mode", "reclass");
  });

  it("clicking a line shows the adjustments behind it", async () => {
    installMgmtApi();
    mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    fireEvent.click(screen.getByTestId("line-material_cost"));
    const panel = await screen.findByTestId("mgmt-adjustments", {}, T);
    await within(panel).findByTestId("adj-1", {}, T);
    expect(panel).toHaveTextContent("COGS correction: 1% of net sales");
    expect(panel).not.toHaveTextContent("Gratuity");
    // a single cell narrows to its month; April has no adjustment on this line in the register
    fireEvent.click(screen.getByLabelText("Material cost Apr 26: adjustments"));
    await screen.findByTestId("mgmt-adjustments-empty", {}, T);
    // a subtotal explains itself instead of inventing rows
    fireEvent.click(screen.getByTestId("line-store_ebitda"));
    expect(await screen.findByTestId("mgmt-adjustments-empty", {}, T)).toHaveTextContent(/subtotal/i);
    fireEvent.click(screen.getByTestId("mgmt-adjustments-close"));
    expect(screen.queryByTestId("mgmt-adjustments")).toBeNull();
  });

  it("shows the warnings, including the missing entity and the provisional adjustments", async () => {
    installMgmtApi();
    mount("/mgmt");
    const banner = await screen.findByTestId("mgmt-warnings", {}, T);
    expect(banner).toHaveTextContent("Citykart Ventures not in gold: stop-gap from workbook");
    expect(banner).toHaveTextContent("provisional adjustments included");
    expect(banner).toHaveTextContent("Intercompany loan, interest and service charges are read from the ledger");
    expect(screen.getAllByTestId("mgmt-warning")).toHaveLength(3); // repeated by the P&L response, shown once
  });

  it("asks the API for the chosen months and for proposed adjustments, and narrows the columns", async () => {
    const calls = installMgmtApi();
    mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    fireEvent.change(screen.getByTestId("mgmt-from"), { target: { value: "2026-08" } });
    await waitFor(() => expect(screen.queryByTestId("col-2026-04")).toBeNull(), T);
    expect(calls.some((c) => c.includes("/mgmt-api/pnl?") && c.includes("from_month=2026-08") && c.includes("to_month=2026-08") && c.includes("include_proposed=true"))).toBe(true);
    fireEvent.click(screen.getByTestId("mgmt-include-proposed"));
    await waitFor(() => expect(calls.some((c) => c.includes("include_proposed=false"))).toBe(true), T);
    expect(cellText("cell-corporate_ebitda-total")).toBe("3.34");
  });

  it("shows an em dash with a reason for a missing figure, never a zero", async () => {
    installMgmtApi({
      pnl: (u) => {
        const d = buildPnl(u.searchParams.get("from_month") ?? undefined, u.searchParams.get("to_month") ?? undefined);
        const l = d.lines.find((x) => x.key === "pct_corporate_ebitda")!;
        l.values["2026-08"] = { book: null, adjustment: null, total: null };
        return d;
      },
    });
    mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    const c = screen.getByTestId("cell-pct_corporate_ebitda-2026-08");
    expect(c).toHaveTextContent("—");
    expect(c.getAttribute("title")).toMatch(/Not computed/);
    expect(c.getAttribute("data-exact")).toBe("");
  });

  it("with the API down it says so and shows no figures", async () => {
    installMgmtApi({ fail: 500 });
    mount("/mgmt");
    const box = await screen.findByTestId("mgmt-unavailable", {}, T);
    expect(box).toHaveTextContent(/No management P&L run is available/);
    expect(box).toHaveTextContent(/Nothing is shown rather than a demo figure/);
    expect(screen.queryByTestId("mgmt-table")).toBeNull();
  });
});

describe("Management P&L: navigation", () => {
  it("has a left-nav entry and links between the four pages", async () => {
    installMgmtApi();
    const m = mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    expect(screen.getByTestId("nav-mgmt")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("nav-profitability")).not.toHaveAttribute("aria-current");
    expect(screen.getByTestId("real-asof")).toHaveTextContent("09 Oct 2026");
    expect(screen.getByTestId("real-state")).toHaveTextContent(/Management view/);
    const tabs = screen.getByTestId("mgmt-tabs");
    expect(within(tabs).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/mgmt", "/mgmt/stores", "/mgmt/store-expenses", "/mgmt/dc-expenses", "/mgmt/reconciliation", "/mgmt/mapping"]);
    fireEvent.click(screen.getByTestId("mgmt-tab-stores"));
    await screen.findByTestId("stores-table", {}, T);
    expect(m.router.state.location.pathname).toBe("/mgmt/stores");
    expect(screen.getByTestId("nav-mgmt")).toHaveAttribute("aria-current", "page");
  });
});

describe("Management P&L: entity", () => {
  it("defaults to consolidated, switches through the URL and asks the API for that entity", async () => {
    const calls = installMgmtApi();
    const m = mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    expect(screen.getByTestId("mgmt-entity")).toHaveAttribute("data-entity", "consolidated");
    for (const l of ["Consolidated", "SubCo - Citykart Stores", "HoldCo - Citykart Ventures"]) expect(screen.getByTestId("mgmt-entity")).toHaveTextContent(l);
    expect(calls.some((c) => c.includes("/mgmt-api/pnl?") && c.includes("entity=consolidated"))).toBe(true);
    fireEvent.click(screen.getByTestId("entity-holdco"));
    await waitFor(() => expect(m.router.state.location.search).toMatchObject({ entity: "holdco" }), T);
    await waitFor(() => expect(cellText("cell-dc_cost-2026-08")).toBe("−0.89"), T);
    expect(calls.some((c) => c.includes("/mgmt-api/pnl?") && c.includes("entity=holdco"))).toBe(true);
    expect(cellText("cell-revenue-2026-08")).toBe("0.00");
    // sub-links keep the entity
    expect(screen.getByTestId("mgmt-tab-stores").getAttribute("href")).toMatch(/entity=holdco/);
    fireEvent.click(screen.getByTestId("entity-consolidated"));
    await waitFor(() => expect(cellText("cell-dc_cost-2026-08")).toBe("−2.22"), T);
    expect(m.router.state.location.search).not.toHaveProperty("entity");
  });

  it("opens straight onto an entity from the address, and SubCo plus HoldCo add up to the consolidated MIS", async () => {
    installMgmtApi();
    mount("/mgmt?entity=subco");
    await screen.findByTestId("mgmt-table", {}, T);
    expect(screen.getByTestId("entity-subco")).toHaveAttribute("aria-pressed", "true");
    const sub = Number(exact("cell-corporate_ebitda-total"));
    const hold = buildPnl(undefined, undefined, true, "holdco").lines.find((l) => l.key === "corporate_ebitda")!.total.total!;
    expect(sub + hold).toBeCloseTo(63.63, 2);
    expect(sub).toBeGreaterThan(63.63);
  });

  it("an unknown entity falls back to consolidated", async () => {
    installMgmtApi();
    mount("/mgmt?entity=nonsense");
    await screen.findByTestId("mgmt-table", {}, T);
    expect(screen.getByTestId("mgmt-entity")).toHaveAttribute("data-entity", "consolidated");
  });

  it("shows interest income and finance cost below EBITDA, apart from the EBITDA lines", async () => {
    installMgmtApi();
    mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    const below = screen.getByTestId("mgmt-below");
    expect(below).toHaveTextContent("Below EBITDA");
    expect(below).toHaveTextContent("Not part of Corporate EBITDA");
    expect(below).toHaveTextContent("Interest income");
    expect(below).toHaveTextContent("Finance cost");
    expect(screen.getByTestId("mgmt-table").querySelector("[data-testid='row-interest_income']")).toBeNull();
    expect(cellText("cell-corporate_ebitda-total")).toBe("63.63"); // unchanged by the block
  });

  it("shows intercompany eliminations distinctly in the adjustments list", async () => {
    installMgmtApi();
    mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    fireEvent.click(screen.getByTestId("line-ho_cost"));
    const row = await screen.findByTestId("adj-9", {}, T);
    expect(row).toHaveAttribute("data-elimination", "true");
    expect(screen.getByTestId("adj-9-elimination")).toHaveTextContent("Elimination");
    expect(screen.getByTestId("adj-9-counterparty")).toHaveTextContent("Citykart Stores (CKSPL)");
  });

  it("applies the entity to the store league and the reconciliation", async () => {
    const calls = installMgmtApi();
    mount("/mgmt/stores?entity=holdco");
    await screen.findByTestId("stores-empty", {}, T);
    expect(screen.getByTestId("stores-empty")).toHaveTextContent("no stores");
    expect(calls.some((c) => c.includes("/mgmt-api/stores?") && c.includes("entity=holdco"))).toBe(true);
    fireEvent.click(screen.getByTestId("entity-subco"));
    await screen.findByTestId("store-1001", {}, T);
    expect(screen.getByTestId("stores-reconciles")).toHaveAttribute("data-ok", "true");
    expect(cellText("stores-rate-value")).toBe("3.08%");
    fireEvent.click(screen.getByTestId("mgmt-tab-recon"));
    await screen.findByTestId("recon-table", {}, T);
    expect(calls.some((c) => c.includes("/mgmt-api/reconciliation?") && c.includes("entity=subco"))).toBe(true);
    expect(screen.getByTestId("mgmt-entity")).toHaveAttribute("data-entity", "subco");
  });
});

describe("Management store league", () => {
  it("states the blended rate, and the total row adds up to the P&L", async () => {
    installMgmtApi();
    mount("/mgmt/stores");
    await screen.findByTestId("stores-table", {}, T);
    expect(cellText("stores-rate-value")).toBe("5.03%");
    expect(screen.getByTestId("stores-rate-note")).toHaveTextContent(/pro rata to revenue from operations/);
    const d = buildStores();
    expect(screen.getByTestId("stores-reconciles")).toHaveAttribute("data-ok", "true");
    expect(Number(exact("total-net_sales"))).toBeCloseTo(127.32, 3);
    expect(Number(exact("total-rgm"))).toBeCloseTo(35.65, 3);
    expect(Number(exact("total-store_expenses"))).toBeCloseTo(-25.91, 3);
    expect(Number(exact("total-four_wall"))).toBeCloseTo(9.74, 3);
    expect(Number(exact("total-apportioned"))).toBeCloseTo(-6.4, 2);
    expect(Number(exact("total-ebitda_after"))).toBeCloseTo(3.34, 2);
    expect(cellText("total-ebitda_after")).toBe("3.34");
    expect(screen.getByTestId("stores-total")).toHaveTextContent(`Total (${d.rows.length} stores)`);
    // every store row: 4-wall = RGM + store expenses, after = 4-wall + apportioned
    for (const r of d.rows) {
      const cells = [...screen.getByTestId(`store-${r.site_code}`).querySelectorAll("td[data-exact]")].map((c) => Number(c.getAttribute("data-exact")));
      const [, rgm, exp, four, app, after] = cells;
      expect(four).toBeCloseTo(rgm + exp, 3);
      expect(after).toBeCloseTo(four + app, 3);
    }
  });

  it("sorts, filters, and the total follows the filter", async () => {
    installMgmtApi();
    mount("/mgmt/stores");
    await screen.findByTestId("stores-table", {}, T);
    const d = buildStores();
    const ids = () => [...screen.getByTestId("stores-table").querySelectorAll("tbody tr[data-testid^='store-']")].map((r) => r.getAttribute("data-testid")!.slice(6));
    const net = (id: string) => d.rows.find((r) => r.site_code === id)!.net_sales!;
    const desc = ids().map(net);
    expect(desc).toEqual([...desc].sort((a, b) => b - a));
    expect(ids()).toHaveLength(d.rows.length);
    fireEvent.click(screen.getByTestId("sort-net_sales")); // toggles to ascending
    const asc = ids().map(net);
    expect(asc).toEqual([...asc].sort((a, b) => a - b));
    expect(asc[0]).toBeLessThan(asc[asc.length - 1]);
    fireEvent.change(screen.getByTestId("stores-type"), { target: { value: "NEW" } });
    const newOnes = d.rows.filter((r) => r.store_type === "NEW");
    expect(ids().sort()).toEqual(newOnes.map((r) => r.site_code).sort());
    expect(screen.getByTestId("stores-total")).toHaveTextContent(`Total (${newOnes.length} of ${d.rows.length} stores)`);
    expect(Number(exact("total-net_sales"))).toBeCloseTo(newOnes.reduce((s, r) => s + (r.net_sales ?? 0), 0), 3);
    fireEvent.change(screen.getByTestId("stores-search"), { target: { value: "no such store" } });
    expect(screen.getByTestId("stores-empty")).toBeInTheDocument();
  });

  it("flags stores that do not add up to the summary", () => {
    const d = buildStores();
    expect(checkStores(d).ok).toBe(true);
    const bad = { ...d, rows: d.rows.map((r, i) => (i === 0 ? { ...r, net_sales: (r.net_sales ?? 0) + 0.5 } : r)) };
    const res = checkStores(bad);
    expect(res.ok).toBe(false);
    expect(res.problems[0]).toMatch(/Revenue from operations/);
    expect(checkStores({ ...d, summary: { ...d.summary, reconciles: false } }).ok).toBe(false);
  });
});

describe("Management reconciliation", () => {
  it("shows TIED / VARIANCE per month, the variance cells, override reasons and the bridge", async () => {
    installMgmtApi();
    mount("/mgmt/reconciliation");
    await screen.findByTestId("recon-table", {}, T);
    const status = (m: string) => within(screen.getByTestId(`recon-month-${m}`)).getByTestId("status-pill").getAttribute("data-status");
    expect(status("2026-04")).toBe("TIED");
    expect(status("2026-05")).toBe("VARIANCE");
    expect(status("2026-06")).toBe("VARIANCE");
    expect(status("2026-07")).toBe("TIED");
    expect(status("2026-08")).toBe("TIED");
    expect(screen.getByTestId("recon-months")).toHaveTextContent("3 of 5 months tied");
    // a variance cell is an exception and carries its reason; a tied cell does not
    const v = screen.getByTestId("recon-other_operating_income-2026-05");
    expect(v).toHaveAttribute("data-tied", "false");
    expect(v.className).toMatch(/oklch\(0\.97_0\.03_25\)/);
    expect(v).toHaveTextContent("−0.031");
    expect(screen.getByTestId("override-other_operating_income-2026-05")).toHaveTextContent(/Hard-coded \+0\.031/);
    expect(screen.getByTestId("recon-revenue-2026-08")).toHaveAttribute("data-tied", "true");
    expect(screen.getByTestId("recon-revenue-2026-08")).toHaveTextContent("tied");
    expect(screen.getByTestId("recon-overrides")).toHaveTextContent("Other expenses");
    // the standing bridge from portal books to the MIS
    expect(screen.getByTestId("bridge-0")).toHaveTextContent("87.29");
    expect(screen.getByTestId("bridge-1")).toHaveTextContent("Citykart Ventures OU not in portal");
    expect(screen.getByTestId("bridge-1")).toHaveTextContent("−14.52");
    expect(screen.getByTestId("bridge-1")).toHaveTextContent("Missing data");
    const last = screen.getByTestId("bridge-13");
    expect(last).toHaveAttribute("data-subtotal", "true");
    expect(last).toHaveTextContent("63.68");
    expect(last).toHaveTextContent("Published 63.63");
  });

  it("reconciles the bridge: the steps add up to the subtotals", async () => {
    installMgmtApi();
    mount("/mgmt/reconciliation");
    await screen.findByTestId("bridge-table", {}, T);
    const amt = (i: number) => Number(screen.getByTestId(`bridge-${i}`).querySelector("td[data-exact]")!.getAttribute("data-exact"));
    let run = 0;
    for (let i = 0; i <= 10; i++) run += amt(i);
    expect(Math.abs(run - amt(11))).toBeLessThan(0.015); // 62.84 by the steps, 62.85 published: rounding in the sheet
    expect(amt(11) + amt(12)).toBeCloseTo(amt(13), 1); // 63.68
  });
});

describe("Management ledger mapping", () => {
  it("lists the map and the unmapped exceptions", async () => {
    installMgmtApi();
    mount("/mgmt/mapping");
    const ex = await screen.findByTestId("mapping-exceptions-table", {}, T);
    expect(ex).toHaveTextContent("MKTG-Loyalty/Communication");
    expect(ex).toHaveTextContent("Conflicting group");
    expect(screen.getByTestId("mapping-exceptions")).toHaveTextContent("Unmapped and conflicting ledgers (3)");
    expect(screen.getByTestId("mapping-table")).toHaveTextContent("Salaries and wages");
    fireEvent.change(screen.getByTestId("mapping-search"), { target: { value: "rent" } });
    expect(screen.getByTestId("mapping-table")).toHaveTextContent("Store rent");
    expect(screen.getByTestId("mapping-table")).not.toHaveTextContent("Salaries and wages");
  });
});

describe("Store league: partial month and nomenclature (P-06, N-09)", () => {
  it("opens on the last COMPLETE month, not the partial current month", async () => {
    const calls = installMgmtApi({ months: ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"] });
    mount("/mgmt/stores");
    await screen.findByTestId("stores-table", {}, T);
    const c = calls.find((x) => x.includes("/mgmt-api/stores?"))!;
    expect(c).toContain("month=2026-09");
    expect(c).not.toContain("2026-10");
    expect((screen.getByTestId("mgmt-to") as HTMLSelectElement).value).toBe("2026-09");
    expect(within(screen.getByTestId("mgmt-to")).getByRole("option", { name: /Oct.*partial/ })).toBeInTheDocument();
    expect(screen.queryByTestId("stores-partial")).toBeNull();
  });

  it("says the partial month is partial when the user picks it", async () => {
    installMgmtApi({ months: ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"] });
    mount("/mgmt/stores");
    await screen.findByTestId("stores-table", {}, T);
    fireEvent.change(screen.getByTestId("mgmt-from"), { target: { value: "2026-10" } });
    fireEvent.change(screen.getByTestId("mgmt-to"), { target: { value: "2026-10" } });
    expect(await screen.findByTestId("stores-partial", {}, T)).toHaveTextContent(/partial month/);
  });

  it("uses the portal vocabulary: Material Margin and Revenue from operations, never RGM or Net sales", async () => {
    installMgmtApi();
    mount("/mgmt/stores");
    await screen.findByTestId("stores-table", {}, T);
    const page = screen.getByTestId("mgmt-room").textContent ?? "";
    expect(page).toMatch(/Material Margin/);
    expect(page).toMatch(/Revenue from operations/);
    expect(page).not.toMatch(/\bRGM\b|Net sales|net sales|retail gross margin/);
  });
});

describe("Corporate EBITDA basis tag (P-04)", () => {
  it("tags the strip 'Management total' and the table row by the layer shown", async () => {
    installMgmtApi();
    mount("/mgmt");
    await screen.findByTestId("mgmt-table", {}, T);
    expect(within(screen.getByTestId("strip-corp")).getByTestId("basis-tag")).toHaveTextContent("Management total");
    expect(within(screen.getByTestId("row-corporate_ebitda")).getByTestId("basis-tag")).toHaveTextContent("Management total");
    fireEvent.click(screen.getByTestId("mode-book"));
    await waitFor(() => expect(within(screen.getByTestId("row-corporate_ebitda")).getByTestId("basis-tag")).toHaveTextContent("Management: book layer"), T);
  });
});
