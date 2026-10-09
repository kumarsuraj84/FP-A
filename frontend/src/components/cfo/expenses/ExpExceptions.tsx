import { useState } from "react";
import { useExpExceptions } from "@/api/expensesLiveHooks";
import { DASH } from "@/lib/format";
import { ledgerListHref, type TrailItem } from "@/lib/entryLinks";
import { cn } from "@/lib/utils";
import type { ExpException, ExpQuery } from "@/types/expensesLive";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { AppLink } from "../entry/parts";
import { cr2, monthShort } from "../mgmt/mgmtFormat";

const SEV: Record<string, string> = {
  high: "border-[oklch(0.78_0.12_25)] bg-[oklch(0.97_0.03_25)] text-[oklch(0.45_0.15_25)]",
  medium: "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] text-[oklch(0.45_0.09_75)]",
  low: "border-border bg-muted text-muted-foreground",
};

function Actions({ e, next, onSite }: { e: ExpException; next: TrailItem[]; onSite: (e: ExpException) => void }) {
  const canVouchers = e.site_code !== null && e.ledger_code !== null;
  const month = e.rule_id === "DUPLICATE_BOOKING" ? e.month : null;
  return (
    <span className="inline-flex gap-1">
      {canVouchers && (
        <AppLink
          testId={`exc-vouchers-${e.rule_id}-${e.site_code}-${e.ledger_code}-${e.month ?? "p"}`}
          href={ledgerListHref({ site: String(e.site_code), glcode: String(e.ledger_code), from_month: month ?? e.from_month, to_month: month ?? e.to_month, entity: e.voucher_entity === "VENTURES" ? "VENTURES" : undefined, title: `${e.ledger_name} · ${e.site_name ?? `site ${e.site_code}`}` }, next)}
          className="press whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-semibold text-primary hover:bg-muted"
        >
          Vouchers
        </AppLink>
      )}
      {e.site_code !== null && (
        <button type="button" onClick={() => onSite(e)} className="press whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-semibold hover:bg-muted">Site ledgers</button>
      )}
    </span>
  );
}

/** Outliers and data-quality prompts, each with the rule that raised it. */
export function ExpExceptionsPanel({ q, next, onSite }: { q: ExpQuery; next: TrailItem[]; onSite: (e: ExpException) => void }) {
  const ex = useExpExceptions(q);
  const [rule, setRule] = useState("");
  return (
    <Panel testId="exp-exceptions" eyebrow="Exceptions" title="Outliers and things to check" right={ex.data ? <span className="text-[11.5px] text-muted-foreground" data-testid="exc-total">{ex.data.total} found</span> : undefined}>
      <LiveBoundary query={ex} skeleton={<Skeleton className="m-4 h-40" />}>
        {(d) => {
          const rows = d.exceptions.filter((e) => !rule || e.rule_id === rule);
          return (
            <>
              <div className="flex flex-wrap items-center gap-1.5 border-b px-4 py-2" data-testid="exc-rules">
                <button type="button" aria-pressed={rule === ""} onClick={() => setRule("")} className={cn("press rounded border px-2 py-0.5 text-[11.5px] font-medium", rule === "" ? "bg-foreground text-background" : "hover:bg-muted")}>All ({d.total})</button>
                {d.rules.map((r) => (
                  <button key={r.id} type="button" data-testid={`exc-rule-${r.id}`} aria-pressed={rule === r.id} title={r.text} onClick={() => setRule(rule === r.id ? "" : r.id)} className={cn("press rounded border px-2 py-0.5 text-[11.5px] font-medium", rule === r.id ? "bg-foreground text-background" : "hover:bg-muted")}>
                    {r.title} ({r.count})
                  </button>
                ))}
              </div>
              <ul className="divide-y border-b" data-testid="exc-rule-text">
                {d.rules.filter((r) => !rule || r.id === rule).map((r) => (
                  <li key={r.id} className="px-4 py-1.5 text-[11.5px] text-muted-foreground"><span className="font-semibold text-foreground">{r.title}.</span> {r.text}</li>
                ))}
              </ul>
              <div className="max-h-[60vh] overflow-auto">
                <table className="w-full min-w-[760px] text-[12.5px]" data-testid="exc-table">
                  <thead>
                    <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      <th className="px-4 py-2 font-semibold">Severity</th>
                      <th className="px-2 py-2 font-semibold">Site</th>
                      <th className="px-2 py-2 font-semibold">Head · ledger</th>
                      <th className="px-2 py-2 text-right font-semibold">INR Cr</th>
                      <th className="px-2 py-2 font-semibold">Why it is listed</th>
                      <th className="px-4 py-2 text-right font-semibold">Drill</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((e, i) => (
                      <tr key={`${e.rule_id}-${e.site_code}-${e.ledger_code}-${e.month}-${i}`} data-testid="exc-row" data-rule={e.rule_id} className="border-b align-top">
                        <td className="px-4 py-1.5"><span className={cn("rounded-sm border px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide", SEV[e.severity])}>{e.severity}</span></td>
                        <td className="px-2 py-1.5">{e.site_name ?? DASH}{e.site_code !== null && <span className="ml-1.5 text-[10.5px] text-muted-foreground">{e.site_code} · {e.entity === "HOLDCO" ? "HoldCo" : "SubCo"}</span>}</td>
                        <td className="px-2 py-1.5">{e.head_label ?? DASH}{e.ledger_name && <span className="block text-[11px] text-muted-foreground">{e.ledger_name}</span>}</td>
                        <td data-exact={String(e.amount_cr ?? "")} className="num-mono px-2 py-1.5 text-right">{cr2(e.amount_cr)}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">{e.metric}{e.month && e.rule_id !== "MOM_JUMP" ? <span> · {monthShort(e.month)}</span> : null}{e.likely_intercompany ? <span className="ml-1 rounded-sm border px-1 text-[10px] uppercase">intercompany?</span> : null}</td>
                        <td className="px-4 py-1.5 text-right"><Actions e={e} next={next} onSite={onSite} /></td>
                      </tr>
                    ))}
                    {rows.length === 0 && <tr><td colSpan={6} data-testid="exc-empty" className="px-4 py-6 text-center text-muted-foreground">Nothing raised by these rules for the period.</td></tr>}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-2 text-[11.5px] text-muted-foreground">{d.note}{d.truncated ? ` Showing the first ${d.exceptions.length} of ${d.total}, by severity then size.` : ""}</div>
            </>
          );
        }}
      </LiveBoundary>
    </Panel>
  );
}
