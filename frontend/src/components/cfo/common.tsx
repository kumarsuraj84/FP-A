import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle, DatabaseZap, Inbox, RefreshCw, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { DASH } from "@/lib/format";
import type { Envelope, MetricValue, Severity, Tone } from "@/types/cfo";

export const toneClass = (t: Tone) => (t === "good" ? "tone-good" : t === "bad" ? "tone-bad" : t === "warn" ? "tone-warn" : "tone-neutral");

export const SEVERITY_STYLE: Record<Severity, { bar: string; chip: string; label: string }> = {
  critical: { bar: "bg-[oklch(0.55_0.22_25)]", chip: "bg-[oklch(0.95_0.04_25)] text-[oklch(0.45_0.2_25)]", label: "Critical" },
  high: { bar: "bg-[oklch(0.68_0.17_50)]", chip: "bg-[oklch(0.96_0.05_60)] text-[oklch(0.45_0.14_50)]", label: "High" },
  medium: { bar: "bg-[oklch(0.8_0.14_85)]", chip: "bg-[oklch(0.97_0.05_95)] text-[oklch(0.45_0.1_80)]", label: "Medium" },
  low: { bar: "bg-[oklch(0.7_0.14_155)]", chip: "bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]", label: "Low" },
};

/** Renders "—" with its reason whenever a metric is genuinely missing. Never zero. */
export function Metric({ m, fmt, className }: { m: MetricValue; fmt: (n: number) => string; className?: string }) {
  if (m.value === null) {
    return (
      <span className={cn("text-muted-foreground", className)} title={m.reason}>
        {DASH}
      </span>
    );
  }
  return <span className={className}>{fmt(m.value)}</span>;
}

export function SectionTitle({ eyebrow, title, right, className }: { eyebrow?: string; title: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h2 className="truncate text-[15px] font-semibold leading-tight tracking-tight text-foreground">{title}</h2>
      </div>
      {right}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-muted", className)} aria-hidden />;
}

function Notice({ icon, title, body, action, testId }: { icon: ReactNode; title: string; body?: string; action?: ReactNode; testId: string }) {
  return (
    <div data-testid={testId} className="flex min-h-[120px] w-full flex-col items-center justify-center gap-1.5 px-4 py-6 text-center">
      <div className="text-muted-foreground">{icon}</div>
      <div className="text-[13px] font-medium text-foreground">{title}</div>
      {body && <div className="max-w-sm text-xs text-muted-foreground">{body}</div>}
      {action}
    </div>
  );
}

export function StaleChip({ reason }: { reason?: string }) {
  return (
    <span
      data-testid="stale-chip"
      title={reason}
      className="inline-flex items-center gap-1 rounded-sm bg-[oklch(0.96_0.05_85)] px-1.5 py-0.5 text-[10.5px] font-medium text-[oklch(0.45_0.1_75)]"
    >
      <Clock className="h-3 w-3" /> Stale
    </span>
  );
}

interface BoundaryProps<T> {
  query: UseQueryResult<Envelope<T>>;
  skeleton?: ReactNode;
  emptyTitle?: string;
  children: (data: T, stale: boolean) => ReactNode;
}

/**
 * One boundary for every section: loading, error, unavailable, empty, stale.
 * Missing data is never rendered as zero.
 */
export function Boundary<T>({ query, skeleton, emptyTitle = "Nothing to show", children }: BoundaryProps<T>) {
  if (query.isPending) return <div data-testid="state-loading">{skeleton ?? <Skeleton className="h-32 w-full" />}</div>;
  if (query.isError) {
    return (
      <Notice
        testId="state-error"
        icon={<AlertTriangle className="h-5 w-5 text-[oklch(0.55_0.2_25)]" />}
        title="Could not load this section"
        body={(query.error as Error)?.message}
        action={
          <button onClick={() => query.refetch()} className="press mt-1 inline-flex items-center gap-1 rounded border bg-card px-2 py-1 text-xs font-medium hover:bg-muted">
            <RefreshCw className="h-3 w-3" /> Retry
          </button>
        }
      />
    );
  }
  const env = query.data;
  if (env.status === "unavailable") {
    return <Notice testId="state-unavailable" icon={<DatabaseZap className="h-5 w-5" />} title={`${DASH}  Unavailable`} body={env.reason ?? "Awaiting finance mapping"} />;
  }
  if (env.status === "empty" || env.data === undefined) {
    return <Notice testId="state-empty" icon={<Inbox className="h-5 w-5" />} title={emptyTitle} body={env.reason} />;
  }
  return <>{children(env.data, env.status === "stale")}</>;
}
