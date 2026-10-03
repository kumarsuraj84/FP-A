import { ArrowDownRight, ArrowRight, ArrowUpRight, Clock, Users } from "lucide-react";
import { useActions, useRisks } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { fmtBps, fmtCr } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { RiskPillar } from "@/types/cfo";
import { Boundary, Metric, SectionTitle, SEVERITY_STYLE, Skeleton, StaleChip } from "./common";

const EXPOSURE_LABEL: Record<RiskPillar["id"], string> = {
  liquidity: "Cash on hand",
  gm: "Est. FY impact",
  payables: "Owed over 180 days",
  advances: "Advances over 90 days",
  recon: "Awaiting reconciliation",
};

export function RiskLandscape() {
  const q = useRisks();
  const { state, openOrigin } = useCfo();
  return (
    <section aria-label="Risk landscape" data-testid="risk-landscape" className="@container rounded-md border bg-card shadow-elegant">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <SectionTitle eyebrow="Exposure" title="Risk landscape" />
        {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
      </div>
      <Boundary query={q} skeleton={<Skeleton className="m-4 h-[150px]" />} emptyTitle="No risk readings for this selection">
        {(pillars) => (
          <div className="grid grid-cols-5 divide-x @max-[1000px]:grid-cols-[repeat(5,minmax(150px,1fr))] @max-[1000px]:overflow-x-auto">
            {pillars.map((p) => {
              const sev = SEVERITY_STYLE[p.severity];
              const mv = p.movement.value;
              const bad = p.id === "gm" ? (mv ?? 0) < 0 : p.id === "liquidity" ? (mv ?? 0) < 0 : (mv ?? 0) > 0;
              const Arrow = mv === null || mv === 0 ? ArrowRight : (mv ?? 0) > 0 ? ArrowUpRight : ArrowDownRight;
              const active = state.origin?.source === "risk" && state.origin.id === p.origin.id;
              return (
                <button
                  key={p.id}
                  data-testid={`risk-${p.id}`}
                  aria-pressed={active}
                  onClick={() => openOrigin(p.origin)}
                  className={cn("press relative flex min-w-0 flex-col items-start gap-1 px-4 pb-3.5 pt-4 text-left hover:bg-[oklch(0.975_0.01_265)]", active && "bg-[oklch(0.95_0.025_265)]")}
                >
                  <span className={cn("absolute inset-x-0 top-0 h-1", sev.bar)} />
                  <span className="flex w-full items-center justify-between">
                    <span className="text-[13px] font-semibold text-foreground">{p.label}</span>
                    <span data-testid={`risk-sev-${p.id}`} className={cn("rounded-sm px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wide", sev.chip)}>
                      {sev.label}
                    </span>
                  </span>
                  <span className="num-mono mt-1 text-[24px] font-semibold leading-none text-foreground">
                    <Metric m={p.exposure} fmt={(n) => fmtCr(n)} />
                  </span>
                  <span className="text-[11px] text-muted-foreground">{p.diagnosticLabel === "Shortfall vs minimum" ? "Shortfall vs minimum" : EXPOSURE_LABEL[p.id]}</span>
                  <span className={cn("num mt-1 flex items-center gap-1 text-[12px] font-semibold", bad ? "tone-bad" : "tone-good")}>
                    <Arrow className="h-3.5 w-3.5" />
                    <Metric m={p.movement} fmt={(n) => (p.id === "gm" ? fmtBps(n) : fmtCr(n, { signed: true }))} />
                  </span>
                  <span className="mt-1.5 flex w-full items-baseline justify-between gap-2 border-t pt-1.5 text-[11.5px]">
                    <span className="truncate text-muted-foreground">{p.diagnosticLabel}</span>
                    <span className="num shrink-0 font-semibold text-foreground">{p.diagnosticValue}</span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </Boundary>
    </section>
  );
}

export function AttentionQueue() {
  const q = useActions();
  const { openOrigin } = useCfo();
  return (
    <section aria-label="Needs your attention" data-testid="attention" className="@container rounded-md border bg-card shadow-elegant">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <SectionTitle eyebrow="Decision queue" title="Needs your attention" />
        {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
      </div>
      <Boundary query={q} skeleton={<Skeleton className="m-4 h-[200px]" />} emptyTitle="Nothing needs your attention">
        {(actions) => (
          <ul className="divide-y">
            {actions.map((a) => {
              const sev = SEVERITY_STYLE[a.severity];
              return (
                <li key={a.id} data-testid={`action-${a.id}`} className="relative grid grid-cols-[minmax(260px,1.3fr)_110px_minmax(180px,1fr)_minmax(200px,1fr)_auto] items-center gap-x-5 gap-y-1 py-3 pl-5 pr-4 @max-[1150px]:grid-cols-[1fr_auto_auto]">
                  <span className={cn("absolute inset-y-0 left-0 w-1", sev.bar)} />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[14px] font-semibold text-foreground">{a.problem}</span>
                      <span className={cn("shrink-0 rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide", sev.chip)}>{sev.label}</span>
                    </div>
                    <div className="truncate text-[12px] text-muted-foreground">{a.driver}</div>
                  </div>
                  <div className="num-mono text-[17px] font-semibold text-foreground">
                    <Metric m={a.amount} fmt={(n) => fmtCr(n)} />
                  </div>
                  <div className="flex min-w-0 items-start gap-1.5 text-[12px] text-foreground/80 @max-[1150px]:col-span-3">
                    <Users className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span>{a.concentration}</span>
                  </div>
                  <div className="flex min-w-0 items-start gap-1.5 text-[12px] text-foreground/80 @max-[1150px]:col-span-3">
                    <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span>{a.age}</span>
                  </div>
                  <button
                    data-testid={`action-cta-${a.id}`}
                    onClick={() => openOrigin(a.origin)}
                    className="press inline-flex items-center gap-1.5 whitespace-nowrap rounded bg-primary px-3 py-1.5 text-[12.5px] font-semibold text-primary-foreground hover:bg-primary/90"
                  >
                    {a.cta} <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Boundary>
    </section>
  );
}
