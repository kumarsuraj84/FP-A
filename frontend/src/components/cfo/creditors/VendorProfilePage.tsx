import { useState } from "react";
import { Navigate, useRouterState } from "@tanstack/react-router";
import { useLiveItems, useLiveLedgers, useLiveRun, useLiveVendor } from "@/api/creditorsLiveHooks";
import { API_TO_BUCKET, absText, fmtRupees, num, toCr, vendorLabel } from "@/api/creditorsLive";
import { useCfo } from "@/context/CfoContext";
import { vendorIdOf } from "@/lib/creditorNodes";
import { DASH, fmtCr, fmtDate, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AGE_FILTER_LABELS, type BucketId } from "@/types/creditors";
import type { LiveItem, LiveVendor } from "@/types/creditorsLive";
import { Skeleton } from "../common";
import { PageFrame } from "../DeepPages";
import { DUE_COLOR, DUE_ORDER, DataStateBadge, LiveBoundary, NotAvailable, bucketColor } from "./parts";

const AGE_KEYS = ["D0_30", "D31_60", "D61_90", "D91_180", "D181_365", "D365_PLUS"] as const;
const DUE_LABEL: Record<string, string> = { NOT_YET_DUE: "Not yet due", PAST_DUE_OR_DUE_TODAY: "Past due / due today", DUE_UNAVAILABLE: "Due date unavailable", DUE_INVALID: "Invalid due date" };
const UNCLASSIFIED_COLOR = "oklch(0.8 0.02 260)";

function Block({ title, eyebrow, children, right, testId }: { title: string; eyebrow?: string; children: React.ReactNode; right?: React.ReactNode; testId?: string }) {
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

function StripCell({ label, children, sub, testId, exact }: { label: string; children: React.ReactNode; sub?: React.ReactNode; testId: string; exact?: string }) {
  return (
    <div className="px-4 py-3" data-testid={testId}>
      <div className="eyebrow">{label}</div>
      <div data-exact={exact} className="num-mono whitespace-nowrap text-[20px] font-semibold leading-tight">{children}</div>
      {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

/** One stacked bar from a { key → exact text } split, with a legend row of amounts. Zero parts are not drawn. */
function Split({ parts, testId }: { parts: { key: string; label: string; color: string; value: string }[]; testId: string }) {
  const total = parts.reduce((a, p) => a + num(p.value), 0);
  return (
    <div className="px-4 py-3" data-testid={testId}>
      <div className="flex h-4 overflow-hidden rounded-sm bg-muted/50" aria-hidden>
        {parts.map((p) => (
          <i key={p.key} title={`${p.label}: ${fmtRupees(p.value)}`} style={{ width: `${total ? (num(p.value) / total) * 100 : 0}%`, background: p.color }} />
        ))}
      </div>
      <ul className="mt-2 grid grid-cols-3 gap-x-4 gap-y-1 text-[12px] @max-[900px]:grid-cols-2">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center justify-between gap-2" data-testid={`${testId}-${p.key}`}>
            <span className="flex items-center gap-1.5 text-muted-foreground"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} />{p.label}</span>
            <span data-exact={p.value} className="num font-semibold">{num(p.value) === 0 ? <span className="font-normal text-muted-foreground">{DASH}</span> : fmtCr(toCr(p.value))}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ageLabel(code: string): string {
  const id = API_TO_BUCKET[code];
  return id ? AGE_FILTER_LABELS[id] : code.startsWith("UNCLASSIFIED") ? "Unclassified" : code;
}

function OpenItems({ items, named }: { items: LiveItem[]; named: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]" data-testid="open-items">
        <thead>
          <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-2 font-semibold">{named ? "Document" : "Item"}</th>
            <th className="px-2 py-2 font-semibold">Ledger</th>
            <th className="px-2 py-2 font-semibold">Dr/Cr</th>
            <th className="px-2 py-2 font-semibold">Document date</th>
            <th className="px-2 py-2 font-semibold">Due date</th>
            <th className="px-2 py-2 text-right font-semibold" title="As-of date − document date">Document age</th>
            <th className="px-2 py-2 font-semibold">Due status</th>
            <th className="px-4 py-2 text-right font-semibold">Open amount</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => {
            const bucket: BucketId | undefined = API_TO_BUCKET[i.document_age_bucket];
            return (
              <tr key={i.item_ref} data-testid={`open-item-${i.item_ref}`} className="border-b">
                <td className="px-4 py-2">
                  {named ? (
                    <>
                      <span className="font-medium text-foreground">{[i.document_initial, i.document_no].filter(Boolean).join(" ") || i.document_code}</span>
                      {i.document_type && <span className="text-muted-foreground"> · {i.document_type}</span>}
                    </>
                  ) : (
                    <span className="num-mono text-[11.5px] text-muted-foreground" title={i.item_ref}>…{i.item_ref.slice(-8)}</span>
                  )}
                </td>
                <td className="px-2 py-2 text-muted-foreground">{i.ledger_name}</td>
                <td className={cn("px-2 py-2 font-semibold", i.drcr === "Dr" && "tone-warn")}>{i.drcr}</td>
                <td className="num px-2 py-2">{i.document_date ? fmtDate(i.document_date) : DASH}</td>
                <td className="num px-2 py-2">{i.due_date ? fmtDate(i.due_date) : DASH}</td>
                <td className="num px-2 py-2 text-right" title={i.document_age_days === null ? `No usable document date (${i.document_age_bucket.replaceAll("_", " ").toLowerCase()})` : undefined}>
                  {i.document_age_days === null ? DASH : (
                    <span className="inline-flex items-center gap-1.5">
                      {bucket && <i className="h-2.5 w-2.5 rounded-sm" style={{ background: bucketColor(bucket) }} />}
                      {i.document_age_days} d
                    </span>
                  )}
                </td>
                <td className="px-2 py-2">
                  <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: DUE_COLOR[i.due_status] }} />{DUE_LABEL[i.due_status] ?? i.due_status}</span>
                  {i.overdue_days !== null && i.overdue_days > 0 && <span className="num ml-1 text-[11px] text-muted-foreground">{i.overdue_days} d</span>}
                </td>
                <td data-exact={absText(i.pending)} className={cn("num px-4 py-2 text-right font-semibold", i.drcr === "Dr" && "tone-warn")}>{fmtRupees(absText(i.pending))}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Profile({ v, named }: { v: LiveVendor; named: boolean }) {
  const [side, setSide] = useState<"all" | "Cr" | "Dr">("all");
  const items = useLiveItems(v.vendor_ref, side === "all" ? undefined : side);
  const ledgers = useLiveLedgers();
  const o90 = ["D91_180", "D181_365", "D365_PLUS"].reduce((a, k) => a + num(v.credit_by_document_age[k]), 0);
  const ledgerName = (code: string) => ledgers.data?.find((l) => l.ledger_code === code)?.ledger_name ?? code;
  return (
    <div className="space-y-4">
      <section className="grid grid-cols-6 divide-x rounded-md border bg-card shadow-elegant @max-[900px]:grid-cols-3 @max-[900px]:divide-y" data-testid="vendor-strip">
        <StripCell testId="strip-credit" label="Credit Outstanding" exact={v.credit_outstanding} sub={`${v.credit_items} credit item${v.credit_items === 1 ? "" : "s"} · ${fmtPct(num(v.share_of_credit) * 100, { digits: 2 })} of book`}>{fmtCr(toCr(v.credit_outstanding))}</StripCell>
        <StripCell testId="strip-debit" label="Debit Balance" exact={v.debit_balance} sub={`${v.debit_items} debit item${v.debit_items === 1 ? "" : "s"} · not netted`}>{fmtCr(toCr(v.debit_balance))}</StripCell>
        <StripCell testId="strip-pastdue" label="Past Due" exact={v.past_due_credit} sub="stored due date reached">{fmtCr(toCr(v.past_due_credit))}</StripCell>
        <StripCell testId="strip-noduedate" label="Due Date Unavailable" exact={v.due_unavailable_credit} sub="no due date in source">{fmtCr(toCr(v.due_unavailable_credit))}</StripCell>
        <StripCell testId="strip-over90" label=">90 Days Document Age" exact={String(o90)} sub="credit, by document date">{fmtCr(o90 / 1e7)}</StripCell>
        <StripCell testId="strip-oldest" label="Oldest Credit Item" sub="days since document date">{v.oldest_credit_age_days === null ? DASH : `${v.oldest_credit_age_days} days`}</StripCell>
      </section>

      <div className="grid grid-cols-2 gap-4 @max-[1000px]:grid-cols-1">
        <Block eyebrow="Document Age" title="Credit by age of document">
          <Split
            testId="vendor-age"
            parts={[
              ...AGE_KEYS.map((k) => ({ key: k, label: ageLabel(k), color: bucketColor(API_TO_BUCKET[k]), value: v.credit_by_document_age[k] ?? "0" })),
              { key: "UNCLASSIFIED", label: "Unclassified", color: UNCLASSIFIED_COLOR, value: v.credit_by_document_age.UNCLASSIFIED ?? "0" },
            ]}
          />
        </Block>
        <Block eyebrow="Due Status" title="Credit by what the source says is due">
          <Split testId="vendor-due" parts={DUE_ORDER.map((k) => ({ key: k, label: DUE_LABEL[k], color: DUE_COLOR[k], value: v.credit_by_due_status[k] ?? "0" }))} />
        </Block>
      </div>

      <div className="grid grid-cols-2 gap-4 @max-[1000px]:grid-cols-1">
        <Block testId="vendor-identity" eyebrow="Identity" title={named ? "Vendor identity (Finance access)" : "Vendor identity (restricted)"}>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-4 py-3 text-[12.5px]">
            {named ? (
              <>
                <dt className="text-muted-foreground">Name</dt><dd className="font-medium">{v.vendor_name}</dd>
                <dt className="text-muted-foreground">SLID</dt><dd className="num">{v.slid ?? DASH}</dd>
                <dt className="text-muted-foreground">Sub-ledger code</dt><dd className="num">{v.sub_ledger_code ?? DASH}</dd>
                <dt className="text-muted-foreground">Credit days</dt><dd className="num">{v.credit_days ?? DASH}</dd>
              </>
            ) : (
              <>
                <dt className="text-muted-foreground">Reference</dt><dd className="num-mono">{v.vendor_ref}</dd>
                <dt className="col-span-2 text-[11.5px] text-muted-foreground">Names, codes and document numbers are shown to authorised Finance / CFO access only.</dt>
              </>
            )}
            <dt className="text-muted-foreground">Party class</dt><dd>{v.party_class ?? DASH}{v.party_class_type ? ` · ${v.party_class_type}` : ""}</dd>
            <dt className="text-muted-foreground">Ledgers</dt><dd>{v.ledger_codes.map(ledgerName).join(", ")}</dd>
          </dl>
        </Block>
        <Block testId="vendor-unavailable" eyebrow="Not in this snapshot" title="Shown only when sourced">
          <NotAvailable title="Payment history, advances, lifecycle and ageing movement" reason="The verified extract holds open items as of one date. Payment behaviour, vendor advances, invoice-to-payment lifecycle and migration between buckets need further sources or a second snapshot, so they are not displayed and nothing is estimated." />
        </Block>
      </div>

      <Block
        testId="vendor-open-items"
        eyebrow="Open items"
        title={items.data ? `${items.data.total_items.toLocaleString("en-IN")} open item${items.data.total_items === 1 ? "" : "s"} · oldest document first` : "Open items"}
        right={
          <div role="tablist" aria-label="Side" className="flex gap-1">
            {(["all", "Cr", "Dr"] as const).map((s) => (
              <button key={s} role="tab" aria-selected={side === s} data-testid={`items-${s}`} onClick={() => setSide(s)} className={cn("press rounded px-2 py-0.5 text-[11.5px] font-semibold", side === s ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground")}>
                {s === "all" ? "All" : s === "Cr" ? "Credit" : "Debit"}
              </button>
            ))}
          </div>
        }
      >
        <LiveBoundary query={items} skeleton={<Skeleton className="m-4 h-[200px]" />}>
          {(p) => (
            <>
              <OpenItems items={p.items} named={p.named} />
              {p.total_items > p.returned && <div className="border-t px-4 py-2 text-[11px] text-muted-foreground">Showing the oldest {p.returned} of {p.total_items.toLocaleString("en-IN")}.</div>}
              <div className="border-t bg-[oklch(0.985_0.006_265)] px-4 py-2 text-[11px] text-muted-foreground">Debit items are shown as found and never netted into the credit total.</div>
            </>
          )}
        </LiveBoundary>
      </Block>
    </div>
  );
}

export function VendorProfilePage() {
  const { state, ready, resolving } = useCfo();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const run = useLiveRun();
  const vnode = [...state.nodes].reverse().find((n) => n.dim === "Vendor");
  const ref = vendorIdOf(vnode);
  const q = useLiveVendor(ref);
  if (ready && !resolving && pathname === "/creditors/vendor" && !ref) return <Navigate to="/creditors" />;
  const v = q.data?.vendor;
  const title = v ? vendorLabel(v) : (vnode?.label ?? "Vendor");
  return (
    <PageFrame
      eyebrow="Vendor financial profile"
      title={title}
      subtitle={v ? `${q.data?.named ? "Finance view" : "Masked view"} · ${v.vendor_ref}` : undefined}
      right={<div className="flex items-center gap-2">{run.data && <DataStateBadge state={run.data.data_state} run={run.data.extraction_run_id} asOf={run.data.as_of_date} />}</div>}
    >
      <div className="@container" data-testid="vendor-profile">
        <LiveBoundary query={q} skeleton={<Skeleton className="h-[520px] w-full" />}>
          {(d) => <Profile v={d.vendor} named={d.named} />}
        </LiveBoundary>
      </div>
    </PageFrame>
  );
}
