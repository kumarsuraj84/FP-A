import { CheckCircle2, ChevronRight, X } from "lucide-react";
import { useExpLedgers } from "@/api/expensesLiveHooks";
import { ledgerListHref, type TrailItem } from "@/lib/entryLinks";
import { cn } from "@/lib/utils";
import type { ExpLedgerRow, ExpLedgers, ExpQuery, SiteEntity, VoucherEntity } from "@/types/expensesLive";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { AppLink } from "../entry/parts";
import { cr2, monthShort, pct1 } from "../mgmt/mgmtFormat";
import type { ExpSearch } from "./expensesUrl";

/**
 * The drill to the last leg:  head -> ledgers -> site -> vouchers (/entry/list) -> voucher (/entry).
 * The state (head, ledger, site) lives in the page address; the links to the voucher pages carry this page as the first step of their trail,
 * so the user comes back to the same drill.
 */

const voucherEntity = (e: VoucherEntity | null | undefined): "VENTURES" | undefined => (e === "VENTURES" ? "VENTURES" : undefined);
const period = (d: ExpLedgers) => (d.from_month === d.to_month ? monthShort(d.from_month) : `${monthShort(d.from_month)} to ${monthShort(d.to_month)}`);

interface Props {
  q: ExpQuery;
  s: ExpSearch;
  headLabel: (key: string) => string;
  set: (patch: Partial<Record<keyof ExpSearch, string | number | undefined>>) => void;
  next: TrailItem[];
}

function Crumb({ children, onClick, current }: { children: React.ReactNode; onClick?: () => void; current?: boolean }) {
  return onClick && !current ? (
    <button type="button" onClick={onClick} className="press rounded px-1 py-0.5 text-primary hover:bg-muted">{children}</button>
  ) : (
    <span className={cn("px-1 py-0.5", current && "font-semibold text-foreground")}>{children}</span>
  );
}

function VoucherLink({ r, d, next, site, siteName, from, to }: { r: ExpLedgerRow; d: ExpLedgers; next: TrailItem[]; site: number | null; siteName?: string | null; from?: string; to?: string }) {
  const ent = voucherEntity(r.voucher_entity ?? (d.site_entity === "HOLDCO" ? "VENTURES" : undefined));
  const href = ledgerListHref(
    { site: site === null ? undefined : String(site), glcode: String(r.ledger_code), from_month: from ?? d.from_month, to_month: to ?? d.to_month, entity: ent, title: `${r.ledger_name}${siteName ? ` · ${siteName}` : site !== null ? ` · site ${site}` : ""}` },
    next,
  );
  return (
    <AppLink href={href} testId={`exp-vouchers-${r.ledger_code}${site !== null ? `-${site}` : ""}`} className="press whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-semibold text-primary hover:bg-muted">
      Vouchers
    </AppLink>
  );
}

function ReconChip({ d }: { d: ExpLedgers }) {
  if (d.reconciles === null) return <span className="text-[11.5px] text-muted-foreground">Showing the largest {d.rows.length} of {d.row_count}</span>;
  return (
    <span data-testid="exp-drill-reconciles" data-ok={String(d.reconciles)} className={cn("inline-flex items-center gap-1 text-[11.5px]", d.reconciles ? "text-[oklch(0.4_0.12_155)]" : "tone-bad")}>
      <CheckCircle2 className="h-3 w-3" /> {d.reconciles ? "Rows add up to the figure above" : "Rows do NOT add up to the figure above"}
    </span>
  );
}

function Table({ d, p }: { d: ExpLedgers; p: Props }) {
  const { s, set, next } = p;
  const bySite = d.grain === "site";
  const atSite = d.site !== null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-[12.5px]" data-testid="exp-drill-table">
        <thead>
          <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-2 font-semibold">{bySite ? "Site" : "Ledger"}</th>
            {!atSite && !bySite && <th className="px-2 py-2 text-right font-semibold">Sites</th>}
            <th className="px-2 py-2 text-right font-semibold">Lines</th>
            <th className="px-2 py-2 text-right font-semibold">Book, INR Cr</th>
            <th className="px-2 py-2 text-right font-semibold">Share</th>
            {d.rows.some((r) => r.pct_ns !== undefined && r.pct_ns !== null) && <th className="px-2 py-2 text-right font-semibold">% of revenue</th>}
            <th className="px-4 py-2 text-right font-semibold">Drill</th>
          </tr>
        </thead>
        <tbody>
          {d.rows.map((r) => {
            const key = bySite ? `${r.site_entity}:${r.site_code}` : `${r.ledger_code}`;
            return (
              <tr key={key} data-testid={`exp-drill-row-${key}`} data-exact={String(r.amount_cr)} className="border-b hover:bg-muted/40">
                <td className="px-4 py-1.5">
                  {bySite ? (
                    <>
                      {r.site_name ?? `Site ${r.site_code}`}<span className="ml-2 text-[10.5px] text-muted-foreground">{r.site_code} · {r.site_entity === "HOLDCO" ? "HoldCo" : "SubCo"}</span>
                    </>
                  ) : (
                    <>
                      {r.ledger_name}<span className="ml-2 text-[10.5px] text-muted-foreground">ledger {r.ledger_code}{atSite ? ` · ${r.head_label ?? p.headLabel(r.head)}` : ""}</span>
                    </>
                  )}
                </td>
                {!atSite && !bySite && <td className="num px-2 py-1.5 text-right text-muted-foreground">{r.sites}</td>}
                <td className="num px-2 py-1.5 text-right text-muted-foreground">{r.lines}</td>
                <td className="num-mono px-2 py-1.5 text-right">{cr2(r.amount_cr)}</td>
                <td className="num px-2 py-1.5 text-right text-muted-foreground">{pct1(r.share_pct)}</td>
                {d.rows.some((x) => x.pct_ns !== undefined && x.pct_ns !== null) && <td className="num px-2 py-1.5 text-right text-muted-foreground">{pct1(r.pct_ns ?? null)}</td>}
                <td className="whitespace-nowrap px-4 py-1.5 text-right">
                  {bySite ? (
                    <span className="inline-flex gap-1">
                      <VoucherLink r={r} d={d} next={next} site={r.site_code} siteName={r.site_name} />
                      <button type="button" data-testid={`exp-open-site-${r.site_code}`} onClick={() => set({ site: r.site_code ?? undefined, se: r.site_entity ?? undefined, sn: r.site_name ?? undefined, gl: undefined })} className="press rounded border px-1.5 py-0.5 text-[11px] font-semibold hover:bg-muted">All ledgers at site</button>
                    </span>
                  ) : atSite ? (
                    <VoucherLink r={r} d={d} next={next} site={d.site} siteName={s.sn} />
                  ) : (
                    <span className="inline-flex gap-1">
                      <button type="button" data-testid={`exp-by-site-${r.ledger_code}`} onClick={() => set({ gl: r.ledger_code, head: r.head })} className="press rounded border px-1.5 py-0.5 text-[11px] font-semibold text-primary hover:bg-muted">By site</button>
                      {r.voucher_entity && <VoucherLink r={r} d={d} next={next} site={null} />}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
          {d.rows.length === 0 && <tr><td colSpan={7} data-testid="exp-drill-empty" className="px-4 py-5 text-center text-muted-foreground">No ledger posting in this selection for the period.</td></tr>}
        </tbody>
        <tfoot>
          {d.adjustments.map((a) => (
            <tr key={a.id} data-testid={`exp-adj-${a.id}`} className="border-t bg-[oklch(0.97_0.05_85)]">
              <td className="px-4 py-1.5" colSpan={3}>
                <span className="font-medium">Management adjustment</span> · {monthShort(a.month)} · {a.rule}{a.note ? <span className="text-muted-foreground"> · {a.note}</span> : null}
                <span className="ml-2 rounded-sm border px-1 text-[10.5px] uppercase tracking-wide text-muted-foreground">{a.kind}{a.provisional ? " · provisional" : ""}</span>
              </td>
              <td className="num-mono px-2 py-1.5 text-right" data-exact={String(a.amount_cr)}>{cr2(a.amount_cr)}</td>
              <td colSpan={3} />
            </tr>
          ))}
          {d.allocated_adjustment && (
            <tr data-testid="exp-adj-allocated" className="border-t bg-[oklch(0.97_0.05_85)]">
              <td className="px-4 py-1.5" colSpan={3}>
                <span className="font-medium">Management adjustments allocated to this site</span><span className="text-muted-foreground"> · {d.allocated_adjustment.note}</span>
              </td>
              <td className="num-mono px-2 py-1.5 text-right" data-exact={String(d.allocated_adjustment.amount_cr)}>{cr2(d.allocated_adjustment.amount_cr)}</td>
              <td colSpan={3} />
            </tr>
          )}
          <tr className="border-t-2 bg-secondary font-semibold" data-testid="exp-drill-total" data-exact={String(d.children_sum.total)}>
            <td className="px-4 py-2" colSpan={3}>{bySite || d.adjustments.length || d.allocated_adjustment ? "Total (book" + (d.adjustments.length || d.allocated_adjustment ? " + adjustments" : "") + ")" : "Total (book)"}</td>
            <td className="num-mono px-2 py-2 text-right">{cr2(d.children_sum.total)}</td>
            <td colSpan={3} className="px-4 py-2 text-right text-[11.5px] font-normal text-muted-foreground">{`The figure it breaks down: ${cr2(d.parent.total)}`}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export function DrillPanel(p: Props) {
  const { q, s, set, headLabel } = p;
  const site = s.site ? Number(s.site) : undefined;
  const siteEntity: SiteEntity | undefined = s.se ?? (site !== undefined ? (q.entity === "holdco" ? "HOLDCO" : "SUBCO") : undefined);
  const gl = s.gl ? Number(s.gl) : undefined;
  const lq = s.head || site !== undefined || gl !== undefined ? { ...q, head: s.head, site: Number.isFinite(site) ? site : undefined, site_entity: site !== undefined ? siteEntity : undefined, glcode: gl !== undefined && site === undefined ? gl : undefined } : null;
  const ledgers = useExpLedgers(lq);
  if (!lq) return null;
  const title =
    site !== undefined ? `Ledgers at ${s.sn ?? `site ${site}`}${s.head ? ` · ${headLabel(s.head)}` : ""}` : gl !== undefined ? `Sites posting ledger ${gl}` : `${headLabel(s.head ?? "")}: the ledgers behind this head`;
  return (
    <Panel
      testId="exp-drill"
      eyebrow="Drill to the voucher"
      title={title}
      right={
        <div className="flex items-center gap-2">
          {ledgers.data && <ReconChip d={ledgers.data} />}
          <button type="button" aria-label="Close the drill" data-testid="exp-drill-close" onClick={() => set({ head: undefined, gl: undefined, site: undefined, se: undefined, sn: undefined })} className="press rounded border p-1 hover:bg-muted"><X className="h-3.5 w-3.5" /></button>
        </div>
      }
    >
      <nav aria-label="Drill path" data-testid="exp-drill-path" className="flex flex-wrap items-center gap-0.5 border-b px-3 py-1.5 text-[11.5px] text-muted-foreground">
        <Crumb onClick={() => set({ head: undefined, gl: undefined, site: undefined, se: undefined, sn: undefined })}>Heads</Crumb>
        {s.head && (<><ChevronRight className="h-3 w-3" /><Crumb current={site === undefined && gl === undefined} onClick={() => set({ gl: undefined, site: undefined, se: undefined, sn: undefined })}>{headLabel(s.head)}</Crumb></>)}
        {gl !== undefined && (<><ChevronRight className="h-3 w-3" /><Crumb current={site === undefined}>Ledger {gl} by site</Crumb></>)}
        {site !== undefined && (<><ChevronRight className="h-3 w-3" /><Crumb current>{s.sn ?? `Site ${site}`}</Crumb></>)}
        <ChevronRight className="h-3 w-3" /><span>Vouchers</span><ChevronRight className="h-3 w-3" /><span>Voucher</span>
      </nav>
      <LiveBoundary query={ledgers} skeleton={<Skeleton className="m-4 h-32" />}>
        {(d) => (
          <>
            <div className="border-b px-4 py-1.5 text-[11.5px] text-muted-foreground" data-testid="exp-drill-scope">{period(d)} · {d.entity === "consolidated" ? "both entities" : d.entity === "holdco" ? "HoldCo (Citykart Ventures)" : "SubCo (Citykart Stores)"} · {d.voucher_note}</div>
            <Table d={d} p={p} />
          </>
        )}
      </LiveBoundary>
    </Panel>
  );
}
