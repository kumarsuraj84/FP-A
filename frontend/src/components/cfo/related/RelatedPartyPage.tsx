import { Fragment, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, Handshake, XCircle } from "lucide-react";
import { useRelatedItems, useRelatedSummary } from "@/api/relatedLiveHooks";
import { absText, fmtRupees, num, toCr } from "@/api/creditorsLive";
import { DASH, fmtCr, fmtDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { RelatedCandidate, RelatedLoans, RelatedParty, RelatedSummary } from "@/types/relatedParty";
import { Skeleton } from "../common";
import { DataStateBadge, LiveBoundary, NotAvailable } from "../creditors/parts";
import { BillVoucherCell } from "../entry/BillVoucherCell";
import { useHere } from "../entry/parts";

const AGE_COLS = [
  { key: "D0_30", label: "0–30" },
  { key: "D31_60", label: "31–60" },
  { key: "D61_90", label: "61–90" },
  { key: "D91_180", label: "91–180" },
  { key: "D181_365", label: "181–365" },
  { key: "D365_PLUS", label: ">365" },
] as const;

const cr = (m: string | null | undefined) => fmtCr(toCr(m));

function Block({ title, eyebrow, children, testId, right }: { title: string; eyebrow?: string; children: React.ReactNode; testId?: string; right?: React.ReactNode }) {
  return (
    <section data-testid={testId} className="rounded-md border bg-card shadow-elegant">
      <div className="flex items-end justify-between gap-3 border-b px-4 py-2.5">
        <div>
          {eyebrow && <div className="eyebrow">{eyebrow}</div>}
          <h2 className="text-[14px] font-semibold tracking-tight">{title}</h2>
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

function Cell({ label, value, exact, sub, testId }: { label: string; value: string; exact?: string; sub?: string; testId: string }) {
  return (
    <div className="px-4 py-3" data-testid={testId}>
      <div className="eyebrow">{label}</div>
      <div data-exact={exact} className="num-mono whitespace-nowrap text-[22px] font-semibold leading-tight">{value}</div>
      {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const confirmed = status === "confirmed";
  return (
    <span
      data-testid={`status-${status}`}
      title={confirmed ? "Confirmed by Finance as intercompany" : "Proposed from the name; not yet confirmed by Finance. Excluded from the main pages meanwhile."}
      className={cn(
        "inline-flex rounded-sm border px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide",
        confirmed ? "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]" : "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] text-[oklch(0.45_0.09_75)]",
      )}
    >
      {status}
    </span>
  );
}

function Bills({ code, name }: { code: number; name: string }) {
  const q = useRelatedItems(code);
  const { next } = useHere([], "Related Party Transactions");
  return (
    <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[120px]" />}>
      {(p) => (
        <div data-testid={`bills-${code}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-2 font-semibold">Document</th>
                  <th className="px-2 py-2 font-semibold">Dr/Cr</th>
                  <th className="px-2 py-2 font-semibold">Document date</th>
                  <th className="px-2 py-2 font-semibold">Due date</th>
                  <th className="px-2 py-2 text-right font-semibold">Age</th>
                  <th className="px-2 py-2 text-right font-semibold">Open amount</th>
                  <th className="px-4 py-2 font-semibold">Voucher</th>
                </tr>
              </thead>
              <tbody>
                {p.items.map((i) => (
                  <tr key={i.item_ref} data-testid={`bill-${i.item_ref}`} className="border-b">
                    <td className="px-4 py-2">
                      <span className="font-medium">{[i.document_initial, i.document_no].filter(Boolean).join(" ") || i.document_code}</span>
                      {i.document_type && <span className="text-muted-foreground"> · {i.document_type}</span>}
                    </td>
                    <td className={cn("px-2 py-2 font-semibold", i.drcr === "Dr" && "tone-warn")}>{i.drcr}</td>
                    <td className="num px-2 py-2">{i.document_date ? fmtDate(i.document_date) : DASH}</td>
                    <td className="num px-2 py-2">{i.due_date ? fmtDate(i.due_date) : DASH}</td>
                    <td className="num px-2 py-2 text-right">{i.document_age_days === null ? DASH : `${i.document_age_days} d`}</td>
                    <td data-exact={absText(i.pending)} className={cn("num px-2 py-2 text-right font-semibold", i.drcr === "Dr" && "tone-warn")}>{fmtRupees(absText(i.pending))}</td>
                    <td className="px-4 py-2"><BillVoucherCell itemRef={i.item_ref} documentCode={i.document_code} trail={next} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t bg-[oklch(0.985_0.006_265)] px-4 py-2 text-[11px] text-muted-foreground">
            {name}: {p.total_items.toLocaleString("en-IN")} open item{p.total_items === 1 ? "" : "s"}
            {p.total_items > p.returned ? `, showing the oldest ${p.returned}` : ""}. Debit items are shown as found and not netted into the payable.
          </div>
        </div>
      )}
    </LiveBoundary>
  );
}

function PartyTable({ rows }: { rows: RelatedParty[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]" data-testid="party-table">
        <thead>
          <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-2 font-semibold">Party</th>
            <th className="px-2 py-2 font-semibold">Group entity</th>
            <th className="px-2 py-2 font-semibold">Relationship</th>
            <th className="px-2 py-2 font-semibold">Status</th>
            <th className="px-2 py-2 text-right font-semibold">Payable</th>
            <th className="px-2 py-2 text-right font-semibold">Debit balance</th>
            <th className="px-2 py-2 text-right font-semibold">Net</th>
            <th className="px-2 py-2 text-right font-semibold">Items</th>
            <th className="px-2 py-2 font-semibold">Oldest</th>
            {AGE_COLS.map((a) => <th key={a.key} className="px-2 py-2 text-right font-semibold" title={`Payable by document age, ${a.label} days`}>{a.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isOpen = open === r.sub_ledger_code;
            return (
              <Fragment key={r.sub_ledger_code}>
                <tr data-testid={`party-${r.sub_ledger_code}`} aria-expanded={isOpen} tabIndex={0} onClick={() => setOpen(isOpen ? null : r.sub_ledger_code)} onKeyDown={(e) => e.key === "Enter" && setOpen(isOpen ? null : r.sub_ledger_code)}
                  title={r.basis ? `Basis: ${r.basis}` : undefined} className={cn("press cursor-pointer border-b hover:bg-[oklch(0.97_0.012_265)]", isOpen && "bg-[oklch(0.95_0.025_265)]")}>
                  <td className="px-4 py-2">
                    <span className="inline-flex items-center gap-1 font-medium">{isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}{r.party_name}</span>
                    <span className="num ml-5 block text-[11px] text-muted-foreground">sub-ledger {r.sub_ledger_code}</span>
                  </td>
                  <td className="px-2 py-2 text-muted-foreground">{r.group_entity || DASH}</td>
                  <td className="px-2 py-2 capitalize">{r.relationship || DASH}</td>
                  <td className="px-2 py-2"><StatusPill status={r.status} /></td>
                  <td data-exact={r.payable} className="num px-2 py-2 text-right font-semibold">{cr(r.payable)}</td>
                  <td data-exact={r.debit_balance} className="num px-2 py-2 text-right tone-warn">{cr(r.debit_balance)}</td>
                  <td data-exact={r.net} className="num px-2 py-2 text-right font-semibold">{cr(r.net)}</td>
                  <td className="num px-2 py-2 text-right">{r.items.toLocaleString("en-IN")}</td>
                  <td className="num px-2 py-2" title={r.max_age_days === null ? undefined : `${r.max_age_days} days`}>{r.oldest_doc ? fmtDate(r.oldest_doc) : DASH}</td>
                  {AGE_COLS.map((a) => <td key={a.key} data-exact={r.ageing[a.key]} className="num px-2 py-2 text-right text-muted-foreground">{num(r.ageing[a.key]) === 0 ? DASH : cr(r.ageing[a.key])}</td>)}
                </tr>
                {isOpen && (
                  <tr><td colSpan={9 + AGE_COLS.length} className="border-b bg-background p-0"><Bills code={r.sub_ledger_code} name={r.party_name} /></td></tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Candidates({ rows }: { rows: RelatedCandidate[] }) {
  const withItems = rows.filter((c) => c.open_items > 0);
  const rest = rows.filter((c) => c.open_items === 0);
  const line = (c: RelatedCandidate) => (
    <li key={c.sub_ledger_code} data-testid={`candidate-${c.sub_ledger_code}`} className="flex items-baseline justify-between gap-3 border-b px-4 py-1.5 last:border-b-0">
      <span className="min-w-0">
        <span className="font-medium">{c.party_name}</span> <span className="num text-[11px] text-muted-foreground">· {c.sub_ledger_code}{c.class_name ? ` · ${c.class_name}` : ""}{c.is_extinct ? " · extinct" : ""}</span>
        <span className="block truncate text-[11px] text-muted-foreground">{c.reason}</span>
      </span>
      <span className="num shrink-0 text-right text-[12px]">{c.open_items > 0 ? <>{cr(c.payable)} payable{num(c.debit_balance) ? ` · ${cr(c.debit_balance)} Dr` : ""}</> : <span className="text-muted-foreground">no open items</span>}</span>
    </li>
  );
  return (
    <Block testId="candidates" eyebrow="To be confirmed" title={`Possible group parties not yet in the register (${rows.length})`}>
      <div className="border-b px-4 py-2 text-[11.5px] text-muted-foreground">
        These names look like group entities or cross-charge accounts but are NOT excluded from Creditors, Cash or the Command Center until Finance adds them to the register.
      </div>
      {rows.length === 0 ? (
        <div className="px-4 py-3 text-[12.5px] text-muted-foreground">No other group-looking names found.</div>
      ) : (
        <>
          {withItems.length > 0 && <ul data-testid="candidates-with-balance">{withItems.map(line)}</ul>}
          {rest.length > 0 && (
            <details data-testid="candidates-no-balance">
              <summary className="cursor-pointer px-4 py-2 text-[12px] font-semibold text-primary">{rest.length} more with no open creditor items today</summary>
              <ul>{rest.map(line)}</ul>
            </details>
          )}
        </>
      )}
    </Block>
  );
}

function Loans({ loans }: { loans: RelatedLoans }) {
  if (!loans.available) {
    return (
      <Block testId="loans" eyebrow="Intercompany loans" title="Loans between group companies">
        <div data-testid="loans-unavailable"><NotAvailable title="Not loaded" reason={loans.reason ?? "Intercompany loan data is not available."} /></div>
      </Block>
    );
  }
  const cols = loans.tables.flatMap((t) => t.columns).filter((c, i, a) => a.indexOf(c) === i);
  return (
    <Block testId="loans" eyebrow="Intercompany loans" title={`Loans between group companies (${loans.rows.length} row${loans.rows.length === 1 ? "" : "s"})`}>
      <div className="overflow-x-auto">
        <table className="w-full text-[12.5px]" data-testid="loans-table">
          <thead>
            <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
              {cols.map((c) => <th key={c} className="px-3 py-2 font-semibold">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {loans.rows.map((r, i) => (
              <tr key={i} className="border-b">{cols.map((c) => <td key={c} className="num px-3 py-1.5">{r[c] === null || r[c] === undefined ? DASH : String(r[c])}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t px-4 py-2 text-[11px] text-muted-foreground">Shown as stored in {loans.tables.map((t) => t.table).join(", ")}; columns are not interpreted here.</div>
    </Block>
  );
}

function Recon({ s }: { s: RelatedSummary }) {
  const c = s.controls;
  const ok = c.main_plus_related_equals_all;
  return (
    <div data-testid="recon-strip" data-ok={ok} className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border px-4 py-2 text-[12px]", ok ? "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)]" : "border-[oklch(0.8_0.1_25)] bg-[oklch(0.95_0.04_25)]")}>
      {ok ? <CheckCircle2 className="h-4 w-4 text-[oklch(0.4_0.12_155)]" /> : <XCircle className="h-4 w-4 text-[oklch(0.45_0.2_25)]" />}
      <span className="font-semibold">Reconciliation</span>
      <span className="num">Main creditors <b data-exact={c.main_payable}>{cr(c.main_payable)}</b> + Related <b data-exact={c.related_payable}>{cr(c.related_payable)}</b> = All parties <b data-exact={c.all_payable}>{cr(c.all_payable)}</b> payable</span>
      <span className="num text-muted-foreground" data-exact={c.variance}>variance {fmtRupees(c.variance)}</span>
      <span className="text-muted-foreground">{ok ? "Ties out (payable, debit balances and net)" : "Does NOT tie out: do not rely on these figures"}</span>
    </div>
  );
}

function Body({ s }: { s: RelatedSummary }) {
  const c = s.creditors;
  return (
    <div className="space-y-4 p-4">
      <section className="grid grid-cols-4 divide-x rounded-md border bg-card shadow-elegant @max-[900px]:grid-cols-2 @max-[900px]:divide-y" data-testid="related-strip">
        <Cell testId="rp-payable" label="Payable to related parties" value={cr(c.payable)} exact={c.payable} sub={`credit items · ${c.items.toLocaleString("en-IN")} open items in total`} />
        <Cell testId="rp-debit" label="Debit balances" value={cr(c.debit_balance)} exact={c.debit_balance} sub="Dr in the same sub-ledgers · not netted" />
        <Cell testId="rp-net" label="Net payable" value={cr(c.net)} exact={c.net} sub="payable − debit balances (positive = we owe)" />
        <Cell testId="rp-parties" label="Parties" value={String(c.parties)} sub={`${s.register.proposed} proposed · ${s.register.confirmed} confirmed`} />
      </section>
      <Recon s={s} />
      <Block testId="parties" eyebrow="Creditors side · intercompany" title="Related-party sub-ledgers" right={<span className="text-[11px] text-muted-foreground">Click a party for its open bills</span>}>
        {c.by_party.length === 0 ? <NotAvailable title="No related parties registered" reason="Add sub-ledgers to config/mgmt/related_parties.csv; until then nothing is excluded from the main pages." /> : <PartyTable rows={c.by_party} />}
        <div className="border-t bg-[oklch(0.985_0.006_265)] px-4 py-2 text-[11px] text-muted-foreground">
          Proposed parties are matched by name and are already kept out of Creditors, Cash and the Command Center; Finance confirms them in the register. Ageing columns are payable by document age.
        </div>
      </Block>
      <Candidates rows={s.candidates} />
      <Loans loans={s.loans} />
    </div>
  );
}

/**
 * Related Party Transactions: intercompany creditors (and loans, when loaded) that are excluded from the main Creditors, Cash and Command Center figures
 * and would be eliminated on consolidation. The register of related sub-ledgers is config; the API reconciles main + related = all.
 */
export function RelatedPartyPage() {
  const q = useRelatedSummary();
  return (
    <div data-testid="related-page" className="@container">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-5 py-3">
        <div className="min-w-0">
          <div className="eyebrow">Group · intercompany</div>
          <h1 className="flex items-center gap-2 truncate text-[20px] font-semibold tracking-tight text-foreground"><Handshake className="h-5 w-5 text-muted-foreground" />Related Party Transactions</h1>
          <div data-testid="related-note" className="max-w-3xl text-[12px] text-muted-foreground">
            These are intercompany balances between group companies (Citykart Ventures and Citykart Stores). They are excluded from Creditors, Cash and the Command Center and would be eliminated on consolidation.
          </div>
        </div>
        {q.data && <DataStateBadge state="live" run={q.data.extraction_run_id} asOf={q.data.as_of_date} />}
      </div>
      <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[420px]" />}>{(s) => <Body s={s} />}</LiveBoundary>
    </div>
  );
}
