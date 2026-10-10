import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { sourcefix, type FixCandidate, type Me } from "@/api/controlApi";
import { cn } from "@/lib/utils";
import { Skeleton } from "../common";
import { Panel } from "../panels";
import { ControlFrame } from "./ControlFrame";
import { Btn, cr, ErrMsg, Field, History, input, label, Pill, useWrite } from "./ui";

const ISSUE: Record<string, string> = { RECURRING_GROUP_RECLASS: "Recurring group reclass", RECURRING_MONTH_SHIFT: "Recurring month shift", RECURRING_MAPPING_CHANGE: "Recurring mapping change" };
const VALIDATION_TEXT: Record<string, string> = { NOT_VALIDATED: "Not yet validated", PENDING: "Fix recorded: waiting for a complete month to check", PASSED: "Validated: the pattern stopped", FAILED: "Failed: the pattern came back after the fix" };
const TABS: [string, string][] = [["open", "Open"], ["fixed", "Fix recorded"], ["validated", "Validated"], ["dismissed", "Dismissed"]];
const today = () => new Date().toISOString().slice(0, 10);

function Detail({ c, me, onClose }: { c: FixCandidate; me: Me; onClose: () => void }) {
  const hist = useQuery({ queryKey: ["sourcefix", "history", c.candidate_id, c.status], queryFn: () => sourcefix.history(c.candidate_id) });
  const [reason, setReason] = useState("");
  const [fixDate, setFixDate] = useState(today());
  const [fin, setFin] = useState(c.finance_owner ?? "");
  const [data, setData] = useState(c.data_owner ?? "");
  const act = useWrite((x: { a: string; body?: { comment?: string; fix_date?: string } }) => sourcefix.act(c.candidate_id, x.a, x.body), ["sourcefix"], () => setReason(""));
  const owners = useWrite(() => sourcefix.owners(c.candidate_id, fin, data), ["sourcefix"]);
  const worker = me.role !== "viewer";
  const live = c.status === "OPEN" || c.status === "ACKNOWLEDGED" || c.status === "STILL_RECURRING";
  return (
    <Panel testId="fix-detail" eyebrow={ISSUE[c.issue_type]} title={c.subject_name ?? c.subject_key} right={<button className="text-[12px] underline" onClick={onClose}>Close</button>}>
      <div className="grid gap-3 p-4 text-[12.5px]">
        <div className="flex flex-wrap items-center gap-2"><Pill value={c.status === "FIX_IMPLEMENTED" ? "APPROVED" : c.status === "VALIDATED" ? "ACTIVE" : c.status === "STILL_RECURRING" ? "REJECTED" : c.status === "DISMISSED" ? "WITHDRAWN" : c.status === "ACKNOWLEDGED" ? "REVIEW" : "DRAFT"} testId="detail-status" /> <span data-testid="detail-status-text">{label(c.status)}</span><span className="num">score {Number(c.score).toFixed(0)}</span></div>
        <div data-testid="fix-recommendation" className="font-medium">{c.recommended_fix}</div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5" data-testid="fix-evidence">
          {c.from_value && <><dt className="text-muted-foreground">From</dt><dd>{c.from_value} → {c.to_value}</dd></>}
          <dt className="text-muted-foreground">Seen</dt><dd>{c.months_affected} month(s){c.consecutive_months ? `, ${c.consecutive_months} in a row` : ""}{c.first_seen ? `, ${c.first_seen} to ${c.last_seen}` : ""}</dd>
          {c.line_count > 0 && <><dt className="text-muted-foreground">Breadth</dt><dd>{c.correction_count} corrections, {c.line_count} lines, {c.site_count} sites, {cr(c.cumulative_amount_cr)} Cr moved</dd></>}
          <dt className="text-muted-foreground">Evidence</dt><dd data-testid="origin-ids">{c.origin_ids.length} originating {c.issue_type === "RECURRING_MAPPING_CHANGE" ? "mapping version(s)" : "correction(s)"}: <span className="num text-[11px] text-muted-foreground">{c.origin_ids.slice(0, 3).map((x) => x.slice(0, 8)).join(", ")}{c.origin_ids.length > 3 ? " …" : ""}</span></dd>
          <dt className="text-muted-foreground">Validation</dt><dd data-testid="validation" data-state={c.post_fix_validation}>{VALIDATION_TEXT[c.post_fix_validation]}{c.source_fix_date ? ` (fix dated ${c.source_fix_date})` : ""}</dd>
        </dl>
        <p className="text-[11px] text-muted-foreground">{c.advisory} Thresholds {c.threshold_version} are uncalibrated.</p>
        {worker && (
          <div className="grid gap-2 rounded border p-3">
            <div className="grid gap-2 @[700px]:grid-cols-2">
              <Field label="Finance owner"><input aria-label="Finance owner" className={input} value={fin} onChange={(e) => setFin(e.target.value)} /></Field>
              <Field label="Data owner (extraction team)"><input aria-label="Data owner" className={input} value={data} onChange={(e) => setData(e.target.value)} /></Field>
            </div>
            <div><Btn testId="save-owners" onClick={() => owners.mutate(undefined)} disabled={owners.isPending}>Save owners</Btn></div>
          </div>
        )}
        {worker && (live || c.status === "FIX_IMPLEMENTED") && (
          <div className="grid gap-2">
            {live && <div className="flex flex-wrap items-end gap-2"><Field label="Date of the source fix"><input aria-label="Fix date" type="date" className={input} value={fixDate} max={today()} onChange={(e) => setFixDate(e.target.value)} /></Field>
              <Field label="Note" className="min-w-[240px] flex-1"><input aria-label="Fix note" className={input} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What was changed upstream" /></Field>
              <Btn testId="act-implemented" tone="primary" onClick={() => act.mutate({ a: "implemented", body: { fix_date: fixDate, comment: reason || undefined } })} disabled={!fixDate || act.isPending}>Record source fix</Btn></div>}
            <ErrMsg error={act.error ?? owners.error} />
            <div className="flex flex-wrap gap-2">
              {c.status === "OPEN" && <Btn testId="act-acknowledge" onClick={() => act.mutate({ a: "acknowledge" })}>Acknowledge</Btn>}
              {live && <Btn testId="act-dismiss" tone="danger" disabled={reason.trim().length < 10} title="Needs a reason in the note box" onClick={() => act.mutate({ a: "dismiss", body: { comment: reason } })}>Dismiss</Btn>}
            </div>
          </div>
        )}
        <div><div className="eyebrow mb-1">History</div>{hist.data ? <History events={hist.data} /> : <Skeleton className="h-10" />}</div>
      </div>
    </Panel>
  );
}

export function SourceFixesPage() {
  const [tab, setTab] = useState("open");
  const [selected, setSelected] = useState<string | null>(null);
  const statusFor: Record<string, string | undefined> = { open: undefined, fixed: "FIX_IMPLEMENTED", validated: "VALIDATED", dismissed: "DISMISSED" };
  const q = useQuery({ queryKey: ["sourcefix", "list", tab], queryFn: () => sourcefix.list({ status: statusFor[tab] }) });
  const refresh = useWrite(() => sourcefix.refresh(), ["sourcefix"]);
  const [copied, setCopied] = useState("");
  const exp = useWrite(() => sourcefix.exportText(), [], (r) => { void navigator.clipboard?.writeText(r.text); setCopied(r.text); });
  const d = q.data;
  const sel = d?.items.find((x) => x.candidate_id === selected) ?? null;
  return (
    <ControlFrame active="sourcefix" subtitle="Where the same correction or mapping change keeps coming back, the fix belongs upstream. Ranked by recurrence, materiality and breadth. Advisory only: this queue never changes a mapping, a correction or finance data.">
      {(me) => (
        <>
          <div role="tablist" className="flex flex-wrap items-center gap-1 border-b bg-card px-3 py-1.5">
            {TABS.map(([id, text]) => <button key={id} role="tab" aria-selected={tab === id} data-testid={`fix-tab-${id}`} onClick={() => { setTab(id); setSelected(null); }} className={cn("rounded px-2.5 py-1 text-[12.5px] font-semibold", tab === id ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}>{text}</button>)}
            <span className="ml-auto flex items-center gap-2">
              {d && <span data-testid="fix-calibration" className="text-[11px] text-muted-foreground">{d.calibration_status.toLowerCase()} · thresholds {d.threshold_version}</span>}
              <Btn testId="export-fixes" onClick={() => exp.mutate(undefined)} title="Copy the open list as plain text for the extraction team">Copy list for extraction</Btn>
              <Btn testId="refresh-fixes" tone="primary" disabled={me.role === "viewer" || refresh.isPending} onClick={() => refresh.mutate(undefined)}>{refresh.isPending ? "Checking…" : "Refresh candidates"}</Btn>
            </span>
          </div>
          {refresh.data && <div role="status" data-testid="refresh-result" className="border-b px-4 py-1.5 text-[12px]">{refresh.data.raised} new, {refresh.data.updated} updated; fixes validated {refresh.data.validated}, still recurring {refresh.data.still_recurring}.</div>}
          {copied && <div role="status" data-testid="copied" className="border-b px-4 py-1.5 text-[12px]">The list is on your clipboard ({copied.split("\n").filter((l) => /^\d+\./.test(l)).length} candidates).</div>}
          <ErrMsg error={refresh.error ?? exp.error} />
          <div className="grid gap-3 p-3 @[1100px]:grid-cols-[1.3fr_1fr]">
            <Panel testId="fix-list" eyebrow="Ranked" title={`Source fix candidates${d ? ` (${d.total})` : ""}`}>
              {q.isPending ? <Skeleton className="m-4 h-[160px]" /> : q.isError ? <div className="p-4"><ErrMsg error={q.error} /></div> : (
                <ul data-testid="fix-rows">
                  {d!.items.map((c) => (
                    <li key={c.candidate_id}><button data-testid={`fix-${c.candidate_id}`} onClick={() => setSelected(c.candidate_id)} className={cn("flex w-full items-start gap-3 border-b px-4 py-2 text-left hover:bg-muted/40", selected === c.candidate_id && "bg-muted/60")}>
                      <span className="num w-8 shrink-0 text-[13px] font-semibold">{Number(c.score).toFixed(0)}</span>
                      <span className="min-w-0 flex-1"><span className="block font-medium">{c.subject_name ?? c.subject_key}</span><span className="block text-[11.5px] text-muted-foreground">{ISSUE[c.issue_type]}{c.line_count ? ` · ${c.line_count} lines · ${c.months_affected} months` : ` · ${c.months_affected} changes`}{c.data_owner ? ` · ${c.data_owner}` : " · no data owner"}</span></span>
                      <Pill value={c.status === "FIX_IMPLEMENTED" ? "APPROVED" : c.status === "VALIDATED" ? "ACTIVE" : c.status === "STILL_RECURRING" ? "REJECTED" : c.status === "ACKNOWLEDGED" ? "REVIEW" : "DRAFT"} /></button></li>
                  ))}
                  {d!.items.length === 0 && <li className="px-4 py-6 text-center text-muted-foreground" data-testid="fix-empty">No candidates here. Refresh to check the corrections and mapping changes.</li>}
                </ul>
              )}
            </Panel>
            {sel ? <Detail key={sel.candidate_id + sel.status} c={sel} me={me} onClose={() => setSelected(null)} /> : <div className="hidden @[1100px]:block"><Panel eyebrow="Candidate" title="Select a row"><div className="p-4 text-[12.5px] text-muted-foreground">Open a candidate to see the evidence, record the source fix and follow the validation.</div></Panel></div>}
          </div>
        </>
      )}
    </ControlFrame>
  );
}
