import { useQuery } from "@tanstack/react-query";
import { liveMgmt } from "./mgmtLive";
import type { MgmtEntity, MgmtPnlQuery } from "@/types/mgmtLive";

const opts = { retry: false, staleTime: 60_000 } as const;

export const useMgmtRun = (enabled = true) => useQuery({ queryKey: ["mgmt", "run"], queryFn: liveMgmt.current, enabled, ...opts });

/** The run header says which run is serving: wait for it, and show its own failure if there is none (same pattern as the P&L pages). */
function useRunQuery<T>(key: string, fn: () => Promise<T>, extra: unknown[] = []) {
  const run = useMgmtRun();
  const id = run.data?.run_id;
  const q = useQuery({ queryKey: ["mgmt", key, id, ...extra], queryFn: fn, enabled: !!id, ...opts, placeholderData: (prev) => prev });
  if (run.isError) return { ...q, isPending: false, isError: true, error: run.error, data: undefined, refetch: run.refetch } as typeof q;
  if (run.isPending) return { ...q, isPending: true } as typeof q;
  return q;
}

export const useMgmtPnl = (p: MgmtPnlQuery) => useRunQuery("pnl", () => liveMgmt.pnl(p), [p.from_month, p.to_month, p.include_proposed, p.entity]);
export const useMgmtStores = (month: string | undefined, toMonth: string | undefined, entity: MgmtEntity) => useRunQuery("stores", () => liveMgmt.stores(month, toMonth, entity), [month, toMonth, entity]);
export const useMgmtReconciliation = (from: string | undefined, to: string | undefined, entity: MgmtEntity) => useRunQuery("recon", () => liveMgmt.reconciliation(from, to, entity), [from, to, entity]);
export const useMgmtAdjustments = () => useRunQuery("adjustments", () => liveMgmt.adjustments());
export const useMgmtMapping = () => useRunQuery("mapping", () => liveMgmt.mapping());
