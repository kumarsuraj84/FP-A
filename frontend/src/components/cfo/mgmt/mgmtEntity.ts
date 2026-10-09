import { useRouterState } from "@tanstack/react-router";
import { MGMT_ENTITIES, type MgmtEntity } from "@/types/mgmtLive";

/** The entity lives in the page address (?entity=subco|holdco; absent means consolidated), so a view can be shared and survives a refresh. */
export const parseEntity = (v: unknown): MgmtEntity => (MGMT_ENTITIES.some((e) => e.id === v) ? (v as MgmtEntity) : "consolidated");

/** Router `validateSearch` for the Management pages: an unknown value is dropped, never thrown. */
export function validateMgmtSearch(raw: Record<string, unknown>): { entity?: "subco" | "holdco" } {
  const e = parseEntity(raw.entity);
  return e === "consolidated" ? {} : { entity: e };
}

export const useMgmtEntity = (): MgmtEntity => parseEntity(useRouterState({ select: (s) => (s.location.search as { entity?: unknown }).entity }));
