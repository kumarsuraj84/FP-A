import type { Bridge, BridgeItem, DrillOrigin, HeroTab, LiquiditySummary, WorkingCapitalLine } from "@/types/cfo";

/** Builds the drill origin for a clicked waterfall bar. Totals carry the net movement as variance. */
export function originFromBridgeItem(bridge: Bridge, item: BridgeItem, scope: string): DrillOrigin {
  const totals = bridge.items.filter((i) => i.kind === "total");
  const net = totals.length >= 2 ? Math.round((totals[totals.length - 1].value - totals[0].value) * 100) / 100 : 0;
  const isFirst = item.kind === "total" && item.id === totals[0]?.id;
  return {
    source: scope.startsWith("forecast") ? "forecast" : "bridge",
    scope,
    id: item.id,
    label: item.label,
    family: item.family,
    amount: item.value,
    variance: item.kind === "delta" ? item.value : isFirst ? 0 : net,
    base: totals[0]?.value ?? null,
  };
}

export function originFromWcRow(row: WorkingCapitalLine): DrillOrigin {
  return { source: "workingCapital", scope: "wc", id: row.id, label: row.label, family: row.family, amount: row.cashImpact, variance: row.cashImpact };
}

export function originFromLiquidity(kind: "inflows" | "obligations" | "projected" | "current", s: LiquiditySummary): DrillOrigin {
  const cur = s.currentCash.value;
  const proj = s.projectedCash.value;
  const map = {
    inflows: { id: "inflows", label: "Expected Inflows", amount: s.expectedInflows.value },
    obligations: { id: "obligations", label: "Upcoming Obligations", amount: s.upcomingObligations.value === null ? null : -s.upcomingObligations.value },
    projected: { id: "projected", label: "Projected Cash", amount: proj },
    current: { id: "current", label: "Current Cash", amount: cur },
  }[kind];
  return { source: "liquidity", scope: "liquidity", id: map.id, label: map.label, family: "cash", amount: map.amount, variance: map.amount };
}

export const HERO_TABS: { id: HeroTab; label: string }[] = [
  { id: "profit", label: "Profit" },
  { id: "cash", label: "Cash" },
  { id: "workingCapital", label: "Working Capital" },
];
