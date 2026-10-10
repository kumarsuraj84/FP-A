import type { ReactNode } from "react";
import { Skeleton } from "../common";
import { ChangePassword, LoginForm, useMe } from "./ControlFrame";
import { ErrMsg } from "./ui";

/** Whole-application sign-in. Off by default (the pages still read through the transitional proxy token); with VITE_REQUIRE_LOGIN=1 nothing renders until a named user is signed in,
 *  and the server attributes every Finance read to that person. Pair it with FPA_ALLOW_PROXY_TOKEN=0 on the API to retire the shared token. */
export const loginRequired = (): boolean => import.meta.env.VITE_REQUIRE_LOGIN === "1";

export function SessionGate({ children }: { children: ReactNode }) {
  const me = useMe();
  if (!loginRequired()) return <>{children}</>;
  if (me.isPending) return <div className="p-6"><Skeleton className="h-[240px]" /></div>;
  if (me.isError) return <div className="p-6"><ErrMsg error={me.error} /></div>;
  if (!me.data) return <div className="flex-1 overflow-y-auto bg-background"><LoginForm /></div>;
  if (me.data.must_change_password) return <div className="flex-1 overflow-y-auto bg-background"><ChangePassword me={me.data} forced /></div>;
  return <>{children}</>;
}
