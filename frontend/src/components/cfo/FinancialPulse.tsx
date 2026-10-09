import { AlertTriangle, ArrowDownRight, ArrowUpRight, Minus, RefreshCw } from "lucide-react";
import { usePulse } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { fmtBps, fmtCr, fmtDate, fmtPct, stampText, DASH } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PulseMetric } from "@/types/cfo";
import { StaleChip, Skeleton, toneClass } from "./common";

const LABELS = ["Store till cash", "Revenue from operations", "Material Margin", "Store EBITDA", "Creditors", "Vendor Advances", "Unreconciled"];
const TONE_BAR: Record<string, string> = {
  good: "bg-[oklch(0.62_0.16_155)]",
  bad: "bg-[oklch(0.58_0.2_25)]",
  warn: "bg-[oklch(0.75_0.15_75)]",
  neutral: "bg-[oklch(0.8_0.01_260)]",
};

function Cell({ m, active, onClick }: { m: PulseMetric; active: boolean; onClick: () => void }) {
  const val = m.unit === "pct" ? fmtPct(m.value.value) : fmtCr(m.value.value);
  const mv = m.movement.value;
  const mvText = m.movementUnit === "bps" ? fmtBps(mv) : fmtCr(mv, { signed: true });
  const up = mv !== null && mv > 0;
  const Arrow = mv === null || mv === 0 ? Minus : up ? ArrowUpRight : ArrowDownRight;
  return (
    <button
      data-testid={`pulse-${m.id}`}
      aria-pressed={active}
      onClick={onClick}
      className={cn("press relative flex min-w-0 flex-col items-start gap-0.5 px-4 pb-2.5 pt-3 text-left hover:bg-[oklch(0.975_0.01_265)] @max-[1000px]:px-3", active && "bg-[oklch(0.95_0.025_265)] shadow-[inset_0_-2px_0_oklch(0.42_0.18_265)]")}
    >
      <span className={cn("absolute inset-x-0 top-0 h-[3px]", TONE_BAR[m.tone])} />
      <span className="eyebrow">{m.label}</span>
      <span className="num-mono whitespace-nowrap text-[22px] font-semibold leading-tight text-foreground @max-[1000px]:text-[17px]">{val}</span>
      <span className={cn("num flex items-center gap-1 whitespace-nowrap text-[12px] font-semibold @max-[1000px]:text-[11px]", toneClass(m.tone))}>
        <Arrow className="h-3.5 w-3.5" />
        {mvText}
        <span className="font-normal text-muted-foreground @max-[1500px]:hidden">{m.comparisonLabel}</span>
      </span>
      <span className="w-full truncate text-[11px] text-muted-foreground @max-[1000px]:hidden" title={m.status}>
        {m.status}
      </span>
      {m.source && (
        <span data-testid={`pulse-source-${m.id}`} data-source={m.source.id} className="w-full truncate text-[10px] text-muted-foreground/80 @max-[1000px]:hidden" title={stampText(m.source)}>
          {m.source.label} · {m.source.runId ?? "not read"} · {m.source.asOf ? fmtDate(m.source.asOf) : DASH}
        </span>
      )}
    </button>
  );
}

function Placeholder({ reason }: { reason: string }) {
  return (
    <>
      {LABELS.map((l) => (
        <div key={l} data-testid="pulse-placeholder" className="flex flex-col items-start gap-0.5 px-4 pb-2.5 pt-3">
          <span className="eyebrow">{l}</span>
          <span className="num-mono text-[22px] font-semibold leading-tight text-muted-foreground">{DASH}</span>
          <span className="text-[11px] text-muted-foreground">{reason}</span>
        </div>
      ))}
    </>
  );
}

export function FinancialPulse() {
  const q = usePulse();
  const { state, openOrigin, enterCreditors } = useCfo();
  const grid = "grid grid-cols-[repeat(7,minmax(0,1fr))] divide-x";
  let body;
  let stale = false;
  if (q.isPending) {
    body = (
      <div data-testid="state-loading" className={grid}>
        {LABELS.map((l) => (
          <div key={l} className="space-y-2 px-4 py-3">
            <Skeleton className="h-2.5 w-14" />
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-2.5 w-28" />
          </div>
        ))}
      </div>
    );
  } else if (q.isError) {
    body = (
      <div data-testid="state-error" className="flex items-center justify-center gap-3 px-4 py-5 text-[13px]">
        <AlertTriangle className="h-4 w-4 text-[oklch(0.55_0.2_25)]" /> Could not load the financial pulse
        <button onClick={() => q.refetch()} className="press inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium hover:bg-muted">
          <RefreshCw className="h-3 w-3" /> Retry
        </button>
      </div>
    );
  } else if (q.data.status === "unavailable" || q.data.status === "empty" || !q.data.data) {
    body = (
      <div data-testid="state-unavailable" className={grid}>
        <Placeholder reason={q.data.reason ?? "Awaiting finance mapping"} />
      </div>
    );
  } else {
    stale = q.data.status === "stale";
    body = (
      <div className={grid}>
        {q.data.data.map((m) => (
          <Cell key={m.id} m={m} active={state.origin?.source === "pulse" && state.origin.id === m.origin.id} onClick={() => (m.target ? enterCreditors(m.target) : openOrigin(m.origin, m.heroTab))} />
        ))}
      </div>
    );
  }
  return (
    <section aria-label="Financial pulse" data-testid="financial-pulse" className="@container relative border-b bg-card">
      {stale && (
        <div className="absolute right-2 top-1 z-10">
          <StaleChip reason={q.data?.reason} />
        </div>
      )}
      {body}
    </section>
  );
}
