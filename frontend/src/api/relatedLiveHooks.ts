import { useQuery } from "@tanstack/react-query";
import { relatedLive } from "./relatedLive";

export const useRelatedSummary = () => useQuery({ queryKey: ["related", "summary"], queryFn: relatedLive.summary, retry: false, staleTime: 60_000 });

export const useRelatedItems = (code: number | null) =>
  useQuery({ queryKey: ["related", "items", code], queryFn: () => relatedLive.items(code as number), enabled: code !== null, retry: false, staleTime: 60_000 });
