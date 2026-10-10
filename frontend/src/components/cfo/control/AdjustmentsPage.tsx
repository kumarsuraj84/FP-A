import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { adjustments, CHECKERS, MAKERS, type AdjInput, type Adjustment, type Calendar, type Impact, type Me } from "@/api/controlApi";
import { cn } from "@/lib/utils";
import { Skeleton } from "../common";
import { Panel } from "../panels";
import { ControlFrame } from "./ControlFrame";
import { Btn, cr, ErrMsg, Field, History, input, label, Pill, useWrite, when } from "./ui";

export const LINES: { key: string; label: string }[] = [
  { key: "other_operating_income", label: "Other operating income" }, { key: "material_cost", label: "Material cost" }, { key: "rent", label: "Rent" }, { key: "employee_cost", label: "Employee cost" },
  { key: "power_fuel", label: "Power and fuel" }, { key: "advertisement", label: "Advertisement and sales promotion" }, { key: "freight", label: "Freight forwarding" }, { key: "other_expenses", label: "Other expenses" },
  { key: "one_time", label: "One-time expense" }, { key: "interest_income", label: "Interest income" }, { key: "finance_cost", label: "Finance cost" },
];
const TYPES = ["PROVISION", "MANAGEMENT_JOURNAL", "INCOME_ADJUSTMENT", "ONE_TIME", "INTERCOMPANY_ELIMINATION", "COGS_MANAGEMENT_CORRECTION"];
const ENTITIES = [["SUBCO", "SubCo (Citykart Stores)"], ["HOLDCO", "HoldCo (Citykart Ventures)"], ["CONSOLIDATED", "Consolidated (eliminations only)"]];
const lineLabel = (k: string) => LINES.find((l) => l.key === k)?.label ?? k;
const STATE_MARK: Record<string, string> = { active: "●", proposed: "◐", missing: "!", future: "○", locked: "🔒", paused: "⏸", "n/a": "" };
const STATE_TEXT: Record<string, string> = { active: "Active", proposed: "Proposed, not yet in the management total", missing: "Missing: due and nothing exists", future: "Future", locked: "Period locked: a controller must reopen it", paused: "Template paused", "n/a": "Outside the template" };

const thisMonth = () => new Date().toISOString().slice(0, 7);
const blank = (): AdjInput & { name?: string; start_month?: string; end_month?: string } => ({
  month: thisMonth(), entity: "SUBCO", management_line: "employee_cost", location_type: "STORES", adjustment_type: "PROVISION", basis_type: "FIXED", effect: "COST", amount_rupees: "", rate: "", rate_metric: "net_sales",
  supporting_reference: "", narrative: "", linked_policy: "",
});

function ImpactTable({ d }: { d: Impact }) {
  const names: Record<string, string> = { consolidated: "Consolidated", subco: "SubCo", holdco: "HoldCo" };
  const rows = ["total_store_expenses", "store_ebitda", "total_corporate", "corporate_ebitda"];
  const rl: Record<string, string> = { total_store_expenses: "Total store expenses", store_ebitda: "Store EBITDA", total_corporate: "Total corporate cost", corporate_ebitda: "Corporate EBITDA" };
  return (
    <div data-testid="impact" className="space-y-2 text-[12.5px]">
      <div className="text-muted-foreground">Month {d.month} · {lineLabel(d.line)} · amount {cr(d.amount_cr, true)} Cr{d.already_in_management_total ? " · already in the management total" : ""}</div>
      {Object.entries(d.views).map(([v, cells]) => (
        <table key={v} className="w-full border-separate border-spacing-0" data-testid={`impact-${v}`}>
          <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="py-1">{names[v] ?? v}</th><th className="text-right">Before</th><th className="text-right">Adjustment</th><th className="text-right">After</th></tr></thead>
          <tbody>
            {[d.line === "revenue" ? "revenue" : Object.keys(cells).find((k) => k === lineKeyFor(d)) ?? "", ...rows].filter((k, i, a) => k && cells[k] && a.indexOf(k) === i).map((k) => (
              <tr key={k} className="border-t"><td className="py-1">{rl[k] ?? lineLabel(k)}</td><td className="num text-right">{cr(cells[k].before)}</td><td className={cn("num text-right font-semibold", Number(cells[k].change) < 0 && "tone-warn")}>{cr(cells[k].change, true)}</td><td className="num text-right">{cr(cells[k].after)}</td></tr>
            ))}
          </tbody>
        </table>
      ))}
      <p className="text-[11px] text-muted-foreground">{d.note}</p>
    </div>
  );
}
const lineKeyFor = (d: Impact) => (d.location_type === "STORES" ? d.line : d.location_type === "DC" ? "dc_cost" : "ho_cost");

function AdjForm({ me, initial, template, onSaved }: { me: Me; initial?: Adjustment; template?: boolean; onSaved: (a: Adjustment | null) => void }) {
  const [f, setF] = useState(() => (initial ? { ...blank(), month: initial.month, entity: initial.entity, management_line: initial.management_line, location_type: initial.location_type, adjustment_type: initial.adjustment_type,
    basis_type: initial.basis_type, effect: initial.effect, amount_rupees: initial.basis_type === "RATE" ? "" : String(Math.abs(Number(initial.amount_rupees))), rate: initial.rate ?? "", rate_metric: initial.rate_metric ?? "net_sales",
    supporting_reference: initial.supporting_reference, narrative: initial.narrative, linked_policy: initial.linked_policy ?? "" } : blank()));
  const [impact, setImpact] = useState<Impact | null>(null);
  const set = (k: string, v: string) => { setF((x) => ({ ...x, [k]: v })); setImpact(null); };
  const body = (): AdjInput => ({ ...f, amount_rupees: f.basis_type === "RATE" ? undefined : f.amount_rupees, rate: f.basis_type === "RATE" ? f.rate : undefined, rate_metric: f.basis_type === "RATE" ? f.rate_metric : undefined, linked_policy: f.linked_policy || undefined });
  const preview = useWrite(() => adjustments.preview(body()), [], (r) => setImpact(r));
  const save = useWrite((submit: boolean) => (async () => {
    if (template) {
      await adjustments.createTemplate({ ...body(), name: f.name ?? "", start_month: f.month, end_month: f.end_month || undefined });
      return null;
    }
    const a = initial ? await adjustments.update(initial.adjustment_id, body()) : await adjustments.create(body());
    return submit ? adjustments.act(a.adjustment_id, "submit") : a;
  })(), ["adjustments"], (a) => onSaved(a));
  const canMake = MAKERS.includes(me.role);
  const rate = f.basis_type === "RATE";
  return (
    <div className="grid gap-3 p-4" data-testid={template ? "template-form" : "adjustment-form"}>
      {!canMake && <div role="status" className="rounded border bg-muted px-3 py-2 text-[12px]">Your role ({me.role.replaceAll("_", " ")}) can read and comment but not create adjustments.</div>}
      <div className="grid grid-cols-2 gap-3 @[900px]:grid-cols-4">
        {template && <Field label="Template name" className="col-span-2"><input aria-label="Template name" className={input} value={f.name ?? ""} onChange={(e) => set("name", e.target.value)} placeholder="Gratuity provision, stores" /></Field>}
        <Field label={template ? "Start month" : "Reporting month"}><input aria-label="Reporting month" type="month" className={input} value={f.month} onChange={(e) => set("month", e.target.value)} /></Field>
        {template && <Field label="End month (optional)"><input aria-label="End month" type="month" className={input} value={f.end_month ?? ""} onChange={(e) => set("end_month", e.target.value)} /></Field>}
        <Field label="Entity"><select aria-label="Entity" className={input} value={f.entity} onChange={(e) => set("entity", e.target.value)}>{ENTITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label="Management line"><select aria-label="Management line" className={input} value={f.management_line} onChange={(e) => set("management_line", e.target.value)}>{LINES.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}</select></Field>
        <Field label="Location type"><select aria-label="Location type" className={input} value={f.location_type} onChange={(e) => set("location_type", e.target.value)}><option value="STORES">Stores</option><option value="DC">DC</option><option value="HO">HO</option></select></Field>
        <Field label="Adjustment type"><select aria-label="Adjustment type" className={input} value={f.adjustment_type} onChange={(e) => set("adjustment_type", e.target.value)}>{TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}</select></Field>
        <Field label="Effect on profit"><select aria-label="Effect on profit" className={input} value={f.effect} onChange={(e) => set("effect", e.target.value)}><option value="COST">Cost (reduces profit)</option><option value="INCOME">Income (raises profit)</option></select></Field>
        <Field label="Basis"><select aria-label="Basis" className={input} value={f.basis_type} onChange={(e) => set("basis_type", e.target.value)}><option value="FIXED">Fixed amount</option><option value="RATE">Percentage of a metric</option>{!template && <option value="MANUAL">Manual amount</option>}</select></Field>
        {rate ? (
          <>
            <Field label="Rate (percent)" hint="1 means 1 percent"><input aria-label="Rate" className={input} inputMode="decimal" value={f.rate ? String(Number(f.rate) * 100) : ""} onChange={(e) => set("rate", e.target.value === "" ? "" : String(Number(e.target.value) / 100))} /></Field>
            <Field label="Rate basis"><select aria-label="Rate basis" className={input} value={f.rate_metric} onChange={(e) => set("rate_metric", e.target.value)}><option value="net_sales">Net sales (stores)</option><option value="material_cost">Material cost (stores)</option></select></Field>
          </>
        ) : (
          <Field label="Amount (₹, positive)" hint="The effect says whether it is a cost or income"><input aria-label="Amount" className={input} inputMode="decimal" value={f.amount_rupees ?? ""} onChange={(e) => set("amount_rupees", e.target.value)} /></Field>
        )}
        <Field label="Supporting reference" hint="Document, policy, email or workbook cell"><input aria-label="Supporting reference" className={input} value={f.supporting_reference} onChange={(e) => set("supporting_reference", e.target.value)} /></Field>
        <Field label="Linked policy (optional)"><input aria-label="Linked policy" className={input} value={f.linked_policy ?? ""} onChange={(e) => set("linked_policy", e.target.value)} /></Field>
      </div>
      <Field label="Narrative" hint={f.basis_type === "MANUAL" ? "A manual amount needs a fuller explanation (30+ characters)" : "At least 10 characters"}><textarea aria-label="Narrative" className={cn(input, "min-h-[60px]")} value={f.narrative} onChange={(e) => set("narrative", e.target.value)} /></Field>
      <ErrMsg error={preview.error ?? save.error} />
      <div className="flex flex-wrap items-center gap-2">
        <Btn testId="preview-impact" onClick={() => preview.mutate(undefined)} disabled={preview.isPending}>Preview impact</Btn>
        {template ? <Btn tone="primary" testId="save-template" disabled={!canMake || save.isPending} onClick={() => save.mutate(false)}>Save template</Btn> : (
          <>
            <Btn testId="save-draft" disabled={!canMake || save.isPending} onClick={() => save.mutate(false)}>Save draft</Btn>
            <Btn tone="primary" testId="save-submit" disabled={!canMake || save.isPending} onClick={() => save.mutate(true)}>Save and submit for review</Btn>
          </>
        )}
      </div>
      {impact && <ImpactTable d={impact} />}
    </div>
  );
}

function Detail({ a, me, onClose }: { a: Adjustment; me: Me; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const hist = useQuery({ queryKey: ["adjustments", "history", a.adjustment_id, a.status], queryFn: () => adjustments.history(a.adjustment_id) });
  const [impact, setImpact] = useState<Impact | null>(null);
  const prev = useWrite(() => adjustments.previewSaved(a.adjustment_id), [], setImpact);
  const act = useWrite((x: string) => adjustments.act(a.adjustment_id, x, reason || undefined), ["adjustments"], () => setReason(""));
  const maker = MAKERS.includes(me.role), checker = CHECKERS.includes(me.role);
  type Act = { action: string; text: string; tone?: "primary" | "danger"; show: boolean; needsReason?: boolean };
  const all: Act[] = [
    { action: "submit", text: "Submit for review", tone: "primary", show: a.status === "DRAFT" && maker },
    { action: "withdraw", text: "Withdraw", tone: "danger", show: (a.status === "DRAFT" || a.status === "REVIEW") && maker },
    { action: "approve", text: "Approve", tone: "primary", show: a.status === "REVIEW" && checker },
    { action: "reject", text: "Reject", tone: "danger", show: a.status === "REVIEW" && checker, needsReason: true },
    { action: "activate", text: "Activate (counts in the management total)", tone: "primary", show: a.status === "APPROVED" && checker },
    { action: "request-reversal", text: "Request reversal", tone: "danger", show: a.status === "ACTIVE" && maker, needsReason: true },
    { action: "approve-reversal", text: "Approve reversal", tone: "primary", show: a.status === "REVERSAL_REQUESTED" && checker },
    { action: "reject-reversal", text: "Keep it active", show: a.status === "REVERSAL_REQUESTED" && checker, needsReason: true },
  ];
  const buttons = all.filter((b) => b.show);
  const needsReason = buttons.some((b) => b.needsReason);
  return (
    <Panel testId="adjustment-detail" eyebrow="Adjustment" title={`${lineLabel(a.management_line)} · ${a.month}`} right={<button className="text-[12px] underline" onClick={onClose}>Close</button>}>
      <div className="grid gap-3 p-4 text-[12.5px]">
        <div className="flex flex-wrap items-center gap-2"><Pill value={a.status} testId="detail-status" />{a.provisional && <span className="rounded bg-[oklch(0.95_0.05_85)] px-1.5 text-[10.5px] font-bold text-[oklch(0.4_0.09_75)]">PROVISIONAL</span>}
          <span>{label(a.adjustment_type)} · {a.entity} · {a.location_type} · {a.basis_type === "RATE" ? `${Number(a.rate) * 100}% of ${a.rate_metric}` : label(a.basis_type)}</span></div>
        <div>Amount <b className="num" data-testid="detail-amount">{cr(a.amount_cr, true)} Cr</b> <span className="text-muted-foreground">({a.effect === "COST" ? "cost" : "income"}; ₹{Number(a.amount_rupees).toLocaleString("en-IN")})</span>{a.metric_snapshot?.partial_month && <span className="ml-2 text-[11px] tone-warn">basis month not complete</span>}</div>
        <div className="text-muted-foreground">Reference: {a.supporting_reference}{a.linked_policy ? ` · policy ${a.linked_policy}` : ""}</div>
        <div>{a.narrative}</div>
        <div className="text-muted-foreground">Created {when(a.created_at)}{a.approved_at ? ` · approved ${when(a.approved_at)}` : ""}{a.activated_at ? ` · active since ${when(a.activated_at)}` : ""}</div>
        {needsReason && <Field label="Reason (10+ characters)"><input aria-label="Reason" className={input} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        <ErrMsg error={act.error ?? prev.error} />
        <div className="flex flex-wrap gap-2">
          {buttons.map((b) => <Btn key={b.action} testId={`act-${b.action}`} tone={b.tone} disabled={act.isPending || (b.needsReason && reason.trim().length < 10)} onClick={() => act.mutate(b.action)}>{b.text}</Btn>)}
          <Btn testId="detail-preview" onClick={() => prev.mutate(undefined)}>Impact on EBITDA</Btn>
        </div>
        {impact && <ImpactTable d={impact} />}
        <div><div className="eyebrow mb-1">History</div>{hist.data ? <History events={hist.data} /> : <Skeleton className="h-10" />}</div>
      </div>
    </Panel>
  );
}

function Register({ me, selected, setSelected }: { me: Me; selected: string | null; setSelected: (id: string | null) => void }) {
  const [status, setStatus] = useState("");
  const [month, setMonth] = useState("");
  const list = useQuery({ queryKey: ["adjustments", "list", status, month], queryFn: () => adjustments.list({ status: status || undefined, month: month || undefined, limit: 200 }) });
  const sel = list.data?.items.find((x) => x.adjustment_id === selected) ?? null;
  return (
    <div className="grid gap-3 p-3 @[1100px]:grid-cols-[1.4fr_1fr]">
      <Panel testId="adjustment-register" eyebrow="Register" title={`Adjustments${list.data ? ` (${list.data.total})` : ""}`}
        right={<div className="flex gap-2 text-[12px]"><select aria-label="Status filter" className={input} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{["DRAFT", "REVIEW", "APPROVED", "ACTIVE", "REJECTED", "WITHDRAWN", "REVERSAL_REQUESTED", "REVERSED"].map((s) => <option key={s} value={s}>{label(s)}</option>)}</select><input aria-label="Month filter" type="month" className={input} value={month} onChange={(e) => setMonth(e.target.value)} /></div>}>
        {list.isPending ? <Skeleton className="m-4 h-[200px]" /> : list.isError ? <div className="p-4"><ErrMsg error={list.error} /></div> : (
          <div className="overflow-x-auto"><table className="w-full text-[12.5px]" data-testid="adjustment-table">
            <thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-3 py-2">Month</th><th>Line</th><th>Entity · location</th><th>Type</th><th className="text-right">Amount Cr</th><th className="px-3">Status</th></tr></thead>
            <tbody>
              {list.data.items.map((a) => (
                <tr key={a.adjustment_id} data-testid={`adj-row-${a.adjustment_id}`} onClick={() => setSelected(a.adjustment_id)} className={cn("cursor-pointer border-b hover:bg-muted/40", selected === a.adjustment_id && "bg-muted/60")}>
                  <td className="num px-3 py-1.5">{a.month}</td><td>{lineLabel(a.management_line)}</td><td>{a.entity} · {a.location_type}</td><td>{label(a.adjustment_type)}</td>
                  <td className={cn("num text-right font-semibold", Number(a.amount_cr) < 0 && "tone-warn")}>{cr(a.amount_cr, true)}</td><td className="px-3"><Pill value={a.status} />{a.provisional && a.status !== "DRAFT" && a.status !== "REVIEW" && a.status !== "APPROVED" && <span className="ml-1 text-[10px] tone-warn">provisional</span>}</td>
                </tr>
              ))}
              {list.data.items.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-muted-foreground" data-testid="adjustment-empty">No adjustments yet. Use New adjustment, or generate the month from the templates.</td></tr>}
            </tbody>
          </table></div>
        )}
      </Panel>
      {sel ? <Detail key={sel.adjustment_id + sel.status} a={sel} me={me} onClose={() => setSelected(null)} /> : <div className="hidden @[1100px]:block"><Panel eyebrow="Adjustment" title="Select a row"><div className="p-4 text-[12.5px] text-muted-foreground">Open an adjustment to see its history, preview its effect on Store and Corporate EBITDA, and act on it.</div></Panel></div>}
    </div>
  );
}

function CalendarView({ onOpen }: { onOpen: (id: string) => void }) {
  const { from, to } = useMemo(() => {
    const t = new Date();
    const fyStart = t.getMonth() >= 3 ? t.getFullYear() : t.getFullYear() - 1;
    return { from: `${fyStart}-04`, to: thisMonth() };
  }, []);
  const cal = useQuery({ queryKey: ["adjustments", "calendar", from, to], queryFn: () => adjustments.calendar(from, to) });
  const c: Calendar | undefined = cal.data;
  return (
    <div className="p-3">
      <Panel testId="provision-calendar" eyebrow="Provision calendar" title={`Template by month · ${from} to ${to}`}>
        {cal.isPending ? <Skeleton className="m-4 h-[160px]" /> : cal.isError ? <div className="p-4"><ErrMsg error={cal.error} /></div> : c && c.rows.length === 0 ? (
          <div className="p-4 text-[12.5px] text-muted-foreground" data-testid="calendar-empty">No recurring templates yet. Create one on the Templates tab.</div>
        ) : c && (
          <div className="overflow-x-auto"><table className="w-full text-[12.5px]">
            <thead><tr className="border-b text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-3 py-2 text-left">Template</th>{c.months.map((m) => <th key={m} className="px-2 text-center">{m.slice(2)}</th>)}</tr></thead>
            <tbody>{c.rows.map((r) => (
              <tr key={r.template_id} className="border-b" data-testid={`cal-row-${r.name}`}>
                <td className="px-3 py-1.5 font-medium">{r.name}<span className="block text-[10.5px] text-muted-foreground">{r.entity} · {lineLabel(r.line)}</span></td>
                {c.months.map((m) => { const cell = r.cells[m]; return (
                  <td key={m} className="px-2 text-center">
                    <button data-testid={`cal-${r.name}-${m}`} data-state={cell.state} title={`${STATE_TEXT[cell.state]}${cell.amount_cr ? ` · ${cr(cell.amount_cr, true)} Cr` : ""}`} disabled={!cell.adjustment_id} onClick={() => cell.adjustment_id && onOpen(cell.adjustment_id)}
                      className={cn("h-6 w-6 rounded text-[13px]", cell.state === "missing" && "bg-[oklch(0.95_0.05_25)] font-bold text-[oklch(0.45_0.15_25)]", cell.state === "active" && "text-[oklch(0.4_0.12_155)]", cell.state === "proposed" && "text-[oklch(0.5_0.12_75)]", cell.state === "n/a" && "opacity-30")}>{STATE_MARK[cell.state]}</button>
                  </td>); })}
              </tr>))}
            </tbody>
          </table></div>
        )}
        <div className="flex flex-wrap gap-3 border-t px-4 py-2 text-[11px] text-muted-foreground">{["active", "proposed", "missing", "future", "locked", "paused"].map((s) => <span key={s}>{STATE_MARK[s]} {s}</span>)}</div>
      </Panel>
    </div>
  );
}

function Templates({ me }: { me: Me }) {
  const q = useQuery({ queryKey: ["adjustments", "templates"], queryFn: adjustments.templates });
  const [gen, setGen] = useState(thisMonth());
  const act = useWrite((x: { id: string; action: string }) => adjustments.templateAction(x.id, x.action), ["adjustments"]);
  const generate = useWrite(() => adjustments.generate(gen), ["adjustments"]);
  const [adding, setAdding] = useState(false);
  return (
    <div className="grid gap-3 p-3">
      <Panel testId="templates" eyebrow="Recurring provisions" title={`Templates${q.data ? ` (${q.data.length})` : ""}`}
        right={<div className="flex items-center gap-2"><input aria-label="Generate month" type="month" className={cn(input, "w-[130px]")} value={gen} onChange={(e) => setGen(e.target.value)} /><Btn testId="generate-month" onClick={() => generate.mutate(undefined)} disabled={!MAKERS.includes(me.role) || generate.isPending}>Generate month</Btn><Btn onClick={() => setAdding(!adding)} testId="add-template">{adding ? "Close" : "New template"}</Btn></div>}>
        <ErrMsg error={act.error ?? generate.error} />
        {generate.data && <div role="status" data-testid="generate-result" className="border-b px-4 py-2 text-[12px]">Created {generate.data.created.length}{generate.data.created.some((c) => c.provisional) ? " (some provisional: the basis month is not complete)" : ""}; skipped {generate.data.skipped.length}{generate.data.skipped.length ? ": " + generate.data.skipped.map((s) => `${s.template} (${s.reason})`).join("; ") : ""}.</div>}
        {adding && <AdjForm me={me} template onSaved={() => setAdding(false)} />}
        {q.isPending ? <Skeleton className="m-4 h-[120px]" /> : q.isError ? <div className="p-4"><ErrMsg error={q.error} /></div> : (
          <table className="w-full text-[12.5px]" data-testid="template-table">
            <thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-3 py-2">Name</th><th>Entity · line</th><th>Basis</th><th>From – to</th><th>Last generated</th><th className="px-3">Status</th><th /></tr></thead>
            <tbody>{q.data.map((t) => (
              <tr key={t.template_id} className="border-b" data-testid={`template-${t.name}`}>
                <td className="px-3 py-1.5 font-medium">{t.name}</td><td>{t.entity} · {lineLabel(t.management_line)}</td>
                <td>{t.basis_type === "FIXED" ? `₹${Math.abs(Number(t.fixed_amount_rupees)).toLocaleString("en-IN")} ${t.effect === "COST" ? "cost" : "income"}` : `${Number(t.rate) * 100}% of ${t.rate_metric}`}</td>
                <td className="num">{t.start_month} – {t.end_month ?? "open"}</td><td className="num">{t.last_generated_month ?? "–"}</td><td className="px-3"><Pill value={t.status === "PAUSED" ? "WITHDRAWN" : t.status === "RETIRED" ? "REVERSED" : t.status} /> <span className="text-[10px]">{t.status}</span></td>
                <td className="space-x-1 whitespace-nowrap px-2">
                  {t.status === "DRAFT" && <Btn testId={`tpl-approve-${t.name}`} tone="primary" onClick={() => act.mutate({ id: t.template_id, action: "approve" })}>Approve</Btn>}
                  {t.status === "ACTIVE" && <Btn onClick={() => act.mutate({ id: t.template_id, action: "pause" })}>Pause</Btn>}
                  {t.status === "PAUSED" && <Btn onClick={() => act.mutate({ id: t.template_id, action: "resume" })}>Resume</Btn>}
                  {t.status !== "RETIRED" && <Btn tone="danger" onClick={() => act.mutate({ id: t.template_id, action: "retire" })}>Retire</Btn>}
                </td>
              </tr>))}
              {q.data.length === 0 && <tr><td colSpan={7} className="px-4 py-6 text-center text-muted-foreground">No templates yet.</td></tr>}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

function Cutover({ me }: { me: Me }) {
  const [month, setMonth] = useState(thisMonth());
  const [comment, setComment] = useState("");
  const imp = useWrite(() => adjustments.importRegister(), ["adjustments"]);
  const val = useWrite(() => adjustments.validateRegister(), []);
  const rec = useWrite(() => adjustments.cutover(month, comment), []);
  const admin = me.role === "admin";
  return (
    <div className="p-3">
      <Panel testId="adjustments-cutover" eyebrow="Cut-over" title="From the spreadsheet register to this one">
        <div className="grid gap-3 p-4 text-[12.5px]">
          <p className="text-muted-foreground">Import the spreadsheet rows once, check that the Management P&L is identical under both, record the decision, then set <code>FPA_ADJ_SOURCE=app</code> and restart the API. Do not leave both sources on: a row in both counts twice. Rows the engine works out from the books (the HoldCo stop-gap, true-ups) stay engine rows.</p>
          <ErrMsg error={imp.error ?? val.error ?? rec.error} />
          <div className="flex flex-wrap gap-2">
            <Btn testId="import-register" disabled={!admin || imp.isPending} title={admin ? undefined : "Administrator only"} onClick={() => imp.mutate(undefined)}>Import legacy register</Btn>
            <Btn testId="validate-register" tone="primary" disabled={val.isPending} onClick={() => val.mutate(undefined)}>{val.isPending ? "Validating…" : "Validate against the spreadsheet"}</Btn>
          </div>
          {imp.data && <div role="status" data-testid="register-import-result">Imported {imp.data.imported}; skipped {imp.data.skipped_existing} already there; {imp.data.kept_as_engine_rows} kept as engine rows{imp.data.not_importable.length ? `; ${imp.data.not_importable.length} could not be imported` : ""}.</div>}
          {val.data && <div data-testid="register-validation" data-identical={String(val.data.identical)} className={cn("rounded border px-3 py-2", val.data.identical ? "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)]" : "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)]")}>{val.data.identical ? "Identical: the cut-over changes no number." : `${val.data.line_differences.length} P&L line(s) differ: ${val.data.line_differences.slice(0, 5).map((d) => d.label).join(", ")}.`} ({val.data.window[0]} to {val.data.window[1]}; {val.data.csv_importable} importable rows, {val.data.csv_engine_rows} engine rows.)</div>}
          <div className="flex flex-wrap items-end gap-2">
            <Field label="First month the app is the source"><input aria-label="Cut-over month" type="month" className={input} value={month} onChange={(e) => setMonth(e.target.value)} /></Field>
            <Field label="What was decided (10+ characters)" className="min-w-[300px] flex-1"><input aria-label="Cut-over comment" className={input} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
            <Btn testId="record-cutover" tone="primary" disabled={!admin || comment.trim().length < 10 || rec.isPending} onClick={() => rec.mutate(undefined)}>Record cut-over</Btn>
          </div>
          {rec.data && <div role="status" data-testid="cutover-recorded">Recorded for {rec.data.first_month}. {rec.data.next}</div>}
        </div>
      </Panel>
    </div>
  );
}

type SubTab = "register" | "new" | "calendar" | "templates" | "cutover";

export function AdjustmentsPage() {
  const [tab, setTab] = useState<SubTab>("register");
  const [selected, setSelected] = useState<string | null>(null);
  const tabs: [SubTab, string][] = [["register", "Register"], ["new", "New adjustment"], ["calendar", "Provision calendar"], ["templates", "Templates"], ["cutover", "Cut-over"]];
  return (
    <ControlFrame active="adjustments" subtitle="Management adjustments and provisions: Management Total = Book + Reclass + approved Adjustment. Only ACTIVE adjustments count; proposed ones are shown as provisional.">
      {(me) => (
        <>
          <div role="tablist" className="flex gap-1 border-b bg-card px-3 py-1.5">
            {tabs.map(([id, text]) => <button key={id} role="tab" aria-selected={tab === id} data-testid={`adj-tab-${id}`} onClick={() => setTab(id)} className={cn("rounded px-2.5 py-1 text-[12.5px] font-semibold", tab === id ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}>{text}</button>)}
          </div>
          {tab === "register" && <Register me={me} selected={selected} setSelected={setSelected} />}
          {tab === "new" && <div className="p-3"><Panel eyebrow="Entry" title="New adjustment or provision"><AdjForm me={me} onSaved={(a) => { setSelected(a?.adjustment_id ?? null); setTab("register"); }} /></Panel></div>}
          {tab === "calendar" && <CalendarView onOpen={(id) => { setSelected(id); setTab("register"); }} />}
          {tab === "templates" && <Templates me={me} />}
          {tab === "cutover" && <Cutover me={me} />}
        </>
      )}
    </ControlFrame>
  );
}
