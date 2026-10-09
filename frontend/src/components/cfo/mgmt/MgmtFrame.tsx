import type { ReactNode } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { AlertTriangle, FlaskConical } from "lucide-react";
import { useMgmtRun } from "@/api/mgmtLiveHooks";
import { fmtDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Skeleton } from "../common";
import { NotAvailable } from "../creditors/parts";
import { WorkspaceHeader } from "../panels";
import { monthShort } from "./mgmtFormat";
import { useMgmtEntity } from "./mgmtEntity";
import { MGMT_ENTITIES, type MgmtEntity } from "@/types/mgmtLive";

export type MgmtTab = "pnl" | "stores" | "store-exp" | "dc-exp" | "recon" | "mapping";

const TABS: { id: MgmtTab; label: string; to: "/mgmt" | "/mgmt/stores" | "/mgmt/store-expenses" | "/mgmt/dc-expenses" | "/mgmt/reconciliation" | "/mgmt/mapping" }[] = [
  { id: "pnl", label: "Management P&L", to: "/mgmt" },
  { id: "stores", label: "Store league", to: "/mgmt/stores" },
  { id: "store-exp", label: "Store Expenses", to: "/mgmt/store-expenses" },
  { id: "dc-exp", label: "DC Expenses", to: "/mgmt/dc-expenses" },
  { id: "recon", label: "Reconciliation", to: "/mgmt/reconciliation" },
  { id: "mapping", label: "Ledger mapping", to: "/mgmt/mapping" },
];

/** Warnings from the API, shown above the figures they qualify: never hidden, never softened. */
export function WarningsBanner({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <div data-testid="mgmt-warnings" role="status" className="flex items-start gap-2 border-b bg-[oklch(0.97_0.05_85)] px-5 py-2 text-[12px] text-[oklch(0.38_0.09_70)]">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <ul className="space-y-0.5">
        {warnings.map((w) => (
          <li key={w} data-testid="mgmt-warning">{w}</li>
        ))}
      </ul>
    </div>
  );
}

/** Consolidated | SubCo | HoldCo, kept in the URL. Consolidated is what the finance MIS shows. */
export function EntitySelector({ entity }: { entity: MgmtEntity }) {
  const navigate = useNavigate();
  return (
    <div role="group" aria-label="Entity" data-testid="mgmt-entity" data-entity={entity} className="flex items-center gap-2 border-b bg-card px-5 py-2 text-[12px]">
      <span className="eyebrow">Entity</span>
      <div className="flex overflow-hidden rounded border">
        {MGMT_ENTITIES.map((e) => (
          <button
            key={e.id}
            type="button"
            data-testid={`entity-${e.id}`}
            aria-pressed={entity === e.id}
            onClick={() => navigate({ search: ((p: Record<string, unknown>) => ({ ...p, entity: e.id === "consolidated" ? undefined : e.id })) as never })}
            className={cn("press px-2.5 py-1 font-medium", entity === e.id ? "bg-foreground text-background" : "hover:bg-muted")}
          >
            {e.label}
          </button>
        ))}
      </div>
      <span className="text-[11.5px] text-muted-foreground">{entity === "consolidated" ? "Both legal entities, as the finance MIS shows." : entity === "holdco" ? "Citykart Ventures only: warehouses and the registered head office." : "Citykart Stores (CKSPL) only: the stores and their own DC and HO cost."}</span>
    </div>
  );
}

/** From / To month selectors over the months the run serves. */
export function MonthRange({ months, from, to, onChange }: { months: string[]; from: string; to: string; onChange: (from: string, to: string) => void }) {
  const sel = "h-7 rounded border bg-card px-1.5 text-[12px]";
  return (
    <div data-testid="mgmt-range" className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-1">
        <span className="eyebrow">From</span>
        <select aria-label="From month" data-testid="mgmt-from" className={sel} value={from} onChange={(e) => onChange(e.target.value, e.target.value > to ? e.target.value : to)}>
          {months.map((m) => <option key={m} value={m}>{monthShort(m)}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-1">
        <span className="eyebrow">To</span>
        <select aria-label="To month" data-testid="mgmt-to" className={sel} value={to} onChange={(e) => onChange(e.target.value < from ? e.target.value : from, e.target.value)}>
          {months.map((m) => <option key={m} value={m}>{monthShort(m)}</option>)}
        </select>
      </label>
      <button className="press rounded border px-2 py-1 text-[12px] font-medium hover:bg-muted" data-testid="mgmt-preset-ytd" onClick={() => onChange(months[0], months[months.length - 1])}>FY YTD</button>
      <button className="press rounded border px-2 py-1 text-[12px] font-medium hover:bg-muted" data-testid="mgmt-preset-month" onClick={() => onChange(months[months.length - 1], months[months.length - 1])}>Latest month</button>
    </div>
  );
}

/** The page chrome shared by the four pages: header, the REAL DATA badge, the sub-links, and the not-available state when the API has no run. */
export function MgmtFrame({ active, subtitle, entitySelector = true, children }: { active: MgmtTab; subtitle?: ReactNode; entitySelector?: boolean; children: (months: string[], warnings: string[]) => ReactNode }) {
  const run = useMgmtRun();
  const entity = useMgmtEntity();
  return (
    <div data-testid="mgmt-room" data-entity={entity} className="@container flex min-w-0 flex-1 flex-col overflow-y-auto bg-background">
      <WorkspaceHeader
        eyebrow="Performance"
        title="Management P&L"
        subtitle={subtitle ?? "The finance MIS view: store lines, DC and HO cost, corporate EBITDA. INR Cr. Each figure is the books plus management adjustments."}
        right={
          run.data ? (
            <span data-testid="mgmt-badge" title={`Run ${run.data.run_id} · data as of ${run.data.as_of_date}. Management view: includes adjustments that are not in the books.`} className="inline-flex items-center gap-1.5 rounded-sm border bg-[oklch(0.94_0.06_155)] px-2 py-0.5 text-[11px] font-semibold text-[oklch(0.32_0.1_155)]">
              <FlaskConical className="h-3 w-3" />
              <span className="rounded-sm bg-foreground px-1 text-[10px] font-bold tracking-wider text-background">REAL DATA</span>
              Management view
              <span className="font-normal opacity-80">· As of {fmtDate(run.data.as_of_date)} · {run.data.run_id}</span>
            </span>
          ) : undefined
        }
      />
      <nav aria-label="Management P&L pages" data-testid="mgmt-tabs" className="flex flex-wrap gap-0.5 border-b bg-card px-3 pt-1.5">
        {TABS.map((t) => (
          <Link
            key={t.id}
            to={t.to}
            search={((t.id === "mapping" || t.id === "store-exp" || entity === "consolidated" ? {} : { entity }) as never)}
            data-testid={`mgmt-tab-${t.id}`}
            aria-current={active === t.id ? "page" : undefined}
            className={cn("press -mb-px rounded-t border border-b-0 px-3 py-1.5 text-[12.5px] font-semibold", active === t.id ? "border-border bg-background text-foreground" : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground")}
          >
            {t.label}
          </Link>
        ))}
      </nav>
      {entitySelector && <EntitySelector entity={entity} />}
      {run.isPending ? (
        <div data-testid="state-loading"><Skeleton className="m-4 h-[320px]" /></div>
      ) : run.isError || !run.data ? (
        <NotAvailable testId="mgmt-unavailable" title="No management P&L run is available" reason={`${(run.error as Error | null)?.message ?? "The Management P&L API did not return a run"}. Nothing is shown rather than a demo figure.`} />
      ) : (
        <>
          <WarningsBanner warnings={run.data.warnings} />
          {children(run.data.months, run.data.warnings)}
        </>
      )}
    </div>
  );
}
