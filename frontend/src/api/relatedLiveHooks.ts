import { useQuery } from "@tanstack/react-query";
import type { GlQuery } from "@/types/relatedParty";
import { relatedLive } from "./relatedLive";

export const useRelatedSummary = () => useQuery({ queryKey: ["related", "summary"], queryFn: relatedLive.summary, retry: false, staleTime: 60_000 });

export const useRelatedItems = (code: number | null) =>
  useQuery({ queryKey: ["related", "items", code], queryFn: () => relatedLive.items(code as number), enabled: code !== null, retry: false, staleTime: 60_000 });

export const useRelatedIntercompany = () => useQuery({ queryKey: ["related", "intercompany"], queryFn: relatedLive.intercompany, retry: false, staleTime: 60_000 });

export const useRelatedGl = (q: GlQuery) => useQuery({ queryKey: ["related", "gl", q], queryFn: () => relatedLive.glEntries(q), retry: false, staleTime: 60_000, placeholderData: (p) => p });
