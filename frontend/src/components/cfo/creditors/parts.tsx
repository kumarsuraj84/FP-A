import type { ReactNode } from "react";
import { AlertTriangle, DatabaseZap, FlaskConical, RefreshCw } from "lucide-react";
import { Skeleton } from "../common";
import { useCfo } from "@/context/CfoContext";
import { ageFilterOf, ageNode } from "@/lib/creditorNodes";
import { cn } from "@/lib/utils";
import type { AgeFilter, BucketId } from "@/types/creditors";
import type { DataState } from "@/types/creditorsLive";

export const BUCKET_ORDER: BucketId[] = ["b0_30", "b31_60", "b61_90", "b91_180", "b181_365", "b365p"];

/** Cool → hot: the same colour always means the same age, everywhere on the page. */
const HUES = ["oklch(0.66 0.1 205)", "oklch(0.66 0.11 170)", "oklch(0.7 0.12 130)", "oklch(0.76 0.14 88)", "oklch(0.66 0.17 48)", "oklch(0.52 0.2 25)"];
export const bucketColor = (id: BucketId) => HUES[BUCKET_ORDER.indexOf(id)];

/** Due Status is its own dimension, so it has its own colours (never the age hues). */
export const DUE_ORDER = ["NOT_YET_DUE", "PAST_DUE_OR_DUE_TODAY", "DUE_UNAVAILABLE", "DUE_INVALID"] as const;
export const DUE_COLOR: Record<string, string> = {
  NOT_YET_DUE: "oklch(0.62 0.1 190)",
  PAST_DUE_OR_DUE_TODAY: "oklch(0.55 0.19 25)",
  DUE_UNAVAILABLE: "oklch(0.72 0.03 260)",
  DUE_INVALID: "oklch(0.6 0.12 320)",
};
export const DUE_FILTER: Record<string, AgeFilter> = { NOT_YET_DUE: "not_yet_due", PAST_DUE_OR_DUE_TODAY: "past_due", DUE_UNAVAILABLE: "due_unavailable", DUE_INVALID: "due_invalid" };

const STATE_STYLE: Record<DataState, string> = {
  verified_candidate: "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] text-[oklch(0.45_0.09_75)]",
  live: "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]",
  superseded: "border-border bg-muted text-muted-foreground",
  withdrawn: "border-[oklch(0.8_0.1_25)] bg-[oklch(0.95_0.04_25)] text-[oklch(0.45_0.2_25)]",
};
const STATE_TEXT: Record<DataState, string> = { verified_candidate: "Verified candidate · not live", live: "Live", superseded: "Superseded", withdrawn: "Withdrawn" };

/** "04 Oct 2026" from an ISO date. */
const longDate = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

/** The data state is stated by the API; this only displays it. A candidate is real, reconciled data that has not been published. */
export function DataStateBadge({ state, run, asOf, className }: { state: DataState; run: string; asOf: string; className?: string }) {
  return (
    <span
      data-testid="data-state"
      data-state={state}
      title={`Run ${run} · data as of ${asOf}. ${state === "verified_candidate" ? "Reconciled against the source, awaiting promotion." : ""}`}
      className={cn("inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-[11px] font-semibold", STATE_STYLE[state], className)}
    >
      <FlaskConical className="h-3 w-3" />
      <span className="rounded-sm bg-foreground px-1 text-[10px] font-bold tracking-wider text-background">REAL DATA</span>
      {STATE_TEXT[state]}
      <span className="font-normal opacity-80">· As of {longDate(asOf)} · {run}</span>
    </span>
  );
}

/** Loading / error / ready for a live section (no demo-envelope semantics: an API failure is shown, never papered over). */
export function LiveBoundary<T>({ query, skeleton, children }: { query: { isPending: boolean; isError: boolean; error: unknown; data: T | undefined; refetch: () => unknown }; skeleton?: ReactNode; children: (d: T) => ReactNode }) {
  if (query.isPending) return <div data-testid="state-loading">{skeleton ?? <Skeleton className="h-32 w-full" />}</div>;
  if (query.isError || query.data === undefined) {
    return (
      <div data-testid="state-error" className="flex min-h-[120px] w-full flex-col items-center justify-center gap-1.5 px-4 py-6 text-center">
        <AlertTriangle className="h-5 w-5 text-[oklch(0.55_0.2_25)]" />
        <div className="text-[13px] font-medium">Could not load this section</div>
        <div className="max-w-sm text-xs text-muted-foreground">{(query.error as Error)?.message ?? "The Creditors API did not respond"}</div>
        <button onClick={() => query.refetch()} className="press mt-1 inline-flex items-center gap-1 rounded border bg-card px-2 py-1 text-xs font-medium hover:bg-muted">
          <RefreshCw className="h-3 w-3" /> Retry
        </button>
      </div>
    );
  }
  return <>{children(query.data)}</>;
}

/** A section the verified extract cannot support yet: said plainly, with the reason, never a fake zero. */
export function NotAvailable({ title, reason, testId }: { title: string; reason: string; testId?: string }) {
  return (
    <div data-testid={testId} className="flex items-start gap-3 px-4 py-4 text-[12.5px]">
      <DatabaseZap className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div>
        <div className="font-semibold text-foreground">{title}</div>
        <div className="mt-0.5 max-w-2xl text-muted-foreground">{reason}</div>
      </div>
    </div>
  );
}

/** Current selection in the room (a node in the drill path), and how to change it. */
export function useRoomSelection() {
  const { state, selectFilter, pushNode, pushNodes } = useCfo();
  const first = state.nodes[0];
  const raw: AgeFilter = ageFilterOf(first) ?? "all";
  // links written for the demo service: age-based "current / overdue" no longer exist; map to the Due Status they came closest to
  const age: AgeFilter = raw === "overdue" ? "past_due" : raw === "current" ? "not_yet_due" : raw;
  const select = (id: AgeFilter) => {
    // clicking the active selection (or "all") clears it
    selectFilter(id === "all" || id === age ? null : ageNode(id));
  };
  return { state, age, select, selectFilter, pushNode, pushNodes };
}
