import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { auth, type Role } from "@/api/controlApi";
import { Skeleton } from "../common";
import { Panel } from "../panels";
import { ControlFrame } from "./ControlFrame";
import { Btn, ErrMsg, Field, input, label, useWrite, when } from "./ui";

const ROLES: Role[] = ["viewer", "fpa_manager", "finance_reviewer", "controller", "admin"];

export function UsersPage() {
  const q = useQuery({ queryKey: ["control", "users"], queryFn: auth.users, retry: false });
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("fpa_manager");
  const [shown, setShown] = useState<{ email: string; temporary_password: string } | null>(null);
  const create = useWrite(() => auth.createUser(email, name, role), ["control"], (r) => { setShown(r); setEmail(""); setName(""); });
  const set = useWrite((x: { id: string; role: Role }) => auth.setRole(x.id, x.role), ["control"]);
  const active = useWrite((x: { id: string; active: boolean }) => auth.setActive(x.id, x.active), ["control"]);
  const reset = useWrite((id: string) => auth.resetPassword(id), ["control"], (r) => setShown(r));
  const unlock = useWrite((id: string) => auth.unlock(id), ["control"]);
  return (
    <ControlFrame active="users" subtitle="Accounts are created and managed by an administrator only. There is no self sign-up; a temporary password is shown once and must be changed at first sign-in.">
      {(me) => me.role !== "admin" ? <div className="p-4"><ErrMsg error={new Error("Only an administrator can manage users.")} /></div> : (
        <div className="grid gap-3 p-3">
          <Panel eyebrow="Administrator" title="Add a user">
            <form className="grid gap-3 p-4 @[900px]:grid-cols-4" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
              <Field label="Email"><input aria-label="User email" className={input} type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
              <Field label="Name"><input aria-label="User name" className={input} value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <Field label="Role"><select aria-label="User role" className={input} value={role} onChange={(e) => setRole(e.target.value as Role)}>{ROLES.map((r) => <option key={r} value={r}>{label(r)}</option>)}</select></Field>
              <div className="flex items-end"><Btn type="submit" tone="primary" testId="create-user" disabled={!email || !name || create.isPending}>Create user</Btn></div>
            </form>
            <div className="px-4 pb-3"><ErrMsg error={create.error ?? set.error ?? active.error ?? reset.error ?? unlock.error} /></div>
            {shown && <div role="status" data-testid="temp-password" className="mx-4 mb-4 rounded border bg-[oklch(0.97_0.04_85)] px-3 py-2 text-[12.5px]">Temporary password for <b>{shown.email}</b>: <code className="num font-bold">{shown.temporary_password}</code>. It is shown once. Give it to the person privately; they must change it at first sign-in. <button className="underline" onClick={() => setShown(null)}>Hide</button></div>}
          </Panel>
          <Panel testId="user-list" eyebrow="People" title={`Users${q.data ? ` (${q.data.length})` : ""}`}>
            {q.isPending ? <Skeleton className="m-4 h-[120px]" /> : q.isError ? <div className="p-4"><ErrMsg error={q.error} /></div> : (
              <table className="w-full text-[12.5px]"><thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-3 py-2">Name</th><th>Email</th><th>Role</th><th>Last sign-in</th><th>State</th><th /></tr></thead>
                <tbody>{q.data.map((u) => (
                  <tr key={u.user_id} className="border-b" data-testid={`user-${u.email}`}>
                    <td className="px-3 py-1.5 font-medium">{u.display_name}</td><td>{u.email}</td>
                    <td><select aria-label={`Role of ${u.email}`} className={input + " w-auto"} value={u.role} onChange={(e) => set.mutate({ id: u.user_id, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r} value={r}>{label(r)}</option>)}</select></td>
                    <td>{when(u.last_login_at)}</td><td>{!u.active ? "Inactive" : u.locked_until && new Date(u.locked_until) > new Date() ? "Locked" : u.must_change_password ? "Must change password" : "Active"}</td>
                    <td className="space-x-1 whitespace-nowrap px-2"><Btn onClick={() => reset.mutate(u.user_id)}>Reset password</Btn><Btn onClick={() => unlock.mutate(u.user_id)}>Unlock</Btn><Btn tone={u.active ? "danger" : "default"} onClick={() => active.mutate({ id: u.user_id, active: !u.active })}>{u.active ? "Deactivate" : "Activate"}</Btn></td>
                  </tr>))}</tbody></table>
            )}
          </Panel>
        </div>
      )}
    </ControlFrame>
  );
}
