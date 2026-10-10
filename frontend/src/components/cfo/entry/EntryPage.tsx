import { useRouterState } from "@tanstack/react-router";
import { useBillLink, useEntry, useEntryLineDetail, useEntryRun } from "@/api/entryLiveHooks";
import { fmtRupees, num } from "@/api/creditorsLive";
import { DASH, fmtDate } from "@/lib/format";
import { parseEntrySearch } from "@/lib/entryLinks";
import { cn } from "@/lib/utils";
import type { Entry, EntryLine, EntryLineDetail, EntryRunHeader } from "@/types/entryLive";
import { Skeleton } from "../common";
import { LiveBoundary, NotAvailable } from "../creditors/parts";
import { Panel, WorkspaceHeader } from "../panels";
import { BalanceBadge, Crumbs, EntryRunBadge, GAP_NOTE, LINK_REASON, LinkChip, StatusChip } from "./parts";

/**
 * One accounting entry (voucher) from the gold source: header, ALL its lines, the balance check, and the evidence behind it.
 * Dr = Cr is shown as a fact of the extract. The gold table holds cost-tag lines only, so an unbalanced voucher is a data gap and is said to be one.
 */

const money = (m: string | null | undefined) => (m === null || m === undefined || num(m) === 0 ? DASH : fmtRupees(m));

function Fact({ label, children, testId, sub }: { label: string; children: React.ReactNode; testId: string; sub?: React.ReactNode }) {
  return (
    <div className="min-w-0 px-4 py-3" data-testid={testId}>
      <div className="eyebrow">{label}</div>
      <div className="num-mono truncate text-[16px] font-semibold leading-tight">{children}</div>
      {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

function LinesTable({ e, named, detail }: { e: Entry; named: boolean; detail: Map<number, EntryLineDetail> }) {
  const withText = named && e.lines.some((l) => l.text);
  const party = (l: EntryLine, d?: EntryLineDetail) => {
    if (named && d?.vendor_name) return <>{d.vendor_name}{d.vendor_class && <span className="text-muted-foreground"> · {d.vendor_class}</span>}</>;
    if (named && l.text?.sub_ledger_code) return <span className="num">{l.text.sub_ledger_code}</span>;
    if (l.sub_ledger_ref) return <span className="num-mono text-[11.5px] text-muted-foreground" title="Pseudonymous party reference (names are shown to Finance access only)">{l.sub_ledger_ref}</span>;
    return <span className="text-muted-foreground">{DASH}</span>;
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]" data-testid="entry-lines">
        <thead>
          <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-2 font-semibold">#</th>
            <th className="px-2 py-2 font-semibold">Ledger</th>
            <th className="px-2 py-2 font-semibold">Group</th>
            <th className="px-2 py-2 font-semibold">{named ? "Party" : "Party (reference)"}</th>
            <th className="px-2 py-2 font-semibold">Site</th>
            {withText && <th className="px-2 py-2 font-semibold">Narration</th>}
            <th className="px-2 py-2 text-right font-semibold">Debit</th>
            <th className="px-4 py-2 text-right font-semibold">Credit</th>
          </tr>
        </thead>
        <tbody>
          {e.lines.map((l) => {
            const d = detail.get(l.line_no);
            return (
              <tr key={l.line_no} data-testid={`entry-line-${l.line_no}`} className="border-b align-top">
                <td className="num px-4 py-1.5 text-muted-foreground">{l.line_no}</td>
                <td className="px-2 py-1.5">
                  <span className="font-medium text-foreground">{l.ledger_name}</span>
                  <span className="num block text-[10.5px] text-muted-foreground">{l.ledger_code}{l.ledger_nature ? ` · ${l.ledger_nature}` : ""}</span>
                </td>
                <td className="px-2 py-1.5 text-muted-foreground">{d?.fin_group ? d.fin_group.replace(/^\d+-/, "") : DASH}</td>
                <td className="px-2 py-1.5">{party(l, d)}</td>
                <td className="px-2 py-1.5">{d?.site_code != null ? <><span>{d.store_name ?? `Site ${d.site_code}`}</span> <span className="num text-muted-foreground">· {d.site_code}</span></> : <span className="text-muted-foreground">{DASH}</span>}</td>
                {withText && <td className="max-w-[28ch] truncate px-2 py-1.5 text-muted-foreground" title={l.text?.narration ?? undefined}>{l.text?.narration ?? DASH}</td>}
                <td data-exact={l.debit} className="num px-2 py-1.5 text-right font-semibold">{money(l.debit)}</td>
                <td data-exact={l.credit} className="num px-4 py-1.5 text-right font-semibold">{money(l.credit)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 bg-[oklch(0.985_0.006_265)] font-semibold" data-testid="entry-totals">
            <td className="px-4 py-2" colSpan={withText ? 6 : 5}>Total of the {e.line_count} line{e.line_count === 1 ? "" : "s"} in the extract</td>
            <td data-testid="total-dr" data-exact={e.total_dr} className="num px-2 py-2 text-right">{fmtRupees(e.total_dr)}</td>
            <td data-testid="total-cr" data-exact={e.total_cr} className="num px-4 py-2 text-right">{fmtRupees(e.total_cr)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function BillEvidence({ billRef }: { billRef: string }) {
  const q = useBillLink(billRef);
  return (
    <div data-testid="bill-evidence" className="border-b px-4 py-3 text-[12.5px]">
      <div className="eyebrow mb-1">Reached from creditor bill</div>
      <LiveBoundary query={q} skeleton={<Skeleton className="h-14 w-full" />}>
        {(d) => {
          const k = d.link;
          return (
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <LinkChip status={k.link_status} reason={k.not_linked_reason} />
                <span className="text-muted-foreground">matched on {k.key_used.replaceAll("_", " ").toLowerCase()}</span>
                <span className="num text-muted-foreground">· bill {fmtRupees(k.bill_amount.replace(/^-/, ""))}</span>
              </div>
              {k.not_linked_reason && <div className="text-muted-foreground">{LINK_REASON[k.not_linked_reason] ?? k.not_linked_reason}.</div>}
              <div className="text-[11.5px] text-muted-foreground" data-testid="bill-amount-note">
                {k.amount_agrees === null ? "The bill amount cannot be checked against this voucher: the creditor leg of the voucher is not in the extract, so the link is by document code only." : k.amount_agrees ? "The voucher's creditor amount equals the bill." : "The voucher's creditor amount differs from the bill."}
              </div>
            </div>
          );
        }}
      </LiveBoundary>
    </div>
  );
}

function Evidence({ e, run, named, billRef }: { e: Entry; run: EntryRunHeader; named: boolean; billRef?: string }) {
  const text = e.lines.find((l) => l.text?.reference_no)?.text;
  return (
    <Panel testId="entry-evidence" eyebrow="Source and evidence" title="Where this voucher comes from">
      {billRef && <BillEvidence billRef={billRef} />}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 px-4 py-3 text-[12.5px]">
        <dt className="text-muted-foreground">Source</dt><dd>Voucher lines, gold_fpa.voucher_lines (cost-tag grain)</dd>
        <dt className="text-muted-foreground">Voucher key</dt><dd className="num-mono" data-testid="evidence-ref">{e.entry_ref}</dd>
        <dt className="text-muted-foreground">Entry run</dt><dd className="num-mono">{run.entry_run_id}</dd>
        <dt className="text-muted-foreground">Data as of</dt><dd className="num">{fmtDate(run.register_report_date)}</dd>
        <dt className="text-muted-foreground">Register coverage from</dt><dd className="num">{fmtDate(run.coverage_from)}</dd>
        <dt className="text-muted-foreground">Source loaded</dt><dd className="num">{run.source_updated_at ? new Date(run.source_updated_at).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : DASH}</dd>
        {named && e.identity && (<><dt className="text-muted-foreground">Entry number</dt><dd className="num" data-testid="evidence-entry-no">{e.identity.entry_no}</dd></>)}
        {named && text?.reference_no && (<><dt className="text-muted-foreground">Reference</dt><dd className="num">{text.reference_no}{text.reference_date ? ` · ${text.reference_date}` : ""}</dd></>)}
      </dl>
      <div data-testid="entry-attachment" className="border-t px-4 py-2 text-[12px]">
        <span className="font-semibold">Attachment: </span>
        <span className="text-muted-foreground">{e.attachment.message}</span>
      </div>
      <div className="border-t" data-testid="entry-linked-bills">
        <div className="px-4 py-2 text-[12px]">
          <span className="font-semibold">Creditor bills pointing to this voucher: </span>
          {e.linked_bills.length === 0 ? <span className="text-muted-foreground">none</span> : <span className="text-muted-foreground">{e.linked_bills.length}</span>}
        </div>
        {e.linked_bills.length > 0 && (
          <ul className="px-4 pb-2 text-[12px]">
            {e.linked_bills.slice(0, 10).map((b) => (
              <li key={b.item_ref} className="flex items-center justify-between gap-2 py-0.5">
                <span className="num-mono text-muted-foreground">bill {b.item_ref}</span>
                <LinkChip status={b.link_status} />
              </li>
            ))}
          </ul>
        )}
      </div>
      {named && (
        <div className="border-t">
          <NotAvailable title="Prepared / released by, cheque number, counter-ledgers" reason="These fields are not extracted into the gold source. They are shown as not available, never guessed." />
        </div>
      )}
    </Panel>
  );
}

function Body({ e, run, named, billRef, entity }: { e: Entry; run: EntryRunHeader; named: boolean; billRef?: string; entity?: string }) {
  const detail = useEntryLineDetail(e.entry_ref, entity);
  const map = new Map<number, EntryLineDetail>((detail.data?.lines ?? []).map((d) => [d.line_no, d]));
  const diff = (num(e.total_dr) - num(e.total_cr)).toFixed(2);
  return (
    <div className="space-y-4 p-4">
      <section className="grid grid-cols-6 divide-x rounded-md border bg-card shadow-elegant @max-[1000px]:grid-cols-3 @max-[1000px]:divide-y" data-testid="entry-strip">
        <Fact testId="fact-type" label="Type" sub={e.entry_type_long}>{e.entry_type_short}</Fact>
        <Fact testId="fact-number" label={named && e.identity ? "Entry number" : "Voucher key"}>{named && e.identity ? e.identity.entry_no : e.entry_ref}</Fact>
        <Fact testId="fact-date" label="Entry date">{fmtDate(e.entry_date)}</Fact>
        <Fact testId="fact-site" label="Created at site" sub={named && e.identity?.created_by_site ? e.identity.created_by_site : undefined}>{e.site_code ?? DASH}</Fact>
        <Fact testId="fact-status" label="Status"><StatusChip status={e.release_status} /></Fact>
        <Fact testId="fact-lines" label="Lines" sub={`${e.selections.length ? `touches ${e.selections.join(", ")}` : "no till / bill link"}`}>{e.line_count}</Fact>
      </section>

      <div data-testid="entry-balance" data-balanced={String(e.balanced)} className={cn("rounded-md border px-4 py-3 text-[12.5px] shadow-elegant", e.balanced ? "bg-card" : "border-[oklch(0.8_0.08_85)] bg-[oklch(0.995_0.012_90)]")}>
        <div className="flex flex-wrap items-center gap-3">
          <BalanceBadge balanced={e.balanced} difference={diff} />
          <span className="num">Debit <b data-exact={e.total_dr}>{fmtRupees(e.total_dr)}</b></span>
          <span className="num">Credit <b data-exact={e.total_cr}>{fmtRupees(e.total_cr)}</b></span>
          {!e.balanced && <span className="num font-semibold" data-testid="balance-difference">Difference {fmtRupees(diff)}</span>}
        </div>
        {!e.balanced && <p data-testid="gap-note" className="mt-1.5 max-w-3xl text-[12px] text-muted-foreground">{GAP_NOTE}</p>}
        {e.balanced && <p className="mt-1 text-[11.5px] text-muted-foreground">The lines in the extract add up. The gold extract holds cost-tag lines only, so this is the whole voucher only when it is shown as balanced.</p>}
      </div>

      <div className="grid grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)] gap-4 @max-[1100px]:grid-cols-1">
        <Panel testId="entry-lines-panel" eyebrow="All lines" title={`${e.line_count} line${e.line_count === 1 ? "" : "s"} of voucher ${e.entry_type_short}`} right={detail.isError ? <span className="text-[11px] text-muted-foreground" data-testid="detail-missing">Group and site detail unavailable</span> : undefined}>
          <LinesTable e={e} named={named} detail={map} />
        </Panel>
        <Evidence e={e} run={run} named={named} billRef={billRef} />
      </div>
    </div>
  );
}

export function EntryPage() {
  const raw = useRouterState({ select: (s) => s.location.search as Record<string, unknown> });
  const p = parseEntrySearch(raw);
  const run = useEntryRun();
  const q = useEntry(p.ref ?? null, p.entity);
  const title = q.data ? `${q.data.entry.entry_type_short} · ${q.data.named && q.data.entry.identity ? q.data.entry.identity.entry_no : q.data.entry.entry_ref}` : p.ref ? `Voucher ${p.ref}` : "Voucher";
  return (
    <div data-testid="entry-page" className="@container">
      <Crumbs trail={p.trail} current={title} />
      <WorkspaceHeader
        eyebrow="Voucher · accounting entry"
        title={title}
        subtitle={q.data ? `${q.data.entry.entry_type_long} · ${fmtDate(q.data.entry.entry_date)} · ${q.data.named ? "Finance view" : "Masked view"}` : undefined}
        right={<>
          {q.data && (
            <a
              data-testid="create-correction"
              title="Move a line of this voucher to another management group or expense month. Opens the Corrections workbench (sign-in required); nothing is changed here."
              href={`/control/corrections?entity=${p.entity === "VENTURES" ? "VENTURES" : "RETAIL"}&voucher=${encodeURIComponent(q.data.entry.entry_ref)}`}
              className="press rounded border px-2.5 py-1 text-[12px] font-semibold text-primary hover:bg-muted"
            >
              Create correction
            </a>
          )}
          <EntryRunBadge />
        </>}
      />
      {!p.ref ? (
        <NotAvailable testId="entry-no-ref" title="No voucher selected" reason="Open a voucher from a creditor bill, a P&L ledger or a store till day. A voucher link carries its key in the address." />
      ) : (
        <LiveBoundary query={q} skeleton={<div className="space-y-4 p-4"><Skeleton className="h-16 w-full" /><Skeleton className="h-[260px] w-full" /></div>}>
          {(d) => (run.data ? <Body e={d.entry} run={run.data} named={d.named} billRef={p.bill} entity={p.entity} /> : null)}
        </LiveBoundary>
      )}
    </div>
  );
}
