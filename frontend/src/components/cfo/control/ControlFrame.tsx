import { useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { auth, ControlApiError, type Me } from "@/api/controlApi";
import { cn } from "@/lib/utils";
import { Skeleton } from "../common";
import { Panel, WorkspaceHeader } from "../panels";
import { Btn, ErrMsg, Field, input, useWrite } from "./ui";

export type ControlTab = "sourcefix" | "mapping" | "close" | "adjustments" | "corrections" | "inbox" | "users";
const TABS: { id: ControlTab; label: string; to: "/control/source-fixes" | "/control/mapping" | "/control/close" | "/control/adjustments" | "/control/corrections" | "/control/inbox" | "/control/users"; admin?: boolean }[] = [
  { id: "close", label: "Month-end close", to: "/control/close" },
  { id: "adjustments", label: "Adjustments & Provisions", to: "/control/adjustments" },
  { id: "corrections", label: "Corrections", to: "/control/corrections" },
  { id: "inbox", label: "Exception Inbox", to: "/control/inbox" },
  { id: "mapping", label: "Mapping", to: "/control/mapping" },
  { id: "sourcefix", label: "Source fixes", to: "/control/source-fixes" },
  { id: "users", label: "Users", to: "/control/users", admin: true },
];

/** The signed-in person, or null when there is no session (a 401 is an answer, not an error). */
export function useMe() {
  return useQuery({
    queryKey: ["control", "me"],
    queryFn: async (): Promise<Me | null> => {
      try {
        return await auth.me();
      } catch (e) {
        if (e instanceof ControlApiError && e.status === 401) return null;
        throw e;
      }
    },
    retry: false,
    staleTime: 30_000,
  });
}

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const qc = useQueryClient();
  const login = useWrite(() => auth.login(email, password), ["control"], () => setPassword(""));
  return (
    <div className="mx-auto mt-10 w-full max-w-[360px]" data-testid="login">
      <Panel eyebrow="Governed changes" title="Sign in">
        <form className="grid gap-3 p-4" onSubmit={(e) => { e.preventDefault(); login.mutate(undefined, { onSuccess: () => void qc.invalidateQueries() }); }}>
          <Field label="Email"><input aria-label="Email" className={input} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password"><input aria-label="Password" className={input} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <ErrMsg error={login.error} />
          <Btn type="submit" tone="primary" testId="login-submit" disabled={!email || !password || login.isPending}>{login.isPending ? "Signing in…" : "Sign in"}</Btn>
          <p className="text-[11px] text-muted-foreground">Accounts are created by an administrator. Ask them if you need access or a password reset.</p>
        </form>
      </Panel>
    </div>
  );
}

export function ChangePassword({ me, forced }: { me: Me; forced?: boolean }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const change = useWrite(() => auth.changePassword(current, next), ["control"]);
  return (
    <div className="mx-auto mt-10 w-full max-w-[400px]" data-testid="change-password">
      <Panel eyebrow={forced ? "First sign-in" : "Account"} title="Choose a new password">
        <form className="grid gap-3 p-4" onSubmit={(e) => { e.preventDefault(); change.mutate(undefined); }}>
          <p className="text-[12px] text-muted-foreground">{forced ? `Welcome ${me.display_name}. Replace the temporary password before you continue.` : "Changing the password signs you out everywhere."} Use at least 12 characters.</p>
          <Field label="Current password"><input aria-label="Current password" className={input} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
          <Field label="New password"><input aria-label="New password" className={input} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
          <Field label="Repeat the new password"><input aria-label="Repeat the new password" className={input} type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} /></Field>
          {next && again && next !== again && <div className="text-[12px] text-[oklch(0.45_0.15_25)]">The two passwords differ.</div>}
          <ErrMsg error={change.error} />
          {change.isSuccess && <div role="status" className="text-[12px]">Password changed. Sign in again with the new password.</div>}
          <Btn type="submit" tone="primary" testId="change-submit" disabled={!current || next.length < 12 || next !== again || change.isPending}>Change password</Btn>
        </form>
      </Panel>
    </div>
  );
}

export function ControlFrame({ active, subtitle, children }: { active: ControlTab; subtitle: ReactNode; children: (me: Me) => ReactNode }) {
  const me = useMe();
  const qc = useQueryClient();
  const logout = useWrite(() => auth.logout(), ["control"], () => void qc.invalidateQueries());
  const [changing, setChanging] = useState(false);
  const m = me.data;
  return (
    <div data-testid="control-room" className="@container flex min-w-0 flex-1 flex-col overflow-y-auto bg-background">
      <WorkspaceHeader
        eyebrow="Control"
        title="Governed changes"
        subtitle={subtitle}
        right={m ? (
          <span data-testid="whoami" className="inline-flex items-center gap-2 rounded border bg-card px-2 py-1 text-[11.5px]">
            <span className="font-semibold">{m.display_name}</span><span className="text-muted-foreground">{m.role.replaceAll("_", " ")}</span>
            <button className="underline-offset-2 hover:underline" onClick={() => setChanging(true)}>Password</button>
            <button data-testid="signout" className="underline-offset-2 hover:underline" onClick={() => logout.mutate(undefined)}>Sign out</button>
          </span>
        ) : undefined}
      />
      <nav aria-label="Control pages" data-testid="control-tabs" className="flex flex-wrap gap-0.5 border-b bg-card px-3 pt-1.5">
        {TABS.filter((t) => !t.admin || m?.role === "admin").map((t) => (
          <Link key={t.id} to={t.to} data-testid={`control-tab-${t.id}`} aria-current={active === t.id ? "page" : undefined}
            className={cn("press -mb-px rounded-t border border-b-0 px-3 py-1.5 text-[12.5px] font-semibold", active === t.id ? "border-border bg-background text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {t.label}
          </Link>
        ))}
      </nav>
      {me.isPending ? <Skeleton className="m-4 h-[240px]" /> : me.isError ? (
        <div className="p-4"><ErrMsg error={me.error} /></div>
      ) : !m ? <LoginForm /> : m.must_change_password || changing ? <ChangePassword me={m} forced={m.must_change_password} /> : children(m)}
    </div>
  );
}
