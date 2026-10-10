import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { auth, inbox, MAKERS, type Case, type Me } from "@/api/controlApi";
import { cn } from "@/lib/utils";
import { Skeleton } from "../common";
import { Panel } from "../panels";
import { ControlFrame } from "./ControlFrame";
import { Btn, ErrMsg, Field, History, input, label, Pill, useWrite, when } from "./ui";

const DOMAINS = ["EXPENSE", "REVENUE", "CREDITORS", "CASH", "CONTROLS", "RELATED_PARTY", "MAPPING", "CLOSE"];
const CLOSURE = ["RESOLVED_FIXED", "FALSE_POSITIVE", "ACCEPTED_RISK", "DUPLICATE", "SOURCE_FIXED", "OTHER"];
const EVIDENCE_HIDDEN = new Set(["threshold_version", "calibration_status"]);
const REVIEWERS = ["finance_reviewer", "controller", "admin", "fpa_manager"];

function Detail({ c, me, onClose }: { c: Case; me: Me; onClose: () => void }) {
  const full = useQuery({ queryKey: ["inbox", "one", c.case_id, c.status, c.owner_user_id, c.due_date], queryFn: () => inbox.one(c.case_id) });
  const hist = useQuery({ queryKey: ["inbox", "history", c.case_id, c.status, c.owner_user_id, c.due_date, c.next_action], queryFn: () => inbox.history(c.case_id) });
  const users = useQuery({ queryKey: ["control", "assignable"], queryFn: auth.assignable, staleTime: 60_000 });
  const [owner, setOwner] = useState(c.owner_user_id ?? "");
  const [due, setDue] = useState(c.due_date ?? "");
  const [next, setNext] = useState(c.next_action ?? "");
  const [reason, setReason] = useState("");
  const [closure, setClosure] = useState("RESOLVED_FIXED");
  const [note, setNote] = useState("");
  const assign = useWrite(() => inbox.assign(c.case_id, owner, due || undefined, next || undefined), ["inbox"]);
  const act = useWrite((a: string) => inbox.act(c.case_id, a, reason || undefined, a === "close" ? closure : undefined), ["inbox"], () => setReason(""));
  const comment = useWrite(() => inbox.comment(c.case_id, note), ["inbox"], () => setNote(""));
  const d = full.data ?? c;
  const reviewer = REVIEWERS.includes(me.role);
  const worker = me.role !== "viewer";
  const ev = Object.entries(d.evidence).filter(([k]) => !EVIDENCE_HIDDEN.has(k));
  return (
    <Panel testId="case-detail" eyebrow={label(d.domain)} title={d.title} right={<button className="text-[12px] underline" onClick={onClose}>Close</button>}>
      <div className="grid gap-3 p-4 text-[12.5px]">
        <div className="flex flex-wrap items-center gap-2"><Pill value={d.band} /><Pill value={d.status} testId="detail-status" /><span className="num">score {Number(d.final_score).toFixed(0)}</span>
          {d.recurring && <span data-testid="recurring" className="rounded bg-muted px-1.5 text-[10.5px] font-bold">RECURRING · OCCURRENCE {d.recurrence_no}</span>}
          {d.overdue && <span className="text-[11px] font-semibold tone-warn">OVERDUE</span>}</div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5" data-testid="case-evidence">
          {ev.map(([k, v]) => (<><dt key={k + "k"} className="text-muted-foreground">{label(k)}</dt><dd key={k + "v"} className="num">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></>))}
          <dt className="text-muted-foreground">First seen</dt><dd>{when(d.first_detected_at)}</dd><dt className="text-muted-foreground">Last seen</dt><dd>{when(d.last_detected_at)} ({d.detection_count}×)</dd>
        </dl>
        <div className="text-[11px] text-muted-foreground">{String(d.evidence.calibration_status ?? "")} · thresholds {String(d.evidence.threshold_version ?? "")}. Evidence is a snapshot of what triggered the case, not a finance record.</div>
        {d.lineage && d.lineage.length > 0 && <div data-testid="lineage" className="text-[12px]">Earlier occurrences: {d.lineage.map((l) => `#${l.recurrence_no} ${l.status.toLowerCase()}${l.closure_reason ? ` (${label(l.closure_reason)})` : ""}`).join(" · ")}</div>}
        {d.drill_link && <a className="text-primary underline" href={d.drill_link}>Open the evidence</a>}
        {d.status !== "CLOSED" && reviewer && (
          <div className="grid gap-2 rounded border p-3" data-testid="assign-box">
            <div className="eyebrow">Owner and due date</div>
            <div className="grid gap-2 @[700px]:grid-cols-3">
              <Field label="Owner"><select aria-label="Owner" className={input} value={owner} onChange={(e) => setOwner(e.target.value)}><option value="">Choose…</option>{users.data?.map((u) => <option key={u.user_id} value={u.user_id}>{u.display_name}</option>)}</select></Field>
              <Field label="Due date"><input aria-label="Due date" type="date" className={input} value={due} onChange={(e) => setDue(e.target.value)} /></Field>
              <Field label="Next action"><input aria-label="Next action" className={input} value={next} onChange={(e) => setNext(e.target.value)} /></Field>
            </div>
            <div><Btn testId="assign" onClick={() => assign.mutate(undefined)} disabled={!owner || assign.isPending}>{d.owner_user_id ? "Reassign" : "Assign"}</Btn></div>
          </div>
        )}
        {d.status === "CLOSED" ? <div>Closed: {label(d.closure_reason ?? "")}</div> : (d.owner_user_id || d.next_action) && <div>Next action: <b>{d.next_action ?? "not set"}</b> · due {d.due_date ?? "not set"} · owner {users.data?.find((u) => u.user_id === d.owner_user_id)?.display_name ?? "assigned"}</div>}
        <Field label="Reason or note (10+ characters for close, return, reopen)"><input aria-label="Reason" className={input} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <ErrMsg error={assign.error ?? act.error ?? comment.error} />
        <div className="flex flex-wrap items-center gap-2">
          {d.status === "OPEN" && worker && <Btn testId="act-acknowledge" onClick={() => act.mutate("acknowledge")}>Acknowledge</Btn>}
          {(d.status === "OPEN" || d.status === "ACKNOWLEDGED") && worker && <Btn testId="act-resolve" tone="primary" onClick={() => act.mutate("resolve")}>Mark resolved</Btn>}
          {d.status === "RESOLVED" && reviewer && <Btn testId="act-return" onClick={() => act.mutate("return")} disabled={reason.trim().length < 10}>Send back</Btn>}
          {d.status !== "CLOSED" && reviewer && <><select aria-label="Closure reason" className={cn(input, "w-auto")} value={closure} onChange={(e) => setClosure(e.target.value)}>{CLOSURE.map((x) => <option key={x} value={x}>{label(x)}</option>)}</select><Btn testId="act-close" tone="danger" onClick={() => act.mutate("close")} disabled={reason.trim().length < 10 || act.isPending}>Close</Btn></>}
          {d.status === "CLOSED" && reviewer && <Btn testId="act-reopen" onClick={() => act.mutate("reopen")} disabled={reason.trim().length < 10}>Reopen (closed too early)</Btn>}
        </div>
        <div className="flex gap-2"><input aria-label="Comment" className={input} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a comment" /><Btn onClick={() => comment.mutate(undefined)} disabled={note.trim().length < 3}>Comment</Btn></div>
        <div><div className="eyebrow mb-1">History</div>{hist.data ? <History events={hist.data} /> : <Skeleton className="h-10" />}</div>
      </div>
    </Panel>
  );
}

export function InboxPage() {
  const [band, setBand] = useState("");
  const [domain, setDomain] = useState("");
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [mine, setMine] = useState(false);
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const filtered = Boolean(band || domain || search || mine || status || showAll);
  const q = useQuery({ queryKey: ["inbox", "list", band, domain, search, mine, status, showAll], queryFn: () => inbox.list({ band: band || undefined, domain: domain || undefined, search: search || undefined, mine, status: status || undefined, top: filtered ? undefined : 20 }) });
  const th = useQuery({ queryKey: ["inbox", "thresholds"], queryFn: inbox.thresholds, staleTime: 300_000 });
  const detect = useWrite(() => inbox.detect(), ["inbox"]);
  const d = q.data;
  const sel = d?.items.find((c) => c.case_id === selected) ?? null;
  return (
    <ControlFrame active="inbox" subtitle="What needs attention now: ranked, with an owner, a due date and a next action. Workflow only: nothing here changes a reported number.">
      {(me) => (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b bg-card px-3 py-2 text-[12px]" data-testid="inbox-summary">
            {(["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const).map((b) => <button key={b} data-testid={`band-${b}`} aria-pressed={band === b} onClick={() => setBand(band === b ? "" : b)} className={cn("rounded border px-2 py-1", band === b && "border-primary bg-muted")}><Pill value={b} /> <span className="num font-semibold">{d?.bands[b] ?? 0}</span></button>)}
            <span data-testid="unowned" className="text-muted-foreground">{d?.unowned ?? 0} without an owner</span><span data-testid="overdue" className={cn("text-muted-foreground", (d?.overdue ?? 0) > 0 && "tone-warn")}>{d?.overdue ?? 0} overdue</span>
            <span className="ml-auto flex items-center gap-2">
              {th.data && <span className="text-[11px] text-muted-foreground" data-testid="calibration">{th.data.calibration_status.toLowerCase()} · thresholds {th.data.version}</span>}
              <Btn testId="run-detection" onClick={() => detect.mutate(undefined)} disabled={!MAKERS.concat(["finance_reviewer"]).includes(me.role) || detect.isPending} title="Run the detectors now">{detect.isPending ? "Detecting…" : "Run detection"}</Btn>
            </span>
          </div>
          {detect.data && <div role="status" data-testid="detect-result" className="border-b px-4 py-1.5 text-[12px]">{detect.data.created} new, {detect.data.recurred} updated{detect.data.errors.length ? `; ${detect.data.errors.join(", ")}` : ""}.</div>}
          <ErrMsg error={detect.error} />
          <div className="grid gap-3 p-3 @[1100px]:grid-cols-[1.4fr_1fr]">
            <Panel testId="case-list" eyebrow={filtered ? "Filtered" : "Top 20 requiring attention now"} title={`Exceptions${d ? ` (${d.shown} of ${d.total})` : ""}`}
              right={<div className="flex flex-wrap items-center gap-2 text-[12px]">
                <input aria-label="Search" className={cn(input, "w-[130px]")} placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} />
                <select aria-label="Domain" className={cn(input, "w-auto")} value={domain} onChange={(e) => setDomain(e.target.value)}><option value="">All domains</option>{DOMAINS.map((x) => <option key={x} value={x}>{label(x)}</option>)}</select>
                <select aria-label="Status" className={cn(input, "w-auto")} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Open</option>{["OPEN", "ACKNOWLEDGED", "RESOLVED", "CLOSED"].map((x) => <option key={x} value={x}>{label(x)}</option>)}</select>
                <label className="flex items-center gap-1"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Mine</label>
                <label className="flex items-center gap-1"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show all</label>
              </div>}>
              {q.isPending ? <Skeleton className="m-4 h-[200px]" /> : q.isError ? <div className="p-4"><ErrMsg error={q.error} /></div> : (
                <ul data-testid="case-rows">
                  {d!.items.map((c) => (
                    <li key={c.case_id}>
                      <button data-testid={`case-${c.case_id}`} onClick={() => setSelected(c.case_id)} className={cn("flex w-full items-start gap-3 border-b px-4 py-2 text-left hover:bg-muted/40", selected === c.case_id && "bg-muted/60")}>
                        <Pill value={c.band} />
                        <span className="min-w-0 flex-1"><span className="block font-medium">{c.title}</span>
                          <span className="block text-[11.5px] text-muted-foreground">{label(c.domain)}{c.period ? ` · ${c.period}` : ""}{c.recurring ? ` · occurrence ${c.recurrence_no}` : ""}{c.owner_user_id ? "" : " · no owner"}{c.due_date ? ` · due ${c.due_date}` : ""}{c.overdue ? " · OVERDUE" : ""}</span></span>
                        <span className="num text-[12px] font-semibold">{Number(c.final_score).toFixed(0)}</span><Pill value={c.status} />
                      </button>
                    </li>
                  ))}
                  {d!.items.length === 0 && <li className="px-4 py-6 text-center text-muted-foreground" data-testid="inbox-empty">Nothing needs attention. Run detection to check again.</li>}
                </ul>
              )}
              {d && d.total > d.shown && !filtered && <div className="border-t px-4 py-2 text-[11.5px] text-muted-foreground" data-testid="more">{d.total - d.shown} more not shown: use the filters, search or Show all.</div>}
            </Panel>
            {sel ? <Detail key={sel.case_id + sel.status + sel.owner_user_id} c={sel} me={me} onClose={() => setSelected(null)} /> : <div className="hidden @[1100px]:block"><Panel eyebrow="Exception" title="Select a case"><div className="p-4 text-[12.5px] text-muted-foreground">Open a case to see the evidence, assign an owner and due date, and follow it to closure.</div></Panel></div>}
          </div>
        </>
      )}
    </ControlFrame>
  );
}
