import type { DrillNode, DrillOrigin } from "@/types/cfo";
import { AGE_FILTER_LABELS, BUCKET_LABELS, type AbnormalCategory, type AgeFilter, type AgeingMovement } from "@/types/creditors";

/** The creditors room is a drill origin so it reuses breadcrumbs, URL replay, Back and the drawer. */
export const CREDITORS_ORIGIN: DrillOrigin = {
  source: "pulse",
  scope: "creditors",
  id: "room",
  label: "Creditors",
  family: "payables",
  amount: null,
  variance: null,
};

export const isCreditors = (o: DrillOrigin | null | undefined): boolean => o?.scope === "creditors";

/** Room-level age selection. Amounts are not carried; the page reads exposure from the API. */
export function ageNode(age: AgeFilter): DrillNode {
  return { level: "driver", dim: "Ageing bucket", id: `Ageing bucket:${age}`, label: AGE_FILTER_LABELS[age], amount: null, variance: null };
}

export function flowLabel(f: Pick<AgeingMovement, "fromBucket" | "toBucket">): string {
  const from = f.fromBucket === "new" ? "New invoices" : BUCKET_LABELS[f.fromBucket].replace(" days", "");
  const to = f.toBucket === "settled" ? "Settled" : f.toBucket === "adjusted" ? "Adjusted" : BUCKET_LABELS[f.toBucket].replace(" days", "");
  return `${from} → ${to}`;
}

export function flowNode(f: AgeingMovement): DrillNode {
  return { level: "driver", dim: "Migration", id: `Migration:${f.id}`, label: flowLabel(f), amount: f.movedExposure, variance: null };
}

export function abnormalNode(c: AbnormalCategory): DrillNode {
  return { level: "driver", dim: "Abnormal", id: `Abnormal:${c.id}`, label: c.label, amount: c.amount.value, variance: null };
}

export function vendorNode(vendorId: string, name: string, outstanding: number): DrillNode {
  return { level: "entity", dim: "Vendor", id: `Vendor:${vendorId}`, label: name, amount: outstanding, variance: null };
}

export const ageFilterOf = (n: DrillNode | undefined): AgeFilter | null => (n?.dim === "Ageing bucket" ? (n.id.slice("Ageing bucket:".length) as AgeFilter) : null);
export const vendorIdOf = (n: DrillNode | undefined): string | null => (n?.dim === "Vendor" ? n.id.slice("Vendor:".length) : null);
