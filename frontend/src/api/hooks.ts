import { useQuery } from "@tanstack/react-query";
import { cfoApi } from "@/api";
import { useCfo } from "@/context/CfoContext";
import { drawerNodes } from "@/context/cfoState";
import type { DrillNode, DrillOrigin, HeroTab, Horizon } from "@/types/cfo";

/**
 * Query hooks. Every key includes the filters, so changing scenario / period / comparison / data
 * state refetches every section. Components never call the api directly.
 */
function useBase() {
  const { queryCtx, ready } = useCfo();
  return { ctx: queryCtx, ready };
}

export const useFreshness = () => {
  const { ctx, ready } = useBase();
  return useQuery({ queryKey: ["fresh", ctx], queryFn: () => cfoApi.getFreshness(ctx), enabled: ready });
};

export const usePulse = () => {
  const { ctx, ready } = useBase();
  return useQuery({ queryKey: ["pulse", ctx], queryFn: () => cfoApi.getPulse(ctx), enabled: ready, retry: false });
};

export const useBridge = (tab: HeroTab) => {
  const { ctx, ready } = useBase();
  return useQuery({ queryKey: ["bridge", tab, ctx], queryFn: () => cfoApi.getBridge(ctx, tab), enabled: ready, retry: false });
};

export const useLiquidity = (horizon: Horizon) => {
  const { ctx, ready } = useBase();
  return useQuery({ queryKey: ["liq", horizon, ctx], queryFn: () => cfoApi.getLiquidity(ctx, horizon), enabled: ready, retry: false });
};

export const useWorkingCapital = () => {
  const { ctx, ready } = useBase();
  return useQuery({ queryKey: ["wc", ctx], queryFn: () => cfoApi.getWorkingCapital(ctx), enabled: ready, retry: false });
};

export const useRisks = () => {
  const { ctx, ready } = useBase();
  return useQuery({ queryKey: ["risks", ctx], queryFn: () => cfoApi.getRisks(ctx), enabled: ready, retry: false });
};

export const useActions = () => {
  const { ctx, ready } = useBase();
  return useQuery({ queryKey: ["actions", ctx], queryFn: () => cfoApi.getActions(ctx), enabled: ready, retry: false });
};

export const useForecast = () => {
  const { ctx, ready } = useBase();
  return useQuery({ queryKey: ["forecast", ctx], queryFn: () => cfoApi.getForecast(ctx), enabled: ready, retry: false });
};

export const useDrill = (origin: DrillOrigin | null, nodes: DrillNode[]) => {
  const { ctx, ready } = useBase();
  const filters = drawerNodes(nodes);
  return useQuery({
    queryKey: ["drill", origin?.scope, origin?.id, filters.map((n) => n.id), ctx],
    queryFn: () => cfoApi.getDrillView(ctx, origin as DrillOrigin, filters),
    enabled: ready && origin !== null,
    retry: false,
  });
};

export const useLedger = (origin: DrillOrigin | null, nodes: DrillNode[]) => {
  const { ctx, ready } = useBase();
  const filters = drawerNodes(nodes);
  return useQuery({
    queryKey: ["ledger", origin?.id, filters.map((n) => n.id), ctx],
    queryFn: () => cfoApi.getLedger(ctx, origin as DrillOrigin, filters),
    enabled: ready && origin !== null,
    retry: false,
  });
};

export const useVoucher = (voucherId: string | null, amount: number | null) => {
  const { ctx, ready } = useBase();
  return useQuery({
    queryKey: ["voucher", voucherId, ctx],
    queryFn: () => cfoApi.getVoucher(ctx, voucherId as string, amount),
    enabled: ready && voucherId !== null,
    retry: false,
  });
};

export const useProfile = (origin: DrillOrigin | null, nodes: DrillNode[]) => {
  const { ctx, ready } = useBase();
  const filters = drawerNodes(nodes);
  return useQuery({
    queryKey: ["profile", origin?.id, filters.map((n) => n.id), ctx],
    queryFn: () => cfoApi.getEntityProfile(ctx, origin as DrillOrigin, filters),
    enabled: ready && origin !== null,
    retry: false,
  });
};
