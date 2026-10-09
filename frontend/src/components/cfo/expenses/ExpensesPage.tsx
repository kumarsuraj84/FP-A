import { CheckCircle2, Info, XCircle } from "lucide-react";
import { useExpSummary } from "@/api/expensesLiveHooks";
import { DASH } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ExpHeadRow, ExpMode, ExpScope, ExpSummary } from "@/types/expensesLive";
import { MGMT_ENTITIES, type MgmtEntity } from "@/types/mgmtLive";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { useHere } from "../entry/parts";
import { MgmtFrame, MonthRange } from "../mgmt/MgmtFrame";
import { useMgmtEntity } from "../mgmt/mgmtEntity";
import { cr2, cr2s, dashReason, monthShort, pct1 } from "../mgmt/mgmtFormat";
import { DrillPanel } from "./ExpDrill";
import { ExpExceptionsPanel } from "./ExpExceptions";
import { ExpSitesPanel } from "./ExpSites";
import { ExpTrendPanel } from "./ExpTrend";
import { modeOf, queryOf, resolvePeriod, useExpSearch, useSetExp } from "./expensesUrl";

/**
 * Store Expense and DC Expense review. One component for both pages: same layout, the scope decides the heads' denominator
 * (% of net sales for stores, per-site average for DC) and the entity choices (stores are SubCo only; the DC page spans both entities).
 * Everything the finance MIS calls Rent, Employee Cost, Power and Fuel, Advertisement, Freight Forwarding and Other expenses, from the same engine as /mgmt.
 */

const MODES: { id: ExpMode; label: string; hint: string }[] = [
  { id: "total", label: "Total", hint: "The MIS number: book plus management adjustment" },
  { id: "book", label: "Book", hint: "What the ledger says, before any management adjustment" },
  { id: "adjustment", label: "Adjustment", hint: "Only the management adjustments" },
];

const COPY: Record<"store" | "dc", { title: string; subtitle: string; eyebrow: string; unit: string }> = {
  store: { title: "Store Expenses", eyebrow: "Store expense review", unit: "stores", subtitle: "Rent, employee cost, power and fuel, advertisement, freight forwarding and other expenses of the stores, down to the voucher. INR Cr." },
  dc: { title: "DC Expenses", eyebrow: "DC cost review", unit: "DC sites", subtitle: "The cost of the distribution centres (SubCo warehouses and HoldCo warehouses), by head, site and ledger, down to the voucher. INR Cr." },
};

const adjusted = (r: { adjustment: number }) => Math.abs(r.adjustment) >= 0.005;

function EntityBar({ scope, entity }: { scope: "store" | "dc"; entity: MgmtEntity }) {
  const set = useSetExp();
  if (scope === "store") {
    return (
      <div data-testid="exp-entity" data-entity="subco" className="flex items-center gap-2 text-[12px]">
        <span className="eyebrow">Entity</span>
        <span className="rounded border bg-foreground px-2.5 py-1 font-medium text-background">SubCo - Citykart Stores</span>
        <span className="text-[11.5px] text-muted-foreground" data-testid="exp-entity-note">Stores belong to SubCo only: Citykart Ventures (HoldCo) has no stores.</span>
      </div>
    );
  }
  return (
    <div role="group" aria-label="Entity" data-testid="exp-entity" data-entity={entity} className="flex items-center gap-2 text-[12px]">
      <span className="eyebrow">Entity</span>
      <div className="flex overflow-hidden rounded border">
        {MGMT_ENTITIES.map((e) => (
          <button key={e.id} type="button" data-testid={`exp-entity-${e.id}`} aria-pressed={entity === e.id} onClick={() => set({ entity: e.id === "consolidated" ? undefined : e.id, site: undefined, se: undefined, sn: undefined, gl: undefined })} className={cn("press px-2.5 py-1 font-medium", entity === e.id ? "bg-foreground text-background" : "hover:bg-muted")}>{e.label}</button>
        ))}
      </div>
      <span className="text-[11.5px] text-muted-foreground">{entity === "consolidated" ? "SubCo and HoldCo warehouses together." : entity === "holdco" ? "Citykart Ventures warehouses only (CKVPL-*)." : "Citykart Stores (CKSPL) warehouses only."}</span>
    </div>
  );
}

function ModeToggle({ mode }: { mode: ExpMode }) {
  const set = useSetExp();
  return (
    <div role="group" aria-label="Book, adjustment or total" data-testid="exp-mode" data-mode={mode} className="flex items-center gap-1.5 text-[12px]">
      <span className="eyebrow">Show</span>
      <div className="flex overflow-hidden rounded border">
        {MODES.map((m) => (
          <button key={m.id} type="button" data-testid={`exp-mode-${m.id}`} title={m.hint} aria-pressed={mode === m.id} onClick={() => set({ mode: m.id === "total" ? undefined : m.id })} className={cn("press px-2.5 py-1 font-medium", mode === m.id ? "bg-foreground text-background" : "hover:bg-muted")}>{m.label}</button>
        ))}
      </div>
    </div>
  );
}

function Kpi({ id, label, value, sub, tone, exact }: { id: string; label: string; value: string; sub?: React.ReactNode; tone?: "bad" | "good"; exact?: number | null }) {
  return (
    <div className="px-4 py-3" data-testid={id}>
      <div className="eyebrow">{label}</div>
      <div data-testid={`${id}-value`} data-exact={exact === null || exact === undefined ? "" : String(exact)} className={cn("num-mono text-[20px] font-semibold leading-tight", tone === "bad" && "tone-bad", tone === "good" && "text-[oklch(0.4_0.12_155)]")}>{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

function Strip({ d, scope, mode }: { d: ExpSummary; scope: ExpScope; mode: ExpMode }) {
  const t = d.total;
  const v = t[mode];
  const ly = t.ly;
  const mom = t.mom;
  return (
    <section aria-label="Headline figures" data-testid="exp-kpis" className="grid grid-cols-4 divide-x border-b bg-card @max-[800px]:grid-cols-2 @max-[800px]:divide-y">
      <Kpi id="kpi-total" label={`${d.scope_label}, ${mode === "total" ? "total" : mode}`} value={`${cr2(v)} Cr`} exact={v} sub={`${monthShort(d.from_month)}${d.from_month !== d.to_month ? ` to ${monthShort(d.to_month)}` : ""} · book ${cr2(t.book)} + adjustment ${cr2(t.adjustment)}`} />
      {scope === "store" ? (
        <Kpi id="kpi-pct" label="% of net sales" value={t.pct_ns ? pct1(t.pct_ns[mode]) : DASH} exact={t.pct_ns?.[mode] ?? null} sub={d.net_sales !== null ? `net sales ${cr2(d.net_sales)} Cr` : "no net sales"} />
      ) : (
        <Kpi id="kpi-pct" label="Per DC site" value={t.per_site_avg !== null ? `${cr2(t.per_site_avg)} Cr` : DASH} exact={t.per_site_avg} sub={d.site_count !== null ? `${d.site_count} site${d.site_count === 1 ? "" : "s"} with cost in the period` : undefined} />
      )}
      <Kpi
        id="kpi-ly"
        label="vs last year"
        value={ly ? `${cr2s(ly.delta)} Cr` : DASH}
        exact={ly?.delta ?? null}
        tone={ly && ly.delta > 0.005 ? "bad" : ly && ly.delta < -0.005 ? "good" : undefined}
        sub={ly ? `${ly.delta_pct === null ? DASH : pct1(ly.delta_pct)} · same months last year ${cr2(ly.total)} Cr${scope === "store" && ly.pct_ns_delta_pp !== null ? ` · ${ly.pct_ns_delta_pp > 0 ? "+" : "−"}${Math.abs(ly.pct_ns_delta_pp).toFixed(1)} pp of net sales` : ""}` : <span title={dashReason("value", "Gold has no data for the same months last year")}>no last-year months in gold</span>}
      />
      <Kpi id="kpi-mom" label={`${mom ? monthShort(mom.last_month) : monthShort(d.to_month)} vs ${mom ? monthShort(mom.prev_month) : "previous month"}`} value={mom ? `${cr2s(mom.delta)} Cr` : DASH} exact={mom?.delta ?? null} tone={mom && mom.delta > 0.005 ? "bad" : mom && mom.delta < -0.005 ? "good" : undefined} sub={mom ? `${mom.delta_pct === null ? DASH : pct1(mom.delta_pct)} · ${cr2(mom.prev)} to ${cr2(mom.last)} Cr` : "no month before in gold"} />
    </section>
  );
}

function ControlsBadge({ d }: { d: ExpSummary }) {
  const c = d.controls;
  return (
    <details data-testid="exp-controls-badge" data-ok={String(c.ok)} className="group text-[11.5px]">
      <summary className={cn("flex cursor-pointer list-none items-center gap-1", c.ok ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}>
        {c.ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
        {c.ok ? "Store + DC + HO = Management P&L" : "Scopes do NOT add up to the Management P&L"}
      </summary>
      <div className="absolute right-4 z-30 mt-1 w-[min(560px,90vw)] rounded-md border bg-card p-3 shadow-elegant" data-testid="exp-controls-detail">
        <div className="mb-1 text-[11px] text-muted-foreground">{c.basis}. Tolerance {c.tolerance_cr} Cr.</div>
        <table className="w-full text-[11.5px]">
          <thead><tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground"><th className="py-1">Layer</th><th className="text-right">Store</th><th className="text-right">DC</th><th className="text-right">HO</th><th className="text-right">Sum</th><th className="text-right">Mgmt P&amp;L</th><th className="text-right">Variance</th></tr></thead>
          <tbody>
            {c.rows.map((r) => (
              <tr key={r.layer} data-testid={`ctl-${r.layer}`} data-ok={String(r.ok)} className="border-t">
                <td className="py-1 capitalize">{r.layer}</td>
                {[r.store, r.dc, r.ho, r.sum_of_scopes, r.mgmt_pnl].map((x, i) => <td key={i} className="num-mono text-right">{cr2(x)}</td>)}
                <td className={cn("num-mono text-right", !r.ok && "tone-bad")}>{r.variance.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function HeadsTable({ d, scope, mode, openHead, onHead }: { d: ExpSummary; scope: ExpScope; mode: ExpMode; openHead?: string; onHead: (h: ExpHeadRow) => void }) {
  const th = "whitespace-nowrap px-3 py-2 font-semibold text-right";
  const row = (r: ExpHeadRow, isTotal = false) => {
    const v = r[mode];
    const adj = adjusted(r);
    return (
      <tr key={r.key} data-testid={isTotal ? "head-total" : `head-${r.key}`} data-open={openHead === r.key} className={cn("border-b", isTotal ? "bg-secondary font-semibold" : "hover:bg-muted/40", openHead === r.key && "bg-[oklch(0.96_0.03_265)]")}>
        <th scope="row" className="sticky left-0 z-10 whitespace-nowrap border-r bg-inherit px-3 py-1.5 text-left font-normal">
          {isTotal ? <span className="font-semibold">{r.label}</span> : (
            <button type="button" data-testid={`open-head-${r.key}`} aria-expanded={openHead === r.key} onClick={() => onHead(r)} className="press text-left text-primary underline-offset-2 hover:underline">{r.label}</button>
          )}
        </th>
        <td data-testid={`${isTotal ? "head-total" : `head-${r.key}`}-value`} data-exact={String(v)} data-adjusted={adj} title={`Book ${cr2(r.book)} · Adjustment ${cr2(r.adjustment)} · Total ${cr2(r.total)}`} className={cn("num-mono whitespace-nowrap px-3 py-1.5 text-right", adj && !isTotal && "bg-[oklch(0.97_0.05_85)]")}>{cr2(v)}</td>
        {scope === "store" ? (
          <td className="num-mono whitespace-nowrap px-3 py-1.5 text-right" title={r.pct_ns ? `Book ${pct1(r.pct_ns.book)} · Adjustment ${pct1(r.pct_ns.adjustment)} · Total ${pct1(r.pct_ns.total)}` : dashReason("pct", "No net sales in the period")}>{r.pct_ns ? pct1(r.pct_ns[mode]) : DASH}</td>
        ) : (
          <td className="num-mono whitespace-nowrap px-3 py-1.5 text-right" title={r.per_site_avg === null ? dashReason("value", "No DC site has cost in the period") : "Total divided by the number of sites with cost"}>{r.per_site_avg === null ? DASH : cr2(r.per_site_avg)}</td>
        )}
        <td className="num-mono whitespace-nowrap px-3 py-1.5 text-right text-muted-foreground" title="Share of the total (book plus adjustment)">{pct1(r.share_pct)}</td>
        <td className={cn("num-mono whitespace-nowrap px-3 py-1.5 text-right", r.mom && r.mom.delta > 0.005 && "tone-bad")} title={r.mom ? `${monthShort(r.mom.prev_month)} ${cr2(r.mom.prev)} to ${monthShort(r.mom.last_month)} ${cr2(r.mom.last)}` : dashReason("value", "No month before in gold")}>
          {r.mom ? <>{cr2s(r.mom.delta)}<span className="ml-1 text-[10.5px] text-muted-foreground">{r.mom.delta_pct === null ? "" : pct1(r.mom.delta_pct)}</span></> : DASH}
        </td>
        <td className={cn("num-mono whitespace-nowrap px-3 py-1.5 text-right", r.ly && r.ly.delta > 0.005 && "tone-bad")} title={r.ly ? `Last year ${cr2(r.ly.total)} · on books only ${r.ly.delta_pct_book === null ? DASH : pct1(r.ly.delta_pct_book)}` : dashReason("value", d.notes.find((n) => n.startsWith("No last-year")) ?? "No comparable months last year")}>
          {r.ly ? <>{cr2s(r.ly.delta)}<span className="ml-1 text-[10.5px] text-muted-foreground">{r.ly.delta_pct === null ? "" : pct1(r.ly.delta_pct)}</span></> : DASH}
        </td>
      </tr>
    );
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-separate border-spacing-0 text-[12.5px]" data-testid="exp-heads-table" data-mode={mode}>
        <thead>
          <tr className="border-b text-[10.5px] uppercase tracking-wider text-muted-foreground">
            <th className="sticky left-0 z-20 border-b border-r bg-card px-3 py-2 text-left font-semibold">INR Cr</th>
            <th className={th}>{mode === "total" ? "Total" : mode === "book" ? "Book" : "Adjustment"}</th>
            <th className={th}>{scope === "store" ? "% of net sales" : "Per DC site"}</th>
            <th className={th}>Share</th>
            <th className={th}>MoM</th>
            <th className={th}>vs last year</th>
          </tr>
        </thead>
        <tbody>
          {d.heads.map((r) => row(r))}
          {row({ ...d.total, label: d.scope_label }, true)}
        </tbody>
      </table>
    </div>
  );
}

function Body({ scope, months }: { scope: "store" | "dc"; months: string[] }) {
  const s = useExpSearch();
  const set = useSetExp();
  const entityUrl = useMgmtEntity();
  const entity: MgmtEntity = scope === "store" ? "subco" : entityUrl;
  const mode = modeOf(s);
  const q = queryOf(scope, entity, months, s);
  const { from, to } = resolvePeriod(months, s);
  const summary = useExpSummary(q);
  const { next } = useHere([], `${COPY[scope].title} · ${monthShort(from)}${from !== to ? ` to ${monthShort(to)}` : ""}`);
  const headLabels: Record<string, string> = Object.fromEntries((summary.data?.heads ?? []).map((h) => [h.key, h.label]));
  const drillOpen = !!(s.head || s.site || s.gl);
  return (
    <>
      <div data-testid="exp-controls" className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b bg-card px-5 py-2 text-[12px]">
        <MonthRange months={months} from={from} to={to} onChange={(f, t) => set({ from: f, to: t })} />
        <div className="h-5 w-px bg-border" />
        <EntityBar scope={scope} entity={entity} />
        <div className="h-5 w-px bg-border" />
        <ModeToggle mode={mode} />
        <div className="relative ml-auto">{summary.data && <ControlsBadge d={summary.data} />}</div>
      </div>
      <LiveBoundary query={summary} skeleton={<Skeleton className="m-4 h-[320px]" />}>
        {(d) => (
          <>
            <Strip d={d} scope={scope} mode={mode} />
            {d.notes.length > 0 && (
              <ul data-testid="exp-notes" className="space-y-0.5 border-b bg-background px-5 py-2 text-[11.5px] text-muted-foreground">
                {d.notes.map((n) => <li key={n} className="flex items-start gap-1.5"><Info className="mt-0.5 h-3 w-3 shrink-0" />{n}</li>)}
              </ul>
            )}
            <div className="space-y-3 p-3">
              <Panel testId="exp-heads" eyebrow={`${d.entity_label} · ${monthShort(d.from_month)}${d.from_month !== d.to_month ? ` to ${monthShort(d.to_month)}` : ""}`} title={`${d.scope_label} by head (INR Cr)`} right={<span className="text-[11.5px] text-muted-foreground">Click a head to see its ledgers, then the sites, then the vouchers.</span>}>
                <HeadsTable d={d} scope={scope} mode={mode} openHead={s.head} onHead={(h) => set({ head: s.head === h.key ? undefined : h.key, gl: undefined, site: undefined, se: undefined, sn: undefined })} />
              </Panel>
              {drillOpen && <DrillPanel q={q} s={s} set={set} next={next} headLabel={(k) => headLabels[k] ?? k} />}
              <ExpTrendPanel q={q} mode={mode} firstMonth={months[0]} />
              <ExpSitesPanel q={q} scope={scope} mode={mode} s={s} headLabels={headLabels} onPick={(r) => set({ site: r.site_code, se: r.entity, sn: r.short_name ?? r.name ?? undefined, gl: undefined, head: s.head })} />
              <ExpExceptionsPanel q={q} next={next} onSite={(e) => set({ site: e.site_code ?? undefined, se: e.entity, sn: e.site_name ?? undefined, gl: undefined, head: e.head ?? undefined })} />
            </div>
          </>
        )}
      </LiveBoundary>
    </>
  );
}

export function ExpensesPage({ scope }: { scope: "store" | "dc" }) {
  return (
    <MgmtFrame active={scope === "store" ? "store-exp" : "dc-exp"} entitySelector={false} subtitle={COPY[scope].subtitle}>
      {(months) => <Body scope={scope} months={months} />}
    </MgmtFrame>
  );
}
