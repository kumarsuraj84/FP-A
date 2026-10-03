import { Navigate, useRouterState } from "@tanstack/react-router";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowRight, BookOpenText, ChevronRight } from "lucide-react";
import { useVendorProfile } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { vendorIdOf } from "@/lib/creditorNodes";
import { DASH, fmtCr, fmtDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { VendorOpenItem, VendorProfile } from "@/types/creditors";
import { AGE_FILTER_LABELS } from "@/types/creditors";
import { Boundary, Metric, Skeleton, StaleChip } from "../common";
import { PageFrame } from "../DeepPages";
import { AgeingBasisNote, BasisDot, bucketColor } from "./parts";

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

function StripCell({ label, children, sub, basis, testId }: { label: string; children: React.ReactNode; sub?: React.ReactNode; basis?: boolean; testId: string }) {
  return (
    <div className="px-4 py-3" data-testid={testId}>
      <div className="eyebrow">
        {label}
        <BasisDot show={!!basis} />
      </div>
      <div className="num-mono whitespace-nowrap text-[20px] font-semibold leading-tight">{children}</div>
      {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

function Lifecycle({ p }: { p: VendorProfile }) {
  return (
    <ol className="flex flex-wrap items-stretch gap-y-2 px-4 py-4 @max-[900px]:flex-col" data-testid="lifecycle">
      {p.lifecycle.map((s, i) => (
        <li key={s.id} className="flex items-center">
          <div
            data-testid={`lifecycle-${s.id}`}
            className={cn("min-w-[170px] rounded-md border px-3 py-2", s.direction === "result" ? "border-primary/40 bg-[oklch(0.95_0.025_265)]" : s.direction === "increase" ? "bg-[oklch(0.985_0.02_60)]" : s.direction === "decrease" ? "bg-[oklch(0.985_0.015_185)]" : "bg-card")}
          >
            <div className="text-[11px] font-medium text-muted-foreground">{s.label}</div>
            <div className="num-mono text-[17px] font-semibold">
              {s.direction === "increase" ? "+" : s.direction === "decrease" ? "−" : ""}
              {fmtCr(s.amount)}
            </div>
            <div className="text-[11px] text-muted-foreground">{s.documentCount > 0 ? `${s.documentCount} documents` : "brought forward"}</div>
          </div>
          {i < p.lifecycle.length - 1 && <ArrowRight className="mx-2 h-4 w-4 shrink-0 text-muted-foreground @max-[900px]:hidden" />}
        </li>
      ))}
    </ol>
  );
}

function Trend({ p }: { p: VendorProfile }) {
  return (
    <div className="h-[200px] px-2 py-2" data-testid="vendor-trend">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={p.trend} margin={{ top: 10, right: 14, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="vtrend" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="oklch(0.42 0.14 255)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="oklch(0.42 0.14 255)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="oklch(0.92 0.01 260)" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10.5, fill: "oklch(0.5 0.02 260)" }} tickLine={false} axisLine={{ stroke: "oklch(0.9 0.01 260)" }} />
          <YAxis tick={{ fontSize: 10.5, fill: "oklch(0.5 0.02 260)" }} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${Math.round(v * 10) / 10}`} />
          <Tooltip formatter={(v: number) => [fmtCr(v), "Outstanding"]} contentStyle={{ fontSize: 12, borderRadius: 6 }} />
          <Area type="monotone" dataKey="outstanding" stroke="oklch(0.3 0.08 255)" strokeWidth={2.4} fill="url(#vtrend)" dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function VendorMigration({ p }: { p: VendorProfile }) {
  const max = Math.max(...p.migration.flatMap((m) => [m.opening, m.closing]), 1e-9);
  return (
    <div className="px-4 py-3" data-testid="vendor-migration">
      <div className="flex h-[150px] items-end gap-3">
        {p.migration.map((m) => (
          <div key={m.bucket} className="flex flex-1 flex-col items-center gap-1">
            <div className="flex h-[112px] w-full items-end justify-center gap-1">
              <i title={`Opening ${fmtCr(m.opening)}`} className="w-1/2 rounded-t-sm bg-muted-foreground/25" style={{ height: `${(m.opening / max) * 100}%` }} />
              <i title={`Closing ${fmtCr(m.closing)}`} className="w-1/2 rounded-t-sm" style={{ height: `${(m.closing / max) * 100}%`, background: bucketColor(m.bucket) }} />
            </div>
            <span className="num text-[10.5px] font-semibold">{m.closing > 0 ? fmtCr(m.closing, { plain: true }) : ""}</span>
            <span className="text-[10.5px] text-muted-foreground">{AGE_FILTER_LABELS[m.bucket].replace(" days", "")}</span>
          </div>
        ))}
      </div>
      <div className="mt-1 flex items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><i className="h-2 w-3 rounded-sm bg-muted-foreground/25" /> opening</span>
        <span className="flex items-center gap-1"><i className="h-2 w-3 rounded-sm bg-[oklch(0.66_0.11_170)]" /> closing (colour = age)</span>
        <span className="ml-auto">₹ Cr</span>
      </div>
    </div>
  );
}

function OpenItems({ items, basisLabel, onOpen }: { items: VendorOpenItem[]; basisLabel: string; onOpen: (i: VendorOpenItem) => void }) {
  return (
    <table className="w-full text-[12.5px]" data-testid="open-items">
      <thead>
        <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
          <th className="px-4 py-2 font-semibold">Document</th>
          <th className="px-2 py-2 font-semibold">Document date</th>
          <th className="px-2 py-2 font-semibold">Due date</th>
          <th className="px-2 py-2 text-right font-semibold" title={basisLabel}>Age (provisional)</th>
          <th className="px-2 py-2 font-semibold">Bucket</th>
          <th className="px-4 py-2 text-right font-semibold">Open amount</th>
        </tr>
      </thead>
      <tbody>
        {items.map((i) => (
          <tr key={i.documentRef} data-testid={`open-item-${i.documentRef}`} tabIndex={0} onClick={() => onOpen(i)} onKeyDown={(e) => e.key === "Enter" && onOpen(i)} className="press border-b hover:bg-[oklch(0.97_0.012_265)]">
            <td className="px-4 py-2"><span className="font-medium text-primary">{i.documentRef}</span> <span className="text-muted-foreground">· {i.documentType}</span></td>
            <td className="num px-2 py-2">{i.documentDate ? fmtDate(i.documentDate) : DASH}</td>
            <td className="num px-2 py-2">{i.dueDate ? fmtDate(i.dueDate) : DASH}</td>
            <td className="num px-2 py-2 text-right" title={i.ageDays.reason}>{i.ageDays.value === null ? DASH : `${i.ageDays.value} d`}</td>
            <td className="px-2 py-2">
              {i.bucket ? (
                <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: bucketColor(i.bucket) }} />{AGE_FILTER_LABELS[i.bucket]}</span>
              ) : (
                DASH
              )}
            </td>
            <td className="num px-4 py-2 text-right font-semibold">{fmtCr(i.amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function VendorProfilePage() {
  const { state, ready, resolving, pushNode, pushNodes } = useCfo();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const vnode = [...state.nodes].reverse().find((n) => n.dim === "Vendor");
  const vendorId = vendorIdOf(vnode);
  const q = useVendorProfile(vendorId);
  if (ready && !resolving && pathname === "/creditors/vendor" && !vendorId) return <Navigate to="/creditors" />;

  const goLedger = () => pushNode({ level: "ledger", dim: "Ledger", id: "ledger", label: "GL", amount: vnode?.amount ?? null, variance: null });
  const openDoc = (i: VendorOpenItem) => pushNodes([{ level: "voucher", dim: "Voucher", id: i.documentRef, label: i.documentRef, amount: i.amount, variance: null }]);
  const p = q.data?.data;

  return (
    <PageFrame
      eyebrow="Vendor financial profile"
      title={p?.name ?? vnode?.label ?? "Vendor"}
      subtitle={p ? `${p.code} · payment terms ${p.paymentTerms}` : undefined}
      right={
        <div className="flex items-center gap-2">
          {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
          {p && <AgeingBasisNote basis={p.ageingBasis} />}
          <button data-testid="vendor-open-ledger" onClick={goLedger} className="press inline-flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-[12.5px] font-semibold text-primary-foreground hover:bg-primary/90">
            <BookOpenText className="h-4 w-4" /> Open ledger <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      }
    >
      <div className="@container" data-testid="vendor-profile">
        <Boundary query={q} skeleton={<Skeleton className="h-[520px] w-full" />} emptyTitle="No profile for this vendor">
          {(v) => (
            <div className="space-y-4">
              <section className="grid grid-cols-6 divide-x rounded-md border bg-card shadow-elegant @max-[900px]:grid-cols-3 @max-[900px]:divide-y" data-testid="vendor-strip">
                <StripCell testId="strip-outstanding" label="Outstanding" sub="creditor balance"><Metric m={v.strip.outstanding} fmt={(n) => fmtCr(n)} /></StripCell>
                <StripCell testId="strip-overdue" label="Overdue" basis sub="basis awaiting validation"><Metric m={v.strip.overdue} fmt={(n) => fmtCr(n)} /></StripCell>
                <StripCell testId="strip-over90" label=">90 days"><Metric m={v.strip.over90} fmt={(n) => fmtCr(n)} /></StripCell>
                <StripCell testId="strip-advance" label="Advance" sub="separate from creditor balance"><Metric m={v.strip.advance} fmt={(n) => fmtCr(n)} /></StripCell>
                <StripCell testId="strip-oldest" label="Oldest item" sub={v.strip.oldestItemRef ?? v.strip.oldestItem.reason}>
                  <Metric m={v.strip.oldestItem} fmt={(n) => `${n} days`} />
                </StripCell>
                <StripCell testId="strip-lastpay" label="Last payment" sub={v.strip.lastPayment.date ? fmtDate(v.strip.lastPayment.date) : "No payment in period"}>
                  <Metric m={v.strip.lastPayment.amount} fmt={(n) => fmtCr(n)} />
                </StripCell>
              </section>

              <Block testId="vendor-lifecycle" eyebrow="Financial lifecycle" title="Purchase → invoice → credit note / adjustment → payment → open balance">
                <Lifecycle p={v} />
              </Block>

              <div className="grid grid-cols-2 gap-4 @max-[1000px]:grid-cols-1">
                <Block eyebrow="Exposure trend" title="12-month outstanding movement">
                  <Trend p={v} />
                </Block>
                <Block eyebrow="Ageing migration" title="How this vendor's balance moved across ageing buckets">
                  <VendorMigration p={v} />
                </Block>
              </div>

              <div className="grid grid-cols-2 gap-4 @max-[1000px]:grid-cols-1">
                <Block testId="payment-behaviour" eyebrow="Payment behaviour" title="Frequency and elapsed days">
                  <div className="grid grid-cols-2 divide-x border-b">
                    <div className="px-4 py-2.5">
                      <div className="eyebrow">Payments / month</div>
                      <div className="num-mono text-[18px] font-semibold"><Metric m={v.paymentBehaviour.paymentsPerMonth} fmt={(n) => n.toFixed(1)} /></div>
                    </div>
                    <div className="px-4 py-2.5">
                      <div className="eyebrow">Avg days to pay</div>
                      <div className="num-mono text-[18px] font-semibold"><Metric m={v.paymentBehaviour.avgDaysToPay} fmt={(n) => `${n} days`} /></div>
                    </div>
                  </div>
                  <ul>
                    {v.paymentBehaviour.recent.map((r) => (
                      <li key={r.date} className="flex items-center justify-between border-b px-4 py-1.5 text-[12.5px] last:border-b-0">
                        <span className="num">{fmtDate(r.date)}</span>
                        <span className="num text-muted-foreground">{r.daysElapsed} days after invoice</span>
                        <span className="num font-semibold">{fmtCr(r.amount)}</span>
                      </li>
                    ))}
                  </ul>
                </Block>
                <div className="space-y-4">
                  <Block testId="advance-position" eyebrow="Advance position" title="Vendor advance (separate from the creditor balance)">
                    <div className="px-4 py-3">
                      <div className="num-mono text-[20px] font-semibold"><Metric m={v.advancePosition.amount} fmt={(n) => (n === 0 ? "None" : fmtCr(n))} /></div>
                      <div className="text-[11.5px] text-muted-foreground">{v.advancePosition.source}</div>
                      <div className="mt-1 text-[11.5px] text-muted-foreground">{v.advancePosition.note}</div>
                    </div>
                  </Block>
                  <Block testId="debit-balance" eyebrow="Creditor-account debit balance" title="Shown as found; not classified">
                    <div className="px-4 py-3">
                      <div className="num-mono text-[20px] font-semibold"><Metric m={v.debitBalance.amount} fmt={(n) => (n === 0 ? "None" : fmtCr(n))} /></div>
                      <div className="mt-1 text-[11.5px] text-muted-foreground">{v.debitBalance.note}</div>
                    </div>
                  </Block>
                </div>
              </div>

              <Block testId="vendor-abnormal" eyebrow="Diagnostics" title="Unreconciled / abnormal items">
                {v.abnormal.length === 0 ? (
                  <div className="px-4 py-4 text-[12.5px] text-muted-foreground">No diagnostic categories flagged for this vendor.</div>
                ) : (
                  <ul>
                    {v.abnormal.map((a) => (
                      <li key={a.categoryId} className="flex items-center justify-between border-b px-4 py-2 text-[12.5px] last:border-b-0">
                        <span className="font-medium">{a.label}</span>
                        <span className="num text-muted-foreground">{a.documentRef ?? DASH}</span>
                        <span className="num font-semibold" title={a.amount.reason}>
                          <Metric m={a.amount} fmt={(n) => fmtCr(n)} />
                          {a.amount.value === null && <span className="ml-2 text-[10.5px] font-normal text-muted-foreground">{a.amount.reason}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Block>

              <Block testId="vendor-open-items" eyebrow="Open items" title={`${v.openItems.length} open documents · ${fmtCr(v.openBalance)}`} right={<AgeingBasisNote basis={v.ageingBasis} />}>
                <OpenItems items={v.openItems} basisLabel={v.ageingBasis.label} onOpen={openDoc} />
                <div className="border-t bg-[oklch(0.985_0.006_265)] px-4 py-2 text-[11px] text-muted-foreground">Age is measured from the {v.ageingBasis.provisional?.replace("_", " ") ?? "document"} date provisionally. Select a document to open its voucher and source evidence.</div>
              </Block>
            </div>
          )}
        </Boundary>
      </div>
    </PageFrame>
  );
}
