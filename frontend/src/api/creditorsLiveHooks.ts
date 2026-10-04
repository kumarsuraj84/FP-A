import { useQuery } from "@tanstack/react-query";
import type { AgeFilter } from "@/types/creditors";
import { cohortFor, liveCreditors } from "./creditorsLive";

/** One run drives the whole page: the API says which (the live run, else the newest verified candidate). */
export const useLiveRun = () => useQuery({ queryKey: ["cred", "run"], queryFn: liveCreditors.current, retry: false, staleTime: 60_000 });

function useRunQuery<T>(key: string, fn: (run: string) => Promise<T>, extra: unknown[] = []) {
  const run = useLiveRun();
  const id = run.data?.extraction_run_id;
  const q = useQuery({ queryKey: ["cred", key, id, ...extra], queryFn: () => fn(id as string), enabled: !!id, retry: false, staleTime: 60_000 });
  // a failed or pending run lookup is the failure / loading state of every section
  if (run.isError) return { ...q, isPending: false, isError: true, error: run.error, data: undefined, refetch: run.refetch } as typeof q;
  if (run.isPending) return { ...q, isPending: true } as typeof q;
  return q;
}

export const useLiveSummary = () => useRunQuery("summary", liveCreditors.summary);
export const useLiveDocumentAge = () => useRunQuery("age", liveCreditors.documentAge);
export const useLiveDueStatus = () => useRunQuery("due", liveCreditors.dueStatus);
export const useLiveLedgers = () => useRunQuery("ledgers", liveCreditors.ledgers);
export const useLiveControls = () => useRunQuery("controls", liveCreditors.controls);

export const useLiveVendors = (filter: AgeFilter, o: { limit: number; q?: string; sort?: string }) =>
  useRunQuery("vendors", (run) => liveCreditors.vendors(run, { cohort: cohortFor(filter), limit: o.limit, q: o.q, sort: o.sort }), [filter, o.limit, o.q ?? "", o.sort ?? ""]);

export const useLiveVendor = (ref: string | null) => {
  const run = useLiveRun();
  const id = run.data?.extraction_run_id;
  return useQuery({ queryKey: ["cred", "vendor", id, ref], queryFn: () => liveCreditors.vendor(id as string, ref as string), enabled: !!id && !!ref, retry: false, staleTime: 60_000 });
};

export const useLiveItems = (ref: string | null, drcr?: "Cr" | "Dr") => {
  const run = useLiveRun();
  const id = run.data?.extraction_run_id;
  return useQuery({ queryKey: ["cred", "items", id, ref, drcr ?? "all"], queryFn: () => liveCreditors.items(id as string, ref as string, { drcr }), enabled: !!id && !!ref, retry: false, staleTime: 60_000 });
};
