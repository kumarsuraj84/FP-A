import { useQuery } from "@tanstack/react-query";
import { liveEntry, type LedgerEntriesQuery } from "./entryLive";

/** One run drives the whole entry drill: the API says which (the live entry run). */
export const useEntryRun = () => useQuery({ queryKey: ["entry", "run"], queryFn: liveEntry.current, retry: false, staleTime: 60_000 });

function useRunQuery<T>(key: string, fn: (run: string, h: NonNullable<ReturnType<typeof useEntryRun>["data"]>) => Promise<T>, extra: unknown[] = [], enabledExtra = true) {
  const run = useEntryRun();
  const h = run.data;
  const q = useQuery({ queryKey: ["entry", key, h?.entry_run_id, ...extra], queryFn: () => fn(h!.entry_run_id, h!), enabled: !!h && enabledExtra, retry: false, staleTime: 60_000, placeholderData: (prev) => prev });
  // a failed or pending run lookup is the failure / loading state of every section
  if (run.isError) return { ...q, isPending: false, isError: true, error: run.error, data: undefined, refetch: run.refetch } as typeof q;
  if (run.isPending) return { ...q, isPending: true } as typeof q;
  return q;
}

export const useEntry = (ref: string | null, entity?: string) => useRunQuery("entry", (run) => liveEntry.entry(run, ref as string, entity), [ref, entity], !!ref);
export const useEntryLineDetail = (ref: string | null, entity?: string) => useRunQuery("lines", (run) => liveEntry.lineDetail(run, ref as string, entity), [ref, entity], !!ref);
export const useLedgerEntries = (q: LedgerEntriesQuery | null) => useRunQuery("ledger-entries", (run) => liveEntry.ledgerEntries(run, q as LedgerEntriesQuery), [q], !!q);
/** Link status of one creditors open item (`item_ref` from the creditors API). The cash/creditors run ids come from the entry run header. */
export const useBillLink = (itemRef: string | null) => useRunQuery("bill-link", (run, h) => liveEntry.billLink(run, h.creditors_run_id, itemRef as string), [itemRef], !!itemRef);
export const useTillStoresDrill = () => useRunQuery("till-stores", (run, h) => liveEntry.tillStores(run, h.cash_run_id));
export const useTillDays = (site: string | null) => useRunQuery("till-days", (run, h) => liveEntry.tillDays(run, h.cash_run_id, site as string), [site], !!site);
