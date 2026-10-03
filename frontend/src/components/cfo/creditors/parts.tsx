import { FlaskConical } from "lucide-react";
import { useCfo } from "@/context/CfoContext";
import { ageFilterOf, ageNode } from "@/lib/creditorNodes";
import { cn } from "@/lib/utils";
import type { AgeFilter, AgeingBasis, BucketId } from "@/types/creditors";

export const BUCKET_ORDER: BucketId[] = ["b0_30", "b31_60", "b61_90", "b91_180", "b181_365", "b365p"];

/** Cool → hot: the same colour always means the same age, everywhere on the page. */
const HUES = ["oklch(0.66 0.1 205)", "oklch(0.66 0.11 170)", "oklch(0.7 0.12 130)", "oklch(0.76 0.14 88)", "oklch(0.66 0.17 48)", "oklch(0.52 0.2 25)"];
export const bucketColor = (id: BucketId) => HUES[BUCKET_ORDER.indexOf(id)];

/** Subtle development indicator: the ageing-date basis has not been validated by finance. */
export function AgeingBasisNote({ basis, className }: { basis: AgeingBasis; className?: string }) {
  if (basis.confirmed) {
    return <span className={cn("text-[11px] text-muted-foreground", className)}>Ageing basis: {basis.label}</span>;
  }
  return (
    <span
      data-testid="ageing-basis-note"
      title={`Candidates: ${basis.candidates.map((c) => c.replace("_", " ")).join(" or ")}. Buckets currently place documents by ${basis.provisional?.replace("_", " ") ?? "an unconfirmed date"} (provisional).`}
      className={cn("inline-flex items-center gap-1 rounded-sm border border-dashed border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] px-1.5 py-0.5 text-[10.5px] font-medium text-[oklch(0.45_0.09_75)]", className)}
    >
      <FlaskConical className="h-3 w-3" />
      {basis.label}
    </span>
  );
}

/** Marks a figure whose meaning depends on the unconfirmed ageing basis. */
export function BasisDot({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span data-testid="basis-dot" title="Depends on the ageing basis, which is awaiting finance validation" className="ml-1 inline-block h-1.5 w-1.5 rounded-full border border-[oklch(0.7_0.12_80)] bg-[oklch(0.96_0.06_90)] align-middle" />
  );
}

/** Current age selection in the room (a node in the drill path), and how to change it. */
export function useRoomSelection() {
  const { state, selectFilter, pushNode, pushNodes } = useCfo();
  const first = state.nodes[0];
  const age: AgeFilter = ageFilterOf(first) ?? "all";
  const select = (id: AgeFilter) => {
    // clicking the active selection (or "all") clears it
    selectFilter(id === "all" || id === age ? null : ageNode(id));
  };
  return { state, age, select, selectFilter, pushNode, pushNodes, hasFlow: first?.dim === "Migration" || first?.dim === "Abnormal" };
}
