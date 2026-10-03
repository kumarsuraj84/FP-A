import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { useCreditors } from "@/api/hooks";
import { fmtCr } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Skeleton, StaleChip, toneClass } from "../common";
import { BasisDot, useRoomSelection } from "./parts";

const LABELS = ["Total creditors", "Currently due", "Overdue", ">90 days", ">180 days", ">365 days"];

/**
 * Screen A: one continuous creditor exposure strip. Every value is a filter: it narrows the whole page to that
 * ageing exposure. Movement is against the period opening (a balance has no budget to compare with here).
 */
export function ExposureStrip() {
  const q = useCreditors();
  const { age, select } = useRoomSelection();
  const grid = "grid grid-cols-6 divide-x @max-[900px]:grid-cols-3 @max-[900px]:divide-y";
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
  if (q.isError || q.data.status === "unavailable" || q.data.status === "empty" || !q.data.data) {
    const reason = q.isError ? "Could not load creditor exposure" : (q.data?.reason ?? "Awaiting finance mapping");
    return (
      <div data-testid={q.isError ? "state-error" : "state-unavailable"} className={cn("border-b bg-card", grid)}>
        {LABELS.map((l) => (
          <div key={l} className="px-4 py-3">
            <div className="eyebrow">{l}</div>
            <div className="num-mono text-[22px] font-semibold text-muted-foreground">—</div>
            <div className="text-[11px] text-muted-foreground">{reason}</div>
          </div>
        ))}
      </div>
    );
  }
  const o = q.data.data;
  return (
    <section aria-label="Creditor exposure" data-testid="exposure-strip" className="relative border-b bg-card">
      {q.data.status === "stale" && (
        <div className="absolute right-2 top-1 z-10">
          <StaleChip reason={q.data.reason} />
        </div>
      )}
      <div className={grid}>
        {o.headline.map((h) => {
          const active = age === h.id;
          const mv = h.movement.value;
          const Arrow = mv === null || mv === 0 ? Minus : mv > 0 ? ArrowUpRight : ArrowDownRight;
          // a growing old balance is a risk; a growing current balance is just activity
          const worse = h.id !== "all" && h.id !== "current" && (mv ?? 0) > 0;
          return (
            <button
              key={h.id}
              data-testid={`exposure-${h.id}`}
              aria-pressed={active}
              onClick={() => select(h.id)}
              title={h.basisDependent ? "Depends on the ageing basis, which is awaiting finance validation" : undefined}
              className={cn("press relative flex min-w-0 flex-col items-start gap-0.5 px-4 pb-2.5 pt-3 text-left hover:bg-[oklch(0.975_0.01_265)]", active && "bg-[oklch(0.95_0.025_265)] shadow-[inset_0_-2px_0_oklch(0.42_0.18_265)]")}
            >
              <span className="eyebrow">
                {h.label}
                <BasisDot show={h.basisDependent} />
              </span>
              <span className="num-mono whitespace-nowrap text-[22px] font-semibold leading-tight text-foreground">{h.value.value === null ? "—" : fmtCr(h.value.value)}</span>
              <span className={cn("num flex items-center gap-1 whitespace-nowrap text-[12px] font-semibold", mv === null ? "tone-neutral" : worse ? toneClass("bad") : toneClass("neutral"))}>
                <Arrow className="h-3.5 w-3.5" />
                {mv === null ? "—" : fmtCr(mv, { signed: true })}
                <span className="font-normal text-muted-foreground">vs opening</span>
              </span>
              <span className="text-[11px] text-muted-foreground">{active ? "Filtering the whole page" : "Click to filter the page"}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
