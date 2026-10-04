import { useState } from "react";
import { ArrowRight, Landmark } from "lucide-react";
import { useCashRun, useCashSummary, useTillStores } from "@/api/cashLiveHooks";
import { fmtRupees, num, toCr } from "@/api/creditorsLive";
import { useCfo } from "@/context/CfoContext";
import { DASH, fmtCr, fmtDate, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { BankLedger, BankReview, CashSummary, CashTill, CreditorObligations } from "@/types/cashLive";
import { Skeleton } from "../common";
import { DataStateBadge, LiveBoundary, NotAvailable } from "../creditors/parts";
import { Panel, WorkspaceHeader } from "../panels";

/**
 * Liquidity & Working Capital Control, on REAL data (the verified cash mart and the creditors mart).
 *
 * Three kinds of figure, never blended:
 *   - Store Till Cash: cash held in stores. It EXCLUDES bank balances and is never called a cash position.
 *   - Creditor obligations: read from the creditors mart (the same figures as /creditors).
 *   - Bank ledger-book position: a Finance review card, PROVISIONAL and NOT BANK-RECONCILED, kept apart and never added to anything.
 * What the sources cannot support is listed as unavailable with its reason. There is no forecast and no projection.
 */

const cr = (m: string | null | undefined) => fmtCr(toCr(m));
const signedClass = (m: string) => (num(m) < 0 ? "tone-bad" : "");

function Cell({ label, value, exact, sub, testId, tone }: { label: string; value: string; exact?: string; sub?: string; testId: string; tone?: string }) {
  return (
    <div className="flex min-w-0 flex-col items-start gap-0.5 px-4 py-3" data-testid={testId}>
      <span className="eyebrow">{label}</span>
      <span data-testid={`${testId}-value`} data-exact={exact} className={cn("num-mono whitespace-nowrap text-[22px] font-semibold leading-tight", tone)}>
        {value}
      </span>
      {sub && <span className="num max-w-full truncate text-[11.5px] text-muted-foreground">{sub}</span>}
    </div>
  );
}

function Strip({ s }: { s: CashSummary }) {
  const c = s.creditors;
  const credAvail = c.available;
  return (
    <section aria-label="Verified figures" data-testid="cash-strip" className="border-b bg-card">
      <div className="grid grid-cols-4 divide-x @max-[900px]:grid-cols-2 @max-[900px]:divide-y">
        <Cell testId="strip-till" label="Store Till Cash" value={cr(s.till.store_till_cash)} exact={s.till.store_till_cash} sub={`excludes bank balances · ${s.till.stores} stores · ${fmtDate(s.till_balance_date)}`} />
        <Cell testId="strip-credit" label="Credit Outstanding" value={credAvail ? cr(c.credit_outstanding) : DASH} exact={credAvail ? c.credit_outstanding : undefined} sub={credAvail ? `creditors · ${c.credit_items.toLocaleString("en-IN")} items · ${c.credit_vendors.toLocaleString("en-IN")} vendors` : c.reason} />
        <Cell testId="strip-pastdue" label="Past Due Creditors" value={credAvail ? cr(c.past_due_credit) : DASH} exact={credAvail ? c.past_due_credit : undefined} sub={credAvail ? `${fmtPct((num(c.past_due_credit) / (num(c.credit_outstanding) || 1)) * 100)} of credit outstanding` : undefined} />
        <Cell testId="strip-debit" label="Creditor Debit Balances" value={credAvail ? cr(c.creditor_debit_balance) : DASH} exact={credAvail ? c.creditor_debit_balance : undefined} sub={credAvail ? "Dr in creditor ledgers · not netted" : undefined} />
      </div>
      <div data-testid="strip-note" className="border-t bg-[oklch(0.985_0.006_265)] px-4 py-1.5 text-[11.5px] text-muted-foreground">
        <span className="font-semibold text-foreground">Bank position not yet included.</span> These four figures are not a cash position and are not added together: Store Till Cash is cash in store tills only.
        {credAvail && <> Creditors run {c.creditors_run_id} as of {fmtDate(c.as_of_date)}.</>}
      </div>
    </section>
  );
}

function TillPanel({ till }: { till: CashTill }) {
  const [limit, setLimit] = useState(15);
  const q = useTillStores(limit, "balance");
  const stat = (label: string, value: string, exact?: string) => (
    <div className="px-4 py-2.5">
      <div className="eyebrow">{label}</div>
      <div data-exact={exact} className="num-mono text-[16px] font-semibold">{value}</div>
    </div>
  );
  return (
    <Panel testId="till-panel" eyebrow="Real · verified" title="Store Till Cash: cash held in store tills (excludes bank balances)">
      <div className="grid grid-cols-5 divide-x border-b @max-[900px]:grid-cols-3 @max-[900px]:divide-y">
        {stat("Month to date in", cr(till.mtd_debit), till.mtd_debit)}
        {stat("Month to date out", cr(till.mtd_credit), till.mtd_credit)}
        {stat("Year to date in", cr(till.fytd_debit), till.fytd_debit)}
        {stat("Stores holding cash", `${till.stores_with_cash} of ${till.stores}`)}
        {stat("Stores below zero", String(till.stores_negative))}
      </div>
      <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[220px]" />}>
        {(p) => (
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]" data-testid="till-table">
              <thead>
                <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-2 font-semibold">Store</th>
                  <th className="px-2 py-2 text-right font-semibold">Till cash</th>
                  <th className="px-2 py-2 text-right font-semibold">Month to date in / out</th>
                  <th className="px-4 py-2 text-right font-semibold">Last activity</th>
                </tr>
              </thead>
              <tbody>
                {p.stores.map((r) => (
                  <tr key={r.site_code} className="border-b last:border-b-0">
                    <td className="px-4 py-1.5"><span className="font-medium text-foreground">{r.store_name ?? `Site ${r.site_code}`}</span> <span className="text-muted-foreground">· {r.site_code}</span></td>
                    <td data-exact={r.cumulative_balance} className={cn("num px-2 py-1.5 text-right font-semibold", signedClass(r.cumulative_balance))} title={fmtRupees(r.cumulative_balance)}>{cr(r.cumulative_balance)}</td>
                    <td className="num px-2 py-1.5 text-right text-muted-foreground">{cr(r.mtd_debit)} / {cr(r.mtd_credit)}</td>
                    <td className="num px-4 py-1.5 text-right text-muted-foreground">{r.last_activity_date ? fmtDate(r.last_activity_date) : DASH}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center justify-between border-t px-4 py-2 text-[11px] text-muted-foreground">
              <span>{p.stores.length} of {till.stores} stores, highest till cash first</span>
              {p.stores.length < till.stores && limit < 500 && (
                <button data-testid="till-more" onClick={() => setLimit((l) => Math.min(500, l + 50))} className="press rounded px-2 py-0.5 font-semibold text-primary hover:bg-muted">Show more</button>
              )}
            </div>
          </div>
        )}
      </LiveBoundary>
    </Panel>
  );
}

function CreditorsPanel({ c }: { c: CreditorObligations }) {
  const { enterCreditors } = useCfo();
  if (!c.available) {
    return (
      <Panel testId="creditors-panel" eyebrow="Real · verified" title="Creditor obligations">
        <NotAvailable title="Creditor figures are not available" reason={c.reason} />
      </Panel>
    );
  }
  const total = num(c.credit_outstanding) || 1;
  const row = (id: string, label: string, v: string, color: string, note: string) => (
    <li key={id} className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,3fr)_110px_70px] items-center gap-x-3 border-b px-4 py-2.5 last:border-b-0" data-testid={`obligation-${id}`}>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 text-[13px] font-semibold"><i className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: color }} />{label}</span>
        <span className="block truncate text-[11px] text-muted-foreground">{note}</span>
      </span>
      <span className="h-3 overflow-hidden rounded-sm bg-muted/60" aria-hidden><span className="block h-full rounded-sm" style={{ width: `${(num(v) / total) * 100}%`, background: color }} /></span>
      <span data-exact={v} className="num text-right text-[14px] font-semibold">{cr(v)}</span>
      <span className="num text-right text-[12px] text-muted-foreground">{fmtPct((num(v) / total) * 100)}</span>
    </li>
  );
  return (
    <Panel
      testId="creditors-panel"
      eyebrow="Real · verified (from the creditors mart)"
      title="Creditor obligations by Due Status"
      right={
        <button data-testid="open-creditors" onClick={() => enterCreditors()} className="press inline-flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-[12px] font-semibold text-primary-foreground hover:bg-primary/90">
          Open Creditors Control <ArrowRight className="h-3.5 w-3.5" />
        </button>
      }
    >
      <ul>
        {row("past_due", "Past due / due today", c.past_due_credit, "oklch(0.55 0.19 25)", "stored due date reached")}
        {row("not_yet_due", "Not yet due", c.not_yet_due_credit, "oklch(0.62 0.1 190)", "stored due date after the as-of date")}
        {row("due_unavailable", "Due date unavailable", c.due_unavailable_credit, "oklch(0.72 0.03 260)", "no due date in the source; never estimated")}
      </ul>
      <div className="border-t px-4 py-2 text-[11px] text-muted-foreground">
        Credit Outstanding {cr(c.credit_outstanding)}. Creditor debit balances {cr(c.creditor_debit_balance)} are separate and not netted. Creditors run {c.creditors_run_id}, as of {fmtDate(c.as_of_date)} ({c.data_state === "live" ? "live" : "verified candidate, not live"}). Same figures as the Creditors page.
      </div>
    </Panel>
  );
}

function BankCard({ b }: { b: BankReview }) {
  const t = b.totals;
  const cell = (id: string, label: string, v: string, hint: string) => (
    <div className="px-4 py-3" data-testid={id}>
      <div className="eyebrow">{label}</div>
      <div data-testid={`${id}-value`} data-exact={v} className={cn("num-mono text-[20px] font-semibold", signedClass(v))}>{cr(v)}</div>
      <div className="text-[11px] text-muted-foreground">{hint}</div>
    </div>
  );
  return (
    <section data-testid="bank-card" className="rounded-md border-2 border-dashed border-[oklch(0.78_0.1_80)] bg-[oklch(0.995_0.012_90)] shadow-elegant">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-dashed border-[oklch(0.78_0.1_80)] px-4 py-2.5">
        <div>
          <div className="eyebrow flex items-center gap-1.5"><Landmark className="h-3.5 w-3.5" /> Finance review</div>
          <h2 className="text-[14px] font-semibold tracking-tight">Bank ledger-book position</h2>
        </div>
        <span data-testid="bank-status" className="rounded-sm bg-[oklch(0.45_0.12_70)] px-2 py-0.5 text-[11px] font-bold tracking-wide text-white">{b.status}</span>
      </div>
      <div className="grid grid-cols-4 divide-x divide-dashed border-b border-dashed border-[oklch(0.78_0.1_80)] @max-[900px]:grid-cols-2 @max-[900px]:divide-y">
        {cell("bank-opening", "Opening balance", t.opening_balance, "1 Apr 2026, ties to the prior-year closing")}
        {cell("bank-posted", "Posted closing", t.posted_closing, b.last_posted_date ? `posted entries to ${fmtDate(b.last_posted_date)}` : "posted entries")}
        {cell("bank-unposted", "Unposted movement", t.unposted_movement, "entries not yet posted, to the register date")}
        {cell("bank-indicative", "Indicative incl. unposted", t.including_unposted, "indicative only; not a bank balance")}
      </div>
      {b.driver && (
        <div data-testid="bank-driver" className="border-b border-dashed border-[oklch(0.78_0.1_80)] px-4 py-2 text-[12.5px]">
          <span className="font-semibold">{b.driver.ledger_name}</span> drives the negative posted balance: <span className="num font-semibold tone-bad">{cr(b.driver.posted_closing)}</span> posted, <span className="num font-semibold">{cr(b.driver.including_unposted)}</span> including unposted.
          Whether this account is expected to run negative (an overdraft) or posting is lagging cannot be told from the books alone.
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-[12.5px]" data-testid="bank-table">
          <thead>
            <tr className="border-b border-dashed text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
              <th className="px-4 py-2 font-semibold">Ledger</th>
              <th className="px-2 py-2 text-right font-semibold">Opening</th>
              <th className="px-2 py-2 text-right font-semibold">Posted closing</th>
              <th className="px-2 py-2 text-right font-semibold">Unposted</th>
              <th className="px-2 py-2 text-right font-semibold">Incl. unposted</th>
              <th className="px-4 py-2 text-right font-semibold">Last posted</th>
            </tr>
          </thead>
          <tbody>
            {b.ledgers.map((l: BankLedger) => (
              <tr key={l.ledger_code} data-testid={`bank-ledger-${l.ledger_code}`} className="border-b border-dashed last:border-b-0">
                <td className="px-4 py-1.5"><span className="font-medium">{l.ledger_name}</span> <span className="text-muted-foreground">· {l.nature}</span></td>
                <td className="num px-2 py-1.5 text-right">{cr(l.opening_balance)}</td>
                <td data-exact={l.posted_closing} className={cn("num px-2 py-1.5 text-right font-semibold", signedClass(l.posted_closing))}>{cr(l.posted_closing)}</td>
                <td className="num px-2 py-1.5 text-right text-muted-foreground">{cr(l.unposted_movement)}</td>
                <td data-exact={l.including_unposted} className={cn("num px-2 py-1.5 text-right", signedClass(l.including_unposted))}>{cr(l.including_unposted)}</td>
                <td className="num px-4 py-1.5 text-right text-muted-foreground">{l.last_posted_date ? fmtDate(l.last_posted_date) : DASH}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div data-testid="bank-note" className="space-y-1 border-t border-dashed border-[oklch(0.78_0.1_80)] px-4 py-2 text-[11px] text-muted-foreground">
        <div><span className="font-semibold text-foreground">Not bank-reconciled.</span> Book figures from the ledgers; no bank statement is available. Not added to Store Till Cash, and no liquidity, headroom or coverage is derived from them.</div>
        <div>
          {b.ledgers_with_movement} of {b.ledgers_total} bank and cash ledgers have entries; {b.ledgers_without_movement} have none. Source: site register as of {b.register_report_date ? fmtDate(b.register_report_date) : DASH}.
          The GL register {b.cross_check.posted_agrees_with_gl_register ? "agrees on every posted figure" : "does NOT agree on the posted figures"}
          {b.cross_check.gl_register_report_date ? ` (as of ${fmtDate(b.cross_check.gl_register_report_date)}, including unposted ${cr(b.cross_check.gl_register_including_unposted)})` : ""}. Every ledger's opening ties to its prior-year closing
          {b.opening_ties_to_prior_year_closing.ledgers_not_tying === 0 ? ` (${b.opening_ties_to_prior_year_closing.ledgers_checked} checked)` : ` EXCEPT ${b.opening_ties_to_prior_year_closing.ledgers_not_tying}`}.
        </div>
      </div>
    </section>
  );
}

function Unavailable({ items }: { items: CashSummary["unavailable"] }) {
  return (
    <Panel testId="unavailable-panel" eyebrow="Not available / not yet verified" title="What this page does not show yet, and why">
      <ul>
        {items.map((u) => (
          <li key={u.id} data-testid={`unavailable-${u.id}`} className="border-b px-4 py-2 last:border-b-0">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[13px] font-semibold">{u.label}</span>
              <span className="num-mono text-[13px] text-muted-foreground">{DASH}</span>
            </div>
            <div className="text-[11.5px] text-muted-foreground">{u.reason}</div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function CashRoom() {
  const run = useCashRun();
  const q = useCashSummary();
  return (
    <div data-testid="cash-room" className="@container">
      <WorkspaceHeader
        eyebrow="Liquidity"
        title="Liquidity & Working Capital Control"
        subtitle="What is in the tills, what is owed to creditors, and what is not yet known. Bank-reconciled cash and a forecast are not available from the current sources."
        right={run.data ? <DataStateBadge state={run.data.data_state} run={run.data.run_id} asOf={run.data.as_of_date} /> : undefined}
      />
      <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[420px]" />}>
        {(s) => (
          <>
            <Strip s={s} />
            <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-4 @max-[1100px]:grid-cols-1">
                <TillPanel till={s.till} />
                <CreditorsPanel c={s.creditors} />
              </div>
              <BankCard b={s.bank_review} />
              <Unavailable items={s.unavailable} />
            </div>
          </>
        )}
      </LiveBoundary>
    </div>
  );
}
