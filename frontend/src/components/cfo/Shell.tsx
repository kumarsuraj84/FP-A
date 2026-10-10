import type { ReactNode } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { useState } from "react";
import { Banknote, CalendarCheck, ClipboardCheck, Inbox, Shuffle, ChevronRight, ChevronsLeft, ChevronsRight, CircleDot, FileSpreadsheet, Handshake, LayoutDashboard, LayoutGrid, Receipt, Route, Store, Truck, Warehouse, Wrench } from "lucide-react";
import { useCfo } from "@/context/CfoContext";
import { searchFromState } from "@/context/drillUrl";
import { CREDITORS_ORIGIN } from "@/lib/creditorNodes";
import { PROFIT_ORIGIN } from "@/lib/profitNodes";
import { CASH_ORIGIN } from "@/lib/cashNodes";
import type { DrillOrigin } from "@/types/cfo";
import { useFreshness } from "@/api/hooks";
import { useCashRun } from "@/api/cashLiveHooks";
import { usePnlRun } from "@/api/pnlLiveHooks";
import { useEntryRun } from "@/api/entryLiveHooks";
import { useMgmtRun } from "@/api/mgmtLiveHooks";
import { useLiveRun } from "@/api/creditorsLiveHooks";
import { DataStatus } from "./DataStatus";
import { COMPARISON_ORDER, COMPARISONS, PERIOD_ORDER, PERIODS, SCENARIOS, SCENARIO_ORDER } from "@/mocks/scenarios";
import type { ComparisonId, DataStateId, PeriodId, ScenarioId } from "@/types/cfo";
import { cn } from "@/lib/utils";
import { isLiveCfo, isMockApi } from "@/api";

const DATA_STATES: { id: DataStateId; label: string }[] = [
  { id: "live", label: "Normal" },
  { id: "stale", label: "Stale" },
  { id: "unavailable", label: "Unavailable" },
  { id: "error", label: "Error" },
  { id: "empty", label: "Empty" },
];

function Select<T extends string>({ label, value, options, onChange, testId, width }: { label: string; value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; testId: string; width?: string }) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
      <span className="hidden uppercase tracking-wider xl:inline">{label}</span>
      <select
        data-testid={testId}
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className={cn("h-7 cursor-pointer rounded border bg-card pl-2 pr-6 text-xs font-semibold text-foreground outline-none hover:border-primary/40 focus-visible:ring-2 focus-visible:ring-ring", width)}
      >
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Pages that are still served by the demo service even when the app runs on real data. */
export const isDemoOnlyPath = (p: string) => p.startsWith("/profitability/store");

/** Query keys the top-bar Refresh invalidates: the page's own family plus the families it reads (the expense pages use "expenses"). */
export const refreshKeysFor = (scope: RealMeta["scope"]): string[][] => (scope === "mgmt" ? [["mgmt"], ["expenses"]] : [[scope]]);

export function DemoBanner() {
  const { state, dispatch } = useCfo();
  const path = useRouterState({ select: (r) => r.location.pathname });
  const realPage = path.startsWith("/creditors") ? "Creditors" : path.startsWith("/cash") ? "Liquidity" : path === "/profitability" ? "Profitability" : path.startsWith("/mgmt") ? "Management P&L" : path.startsWith("/entry") ? "Voucher drill" : path.startsWith("/related-party") ? "Related Party Transactions" : null;
  if (isLiveCfo && isDemoOnlyPath(path)) {
    return (
      <div data-testid="demo-banner" data-real="false" data-source-mode="demo" className="flex h-6 items-center bg-[oklch(0.96_0.06_85)] px-4 text-[11px] font-medium text-[oklch(0.38_0.09_70)]">
        <span className="flex min-w-0 items-center gap-1.5">
          <CircleDot className="h-3 w-3 shrink-0" />
          <span className="truncate">Demo data - not real. This store workspace (AOP, forecast, trajectory, network comparison) is illustrative and is not read from the verified sources.</span>
        </span>
      </div>
    );
  }
  if (isLiveCfo) return null; // real data: the status chip + drawer in the top bar carries what this banner used to say
  if (realPage) {
    // this page runs on a verified mart; every module not yet connected is still demo data and the banner says so
    return (
      <div data-testid="demo-banner" data-real="true" className="flex h-6 items-center bg-[oklch(0.94_0.06_155)] px-4 text-[11px] font-medium text-[oklch(0.32_0.1_155)]">
        <span className="flex items-center gap-1.5">
          <CircleDot className="h-3 w-3" />
          {realPage} shows REAL data (verified candidate, not live). Command Center is still demo data and waits for a synchronized run: the real pages carry different as-of dates, so their figures are not one CFO position.
        </span>
      </div>
    );
  }
  return (
    <div data-testid="demo-banner" className="flex h-6 items-center justify-between bg-[oklch(0.96_0.06_85)] px-4 text-[11px] font-medium text-[oklch(0.38_0.09_70)]">
      <span className="flex items-center gap-1.5">
        <CircleDot className="h-3 w-3" />
        Demo data — financial source reconciliation pending
        {!isMockApi && !isLiveCfo && <span className="rounded bg-white/60 px-1">API configured</span>}
      </span>
      <label className="flex items-center gap-1.5 opacity-90">
        <span>Simulate data state</span>
        <select
          data-testid="select-datastate"
          aria-label="Simulate data state"
          value={state.dataState}
          onChange={(e) => dispatch({ type: "setDataState", value: e.target.value as DataStateId })}
          className="h-[18px] cursor-pointer rounded border border-[oklch(0.8_0.08_85)] bg-white/70 px-1 text-[11px] font-semibold"
        >
          {DATA_STATES.map((d) => (
            <option key={d.id} value={d.id}>
              {d.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

/** Real-data pages state their OWN as-of date and state (from the API), not the demo shell's freshness or controls. */
export interface RealMeta { asOf: string | null; state: string; stateLabel: string; updated: string | null; scope: "cash" | "cred" | "pnl" | "entry" | "mgmt"; status: "ok" | "error" | "pending" }
const STATE_TEXT: Record<string, string> = { verified_candidate: "Verified candidate · not live", live: "Live", superseded: "Superseded", withdrawn: "Withdrawn" };

function useRealMeta(): RealMeta | null {
  const path = useRouterState({ select: (r) => r.location.pathname });
  const cash = useCashRun();
  const cred = useLiveRun();
  const pnl = usePnlRun();
  const entry = useEntryRun();
  const mgmt = useMgmtRun(path.startsWith("/mgmt")); // only fetched on its own pages
  const scope = path.startsWith("/cash") ? "cash" : path.startsWith("/creditors") ? "cred" : path === "/profitability" ? "pnl" : path.startsWith("/entry") ? "entry" : path.startsWith("/mgmt") ? "mgmt" : null;
  if (!scope) return null;
  if (scope === "mgmt") {
    // the Management P&L run has no promotion state of its own: it is a management view (books plus adjustments), said as such
    if (mgmt.isError) return { asOf: null, state: "error", stateLabel: "Real data unavailable", updated: null, scope, status: "error" };
    if (!mgmt.data) return { asOf: null, state: "pending", stateLabel: "Checking…", updated: null, scope, status: "pending" };
    return { asOf: mgmt.data.as_of_date, state: "management", stateLabel: "Management view · books + adjustments", updated: null, scope, status: "ok" };
  }
  const run = scope === "cash" ? cash : scope === "pnl" ? pnl : scope === "entry" ? entry : cred;
  if (run.isError) return { asOf: null, state: "error", stateLabel: "Real data unavailable", updated: null, scope, status: "error" };
  if (!run.data) return { asOf: null, state: "pending", stateLabel: "Checking…", updated: null, scope, status: "pending" };
  const d = scope === "entry" ? { ...(run.data as { register_report_date: string; data_state: string; source_updated_at?: string }), as_of_date: (run.data as { register_report_date: string }).register_report_date } : (run.data as { as_of_date: string; data_state: string; source_updated_at?: string });
  const updated = d.source_updated_at ? new Date(d.source_updated_at).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : null;
  return { asOf: d.as_of_date, state: d.data_state, stateLabel: STATE_TEXT[d.data_state] ?? d.data_state, updated, scope, status: "ok" };
}

export function TopBar() {
  const { state, dispatch } = useCfo();
  const fresh = useFreshness();
  const real = useRealMeta();
  const path = useRouterState({ select: (r) => r.location.pathname });
  const demoOnly = isLiveCfo && isDemoOnlyPath(path);
  const f = fresh.data;
  return (
    <header className="flex h-12 items-center gap-4 border-b bg-card px-4">
      <Link to="/" onClick={() => dispatch({ type: "home" })} className="flex items-center gap-2.5" aria-label="CityKart CFO OS home">
        <span className="flex h-7 w-7 items-center justify-center rounded bg-[oklch(0.24_0.07_255)] text-[11px] font-bold tracking-tight text-white">CK</span>
        <span className="leading-none">
          <span className="block text-[13px] font-bold tracking-tight text-foreground">CityKart FP&amp;A</span>
          <span className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">CFO Operating System</span>
        </span>
      </Link>
      <div className="mx-1 h-6 w-px bg-border" />
      {real ? (
        <div className="flex flex-1 items-center justify-end gap-2" data-testid="real-controls"><DataStatus page={real} refreshKeys={refreshKeysFor(real.scope)} /></div>
      ) : path.startsWith("/related-party") ? (
        <div className="flex-1" /> // intercompany balances are a position as of the run: period, comparison and scenario do not apply
      ) : (
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Select<PeriodId> label="Period" testId="select-period" value={state.period} options={PERIOD_ORDER.map((id) => ({ id, label: PERIODS[id].label }))} onChange={(v) => dispatch({ type: "setPeriod", value: v })} />
        <Select<ComparisonId> label="Compare" testId="select-comparison" value={state.comparison} options={COMPARISON_ORDER.map((id) => ({ id, label: isLiveCfo && id !== "ly" ? `${COMPARISONS[id].label} (not available)` : COMPARISONS[id].label }))} onChange={(v) => dispatch({ type: "setComparison", value: v })} />
        {isLiveCfo ? (
          <span data-testid="scenario-live-note" title="Scenarios are demo-only controls. They do not apply to real data." className="hidden whitespace-nowrap rounded bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground 2xl:inline">
            Scenarios: demo only
          </span>
        ) : (
          <Select<ScenarioId> label="Scenario" testId="select-scenario" value={state.scenario} options={SCENARIO_ORDER.map((id) => ({ id, label: SCENARIOS[id].label }))} onChange={(v) => dispatch({ type: "setScenario", value: v })} />
        )}
      </div>
      )}
      {demoOnly && (
        <div data-testid="demo-chip" className="flex items-center gap-1.5 rounded bg-[oklch(0.96_0.06_85)] px-2 py-1 text-[11px] font-semibold text-[oklch(0.38_0.09_70)]">
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
          Demo data - not real
        </div>
      )}
      {!real && isLiveCfo && !demoOnly && <DataStatus />}
      {!real && !isLiveCfo && (      <div
        data-testid="freshness"
        className={cn("flex items-center gap-1.5 rounded px-2 py-1 text-[11px] font-medium", f?.stale ? "bg-[oklch(0.96_0.05_85)] text-[oklch(0.42_0.1_75)]" : "bg-[oklch(0.96_0.03_155)] text-[oklch(0.38_0.1_155)]")}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", f?.stale ? "bg-[oklch(0.7_0.15_75)]" : "bg-[oklch(0.62_0.16_155)]")} />
        {f?.label ?? "Checking freshness…"}
      </div>
      )}
      <Link to="/home" data-testid="link-home" title="Analytics Home: Finance, Operations and Merchandising" className="press inline-flex items-center gap-1 rounded border bg-card px-2 py-1 text-[11px] font-semibold text-muted-foreground hover:bg-muted hover:text-foreground">
        <LayoutGrid className="h-3 w-3" /> All reports
      </Link>
      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary text-[11px] font-bold text-secondary-foreground" title="CFO">
        CF
      </div>
    </header>
  );
}

type NavTo = "/" | "/profitability" | "/mgmt" | "/mgmt/store-expenses" | "/mgmt/dc-expenses" | "/cash" | "/creditors" | "/related-party" | "/control/adjustments" | "/control/corrections" | "/control/inbox" | "/control/close" | "/control/mapping" | "/control/source-fixes";
type NavId = "command" | "profitability" | "mgmt" | "storeExp" | "dcExp" | "cash" | "creditors" | "related" | "adjust" | "corrections" | "inbox" | "close" | "mapping" | "sourcefix";

const NAV_GROUPS: { group: string; items: { id: NavId; label: string; title: string; to: NavTo; testId: string; icon: typeof Truck }[] }[] = [
  { group: "Executive", items: [{ id: "command", label: "Command Center", title: "CFO Command Center", to: "/", testId: "nav-command-center", icon: LayoutDashboard }] },
  { group: "Performance", items: [
    { id: "mgmt", label: "Management P&L", title: "Management P&L: the finance MIS view (books + adjustments)", to: "/mgmt", testId: "nav-mgmt", icon: FileSpreadsheet },
    { id: "profitability", label: "Profitability", title: "Store Profitability (verified data)", to: "/profitability", testId: "nav-profitability", icon: Store },
    { id: "storeExp", label: "Store Expenses", title: "Store Expenses: rent, employee, power, advertisement, freight and other, down to the voucher", to: "/mgmt/store-expenses", testId: "nav-store-expenses", icon: Receipt },
    { id: "dcExp", label: "DC Expenses", title: "DC Expenses: SubCo and HoldCo warehouse cost, down to the voucher", to: "/mgmt/dc-expenses", testId: "nav-dc-expenses", icon: Warehouse },
  ] },
  { group: "Working capital", items: [
    { id: "cash", label: "Liquidity", title: "Liquidity & Working Capital Control", to: "/cash", testId: "nav-cash", icon: Banknote },
    { id: "creditors", label: "Creditors", title: "Creditors Control", to: "/creditors", testId: "nav-creditors", icon: Truck },
    { id: "related", label: "Related Party", title: "Related Party Transactions: intercompany balances, kept out of Creditors, Cash and the Command Center", to: "/related-party", testId: "nav-related", icon: Handshake },
  ] },
  { group: "Control", items: [
    { id: "inbox", label: "Exception Inbox", title: "Exception Inbox: what needs attention now, with owner and due date (sign-in required)", to: "/control/inbox", testId: "nav-inbox", icon: Inbox },
    { id: "close", label: "Month-end close", title: "Month-end close readiness: every gate for the period (sign-in required)", to: "/control/close", testId: "nav-close", icon: CalendarCheck },
    { id: "adjust", label: "Adjustments", title: "Adjustments and Provisions: governed management amounts (sign-in required)", to: "/control/adjustments", testId: "nav-adjustments", icon: ClipboardCheck },
    { id: "corrections", label: "Corrections", title: "Corrections: reclassify a booked line to another group or month (sign-in required)", to: "/control/corrections", testId: "nav-corrections", icon: Shuffle },
    { id: "mapping", label: "Mapping", title: "Mapping governance: how ledgers map to management groups (sign-in required)", to: "/control/mapping", testId: "nav-mapping", icon: Route },
    { id: "sourcefix", label: "Source fixes", title: "Source-fix queue: errors to be corrected at the source system (sign-in required)", to: "/control/source-fixes", testId: "nav-source-fixes", icon: Wrench },
  ] },
];

const ORIGIN_FOR: Record<NavId, DrillOrigin | null> = { command: null, profitability: PROFIT_ORIGIN, mgmt: null, storeExp: null, dcExp: null, cash: CASH_ORIGIN, creditors: CREDITORS_ORIGIN, related: null, adjust: null, corrections: null, inbox: null, close: null, mapping: null, sourcefix: null };

/** The destination the current investigation belongs to, so a ledger or voucher still highlights its own area. */
function activeNav(scope: string | undefined, path: string, trail?: unknown): NavId {
  if (path.startsWith("/mgmt/store-expenses")) return "storeExp";
  if (path.startsWith("/mgmt/dc-expenses")) return "dcExp";
  if (path.startsWith("/mgmt")) return "mgmt";
  if (path.startsWith("/related-party")) return "related";
  if (path.startsWith("/control/adjustments")) return "adjust";
  if (path.startsWith("/control/corrections")) return "corrections";
  if (path.startsWith("/control/close")) return "close";
  if (path.startsWith("/control/mapping")) return "mapping";
  if (path.startsWith("/control/source-fixes")) return "sourcefix";
  if (path.startsWith("/control/")) return "inbox";
  if (path.startsWith("/entry")) {
    // the voucher drill highlights the area it was reached from: the first step of its trail
    const first = Array.isArray(trail) ? (trail[0] as { h?: unknown } | undefined)?.h : undefined;
    const h = typeof first === "string" ? first : "";
    return h.startsWith("/mgmt/store-expenses") ? "storeExp" : h.startsWith("/mgmt/dc-expenses") ? "dcExp" : h.startsWith("/creditors") ? "creditors" : h.startsWith("/profitability") ? "profitability" : h.startsWith("/cash") ? "cash" : "command";
  }
  if (scope === "creditors" || path.startsWith("/creditors")) return "creditors";
  if (scope === "profitability" || path.startsWith("/profitability")) return "profitability";
  if (scope === "cashroom" || path === "/cash") return "cash";
  return "command";
}

const NAV_KEY = "fpa.nav.collapsed";
const readCollapsed = (): boolean => { try { return window.localStorage.getItem(NAV_KEY) === "1"; } catch { return false; } };

export function SideNav() {
  const { state, dispatch, enterCreditors, enterRoom } = useCfo();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const path = useRouterState({ select: (x) => x.location.pathname });
  const trail = useRouterState({ select: (x) => (x.location.search as { trail?: unknown }).trail });
  const active = activeNav(state.origin?.scope, path, trail);
  const go: Record<NavId, () => void> = {
    command: () => dispatch({ type: "home" }),
    profitability: () => enterRoom("profitability"),
    mgmt: () => undefined, // not part of the drill workflow: nothing to reset
    storeExp: () => undefined,
    dcExp: () => undefined,
    cash: () => enterRoom("cashroom"),
    creditors: () => enterCreditors(),
    related: () => undefined, // its own page, outside the drill workflow
    adjust: () => undefined,
    corrections: () => undefined,
    inbox: () => undefined,
    close: () => undefined,
    mapping: () => undefined,
    sourcefix: () => undefined,
  };
  const toggle = () => { const v = !collapsed; setCollapsed(v); try { window.localStorage.setItem(NAV_KEY, v ? "1" : "0"); } catch { /* per-viewer convenience only */ } };
  return (
    <nav aria-label="Primary" data-collapsed={collapsed} className={cn("hidden shrink-0 flex-col border-r bg-card py-3 md:flex", collapsed ? "w-14" : "w-[208px]")}>
      {NAV_GROUPS.map(({ group, items }) => (
        <div key={group} className={cn("mb-1", collapsed && "border-t pt-1 first:border-t-0 first:pt-0")}>
          {!collapsed && <div className="eyebrow mt-3 px-4 first:mt-0">{group}</div>}
          {items.map(({ id, label, title, to, testId, icon: Icon }) => (
            <Link
              key={id}
              to={to}
              // carry period / comparison / scenario / horizon into the destination, so the address is complete and shareable
              search={searchFromState({ ...state, origin: ORIGIN_FOR[id], nodes: [], drawerOpen: false }) as never}
              onClick={go[id]}
              data-testid={testId}
              title={title}
              aria-label={label}
              aria-current={active === id ? "page" : undefined}
              className={cn(
                "press mx-2 mt-1 flex items-center gap-2 rounded px-2.5 py-2 text-[13px] font-semibold",
                collapsed && "justify-center",
                active === id ? "bg-[oklch(0.95_0.025_265)] text-[oklch(0.28_0.09_265)]" : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" /> {!collapsed && <span className="whitespace-nowrap">{label}</span>}
            </Link>
          ))}
        </div>
      ))}
      <button type="button" data-testid="nav-collapse" onClick={toggle} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} title={collapsed ? "Expand navigation" : "Collapse navigation"} className="press mx-2 mt-auto flex items-center justify-center gap-2 rounded px-2.5 py-2 text-[12px] font-medium text-muted-foreground hover:bg-muted">
        {collapsed ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /> Collapse</>}
      </button>
    </nav>
  );
}

export function Breadcrumbs() {
  const { crumbs, goToCrumb } = useCfo();
  const path = useRouterState({ select: (x) => x.location.pathname });
  if (path.startsWith("/entry")) return null; // the voucher drill carries its own trail (where the user came from), in the URL
  if (path.startsWith("/mgmt")) {
    return (
      <nav aria-label="Breadcrumb" data-testid="breadcrumbs" className="flex h-8 items-center gap-1 overflow-x-auto whitespace-nowrap border-b bg-background px-4 text-[12px]">
        <span className="text-muted-foreground">CityKart</span>
        <ChevronRight className="h-3 w-3 text-muted-foreground/60" />
        <span aria-current="page" className="font-semibold text-foreground">Management P&amp;L</span>
      </nav>
    );
  }
  if (path.startsWith("/related-party")) {
    return (
      <nav aria-label="Breadcrumb" data-testid="breadcrumbs" className="flex h-8 items-center gap-1 overflow-x-auto whitespace-nowrap border-b bg-background px-4 text-[12px]">
        <span className="text-muted-foreground">CityKart</span>
        <ChevronRight className="h-3 w-3 text-muted-foreground/60" />
        <span aria-current="page" className="font-semibold text-foreground">Related Party Transactions</span>
      </nav>
    );
  }
  if (path === "/profitability") {
    return (
      <nav aria-label="Breadcrumb" data-testid="breadcrumbs" className="flex h-8 items-center gap-1 overflow-x-auto whitespace-nowrap border-b bg-background px-4 text-[12px]">
        <span className="text-muted-foreground">CityKart</span>
        <ChevronRight className="h-3 w-3 text-muted-foreground/60" />
        <span aria-current="page" className="font-semibold text-foreground">Profitability</span>
      </nav>
    );
  }
  return (
    <nav aria-label="Breadcrumb" data-testid="breadcrumbs" className="flex h-8 items-center gap-1 overflow-x-auto whitespace-nowrap border-b bg-background px-4 text-[12px]">
      {crumbs.map((c, i) => (
        <span key={`${c.label}-${i}`} className="flex items-center gap-1">
          {i > 0 && <ChevronRight className="h-3 w-3 text-muted-foreground/60" />}
          {c.current ? (
            <span aria-current="page" className="font-semibold text-foreground">
              {c.label}
            </span>
          ) : (
            <button data-testid={`crumb-${i}`} onClick={() => goToCrumb(c)} className="press rounded px-1 py-0.5 text-muted-foreground hover:bg-muted hover:text-foreground">
              {c.label}
            </button>
          )}
        </span>
      ))}
    </nav>
  );
}

/** Home and the Operations pages are not part of the CFO workflow: they get the same header look, without the finance banner, period controls or finance sidebar. */
const PORTAL_PREFIXES = ["/home", "/operations"];
export const isPortalPath = (p: string) => PORTAL_PREFIXES.some((x) => p === x || p.startsWith(`${x}/`));

function PortalHeader({ path }: { path: string }) {
  const link = (active: boolean) => cn("press rounded px-2.5 py-1 text-[12.5px] font-semibold", active ? "bg-[oklch(0.95_0.025_265)] text-[oklch(0.28_0.09_265)]" : "text-muted-foreground hover:bg-muted hover:text-foreground");
  return (
    <header data-testid="portal-header" className="flex h-12 items-center gap-2 border-b bg-card px-3 sm:gap-4 sm:px-4">
      <Link to="/home" className="flex items-center gap-2.5" aria-label="CityKart Analytics home">
        <span className="flex h-7 w-7 items-center justify-center rounded bg-[oklch(0.24_0.07_255)] text-[11px] font-bold tracking-tight text-white">CK</span>
        <span className="hidden leading-none sm:block">
          <span className="block text-[13px] font-bold tracking-tight text-foreground">CityKart Analytics</span>
          <span className="hidden text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground md:block">Finance · Operations · Merchandising</span>
        </span>
      </Link>
      <div className="mx-1 hidden h-6 w-px bg-border sm:block" />
      <nav aria-label="Areas" className="flex items-center gap-0.5 sm:gap-1">
        <Link to="/home" data-testid="portal-nav-home" className={link(path === "/home")}>Home</Link>
        <Link to="/" data-testid="portal-nav-finance" className={link(false)}>Finance</Link>
        <Link to="/operations/sales" data-testid="portal-nav-operations" className={link(path.startsWith("/operations"))}>Operations</Link>
      </nav>
    </header>
  );
}

export function AppShell({ children, drawer, drawerOpen }: { children: ReactNode; drawer: ReactNode; drawerOpen: boolean }) {
  const path = useRouterState({ select: (r) => r.location.pathname });
  if (isPortalPath(path)) {
    return (
      <div className="flex min-h-screen flex-col bg-background text-foreground">
        <PortalHeader path={path} />
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    );
  }
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <DemoBanner />
      <TopBar />
      <Breadcrumbs />
      <div className="flex min-h-0 flex-1">
        <SideNav />
        <main className="min-w-0 flex-1 transition-[margin] duration-200" style={{ marginRight: drawerOpen ? "var(--drawer-w)" : 0 }}>
          {children}
        </main>
      </div>
      {drawer}
    </div>
  );
}
