import { useMemo, useState } from "react";
import { CheckCircle2, ChevronRight, X } from "lucide-react";
import { usePnlHierarchy, usePnlLedgers, usePnlReconciliation, usePnlRun, usePnlStore, usePnlStores, usePnlSummary, usePnlTrend } from "@/api/pnlLiveHooks";
import { fmtDate } from "@/lib/format";
import { DASH, fmtCr, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Basis, PnlLine, PnlMoney, PnlQuery, PnlStoreRow } from "@/types/pnlLive";
import { Skeleton } from "../common";
import { DataStateBadge, LiveBoundary, NotAvailable } from "../creditors/parts";
import { Panel, WorkspaceHeader } from "../panels";
import { monthLabel, PnlTrendChart, PnlWaterfall } from "./PnlCharts";
import { GrowthMarginQuadrant, reference } from "./PnlQuadrant";

/**
 * Store P&L actuals, on REAL data (the verified pnl mart).
 *
 *   Net sales      books, ex-GST (the POS value includes GST; the books do not)
 *   COGS           the COGS table (it has no posted / unposted split)
 *   Store opex     books
 *   Contribution   gross margin + store opex: BEFORE other income, finance cost and any head-office allocation
 * Budget is not available and is shown blank. Ledgers the finance mapping does not know are excluded from every total and listed on the reconciliation panel.
 */

const cr = (m: string | null | undefined) => (m === null || m === undefined ? DASH : fmtCr(Number(m) / 1e7));
const pct = (m: string | null | undefined, signed = false) => (m === null || m === undefined ? DASH : fmtPct(Number(m), { signed }));
const tone = (m: string | null | undefined) => (m !== null && m !== undefined && Number(m) < 0 ? "tone-bad" : "");
const FILTERS = [
  { key: "region", label: "Region" },
  { key: "cluster", label: "Cluster" },
  { key: "state", label: "State" },
  { key: "vintage", label: "Same / new store" },
] as const;
type FilterKey = (typeof FILTERS)[number]["key"];

function monthOptions(asOf: string): string[] {
  const end = asOf.slice(0, 7);
  const out: string[] = [];
  let [y, m] = [2025, 4];
  while (`${y}-${String(m).padStart(2, "0")}` <= end) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m += 1;
    if (m > 12) [y, m] = [y + 1, 1];
  }
  return out;
}

function Cell({ label, value, exact, sub, testId, tone: t }: { label: string; value: string; exact?: string; sub?: string; testId: string; tone?: string }) {
  return (
    <div className="flex min-w-0 flex-col items-start gap-0.5 px-4 py-3" data-testid={testId}>
      <span className="eyebrow">{label}</span>
      <span data-testid={`${testId}-value`} data-exact={exact} className={cn("num-mono whitespace-nowrap text-[22px] font-semibold leading-tight", t)}>
        {value}
      </span>
      {sub && <span className="num max-w-full truncate text-[11.5px] text-muted-foreground">{sub}</span>}
    </div>
  );
}

function Strip({ q, filtered }: { q: PnlQuery; filtered: boolean }) {
  const s = usePnlSummary(q);
  return (
    <LiveBoundary query={s} skeleton={<Skeleton className="m-4 h-[88px]" />}>
      {(d) => {
        const t = d.totals;
        const c = d.comparison;
        const g = c?.growth;
        return (
          <section aria-label="Verified figures" data-testid="pnl-strip" className="border-b bg-card">
            <div className="grid grid-cols-7 divide-x @max-[1300px]:grid-cols-4 @max-[1300px]:divide-y @max-[640px]:grid-cols-2">
              <Cell testId="strip-sales" label="Net sales ex-GST" value={cr(t.revenue)} exact={t.revenue} sub={`${monthLabel(d.scope.from_month)} to ${monthLabel(d.scope.to_month)}${d.scope.partial_last_month ? " (last month partial)" : ""}`} />
              <Cell testId="strip-gm" label="Gross margin" value={cr(t.gross_margin)} exact={t.gross_margin} sub={`${pct(t.gross_margin_pct)} of sales`} />
              <Cell testId="strip-opex" label="Store opex" value={cr(t.opex)} exact={t.opex} sub={`${pct(t.opex_pct)} of sales`} tone="" />
              <Cell testId="strip-contribution" label="Contribution" value={cr(t.contribution)} exact={t.contribution} sub={`${pct(t.contribution_pct)} of sales`} tone={tone(t.contribution)} />
              <Cell testId="strip-growth" label="Sales growth vs last year" value={g ? pct(g.revenue_pct, true) : DASH} exact={g?.revenue_pct ?? undefined} sub={c ? `${monthLabel(c.period.from_month)} to ${monthLabel(c.period.to_month)} · complete months` : "no last-year data for these months"} tone={tone(g?.revenue_pct)} />
              <Cell testId="strip-stores" label={filtered ? "Stores in this view" : "Stores trading"} value={d.stores_in_scope.toLocaleString("en-IN")} sub={filtered ? "after the filters" : "sites with sales"} />
              <Cell testId="strip-budget" label="Budget" value="Not available" sub="no FY26-27 plan in the sources" tone="text-muted-foreground" />
            </div>
            <div data-testid="strip-note" className="border-t bg-[oklch(0.985_0.006_265)] px-4 py-1.5 text-[11.5px] text-muted-foreground">
              <span className="font-semibold text-foreground">Contribution is before other income, finance cost and head-office allocation.</span> Budget: not available (blank). {d.flags.cogs_lags_books && <>COGS runs to {fmtDate(d.flags.cogs_through)}, the books to {fmtDate(d.flags.books_through)}. </>}
              {d.flags.provisional_months.length > 0 && <>Provisional (unposted sales): {d.flags.provisional_months.map(monthLabel).join(", ")}. </>}
              {d.excluded_unmapped.ledgers > 0 && <>{d.excluded_unmapped.ledgers} ledgers are {d.excluded_unmapped.label}: excluded from every total and listed under Reconciliation.</>}
            </div>
          </section>
        );
      }}
    </LiveBoundary>
  );
}

function Controls({ asOf, q, setQ }: { asOf: string; q: PnlQuery; setQ: (f: (p: PnlQuery) => PnlQuery) => void }) {
  const months = useMemo(() => monthOptions(asOf), [asOf]);
  const hier = usePnlHierarchy({ basis: q.basis });
  const sel = "h-7 rounded border bg-card px-1.5 text-[12px]";
  const last = months[months.length - 1];
  const idx = months.length - 1;
  const preset = (from: string, to: string) => setQ((p) => ({ ...p, from_month: from, to_month: to }));
  return (
    <div data-testid="pnl-controls" className="flex flex-wrap items-center gap-2 border-b bg-card px-4 py-2 text-[12px]">
      <label className="flex items-center gap-1">
        <span className="eyebrow">From</span>
        <select aria-label="From month" data-testid="ctl-from" className={sel} value={q.from_month ?? ""} onChange={(e) => setQ((p) => ({ ...p, from_month: e.target.value || undefined }))}>
          <option value="">FY start</option>
          {months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-1">
        <span className="eyebrow">To</span>
        <select aria-label="To month" data-testid="ctl-to" className={sel} value={q.to_month ?? ""} onChange={(e) => setQ((p) => ({ ...p, to_month: e.target.value || undefined }))}>
          <option value="">As-of month</option>
          {months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
        </select>
      </label>
      <div className="flex items-center gap-1">
        <button className="press rounded border px-2 py-1 font-medium hover:bg-muted" data-testid="preset-ytd" onClick={() => preset("", "")}>FY YTD</button>
        <button className="press rounded border px-2 py-1 font-medium hover:bg-muted" data-testid="preset-last3" onClick={() => preset(months[Math.max(0, idx - 3)], months[Math.max(0, idx - 1)])}>Last 3 complete months</button>
        <button className="press rounded border px-2 py-1 font-medium hover:bg-muted" data-testid="preset-month" onClick={() => preset(last, last)}>This month</button>
      </div>
      <div className="mx-1 h-5 w-px bg-border" />
      {FILTERS.map((f) => (
        <label key={f.key} className="flex items-center gap-1">
          <span className="eyebrow">{f.label}</span>
          <select aria-label={f.label} data-testid={`ctl-${f.key}`} className={sel} value={q[f.key as FilterKey] ?? ""} onChange={(e) => setQ((p) => ({ ...p, [f.key]: e.target.value || undefined }))}>
            <option value="">All</option>
            {(hier.data?.options[f.key] ?? []).map((o) => <option key={o.value} value={o.value}>{`${o.value === "-" ? "Unassigned" : o.value} (${o.stores})`}</option>)}
          </select>
        </label>
      ))}
      <div className="mx-1 h-5 w-px bg-border" />
      <div role="group" aria-label="Basis" className="flex overflow-hidden rounded border">
        {(["all", "posted"] as Basis[]).map((b) => (
          <button key={b} data-testid={`basis-${b}`} aria-pressed={q.basis === b} onClick={() => setQ((p) => ({ ...p, basis: b }))} className={cn("press px-2 py-1 font-medium", q.basis === b ? "bg-foreground text-background" : "hover:bg-muted")}>
            {b === "all" ? "All entries" : "Posted only"}
          </button>
        ))}
      </div>
      {(q.region || q.cluster || q.state || q.vintage || q.from_month || q.to_month) && (
        <button data-testid="ctl-clear" className="press inline-flex items-center gap-1 rounded border px-2 py-1 hover:bg-muted" onClick={() => setQ((p) => ({ basis: p.basis }))}>
          <X className="h-3 w-3" /> Clear
        </button>
      )}
    </div>
  );
}

const LINE_TONE: Record<PnlLine["section"], string> = { REVENUE: "", COGS_BOOKS: "", STORE_OPEX: "", OTHER_INCOME: "", FINANCE_COST: "" };

function Lines({ lines, revenue, onGroup, selected }: { lines: PnlLine[]; revenue: string; onGroup?: (g: string) => void; selected?: string | null }) {
  const rev = Number(revenue) || 0;
  let last = "";
  return (
    <table className="w-full text-[12.5px]" data-testid="pnl-lines">
      <thead>
        <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
          <th className="px-4 py-2 font-semibold">Line</th>
          <th className="px-3 py-2 text-right font-semibold">₹ Cr</th>
          <th className="px-3 py-2 text-right font-semibold">% of sales</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((l) => {
          const head = l.section !== last;
          last = l.section;
          return [
            head && (
              <tr key={`h-${l.section}`} className="bg-[oklch(0.975_0.008_265)]">
                <td colSpan={3} className="px-4 py-1 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">{l.section_label}</td>
              </tr>
            ),
            <tr key={l.group_label} data-testid={`line-${l.group_label}`} data-exact={l.amount} className={cn("border-b last:border-0", onGroup && "cursor-pointer hover:bg-muted/50", selected === l.group_label && "bg-[oklch(0.95_0.025_265)]")} onClick={() => onGroup?.(l.group_label)}>
              <td className={cn("px-4 py-1.5", LINE_TONE[l.section])}>
                <span className="inline-flex items-center gap-1">{onGroup && <ChevronRight className="h-3 w-3 text-muted-foreground" />}{l.group_label.replace(/^\d+-/, "")}</span>
              </td>
              <td className={cn("num-mono px-3 py-1.5 text-right", tone(l.amount))}>{cr(l.amount)}</td>
              <td className="num-mono px-3 py-1.5 text-right text-muted-foreground">{rev ? fmtPct((Number(l.amount) / rev) * 100, { digits: 2 }) : DASH}</td>
            </tr>,
          ];
        })}
      </tbody>
    </table>
  );
}

function LedgerDrill({ site, group, q }: { site: string; group: string; q: PnlQuery }) {
  const l = usePnlLedgers(site, group, q);
  return (
    <div data-testid="ledger-drill" className="border-t bg-[oklch(0.985_0.006_265)]">
      <div className="flex items-center justify-between px-4 py-1.5 text-[11.5px]">
        <span className="font-semibold">{group.replace(/^\d+-/, "")}: the ledgers behind this line</span>
        {l.data && <span data-testid="ledger-reconciles" className={cn("inline-flex items-center gap-1", l.data.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}><CheckCircle2 className="h-3 w-3" /> {l.data.reconciles ? "adds up to the line" : "does not add up"}</span>}
      </div>
      <LiveBoundary query={l} skeleton={<Skeleton className="m-3 h-16" />}>
        {(d) => (
          <table className="w-full text-[12px]">
            <tbody>
              {d.ledgers.map((x) => (
                <tr key={x.glcode} className="border-t" data-testid={`ledger-${x.glcode}`} data-exact={x.amount}>
                  <td className="px-4 py-1">{x.ledger_name}<span className="ml-2 text-[10.5px] text-muted-foreground">{x.lines} lines · ledger {x.glcode}</span></td>
                  <td className={cn("num-mono px-3 py-1 text-right", tone(x.amount))}>{cr(x.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </LiveBoundary>
    </div>
  );
}

function StorePanel({ site, q, onClose }: { site: string; q: PnlQuery; onClose: () => void }) {
  const s = usePnlStore(site, q);
  const [group, setGroup] = useState<string | null>(null);
  return (
    <Panel
      testId="store-panel"
      eyebrow="Store drill"
      title={s.data ? `${s.data.site.store_name ?? `Site ${site}`} · site ${site}` : `Site ${site}`}
      right={<button aria-label="Close store" data-testid="store-close" onClick={onClose} className="press rounded border p-1 hover:bg-muted"><X className="h-3.5 w-3.5" /></button>}
    >
      <LiveBoundary query={s} skeleton={<Skeleton className="m-4 h-[200px]" />}>
        {(d) => (
          <div className="grid grid-cols-[1.1fr_1fr] gap-0 divide-x @max-[900px]:grid-cols-1 @max-[900px]:divide-x-0">
            <div>
              <div className="flex flex-wrap gap-x-5 gap-y-1 border-b px-4 py-2 text-[12px] text-muted-foreground">
                {[d.site.region && `Region ${d.site.region}`, d.site.cluster && `Cluster ${d.site.cluster}`, d.site.state, d.site.vintage, d.site.opening_date && `Opened ${fmtDate(d.site.opening_date)}`].filter(Boolean).map((x) => <span key={String(x)}>{x}</span>)}
                <span data-testid="store-reconciles" className={cn("inline-flex items-center gap-1", d.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}><CheckCircle2 className="h-3 w-3" />{d.reconciles ? "months and lines add up" : "does not add up"}</span>
              </div>
              <div className="grid grid-cols-4 divide-x border-b">
                {[["Net sales", d.totals.revenue, null], ["Gross margin", d.totals.gross_margin, d.totals.gross_margin_pct], ["Store opex", d.totals.opex, d.totals.opex_pct], ["Contribution", d.totals.contribution, d.totals.contribution_pct]].map(([l, v, p]) => (
                  <div key={String(l)} className="px-3 py-2"><div className="eyebrow">{l}</div><div className={cn("num-mono text-[15px] font-semibold", tone(String(v)))} data-exact={String(v)}>{cr(String(v))}</div>{p !== null && <div className="num text-[11px] text-muted-foreground">{pct(p as string)}</div>}</div>
                ))}
              </div>
              <table className="w-full text-[12px]" data-testid="store-months">
                <thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-4 py-1.5 font-semibold">Month</th><th className="px-3 py-1.5 text-right font-semibold">Net sales</th><th className="px-3 py-1.5 text-right font-semibold">GM %</th><th className="px-3 py-1.5 text-right font-semibold">Contribution</th><th className="px-3 py-1.5 text-right font-semibold">%</th></tr></thead>
                <tbody>
                  {d.months.map((m) => (
                    <tr key={m.month} className="border-b last:border-0"><td className="px-4 py-1">{monthLabel(m.month)}</td><td className="num-mono px-3 py-1 text-right">{cr(m.revenue)}</td><td className="num-mono px-3 py-1 text-right">{pct(m.gross_margin_pct)}</td><td className={cn("num-mono px-3 py-1 text-right", tone(m.contribution))}>{cr(m.contribution)}</td><td className="num-mono px-3 py-1 text-right text-muted-foreground">{pct(m.contribution_pct)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <Lines lines={d.lines} revenue={d.totals.revenue} onGroup={(g) => setGroup((p) => (p === g ? null : g))} selected={group} />
              {group && <LedgerDrill site={site} group={group} q={q} />}
            </div>
          </div>
        )}
      </LiveBoundary>
    </Panel>
  );
}

interface LeagueView { id: string; label: string; sort: string; order: "asc" | "desc"; floor: boolean; note: string }
const VIEWS: LeagueView[] = [
  { id: "top", label: "Top contribution", sort: "contribution", order: "desc", floor: false, note: "highest contribution ₹" },
  { id: "bottom", label: "Bottom contribution", sort: "contribution", order: "asc", floor: false, note: "lowest contribution ₹" },
  { id: "gm_high", label: "Highest GM %", sort: "gross_margin_pct", order: "desc", floor: true, note: "highest gross margin %" },
  { id: "gm_low", label: "Lowest GM %", sort: "gross_margin_pct", order: "asc", floor: true, note: "lowest gross margin %" },
  { id: "opex_high", label: "Highest opex %", sort: "opex_pct", order: "desc", floor: true, note: "highest store opex as a share of sales" },
  { id: "grow_fast", label: "Fastest growth", sort: "growth", order: "desc", floor: true, note: "fastest sales growth vs last year" },
  { id: "grow_down", label: "Biggest decline", sort: "growth", order: "asc", floor: true, note: "biggest sales decline vs last year" },
  { id: "all", label: "All stores", sort: "contribution", order: "desc", floor: false, note: "every store, by contribution" },
];
const FLOORS = [0, 0.5, 1, 2, 5];

function League({ q, onPick, picked }: { q: PnlQuery; onPick: (s: string) => void; picked: string | null }) {
  const [viewId, setViewId] = useState("top");
  const [floor, setFloor] = useState(1);
  const [limit, setLimit] = useState(50);
  const v = VIEWS.find((x) => x.id === viewId) ?? VIEWS[0];
  const lim = v.id === "all" ? limit : 10;
  const stores = usePnlStores(q, v.sort, v.order, lim, v.floor ? floor * 1e7 : undefined);
  return (
    <Panel
      testId="league-panel"
      eyebrow="Real · verified"
      title="Store league: who earns their place"
      right={
        <div className="flex flex-wrap items-center gap-2">
          {v.floor && (
            <label className="flex items-center gap-1 text-[11.5px]" title="Percentage and growth rankings ignore very small stores">
              <span className="eyebrow">Min net sales</span>
              <select aria-label="Minimum net sales" data-testid="league-floor" value={floor} onChange={(e) => setFloor(Number(e.target.value))} className="h-7 rounded border bg-card px-1.5 text-[12px]">
                {FLOORS.map((f) => <option key={f} value={f}>{f === 0 ? "none" : `₹${f} Cr`}</option>)}
              </select>
            </label>
          )}
          <label className="flex items-center gap-1 text-[11.5px]"><span className="eyebrow">View</span>
            <select aria-label="League view" data-testid="league-view" value={viewId} onChange={(e) => setViewId(e.target.value)} className="h-7 rounded border bg-card px-1.5 text-[12px] font-medium">
              {VIEWS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
            </select>
          </label>
        </div>
      }
    >
      <div role="tablist" aria-label="League views" className="flex flex-wrap gap-1 border-b px-3 py-1.5" data-testid="league-tabs">
        {VIEWS.map((x) => (
          <button key={x.id} role="tab" data-testid={`league-${x.id}`} aria-selected={viewId === x.id} aria-pressed={viewId === x.id} onClick={() => setViewId(x.id)}
            className={cn("press rounded px-2 py-1 text-[12px] font-medium", viewId === x.id ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>{x.label}</button>
        ))}
      </div>
      <LiveBoundary query={stores} skeleton={<Skeleton className="m-4 h-[260px]" />}>
        {(p) => (
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]" data-testid="league-table" data-view={v.id}>
              <thead>
                <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-2 font-semibold">#</th>
                  <th className="px-3 py-2 font-semibold">Store</th>
                  <th className="px-3 py-2 font-semibold">Region · cluster</th>
                  <th className="px-3 py-2 text-right font-semibold">Net sales</th>
                  <th className="px-3 py-2 text-right font-semibold">GM %</th>
                  <th className="px-3 py-2 text-right font-semibold">Opex %</th>
                  <th className="px-3 py-2 text-right font-semibold">Contribution</th>
                  <th className="px-3 py-2 text-right font-semibold">Contrib. %</th>
                  <th className="px-3 py-2 text-right font-semibold">Growth</th>
                </tr>
              </thead>
              <tbody>
                {p.stores.map((s: PnlStoreRow) => (
                  <tr key={s.site_code} data-testid={`league-row-${s.site_code}`} data-exact={s.contribution} onClick={() => onPick(s.site_code)} className={cn("cursor-pointer border-b last:border-0 hover:bg-muted/50", picked === s.site_code && "bg-[oklch(0.95_0.025_265)]")}>
                    <td className="px-4 py-1.5 text-muted-foreground">{s.rank}</td>
                    <td className="px-3 py-1.5"><span className="font-medium">{s.store_name ?? `Site ${s.site_code}`}</span><span className="ml-1.5 text-[10.5px] text-muted-foreground">#{s.site_code}</span>{s.vintage === "NEW STORE" && <span className="ml-1.5 rounded bg-secondary px-1 text-[10px] font-semibold">new</span>}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{[s.region, s.cluster].filter((x) => x && x !== "-").join(" · ") || DASH}</td>
                    <td className="num-mono px-3 py-1.5 text-right">{cr(s.revenue)}</td>
                    <td className="num-mono px-3 py-1.5 text-right">{pct(s.gross_margin_pct)}</td>
                    <td className="num-mono px-3 py-1.5 text-right">{pct(s.opex_pct)}</td>
                    <td className={cn("num-mono px-3 py-1.5 text-right font-semibold", tone(s.contribution))}>{cr(s.contribution)}</td>
                    <td className={cn("num-mono px-3 py-1.5 text-right", tone(s.contribution_pct))}>{pct(s.contribution_pct)}</td>
                    <td className={cn("num-mono px-3 py-1.5 text-right", tone(s.growth_pct))}>{pct(s.growth_pct, true)}</td>
                  </tr>
                ))}
                {p.stores.length === 0 && <tr><td colSpan={9} className="px-4 py-6 text-center text-muted-foreground" data-testid="league-empty">No store qualifies{v.floor && floor > 0 ? ` at a ₹${floor} Cr net-sales floor` : ""}.</td></tr>}
              </tbody>
            </table>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-2 text-[11.5px] text-muted-foreground">
              <span data-testid="league-count">{p.returned} of {p.stores_total} stores · {v.note}{v.floor && floor > 0 ? ` · stores under ₹${floor} Cr net sales left out` : ""} · growth over {monthLabel(p.growth_basis.from_month)} to {monthLabel(p.growth_basis.to_month)}, last year's same months · stores with no comparable last year come last</span>
              <span data-testid="league-reconciles" className={cn("inline-flex items-center gap-1", p.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}><CheckCircle2 className="h-3 w-3" />{v.floor && floor > 0 ? "ranking of the stores above the floor" : p.reconciles ? `all stores add up to ${cr(p.parent.contribution)} contribution` : "does not add up"}</span>
              {v.id === "all" && p.returned < p.stores_total && <button className="press rounded border px-2 py-1 font-medium hover:bg-muted" onClick={() => setLimit((l) => l + 50)} data-testid="league-more">Show more</button>}
            </div>
          </div>
        )}
      </LiveBoundary>
    </Panel>
  );
}

function Quadrant({ q, onPick, picked }: { q: PnlQuery; onPick: (s: string) => void; picked: string | null }) {
  const stores = usePnlStores(q, "contribution", "desc", 500, 0.5e7);
  return (
    <Panel testId="quadrant-panel" eyebrow="Real · verified" title="Growth × contribution margin: strong, scale, mature, turnaround">
      <LiveBoundary query={stores} skeleton={<Skeleton className="m-4 h-[380px]" />}>
        {(p) => {
          const ref = reference(p.stores);
          return <GrowthMarginQuadrant stores={p.stores} refGrowth={ref.growth} refMargin={ref.margin} onPick={onPick} picked={picked} />;
        }}
      </LiveBoundary>
    </Panel>
  );
}

function Reconciliation({ q }: { q: PnlQuery }) {
  const r = usePnlReconciliation(q);
  return (
    <Panel testId="recon-panel" eyebrow="Reconciliation" title="What ties, what is excluded, what is missing">
      <LiveBoundary query={r} skeleton={<Skeleton className="m-4 h-[160px]" />}>
        {(d) => (
          <div className="grid grid-cols-3 divide-x @max-[1000px]:grid-cols-1 @max-[1000px]:divide-x-0 @max-[1000px]:divide-y">
            <div data-testid="recon-tieout">
              <div className="border-b px-4 py-2 text-[12px]"><span className="font-semibold">Books vs COGS table, sales ex-GST.</span> {d.sales_tieout.tied.toLocaleString("en-IN")} of {d.sales_tieout.site_months.toLocaleString("en-IN")} store-months agree within ₹{Number(d.tolerance_rupees).toLocaleString("en-IN")}.</div>
              <table className="w-full text-[12px]"><thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-4 py-1.5 font-semibold">Month</th><th className="px-3 py-1.5 text-right font-semibold">Tied</th><th className="px-3 py-1.5 text-right font-semibold">Gap ₹ Cr</th></tr></thead>
                <tbody>{d.sales_tieout.months.map((m) => <tr key={m.month} className="border-b last:border-0"><td className="px-4 py-1">{monthLabel(m.month)}</td><td className="num-mono px-3 py-1 text-right">{m.tied}/{m.site_months}</td><td className={cn("num-mono px-3 py-1 text-right", Number(m.difference) !== 0 && "text-muted-foreground")}>{cr(m.difference)}</td></tr>)}</tbody></table>
            </div>
            <div data-testid="recon-excluded">
              <div className="border-b px-4 py-2 text-[12px]"><span className="font-semibold">{d.excluded_unmapped.label}: {d.excluded_unmapped.count} ledgers in this period</span> ({d.excluded_unmapped.run_ledgers} across the run; net {cr(d.excluded_unmapped.net)} in the period). The finance mapping has no group for them, so none is in any total. Mostly purchases and stock transfers, which reach the P&L through COGS.</div>
              <table className="w-full text-[12px]"><tbody>{d.excluded_unmapped.ledgers.slice(0, 12).map((l) => <tr key={l.glcode} className="border-b last:border-0"><td className="px-4 py-1">{l.ledger_name}</td><td className={cn("num-mono px-3 py-1 text-right", tone(l.net))}>{cr(l.net)}</td></tr>)}</tbody></table>
              <div className="px-4 py-1.5 text-[11px] text-muted-foreground">Finance needs to classify each one before it can enter the P&L. None is assigned automatically.</div>
            </div>
            <div data-testid="recon-missing">
              <div className="border-b px-4 py-2 text-[12px]"><span className="font-semibold">{d.sites_without_books_sales.count} sites have sales in the COGS table but none in the books</span> ({cr(d.sites_without_books_sales.sales_ex_gst)} ex-GST). They are not stores in the league: their costs and COGS count for the company, not for a store.</div>
              <table className="w-full text-[12px]"><tbody>{d.sites_without_books_sales.sites.map((s) => <tr key={s.site_code} className="border-b last:border-0"><td className="px-4 py-1">{s.store_name ?? `Site ${s.site_code}`} <span className="text-[10.5px] text-muted-foreground">#{s.site_code}</span></td><td className="num-mono px-3 py-1 text-right">{cr(s.sales_ex_gst)}</td></tr>)}</tbody></table>
              <div className="border-t px-4 py-1.5 text-[11px] text-muted-foreground">{d.flags.cogs_has_no_posting_status}</div>
            </div>
          </div>
        )}
      </LiveBoundary>
    </Panel>
  );
}

function CogsWatch({ months }: { months: { month: string; revenue: string; cogs: string; partial: boolean }[] }) {
  const rows = months.filter((m) => !m.partial).map((m) => ({ month: m.month, p: (Number(m.cogs) / (Number(m.revenue) || 1)) * 100 }));
  if (rows.length < 3) return null;
  const base = [...rows].map((r) => r.p).sort((a, b) => a - b)[Math.floor(rows.length / 2)];
  const high = rows.filter((r) => r.p >= base + 6);
  if (!high.length) return null;
  return (
    <div data-testid="cogs-watch" className="border-t bg-[oklch(0.985_0.03_90)] px-4 py-2 text-[11.5px] text-[oklch(0.4_0.09_70)]">
      <span className="font-semibold">COGS watch.</span> COGS was {high.map((r) => `${r.p.toFixed(0)}% of net sales in ${monthLabel(r.month)}`).join(", ")} against a typical {base.toFixed(0)}%. The cause is not known (cost adjustments, stock corrections or timing): confirm with Finance before reading margin trends.
    </div>
  );
}

export function PnlRoom() {
  const run = usePnlRun();
  const [q, setQ0] = useState<PnlQuery>({ basis: "all" });
  const [site, setSite] = useState<string | null>(null);
  const setQ = (f: (p: PnlQuery) => PnlQuery) => setQ0((p) => f(p));
  const summary = usePnlSummary(q);
  const trend = usePnlTrend(q);
  const filtered = !!(q.region || q.cluster || q.state || q.vintage);
  return (
    <div data-testid="pnl-room" className="@container flex min-w-0 flex-1 flex-col overflow-y-auto bg-background">
      <WorkspaceHeader
        eyebrow="Performance"
        title="Profitability"
        subtitle="Net sales ex-GST and store opex from the books; COGS from the COGS table. Contribution is before head-office allocation. Budget is not available."
        right={run.data ? <DataStateBadge state={run.data.data_state} run={run.data.run_id} asOf={run.data.as_of_date} /> : undefined}
      />
      {run.isError ? (
        <NotAvailable testId="pnl-unavailable" title="No verified P&L run is available" reason="The P&L API did not return a verified run. Nothing is shown rather than a demo figure." />
      ) : (
        <>
          <Controls asOf={run.data?.as_of_date ?? "2026-10-01"} q={q} setQ={setQ} />
          <Strip q={q} filtered={filtered} />
          <div className="grid grid-cols-2 gap-3 p-3 @max-[1000px]:grid-cols-1">
            <Panel testId="bridge-panel" eyebrow="Real · verified" title="From net sales to contribution" right={summary.data && <span className="num text-[11.5px] text-muted-foreground">{monthLabel(summary.data.scope.from_month)} to {monthLabel(summary.data.scope.to_month)} · {summary.data.scope.basis_label}</span>}>
              <LiveBoundary query={summary} skeleton={<Skeleton className="m-4 h-[300px]" />}>{(d) => <PnlWaterfall t={d.totals as PnlMoney} />}</LiveBoundary>
              {summary.data?.reconciliation && (
                <div data-testid="bridge-reconciles" className={cn("border-t px-4 py-1.5 text-[11.5px]", summary.data.reconciliation.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}>
                  <CheckCircle2 className="mr-1 inline h-3 w-3" />
                  {summary.data.reconciliation.reconciles ? `Company = stores (${cr(summary.data.reconciliation.stores.contribution)}) + head office and depots (${cr(summary.data.reconciliation.non_store.contribution)})` : "Company does not equal stores + non-store"}
                </div>
              )}
            </Panel>
            <Panel testId="trend-panel" eyebrow="Real · verified" title="Month by month, against last year">
              <LiveBoundary query={trend} skeleton={<Skeleton className="m-4 h-[300px]" />}>{(d) => <><PnlTrendChart months={d.months} /><CogsWatch months={d.months} /></>}</LiveBoundary>
            </Panel>
          </div>
          <div className="px-3 pb-3"><Quadrant q={q} onPick={setSite} picked={site} /></div>
          <div className="grid grid-cols-[1.6fr_1fr] gap-3 px-3 pb-3 @max-[1000px]:grid-cols-1">
            <League q={q} onPick={setSite} picked={site} />
            <Panel testId="lines-panel" eyebrow="Real · verified" title="P&L lines (finance groups)">
              <LiveBoundary query={summary} skeleton={<Skeleton className="m-4 h-[260px]" />}>{(d) => <Lines lines={d.lines} revenue={d.totals.revenue} />}</LiveBoundary>
            </Panel>
          </div>
          {site && (
            <div className="px-3 pb-3">
              <StorePanel site={site} q={q} onClose={() => setSite(null)} />
            </div>
          )}
          <div className="px-3 pb-3"><Reconciliation q={q} /></div>
          <div className="px-3 pb-6">
            <Panel testId="unavailable-panel" eyebrow="Not available" title="What the sources cannot support yet">
              <div className="divide-y">
                <NotAvailable testId="unavailable-budget" title="Budget" reason="No FY26-27 plan exists in the sources (the FY25-26 plan ended in March 2026). Budget and variance to budget are left blank; nothing is estimated." />
                <NotAvailable testId="unavailable-allocation" title="Head-office allocation and net store profit" reason="Contribution stops before head-office and depot costs. Allocating them needs a rule from Finance." />
                <NotAvailable testId="unavailable-hierarchy" title="Area and zone" reason="The site master carries region, cluster and state only. No area or zone is shown or invented." />
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
