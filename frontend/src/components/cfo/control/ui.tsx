import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { ControlApiError, close } from "@/api/controlApi";

export const input = "w-full rounded border bg-card px-2 py-1 text-[12.5px] outline-none focus:ring-1 focus:ring-primary disabled:opacity-60";

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("grid gap-0.5 text-[11.5px] text-muted-foreground", className)}>
      <span className="font-semibold">{label}</span>
      {children}
      {hint && <span className="text-[10.5px] font-normal">{hint}</span>}
    </label>
  );
}

export function Btn({ children, onClick, disabled, tone = "default", testId, type = "button", title }: { children: ReactNode; onClick?: () => void; disabled?: boolean; tone?: "default" | "primary" | "danger"; testId?: string; type?: "button" | "submit"; title?: string }) {
  return (
    <button
      type={type}
      data-testid={testId}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "press rounded border px-2.5 py-1 text-[12px] font-semibold disabled:opacity-50",
        tone === "primary" && "border-primary bg-primary text-primary-foreground",
        tone === "danger" && "border-[oklch(0.7_0.12_25)] text-[oklch(0.45_0.15_25)]",
      )}
    >
      {children}
    </button>
  );
}

const PILL: Record<string, string> = {
  DRAFT: "bg-muted text-muted-foreground", REVIEW: "bg-[oklch(0.95_0.05_85)] text-[oklch(0.4_0.09_75)]", SUBMITTED: "bg-[oklch(0.95_0.05_85)] text-[oklch(0.4_0.09_75)]",
  APPROVED: "bg-[oklch(0.95_0.04_240)] text-[oklch(0.35_0.1_250)]", ACTIVE: "bg-[oklch(0.94_0.06_155)] text-[oklch(0.35_0.12_155)]",
  REJECTED: "bg-[oklch(0.95_0.04_25)] text-[oklch(0.45_0.15_25)]", WITHDRAWN: "bg-muted text-muted-foreground", REVERSED: "bg-muted text-muted-foreground",
  REVERSAL_REQUESTED: "bg-[oklch(0.95_0.05_85)] text-[oklch(0.4_0.09_75)]", SOURCE_REVIEW_REQUIRED: "bg-[oklch(0.95_0.04_25)] text-[oklch(0.45_0.15_25)]", SUPERSEDED_BY_SOURCE: "bg-muted text-muted-foreground",
  OPEN: "bg-[oklch(0.95_0.05_85)] text-[oklch(0.4_0.09_75)]", ACKNOWLEDGED: "bg-[oklch(0.95_0.04_240)] text-[oklch(0.35_0.1_250)]", RESOLVED: "bg-[oklch(0.94_0.06_155)] text-[oklch(0.35_0.12_155)]", CLOSED: "bg-muted text-muted-foreground",
  CRITICAL: "bg-[oklch(0.55_0.2_25)] text-white", HIGH: "bg-[oklch(0.7_0.15_55)] text-white", MEDIUM: "bg-[oklch(0.85_0.12_90)] text-[oklch(0.3_0.07_80)]", LOW: "bg-muted text-muted-foreground",
};
export const label = (s: string) => s.replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

export function Pill({ value, testId }: { value: string; testId?: string }) {
  return <span data-testid={testId} data-value={value} className={cn("inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[10.5px] font-bold tracking-wide", PILL[value] ?? "bg-muted text-muted-foreground")}>{label(value).toUpperCase()}</span>;
}

export function ErrMsg({ error }: { error: unknown }) {
  if (!error) return null;
  return <div role="alert" data-testid="control-error" className="rounded border border-[oklch(0.75_0.1_25)] bg-[oklch(0.97_0.03_25)] px-3 py-2 text-[12px] text-[oklch(0.4_0.15_25)]">{error instanceof ControlApiError || error instanceof Error ? error.message : "Something went wrong."}</div>;
}

/** A write: runs the call, then refreshes the named query families. Errors stay on the mutation so the page can show them. */
export function useWrite<A, R>(fn: (a: A) => Promise<R>, invalidate: string[], onDone?: (r: R) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async (r) => {
      await Promise.all(invalidate.map((k) => qc.invalidateQueries({ queryKey: [k] })));
      onDone?.(r);
    },
  });
}

export const cr = (v: string | number | null | undefined, signed = false) => {
  if (v === null || v === undefined || v === "") return "–";
  const n = Number(v);
  if (!Number.isFinite(n)) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  return `${n < 0 ? "-" : signed && n > 0 ? "+" : ""}${s}`;
};

export const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "–");

export function History({ events }: { events: { seq: number; event_type: string; comment: string | null; at: string; actor_email?: string | null; actor?: string | null }[] }) {
  return (
    <ol data-testid="history" className="space-y-1 text-[12px]">
      {events.map((e) => (
        <li key={e.seq} className="flex flex-wrap gap-x-2">
          <span className="num text-muted-foreground">{when(e.at)}</span>
          <span className="font-semibold">{label(e.event_type)}</span>
          <span className="text-muted-foreground">{e.actor_email ?? e.actor ?? ""}</span>
          {e.comment && <span>· {e.comment}</span>}
        </li>
      ))}
    </ol>
  );
}

/** Months that no longer accept changes. A soft-closed month still does (a controller approves it); management and final closed months are locked until a controller reopens them. */
export const LOCKED_STATUSES = ["MANAGEMENT_CLOSED", "FINAL_CLOSED"];

/** Whether the month is locked for this entity, read from the close calendar, so the form says so before anyone fills it in (the database refuses it anyway). */
export function usePeriodLock(entity: string, month: string) {
  const ok = /^\d{4}-\d{2}$/.test(month);
  const q = useQuery({ queryKey: ["close", "period", month], queryFn: () => close.periods(month, month), enabled: ok, staleTime: 15_000 });
  const row = q.data?.[0];
  const status = row ? (entity === "HOLDCO" ? row.holdco : row.subco) : "OPEN";
  return { status, locked: LOCKED_STATUSES.includes(status) };
}

export function PeriodLockNotice({ status, month }: { status: string; month: string }) {
  if (!LOCKED_STATUSES.includes(status)) return null;
  return (
    <div role="alert" data-testid="period-locked" className="rounded border border-[oklch(0.75_0.12_25)] bg-[oklch(0.97_0.03_25)] px-3 py-2 text-[12px] text-[oklch(0.4_0.15_25)]">
      {month} is {status === "FINAL_CLOSED" ? "final closed" : "management closed"} for this entity: nothing can be added or changed in it until a controller reopens the month (Month-end close).
    </div>
  );
}
