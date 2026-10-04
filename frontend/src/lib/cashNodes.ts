import type { DrillNode, DrillOrigin, Family } from "@/types/cfo";

/** The Cash & Working Capital workspace is a drill origin; its first node is the cash driver being investigated. */
export const CASH_ORIGIN: DrillOrigin = {
  source: "liquidity",
  scope: "cashroom",
  id: "room",
  label: "Cash & Working Capital",
  family: "cash",
  amount: null,
  variance: null,
};

export const isCashRoom = (o: DrillOrigin | null | undefined): boolean => o?.scope === "cashroom";

export type CashKey = "current" | "projected" | "inflows" | "obl_vendor" | "obl_payroll" | "obl_statutory" | "obl_other" | "inventory" | "creditors" | "vendor_advances" | "receivables" | "other_wc";

/** Which Stage 1 investigation each cash driver reuses, so the same number always drills the same way. */
export const CASH_KEY_META: Record<CashKey, { family: Family; wc: boolean }> = {
  current: { family: "cash", wc: false },
  projected: { family: "cash", wc: false },
  inflows: { family: "cash", wc: false },
  obl_vendor: { family: "cash", wc: false },
  obl_payroll: { family: "cash", wc: false },
  obl_statutory: { family: "cash", wc: false },
  obl_other: { family: "cash", wc: false },
  inventory: { family: "volume", wc: true },
  creditors: { family: "payables", wc: true },
  vendor_advances: { family: "advances", wc: true },
  receivables: { family: "cash", wc: true },
  other_wc: { family: "cash", wc: true },
};

export const isCashKey = (k: string): k is CashKey => k in CASH_KEY_META;

export function cashNode(key: CashKey, label: string, amount: number | null): DrillNode {
  return { level: "driver", dim: "Cash driver", id: `CashDriver:${key}`, label, amount, variance: amount };
}

export const isCashNode = (n: DrillNode | undefined): boolean => n?.dim === "Cash driver";
export const cashKeyOf = (n: DrillNode | undefined): CashKey | null => {
  const k = n?.dim === "Cash driver" ? n.id.slice("CashDriver:".length) : "";
  return isCashKey(k) ? k : null;
};

/** The Stage 1 style origin a cash driver investigates (amount and variance are the driver's own cash effect). */
export function cashEffectiveOrigin(node: DrillNode): DrillOrigin {
  const key = cashKeyOf(node) ?? "projected";
  const meta = CASH_KEY_META[key];
  return {
    source: meta.wc ? "workingCapital" : "liquidity",
    scope: meta.wc ? "wc" : "liquidity",
    id: key,
    label: node.label,
    family: meta.family,
    amount: node.amount,
    variance: node.amount,
  };
}
