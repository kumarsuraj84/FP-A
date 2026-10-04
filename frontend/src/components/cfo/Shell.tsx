import type { ReactNode } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { Banknote, ChevronRight, CircleDot, Landmark, LayoutDashboard, Lock, PiggyBank, Scale, Store, Truck, Wallet } from "lucide-react";
import { useCfo } from "@/context/CfoContext";
import { searchFromState } from "@/context/drillUrl";
import { CREDITORS_ORIGIN } from "@/lib/creditorNodes";
import { PROFIT_ORIGIN } from "@/lib/profitNodes";
import { CASH_ORIGIN } from "@/lib/cashNodes";
import type { DrillOrigin } from "@/types/cfo";
import { useFreshness } from "@/api/hooks";
import { COMPARISON_ORDER, COMPARISONS, PERIOD_ORDER, PERIODS, SCENARIOS, SCENARIO_ORDER } from "@/mocks/scenarios";
import type { ComparisonId, DataStateId, PeriodId, ScenarioId } from "@/types/cfo";
import { cn } from "@/lib/utils";
import { isMockApi } from "@/api";

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

export function DemoBanner() {
  const { state, dispatch } = useCfo();
  return (
    <div data-testid="demo-banner" className="flex h-6 items-center justify-between bg-[oklch(0.96_0.06_85)] px-4 text-[11px] font-medium text-[oklch(0.38_0.09_70)]">
      <span className="flex items-center gap-1.5">
        <CircleDot className="h-3 w-3" />
        Demo data — financial source reconciliation pending
        {!isMockApi && <span className="rounded bg-white/60 px-1">API configured</span>}
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

export function TopBar() {
  const { state, dispatch } = useCfo();
  const fresh = useFreshness();
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
      <div className="flex flex-1 flex-wrap items-center gap-3">
        <Select<PeriodId> label="Period" testId="select-period" value={state.period} options={PERIOD_ORDER.map((id) => ({ id, label: PERIODS[id].label }))} onChange={(v) => dispatch({ type: "setPeriod", value: v })} />
        <Select<ComparisonId> label="Compare" testId="select-comparison" value={state.comparison} options={COMPARISON_ORDER.map((id) => ({ id, label: COMPARISONS[id].label }))} onChange={(v) => dispatch({ type: "setComparison", value: v })} />
        <Select<ScenarioId> label="Scenario" testId="select-scenario" value={state.scenario} options={SCENARIO_ORDER.map((id) => ({ id, label: SCENARIOS[id].label }))} onChange={(v) => dispatch({ type: "setScenario", value: v })} />
      </div>
      <div
        data-testid="freshness"
        className={cn("flex items-center gap-1.5 rounded px-2 py-1 text-[11px] font-medium", f?.stale ? "bg-[oklch(0.96_0.05_85)] text-[oklch(0.42_0.1_75)]" : "bg-[oklch(0.96_0.03_155)] text-[oklch(0.38_0.1_155)]")}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", f?.stale ? "bg-[oklch(0.7_0.15_75)]" : "bg-[oklch(0.62_0.16_155)]")} />
        {f?.label ?? "Checking freshness…"}
      </div>
      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary text-[11px] font-bold text-secondary-foreground" title="CFO">
        CF
      </div>
    </header>
  );
}

const FUTURE = [
  { label: "Budget & Forecast", icon: PiggyBank },
  { label: "Vendor Advances", icon: Wallet },
  { label: "Reconciliation", icon: Scale },
  { label: "Balance Sheet", icon: Landmark },
];

type NavId = "command" | "profitability" | "cash" | "creditors";

const NAV_GROUPS: { group: string; items: { id: NavId; label: string; title: string; to: "/" | "/profitability" | "/cash" | "/creditors"; testId: string; icon: typeof Truck }[] }[] = [
  { group: "Command", items: [{ id: "command", label: "CFO Command Center", title: "CFO Command Center", to: "/", testId: "nav-command-center", icon: LayoutDashboard }] },
  { group: "Performance", items: [{ id: "profitability", label: "Profitability", title: "Store Profitability", to: "/profitability", testId: "nav-profitability", icon: Store }] },
  { group: "Liquidity", items: [{ id: "cash", label: "Cash & Working Capital", title: "Cash & Working Capital", to: "/cash", testId: "nav-cash", icon: Banknote }] },
  { group: "Exposure", items: [{ id: "creditors", label: "Creditors", title: "Creditors Control", to: "/creditors", testId: "nav-creditors", icon: Truck }] },
];

const ORIGIN_FOR: Record<NavId, DrillOrigin | null> = { command: null, profitability: PROFIT_ORIGIN, cash: CASH_ORIGIN, creditors: CREDITORS_ORIGIN };

/** The destination the current investigation belongs to, so a ledger or voucher still highlights its own area. */
function activeNav(scope: string | undefined, path: string): NavId {
  if (scope === "creditors" || path.startsWith("/creditors")) return "creditors";
  if (scope === "profitability" || path.startsWith("/profitability")) return "profitability";
  if (scope === "cashroom" || path === "/cash") return "cash";
  return "command";
}

export function SideNav() {
  const { state, dispatch, enterCreditors, enterRoom } = useCfo();
  const path = useRouterState({ select: (x) => x.location.pathname });
  const active = activeNav(state.origin?.scope, path);
  const go: Record<NavId, () => void> = {
    command: () => dispatch({ type: "home" }),
    profitability: () => enterRoom("profitability"),
    cash: () => enterRoom("cashroom"),
    creditors: () => enterCreditors(),
  };
  return (
    <nav aria-label="Primary" className="hidden w-14 shrink-0 flex-col border-r bg-card py-3 md:flex min-[1360px]:w-[196px]">
      {NAV_GROUPS.map(({ group, items }) => (
        <div key={group} className="mb-1">
          <div className="eyebrow mt-3 hidden px-4 first:mt-0 min-[1360px]:block">{group}</div>
          {items.map(({ id, label, title, to, testId, icon: Icon }) => (
            <Link
              key={id}
              to={to}
              // carry period / comparison / scenario / horizon into the destination, so the address is complete and shareable
              search={searchFromState({ ...state, origin: ORIGIN_FOR[id], nodes: [], drawerOpen: false }) as never}
              onClick={go[id]}
              data-testid={testId}
              title={title}
              aria-current={active === id ? "page" : undefined}
              className={cn(
                "press mx-2 mt-1 flex items-center justify-center gap-2 rounded px-2.5 py-2 text-[13px] font-semibold min-[1360px]:justify-start",
                active === id ? "bg-[oklch(0.95_0.025_265)] text-[oklch(0.28_0.09_265)]" : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" /> <span className="hidden whitespace-nowrap min-[1360px]:inline">{label}</span>
            </Link>
          ))}
        </div>
      ))}
      <div className="eyebrow mt-4 hidden px-4 min-[1360px]:block">Upcoming</div>
      <ul className="mt-3 space-y-0.5 px-2 min-[1360px]:mt-1.5">
        {FUTURE.map(({ label, icon: Icon }) => (
          <li key={label}>
            <div aria-disabled="true" title={`${label} — planned for a later stage`} className="flex cursor-not-allowed items-center justify-center gap-2 rounded px-2.5 py-1.5 text-[12.5px] text-muted-foreground/70 min-[1360px]:justify-start">
              <Icon className="h-4 w-4 shrink-0" />
              <span className="hidden flex-1 whitespace-nowrap min-[1360px]:inline">{label}</span>
              <Lock className="hidden h-3 w-3 opacity-60 min-[1360px]:block" />
            </div>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function Breadcrumbs() {
  const { crumbs, goToCrumb } = useCfo();
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

export function AppShell({ children, drawer, drawerOpen }: { children: ReactNode; drawer: ReactNode; drawerOpen: boolean }) {
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
