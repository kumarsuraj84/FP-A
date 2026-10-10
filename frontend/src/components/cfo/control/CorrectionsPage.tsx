import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { CHECKERS, corrections, MAKERS, type CorCreate, type Correction, type CorPreview, type Me, type SourceLine } from "@/api/controlApi";
import { cn } from "@/lib/utils";
import { Skeleton } from "../common";
import { Panel } from "../panels";
import { ControlFrame } from "./ControlFrame";
import { Btn, cr, ErrMsg, Field, History, input, label, Pill, useWrite, when } from "./ui";

const REASONS = ["WRONG_CLASSIFICATION", "WRONG_MONTH", "LATE_INVOICE_TIMING", "WRONG_SOURCE_MAPPING", "MANAGEMENT_RECLASSIFICATION", "OTHER"];
const TABS: [string, string, string[]][] = [
  ["awaiting", "Awaiting approval", ["SUBMITTED"]], ["approved", "Approved", ["APPROVED"]], ["active", "Active", ["ACTIVE", "REVERSAL_REQUESTED"]],
  ["review", "Review required", ["SOURCE_REVIEW_REQUIRED"]], ["draft", "Drafts", ["DRAFT"]], ["closed", "Reversed and closed", ["REVERSED", "REJECTED", "WITHDRAWN", "SUPERSEDED_BY_SOURCE"]],
];
const sumCounts = (counts: Record<string, number> | undefined, st: string[]) => st.reduce((s, k) => s + (counts?.[k] ?? 0), 0);
const monthOf = (s: string | null) => s ?? "";

function PreviewTable({ p }: { p: CorPreview }) {
  const groups = Object.entries(p.by_group), months = Object.entries(p.by_month);
  return (
    <div data-testid="correction-preview" className="grid gap-3 text-[12.5px]">
      <div className="text-muted-foreground">{p.lines} line{p.lines === 1 ? "" : "s"} · {p.stores} store{p.stores === 1 ? "" : "s"} · source value {cr(p.source_total_cr, true)} Cr (profit-effect sign)</div>
      <table className="w-full"><thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th>Management group</th><th className="text-right">Reclass Cr</th></tr></thead>
        <tbody>{groups.map(([g, v]) => <tr key={g} className="border-t"><td className="py-1">{g}</td><td className={cn("num text-right font-semibold", Number(v) < 0 && "tone-warn")}>{cr(v, true)}</td></tr>)}
          <tr className="border-t-2 font-semibold"><td className="py-1">Net</td><td data-testid="net-group" className="num text-right">{cr(p.net_by_group_cr, true)}</td></tr></tbody></table>
      <table className="w-full"><thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th>Expense month</th><th className="text-right">Reclass Cr</th></tr></thead>
        <tbody>{months.map(([m, v]) => <tr key={m} className="border-t"><td className="py-1">{m}</td><td className={cn("num text-right font-semibold", Number(v) < 0 && "tone-warn")}>{cr(v, true)}</td></tr>)}
          <tr className="border-t-2 font-semibold"><td className="py-1">Net</td><td data-testid="net-month" className="num text-right">{cr(p.net_by_month_cr, true)}</td></tr></tbody></table>
      <p className="text-[11px] text-muted-foreground">{p.note}</p>
    </div>
  );
}

function Detail({ c, me, onClose }: { c: Correction; me: Me; onClose: () => void }) {
  const full = useQuery({ queryKey: ["corrections", "one", c.request_id, c.status], queryFn: () => corrections.one(c.request_id) });
  const hist = useQuery({ queryKey: ["corrections", "history", c.request_id, c.status], queryFn: () => corrections.history(c.request_id) });
  const [prev, setPrev] = useState<CorPreview | null>(null);
  const [reason, setReason] = useState("");
  const preview = useWrite(() => corrections.preview(c.request_id), [], setPrev);
  const act = useWrite((a: string) => corrections.act(c.request_id, a, reason || undefined), ["corrections"], () => setReason(""));
  const maker = MAKERS.includes(me.role), checker = CHECKERS.includes(me.role);
  type Act = { action: string; text: string; tone?: "primary" | "danger"; show: boolean; needsReason?: boolean };
  const all: Act[] = [
    { action: "submit", text: "Submit for approval", tone: "primary", show: c.status === "DRAFT" && maker },
    { action: "withdraw", text: "Withdraw", tone: "danger", show: (c.status === "DRAFT" || c.status === "SUBMITTED") && maker },
    { action: "approve", text: "Approve", tone: "primary", show: c.status === "SUBMITTED" && checker },
    { action: "reject", text: "Reject", tone: "danger", show: c.status === "SUBMITTED" && checker, needsReason: true },
    { action: "activate", text: "Activate (apply in the management reporting)", tone: "primary", show: c.status === "APPROVED" && checker },
    { action: "void", text: "Void", tone: "danger", show: c.status === "APPROVED" && checker, needsReason: true },
    { action: "request-reversal", text: "Request reversal", tone: "danger", show: c.status === "ACTIVE" && maker, needsReason: true },
    { action: "approve-reversal", text: "Approve reversal", tone: "primary", show: (c.status === "REVERSAL_REQUESTED" || c.status === "SOURCE_REVIEW_REQUIRED") && checker },
    { action: "reject-reversal", text: "Keep it active", show: c.status === "REVERSAL_REQUESTED" && checker, needsReason: true },
    { action: "reconfirm-source", text: "Source still wrong: reconfirm", show: c.status === "SOURCE_REVIEW_REQUIRED" && checker, needsReason: true },
  ];
  const buttons = all.filter((b) => b.show);
  const needsReason = buttons.some((b) => b.needsReason);
  const d = full.data ?? c;
  return (
    <Panel testId="correction-detail" eyebrow="Correction" title={`${label(d.scope_type)} · ${d.line_count} line${d.line_count === 1 ? "" : "s"}`} right={<button className="text-[12px] underline" onClick={onClose}>Close</button>}>
      <div className="grid gap-3 p-4 text-[12.5px]">
        <div className="flex flex-wrap items-center gap-2"><Pill value={d.status} testId="detail-status" /><span>{label(d.correction_type)} · {d.source_entity === "RETAIL" ? "SubCo" : "HoldCo"} · {label(d.reason_code)}</span></div>
        <div>{d.reason_text}</div>
        <div className="text-muted-foreground">Evidence: {d.evidence_reference} · requested {when(d.requested_at)}{d.approved_at ? ` · approved ${when(d.approved_at)}` : ""}</div>
        <div className="overflow-x-auto"><table className="w-full" data-testid="correction-lines">
          <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th>Line</th><th>From</th><th>To</th><th className="text-right">Source Cr</th><th>Source check</th></tr></thead>
          <tbody>{(full.data?.lines ?? []).map((l) => (
            <tr key={l.line_id} className="border-t"><td className="num py-1">{l.source_line_key}</td>
              <td>{l.original_group.replace(/^\d+-/, "")} · {l.original_month}</td>
              <td className="font-semibold">{(l.corrected_group ?? l.original_group).replace(/^\d+-/, "")} · {l.corrected_month ?? l.original_month}</td>
              <td className="num text-right">{cr(l.source_amount_cr, true)}</td><td className={cn(l.source_state !== "UNCHANGED" && "tone-warn")}>{label(l.source_state)}</td></tr>))}</tbody>
        </table></div>
        {needsReason && <Field label="Reason (10+ characters)"><input aria-label="Reason" className={input} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        <ErrMsg error={act.error ?? preview.error} />
        <div className="flex flex-wrap gap-2">
          {buttons.map((b) => <Btn key={b.action} testId={`act-${b.action}`} tone={b.tone} disabled={act.isPending || (b.needsReason && reason.trim().length < 10)} onClick={() => act.mutate(b.action)}>{b.text}</Btn>)}
          <Btn testId="detail-preview" onClick={() => preview.mutate(undefined)}>Impact preview</Btn>
        </div>
        {prev && <PreviewTable p={prev} />}
        <div><div className="eyebrow mb-1">Audit trail</div>{hist.data ? <History events={hist.data} /> : <Skeleton className="h-10" />}</div>
      </div>
    </Panel>
  );
}

function NewCorrection({ me, initial, onCreated }: { me: Me; initial: { entity: string; voucher: string }; onCreated: (c: Correction) => void }) {
  const [entity, setEntity] = useState(initial.entity || "RETAIL");
  const [voucher, setVoucher] = useState(initial.voucher);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [wholeVoucher, setWholeVoucher] = useState(false);
  const [group, setGroup] = useState("");
  const [month, setMonth] = useState("");
  const [reasonCode, setReasonCode] = useState("WRONG_CLASSIFICATION");
  const [text, setText] = useState("");
  const [evidence, setEvidence] = useState("");
  const [prevSet, setPrev] = useState<CorPreview | null>(null);
  const lines = useWrite(() => corrections.sourceLines(entity, voucher), [], (r) => { setPicked(new Set(r.lines.filter((l) => l.correctable).map((l) => l.cost_tag_key).slice(0, 1))); });
  const create = useWrite((submit: boolean) => (async () => {
    const all = lines.data?.lines.filter((l) => l.correctable) ?? [];
    const keys = [...picked];
    const scope: CorCreate["scope"] = wholeVoucher && keys.length === all.length ? "VOUCHER" : keys.length === 1 ? "LINE" : "BULK";
    const c = await corrections.create({ source_entity: entity, scope, ...(scope === "VOUCHER" ? { voucher } : { line_keys: keys }), corrected_group: group || undefined, corrected_month: month || undefined, reason_code: reasonCode, reason_text: text, evidence_reference: evidence });
    return submit ? corrections.act(c.request_id, "submit") : c;
  })(), ["corrections"], onCreated);
  const preview = useWrite(() => { const keys = [...picked]; return corrections.previewNew({ source_entity: entity, scope: keys.length === 1 ? "LINE" : "BULK", line_keys: keys, corrected_group: group || undefined, corrected_month: month || undefined, reason_code: reasonCode, reason_text: text || "preview of a correction", evidence_reference: evidence || "preview" }); }, [], setPrev);
  const toggle = (k: number) => setPicked((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const canMake = MAKERS.includes(me.role);
  const ready = canMake && picked.size > 0 && (group || month) && text.trim().length >= 10 && evidence.trim().length >= 3;
  return (
    <div className="grid gap-3 p-4" data-testid="correction-form">
      {!canMake && <div role="status" className="rounded border bg-muted px-3 py-2 text-[12px]">Your role ({me.role.replaceAll("_", " ")}) can read and comment but not request corrections.</div>}
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Books"><select aria-label="Books" className={input} value={entity} onChange={(e) => setEntity(e.target.value)}><option value="RETAIL">SubCo (Citykart Stores)</option><option value="VENTURES">HoldCo (Citykart Ventures)</option></select></Field>
        <Field label="Voucher number"><input aria-label="Voucher number" className={input} value={voucher} onChange={(e) => setVoucher(e.target.value)} /></Field>
        <Btn testId="load-lines" onClick={() => lines.mutate(undefined)} disabled={!voucher.trim() || lines.isPending}>Load lines</Btn>
      </div>
      <ErrMsg error={lines.error} />
      {lines.data && (
        <>
          <div className="overflow-x-auto"><table className="w-full text-[12.5px]" data-testid="source-lines">
            <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th /><th>Ledger</th><th>Current group</th><th>Month</th><th>Site</th><th className="text-right">Amount Cr</th><th>Source fingerprint</th></tr></thead>
            <tbody>{lines.data.lines.map((l: SourceLine) => (
              <tr key={l.cost_tag_key} className={cn("border-t", !l.correctable && "opacity-60")} title={l.not_correctable_reason ?? undefined}>
                <td className="py-1"><input type="checkbox" aria-label={`Select line ${l.cost_tag_key}`} disabled={!l.correctable} checked={picked.has(l.cost_tag_key)} onChange={() => toggle(l.cost_tag_key)} /></td>
                <td>{l.ledger}</td><td>{l.management_group?.replace(/^\d+-/, "") ?? "Not a P&L line"}{l.active_correction && <span className="ml-1 text-[10.5px] tone-warn">· already corrected</span>}</td><td className="num">{l.month ?? ""}</td><td className="num">{l.site_code ?? ""}</td><td className="num text-right">{cr(l.amount_cr, true)}</td><td className="num text-[11px] text-muted-foreground">{l.fingerprint ?? ""}</td></tr>))}</tbody>
          </table></div>
          <div data-testid="source-read" className="text-[11px] text-muted-foreground">Lines read from the finance data just now{lines.data.read_at ? ` (${when(lines.data.read_at)})` : ""}. The fingerprint is checked again at approval and activation; if the source changes in between, the correction stops.</div>
          <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={wholeVoucher} onChange={(e) => setWholeVoucher(e.target.checked)} /> Correct the whole voucher (every P&L line becomes a child of one request)</label>
          <div className="grid gap-3 @[900px]:grid-cols-4">
            <Field label="Corrected management group"><select aria-label="Corrected management group" className={input} value={group} onChange={(e) => setGroup(e.target.value)}><option value="">No change</option>{lines.data.groups.map((g) => <option key={g} value={g}>{g}</option>)}</select></Field>
            <Field label="Corrected expense month"><input aria-label="Corrected expense month" type="month" className={input} value={month} onChange={(e) => setMonth(e.target.value)} /></Field>
            <Field label="Reason code"><select aria-label="Reason code" className={input} value={reasonCode} onChange={(e) => setReasonCode(e.target.value)}>{REASONS.map((r) => <option key={r} value={r}>{label(r)}</option>)}</select></Field>
            <Field label="Evidence reference"><input aria-label="Evidence reference" className={input} value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Ticket, email or document" /></Field>
          </div>
          <Field label="Reason" hint="No amount is entered: the amount stays in the finance data and the correction nets to zero."><textarea aria-label="Reason" className={cn(input, "min-h-[56px]")} value={text} onChange={(e) => setText(e.target.value)} /></Field>
          <ErrMsg error={create.error ?? preview.error} />
          <div className="flex flex-wrap gap-2">
            <Btn testId="preview-correction" onClick={() => preview.mutate(undefined)} disabled={!canMake || picked.size === 0 || !(group || month) || preview.isPending}>Preview impact</Btn>
            <Btn testId="save-correction-draft" onClick={() => create.mutate(false)} disabled={!ready || create.isPending}>Save draft</Btn>
            <Btn tone="primary" testId="save-correction-submit" onClick={() => create.mutate(true)} disabled={!ready || create.isPending}>Save and submit for approval</Btn>
          </div>
          {prevSet && <PreviewTable p={prevSet} />}
        </>
      )}
    </div>
  );
}

export function CorrectionsPage() {
  const searchStr = useRouterState({ select: (x) => x.location.searchStr });
  const params = new URLSearchParams(searchStr);
  const initial = { entity: params.get("entity") ?? "RETAIL", voucher: params.get("voucher") ?? "" };
  const [tab, setTab] = useState<string>(initial.voucher ? "new" : "awaiting");
  const [selected, setSelected] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["corrections", "list"], queryFn: () => corrections.list() });
  const check = useWrite(() => corrections.sourceCheck(), ["corrections"]);
  const set = TABS.find((t) => t[0] === tab);
  const items = (list.data?.items ?? []).filter((c) => set?.[2].includes(c.status));
  const sel = list.data?.items.find((c) => c.request_id === selected) ?? null;
  return (
    <ControlFrame active="corrections" subtitle="Reclassify an existing booked line to another management group and/or expense month. The amount never changes and the correction nets to zero; the finance data stays untouched.">
      {(me) => (
        <>
          <div role="tablist" className="flex flex-wrap items-center gap-1 border-b bg-card px-3 py-1.5">
            {TABS.map(([id, text, st]) => <button key={id} role="tab" aria-selected={tab === id} data-testid={`cor-tab-${id}`} onClick={() => { setTab(id); setSelected(null); }} className={cn("rounded px-2.5 py-1 text-[12.5px] font-semibold", tab === id ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}>{text} <span className="num" data-testid={`cor-count-${id}`}>{sumCounts(list.data?.counts, st)}</span></button>)}
            <button role="tab" aria-selected={tab === "new"} data-testid="cor-tab-new" onClick={() => setTab("new")} className={cn("rounded px-2.5 py-1 text-[12.5px] font-semibold", tab === "new" ? "bg-primary text-primary-foreground" : "border text-foreground")}>New correction</button>
            <span className="ml-auto"><Btn testId="source-check" title="Re-read every active correction from the finance data (run after each data refresh)" disabled={!MAKERS.includes(me.role) || check.isPending} onClick={() => check.mutate(undefined)}>Run source check</Btn></span>
          </div>
          {check.data && <div role="status" data-testid="source-check-result" className="border-b px-4 py-1.5 text-[12px]">Checked {check.data.checked}; paused for review {check.data.changed.length}; superseded by the source {check.data.superseded.length}.</div>}
          <ErrMsg error={check.error} />
          {tab === "new" ? (
            <div className="p-3"><Panel eyebrow="Request" title="New correction"><NewCorrection me={me} initial={initial} onCreated={(c) => { setSelected(c.request_id); setTab(c.status === "DRAFT" ? "draft" : "awaiting"); }} /></Panel></div>
          ) : (
            <div className="grid gap-3 p-3 @[1100px]:grid-cols-[1.3fr_1fr]">
              <Panel testId="correction-queue" eyebrow="Queue" title={`${set?.[1] ?? ""} (${items.length})`}>
                {list.isPending ? <Skeleton className="m-4 h-[160px]" /> : list.isError ? <div className="p-4"><ErrMsg error={list.error} /></div> : (
                  <table className="w-full text-[12.5px]" data-testid="correction-table">
                    <thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-3 py-2">Requested</th><th>Scope</th><th>Change</th><th className="text-right">Lines</th><th className="text-right">Source Cr</th><th className="px-3">Status</th></tr></thead>
                    <tbody>{items.map((c) => (
                      <tr key={c.request_id} data-testid={`cor-row-${c.request_id}`} onClick={() => setSelected(c.request_id)} className={cn("cursor-pointer border-b hover:bg-muted/40", selected === c.request_id && "bg-muted/60")}>
                        <td className="px-3 py-1.5">{when(c.requested_at)}</td><td>{label(c.scope_type)}</td><td>{label(c.correction_type)}</td><td className="num text-right">{c.line_count}</td><td className="num text-right">{cr(c.source_total_cr, true)}</td><td className="px-3"><Pill value={c.status} /></td></tr>))}
                      {items.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-muted-foreground" data-testid="correction-empty">Nothing here. Corrections start from a voucher: use New correction, or Create correction on the voucher page.</td></tr>}</tbody>
                  </table>
                )}
              </Panel>
              {sel ? <Detail key={sel.request_id + sel.status} c={sel} me={me} onClose={() => setSelected(null)} /> : <div className="hidden @[1100px]:block"><Panel eyebrow="Correction" title="Select a row"><div className="p-4 text-[12.5px] text-muted-foreground">Open a correction to see its lines, preview the move between groups and months, and act on it.</div></Panel></div>}
            </div>
          )}
        </>
      )}
    </ControlFrame>
  );
}
export { monthOf };
