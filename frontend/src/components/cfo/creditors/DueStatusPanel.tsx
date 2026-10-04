import { useLiveDueStatus, useLiveSummary } from "@/api/creditorsLiveHooks";
import { fmtRupees, num, toCr } from "@/api/creditorsLive";
import { fmtCr, fmtDate, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DueStateRow } from "@/types/creditorsLive";
import { Skeleton } from "../common";
import { DUE_COLOR, DUE_FILTER, DUE_ORDER, LiveBoundary, useRoomSelection } from "./parts";

const NOTE: Record<string, string> = {
  NOT_YET_DUE: "Stored due date is after the as-of date.",
  PAST_DUE_OR_DUE_TODAY: "Stored due date is on or before the as-of date.",
  DUE_UNAVAILABLE: "No due date in the source. Reported as unavailable; never estimated or assumed past due.",
  DUE_INVALID: "A due date exists but is outside the valid window or earlier than the document.",
};

/** Due Status: what the source says about when payment is due. Independent of Document Age. */
export function DueStatusPanel() {
  const q = useLiveDueStatus();
  const sum = useLiveSummary();
  const { age, select } = useRoomSelection();
  return (
    <section aria-label="Due status" data-testid="due-status" className="rounded-md border bg-card shadow-elegant">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b px-4 py-3">
        <div>
          <div className="eyebrow">Due Status · from the stored due date only</div>
          <h2 className="text-[15px] font-semibold tracking-tight">What does the source say is due?</h2>
        </div>
        {sum.data && <span className="text-[11.5px] text-muted-foreground">As of {fmtDate(sum.data.as_of_date)}</span>}
      </div>
      <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[200px]" />}>
        {(rows: DueStateRow[]) => {
          const by = new Map(rows.map((r) => [r.state, r]));
          const credit = rows.reduce((a, r) => a + num(r.credit_outstanding), 0);
          const max = Math.max(...rows.map((r) => num(r.credit_outstanding)), 1e-9);
          return (
            <ul data-testid="due-list">
              {DUE_ORDER.map((k) => by.get(k))
                .filter((r): r is DueStateRow => !!r)
                .map((r) => {
                  const f = DUE_FILTER[r.state];
                  const active = age === f;
                  const empty = r.credit_items === 0 && r.debit_items === 0;
                  return (
                    <li key={r.state}>
                      <button
                        data-testid={`due-${r.state}`}
                        aria-pressed={active}
                        disabled={empty}
                        onClick={() => select(f)}
                        className={cn(
                          "press grid w-full grid-cols-[minmax(0,1.5fr)_minmax(0,3fr)_110px_90px_70px_140px] items-center gap-x-3 border-b px-4 py-2.5 text-left last:border-b-0 hover:bg-[oklch(0.97_0.012_265)] disabled:cursor-default disabled:opacity-60 @max-[1000px]:grid-cols-[minmax(0,1.5fr)_minmax(0,2fr)_110px]",
                          active && "bg-[oklch(0.95_0.025_265)]",
                        )}
                      >
                        <span className="min-w-0">
                          <span className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
                            <i className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: DUE_COLOR[r.state] }} />
                            {r.label}
                          </span>
                          <span className="block truncate text-[11px] text-muted-foreground" title={NOTE[r.state]}>{NOTE[r.state]}</span>
                        </span>
                        <span className="h-3 overflow-hidden rounded-sm bg-muted/60" aria-hidden>
                          <span className="block h-full rounded-sm" style={{ width: `${(num(r.credit_outstanding) / max) * 100}%`, background: DUE_COLOR[r.state] }} />
                        </span>
                        <span data-exact={r.credit_outstanding} className="num text-right text-[14px] font-semibold">{fmtCr(toCr(r.credit_outstanding))}</span>
                        <span className="num text-right text-[12px] text-muted-foreground @max-[1000px]:hidden">{credit ? fmtPct((num(r.credit_outstanding) / credit) * 100) : "—"} of credit</span>
                        <span className="num text-right text-[12px] text-muted-foreground @max-[1000px]:hidden">{r.credit_items.toLocaleString("en-IN")} items</span>
                        <span className="num text-right text-[11.5px] text-muted-foreground @max-[1000px]:hidden" title={fmtRupees(r.debit_balance)}>
                          {r.debit_items > 0 ? `Dr ${fmtCr(toCr(r.debit_balance))} · ${r.debit_items}` : "no debit items"}
                        </span>
                      </button>
                    </li>
                  );
                })}
            </ul>
          );
        }}
      </LiveBoundary>
      <div className="border-t px-4 py-2 text-[10.5px] text-muted-foreground">Due Status and Document Age are separate: an old document can still be not yet due, and a recent one can be past due. Click a status to filter the vendor sections.</div>
    </section>
  );
}
