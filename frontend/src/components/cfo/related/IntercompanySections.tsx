import { useState } from "react";
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { useRelatedGl, useRelatedIntercompany } from "@/api/relatedLiveHooks";
import { DASH, fmtCr, fmtDate } from "@/lib/format";
import { entryHref } from "@/lib/entryLinks";
import { cn } from "@/lib/utils";
import type { GlCounterparty, GlQuery, Intercompany, IcPair, RelatedGlSideTotals } from "@/types/relatedParty";
import { Skeleton } from "../common";
import { LiveBoundary, NotAvailable } from "../creditors/parts";
import { AppLink, useHere } from "../entry/parts";
import { StatusPill } from "./RelatedPartyPage";

const c = (m: string | null | undefined, signed = false) => (m === null || m === undefined || m === "" ? DASH : fmtCr(Number(m), { signed }));
const CP: Record<GlCounterparty, string> = { HOLDCO: "HoldCo (Citykart Ventures)", SUBCO: "SubCo (Citykart Stores)", SAME_COMPANY: "Same company (ISD registration)" };
const BOOKS: Record<string, string> = { VENTURES: "HoldCo books", RETAIL: "SubCo books" };

function Block({ title, eyebrow, children, testId }: { title: string; eyebrow?: string; children: React.ReactNode; testId?: string }) {
  return (
    <section data-testid={testId} className="rounded-md border bg-card shadow-elegant">
      <div className="border-b px-4 py-2.5">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h2 className="text-[14px] font-semibold tracking-tight">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Card({ testId, label, value, sub, tone }: { testId: string; label: string; value: string; sub: string; tone?: "ok" | "bad" }) {
  return (
    <div className="px-4 py-3" data-testid={testId}>
      <div className="eyebrow">{label}</div>
      <div className={cn("num-mono whitespace-nowrap text-[22px] font-semibold leading-tight", tone === "bad" && "tone-warn")}>{value}</div>
      <div className="text-[11px] text-muted-foreground">{sub}</div>
    </div>
  );
}

function Check({ ok, yes, no, testId }: { ok: boolean; yes: string; no: string; testId: string }) {
  return (
    <span data-testid={testId} data-ok={ok} className={cn("inline-flex items-center gap-1 text-[11.5px] font-semibold", ok ? "text-[oklch(0.4_0.12_155)]" : "tone-warn")}>
      {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
      {ok ? yes : no}
    </span>
  );
}

function FyTable({ p }: { p: IcPair }) {
  return (
    <div className="overflow-x-auto" data-testid={`pair-${p.pair_id}-fy`}>
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-1.5 font-semibold">Financial year (from April)</th>
            <th className="px-2 py-1.5 text-right font-semibold">HoldCo net</th>
            <th className="px-2 py-1.5 text-right font-semibold">SubCo net</th>
            <th className="px-4 py-1.5 text-right font-semibold">Difference</th>
          </tr>
        </thead>
        <tbody>
          {p.by_fy.map((f) => (
            <tr key={f.fy} data-testid={`fy-${p.pair_id}-${f.fy}`} className="border-b">
              <td className="num px-4 py-1.5">{f.fy}{f.one_sided && <span className="ml-2 text-[11px] tone-warn">one side only: not carried by the other company</span>}</td>
              <td className="num px-2 py-1.5 text-right">{c(f.holdco_net_cr)}</td>
              <td className="num px-2 py-1.5 text-right">{c(f.subco_net_cr)}</td>
              <td className={cn("num px-4 py-1.5 text-right font-semibold", !f.matches && "tone-warn")}>{f.matches ? DASH : c(f.difference_cr, true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PairTable({ p }: { p: IcPair }) {
  const quarterly = p.pair_id === "SERVICE";
  const fy = !quarterly && p.by_fy.length > 0;
  return (
    <div data-testid={`pair-${p.pair_id}`} className="border-b last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
        <div className="text-[12.5px] font-semibold">{p.label}</div>
        <div className="flex items-center gap-3 text-[11.5px] text-muted-foreground">
          <span>HoldCo {c(p.totals.holdco_net_cr)} · SubCo {c(p.totals.subco_net_cr)} · difference {c(p.totals.difference_cr, true)}</span>
          <Check testId={`pair-${p.pair_id}-check`} ok={p.totals.mirrors} yes="Both sides agree" no="Sides differ" />
        </div>
      </div>
      {fy && <FyTable p={p} />}
      <details open={!fy}>
        {fy && <summary className="cursor-pointer px-4 py-1.5 text-[11.5px] font-semibold text-primary">Month by month ({p.monthly.length})</summary>}
      <div className="overflow-x-auto">
        <table className="w-full text-[12.5px]" data-testid={`pair-${p.pair_id}-table`}>
          <thead>
            <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
              <th className="px-4 py-1.5 font-semibold">{quarterly ? "Billed in" : "Month"}</th>
              <th className="px-2 py-1.5 text-right font-semibold">HoldCo debit</th>
              <th className="px-2 py-1.5 text-right font-semibold">HoldCo credit</th>
              <th className="px-2 py-1.5 text-right font-semibold">SubCo debit</th>
              <th className="px-2 py-1.5 text-right font-semibold">SubCo credit</th>
              <th className="px-4 py-1.5 text-right font-semibold">Difference</th>
            </tr>
          </thead>
          <tbody>
            {p.monthly.map((m) => (
              <tr key={m.month} className="border-b">
                <td className="num px-4 py-1.5">{m.month}</td>
                <td className="num px-2 py-1.5 text-right">{c(m.holdco_dr_cr)}</td>
                <td className="num px-2 py-1.5 text-right">{c(m.holdco_cr_cr)}</td>
                <td className="num px-2 py-1.5 text-right">{c(m.subco_dr_cr)}</td>
                <td className="num px-2 py-1.5 text-right">{c(m.subco_cr_cr)}</td>
                <td className={cn("num px-4 py-1.5 text-right font-semibold", !m.matches && "tone-warn")}>{m.matches ? DASH : c(m.difference_cr, true)}</td>
              </tr>
            ))}
            {p.monthly.length === 0 && <tr><td colSpan={6} className="px-4 py-3 text-muted-foreground">{DASH} No postings found for this pair.</td></tr>}
          </tbody>
        </table>
      </div>
      </details>
    </div>
  );
}

function IcBody({ d }: { d: Intercompany }) {
  const ln = d.loan;
  const sv = d.service;
  const rep = d.reported_by_ledger;
  const full = d.sources.full_ledger;
  const nc = ln.not_carried;
  const eff = d.effect_on_ebitda;
  return (
    <div className="space-y-3 p-4">
      <div data-testid="ic-basis" className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-[12px]", ln.full_history ? "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)]" : "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] text-[oklch(0.4_0.09_75)]")}>
        {ln.full_history ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
        <span>
          {ln.basis}. {ln.full_history ? "" : `${ln.balance_note}. `}Loan and interest: {d.sources.loan ?? DASH}; service charges: {d.sources.service ?? DASH}.
          {" "}{full ? full.note : ""}
        </span>
      </div>

      <section className="grid grid-cols-3 divide-x rounded-md border @max-[900px]:grid-cols-1 @max-[900px]:divide-x-0 @max-[900px]:divide-y" data-testid="ic-cards">
        <div data-testid="ic-loan">
          {ln.full_history ? (
            <>
              <Card testId="ic-loan-net" label="Loan balance per ledger (SubCo owes HoldCo)" value={c(ln.subco_balance_cr)} sub={`SubCo ledger ${c(ln.subco_balance_cr)} · HoldCo ledger ${c(ln.holdco_balance_cr)} · all history`} />
              <div className="px-4 pb-3"><Check testId="ic-loan-mirror" ok={ln.carried_years_mirror} yes="Every year both companies carry mirrors exactly" no="Years both carry do not mirror" /></div>
            </>
          ) : (
            <>
              <Card testId="ic-loan-net" label="Loan movement since Apr-25 (partial view)" value={c(ln.net_movement_cr, true)} sub={`SubCo drew ${c(ln.drawn_cr)} and repaid ${c(ln.repaid_cr)} on cost-tagged lines; not the loan balance`} />
              <div className="px-4 pb-3"><Check testId="ic-loan-mirror" ok={ln.mirrors} yes="HoldCo and SubCo ledgers mirror every month" no={`Ledgers differ by ${c(ln.variance_cr, true)}`} /></div>
            </>
          )}
        </div>
        <div data-testid="ic-interest">
          <Card testId="ic-interest-net" label="Interest accrued vs payable vs expense" value={c(ln.interest.accrued_holdco_cr, true)} sub={`HoldCo accrued · SubCo payable ${c(ln.interest.payable_subco_cr, true)} · SubCo expense ${c(ln.interest.expense_subco_cr)}`} />
          <div className="px-4 pb-3"><Check testId="ic-interest-mirror" ok={ln.interest.mirrors} yes="HoldCo accrual mirrors SubCo payable" no="Accrual and payable differ" /></div>
        </div>
        <div data-testid="ic-service">
          <Card testId="ic-service-net" label="Service charges: HoldCo billed vs SubCo charged" value={c(sv.billed_holdco_cr)} sub={`SubCo charged ${c(sv.charged_subco_cr)} · unmatched ${c(sv.unmatched_cr, true)} over ${sv.billings} billings`} tone={Math.abs(Number(sv.unmatched_cr)) >= 0.0005 ? "bad" : undefined} />
          <div className="px-4 pb-3 text-[11.5px] text-muted-foreground">
            {sv.constant_difference && sv.by_quarter[0] ? <span data-testid="ic-service-flag" className="tone-warn font-semibold">HoldCo is higher by {c(sv.by_quarter[0].difference_cr)} every quarter: unexplained, not netted.</span> : "Compare each billing below."}
          </div>
        </div>
      </section>

      {ln.full_history && (
        <div data-testid="ic-not-carried" className="rounded-md border px-4 py-3 text-[12.5px]">
          <div className="eyebrow">Not carried by the other side</div>
          <p className="mt-1">
            SubCo loan entries before {nc.pre_carry_years.length ? "the first year HoldCo carries" : "the years shown"} ({nc.pre_carry_years.join(", ") || DASH}) total <b className="num">{c(nc.pre_carry_gap_cr, true)}</b> against HoldCo.
          </p>
          {nc.ledger && (
            <p className="mt-1">
              A separate SubCo ledger, {nc.ledger.glname} ({nc.ledger.glcode}, {nc.ledger.lines} lines), has <b className="num">{c(nc.ledger.dr_cr)} Dr</b> and no HoldCo counterpart.
              {nc.after_uncarried_difference_cr !== null && <> After it, HoldCo is higher than SubCo by <b className="num">{c(nc.after_uncarried_difference_cr, true)}</b>.</>}
            </p>
          )}
          <p className="mt-1 text-muted-foreground">{nc.note}</p>
        </div>
      )}

      {!ln.full_history && <div data-testid="ic-reported" className="rounded-md border">
        <div className="border-b px-4 py-2">
          <div className="eyebrow">Reported by the ledger (silver)</div>
          <div className="text-[12px] text-muted-foreground">{rep.note}</div>
        </div>
        <table className="w-full text-[12.5px]">
          <tbody>
            {rep.ledgers.map((l) => (
              <tr key={`${l.entity}-${l.glcode}-${l.glname}`} className="border-b last:border-b-0">
                <td className="px-4 py-1.5">{l.glname} <span className="text-[11px] text-muted-foreground">· {l.side === "holdco" ? "HoldCo" : "SubCo"} · {l.glcode}{l.lines ? ` · ${l.lines} lines` : ""}{l.last_entry ? ` · last ${l.last_entry}` : ""}</span></td>
                <td className="num px-4 py-1.5 text-right font-semibold">{l.amount_cr === null ? `${DASH} not supplied` : `${l.approx ? "about " : ""}${c(l.amount_cr)} ${l.drcr ?? ""}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rep.loan_difference_cr !== null && (
          <div data-testid="ic-reported-diff" className="border-t px-4 py-2 text-[12px] text-muted-foreground">
            The two full loan ledgers differ by {c(rep.loan_difference_cr, true)} (SubCo credit minus HoldCo debit)
            {rep.after_old_debit_cr !== null ? `; ${c(rep.after_old_debit_cr, true)} after the old 2019 SubCo debit` : ""}. Not forced to zero.
          </div>
        )}
      </div>}

      <div className="rounded-md border">
        {d.pairs.filter((p) => p.pair_id !== "OTHER").map((p) => <PairTable key={p.pair_id} p={p} />)}
        <div className="border-t px-4 py-2 text-[11px] text-muted-foreground">{d.pairs.flatMap((p) => p.notes).join(" ")}</div>
      </div>

      <div data-testid="ic-effect" className="rounded-md border px-4 py-3 text-[12.5px]">
        <div className="eyebrow">Effect on EBITDA</div>
        <p className="mt-1">{eff.reason}</p>
        <p className="mt-1 text-muted-foreground">{eff.note}</p>
        <div className="num mt-1 text-[12px]">Consolidated {c(eff.consolidated_cr)} · SubCo alone {c(eff.subco_standalone_cr, true)} · HoldCo alone {c(eff.holdco_standalone_cr, true)}</div>
      </div>

      {d.flags.length > 0 && (
        <ul data-testid="ic-flags" className="rounded-md border">
          {d.flags.map((f, i) => (
            <li key={i} className="flex items-start gap-2 border-b px-4 py-1.5 text-[12.5px] last:border-b-0"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 tone-warn" /><span><b>{f.ledger}</b>: {f.reason}</span></li>
          ))}
        </ul>
      )}

      <details data-testid="ic-candidates" className="rounded-md border">
        <summary className="cursor-pointer px-4 py-2 text-[12px] font-semibold text-primary">Other ledgers whose name looks intercompany, to be confirmed ({d.candidates.length})</summary>
        <ul>
          {d.candidates.map((x) => (
            <li key={`${x.entity}-${x.glcode}`} className="flex justify-between gap-3 border-t px-4 py-1.5 text-[12.5px]">
              <span><b>{x.glname}</b> <span className="text-[11px] text-muted-foreground">· {x.entity === "VENTURES" ? "HoldCo" : "SubCo"} · {x.glcode}</span><span className="block text-[11px] text-muted-foreground">{x.reason}</span></span>
              <span className="num shrink-0">{c(x.net_cr, true)}</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export function IntercompanySection() {
  const q = useRelatedIntercompany();
  return (
    <Block testId="loans" eyebrow="Intercompany · from the ledger" title="Intercompany loan, interest and charges (from the ledger)">
      <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[240px]" />}>
        {(d) => (d.pairs.some((p) => p.configured) ? <IcBody d={d} /> : <div data-testid="loans-unavailable"><NotAvailable title="Not configured" reason="Add the intercompany ledgers to config/mgmt/intercompany_ledgers.csv." /></div>)}
      </LiveBoundary>
    </Block>
  );
}

/* ---------------- All GL entries with group companies ---------------- */

function Totals({ label, t, testId }: { label: string; t: RelatedGlSideTotals; testId: string }) {
  return <Card testId={testId} label={label} value={`${t.entries.toLocaleString("en-IN")} entries`} sub={`Debit ${c(t.debit_cr)} · Credit ${c(t.credit_cr)}`} />;
}

export function GlEntriesSection() {
  const [f, setF] = useState<GlQuery>({ basis: "all", offset: 0 });
  const q = useRelatedGl(f);
  const { next } = useHere([], "Related Party Transactions");
  const set = (p: Partial<GlQuery>) => setF((x) => ({ ...x, offset: 0, ...p }));
  const inp = "rounded border bg-card px-2 py-1 text-[12px]";
  return (
    <Block testId="gl-entries" eyebrow="Group companies · every GL entry" title="All GL entries with group companies">
      <div data-testid="gl-filters" className="flex flex-wrap items-end gap-3 border-b px-4 py-2 text-[11.5px] text-muted-foreground">
        <label className="grid gap-0.5">Books of
          <select aria-label="Books of" className={inp} value={f.entity ?? ""} onChange={(e) => set({ entity: (e.target.value || undefined) as GlQuery["entity"] })}>
            <option value="">Both</option><option value="VENTURES">HoldCo (Citykart Ventures)</option><option value="RETAIL">SubCo (Citykart Stores)</option>
          </select>
        </label>
        <label className="grid gap-0.5">From month<input aria-label="From month" type="month" className={inp} value={f.from_month ?? ""} onChange={(e) => set({ from_month: e.target.value || undefined })} /></label>
        <label className="grid gap-0.5">To month<input aria-label="To month" type="month" className={inp} value={f.to_month ?? ""} onChange={(e) => set({ to_month: e.target.value || undefined })} /></label>
        <label className="grid gap-0.5">Matched by
          <select aria-label="Matched by" className={inp} value={f.basis} onChange={(e) => set({ basis: e.target.value as GlQuery["basis"] })}>
            <option value="all">Party name or ledger</option><option value="party">Party name only</option><option value="ledger">Ledger only</option>
          </select>
        </label>
      </div>
      <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[200px]" />}>
        {(d) => (
          <div>
            <section className="grid grid-cols-4 divide-x border-b @max-[900px]:grid-cols-2 @max-[900px]:divide-y" data-testid="gl-cards">
              <Totals testId="gl-holdco" label="In HoldCo books" t={d.by_entity.VENTURES} />
              <Totals testId="gl-subco" label="In SubCo books" t={d.by_entity.RETAIL} />
              <Totals testId="gl-same" label="Same-company registration (ISD)" t={d.same_company} />
              <Card testId="gl-mirror" label="Party lines: HoldCo vs SubCo" value={`${c(d.mirror.debit_vs_credit_cr, true)} / ${c(d.mirror.credit_vs_debit_cr, true)}`}
                sub={d.mirror.mirrors ? "HoldCo debit = SubCo credit and the reverse" : "Do not agree (debit vs credit / credit vs debit); shown, not forced"} tone={d.mirror.mirrors ? undefined : "bad"} />
            </section>
            <div data-testid="gl-ledger-mirror" className="border-b px-4 py-2 text-[11.5px] text-muted-foreground">
              Ledger pairs: {d.ledger_mirror.map((m) => `${m.pair_id} difference ${c(m.difference_cr, true)}`).join(" · ")}. Entries read from {d.source.entries === "related_party_gl_lines" ? "gold_fpa.related_party_gl_lines (full ledger lines)" : "voucher_lines (cost-tagged lines since Apr-2025, a partial view)"}.
              {d.source.control && <span data-testid="gl-control" data-ok={d.source.control.ok}> Table check against its control totals: {d.source.control.ok ? "ties out" : "DOES NOT tie out"}.</span>}
            </div>
            <div data-testid="gl-register" className="border-b px-4 py-2 text-[12px]">
              <div className="eyebrow">Party-name register ({d.party_register.patterns}: {d.party_register.proposed} proposed · {d.party_register.confirmed} confirmed)</div>
              <ul>
                {d.register.map((r, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-2 py-0.5"><StatusPill status={r.status} /><span>{BOOKS[r.books_of_entity]}</span><code className="text-[11px]">{r.party_pattern}</code><span className="text-muted-foreground">→ {CP[r.counterparty_entity]}</span></li>
                ))}
              </ul>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[12.5px]" data-testid="gl-table">
                <thead>
                  <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                    <th className="px-4 py-2 font-semibold">Date</th><th className="px-2 py-2 font-semibold">Books</th><th className="px-2 py-2 font-semibold">Counterparty</th>
                    <th className="px-2 py-2 font-semibold">Ledgers</th><th className="px-2 py-2 font-semibold">Why listed</th>
                    <th className="px-2 py-2 text-right font-semibold">Debit</th><th className="px-2 py-2 text-right font-semibold">Credit</th><th className="px-4 py-2 font-semibold">Voucher</th>
                  </tr>
                </thead>
                <tbody>
                  {d.entries.map((e) => (
                    <tr key={`${e.entity}-${e.entcode}`} data-testid={`gl-${e.entity}-${e.entcode}`} className="border-b" title={e.narration ?? undefined}>
                      <td className="num px-4 py-1.5">{e.entdt ? fmtDate(e.entdt) : DASH}{e.release_status !== "P" && <span className="ml-1 text-[10.5px] text-muted-foreground">unposted</span>}</td>
                      <td className="px-2 py-1.5">{BOOKS[e.entity]}</td>
                      <td className="px-2 py-1.5">{CP[e.counterparty_entity]}</td>
                      <td className="px-2 py-1.5">{e.ledgers.join(", ")}{e.party && <span className="block text-[11px] text-muted-foreground">{e.party}</span>}
                        {e.balances && e.balances.length > 0 && <span className="num block text-[11px] text-muted-foreground" data-testid={`gl-bal-${e.entity}-${e.entcode}`}>Balance after: {e.balances.map((b) => `${c(b.running_balance_cr, true)}`).join(", ")}</span>}</td>
                      <td className="px-2 py-1.5 text-muted-foreground">{e.reason === "party" ? "Party name" : `Ledger (${e.reason.replace("ledger:", "").replace(/_/g, " ")})`}</td>
                      <td className="num px-2 py-1.5 text-right">{Number(e.debit) ? c(e.debit_cr) : DASH}</td>
                      <td className="num px-2 py-1.5 text-right">{Number(e.credit) ? c(e.credit_cr) : DASH}</td>
                      <td className="px-4 py-1.5"><AppLink testId={`gl-open-${e.entity}-${e.entcode}`} className="num-mono text-[11.5px] font-semibold text-primary underline-offset-2 hover:underline" href={entryHref(e.entcode, next, undefined, e.entity === "VENTURES" ? "VENTURES" : undefined)}>{e.entcode}</AppLink></td>
                    </tr>
                  ))}
                  {d.entries.length === 0 && <tr><td colSpan={8} className="px-4 py-3 text-muted-foreground">{DASH} No entries match these filters.</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t px-4 py-2 text-[11.5px] text-muted-foreground">
              <span data-testid="gl-count">{d.total_entries.toLocaleString("en-IN")} entries · showing {d.filters.offset + (d.returned ? 1 : 0)}–{d.filters.offset + d.returned}. Debit and credit are the group-company lines of each entry only.</span>
              <span className="flex gap-2">
                <button disabled={f.offset === 0} onClick={() => setF({ ...f, offset: Math.max(0, f.offset - d.filters.limit) })} className="press rounded border px-2 py-0.5 disabled:opacity-40">Previous</button>
                <button disabled={f.offset + d.returned >= d.total_entries} onClick={() => setF({ ...f, offset: f.offset + d.filters.limit })} className="press rounded border px-2 py-0.5 disabled:opacity-40">Next</button>
              </span>
            </div>
          </div>
        )}
      </LiveBoundary>
    </Block>
  );
}
