import type { DrillNode, DrillOrigin } from "@/types/cfo";
import { QUADRANT_META, type QuadrantId, type StoreDot, type StoreMovement } from "@/types/profitability";

/** The Profitability portfolio is a drill origin, so breadcrumbs, URL replay, Back and the drawer all just work. */
export const PROFIT_ORIGIN: DrillOrigin = {
  source: "pulse",
  scope: "profitability",
  id: "portfolio",
  label: "Profitability",
  family: "margin",
  amount: null,
  variance: null,
};

export const isProfitability = (o: DrillOrigin | null | undefined): boolean => o?.scope === "profitability";

export function quadrantNode(q: QuadrantId): DrillNode {
  return { level: "driver", dim: "Quadrant", id: `Quadrant:${q}`, label: QUADRANT_META[q].label, amount: null, variance: null };
}

export function storeNode(s: Pick<StoreDot, "id" | "name" | "contribution" | "contributionVsComparison">): DrillNode {
  return { level: "entity", dim: "Store", id: `Store:${s.id}`, label: s.name, amount: s.contribution, variance: s.contributionVsComparison };
}

export function movementNode(m: StoreMovement): DrillNode {
  return { level: "driver", dim: "Movement", id: `Movement:${m.id}`, label: m.label, amount: m.amount, variance: m.kind === "impact" ? m.amount : null };
}

export const quadrantOf = (n: DrillNode | undefined): QuadrantId | null => (n?.dim === "Quadrant" ? (n.id.slice("Quadrant:".length) as QuadrantId) : null);
export const storeIdOf = (n: DrillNode | undefined): string | null => (n?.dim === "Store" ? n.id.slice("Store:".length) : null);
export const movementIdOf = (n: DrillNode | undefined): string | null => (n?.dim === "Movement" ? n.id.slice("Movement:".length) : null);

export const slugStore = (name: string): string => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** A store node built from its name alone (e.g. from a Command Center drill); the workspace supplies the figures. */
export const storeNodeByName = (name: string): DrillNode => ({ level: "entity", dim: "Store", id: `Store:${slugStore(name)}`, label: name, amount: null, variance: null });
