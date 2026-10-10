import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CHECKERS, mapping, MAKERS, type MapInput, type MappingImpact, type MappingRule, type Me } from "@/api/controlApi";
import { cn } from "@/lib/utils";
import { Skeleton } from "../common";
import { Panel } from "../panels";
import { ControlFrame } from "./ControlFrame";
import { Btn, cr, ErrMsg, Field, History, input, label, Pill, useWrite } from "./ui";

const TABS: [string, string, string[]][] = [
  ["pending", "Pending", ["DRAFT", "SUBMITTED", "APPROVED"]], ["active", "Active", ["ACTIVE"]], ["retired", "Superseded and retired", ["RETIRED"]], ["closed", "Rejected and withdrawn", ["REJECTED", "WITHDRAWN"]],
];
const sum = (c: Record<string, number> | undefined, st: string[]) => st.reduce((s, k) => s + (c?.[k] ?? 0), 0);
const thisMonth = () => new Date().toISOString().slice(0, 7);

function Impact({ d }: { d: MappingImpact }) {
  return (
    <div data-testid="mapping-impact" className="grid gap-2 text-[12.5px]">
      <div className="text-muted-foreground">Management P&L {d.from_month} to {d.to_month}, crore.</div>
      {d.lines.length === 0 ? <div data-testid="impact-none">No line changes in that period.</div> : (
        <table className="w-full"><thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th>Line</th><th className="text-right">Before</th><th className="text-right">Change</th><th className="text-right">After</th></tr></thead>
          <tbody>{d.lines.map((l) => <tr key={l.key} className="border-t" data-testid={`impact-${l.key}`}><td className="py-1">{l.label}</td><td className="num text-right">{cr(l.before)}</td><td className={cn("num text-right font-semibold", Number(l.change) < 0 && "tone-warn")}>{cr(l.change, true)}</td><td className="num text-right">{cr(l.after)}</td></tr>)}</tbody></table>
      )}
      <p className="text-[11px] text-muted-foreground">{d.note}</p>
    </div>
  );
}

function ProposeForm({ me, groups, onCreated }: { me: Me; groups: string[]; onCreated: (r: MappingRule) => void }) {
  const [f, setF] = useState<MapInput>({ domain: "LEDGER_GROUP", source_key: "", mapped_value: "", effective_from: thisMonth(), reason: "", evidence_ref: "" });
  const [impact, setImpact] = useState<MappingImpact | null>(null);
  const set = (k: keyof MapInput, v: string) => { setF((x) => ({ ...x, [k]: v })); setImpact(null); };
  const preview = useWrite(() => mapping.preview(f), [], setImpact);
  const save = useWrite((submit: boolean) => (async () => { const r = await mapping.create({ ...f, evidence_ref: f.evidence_ref || undefined }); return submit ? mapping.act(r.mapping_id, "submit") : r; })(), ["mapping"], onCreated);
  const can = MAKERS.concat(["finance_reviewer"]).includes(me.role) || me.role === "fpa_manager";
  const ledger = f.domain === "LEDGER_GROUP";
  return (
    <div className="grid gap-3 p-4" data-testid="mapping-form">
      {!can && <div role="status" className="rounded border bg-muted px-3 py-2 text-[12px]">Your role ({me.role.replaceAll("_", " ")}) can read mappings but not propose changes.</div>}
      <p className="text-[12px] text-muted-foreground">A mapping changes the rule from a month onward; it is not a correction of one booked line. Saving creates a new version that supersedes the rule in force.</p>
      <div className="grid gap-3 @[900px]:grid-cols-4">
        <Field label="Domain"><select aria-label="Domain" className={input} value={f.domain} onChange={(e) => { set("domain", e.target.value); set("mapped_value", ""); }}><option value="LEDGER_GROUP">Ledger to management group</option><option value="SITE_LOCATION">Site to location type</option></select></Field>
        <Field label={ledger ? "Ledger name" : "Site code"}><input aria-label="Source key" className={input} value={f.source_key} onChange={(e) => set("source_key", e.target.value)} /></Field>
        <Field label={ledger ? "Management group" : "Location type"}>
          <select aria-label="Mapped value" className={input} value={f.mapped_value} onChange={(e) => set("mapped_value", e.target.value)}><option value="">Choose…</option>{(ledger ? groups : ["STORES", "DC", "HO"]).map((g) => <option key={g} value={g}>{g}</option>)}</select>
        </Field>
        <Field label="Effective from (month)"><input aria-label="Effective from" type="month" className={input} value={f.effective_from} onChange={(e) => set("effective_from", e.target.value)} /></Field>
      </div>
      <div className="grid gap-3 @[900px]:grid-cols-[1fr_260px]">
        <Field label="Reason (10+ characters)"><input aria-label="Reason" className={input} value={f.reason} onChange={(e) => set("reason", e.target.value)} /></Field>
        <Field label="Evidence reference"><input aria-label="Evidence reference" className={input} value={f.evidence_ref ?? ""} onChange={(e) => set("evidence_ref", e.target.value)} /></Field>
      </div>
      <ErrMsg error={preview.error ?? save.error} />
      <div className="flex flex-wrap gap-2">
        <Btn testId="preview-mapping" onClick={() => preview.mutate(undefined)} disabled={!f.source_key || !f.mapped_value || f.reason.trim().length < 10 || preview.isPending}>Preview impact</Btn>
        <Btn testId="save-mapping-draft" onClick={() => save.mutate(false)} disabled={!can || !f.source_key || !f.mapped_value || f.reason.trim().length < 10 || save.isPending}>Save draft</Btn>
        <Btn tone="primary" testId="save-mapping-submit" onClick={() => save.mutate(true)} disabled={!can || !f.source_key || !f.mapped_value || f.reason.trim().length < 10 || save.isPending}>Save and submit for approval</Btn>
      </div>
      {impact && <Impact d={impact} />}
    </div>
  );
}

function Detail({ r, me, onClose }: { r: MappingRule; me: Me; onClose: () => void }) {
  const full = useQuery({ queryKey: ["mapping", "one", r.mapping_id, r.status], queryFn: () => mapping.one(r.mapping_id) });
  const [reason, setReason] = useState("");
  const [impact, setImpact] = useState<MappingImpact | null>(null);
  const prev = useWrite(() => mapping.previewSaved(r.mapping_id), [], setImpact);
  const act = useWrite((a: string) => mapping.act(r.mapping_id, a, reason || undefined), ["mapping"], () => setReason(""));
  const maker = MAKERS.concat(["finance_reviewer"]).includes(me.role) || me.role === "fpa_manager", checker = CHECKERS.includes(me.role);
  type Act = { action: string; text: string; tone?: "primary" | "danger"; show: boolean; needsReason?: boolean };
  const all: Act[] = [
    { action: "submit", text: "Submit for approval", tone: "primary", show: r.status === "DRAFT" && maker },
    { action: "withdraw", text: "Withdraw", tone: "danger", show: (r.status === "DRAFT" || r.status === "SUBMITTED") && maker },
    { action: "approve", text: "Approve", tone: "primary", show: r.status === "SUBMITTED" && checker },
    { action: "reject", text: "Reject", tone: "danger", show: r.status === "SUBMITTED" && checker, needsReason: true },
    { action: "activate", text: "Activate (the engine reads it from its month)", tone: "primary", show: r.status === "APPROVED" && checker },
    { action: "void", text: "Void", tone: "danger", show: r.status === "APPROVED" && checker, needsReason: true },
    { action: "retire", text: "Retire", tone: "danger", show: r.status === "ACTIVE" && checker, needsReason: true },
  ];
  const buttons = all.filter((b) => b.show);
  const needsReason = buttons.some((b) => b.needsReason);
  return (
    <Panel testId="mapping-detail" eyebrow={label(r.domain)} title={`${r.source_key} → ${r.mapped_value}`} right={<button className="text-[12px] underline" onClick={onClose}>Close</button>}>
      <div className="grid gap-3 p-4 text-[12.5px]">
        <div className="flex flex-wrap items-center gap-2"><Pill value={r.status} testId="detail-status" /><span>Version {r.version} · from {r.effective_from}{r.effective_to ? ` to ${r.effective_to}` : ""}{r.in_force_now ? " · in force now" : ""}</span><span className="text-muted-foreground">source {r.source.replaceAll("_", " ")}</span></div>
        <div>{r.reason}{r.evidence_ref ? ` (${r.evidence_ref})` : ""}</div>
        {full.data && full.data.versions.length > 1 && <div data-testid="versions" className="text-[12px]">Versions: {full.data.versions.map((v) => `v${v.version} ${v.mapped_value} from ${v.effective_from}${v.effective_to ? " to " + v.effective_to : ""} (${v.status.toLowerCase()})`).join(" · ")}</div>}
        {needsReason && <Field label="Reason (10+ characters)"><input aria-label="Reason" className={input} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        <ErrMsg error={act.error ?? prev.error} />
        <div className="flex flex-wrap gap-2">
          {buttons.map((b) => <Btn key={b.action} testId={`act-${b.action}`} tone={b.tone} disabled={act.isPending || (b.needsReason && reason.trim().length < 10)} onClick={() => act.mutate(b.action)}>{b.text}</Btn>)}
          <Btn testId="detail-preview" onClick={() => prev.mutate(undefined)}>Impact preview</Btn>
        </div>
        {impact && <Impact d={impact} />}
        <div><div className="eyebrow mb-1">History</div>{full.data ? <History events={full.data.events} /> : <Skeleton className="h-10" />}</div>
      </div>
    </Panel>
  );
}

function Validation({ me }: { me: Me }) {
  const val = useWrite(() => mapping.validate(), []);
  const imp = useWrite(() => mapping.importBaseline(), ["mapping"]);
  const d = val.data;
  return (
    <Panel testId="mapping-validation" eyebrow="Cut-over" title="Legacy CSV baseline and validation">
      <div className="grid gap-3 p-4 text-[12.5px]">
        <p className="text-muted-foreground">The engine uses the source shown above. To move from the legacy CSV files to these governed rules: import the CSV as version 1, validate that both give the same Management P&L, then set <code>FPA_MAPPING_SOURCE=app</code> and restart the API.</p>
        <ErrMsg error={val.error ?? imp.error} />
        <div className="flex flex-wrap gap-2">
          <Btn testId="import-baseline" disabled={me.role !== "admin" || imp.isPending} title={me.role === "admin" ? undefined : "Administrator only"} onClick={() => imp.mutate(undefined)}>Import legacy baseline</Btn>
          <Btn testId="validate-mapping" tone="primary" disabled={val.isPending} onClick={() => val.mutate(undefined)}>{val.isPending ? "Validating…" : "Validate against the CSV"}</Btn>
        </div>
        {imp.data && <div role="status" data-testid="import-result">Imported {imp.data.imported.LEDGER_GROUP} ledger and {imp.data.imported.SITE_LOCATION} site rules; skipped {imp.data.skipped_existing} that already exist.</div>}
        {d && (
          <div data-testid="validation-result" data-identical={String(d.identical)} className={cn("rounded border px-3 py-2", d.identical ? "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)]" : "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)]")}>
            {d.identical ? "Identical: every mapped key and every Management P&L line agree under both sources." : `${d.key_difference_count} mapped key(s) and ${d.line_differences.length} P&L line(s) differ.`} ({d.window[0]} to {d.window[1]}; {d.csv_ledgers} CSV ledgers and {d.csv_sites} sites, {d.app_ledgers} and {d.app_sites} in the app rules.)
            {d.key_differences.slice(0, 8).map((k) => <div key={k.domain + k.key}>{k.key}: CSV {k.csv ?? "none"}, app {k.app ?? "none"}</div>)}
          </div>
        )}
      </div>
    </Panel>
  );
}

export function MappingPage() {
  const [tab, setTab] = useState("pending");
  const [domain, setDomain] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["mapping", "list", domain, search], queryFn: () => mapping.list({ domain: domain || undefined, search: search || undefined }) });
  const set = TABS.find((t) => t[0] === tab);
  const items = (q.data?.items ?? []).filter((r) => set?.[2].includes(r.status));
  const sel = q.data?.items.find((r) => r.mapping_id === selected) ?? null;
  return (
    <ControlFrame active="mapping" subtitle="Versioned, effective-dated rules that classify the finance data: ledger to management group, site to location type. A change is a new version from a month; history stays reproducible.">
      {(me) => (
        <>
          <div role="tablist" className="flex flex-wrap items-center gap-1 border-b bg-card px-3 py-1.5">
            {TABS.map(([id, text, st]) => <button key={id} role="tab" aria-selected={tab === id} data-testid={`map-tab-${id}`} onClick={() => { setTab(id); setSelected(null); }} className={cn("rounded px-2.5 py-1 text-[12.5px] font-semibold", tab === id ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}>{text} <span className="num" data-testid={`map-count-${id}`}>{sum(q.data?.counts, st)}</span></button>)}
            <button role="tab" aria-selected={tab === "new"} data-testid="map-tab-new" onClick={() => setTab("new")} className={cn("rounded px-2.5 py-1 text-[12.5px] font-semibold", tab === "new" ? "bg-primary text-primary-foreground" : "border text-foreground")}>Propose a change</button>
            <button role="tab" aria-selected={tab === "cutover"} data-testid="map-tab-cutover" onClick={() => setTab("cutover")} className={cn("rounded px-2.5 py-1 text-[12.5px] font-semibold", tab === "cutover" ? "bg-muted" : "text-muted-foreground")}>Cut-over</button>
            {q.data && <span data-testid="source-in-use" className="ml-auto text-[11.5px] text-muted-foreground">The engine reads: {q.data.source_in_use === "app" ? "these governed rules" : "the legacy CSV files"}</span>}
          </div>
          {tab === "new" ? <div className="p-3"><Panel eyebrow="Proposal" title="Propose a mapping change"><ProposeForm me={me} groups={q.data?.groups ?? []} onCreated={(r) => { setSelected(r.mapping_id); setTab("pending"); }} /></Panel></div>
            : tab === "cutover" ? <div className="p-3"><Validation me={me} /></div> : (
              <div className="grid gap-3 p-3 @[1100px]:grid-cols-[1.3fr_1fr]">
                <Panel testId="mapping-list" eyebrow="Rules" title={`${set?.[1] ?? ""} (${items.length})`}
                  right={<div className="flex gap-2 text-[12px]"><input aria-label="Search" className={cn(input, "w-[140px]")} placeholder="Search key" value={search} onChange={(e) => setSearch(e.target.value)} /><select aria-label="Domain filter" className={cn(input, "w-auto")} value={domain} onChange={(e) => setDomain(e.target.value)}><option value="">All domains</option><option value="LEDGER_GROUP">Ledger</option><option value="SITE_LOCATION">Site</option></select></div>}>
                  {q.isPending ? <Skeleton className="m-4 h-[160px]" /> : q.isError ? <div className="p-4"><ErrMsg error={q.error} /></div> : (
                    <div className="max-h-[60vh] overflow-auto"><table className="w-full text-[12.5px]" data-testid="mapping-table">
                      <thead><tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground"><th className="px-3 py-2">Key</th><th>Mapped to</th><th>From</th><th>Ver.</th><th className="px-3">Status</th></tr></thead>
                      <tbody>{items.map((r) => (
                        <tr key={r.mapping_id} data-testid={`map-row-${r.mapping_id}`} onClick={() => setSelected(r.mapping_id)} className={cn("cursor-pointer border-b hover:bg-muted/40", selected === r.mapping_id && "bg-muted/60")}>
                          <td className="px-3 py-1.5">{r.source_key}<span className="block text-[10.5px] text-muted-foreground">{label(r.domain)}</span></td><td>{r.mapped_value}</td><td className="num">{r.effective_from}</td><td className="num">{r.version}</td><td className="px-3"><Pill value={r.status} /></td></tr>))}
                        {items.length === 0 && <tr><td colSpan={5} className="px-4 py-6 text-center text-muted-foreground" data-testid="mapping-empty">Nothing here.</td></tr>}</tbody>
                    </table></div>
                  )}
                </Panel>
                {sel ? <Detail key={sel.mapping_id + sel.status} r={sel} me={me} onClose={() => setSelected(null)} /> : <div className="hidden @[1100px]:block"><Panel eyebrow="Rule" title="Select a row"><div className="p-4 text-[12.5px] text-muted-foreground">Open a rule to see its versions and history, preview its effect on the Management P&L and act on it.</div></Panel></div>}
              </div>
            )}
        </>
      )}
    </ControlFrame>
  );
}
