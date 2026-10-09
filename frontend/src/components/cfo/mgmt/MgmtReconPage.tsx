import { useState } from "react";
import { CheckCircle2, TriangleAlert } from "lucide-react";
import { useMgmtReconciliation } from "@/api/mgmtLiveHooks";
import { DASH } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { MgmtReconCell } from "@/types/mgmtLive";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { MgmtFrame, MonthRange, WarningsBanner, fyYtdRange } from "./MgmtFrame";
import { useMgmtEntity } from "./mgmtEntity";
import { cr2, cr3, monthShort, toneOf } from "./mgmtFormat";

/**
 * Portal against the published finance MIS, by line and month. A month is TIED when every line ties; a line that does not tie is coloured as an
 * exception, and where the MIS sheet carries a hard-coded override the reason is shown next to the variance. The bridge below walks the portal's
 * books-only Corporate EBITDA to the MIS number.
 */
export function StatusPill({ status }: { status: "TIED" | "VARIANCE" | string }) {
  const tied = status === "TIED";
  return (
    <span data-testid="status-pill" data-status={status} className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wide", tied ? "bg-[oklch(0.94_0.06_155)] text-[oklch(0.32_0.1_155)]" : "bg-[oklch(0.58_0.2_25)] text-white")}>
      {tied ? <CheckCircle2 className="h-3 w-3" /> : <TriangleAlert className="h-3 w-3" />}
      {status}
    </span>
  );
}

function VarianceCell({ lineKey, month, c }: { lineKey: string; month: string; c: MgmtReconCell | undefined }) {
  if (!c) return <td data-testid={`recon-${lineKey}-${month}`} title="The API returned no reconciliation for this month" className="px-3 py-1.5 text-right text-muted-foreground">{DASH}</td>;
  return (
    <td
      data-testid={`recon-${lineKey}-${month}`}
      data-tied={c.tied}
      data-exact={c.variance === null ? "" : String(c.variance)}
      title={`MIS ${cr2(c.mis)} · Portal ${cr2(c.portal)} · Variance ${cr3(c.variance)}${c.override_reason ? ` · ${c.override_reason}` : ""}`}
      className={cn("whitespace-nowrap px-3 py-1.5 text-right align-top", !c.tied && "bg-[oklch(0.97_0.03_25)]")}
    >
      <div className={cn("num-mono", c.tied ? "text-muted-foreground" : "font-semibold tone-bad")}>{c.variance === null ? <span title="No variance can be computed: one side is missing">{DASH}</span> : c.tied ? "tied" : cr3(c.variance)}</div>
      <div className="num-mono text-[10.5px] text-muted-foreground">{cr2(c.mis)} / {cr2(c.portal)}</div>
      {c.override_reason && <div data-testid={`override-${lineKey}-${month}`} className="mt-0.5 max-w-[11rem] whitespace-normal text-left text-[10.5px] italic leading-snug text-[oklch(0.45_0.09_75)]">{c.override_reason}</div>}
    </td>
  );
}

function ReconBody({ months }: { months: string[] }) {
  const [from, setFrom] = useState(fyYtdRange(months)[0]);
  const [to, setTo] = useState(fyYtdRange(months)[1]);
  const entity = useMgmtEntity();
  const rec = useMgmtReconciliation(from || undefined, to || undefined, entity);
  return (
    <>
      <div data-testid="mgmt-controls" className="flex flex-wrap items-center gap-3 border-b bg-card px-5 py-2 text-[12px]">
        <MonthRange months={months} from={from} to={to} onChange={(f, t) => { setFrom(f); setTo(t); }} />
        <span className="text-[11.5px] text-muted-foreground">Each cell: variance (portal minus MIS), then MIS / portal in INR Cr.</span>
      </div>
      <LiveBoundary query={rec} skeleton={<Skeleton className="m-4 h-[420px]" />}>
        {(d) => {
          const cols = d.months.map((m) => m.month);
          const overrides = d.lines.flatMap((l) => cols.filter((m) => l.values[m]?.override_reason).map((m) => ({ key: `${l.key}-${m}`, line: l.label, month: m, reason: l.values[m].override_reason as string, variance: l.values[m].variance })));
          const tiedCount = d.months.filter((m) => m.status === "TIED").length;
          return (
            <>
              <WarningsBanner warnings={d.warnings.filter((w) => w.trim().length > 0)} />
              <section aria-label="Month status" data-testid="recon-months" className="flex flex-wrap items-center gap-2 border-b bg-card px-5 py-3">
                <span className="eyebrow mr-1">{tiedCount} of {d.months.length} months tied</span>
                {d.months.map((m) => (
                  <span key={m.month} data-testid={`recon-month-${m.month}`} className="inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[12px]">
                    {monthShort(m.month)} <StatusPill status={m.status} />
                  </span>
                ))}
              </section>
              <div className="p-3">
                <Panel testId="recon-panel" eyebrow="Portal vs published MIS" title="Variance by line and month (INR Cr)">
                  <div className="max-h-[70vh] overflow-auto">
                    <table className="w-full min-w-[720px] border-separate border-spacing-0 text-[12.5px]" data-testid="recon-table">
                      <thead>
                        <tr className="text-[10.5px] uppercase tracking-wider text-muted-foreground">
                          <th className="sticky left-0 top-0 z-30 border-b border-r bg-card px-3 py-2 text-left font-semibold">Line</th>
                          {cols.map((m) => <th key={m} className="sticky top-0 z-20 whitespace-nowrap border-b bg-card px-3 py-2 text-right font-semibold">{monthShort(m)}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {d.lines.map((l) => (
                          <tr key={l.key} data-testid={`recon-row-${l.key}`} className="border-b">
                            <th scope="row" className="sticky left-0 z-10 whitespace-nowrap border-b border-r bg-card px-3 py-1.5 text-left align-top font-normal">{l.label}</th>
                            {cols.map((m) => <VarianceCell key={m} lineKey={l.key} month={m} c={l.values[m]} />)}
                          </tr>
                        ))}
                        {d.lines.length === 0 && <tr><td colSpan={cols.length + 1} data-testid="recon-empty" className="px-4 py-6 text-center text-muted-foreground">No reconciliation lines for these months.</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              </div>
              {overrides.length > 0 && (
                <div className="px-3 pb-3">
                  <Panel testId="recon-overrides" eyebrow="Explained variances" title="Where the MIS sheet differs from its own ledger">
                    <ul className="divide-y text-[12px]">
                      {overrides.map((o) => (
                        <li key={o.key} className="flex flex-wrap items-baseline gap-x-3 px-4 py-1.5" data-testid={`override-item-${o.key}`}>
                          <span className="font-semibold">{o.line} · {monthShort(o.month)}</span>
                          <span className={cn("num-mono", toneOf(o.variance))}>{cr3(o.variance)}</span>
                          <span className="text-muted-foreground">{o.reason}</span>
                        </li>
                      ))}
                    </ul>
                  </Panel>
                </div>
              )}
              <div className="px-3 pb-6">
                <Panel testId="bridge-panel" eyebrow="Bridge" title="From portal books to the MIS: Corporate EBITDA (INR Cr)">
                  <div className="overflow-x-auto">
                    <table className="w-full text-[12.5px]" data-testid="bridge-table">
                      <thead>
                        <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                          <th className="px-4 py-2 font-semibold">Step</th>
                          <th className="px-3 py-2 text-right font-semibold">INR Cr</th>
                          <th className="px-3 py-2 font-semibold">Nature</th>
                          <th className="px-3 py-2 font-semibold">Note</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.bridge.map((b, i) => {
                          const sub = b.step.trim().startsWith("=") || /^subtotal$/i.test(b.nature);
                          return (
                            <tr key={`${i}-${b.step}`} data-testid={`bridge-${i}`} data-subtotal={sub} className={cn("border-b last:border-0", sub && "bg-[oklch(0.975_0.008_265)] font-semibold")}>
                              <td className="px-4 py-1.5">{b.step}</td>
                              <td data-exact={b.cr === null ? "" : String(b.cr)} title={b.cr === null ? "The API returned no amount for this step" : undefined} className={cn("num-mono whitespace-nowrap px-3 py-1.5 text-right", !sub && toneOf(b.cr))}>{b.cr === null ? DASH : sub ? cr2(b.cr) : cr2(b.cr)}</td>
                              <td className="px-3 py-1.5 text-muted-foreground">{b.nature}</td>
                              <td className="px-3 py-1.5 text-muted-foreground">{b.note}</td>
                            </tr>
                          );
                        })}
                        {d.bridge.length === 0 && <tr><td colSpan={4} data-testid="bridge-empty" className="px-4 py-6 text-center text-muted-foreground">No bridge is available for these months.</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              </div>
            </>
          );
        }}
      </LiveBoundary>
    </>
  );
}

export function MgmtReconPage() {
  return (
    <MgmtFrame active="recon" subtitle="The portal's management P&L against the published finance MIS, line by line and month by month, with the bridge that explains the gap. INR Cr.">
      {(months) => <ReconBody months={months} />}
    </MgmtFrame>
  );
}
