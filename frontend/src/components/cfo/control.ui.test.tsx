import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "@/routeTree.gen";

/* The governed-change screens run on a SYNTHETIC API (invented names and round numbers). fetch is replaced by a small router that records every write. */

const T = { timeout: 5000 };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(status < 400 ? { data } : data), { status, headers: { "Content-Type": "application/json" } });
type Call = { method: string; url: string; body: unknown; headers: Record<string, string> };

const ME = (role: string, must = false) => ({ user_id: "u1", email: "mgr@example.test", display_name: "Asha Manager", role, must_change_password: must });
const ADJ = (over: Record<string, unknown> = {}) => ({
  adjustment_id: "a1", month: "2026-08", entity: "SUBCO", management_line: "employee_cost", location_type: "STORES", location_code: null, adjustment_type: "PROVISION", basis_type: "FIXED", amount_rupees: "-100000.0000", amount_cr: "-0.0100",
  effect: "COST", rate: null, rate_metric: null, metric_snapshot: null, supporting_reference: "Gratuity policy", narrative: "monthly gratuity provision for stores", linked_policy: null, status: "REVIEW", provisional: true,
  counts_in_management_total: false, template_id: null, created_by: "u1", created_at: "2026-10-01T10:00:00Z", approved_by: null, approved_at: null, activated_at: null, ...over,
});
const IMPACT = { month: "2026-08", entity: "SUBCO", line: "employee_cost", location_type: "STORES", amount_cr: "-0.0100", already_in_management_total: false, note: "Management Total = Book + Reclass + approved Adjustment.",
  views: { consolidated: { employee_cost: { before: "-10.0000", after: "-10.0100", change: "-0.0100" }, total_store_expenses: { before: "-20.0000", after: "-20.0100", change: "-0.0100" }, store_ebitda: { before: "30.0000", after: "29.9900", change: "-0.0100" },
    total_corporate: { before: "-5.0000", after: "-5.0000", change: "0.0000" }, corporate_ebitda: { before: "25.0000", after: "24.9900", change: "-0.0100" } } } };
const CASE = (over: Record<string, unknown> = {}) => ({
  case_id: "c1", exception_type: "LINE_MONTH_MOVE", domain: "EXPENSE", entity: "CONSOLIDATED", site_code: null, metric_id: "rent", period: "2026-08", subject_key: "rent", title: "Rent moved +30% against 2026-07", recurrence_of_case_id: null,
  recurrence_no: 1, final_score: "68.00", band: "HIGH", escalated: false, evidence: { observed_cr: "-1.3", reference_cr: "-1.0", threshold_version: "t1", calibration_status: "UNCALIBRATED" }, drill_link: "/mgmt", status: "OPEN", owner_user_id: null,
  due_date: null, next_action: null, closure_reason: null, first_detected_at: "2026-10-02T10:00:00Z", last_detected_at: "2026-10-02T10:00:00Z", detection_count: 1, overdue: false, recurring: false, ...over,
});

const CK = (key: string, title: string, status: string, summary: string, over: Record<string, unknown> = {}) => ({ key, title, status, effective: status, summary, evidence: {}, link: null, manual: false, signature: "s" + key, signoff: null, ...over });
const READY = (over: Record<string, unknown> = {}) => ({
  entity: "SUBCO", month: "2026-09", period_status: "SOFT_CLOSED", outcome: "BLOCKED", readiness_pct: 60, management_pnl: "PROVISIONAL", can_management_close: false, can_final_close: false,
  blockers: [{ key: "provisions", title: "Required provisions generated", summary: "Missing: Gratuity." }], note: "Blockers decide the close.",
  checks: [CK("revenue_loaded", "Revenue loaded for the whole month", "PASS", "Revenue 90.00 Cr."), CK("provisions", "Required provisions generated", "BLOCKED", "Missing: Gratuity."), CK("adjustments", "Adjustments approved", "ATTENTION", "2 adjustment(s) not yet active"),
    CK("intercompany", "Intercompany reconciliation signed off", "PENDING", "Review the intercompany tie, then sign it off.", { manual: true }), CK("pnl_certification", "Management P&L certified", "PENDING", "A controller certifies.", { manual: true })], ...over,
});

function install(opts: { readiness?: unknown; me: unknown | null; adjustments?: unknown[]; corrections?: unknown; cases?: unknown[]; calls?: Call[]; loginMe?: unknown }) {
  const calls = opts.calls ?? [];
  let me = opts.me;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body, headers: (init?.headers ?? {}) as Record<string, string> });
    if (url.startsWith("/auth-api/me")) return me ? json(me) : json({ detail: "Sign in required." }, 401);
    if (url.startsWith("/auth-api/login")) { me = opts.loginMe ?? opts.me ?? ME("fpa_manager"); return json(me); }
    if (url.startsWith("/auth-api/assignable")) return json([{ user_id: "u2", email: "o@example.test", display_name: "Omar Owner", role: "fpa_manager" }]);
    if (url.startsWith("/adjustments-api/preview") || /\/adjustments-api\/[^/]+\/preview/.test(url)) return json(IMPACT);
    if (url.startsWith("/adjustments-api/calendar")) return json({ months: ["2026-08", "2026-09"], legend: [], rows: [{ template_id: "t1", name: "Gratuity", entity: "SUBCO", line: "employee_cost", status: "ACTIVE", cells: { "2026-08": { state: "active", adjustment_id: "a1", amount_cr: "-0.0100" }, "2026-09": { state: "missing", adjustment_id: null, amount_cr: null } } }] });
    if (url.startsWith("/adjustments-api/templates")) return json([]);
    if (/\/adjustments-api\/[^/?]+\/history/.test(url)) return json([{ seq: 1, event_type: "CREATED", from_status: null, to_status: "DRAFT", comment: null, at: "2026-10-01T10:00:00Z", actor_email: "mgr@example.test" }]);
    if (/\/adjustments-api\/[^/?]+\/(approve|submit|activate)/.test(url) && method === "POST") return json(ADJ({ status: "APPROVED" }));
    if (url.startsWith("/adjustments-api") && method === "POST") return json(ADJ({ status: "DRAFT" }));
    if (url.startsWith("/adjustments-api")) return json({ total: (opts.adjustments ?? []).length, items: opts.adjustments ?? [] });
    if (url.startsWith("/corrections-api/source-lines")) return json({ voucher: "V-1", entity: "RETAIL", groups: ["02-Employee Cost", "16-Miscellaneous Expenses"], lines: [
      { cost_tag_key: 11, fingerprint: "abc123def456", ledger: "Salary", entry_date: "2026-08-05", site_code: 10, amount_cr: "-0.0500", management_group: "02-Employee Cost", month: "2026-08", correctable: true, not_correctable_reason: null, active_correction: null },
      { cost_tag_key: 12, ledger: "Stock Transfer", entry_date: "2026-08-05", site_code: 10, amount_cr: "1.0000", management_group: null, month: null, correctable: false, not_correctable_reason: "Not a Management P&L line", active_correction: null }] });
    if (url.startsWith("/corrections-api/preview")) return json({ lines: 1, stores: 1, source_total_cr: "-0.0500", by_group: { "02-Employee Cost": "0.0500", "16-Miscellaneous Expenses": "-0.0500" }, by_month: { "2026-08": "0.0000" }, net_by_group_cr: "0.0000", net_by_month_cr: "0.0000", note: "Both nets are zero." });
    if (url.startsWith("/corrections-api") && method === "POST") return json({ request_id: "r1", scope_type: "LINE", correction_type: "GROUP", source_entity: "RETAIL", status: "DRAFT", reason_code: "WRONG_CLASSIFICATION", reason_text: "booked to the wrong group", evidence_reference: "ticket 1", requested_by: "u1", requested_at: "2026-10-03T10:00:00Z", approved_at: null, line_count: 1, source_total_cr: "-0.0500", counts_in_management_total: false });
    if (url.startsWith("/corrections-api")) return json(opts.corrections ?? { total: 0, counts: {}, items: [] });
    if (url.startsWith("/close-api/readiness")) return json(opts.readiness ?? READY());
    if (url.startsWith("/close-api/history")) return json([{ from_status: "OPEN", to_status: "SOFT_CLOSED", reason: "month complete and reviewed", at: "2026-10-03T10:00:00Z", actor: "mgr@example.test" }]);
    if (url.startsWith("/close-api/signoff") || url.startsWith("/close-api/period")) return json(READY({ period_status: "SOFT_CLOSED" }));
    if (url.startsWith("/inbox-api/thresholds")) return json({ version: "t1", calibration_status: "UNCALIBRATED", thresholds: {} });
    if (/\/inbox-api\/[^/?]+\/history/.test(url)) return json([{ seq: 1, event_type: "DETECTED", from_status: null, to_status: "OPEN", comment: null, at: "2026-10-02T10:00:00Z", actor: "system" }]);
    if (/\/inbox-api\/[^/?]+\/(assign|close|acknowledge)/.test(url) && method === "POST") return json(CASE({ owner_user_id: "u2" }));
    if (/\/inbox-api\/c1/.test(url)) return json(CASE());
    if (url.startsWith("/inbox-api")) return json({ total: (opts.cases ?? []).length + 5, shown: (opts.cases ?? []).length, bands: { CRITICAL: 1, HIGH: 3, MEDIUM: 1 }, unowned: 5, overdue: 1, items: opts.cases ?? [], score_note: "Uncalibrated" });
    return json({ detail: `unexpected ${method} ${url}` }, 404);
  }));
  return calls;
}

function mount(href: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [href] }), context: { queryClient } });
  render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);
}
afterEach(() => vi.unstubAllGlobals());

describe("sign-in", () => {
  it("asks for sign-in with no session, signs in, and never puts a password anywhere but the request body", async () => {
    const calls = install({ me: null, loginMe: ME("fpa_manager"), adjustments: [] });
    mount("/control/adjustments");
    await screen.findByTestId("login", {}, T);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "mgr@example.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Correct-Horse-Battery-9" } });
    fireEvent.click(screen.getByTestId("login-submit"));
    await screen.findByTestId("whoami", {}, T);
    const login = calls.find((c) => c.url.startsWith("/auth-api/login"))!;
    expect(login.method).toBe("POST");
    expect(login.headers["X-FPA-Request"]).toBe("1");
    expect(login.url).not.toMatch(/Correct-Horse/);
    expect(calls.every((c) => !c.url.includes("password"))).toBe(true);
  });

  it("forces a new password before anything else when the temporary one is still in use", async () => {
    install({ me: ME("fpa_manager", true) });
    mount("/control/inbox");
    await screen.findByTestId("change-password", {}, T);
    expect(screen.queryByTestId("case-list")).toBeNull();
    expect(screen.getByTestId("change-submit")).toBeDisabled();
  });

  it("shows the Users tab to an administrator only", async () => {
    install({ me: ME("fpa_manager"), cases: [] });
    mount("/control/inbox");
    await screen.findByTestId("whoami", {}, T);
    expect(screen.queryByTestId("control-tab-users")).toBeNull();
    expect(screen.getByTestId("control-tab-adjustments")).toBeInTheDocument();
  });
});

describe("Adjustments and Provisions", () => {
  it("lists the register, approves a row in review, and sends the writes with the header", async () => {
    const calls = install({ me: ME("fpa_manager"), adjustments: [ADJ()] });
    mount("/control/adjustments");
    const row = await screen.findByTestId("adj-row-a1", {}, T);
    expect(row).toHaveTextContent("Employee cost");
    expect(row).toHaveTextContent("-0.01");
    fireEvent.click(row);
    await screen.findByTestId("adjustment-detail", {}, T);
    expect(screen.getByTestId("detail-amount")).toHaveTextContent("-0.01 Cr");
    fireEvent.click(await screen.findByTestId("act-approve"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/adjustments-api/a1/approve")).toBe(true));
    expect(calls.find((c) => c.url === "/adjustments-api/a1/approve")!.headers["X-FPA-Request"]).toBe("1");
  });

  it("a viewer can read the register but is offered no action", async () => {
    install({ me: ME("viewer"), adjustments: [ADJ()] });
    mount("/control/adjustments");
    fireEvent.click(await screen.findByTestId("adj-row-a1", {}, T));
    await screen.findByTestId("adjustment-detail", {}, T);
    expect(screen.queryByTestId("act-approve")).toBeNull();
    expect(screen.queryByTestId("act-submit")).toBeNull();
  });

  it("rejecting needs a reason of ten characters", async () => {
    install({ me: ME("fpa_manager"), adjustments: [ADJ()] });
    mount("/control/adjustments");
    fireEvent.click(await screen.findByTestId("adj-row-a1", {}, T));
    const reject = await screen.findByTestId("act-reject", {}, T);
    expect(reject).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "amount not supported by policy" } });
    expect(reject).toBeEnabled();
  });

  it("the entry form previews the effect on Store and Corporate EBITDA and posts a positive amount with its effect", async () => {
    const calls = install({ me: ME("fpa_manager"), adjustments: [] });
    mount("/control/adjustments");
    fireEvent.click(await screen.findByTestId("adj-tab-new", {}, T));
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "100000" } });
    fireEvent.change(screen.getByLabelText("Supporting reference"), { target: { value: "Gratuity policy" } });
    fireEvent.change(screen.getByLabelText("Narrative"), { target: { value: "monthly gratuity provision for stores" } });
    fireEvent.click(screen.getByTestId("preview-impact"));
    const impact = await screen.findByTestId("impact", {}, T);
    expect(within(impact).getAllByText("Store EBITDA").length).toBeGreaterThan(0);
    expect(within(impact).getAllByText("Corporate EBITDA").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId("save-draft"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/adjustments-api")).toBe(true));
    const body = calls.find((c) => c.method === "POST" && c.url === "/adjustments-api")!.body as Record<string, unknown>;
    expect(body).toMatchObject({ amount_rupees: "100000", effect: "COST", basis_type: "FIXED", entity: "SUBCO" });
  });

  it("the provision calendar shows active and missing months", async () => {
    install({ me: ME("fpa_manager"), adjustments: [] });
    mount("/control/adjustments");
    fireEvent.click(await screen.findByTestId("adj-tab-calendar", {}, T));
    expect((await screen.findByTestId("cal-Gratuity-2026-08", {}, T)).dataset.state).toBe("active");
    expect(screen.getByTestId("cal-Gratuity-2026-09").dataset.state).toBe("missing");
  });
});

describe("Corrections workbench", () => {
  it("loads a voucher's lines, blocks non-P&L lines, previews a net-zero move and creates a LINE correction without any amount", async () => {
    const calls = install({ me: ME("fpa_manager") });
    mount("/control/corrections?entity=RETAIL&voucher=V-1");
    await screen.findByTestId("correction-form", {}, T);
    fireEvent.click(screen.getByTestId("load-lines"));
    await screen.findByTestId("source-lines", {}, T);
    expect(screen.getByTestId("source-read")).toHaveTextContent(/checked again at approval/);
    expect(screen.getByTestId("source-lines")).toHaveTextContent("abc123def456");
    expect(screen.getByLabelText("Select line 12")).toBeDisabled();
    expect(screen.getByLabelText("Select line 11")).toBeChecked();
    fireEvent.change(screen.getByLabelText("Corrected management group"), { target: { value: "16-Miscellaneous Expenses" } });
    fireEvent.change(screen.getByLabelText("Evidence reference"), { target: { value: "ticket 1" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "booked to the wrong management group" } });
    fireEvent.click(screen.getByTestId("preview-correction"));
    const prev = await screen.findByTestId("correction-preview", {}, T);
    expect(within(prev).getByTestId("net-group")).toHaveTextContent("0.00");
    expect(within(prev).getByTestId("net-month")).toHaveTextContent("0.00");
    fireEvent.click(screen.getByTestId("save-correction-draft"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/corrections-api")).toBe(true));
    const body = calls.find((c) => c.method === "POST" && c.url === "/corrections-api")!.body as Record<string, unknown>;
    expect(body).toMatchObject({ scope: "LINE", line_keys: [11], corrected_group: "16-Miscellaneous Expenses", source_entity: "RETAIL" });
    expect(Object.keys(body).some((k) => k.includes("amount"))).toBe(false);
  });

  it("the queue shows counts by status and an empty state that points to the voucher", async () => {
    install({ me: ME("fpa_manager"), corrections: { total: 0, counts: { SUBMITTED: 2, ACTIVE: 5 }, items: [] } });
    mount("/control/corrections");
    await screen.findByTestId("correction-queue", {}, T);
    await waitFor(() => expect(screen.getByTestId("cor-count-awaiting")).toHaveTextContent("2"));
    expect(screen.getByTestId("cor-count-active")).toHaveTextContent("5");
    expect(screen.getByTestId("correction-empty")).toHaveTextContent(/voucher/);
  });
});

describe("Exception Inbox", () => {
  it("shows the top of the ranked list with band counts, unowned and overdue, and the calibration status", async () => {
    install({ me: ME("fpa_manager"), cases: [CASE()] });
    mount("/control/inbox");
    expect(await screen.findByTestId("case-c1", {}, T)).toHaveTextContent("Rent moved +30%");
    expect(screen.getByTestId("case-list")).toHaveTextContent(/Top 20 requiring attention now/);
    expect(screen.getByTestId("band-HIGH")).toHaveTextContent("3");
    expect(screen.getByTestId("unowned")).toHaveTextContent("5 without an owner");
    expect(screen.getByTestId("overdue")).toHaveTextContent("1 overdue");
    await waitFor(() => expect(screen.getByTestId("calibration")).toHaveTextContent(/uncalibrated/));
    expect(screen.getByTestId("more")).toHaveTextContent("5 more not shown");
  });

  it("assigns an owner with a due date and a next action", async () => {
    const calls = install({ me: ME("fpa_manager"), cases: [CASE()] });
    mount("/control/inbox");
    fireEvent.click(await screen.findByTestId("case-c1", {}, T));
    await screen.findByTestId("assign-box", {}, T);
    await waitFor(() => expect(within(screen.getByTestId("assign-box")).getByRole("option", { name: "Omar Owner" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "u2" } });
    fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "2026-10-20" } });
    fireEvent.change(screen.getByLabelText("Next action"), { target: { value: "check the rent invoices" } });
    fireEvent.click(screen.getByTestId("assign"));
    await waitFor(() => expect(calls.some((c) => c.url === "/inbox-api/c1/assign")).toBe(true));
    expect(calls.find((c) => c.url === "/inbox-api/c1/assign")!.body).toEqual({ owner_user_id: "u2", due_date: "2026-10-20", next_action: "check the rent invoices" });
  });

  it("closing needs a reason, and a viewer sees no workflow buttons", async () => {
    install({ me: ME("finance_reviewer"), cases: [CASE()] });
    mount("/control/inbox");
    fireEvent.click(await screen.findByTestId("case-c1", {}, T));
    const close = await screen.findByTestId("act-close", {}, T);
    expect(close).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "agreed with finance as seasonal" } });
    expect(close).toBeEnabled();
  });

  it("a viewer is offered no workflow action and a recurring case says so", async () => {
    install({ me: ME("viewer"), cases: [CASE({ recurring: true, recurrence_no: 3 })] });
    mount("/control/inbox");
    fireEvent.click(await screen.findByTestId("case-c1", {}, T));
    await screen.findByTestId("case-detail", {}, T);
    expect(screen.queryByTestId("act-acknowledge")).toBeNull();
    expect(screen.queryByTestId("act-close")).toBeNull();
    expect(screen.queryByTestId("assign-box")).toBeNull();
    expect(screen.getByTestId("recurring")).toHaveTextContent("OCCURRENCE 3");
  });
});


describe("Month-end close", () => {
  it("shows the outcome, the blockers and the checklist with each item's status", async () => {
    install({ me: ME("fpa_manager") });
    mount("/control/close");
    expect((await screen.findByTestId("close-outcome", {}, T)).dataset.outcome).toBe("BLOCKED");
    expect(screen.getByTestId("close-blockers")).toHaveTextContent("Missing: Gratuity.");
    expect(screen.getByTestId("status-revenue_loaded").dataset.status).toBe("PASS");
    expect(screen.getByTestId("status-provisions").dataset.status).toBe("BLOCKED");
    expect(screen.getByTestId("pnl-state")).toHaveTextContent("PROVISIONAL");
    expect(screen.getByTestId("readiness-pct")).toHaveTextContent("60%");
    expect(screen.getByTestId("period-status-text")).toHaveTextContent("Soft closed");
  });

  it("a blocker cannot be overridden, an attention item can with a comment, and a manual item is signed off", async () => {
    const calls = install({ me: ME("finance_reviewer") });
    mount("/control/close");
    await screen.findByTestId("close-checklist", {}, T);
    expect(screen.queryByTestId("sign-provisions")).toBeNull();
    fireEvent.click(screen.getByTestId("sign-adjustments"));
    const confirm = screen.getByTestId("confirm-adjustments");
    expect(confirm).toBeDisabled();
    fireEvent.change(within(screen.getByTestId("check-adjustments").nextElementSibling as HTMLElement).getByLabelText("Comment"), { target: { value: "both are covered by the policy" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(calls.some((c) => c.url.startsWith("/close-api/signoff"))).toBe(true));
    expect(calls.find((c) => c.url.startsWith("/close-api/signoff"))!.body).toMatchObject({ entity: "SUBCO", month: expect.any(String), check_key: "adjustments", decision: "OVERRIDDEN" });
    expect(screen.getByTestId("sign-intercompany")).toHaveTextContent("Sign off");
    expect(screen.queryByTestId("sign-pnl_certification")).toBeNull();       // only a controller certifies
  });

  it("period actions need a reason, and management close stays disabled while blockers remain", async () => {
    const calls = install({ me: ME("controller") });
    mount("/control/close");
    await screen.findByTestId("close-checklist", {}, T);
    expect(screen.getByTestId("sign-pnl_certification")).toBeInTheDocument();
    expect(screen.getByTestId("period-management-close")).toBeDisabled();
    fireEvent.change(screen.getAllByLabelText("Reason").slice(-1)[0], { target: { value: "reopening for a late invoice" } });
    expect(screen.getByTestId("period-management-close")).toBeDisabled();       // blockers remain even with a reason
    fireEvent.click(screen.getByTestId("period-reopen"));
    await waitFor(() => expect(calls.some((c) => c.url === "/close-api/period/reopen")).toBe(true));
    expect(calls.find((c) => c.url === "/close-api/period/reopen")!.body).toMatchObject({ entity: "SUBCO", reason: "reopening for a late invoice" });
  });
});
