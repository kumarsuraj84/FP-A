import { useQuery } from "@tanstack/react-query";
import { useMgmtRun } from "./mgmtLiveHooks";
import { liveExpenses, type LedgersQuery } from "./expensesLive";
import type { ExpQuery } from "@/types/expensesLive";

const opts = { retry: false, staleTime: 60_000 } as const;

/** The management run header says which run is serving: wait for it (and show its failure if there is none), like the other management pages. */
function useRunQuery<T>(key: string, fn: () => Promise<T>, extra: unknown[], enabledExtra = true) {
  const run = useMgmtRun();
  const id = run.data?.run_id;
  const q = useQuery({ queryKey: ["expenses", key, id, ...extra], queryFn: fn, enabled: !!id && enabledExtra, ...opts, placeholderData: (prev) => prev });
  if (run.isError) return { ...q, isPending: false, isError: true, error: run.error, data: undefined, refetch: run.refetch } as typeof q;
  if (run.isPending) return { ...q, isPending: true } as typeof q;
  return q;
}

const win = (q: ExpQuery) => [q.scope, q.entity, q.from_month, q.to_month];

export const useExpSummary = (q: ExpQuery) => useRunQuery("summary", () => liveExpenses.summary(q), win(q));
export const useExpTrend = (q: ExpQuery) => useRunQuery("trend", () => liveExpenses.trend(q), win(q));
export const useExpSites = (q: ExpQuery, head?: string) => useRunQuery("sites", () => liveExpenses.sites(q, head), [...win(q), head]);
export const useExpLedgers = (q: LedgersQuery | null) => useRunQuery("ledgers", () => liveExpenses.ledgers(q as LedgersQuery), q ? [...win(q), q.head, q.site, q.site_entity, q.glcode] : [], !!q);
export const useExpExceptions = (q: ExpQuery) => useRunQuery("exceptions", () => liveExpenses.exceptions(q), win(q));
