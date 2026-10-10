import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { close, type CloseCheck, type Me, type Readiness } from "@/api/controlApi";
import { cn } from "@/lib/utils";
import { Skeleton } from "../common";
import { Panel } from "../panels";
import { ControlFrame } from "./ControlFrame";
import { Btn, ErrMsg, Field, input, label, Pill, useWrite, when } from "./ui";

const TONE: Record<string, string> = {
  PASS: "bg-[oklch(0.94_0.06_155)] text-[oklch(0.35_0.12_155)]", ATTENTION: "bg-[oklch(0.95_0.05_85)] text-[oklch(0.4_0.09_75)]", BLOCKED: "bg-[oklch(0.55_0.2_25)] text-white",
  PENDING: "bg-[oklch(0.95_0.04_240)] text-[oklch(0.35_0.1_250)]", NA: "bg-muted text-muted-foreground",
};
const OUTCOME_TEXT: Record<string, string> = { READY: "Ready to close", NEEDS_ATTENTION: "Needs attention before the management close", BLOCKED: "Blocked: cannot be closed" };
const REVIEWERS = ["finance_reviewer", "controller", "admin"];

export function StatusPill({ s, testId }: { s: string; testId?: string }) {
  return <span data-testid={testId} data-status={s} className={cn("inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[10.5px] font-bold tracking-wide", TONE[s] ?? TONE.NA)}>{s === "NA" ? "N/A" : s}</span>;
}

const monthChoices = (): string[] => {
  const out: string[] = [];
  const d = new Date();
  for (let i = 0; i < 14; i++) {
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
    d.setMonth(d.getMonth() - 1);
  }
  return out;
};
const lastMonth = () => { const d = new Date(); d.setMonth(d.getMonth() - 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

function Row({ c, me, onSign }: { c: CloseCheck; me: Me; onSign: (c: CloseCheck, decision: string, comment: string) => void }) {
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  const reviewer = REVIEWERS.includes(me.role) || me.role === "fpa_manager";
  const canCertify = me.role === "controller" || me.role === "admin";
  const decision = c.manual ? "SIGNED_OFF" : "OVERRIDDEN";
  const needs = c.status === "ATTENTION" || c.status === "PENDING";
  const allowed = c.key === "pnl_certification" ? canCertify : reviewer;
  return (
    <>
      <tr data-testid={`check-${c.key}`} data-effective={c.effective} className="border-b align-top">
        <td className="px-4 py-2 font-medium">{c.title}</td>
        <td className="px-2 py-2"><StatusPill s={c.effective} testId={`status-${c.key}`} />{c.effective !== c.status && <span className="ml-1 text-[10.5px] text-muted-foreground">({c.status.toLowerCase()}, {c.signoff?.decision === "OVERRIDDEN" ? "overridden" : "signed off"})</span>}</td>
        <td className="px-2 py-2 text-muted-foreground">{c.summary}{c.signoff?.stale && <span className="ml-1 font-semibold tone-warn">Earlier sign-off is stale: the evidence changed.</span>}</td>
        <td className="space-x-2 whitespace-nowrap px-3 py-2 text-right">
          {c.link && <a className="text-primary underline" href={c.link}>Open</a>}
          {needs && c.effective !== "PASS" && allowed && <Btn testId={`sign-${c.key}`} onClick={() => setOpen(!open)}>{c.manual ? "Sign off" : "Override"}</Btn>}
          {c.signoff && c.effective === "PASS" && c.signoff.by && <span className="text-[11px] text-muted-foreground">{c.signoff.by} · {when(c.signoff.at)}</span>}
        </td>
      </tr>
      {open && (
        <tr className="border-b bg-muted/30"><td colSpan={4} className="px-4 py-2">
          <div className="flex flex-wrap items-end gap-2">
            <Field label={c.manual ? "Sign-off comment (10+ characters)" : "Reason for the override (10+ characters)"} className="min-w-[320px] flex-1"><input aria-label="Comment" className={input} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
            <Btn tone="primary" testId={`confirm-${c.key}`} disabled={comment.trim().length < 10} onClick={() => { onSign(c, decision, comment); setOpen(false); setComment(""); }}>{c.manual ? "Confirm sign-off" : "Confirm override"}</Btn>
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">The sign-off records the evidence you are looking at; if it changes later the item opens again.</p>
        </td></tr>
      )}
    </>
  );
}

function Body({ me }: { me: Me }) {
  const [entity, setEntity] = useState<"SUBCO" | "HOLDCO">("SUBCO");
  const [month, setMonth] = useState(lastMonth());
  const [reason, setReason] = useState("");
  const months = useMemo(monthChoices, []);
  const q = useQuery({ queryKey: ["close", "readiness", entity, month], queryFn: () => close.readiness(entity, month) });
  const hist = useQuery({ queryKey: ["close", "history", entity, month, q.data?.period_status], queryFn: () => close.history(entity, month) });
  const sign = useWrite((a: { c: CloseCheck; decision: string; comment: string }) => close.signoff(entity, month, a.c.key, a.decision, a.comment), ["close"]);
  const act = useWrite((action: string) => close.period(action, entity, month, reason), ["close"], () => setReason(""));
  const d: Readiness | undefined = q.data;
  const st = d?.period_status ?? "OPEN";
  const btn = (action: string, text: string, show: boolean, enabled: boolean, tone?: "primary" | "danger", why?: string) => show && <Btn key={action} testId={`period-${action}`} tone={tone} title={enabled ? undefined : why} disabled={!enabled || act.isPending || reason.trim().length < 10} onClick={() => act.mutate(action)}>{text}</Btn>;
  return (
    <div className="grid gap-3 p-3">
      <div className="flex flex-wrap items-end gap-3 rounded-md border bg-card px-4 py-2.5" data-testid="close-controls">
        <Field label="Entity"><select aria-label="Entity" className={input} value={entity} onChange={(e) => setEntity(e.target.value as "SUBCO" | "HOLDCO")}><option value="SUBCO">SubCo (Citykart Stores)</option><option value="HOLDCO">HoldCo (Citykart Ventures)</option></select></Field>
        <Field label="Month"><select aria-label="Month" className={input} value={month} onChange={(e) => setMonth(e.target.value)}>{months.map((m) => <option key={m} value={m}>{m}</option>)}</select></Field>
        {d && <>
          <div><div className="eyebrow">Period status</div><Pill value={st === "MANAGEMENT_CLOSED" ? "APPROVED" : st === "FINAL_CLOSED" ? "ACTIVE" : st === "SOFT_CLOSED" ? "REVIEW" : "DRAFT"} testId="period-status" /> <span className="text-[11.5px]" data-testid="period-status-text">{label(st)}</span></div>
          <div><div className="eyebrow">Management P&L</div><span data-testid="pnl-state" className={cn("rounded px-1.5 py-0.5 text-[10.5px] font-bold", d.management_pnl === "COMPLETE" ? TONE.PASS : TONE.ATTENTION)}>{d.management_pnl}</span></div>
          <div><div className="eyebrow">Readiness</div><span className="num text-[18px] font-semibold" data-testid="readiness-pct">{d.readiness_pct}%</span></div>
        </>}
      </div>
      {q.isPending ? <Skeleton className="h-[260px]" /> : q.isError ? <ErrMsg error={q.error} /> : d && (
        <>
          <div data-testid="close-outcome" data-outcome={d.outcome} className={cn("rounded-md border px-4 py-2.5 text-[13px] font-semibold", d.outcome === "READY" && "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)]", d.outcome === "BLOCKED" && "border-[oklch(0.7_0.12_25)] bg-[oklch(0.97_0.03_25)]", d.outcome === "NEEDS_ATTENTION" && "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)]")}>
            Can Finance trust and close {d.month}? {OUTCOME_TEXT[d.outcome]}.
          </div>
          <section data-testid="close-tiles" className="grid grid-cols-2 gap-2 @[900px]:grid-cols-5">
            {d.checks.map((c) => <div key={c.key} className="rounded-md border bg-card px-3 py-2"><div className="text-[11px] text-muted-foreground">{c.title}</div><StatusPill s={c.effective} /></div>)}
          </section>
          {d.blockers.length > 0 && (
            <Panel testId="close-blockers" eyebrow="Prevents the management close" title={`Blockers (${d.blockers.length})`}>
              <ol className="list-decimal space-y-1 px-8 py-3 text-[12.5px]">{d.blockers.map((b) => <li key={b.key}><b>{b.title}</b>: {b.summary}</li>)}</ol>
            </Panel>
          )}
          <Panel testId="close-checklist" eyebrow="Checklist" title="What must be true to close the month">
            <div className="overflow-x-auto"><table className="w-full text-[12.5px]">
              <thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-4 py-2">Area</th><th className="px-2">Status</th><th className="px-2">Detail</th><th /></tr></thead>
              <tbody>{d.checks.map((c) => <Row key={c.key + c.signature + String(c.effective)} c={c} me={me} onSign={(cc, decision, comment) => sign.mutate({ c: cc, decision, comment })} />)}</tbody>
            </table></div>
            <p className="border-t px-4 py-2 text-[11px] text-muted-foreground">{d.note}</p>
          </Panel>
          <Panel eyebrow="Period" title="Close actions">
            <div className="grid gap-3 p-4">
              <Field label="Reason (10+ characters, kept in the audit trail)"><input aria-label="Reason" className={input} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
              <ErrMsg error={sign.error ?? act.error} />
              <div className="flex flex-wrap gap-2">
                {btn("soft-close", "Soft close", st === "OPEN" || st === "REOPENED", true, undefined)}
                {btn("management-close", "Management close", st === "SOFT_CLOSED", d.can_management_close, "primary", "Blockers or open items remain")}
                {btn("final-close", "Final close", st === "MANAGEMENT_CLOSED", d.can_final_close, "primary", "Needs every item signed off, including the P&L certification")}
                {btn("reopen", "Reopen", st === "SOFT_CLOSED" || st === "MANAGEMENT_CLOSED" || st === "FINAL_CLOSED", true, "danger")}
              </div>
              <p className="text-[11px] text-muted-foreground">Soft close: a manager. Management close: a finance reviewer. Final close and reopen: a controller or administrator. The database enforces this.</p>
              {hist.data && hist.data.length > 0 && <ol data-testid="period-history" className="space-y-0.5 text-[12px]">{hist.data.map((h, i) => <li key={i}><span className="num text-muted-foreground">{when(h.at)}</span> <b>{label(h.to_status)}</b> <span className="text-muted-foreground">{h.actor ?? ""}</span> · {h.reason}</li>)}</ol>}
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}

export function ClosePage() {
  return <ControlFrame active="close" subtitle="Month-end close: can Finance trust and close this period? Blockers decide, not the percentage.">{(me) => <Body me={me} />}</ControlFrame>;
}
