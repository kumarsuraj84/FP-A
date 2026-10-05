import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";

/* Sales Comparison on SAMPLE data: rules shown on screen, store detail, states, navigation and branding. */

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

describe("Sales Comparison: rules, detail and states", () => {
  it("labels cohort eligibility as illustrative", async () => {
    mount("/operations/sales");
    await screen.findByTestId("cohort-caption", {}, T);
    expect(screen.getByTestId("cohort-caption")).toHaveTextContent(/Illustrative cohort rule \(sample only\)/);
    expect(screen.getByTestId("cohort-caption")).toHaveTextContent(/production rule is not yet decided/);
    expect(screen.getByTestId("contribution")).toHaveTextContent("Cohort (illustrative)");
    expect(screen.getByTestId("outside-cohort")).toHaveTextContent(/illustrative rule/);
  });

  it("shows the exact same-weekday rule, the mapped reference dates and the coverage counts", async () => {
    mount("/operations/sales");
    await screen.findByTestId("mapping", {}, T);
    expect(screen.getByTestId("mapping-rule")).toHaveTextContent(/D − 364 days \(52 whole weeks\)/);
    const details = screen.getByTestId("mapping-details");
    expect(within(details).getByTestId("map-1")).toHaveTextContent(/01 Oct 2026 Thu.*02 Oct 2025 Thu/);
    expect(within(details).getByTestId("map-4")).toHaveTextContent(/04 Oct 2026 Sun.*05 Oct 2025 Sun/);
    expect(screen.getByTestId("coverage")).toHaveTextContent(/76 of 76 store-days have data/); // 19 comparable stores x 4 days
  });

  it("an unequal custom period shows sales per included store-day beside the totals", async () => {
    mount("/operations/sales");
    await screen.findByTestId("kpi-strip", {}, T);
    expect(screen.queryByTestId("kpi-sales-note")).toBeNull();
    fireEvent.click(screen.getByTestId("mode-custom"));
    fireEvent.click(screen.getByTestId("cohort-all"));
    const note = screen.getByTestId("kpi-sales").textContent ?? "";
    expect(note).toMatch(/Per store-day with data/);
    expect(note).toMatch(/Coverage: current [\d,]+ of [\d,]+, reference [\d,]+ of [\d,]+ store-days/);
    expect(note).toMatch(/not comparable-store growth/);
    expect(screen.getByTestId("plan-note")).toHaveTextContent(/not like-for-like/);
  });

  it("a reference period with no data says so and shows growth as a dash", async () => {
    mount("/operations/sales");
    await screen.findByTestId("kpi-strip", {}, T);
    fireEvent.click(screen.getByTestId("mode-custom"));
    fireEvent.change(screen.getByTestId("ref-start"), { target: { value: "2020-01-01" } });
    fireEvent.change(screen.getByTestId("ref-end"), { target: { value: "2020-01-04" } });
    // before any store opened, nothing is comparable: the page says so instead of showing a total of zero
    expect(screen.getByTestId("no-eligible")).toHaveTextContent(/No stores are in this cohort/);
    fireEvent.click(screen.getByTestId("cohort-all"));
    expect(screen.getByTestId("no-reference")).toHaveTextContent(/not as 0% or infinity/);
    expect(screen.getByTestId("kpi-sales-growth")).toHaveTextContent("—");
    expect(screen.getByTestId("sales-comparison").textContent ?? "").not.toMatch(/NaN|Infinity|undefined|null/);
  });

  it("the sample Bills → ABV example is separate, labelled invented, and reconciles; the real bridge stays unavailable", async () => {
    mount("/operations/sales");
    await screen.findByTestId("bridge-example", {}, T);
    expect(screen.getByTestId("bridge-example")).toHaveTextContent(/Invented figures · design example only/);
    expect(screen.getByTestId("bridge-example-note")).toHaveTextContent(/not production evidence/);
    expect(screen.getByTestId("ex-bills-effect")).toHaveTextContent("−₹1.00 L");
    expect(screen.getByTestId("ex-abv-effect")).toHaveTextContent("+₹45,000");
    expect(screen.getByTestId("ex-total").textContent).toBe(screen.getByTestId("ex-delta").textContent);
    expect(screen.getByTestId("ex-total")).toHaveTextContent("−₹55,000");
    expect(screen.getByTestId("unavailable-bridge")).toHaveTextContent(/real data/);
    expect(screen.getByTestId("kpi-bills")).toHaveTextContent("Unavailable");
  });

  it("the store detail view carries its own sample banner and coverage, and shows missing days as dashes", async () => {
    mount("/operations/sales");
    await screen.findByTestId("contribution", {}, T);
    fireEvent.click(screen.getByTestId("cohort-all"));
    fireEvent.click(screen.getByTestId("open-S13"));
    const d = await screen.findByTestId("store-detail", {}, T);
    expect(within(d).getByTestId("detail-sample-banner")).toHaveTextContent(/SAMPLE DATA/);
    expect(within(d).getByTestId("detail-reason")).toHaveTextContent(/Illustrative rule/);
    expect(within(d).getByTestId("detail-coverage")).toHaveTextContent(/current 2 of 4, reference 4 of 4/);
    expect(within(d).getByTestId("detail-cur-2")).toHaveTextContent("—"); // 2 Oct 2026: no row for this store
    expect(within(d).getByTestId("detail-cur-3")).toHaveTextContent("—"); // 3 Oct 2026: no row for this store
    expect(within(d).getByTestId("detail-cur-1")).not.toHaveTextContent("—");
    expect(within(d).getByTestId("detail-ref-2")).not.toHaveTextContent("—");
  });

  it("closes the detail with the close button and with Escape", async () => {
    mount("/operations/sales");
    await screen.findByTestId("contribution", {}, T);
    fireEvent.click(screen.getByTestId("open-S03"));
    await screen.findByTestId("store-detail", {}, T);
    fireEvent.click(screen.getByTestId("close-detail"));
    expect(screen.queryByTestId("store-detail")).toBeNull();
    fireEvent.click(screen.getByTestId("open-S03"));
    await screen.findByTestId("store-detail", {}, T);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("store-detail")).toBeNull());
  });

  it("loading and empty states replace the numbers, never show zeros, and keep the sample banner", async () => {
    mount("/operations/sales");
    await screen.findByTestId("kpi-strip", {}, T);
    fireEvent.change(screen.getByTestId("sample-state"), { target: { value: "loading" } });
    expect(screen.getByTestId("loading")).toBeInTheDocument();
    expect(screen.queryByTestId("kpi-strip")).toBeNull();
    fireEvent.change(screen.getByTestId("sample-state"), { target: { value: "empty" } });
    expect(screen.getByTestId("empty")).toHaveTextContent(/rather than a row of zeros/);
    expect(screen.queryByTestId("kpi-strip")).toBeNull();
    expect(screen.getByTestId("sample-banner")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("sample-state"), { target: { value: "normal" } });
    expect(screen.getByTestId("kpi-strip")).toBeInTheDocument();
  });
});

describe("Navigation and branding", () => {
  it("keeps / as the CFO Command Center and offers a visible link to the Home page", async () => {
    mount("/");
    const link = await screen.findByTestId("link-home", {}, T);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument(); // still the finance shell
    fireEvent.click(link);
    await screen.findByTestId("landing", {}, T);
  });

  it("goes from Home to Finance and back, and to Sales Comparison and back", async () => {
    mount("/home");
    await screen.findByTestId("landing", {}, T);
    fireEvent.click(screen.getByTestId("portal-nav-finance"));
    await screen.findByTestId("link-home", {}, T);
    fireEvent.click(screen.getByTestId("link-home"));
    await screen.findByTestId("landing", {}, T);
    fireEvent.click(screen.getByTestId("tile-sales"));
    await screen.findByTestId("sales-comparison", {}, T);
    fireEvent.click(screen.getByTestId("portal-nav-home"));
    await screen.findByTestId("landing", {}, T);
  });

  it("keeps the existing CityKart branding (the CK mark) in the Home header", async () => {
    mount("/home");
    const header = await screen.findByTestId("portal-header", {}, T);
    expect(header).toHaveTextContent("CK");
    expect(header).toHaveTextContent("CityKart Analytics");
  });
});
