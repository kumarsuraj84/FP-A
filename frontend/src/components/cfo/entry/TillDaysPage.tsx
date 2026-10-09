import { useRouterState } from "@tanstack/react-router";
import { CheckCircle2, XCircle } from "lucide-react";
import { useTillDays, useTillStoresDrill } from "@/api/entryLiveHooks";
import { fmtRupees, num } from "@/api/creditorsLive";
import { DASH, fmtDate } from "@/lib/format";
import { TILL_LEDGER, ledgerListHref, parseTillSearch, tillHref } from "@/lib/entryLinks";
import { cn } from "@/lib/utils";
import type { TillDay } from "@/types/entryLive";
import { Skeleton } from "../common";
import { LiveBoundary, NotAvailable } from "../creditors/parts";
import { Panel, WorkspaceHeader } from "../panels";
import { AppLink, Crumbs, EntryRunBadge, useHere } from "./parts";

/**
 * Store Till Cash drill: stores → days → vouchers. Each level shows its parent figure, the sum of its rows and whether they agree.
 * The till is the Cash Drawer ledger. The day list ends at the store-day: opening balance has no vouchers, a day opens its vouchers.
 */

const money = (m: string) => (num(m) === 0 ? DASH : fmtRupees(m));
const isOpening = (d: TillDay) => d.day.endsWith("-03-31"); // the synthetic day that carries the opening balance in

function Reconciles({ ok, parent, children, label }: { ok: boolean; parent: string; children: string; label: string }) {
  return (
    <div data-testid="till-reconciles" data-ok={String(ok)} className={cn("flex flex-wrap items-center gap-x-3 gap-y-0.5 border-t px-4 py-2 text-[11.5px]", ok ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}>
      {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
      <span className="font-semibold">{ok ? `${label}: rows add up to the figure above` : `${label}: rows do NOT add up to the figure above`}</span>
      <span className="num text-muted-foreground">parent {fmtRupees(parent)} · rows {fmtRupees(children)}</span>
    </div>
  );
}

function Stores({ trail }: { trail: ReturnType<typeof parseTillSearch>["trail"] }) {
  const q = useTillStoresDrill();
  const { next } = useHere(trail, "Store till cash");
  return (
    <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[320px]" />}>
      {(d) => (
        <div className="p-4">
          <Panel testId="till-stores-panel" eyebrow="Store Till Cash" title={`${d.parent.stores} stores · ${fmtRupees(d.parent.store_till_cash)} (excludes bank balances)`}>
            <div className="max-h-[560px] overflow-y-auto">
              <table className="w-full text-[12.5px]" data-testid="till-stores-table">
                <thead>
                  <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                    <th className="px-4 py-2 font-semibold">Site</th>
                    <th className="px-2 py-2 text-right font-semibold">Active days</th>
                    <th className="px-2 py-2 text-right font-semibold">Total in</th>
                    <th className="px-2 py-2 text-right font-semibold">Total out</th>
                    <th className="px-4 py-2 text-right font-semibold">Till cash</th>
                  </tr>
                </thead>
                <tbody>
                  {d.stores.map((s) => (
                    <tr key={s.site_code} className="border-b hover:bg-[oklch(0.97_0.012_265)]">
                      <td className="px-4 py-1.5"><AppLink href={tillHref(s.site_code, next)} testId={`till-store-${s.site_code}`} className="num font-semibold text-primary underline-offset-2 hover:underline">Site {s.site_code}</AppLink></td>
                      <td className="num px-2 py-1.5 text-right text-muted-foreground">{s.active_days}</td>
                      <td className="num px-2 py-1.5 text-right">{money(s.total_debit)}</td>
                      <td className="num px-2 py-1.5 text-right">{money(s.total_credit)}</td>
                      <td data-exact={s.balance} className={cn("num px-4 py-1.5 text-right font-semibold", num(s.balance) < 0 && "tone-bad")}>{fmtRupees(s.balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Reconciles ok={d.reconciles} parent={d.parent.store_till_cash} children={d.children_sum.store_till_cash} label="Stores" />
          </Panel>
        </div>
      )}
    </LiveBoundary>
  );
}

function Days({ site, name, trail }: { site: string; name?: string; trail: ReturnType<typeof parseTillSearch>["trail"] }) {
  const q = useTillDays(site);
  const label = `Till · ${name ?? `site ${site}`}`;
  const { next } = useHere(trail, label);
  return (
    <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[320px]" />}>
      {(d) => {
        const days = [...d.days].reverse();
        return (
          <div className="p-4">
            <Panel testId="till-days-panel" eyebrow="Store till days" title={`${days.length} active day${days.length === 1 ? "" : "s"} · till cash ${fmtRupees(d.parent.balance)} on ${fmtDate(d.balance_date)}`}>
              {days.length === 0 ? (
                <NotAvailable title="No till movement" reason="This store has no Cash Drawer movement and no opening balance in the current financial year." />
              ) : (
                <table className="w-full text-[12.5px]" data-testid="till-days-table">
                  <thead>
                    <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      <th className="px-4 py-2 font-semibold">Day</th>
                      <th className="px-2 py-2 text-right font-semibold">In (debit)</th>
                      <th className="px-2 py-2 text-right font-semibold">Out (credit)</th>
                      <th className="px-2 py-2 text-right font-semibold">Till cash after the day</th>
                      <th className="px-4 py-2 text-right font-semibold">Vouchers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {days.map((r) => (
                      <tr key={r.day} data-testid={`till-day-${r.day}`} className="border-b hover:bg-[oklch(0.97_0.012_265)]">
                        <td className="num px-4 py-1.5">{fmtDate(r.day)}{isOpening(r) && <span className="ml-2 text-[10.5px] text-muted-foreground">opening balance</span>}</td>
                        <td data-exact={r.debit} className="num px-2 py-1.5 text-right">{money(r.debit)}</td>
                        <td data-exact={r.credit} className="num px-2 py-1.5 text-right">{money(r.credit)}</td>
                        <td data-exact={r.cumulative_balance} className={cn("num px-2 py-1.5 text-right font-semibold", num(r.cumulative_balance) < 0 && "tone-bad")}>{fmtRupees(r.cumulative_balance)}</td>
                        <td className="px-4 py-1.5 text-right">
                          {isOpening(r) ? (
                            <span className="text-[11.5px] text-muted-foreground" title="The opening balance is one figure carried in from last year; it has no vouchers in this drill">no vouchers</span>
                          ) : (
                            <AppLink
                              href={ledgerListHref({ site, glcode: TILL_LEDGER, from_date: r.day, to_date: r.day, title: `Cash Drawer · ${name ?? `site ${site}`} · ${fmtDate(r.day)}` }, next)}
                              testId={`till-day-open-${r.day}`}
                              className="press rounded border px-2 py-0.5 text-[11.5px] font-semibold text-primary hover:bg-muted"
                            >
                              Open vouchers
                            </AppLink>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <Reconciles ok={d.reconciles} parent={d.parent.balance} children={d.children_sum.balance} label="Days" />
              <div className="border-t px-4 py-2 text-[11px] text-muted-foreground">{d.note}</div>
            </Panel>
          </div>
        );
      }}
    </LiveBoundary>
  );
}

export function TillDaysPage() {
  const raw = useRouterState({ select: (s) => s.location.search as Record<string, unknown> });
  const p = parseTillSearch(raw);
  return (
    <div data-testid="entry-till-page" className="@container">
      <Crumbs trail={p.trail} current={p.site ? `Till · ${p.name ?? `site ${p.site}`}` : "Store till cash"} />
      <WorkspaceHeader eyebrow="Store Till Cash drill" title={p.site ? (p.name ? `${p.name} · site ${p.site}` : `Site ${p.site}`) : "Store Till Cash by store"} subtitle="Cash Drawer ledger. Excludes bank balances." right={<EntryRunBadge />} />
      {p.site ? <Days site={p.site} name={p.name} trail={p.trail} /> : <Stores trail={p.trail} />}
    </div>
  );
}
