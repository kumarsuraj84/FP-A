import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";

/* Home and Sales Comparison run on SAMPLE data. These tests check that the screen says so, keeps unavailable measures unavailable and shows its reference dates. */

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
  return { router };
}

describe("Analytics Home", () => {
  it("keeps Finance, Operations and Merchandising apart and says what stands behind each tile", async () => {
    mount("/home");
    await screen.findByTestId("landing", {}, T);
    for (const a of ["finance", "operations", "merchandising"]) expect(screen.getByTestId(`area-${a}`)).toBeInTheDocument();
    expect(within(screen.getByTestId("area-finance")).getByTestId("tile-creditors")).toBeInTheDocument();
    expect(within(screen.getByTestId("area-operations")).getByTestId("tile-sales")).toBeInTheDocument();
    expect(screen.getByTestId("tone-creditors")).toHaveTextContent("Real data · verified candidate · not live");
    expect(screen.getByTestId("tone-command")).toHaveTextContent("Demo data");
    expect(screen.getByTestId("tone-sales")).toHaveTextContent("Sample-data prototype");
    expect(screen.getByTestId("tone-merch")).toHaveTextContent("Not started");
  });

  it("not-started tiles are not links", async () => {
    mount("/home");
    await screen.findByTestId("landing", {}, T);
    expect(screen.getByTestId("tile-merch").tagName).not.toBe("A");
    expect(screen.getByTestId("tile-merch")).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByTestId("tile-sales").tagName).toBe("A");
  });

  it("has its own header: no finance banner, no period / compare / scenario controls", async () => {
    mount("/home");
    await screen.findByTestId("portal-header", {}, T);
    expect(screen.queryByTestId("demo-banner")).toBeNull();
    expect(screen.queryByTestId("select-period")).toBeNull();
    expect(screen.queryByTestId("select-comparison")).toBeNull();
    expect(screen.queryByTestId("select-scenario")).toBeNull();
  });
});

describe("Sales Comparison (sample data)", () => {
  it("says it is sample data in the banner, the header and the data state", async () => {
    mount("/operations/sales");
    await screen.findByTestId("sales-comparison", {}, T);
    expect(screen.getByTestId("sample-banner")).toHaveTextContent(/SAMPLE DATA/);
    expect(screen.getByTestId("data-state")).toHaveTextContent("Sample data · not live");
    expect(screen.getByTestId("asof")).toHaveTextContent("04 Oct 2026");
  });

  it("keeps Bills, ABV and the bridge unavailable, with the reason, and never invents a number for them", async () => {
    mount("/operations/sales");
    await screen.findByTestId("kpi-strip", {}, T);
    for (const id of ["bills", "abv"]) {
      expect(screen.getByTestId(`kpi-${id}`)).toHaveTextContent("Unavailable");
      expect(screen.getByTestId(`kpi-${id}-value`)).toHaveTextContent("—");
    }
    expect(screen.getByTestId("kpi-bills-reason")).toHaveTextContent(/return bills are counted as bills/);
    expect(screen.getByTestId("unavailable-bridge")).toHaveTextContent(/Needs a certified bill count/);
    for (const id of ["festival", "department", "footfall", "target"]) expect(screen.getByTestId(`unavailable-${id}`)).toBeInTheDocument();
  });

  it("marks Sales as provisional and shows reference dates for the chosen basis", async () => {
    mount("/operations/sales");
    await screen.findByTestId("kpi-strip", {}, T);
    expect(screen.getByTestId("kpi-sales")).toHaveTextContent("Provisional");
    const weekdays = screen.getByTestId("ref-dates").textContent ?? "";
    expect(weekdays).toMatch(/02 Oct 2025 to 05 Oct 2025/); // 364 days before 1 to 4 Oct 2026
    fireEvent.click(screen.getByTestId("mode-same_dates"));
    expect(screen.getByTestId("ref-dates").textContent ?? "").toMatch(/01 Oct 2025 to 04 Oct 2025/);
  });

  it("the store differences add back to the total, and the total row equals the headline", async () => {
    mount("/operations/sales");
    await screen.findByTestId("kpi-strip", {}, T);
    expect(screen.getByTestId("reconcile")).toHaveTextContent(/add back to the total/);
    expect(screen.getByTestId("total-cur").textContent).toBe(screen.getByTestId("kpi-sales-value").textContent);
  });

  it("Comparable stores excludes new stores and data gaps and says why; All stores warns it is not like-for-like", async () => {
    mount("/operations/sales");
    await screen.findByTestId("contribution", {}, T);
    expect(screen.queryByTestId("row-S22")).toBeNull();
    expect(screen.queryByTestId("row-S13")).toBeNull();
    expect(screen.getByTestId("outside-cohort")).toHaveTextContent(/no data, not zero/);
    fireEvent.click(screen.getByTestId("cohort-all"));
    expect(screen.getByTestId("row-S22")).toBeInTheDocument();
    expect(screen.getByTestId("row-S13")).toBeInTheDocument();
    expect(screen.getByTestId("not-like-for-like")).toBeInTheDocument();
    expect(screen.getByTestId("gap-S13")).toBeInTheDocument();
  });

  it("a custom period of unequal length is flagged", async () => {
    mount("/operations/sales");
    await screen.findByTestId("kpi-strip", {}, T);
    fireEvent.click(screen.getByTestId("mode-custom"));
    expect(screen.getByTestId("plan-note")).toHaveTextContent(/not like-for-like/);
  });

  it("an impossible period shows a message instead of numbers", async () => {
    mount("/operations/sales");
    await screen.findByTestId("kpi-strip", {}, T);
    fireEvent.change(screen.getByTestId("cur-start"), { target: { value: "2026-10-04" } });
    fireEvent.change(screen.getByTestId("cur-end"), { target: { value: "2026-10-01" } });
    expect(screen.getByTestId("plan-problem")).toBeInTheDocument();
    expect(screen.queryByTestId("kpi-strip")).toBeNull();
  });

  it("search filters the table and never renders NaN, null or undefined", async () => {
    mount("/operations/sales");
    await screen.findByTestId("contribution", {}, T);
    fireEvent.change(screen.getByTestId("store-search"), { target: { value: "sample store 03" } });
    expect(screen.getByTestId("row-S03")).toBeInTheDocument();
    expect(screen.queryByTestId("row-S04")).toBeNull();
    fireEvent.click(screen.getByTestId("cohort-all"));
    const text = screen.getByTestId("sales-comparison").textContent ?? "";
    expect(text).not.toMatch(/NaN|undefined|null/);
  });
});
