import { useQuery } from "@tanstack/react-query";
import { liveCash } from "./cashLive";

export const useCashRun = () => useQuery({ queryKey: ["cash", "run"], queryFn: liveCash.current, retry: false, staleTime: 60_000 });

function useRunQuery<T>(key: string, fn: (run: string) => Promise<T>, extra: unknown[] = []) {
  const run = useCashRun();
  const id = run.data?.run_id;
  const q = useQuery({ queryKey: ["cash", key, id, ...extra], queryFn: () => fn(id as string), enabled: !!id, retry: false, staleTime: 60_000 });
  if (run.isError) return { ...q, isPending: false, isError: true, error: run.error, data: undefined, refetch: run.refetch } as typeof q;
  if (run.isPending) return { ...q, isPending: true } as typeof q;
  return q;
}

export const useCashSummary = () => useRunQuery("summary", liveCash.summary);
export const useTillStores = (limit: number, sort: string) => useRunQuery("stores", (run) => liveCash.stores(run, { limit, sort }), [limit, sort]);
