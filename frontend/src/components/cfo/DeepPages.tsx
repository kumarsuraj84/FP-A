import type { ReactNode } from "react";
import { Navigate, useRouterState } from "@tanstack/react-router";
import { ArrowLeft, FileCheck2, Paperclip } from "lucide-react";
import { useLedger, useProfile, useVoucher } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { DASH, fmtCr, fmtDate, fmtPct, fmtRs } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DrillNode, EntityProfile, LedgerEntry } from "@/types/cfo";
import { Boundary, Metric, Skeleton, StaleChip, toneClass } from "./common";

export function PageFrame({ eyebrow, title, subtitle, children, right }: { eyebrow: string; title: string; subtitle?: string; children: ReactNode; right?: ReactNode }) {
  const { back } = useCfo();
  return (
    <div className="mx-auto w-full max-w-[1500px] px-6 py-5" data-testid="deep-page">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <button data-testid="deep-back" onClick={back} className="press mb-2 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[12px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> Back
          </button>
          <div className="eyebrow">{eyebrow}</div>
          <h1 className="truncate text-[22px] font-semibold tracking-tight text-foreground">{title}</h1>
          {subtitle && <div className="text-[12.5px] text-muted-foreground">{subtitle}</div>}
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}

const PAGE_PATH = { ledger: "/ledger", voucher: "/voucher", profile: "/profile" } as const;

function useDeepNode(level: "ledger" | "voucher" | "profile") {
  const { state, ready, resolving } = useCfo();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const node = state.nodes.find((n) => n.level === level) ?? null;
  // Redirect home only when this page is the one actually being shown. During browser Back the previous page
  // can stay mounted for a frame after the URL moved on; it must not bounce the user to "/".
  // Also wait for a shared / refreshed link to finish replaying before deciding there is no context.
  return { state, ready, node, missing: ready && !resolving && pathname === PAGE_PATH[level] && (!state.origin || !node) };
}

const RECON_STYLE: Record<LedgerEntry["recon"], string> = {
  matched: "bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]",
  pending: "bg-[oklch(0.97_0.05_95)] text-[oklch(0.45_0.1_80)]",
  exception: "bg-[oklch(0.95_0.04_25)] text-[oklch(0.45_0.2_25)]",
};

export function LedgerPage() {
  const { state, pushNode } = useCfo();
  const { missing } = useDeepNode("ledger");
  const q = useLedger(state.origin, state.nodes);
  if (missing) return <Navigate to="/" />;
  return (
    <PageFrame eyebrow="Ledger" title={q.data?.data?.title ?? "General ledger"} subtitle={q.data?.data?.subtitle} right={q.data?.status === "stale" ? <StaleChip reason={q.data.reason} /> : undefined}>
      <Boundary query={q} skeleton={<Skeleton className="h-[420px] w-full" />} emptyTitle="No ledger entries for this selection">
        {(l) => (
          <div className="overflow-hidden rounded-md border bg-card shadow-elegant">
            <div className="grid grid-cols-3 divide-x border-b bg-[oklch(0.985_0.006_265)]">
              {[
                ["Opening balance", fmtRs(l.openingBalance)],
                ["Closing balance", fmtRs(l.closingBalance)],
                ["Entries", String(l.entries.length)],
              ].map(([k, v]) => (
                <div key={k} className="px-4 py-3">
                  <div className="eyebrow">{k}</div>
                  <div className="num-mono text-[18px] font-semibold">{v}</div>
                </div>
              ))}
            </div>
            {l.balanceNote && (
              <div className="border-b px-4 py-1.5 text-[11.5px] text-muted-foreground" data-testid="ledger-balance-note">
                {l.balanceNote}
              </div>
            )}
            <table className="w-full text-[12.5px]" data-testid="ledger-table">
              <thead>
                <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-2 font-semibold">Date</th>
                  <th className="px-2 py-2 font-semibold">Voucher</th>
                  <th className="px-2 py-2 font-semibold">Narration</th>
                  <th className="px-2 py-2 font-semibold">Source</th>
                  <th className="px-2 py-2 text-right font-semibold">Debit</th>
                  <th className="px-2 py-2 text-right font-semibold">Credit</th>
                  <th className="px-2 py-2 text-right font-semibold">Balance</th>
                  <th className="px-4 py-2 font-semibold">Recon</th>
                </tr>
              </thead>
              <tbody>
                {l.entries.map((e) => (
                  <tr
                    key={e.id}
                    data-testid={`ledger-row-${e.id}`}
                    tabIndex={0}
                    onClick={() => pushNode({ level: "voucher", dim: "Voucher", id: e.voucherId, label: e.voucherId, amount: (e.debit || e.credit) / 1e7, variance: null })}
                    onKeyDown={(ev) => ev.key === "Enter" && pushNode({ level: "voucher", dim: "Voucher", id: e.voucherId, label: e.voucherId, amount: (e.debit || e.credit) / 1e7, variance: null })}
                    className="press border-b hover:bg-[oklch(0.97_0.012_265)]"
                  >
                    <td className="num px-4 py-2">{fmtDate(e.date)}</td>
                    <td className="px-2 py-2 font-medium text-primary">{e.voucherId}</td>
                    <td className="px-2 py-2 text-foreground/80">{e.narration}</td>
                    <td className="px-2 py-2 text-muted-foreground">{e.source}</td>
                    <td className="num px-2 py-2 text-right">{e.debit ? fmtRs(e.debit) : DASH}</td>
                    <td className="num px-2 py-2 text-right">{e.credit ? fmtRs(e.credit) : DASH}</td>
                    <td className="num px-2 py-2 text-right font-medium">{fmtRs(e.balance)}</td>
                    <td className="px-4 py-2">
                      <span className={cn("rounded-sm px-1.5 py-0.5 text-[10.5px] font-semibold capitalize", RECON_STYLE[e.recon])}>{e.recon}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="border-t bg-[oklch(0.985_0.006_265)] px-4 py-2 text-[11px] text-muted-foreground">Select a row to open its voucher and source evidence.</div>
          </div>
        )}
      </Boundary>
    </PageFrame>
  );
}

export function VoucherPage() {
  const { node, missing } = useDeepNode("voucher");
  const q = useVoucher(node?.id ?? null, node?.amount === null || node?.amount === undefined ? null : node.amount * 1e7);
  if (missing) return <Navigate to="/" />;
  return (
    <PageFrame eyebrow="Voucher / source evidence" title={node?.id ?? "Voucher"} subtitle={q.data?.data ? `${q.data.data.voucherType} · ${fmtDate(q.data.data.date)}` : undefined} right={q.data?.status === "stale" ? <StaleChip reason={q.data.reason} /> : undefined}>
      <Boundary query={q} skeleton={<Skeleton className="h-[420px] w-full" />} emptyTitle="No voucher evidence for this selection">
        {(v) => (
          <div className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] gap-4">
            <div className="space-y-4">
              <section className="rounded-md border bg-card shadow-elegant">
                <div className="grid grid-cols-4 divide-x border-b">
                  {[
                    ["Total", fmtRs(v.total)],
                    ["Status", v.status],
                    ["Posted by", v.postedBy],
                    ["Source system", v.sourceSystem],
                  ].map(([k, val]) => (
                    <div key={k} className="px-4 py-3">
                      <div className="eyebrow">{k}</div>
                      <div className="text-[13.5px] font-semibold">{val}</div>
                    </div>
                  ))}
                </div>
                <div className="px-4 py-3 text-[12.5px] text-foreground/80">
                  <span className="text-muted-foreground">Narration · </span>
                  {v.narration}
                  <span className="ml-3 text-muted-foreground">Document · </span>
                  {v.documentRef}
                </div>
              </section>
              <section className="rounded-md border bg-card shadow-elegant">
                <div className="border-b px-4 py-2.5 text-[13px] font-semibold">Voucher lines</div>
                <table className="w-full text-[12.5px]" data-testid="voucher-lines">
                  <thead>
                    <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      <th className="px-4 py-2 font-semibold">Account</th>
                      <th className="px-2 py-2 font-semibold">Cost centre</th>
                      <th className="px-2 py-2 text-right font-semibold">Debit</th>
                      <th className="px-4 py-2 text-right font-semibold">Credit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {v.lines.map((l) => (
                      <tr key={l.account} className="border-b">
                        <td className="px-4 py-2"><span className="num font-medium">{l.account}</span> · {l.accountName}</td>
                        <td className="px-2 py-2 text-muted-foreground">{l.costCenter}</td>
                        <td className="num px-2 py-2 text-right">{l.debit ? fmtRs(l.debit) : DASH}</td>
                        <td className="num px-4 py-2 text-right">{l.credit ? fmtRs(l.credit) : DASH}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>
            <section className="rounded-md border bg-card shadow-elegant" data-testid="evidence">
              <div className="flex items-center gap-2 border-b px-4 py-2.5 text-[13px] font-semibold"><FileCheck2 className="h-4 w-4 text-primary" /> Source evidence</div>
              <dl className="grid grid-cols-1 gap-2.5 px-4 py-3 text-[12.5px]">
                {[
                  ["Source object", v.evidence.sourceObject],
                  ["Extraction batch", v.evidence.extractionBatch],
                  ["Row hash", v.evidence.rowHash],
                  ["Mapping status", v.evidence.mappingStatus],
                ].map(([k, val]) => (
                  <div key={k}>
                    <dt className="text-[11px] text-muted-foreground">{k}</dt>
                    <dd className="num font-medium">{val}</dd>
                  </div>
                ))}
              </dl>
              <div className="border-t px-4 py-3">
                <div className="eyebrow mb-1.5">Attachments</div>
                <ul className="space-y-1">
                  {v.evidence.attachments.map((a) => (
                    <li key={a.name} className="flex items-center gap-2 text-[12.5px]">
                      <Paperclip className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium">{a.name}</span>
                      <span className="text-muted-foreground">· {a.kind} · {a.size}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="border-t px-4 py-3">
                <div className="eyebrow mb-1.5">Audit trail</div>
                <ol className="space-y-1.5 border-l pl-3">
                  {v.evidence.trail.map((t) => (
                    <li key={t.at} className="text-[12px]">
                      <span className="num text-muted-foreground">{t.at}</span> · <span className="font-medium">{t.by}</span> — {t.action}
                    </li>
                  ))}
                </ol>
              </div>
            </section>
          </div>
        )}
      </Boundary>
    </PageFrame>
  );
}

function formatKpi(k: EntityProfile["kpis"][number]): string {
  if (k.value.value === null) return DASH;
  switch (k.unit) {
    case "cr":
      return fmtCr(k.value.value);
    case "pct":
      return fmtPct(k.value.value);
    case "days":
      return `${k.value.value} days`;
    default:
      return String(k.value.value);
  }
}

export function ProfilePage() {
  const { state } = useCfo();
  const { missing } = useDeepNode("profile");
  const q = useProfile(state.origin, state.nodes);
  if (missing) return <Navigate to="/" />;
  const p = q.data?.data;
  const max = p ? Math.max(...p.trend.map((t) => t.value), 1) : 1;
  return (
    <PageFrame eyebrow={p?.kind === "store" ? "Store profile" : p?.kind === "vendor" ? "Vendor profile" : "Profile"} title={p?.title ?? "Profile"} right={q.data?.status === "stale" ? <StaleChip reason={q.data.reason} /> : undefined}>
      <Boundary query={q} skeleton={<Skeleton className="h-[360px] w-full" />} emptyTitle="No profile for this selection">
        {(prof) => (
          <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] gap-4">
            <section className="rounded-md border bg-card shadow-elegant">
              <div className="grid grid-cols-3 divide-x divide-y">
                {prof.kpis.map((k) => (
                  <div key={k.label} className="px-4 py-3" data-testid={`kpi-${k.label}`}>
                    <div className="eyebrow">{k.label}</div>
                    <div className={cn("num-mono text-[20px] font-semibold", k.value.value === null ? "text-muted-foreground" : toneClass(k.tone) === "tone-neutral" ? "text-foreground" : toneClass(k.tone))}>
                      <Metric m={k.value} fmt={() => formatKpi(k)} />
                    </div>
                    {k.value.value === null && <div className="text-[11px] text-muted-foreground">{k.value.reason}</div>}
                  </div>
                ))}
              </div>
            </section>
            <div className="space-y-4">
              <section className="rounded-md border bg-card px-4 py-3 shadow-elegant">
                <div className="eyebrow mb-2">Details</div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12.5px]">
                  {prof.facts.map((f) => (
                    <div key={f.label}>
                      <dt className="text-[11px] text-muted-foreground">{f.label}</dt>
                      <dd className="font-medium">{f.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
              <section className="rounded-md border bg-card px-4 py-3 shadow-elegant">
                <div className="eyebrow mb-2">{prof.trendLabel}</div>
                <div className="flex h-32 items-end gap-3">
                  {prof.trend.map((t) => (
                    <div key={t.label} className="flex flex-1 flex-col items-center gap-1">
                      <span className="num text-[10.5px] text-muted-foreground">{t.value.toFixed(2)}</span>
                      <div className="w-full rounded-t bg-[oklch(0.35_0.1_255)]" style={{ height: `${(t.value / max) * 88}px` }} />
                      <span className="text-[10.5px] text-muted-foreground">{t.label}</span>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          </div>
        )}
      </Boundary>
    </PageFrame>
  );
}
