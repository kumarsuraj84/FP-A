import { useLiveSummary } from "@/api/creditorsLiveHooks";
import { toCr, num } from "@/api/creditorsLive";
import { fmtCr, fmtDate, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AgeFilter } from "@/types/creditors";
import type { LiveSummary } from "@/types/creditorsLive";
import { Skeleton } from "../common";
import { RelatedExcludedNote } from "../related/ExcludedNote";
import { useRoomSelection } from "./parts";

const LABELS = ["Credit Outstanding", "Creditor Debit Balance", "Past Due", "Due Date Unavailable", ">90 Days Document Age", ">180 Days Document Age"];
const grid = "grid grid-cols-6 divide-x @max-[900px]:grid-cols-3 @max-[900px]:divide-y";

interface Cell {
  id: string;
  filter: AgeFilter | null; // null = a fact, not a filter
  label: string;
  exact: string;
  sub: string;
  hint: string;
  tone?: "caution";
}

function cells(s: LiveSummary): Cell[] {
  const credit = num(s.credit_outstanding);
  const share = (m: string) => (credit ? fmtPct((num(m) / credit) * 100) : "—");
  const items = (n: number) => `${n.toLocaleString("en-IN")} item${n === 1 ? "" : "s"}`;
  return [
    { id: "credit", filter: "all", label: "Credit Outstanding", exact: s.credit_outstanding, sub: `${items(s.credit_items)} · ${s.credit_vendors.toLocaleString("en-IN")} vendors`, hint: "Sum of open credit balances in the four creditor ledgers. Debit balances are not netted off." },
    { id: "debit", filter: null, label: "Creditor Debit Balance", exact: s.creditor_debit_balance, sub: `${items(s.debit_items)} · ${s.debit_vendors.toLocaleString("en-IN")} vendors · Dr, not netted`, hint: "Debit balances sitting in creditor ledgers. Shown separately and not classified (not assumed to be vendor advances)." },
    { id: "past_due", filter: "past_due", label: "Past Due", exact: s.past_due_credit, sub: `${share(s.past_due_credit)} of credit · ${items(s.past_due_items)}`, hint: "Credit items whose stored due date is on or before the as-of date." },
    { id: "due_unavailable", filter: "due_unavailable", label: "Due Date Unavailable", exact: s.due_unavailable_credit, sub: `${share(s.due_unavailable_credit)} of credit · ${items(s.due_unavailable_items)}`, hint: "Credit items with no usable due date in the source. Not estimated and not counted as past due.", tone: "caution" },
    { id: "gt90", filter: "gt90", label: ">90 Days Document Age", exact: s.over_90_credit, sub: `${share(s.over_90_credit)} of credit · ${items(s.over_90_items)}`, hint: "Credit items whose document date is more than 90 days before the as-of date. This is document age, not due status." },
    { id: "gt180", filter: "gt180", label: ">180 Days Document Age", exact: s.over_180_credit, sub: `${share(s.over_180_credit)} of credit · ${items(s.over_180_items)}`, hint: "Credit items whose document date is more than 180 days before the as-of date." },
  ];
}

/**
 * The first real strip. Credit, debit and net are never blended: the signed net appears only as a context line.
 * Past Due is Due Status (stored due date); >90 / >180 are Document Age. They are different dimensions and are labelled as such.
 */
export function ExposureStrip() {
  const q = useLiveSummary();
  const { age, select } = useRoomSelection();
  if (q.isPending) {
    return (
      <div data-testid="state-loading" className={cn("border-b bg-card", grid)}>
        {LABELS.map((l) => (
          <div key={l} className="space-y-2 px-4 py-3">
            <Skeleton className="h-2.5 w-16" />
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-2.5 w-28" />
          </div>
        ))}
      </div>
    );
  }
  if (q.isError || !q.data) {
    return (
      <div data-testid="state-error" data-section="exposure-strip-error" className={cn("border-b bg-card", grid)}>
        {LABELS.map((l) => (
          <div key={l} className="px-4 py-3">
            <div className="eyebrow">{l}</div>
            <div className="num-mono text-[22px] font-semibold text-muted-foreground">—</div>
            <div className="text-[11px] text-muted-foreground">{(q.error as Error)?.message ?? "Could not load creditor exposure"}</div>
          </div>
        ))}
      </div>
    );
  }
  const s = q.data;
  const net = num(s.signed_net);
  return (
    <section aria-label="Creditor exposure" data-testid="exposure-strip" className="border-b bg-card">
      <div className={grid}>
        {cells(s).map((c) => {
          const active = c.filter !== null && age === c.filter && c.filter !== "all";
          const body = (
            <>
              <span className="eyebrow">{c.label}</span>
              <span data-testid={`exposure-${c.id}-value`} data-exact={c.exact} className="num-mono whitespace-nowrap text-[22px] font-semibold leading-tight text-foreground">
                {fmtCr(toCr(c.exact))}
              </span>
              <span className="num max-w-full truncate text-[11.5px] text-muted-foreground">{c.sub}</span>
              <span className="text-[11px] text-muted-foreground">{c.filter === null ? "Shown for information" : c.filter === "all" ? "The whole credit book" : active ? "Filtering the whole page" : "Click to filter the page"}</span>
            </>
          );
          const cls = cn("flex min-w-0 flex-col items-start gap-0.5 px-4 pb-2.5 pt-3 text-left", c.tone === "caution" && "bg-[oklch(0.99_0.012_90)]");
          return c.filter === null || c.filter === "all" ? (
            <div key={c.id} data-testid={`exposure-${c.id}`} title={c.hint} className={cls}>
              {body}
            </div>
          ) : (
            <button
              key={c.id}
              data-testid={`exposure-${c.id}`}
              aria-pressed={active}
              onClick={() => select(c.filter as AgeFilter)}
              title={c.hint}
              className={cn(cls, "press relative hover:bg-[oklch(0.975_0.01_265)]", active && "bg-[oklch(0.95_0.025_265)] shadow-[inset_0_-2px_0_oklch(0.42_0.18_265)]")}
            >
              {body}
            </button>
          );
        })}
      </div>
      <div data-testid="strip-context" className="num border-t bg-[oklch(0.985_0.006_265)] px-4 py-1.5 text-[11.5px] text-muted-foreground">
        As of {fmtDate(s.as_of_date)} · {s.item_rows.toLocaleString("en-IN")} open items across {s.vendors.toLocaleString("en-IN")} vendors · Signed net (Credit − Debit):{" "}
        <span data-exact={s.signed_net} className="font-semibold text-foreground">{fmtCr(toCr(s.signed_net), { signed: net > 0 })}</span> (a reference figure; debit balances are not netted into Credit Outstanding)
      </div>
      <RelatedExcludedNote excluded={s.related_party_excluded} />
    </section>
  );
}
