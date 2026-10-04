import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { fmtCr } from "@/lib/format";
import type { Tone } from "@/types/cfo";
import { toneClass } from "./common";

/** Section card used across the Stage 3 / 4 workspaces. */
export function Panel({ eyebrow, title, right, children, testId, className }: { eyebrow?: string; title: ReactNode; right?: ReactNode; children: ReactNode; testId?: string; className?: string }) {
  return (
    <section data-testid={testId} className={cn("flex min-w-0 flex-col rounded-md border bg-card shadow-elegant", className)}>
      <div className="flex items-end justify-between gap-3 border-b px-4 py-2.5">
        <div className="min-w-0">
          {eyebrow && <div className="eyebrow">{eyebrow}</div>}
          <h2 className="truncate text-[14px] font-semibold tracking-tight text-foreground">{title}</h2>
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

/** Page header shared by the workspaces. */
export function WorkspaceHeader({ eyebrow, title, subtitle, left, right }: { eyebrow: string; title: ReactNode; subtitle?: ReactNode; left?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-5 py-3">
      <div className="min-w-0">
        {left}
        <div className="eyebrow">{eyebrow}</div>
        <h1 className="truncate text-[20px] font-semibold tracking-tight text-foreground">{title}</h1>
        {subtitle && <div className="text-[12px] text-muted-foreground">{subtitle}</div>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

/** A figure with a signed variance underneath it, optionally a button. */
export function StripCell({ label, value, sub, variance, tone, onClick, pressed, testId, valueClass }: { label: string; value: ReactNode; sub?: ReactNode; variance?: ReactNode; tone?: Tone; onClick?: () => void; pressed?: boolean; testId: string; valueClass?: string }) {
  const body = (
    <>
      <div className="eyebrow">{label}</div>
      <div className={cn("num-mono whitespace-nowrap text-[20px] font-semibold leading-tight", valueClass)}>{value}</div>
      {variance !== undefined && <div className={cn("num text-[11.5px] font-semibold", toneClass(tone ?? "neutral"))}>{variance}</div>}
      {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
    </>
  );
  return onClick ? (
    <button data-testid={testId} aria-pressed={pressed} onClick={onClick} className={cn("press px-4 py-3 text-left hover:bg-[oklch(0.97_0.012_265)]", pressed && "bg-[oklch(0.95_0.025_265)]")}>
      {body}
    </button>
  ) : (
    <div data-testid={testId} className="px-4 py-3">
      {body}
    </div>
  );
}

export function Chip({ children, color, className }: { children: ReactNode; color?: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-sm border bg-muted/60 px-1.5 py-0.5 text-[11px] font-semibold text-foreground/80", className)}>
      {color && <i className="h-2 w-2 rounded-full" style={{ background: color }} />}
      {children}
    </span>
  );
}

/** ₹ Cr movement that renders "—" when missing and signs positives. */
export const deltaCr = (v: number | null | undefined) => fmtCr(v, { signed: true });
