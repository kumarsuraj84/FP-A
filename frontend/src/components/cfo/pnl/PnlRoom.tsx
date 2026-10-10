import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouterState } from "@tanstack/react-router";
import { CheckCircle2, ChevronRight, X } from "lucide-react";
import { lastCompleteMonthOf } from "@/api/liveCfoApi";
import { usePnlExpenseExceptions, usePnlHierarchy, usePnlLedgers, usePnlReconciliation, usePnlRevenueExceptions, usePnlRun, usePnlStore, usePnlStores, usePnlSummary, usePnlTrend } from "@/api/pnlLiveHooks";
import { fmtDate } from "@/lib/format";
import { DASH, fmtCr, fmtPct } from "@/lib/format";
import { BOOKS_BASIS_NOTE, T, groupName, vintageLabel } from "@/lib/nomenclature";
import { cn } from "@/lib/utils";
import type { Basis, PnlLine, PnlMoney, PnlQuery, PnlStoreRow } from "@/types/pnlLive";
import { Skeleton } from "../common";
import { DataStateBadge, LiveBoundary, NotAvailable } from "../creditors/parts";
import { Panel, WorkspaceHeader } from "../panels";
import { BasisTag } from "../BasisTag";
import { monthLabel, PnlTrendChart, PnlWaterfall } from "./PnlCharts";
import { PnlComparisonTab, PnlPivotTab } from "./PnlPivotTab";
import { ExpenseExceptionsTab, HeatMapTab, PeersTab, QualityTab, RevenueExceptionsTab } from "./PnlReviewTabs";
import { FLAG_LABEL, SEVERITY_STYLE, lakh } from "./pnlFormat";
import { GrowthMarginQuadrant, reference } from "./PnlQuadrant";
import { AppLink } from "../entry/parts";
import { ledgerListHref } from "@/lib/entryLinks";

/**
 * Store P&L actuals, on REAL data (the verified pnl mart), in the finance MIS vocabulary (docs/NOMENCLATURE.md). Books basis, before management adjustments.
 *
 *   Revenue from operations  books, ex-GST (the POS value includes GST; the books do not)
 *   Material Cost            the COGS table (it has no posted / unposted split)
 *   Store Expenses           books, STORES location only
 *   Store EBITDA             Material Margin (Gross Margin per store) less Store Expenses: BEFORE DC cost, HO cost, interest income and finance cost
 *   Corporate EBITDA         Store EBITDA less DC cost and HO cost
 * AOP is not available and is shown blank. Ledgers neither mapping knows are excluded from every total and listed on the reconciliation panel.
 */

const cr = (m: string | null | undefined) => (m === null || m === undefined ? DASH : fmtCr(Number(m) / 1e7));
const pct = (m: string | null | undefined, signed = false) => (m === null || m === undefined ? DASH : fmtPct(Number(m), { signed }));
const tone = (m: string | null | undefined) => (m !== null && m !== undefined && Number(m) < 0 ? "tone-bad" : "");
const FILTERS = [
  { key: "region", label: "Region" },
  { key: "cluster", label: "Cluster" },
  { key: "state", label: "State" },
  { key: "vintage", label: "Store type (Same Store / Non-LFL)" },
] as const;
type FilterKey = (typeof FILTERS)[number]["key"];

/** A tie-out gap: rupees when it is small (a few paise or rupees must not read as "₹0.0 L"), crore or lakh when it is not. */
const gap = (m: string) => (Math.abs(Number(m)) < 1e5 ? `${Number(m) < 0 ? "−" : ""}₹${Math.abs(Math.round(Number(m))).toLocaleString("en-IN")}` : cr(m));

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

function Cell({ label, value, exact, sub, testId, tone: t, tag }: { tag?: ReactNode; label: string; value: string; exact?: string; sub?: string; testId: string; tone?: string }) {
  return (
    <div className="flex min-w-0 flex-col items-start gap-0.5 px-4 py-3" data-testid={testId}>
      <span className="eyebrow">{label}{tag}</span>
      <span data-testid={`${testId}-value`} data-exact={exact} className={cn("num-mono whitespace-nowrap text-[22px] font-semibold leading-tight", t)}>
        {value}
      </span>
      {sub && <span className="num line-clamp-2 max-w-full text-[11.5px] leading-snug text-muted-foreground">{sub}</span>}
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
          <section aria-label="Verified figures" data-testid="pnl-strip" aria-busy={s.isPlaceholderData} data-updating={s.isPlaceholderData || undefined} className={cn("border-b bg-card transition-opacity", s.isPlaceholderData && "opacity-50")}>
            {s.isPlaceholderData && <div role="status" className="px-4 pt-1.5 text-[11px] font-medium text-muted-foreground">Updating for the selected period…</div>}
            <div className="grid grid-cols-6 divide-x @max-[1300px]:grid-cols-3 @max-[1300px]:divide-y @max-[640px]:grid-cols-2">
              <Cell testId="strip-sales" label={T.revenue} value={cr(t.revenue)} exact={t.revenue} sub={`${monthLabel(d.scope.from_month)} to ${monthLabel(d.scope.to_month)}${d.scope.partial_last_month ? " (last month partial)" : ""}`} />
              <Cell testId="strip-gm" label={filtered ? T.grossMargin : T.materialMargin} value={cr(t.gross_margin)} exact={t.gross_margin} sub={`${pct(t.gross_margin_pct)} of revenue`} />
              <Cell testId="strip-opex" label={T.storeExpenses} value={cr(t.opex)} exact={t.opex} sub={`${pct(t.opex_pct)} of revenue`} tone="" />
              <Cell testId="strip-contribution" label={filtered ? T.fourWall : `${T.storeEbitda} — Books`} value={cr(t.contribution)} exact={t.contribution} sub={`${pct(t.contribution_pct)} of revenue`} tone={tone(t.contribution)} />
              {filtered && <Cell testId="strip-stores" label="Stores in this view" value={d.stores_in_scope.toLocaleString("en-IN")} sub="after the filters" />}
              {filtered
                ? <Cell testId="strip-corporate" label="DC and HO cost" value="Company level" sub="not apportioned to a filtered view" tone="text-muted-foreground" />
                : <Cell testId="strip-corporate" label={`${T.corporateEbitda} — Books`} value={cr(t.corporate_ebitda)} exact={t.corporate_ebitda} sub={`after DC cost ${cr(t.dc_cost)} and HO cost ${cr(t.ho_cost)}`} tone={tone(t.corporate_ebitda)} />}
              <Cell testId="strip-growth" label={`${T.yoy} vs ${T.ly}`} value={g ? pct(g.revenue_pct, true) : DASH} exact={g?.revenue_pct ?? undefined} sub={c ? `${monthLabel(c.period.from_month)} to ${monthLabel(c.period.to_month)} · complete months` : `no ${T.ly} data for these months`} tone={tone(g?.revenue_pct)} />
            </div>
            <div data-testid="strip-note" className="border-t bg-[oklch(0.985_0.006_265)] px-4 py-1.5 text-[11.5px] text-muted-foreground">
              <span className="font-semibold text-foreground">{BOOKS_BASIS_NOTE}</span> {T.storeEbitda} is {T.materialMargin} less {T.storeExpenses} (STORES location only), before {T.dcCost}, {T.hoCost}, interest income and finance cost; the 1% shrinkage provision is not in this view. {T.aop}: not available (blank). {d.flags.cogs_lags_books && <>{T.materialCost} runs to {fmtDate(d.flags.cogs_through)}, the books to {fmtDate(d.flags.books_through)}. </>}
              {d.flags.provisional_months.length > 0 && <>Provisional (unposted sales): {d.flags.provisional_months.map(monthLabel).join(", ")}. </>}
              {d.excluded_unmapped.ledgers > 0 && <>{d.excluded_unmapped.ledgers} ledgers are {d.excluded_unmapped.label}: excluded from every total and listed under Reconciliation. </>}
              <AppLink href="/mgmt" testId="strip-mgmt-link" className="font-semibold text-primary hover:underline">Management P&amp;L</AppLink>
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
            {(hier.data?.options[f.key] ?? []).map((o) => <option key={o.value} value={o.value}>{`${f.key === "vintage" ? vintageLabel(o.value) : o.value === "-" ? "Unassigned" : o.value} (${o.stores})`}</option>)}
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

const LINE_TONE: Record<PnlLine["section"], string> = { REVENUE: "", COGS_BOOKS: "", STORE_OPEX: "", DC_COST: "", HO_COST: "", OTHER_INCOME: "", FINANCE_COST: "" };

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
            <tr key={`${l.section}-${l.group_label}`} data-testid={l.section === "DC_COST" || l.section === "HO_COST" ? `line-${l.section}-${l.group_label}` : `line-${l.group_label}`} data-exact={l.amount} title={l.mis_line ? `${l.group_label} · rolls up to ${l.mis_line}` : l.group_label} className={cn("border-b last:border-0", onGroup && "cursor-pointer hover:bg-muted/50", selected === l.group_label && "bg-[oklch(0.95_0.025_265)]")} onClick={() => onGroup?.(l.group_label)}>
              <td className={cn("px-4 py-1.5", LINE_TONE[l.section])}>
                <span className="inline-flex items-center gap-1">{onGroup && <ChevronRight className="h-3 w-3 text-muted-foreground" />}{l.group_name ?? groupName(l.group_label)}</span>
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

/** The P&L view to come back to from the voucher drill: store, finance group and period are in the address (P&L state otherwise lives in the page). */
export function pnlBackHref(site: string, group: string | null, q: PnlQuery): string {
  const p = new URLSearchParams({ ps: site });
  if (group) p.set("pg", group);
  if (q.from_month) p.set("pf", q.from_month);
  if (q.to_month) p.set("pe", q.to_month);
  if (q.basis === "posted") p.set("pb", "posted");
  return `/profitability?${p}`;
}

function LedgerDrill({ site, group, q, storeName }: { site: string; group: string; q: PnlQuery; storeName?: string | null }) {
  const l = usePnlLedgers(site, group, q);
  const label = `Profitability · ${storeName ?? `site ${site}`} · ${groupName(group)}`;
  const back = [{ l: label, h: pnlBackHref(site, group, q) }];
  return (
    <div data-testid="ledger-drill" className="border-t bg-[oklch(0.985_0.006_265)]">
      <div className="flex items-center justify-between px-4 py-1.5 text-[11.5px]">
        <span className="font-semibold" title={group}>{groupName(group)}: the ledgers behind this line</span>
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
                  <td className="px-3 py-1 text-right">
                    <AppLink
                      testId={`ledger-vouchers-${x.glcode}`}
                      href={ledgerListHref({ site, glcode: x.glcode, from_month: d.scope?.from_month ?? q.from_month, to_month: d.scope?.to_month ?? q.to_month, basis: d.scope?.basis ?? q.basis, title: `${x.ledger_name} · ${storeName ?? `site ${site}`}` }, back)}
                      className="press whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-semibold text-primary hover:bg-muted"
                    >
                      Vouchers
                    </AppLink>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </LiveBoundary>
    </div>
  );
}

function StorePanel({ site, q, onClose, initialGroup }: { site: string; q: PnlQuery; onClose: () => void; initialGroup?: string | null }) {
  const s = usePnlStore(site, q);
  const [group, setGroup] = useState<string | null>(initialGroup ?? null);
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
                {[d.site.region && `Region ${d.site.region}`, d.site.cluster && `Cluster ${d.site.cluster}`, d.site.state, d.site.vintage && vintageLabel(d.site.vintage), d.site.opening_date && `Opened ${fmtDate(d.site.opening_date)}`].filter(Boolean).map((x) => <span key={String(x)}>{x}</span>)}
                <span data-testid="store-reconciles" className={cn("inline-flex items-center gap-1", d.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}><CheckCircle2 className="h-3 w-3" />{d.reconciles ? "months and lines add up" : "does not add up"}</span>
              </div>
              <div className="grid grid-cols-4 divide-x border-b">
                {[[T.revenue, d.totals.revenue, null], [T.grossMargin, d.totals.gross_margin, d.totals.gross_margin_pct], [T.storeExpenses, d.totals.opex, d.totals.opex_pct], [T.fourWall, d.totals.contribution, d.totals.contribution_pct]].map(([l, v, p]) => (
                  <div key={String(l)} className="px-3 py-2"><div className="eyebrow">{l}</div><div className={cn("num-mono text-[15px] font-semibold", tone(String(v)))} data-exact={String(v)}>{cr(String(v))}</div>{p !== null && <div className="num text-[11px] text-muted-foreground">{pct(p as string)}</div>}</div>
                ))}
              </div>
              <table className="w-full text-[12px]" data-testid="store-months">
                <thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-4 py-1.5 font-semibold">Month</th><th className="px-3 py-1.5 text-right font-semibold">Revenue</th><th className="px-3 py-1.5 text-right font-semibold">GM %</th><th className="px-3 py-1.5 text-right font-semibold">4-Wall EBITDA</th><th className="px-3 py-1.5 text-right font-semibold">%</th></tr></thead>
                <tbody>
                  {d.months.map((m) => (
                    <tr key={m.month} className="border-b last:border-0"><td className="px-4 py-1">{monthLabel(m.month)}</td><td className="num-mono px-3 py-1 text-right">{cr(m.revenue)}</td><td className="num-mono px-3 py-1 text-right">{pct(m.gross_margin_pct)}</td><td className={cn("num-mono px-3 py-1 text-right", tone(m.contribution))}>{cr(m.contribution)}</td><td className="num-mono px-3 py-1 text-right text-muted-foreground">{pct(m.contribution_pct)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <Lines lines={d.lines} revenue={d.totals.revenue} onGroup={(g) => setGroup((p) => (p === g ? null : g))} selected={group} />
              {group && <LedgerDrill site={site} group={group} q={q} storeName={d.site.store_name} />}
            </div>
          </div>
        )}
      </LiveBoundary>
    </Panel>
  );
}

interface LeagueView { id: string; label: string; sort: string; order: "asc" | "desc"; floor: boolean; note: string }
const VIEWS: LeagueView[] = [
  { id: "top", label: "Top 4-Wall EBITDA", sort: "contribution", order: "desc", floor: false, note: "highest 4-Wall EBITDA ₹" },
  { id: "bottom", label: "Bottom 4-Wall EBITDA", sort: "contribution", order: "asc", floor: false, note: "lowest 4-Wall EBITDA ₹" },
  { id: "gm_high", label: "Highest GM %", sort: "gross_margin_pct", order: "desc", floor: true, note: "highest Gross Margin %" },
  { id: "gm_low", label: "Lowest GM %", sort: "gross_margin_pct", order: "asc", floor: true, note: "lowest Gross Margin %" },
  { id: "opex_high", label: "Highest store expenses %", sort: "opex_pct", order: "desc", floor: true, note: "highest Store Expenses as a share of revenue" },
  { id: "grow_fast", label: "Fastest growth", sort: "growth", order: "desc", floor: true, note: "fastest Y-o-Y Growth in revenue" },
  { id: "grow_down", label: "Biggest decline", sort: "growth", order: "asc", floor: true, note: "biggest Y-o-Y decline in revenue" },
  { id: "all", label: "All stores", sort: "contribution", order: "desc", floor: false, note: "every store, by 4-Wall EBITDA" },
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
              <span className="eyebrow">Min revenue</span>
              <select aria-label="Minimum revenue" data-testid="league-floor" value={floor} onChange={(e) => setFloor(Number(e.target.value))} className="h-7 rounded border bg-card px-1.5 text-[12px]">
                {FLOORS.map((f) => <option key={f} value={f}>{f === 0 ? "none" : `₹${f} Cr`}</option>)}
              </select>
            </label>
          )}
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
                  <th className="px-3 py-2 text-right font-semibold">Revenue</th>
                  <th className="px-3 py-2 text-right font-semibold">GM %</th>
                  <th className="px-3 py-2 text-right font-semibold">Store exp. %</th>
                  <th className="px-3 py-2 text-right font-semibold">4-Wall EBITDA</th>
                  <th className="px-3 py-2 text-right font-semibold">4-Wall %</th>
                  <th className="px-3 py-2 text-right font-semibold">Growth</th>
                </tr>
              </thead>
              <tbody>
                {p.stores.map((s: PnlStoreRow) => (
                  <tr key={s.site_code} data-testid={`league-row-${s.site_code}`} data-exact={s.contribution} onClick={() => onPick(s.site_code)} className={cn("cursor-pointer border-b last:border-0 hover:bg-muted/50", picked === s.site_code && "bg-[oklch(0.95_0.025_265)]")}>
                    <td className="px-4 py-1.5 text-muted-foreground">{s.rank}</td>
                    <td className="px-3 py-1.5"><span className="font-medium">{s.store_name ?? `Site ${s.site_code}`}</span><span className="ml-1.5 text-[10.5px] text-muted-foreground">#{s.site_code}</span>{s.vintage === "NEW STORE" && <span className="ml-1.5 rounded bg-secondary px-1 text-[10px] font-semibold" title={T.nonLfl}>Non-LFL</span>}</td>
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
              <span data-testid="league-count">{p.returned} of {p.stores_total} stores · {v.note}{v.floor && floor > 0 ? ` · stores under ₹${floor} Cr revenue left out` : ""} · growth over {monthLabel(p.growth_basis.from_month)} to {monthLabel(p.growth_basis.to_month)}, LY's same months · stores with no comparable LY come last</span>
              <span data-testid="league-reconciles" className={cn("inline-flex items-center gap-1", p.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}><CheckCircle2 className="h-3 w-3" />{v.floor && floor > 0 ? "ranking of the stores above the floor" : p.reconciles ? `all stores add up to ${cr(p.parent.contribution)} 4-Wall EBITDA` : "does not add up"}</span>
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
    <Panel testId="quadrant-panel" eyebrow="Real · verified" title="Y-o-Y Growth × 4-Wall EBITDA margin: strong, scale, mature, turnaround">
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
              <div className="border-b px-4 py-2 text-[12px]"><span className="font-semibold">Books vs Material Cost table, revenue ex-GST.</span> {d.sales_tieout.tied.toLocaleString("en-IN")} of {d.sales_tieout.site_months.toLocaleString("en-IN")} store-months agree within ₹{Number(d.tolerance_rupees).toLocaleString("en-IN")}.</div>
              <table className="w-full text-[12px]"><thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-4 py-1.5 font-semibold">Month</th><th className="px-3 py-1.5 text-right font-semibold">Tied</th><th className="px-3 py-1.5 text-right font-semibold">Gap ₹ Cr</th></tr></thead>
                <tbody>{d.sales_tieout.months.map((m) => <tr key={m.month} className="border-b last:border-0"><td className="px-4 py-1">{monthLabel(m.month)}</td><td className="num-mono px-3 py-1 text-right">{m.tied}/{m.site_months}</td><td className={cn("num-mono px-3 py-1 text-right", Number(m.difference) !== 0 && "text-muted-foreground")}>{gap(m.difference)}</td></tr>)}</tbody></table>
            </div>
            <div data-testid="recon-excluded">
              <div className="border-b px-4 py-2 text-[12px]"><span className="font-semibold">{d.excluded_unmapped.label}: {d.excluded_unmapped.count} ledgers in this period</span> ({d.excluded_unmapped.run_ledgers} across the run; net {cr(d.excluded_unmapped.net)} in the period). Neither the finance nor the management mapping has a group for them, so none is in any total (mostly intercompany charges). {d.excluded_unmapped.inventory_flow_ledgers ? `${d.excluded_unmapped.inventory_flow_ledgers} stock-transfer and purchase ledgers (net ${cr(d.excluded_unmapped.inventory_flow_net)}) are excluded by rule: they reach the P&L through Material Cost.` : ""}</div>
              <table className="w-full text-[12px]"><tbody>{d.excluded_unmapped.ledgers.slice(0, 12).map((l) => <tr key={l.glcode} className="border-b last:border-0"><td className="px-4 py-1">{l.ledger_name}</td><td className={cn("num-mono px-3 py-1 text-right", tone(l.net))}>{cr(l.net)}</td></tr>)}</tbody></table>
              <div className="px-4 py-1.5 text-[11px] text-muted-foreground">Finance needs to classify each one before it can enter the P&L. None is assigned automatically.</div>
            </div>
            <div data-testid="recon-missing">
              <div className="border-b px-4 py-2 text-[12px]"><span className="font-semibold">{d.sites_without_books_sales.count} sites have sales in the Material Cost table but none in the books</span> ({cr(d.sites_without_books_sales.sales_ex_gst)} ex-GST). They are not stores in the league and, being virtual or warehouse sites, are left out of Material Cost (the MIS rule).</div>
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
      <span className="font-semibold">Material Cost watch.</span> Material Cost was {high.map((r) => `${r.p.toFixed(0)}% of revenue in ${monthLabel(r.month)}`).join(", ")} against a typical {base.toFixed(0)}%. The cause is not known (cost adjustments, stock corrections or timing): confirm with Finance before reading margin trends.
    </div>
  );
}

type TabId = "overview" | "pivot" | "comparison" | "stores" | "heatmap" | "expense-exceptions" | "revenue-exceptions" | "peers" | "quality";
const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "pivot", label: "P&L Pivot" },
  { id: "comparison", label: "MTD / QTD / YTD" },
  { id: "stores", label: "Store Review" },
  { id: "heatmap", label: "Heat Map" },
  { id: "expense-exceptions", label: "Expense Exceptions" },
  { id: "revenue-exceptions", label: "Revenue Exceptions" },
  { id: "peers", label: "Peer Comparison" },
  { id: "quality", label: "Unmapped / Data Quality" },
];

/** The few exceptions a reviewer should open first, on the Overview. */
function NeedsAttention({ q, onStore, onTab }: { q: PnlQuery; onStore: (site: string, group?: string | null) => void; onTab: (t: TabId) => void }) {
  const ex = usePnlExpenseExceptions(q);
  const rx = usePnlRevenueExceptions(q);
  return (
    <Panel testId="attention-panel" eyebrow="Real · verified" title="Needs attention: the exceptions to open first"
      right={<div className="flex gap-2 text-[11.5px]"><button className="press rounded border px-2 py-1 font-medium hover:bg-muted" onClick={() => onTab("expense-exceptions")} data-testid="attention-all-expense">All expense exceptions</button><button className="press rounded border px-2 py-1 font-medium hover:bg-muted" onClick={() => onTab("revenue-exceptions")} data-testid="attention-all-revenue">All revenue exceptions</button></div>}>
      <div className="grid grid-cols-2 divide-x @max-[1000px]:grid-cols-1 @max-[1000px]:divide-x-0 @max-[1000px]:divide-y">
        <div data-testid="attention-expense">
          <div className="border-b px-4 py-1.5 text-[11.5px] text-muted-foreground">Expenses{ex.data ? `: ${ex.data.total} flagged for ${ex.data.month ? monthLabel(ex.data.month) : DASH} (${ex.data.by_severity.Critical ?? 0} critical, ${ex.data.by_severity.High ?? 0} high)` : ""}</div>
          <LiveBoundary query={ex} skeleton={<Skeleton className="m-4 h-[120px]" />}>
            {(d) => (
              <ul>
                {d.exceptions.slice(0, 5).map((e) => (
                  <li key={`${e.site_code}-${e.group}`} data-testid={`attn-e-${e.site_code}-${e.group}`} onClick={() => onStore(e.site_code, e.group)} className="cursor-pointer border-b px-4 py-1.5 text-[12px] last:border-0 hover:bg-muted/50">
                    <span className={cn("mr-2 rounded px-1.5 py-0.5 text-[10.5px] font-bold", SEVERITY_STYLE[e.severity])}>{e.severity}</span>
                    <span className="font-medium">{e.store_name ?? `Site ${e.site_code}`}</span> · {e.label} {lakh(e.current)} vs {lakh(e.expected)}
                    <div className="text-[11px] text-muted-foreground">{e.flags.map((f) => FLAG_LABEL[f] ?? f).join(", ")}</div>
                  </li>
                ))}
                {d.exceptions.length === 0 && <li className="px-4 py-4 text-muted-foreground">No expense exception.</li>}
              </ul>
            )}
          </LiveBoundary>
        </div>
        <div data-testid="attention-revenue">
          <div className="border-b px-4 py-1.5 text-[11.5px] text-muted-foreground">Revenue{rx.data ? `: ${rx.data.total} flagged for ${rx.data.month ? monthLabel(rx.data.month) : DASH} (${rx.data.by_severity.Critical ?? 0} critical, ${rx.data.by_severity.High ?? 0} high)` : ""}</div>
          <LiveBoundary query={rx} skeleton={<Skeleton className="m-4 h-[120px]" />}>
            {(d) => (
              <ul>
                {d.exceptions.slice(0, 5).map((e) => (
                  <li key={e.site_code} data-testid={`attn-r-${e.site_code}`} onClick={() => onStore(e.site_code)} className="cursor-pointer border-b px-4 py-1.5 text-[12px] last:border-0 hover:bg-muted/50">
                    <span className={cn("mr-2 rounded px-1.5 py-0.5 text-[10.5px] font-bold", SEVERITY_STYLE[e.severity])}>{e.severity}</span>
                    <span className="font-medium">{e.store_name ?? `Site ${e.site_code}`}</span> · {e.flags.map((f) => FLAG_LABEL[f] ?? f).join(", ")}
                    <div className="text-[11px] text-muted-foreground">{e.why}</div>
                  </li>
                ))}
                {d.exceptions.length === 0 && <li className="px-4 py-4 text-muted-foreground">No revenue exception.</li>}
              </ul>
            )}
          </LiveBoundary>
        </div>
      </div>
    </Panel>
  );
}

export function PnlRoom() {
  const run = usePnlRun();
  // coming back from the voucher drill restores the store, finance group and period it left from (absent on a normal visit)
  const back = useRouterState({ select: (s) => s.location.search as Record<string, unknown> });
  const [q, setQ0] = useState<PnlQuery>(() => ({
    basis: back.pb === "posted" ? "posted" : "all",
    ...(typeof back.pf === "string" && /^\d{4}-\d{2}$/.test(back.pf) ? { from_month: back.pf } : {}),
    ...(typeof back.pe === "string" && /^\d{4}-\d{2}$/.test(back.pe) ? { to_month: back.pe } : {}),
  }));
  const [tab, setTab] = useState<TabId>("overview");
  const [site, setSite0] = useState<string | null>(() => (back.ps !== undefined && /^\d{1,9}$/.test(String(back.ps)) ? String(back.ps) : null));
  const [group, setGroup] = useState<string | null>(() => (back.ps !== undefined && typeof back.pg === "string" && back.pg.length < 80 ? back.pg : null));
  const setQ = (f: (p: PnlQuery) => PnlQuery) => setQ0((p) => f(p));
  // the default window is year to date through the last COMPLETE month (a partial month stays selectable); a drill that came back with its own period keeps it
  const asOfRun = run.data?.as_of_date;
  const defaulted = useRef(false);
  useEffect(() => {
    if (!asOfRun || defaulted.current) return;
    defaulted.current = true;
    setQ0((p) => (p.to_month || p.from_month ? p : { ...p, to_month: lastCompleteMonthOf(asOfRun) }));
  }, [asOfRun]);
  const pickStore = (s: string | null, g: string | null = null) => {
    setSite0(s);
    setGroup(g);
  };
  const summary = usePnlSummary(q);
  const trend = usePnlTrend(q);
  const filtered = !!(q.region || q.cluster || q.state || q.vintage);
  const storePanel = site && tab !== "peers" ? (
    <div className="px-3 pb-3"><StorePanel key={`${site}|${group ?? ""}`} site={site} q={q} onClose={() => pickStore(null)} initialGroup={group} /></div>
  ) : null;
  return (
    <div data-testid="pnl-room" className="@container flex min-w-0 flex-1 flex-col overflow-y-auto bg-background">
      <WorkspaceHeader
        eyebrow="Performance"
        title="Profitability"
        subtitle="Revenue from operations and Store Expenses from the books; Material Cost from the COGS table. Books basis, before management adjustments; see Management P&L. AOP is not available."
        right={run.data ? <DataStateBadge state={run.data.data_state} run={run.data.run_id} asOf={run.data.as_of_date} /> : undefined}
      />
      {run.isError ? (
        <NotAvailable testId="pnl-unavailable" title="No verified P&L run is available" reason="The P&L API did not return a verified run. Nothing is shown rather than a demo figure." />
      ) : (
        <>
          <Controls asOf={run.data?.as_of_date ?? "2026-10-01"} q={q} setQ={setQ} />
          <Strip q={q} filtered={filtered} />
          <div role="tablist" aria-label="Profitability review" data-testid="pnl-tabs" className="flex flex-wrap gap-0.5 border-b bg-card px-3 pt-1.5">
            {TABS.map((t) => (
              <button key={t.id} role="tab" data-testid={`tab-${t.id}`} aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                className={cn("press -mb-px rounded-t border border-b-0 px-3 py-1.5 text-[12.5px] font-semibold", tab === t.id ? "border-border bg-background text-foreground" : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground")}>
                {t.label}
              </button>
            ))}
          </div>
          {tab === "overview" && (
            <>
              <div className="grid grid-cols-2 gap-3 p-3 @max-[1000px]:grid-cols-1">
                <Panel testId="bridge-panel" eyebrow="Real · verified" title="From revenue to Corporate EBITDA — Books" right={summary.data && <span className="num text-[11.5px] text-muted-foreground">{monthLabel(summary.data.scope.from_month)} to {monthLabel(summary.data.scope.to_month)} · {summary.data.scope.basis_label}</span>}>
                  <LiveBoundary query={summary} skeleton={<Skeleton className="m-4 h-[300px]" />}>{(d) => <PnlWaterfall t={d.totals as PnlMoney} store={filtered} />}</LiveBoundary>
                  {summary.data?.reconciliation && (
                    <div data-testid="bridge-reconciles" className={cn("border-t px-4 py-1.5 text-[11.5px]", summary.data.reconciliation.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}>
                      <CheckCircle2 className="mr-1 inline h-3 w-3" />
                      {summary.data.reconciliation.reconciles ? `Company Store EBITDA = stores (${cr(summary.data.reconciliation.stores.contribution)}) + virtual and other non-store sites (${cr(summary.data.reconciliation.non_store.contribution)})` : "Company does not equal stores + non-store"}
                    </div>
                  )}
                </Panel>
                <Panel testId="trend-panel" eyebrow="Real · verified" title="Month by month, against LY">
                  <LiveBoundary query={trend} skeleton={<Skeleton className="m-4 h-[300px]" />}>{(d) => <><PnlTrendChart months={d.months} /><CogsWatch months={d.months} /></>}</LiveBoundary>
                </Panel>
              </div>
              <div className="px-3 pb-3"><NeedsAttention q={q} onStore={pickStore} onTab={setTab} /></div>
              <div className="px-3 pb-3"><Quadrant q={q} onPick={(s) => pickStore(s)} picked={site} /></div>
              <div className="px-3 pb-3">
                <Panel testId="lines-panel" eyebrow="Real · verified" title="P&L lines (management groups)">
                  <div className="max-h-[470px] overflow-y-auto">
                    <LiveBoundary query={summary} skeleton={<Skeleton className="m-4 h-[260px]" />}>{(d) => <Lines lines={d.lines} revenue={d.totals.revenue} />}</LiveBoundary>
                  </div>
                </Panel>
              </div>
              {storePanel}
              <div className="px-3 pb-6">
                <Panel testId="unavailable-panel" eyebrow="Not available" title="What the sources cannot support yet">
                  <div className="divide-y">
                    <NotAvailable testId="unavailable-budget" title="AOP" reason="No FY26-27 AOP exists in the sources (the FY25-26 plan ended in March 2026). AOP and variance to AOP are left blank; nothing is estimated." />
                    <NotAvailable testId="unavailable-allocation" title="Management adjustments and DC / HO apportionment" reason="This page is the books basis. The 1% shrinkage provision, gratuity, audit and CSR provisions, journals and the Citykart Ventures cost are on the Management P&L page, which also apportions DC and HO cost to stores at one blended rate." />
                    <NotAvailable testId="unavailable-hierarchy" title="Area and zone" reason="The site master carries region, cluster and state only. No area or zone is shown or invented." />
                  </div>
                </Panel>
              </div>
            </>
          )}
          {tab === "pivot" && <PnlPivotTab q={q} />}
          {tab === "comparison" && <PnlComparisonTab q={q} />}
          {tab === "stores" && (
            <>
              <div className="p-3"><League q={q} onPick={(s) => pickStore(s)} picked={site} /></div>
              {storePanel}
            </>
          )}
          {tab === "heatmap" && (
            <>
              <HeatMapTab q={q} onPick={(s) => pickStore(s)} picked={site} />
              {storePanel}
            </>
          )}
          {tab === "expense-exceptions" && (
            <>
              <ExpenseExceptionsTab q={q} onOpen={(s, g) => pickStore(s, g)} picked={site} />
              {storePanel}
            </>
          )}
          {tab === "revenue-exceptions" && (
            <>
              <RevenueExceptionsTab q={q} onOpen={(s) => pickStore(s)} picked={site} />
              {storePanel}
            </>
          )}
          {tab === "peers" && <PeersTab q={q} site={site} setSite={(s) => pickStore(s)} />}
          {tab === "quality" && <QualityTab q={q} reconciliation={<Reconciliation q={q} />} />}
        </>
      )}
    </div>
  );
}
