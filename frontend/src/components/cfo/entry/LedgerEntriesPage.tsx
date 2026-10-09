import { useRouterState } from "@tanstack/react-router";
import { CheckCircle2, ChevronLeft, ChevronRight } from "lucide-react";
import { useLedgerEntries } from "@/api/entryLiveHooks";
import { fmtRupees, num } from "@/api/creditorsLive";
import { DASH, fmtDate } from "@/lib/format";
import { entryHref, ledgerListHref, parseListSearch, type ListParams } from "@/lib/entryLinks";
import { cn } from "@/lib/utils";
import type { LedgerEntriesPage as Page } from "@/types/entryLive";
import { Skeleton } from "../common";
import { LiveBoundary, NotAvailable } from "../creditors/parts";
import { Panel, WorkspaceHeader } from "../panels";
import { AppLink, Crumbs, EntryRunBadge, StatusChip, useHere } from "./parts";

/**
 * The vouchers behind one ledger at one store in a period (P&L ledger line) or on one day (store till day).
 * One row per voucher; amounts are only the lines on this ledger, so the rows add up to the figure the user clicked.
 */

const PAGE = 100;
const money = (m: string) => (num(m) === 0 ? DASH : fmtRupees(m));
const monthName = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });

function scopeText(s: Page["scope"]): string {
  const bits: string[] = [];
  if (s.site != null) bits.push(`site ${s.site}`);
  if (s.from_date && s.from_date === s.to_date) bits.push(fmtDate(s.from_date));
  else if (s.from_date || s.to_date) bits.push(`${s.from_date ? fmtDate(s.from_date) : "start"} to ${s.to_date ? fmtDate(s.to_date) : "now"}`);
  if (s.from_month || s.to_month) bits.push(s.from_month === s.to_month && s.from_month ? monthName(s.from_month) : `${s.from_month ? monthName(s.from_month) : "start"} to ${s.to_month ? monthName(s.to_month) : "now"}`);
  bits.push(s.basis === "posted" ? "posted entries only" : "all entries, including unposted");
  return bits.join(" · ");
}

function Strip({ d }: { d: Page }) {
  const cell = (id: string, label: string, v: string, exact?: string, sub?: string) => (
    <div className="px-4 py-3" data-testid={id}>
      <div className="eyebrow">{label}</div>
      <div data-testid={`${id}-value`} data-exact={exact} className={cn("num-mono text-[18px] font-semibold", exact && num(exact) < 0 && "tone-bad")}>{v}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
  return (
    <section className="grid grid-cols-5 divide-x border-b bg-card @max-[900px]:grid-cols-2 @max-[900px]:divide-y" data-testid="list-strip">
      {cell("list-vouchers", "Vouchers", d.total.entries.toLocaleString("en-IN"), String(d.total.entries), `${d.total.lines.toLocaleString("en-IN")} line${d.total.lines === 1 ? "" : "s"} on this ledger`)}
      {cell("list-debit", "Debit", fmtRupees(d.total.debit), d.total.debit)}
      {cell("list-credit", "Credit", fmtRupees(d.total.credit), d.total.credit)}
      {cell("list-net", "Net (credit − debit)", fmtRupees(d.total.net), d.total.net, "the P&L sign: income positive")}
      <div className="px-4 py-3" data-testid="list-reconciles">
        <div className="eyebrow">Reconciliation</div>
        {d.reconciles === null ? (
          <div className="text-[12.5px] text-muted-foreground">Showing {d.returned.toLocaleString("en-IN")} of {d.total.entries.toLocaleString("en-IN")}; the totals above are the whole range.</div>
        ) : (
          <div data-ok={String(d.reconciles)} className={cn("flex items-center gap-1 text-[12.5px] font-semibold", d.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}>
            <CheckCircle2 className="h-3.5 w-3.5" /> {d.reconciles ? "Vouchers add up to the ledger figure" : "Vouchers do NOT add up to the ledger figure"}
          </div>
        )}
      </div>
    </section>
  );
}

function Table({ d, p, next }: { d: Page; p: ListParams; next: ReturnType<typeof useHere>["next"] }) {
  const named = d.named && d.entries.some((e) => e.narration !== undefined);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]" data-testid="list-table">
        <thead>
          <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-2 font-semibold">Date</th>
            <th className="px-2 py-2 font-semibold">Type</th>
            <th className="px-2 py-2 font-semibold">Voucher</th>
            <th className="px-2 py-2 font-semibold">Status</th>
            {named && <th className="px-2 py-2 font-semibold">Narration</th>}
            <th className="px-2 py-2 text-right font-semibold">Lines</th>
            <th className="px-2 py-2 text-right font-semibold">Debit</th>
            <th className="px-2 py-2 text-right font-semibold">Credit</th>
            <th className="px-4 py-2 text-right font-semibold">Net</th>
          </tr>
        </thead>
        <tbody>
          {d.entries.map((e) => (
            <tr key={e.entry_ref} data-testid={`list-row-${e.entry_ref}`} className="border-b hover:bg-[oklch(0.97_0.012_265)]">
              <td className="num px-4 py-1.5">{fmtDate(e.entry_date)}</td>
              <td className="px-2 py-1.5"><span className="font-medium">{e.entry_type_short}</span><span className="block text-[10.5px] text-muted-foreground">{e.entry_type_long}</span></td>
              <td className="px-2 py-1.5">
                <AppLink href={entryHref(e.entry_ref, next)} testId={`open-entry-${e.entry_ref}`} className="num-mono font-semibold text-primary underline-offset-2 hover:underline">{e.entry_ref}</AppLink>
              </td>
              <td className="px-2 py-1.5"><StatusChip status={e.release_status} /></td>
              {named && <td className="max-w-[30ch] truncate px-2 py-1.5 text-muted-foreground" title={e.narration ?? undefined}>{e.narration ?? DASH}</td>}
              <td className="num px-2 py-1.5 text-right text-muted-foreground">{e.lines}</td>
              <td data-exact={e.debit} className="num px-2 py-1.5 text-right">{money(e.debit)}</td>
              <td data-exact={e.credit} className="num px-2 py-1.5 text-right">{money(e.credit)}</td>
              <td data-exact={e.net} className={cn("num px-4 py-1.5 text-right font-semibold", num(e.net) < 0 && "tone-bad")}>{fmtRupees(e.net)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center justify-between border-t px-4 py-2 text-[11.5px] text-muted-foreground" data-testid="list-pager">
        <span>
          {d.entries.length === 0 ? "No vouchers" : `Vouchers ${(p.offset + 1).toLocaleString("en-IN")} to ${(p.offset + d.entries.length).toLocaleString("en-IN")} of ${d.total.entries.toLocaleString("en-IN")}, newest first`}
        </span>
        <span className="flex items-center gap-1">
          {p.offset > 0 && (
            <AppLink href={ledgerListHref({ ...p, offset: Math.max(0, p.offset - PAGE) }, p.trail)} testId="list-prev" className="press inline-flex items-center gap-0.5 rounded border px-2 py-0.5 font-semibold hover:bg-muted">
              <ChevronLeft className="h-3 w-3" /> Newer
            </AppLink>
          )}
          {p.offset + d.entries.length < d.total.entries && (
            <AppLink href={ledgerListHref({ ...p, offset: p.offset + PAGE }, p.trail)} testId="list-next" className="press inline-flex items-center gap-0.5 rounded border px-2 py-0.5 font-semibold hover:bg-muted">
              Older <ChevronRight className="h-3 w-3" />
            </AppLink>
          )}
        </span>
      </div>
    </div>
  );
}

export function LedgerEntriesPage() {
  const raw = useRouterState({ select: (s) => s.location.search as Record<string, unknown> });
  const p = parseListSearch(raw);
  const valid = p.site !== undefined || p.glcode !== undefined;
  const q = useLedgerEntries(valid ? { site: p.site, glcode: p.glcode, from_month: p.from_month, to_month: p.to_month, from_date: p.from_date, to_date: p.to_date, basis: p.basis, limit: PAGE, offset: p.offset } : null);
  const title = p.title ?? q.data?.scope.ledger_name ?? "Vouchers";
  const { next } = useHere(p.trail, title);
  return (
    <div data-testid="entry-list-page" className="@container">
      <Crumbs trail={p.trail} current={`Vouchers · ${title}`} />
      <WorkspaceHeader
        eyebrow="Vouchers behind a ledger"
        title={title}
        subtitle={q.data ? scopeText(q.data.scope) : undefined}
        right={<EntryRunBadge />}
      />
      {!valid ? (
        <NotAvailable testId="entry-list-empty" title="No ledger or store selected" reason="Open this list from a P&L ledger line or a store till day." />
      ) : (
        <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[320px]" />}>
          {(d) => (
            <>
              <Strip d={d} />
              <div className="p-4">
                <Panel testId="list-panel" eyebrow="One row per voucher" title={`${d.total.entries.toLocaleString("en-IN")} voucher${d.total.entries === 1 ? "" : "s"}`}>
                  {d.entries.length === 0 ? <NotAvailable title="No vouchers in this selection" reason="The voucher register has no line on this ledger for the selection. Entries start from the register's coverage date." /> : <Table d={d} p={p} next={next} />}
                </Panel>
              </div>
            </>
          )}
        </LiveBoundary>
      )}
    </div>
  );
}
