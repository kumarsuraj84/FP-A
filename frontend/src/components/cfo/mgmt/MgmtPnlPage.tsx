import { useMemo, useState } from "react";
import { Download, X } from "lucide-react";
import { useMgmtAdjustments, useMgmtPnl, useMgmtRun } from "@/api/mgmtLiveHooks";
import { DASH } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { MgmtAdjustment, MgmtLine, MgmtPnlMode as MgmtMode, MgmtTriple } from "@/types/mgmtLive";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { BasisTag } from "../BasisTag";
import { MgmtFrame, MonthRange, WarningsBanner, fyYtdRange } from "./MgmtFrame";
import { useMgmtEntity } from "./mgmtEntity";
import { isPartialMonth } from "./mgmtMonths";
import { cr2, cr2s, dashReason, downloadCsv, monthShort, pct1, toneOf } from "./mgmtFormat";

/**
 * Management P&L in the finance MIS format (INR Cr). Every figure has three layers: Book (the ledger), Adjustment (management provisions and
 * journals that live outside the books) and Total (the MIS number). Total is the default. Cells that carry an adjustment are highlighted;
 * clicking a cell lists the adjustments behind that line.
 */

const MODES: { id: MgmtMode; label: string; hint: string }[] = [
  { id: "total", label: "Total", hint: "The MIS number: book plus adjustment" },
  { id: "book", label: "Book", hint: "What the ledger says, before any management adjustment" },
  { id: "reclass", label: "Reclass", hint: "Only the net-zero movement of approved corrections between groups and months" },
  { id: "adjustment", label: "Adjustment", hint: "Only the management adjustments" },
];

/** The MIS order. Lines the API sends that are not listed keep the order they arrive in, after the known ones. */
const CANON = ["revenue", "other_operating_income", "total_income", "material_cost", "material_margin", "rent", "employee_cost", "power_fuel", "advertisement", "freight", "other_expenses", "total_store_expenses", "store_ebitda", "dc_cost", "ho_cost", "total_corporate", "corporate_ebitda", "one_time", "ebitda_post_one_time"];
const rank = (k: string) => {
  const i = CANON.indexOf(k);
  return i < 0 ? CANON.length : i;
};

/** Informational lines under Corporate EBITDA: shown in their own block, never added into any EBITDA. */
const BELOW_KEYS = ["interest_income", "finance_cost"];
const isBelow = (k: string) => BELOW_KEYS.includes(k.replace(/^pct_/, ""));

const ADJ_BG = "bg-[oklch(0.97_0.05_85)]";
const adjusted = (t: MgmtTriple | undefined) => t?.adjustment !== null && t?.adjustment !== undefined && Math.abs(t.adjustment) >= 0.005;

interface Pick {
  key: string;
  month: string | null;
}

function Cell({ line, month, t, mode, picked, onPick }: { line: MgmtLine; month: string | null; t: MgmtTriple | undefined; mode: MgmtMode; picked: boolean; onPick: (p: Pick) => void }) {
  const v = t ? (t[mode] ?? null) : null;
  const isPct = line.kind === "pct";
  const shown = isPct ? pct1(v) : cr2(v);
  const adj = adjusted(t);
  const title = t ? `Book ${isPct ? pct1(t.book) : cr2(t.book)}${t.reclass ? ` · Reclass ${isPct ? pct1(t.reclass) : cr2(t.reclass)}` : ""} · Adjustment ${isPct ? pct1(t.adjustment) : cr2(t.adjustment)} · Total ${isPct ? pct1(t.total) : cr2(t.total)}` : dashReason(isPct ? "pct" : "value");
  return (
    <td
      data-testid={`cell-${line.key}-${month ?? "total"}`}
      data-exact={v === null || v === undefined ? "" : String(v)}
      data-mode={mode}
      data-adjusted={adj ? "true" : "false"}
      title={v === null || v === undefined ? dashReason(isPct ? "pct" : "value") : title}
      className={cn("num-mono whitespace-nowrap px-0 py-0 text-right", adj && ADJ_BG, picked && "outline outline-2 -outline-offset-2 outline-[oklch(0.5_0.15_265)]", month === null && "border-l")}
    >
      <button
        type="button"
        onClick={() => onPick({ key: line.key, month })}
        aria-label={`${line.label} ${month ? monthShort(month) : "total"}: adjustments`}
        className={cn("block w-full px-3 py-1.5 text-right hover:bg-muted/60", v !== null && v !== undefined && !isPct && toneOf(v), (mode === "adjustment" || mode === "reclass") && v === 0 && "text-muted-foreground")}
      >
        {v === null || v === undefined ? <span className="text-muted-foreground">{DASH}</span> : shown}
      </button>
    </td>
  );
}

function AdjustmentsPanel({ pick, lines, onClose }: { pick: Pick; lines: MgmtLine[]; onClose: () => void }) {
  const adj = useMgmtAdjustments();
  const line = lines.find((l) => l.key === pick.key);
  const base = pick.key.replace(/^pct_/, "");
  const baseLabel = lines.find((l) => l.key === base)?.label;
  const match = (a: MgmtAdjustment) => {
    const x = a.mis_line.toLowerCase();
    return (x === base.toLowerCase() || x === (baseLabel ?? "").toLowerCase()) && (pick.month === null || a.month === pick.month);
  };
  return (
    <Panel
      testId="mgmt-adjustments"
      eyebrow="Adjustments register"
      title={`${line?.label ?? pick.key} · ${pick.month ? monthShort(pick.month) : "selected period"}`}
      right={<button aria-label="Close adjustments" data-testid="mgmt-adjustments-close" onClick={onClose} className="press rounded border p-1 hover:bg-muted"><X className="h-3.5 w-3.5" /></button>}
    >
      <LiveBoundary query={adj} skeleton={<Skeleton className="m-4 h-24" />}>
        {(d) => {
          const rows = d.rows.filter(match);
          if (line?.kind === "subtotal") {
            return <div data-testid="mgmt-adjustments-empty" className="px-4 py-4 text-[12.5px] text-muted-foreground">{line.label} is a subtotal. Its adjustments are the sum of the lines above it: click one of those lines.</div>;
          }
          if (rows.length === 0) return <div data-testid="mgmt-adjustments-empty" className="px-4 py-4 text-[12.5px] text-muted-foreground">No adjustment is registered on this line for {pick.month ? monthShort(pick.month) : "this period"}. The figure is the books.</div>;
          return (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]" data-testid="mgmt-adjustments-table">
                <thead>
                  <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                    {["Month", "Where", "Rule", "Kind", "Owner", "Status", "Source"].map((h) => <th key={h} className="px-3 py-1.5 font-semibold">{h}</th>)}
                    <th className="px-3 py-1.5 text-right font-semibold">INR Cr</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.id} className={cn("border-b last:border-0", /^elimination$/i.test(a.kind) && "bg-[oklch(0.96_0.03_300)]")} data-testid={`adj-${a.id}`} data-elimination={/^elimination$/i.test(a.kind)}>
                      <td className="px-3 py-1">{monthShort(a.month)}</td>
                      <td className="px-3 py-1">{a.location_type}</td>
                      <td className="px-3 py-1">{a.rule}{a.note && <div className="text-[11px] text-muted-foreground">{a.note}</div>}</td>
                      <td className="px-3 py-1">{/^elimination$/i.test(a.kind) ? <span data-testid={`adj-${a.id}-elimination`} className="rounded bg-[oklch(0.9_0.06_300)] px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wide text-[oklch(0.3_0.12_300)]">Elimination</span> : a.kind}{(a.counterparty || a.counterparty_entity) && <div data-testid={`adj-${a.id}-counterparty`} className="text-[11px] text-muted-foreground">vs {[a.counterparty_entity, a.counterparty].filter(Boolean).join(" · ")}</div>}</td>
                      <td className="px-3 py-1">{a.owner}</td>
                      <td className="px-3 py-1"><StatusPill status={a.status} /></td>
                      <td className="px-3 py-1 text-muted-foreground">{a.source}</td>
                      <td className={cn("num-mono px-3 py-1 text-right", toneOf(a.amount_cr))}>{cr2(a.amount_cr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }}
      </LiveBoundary>
    </Panel>
  );
}

export function StatusPill({ status }: { status: string }) {
  const ok = /^(approved|signed|final)/i.test(status);
  return <span className={cn("rounded px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wide", ok ? "bg-[oklch(0.94_0.06_155)] text-[oklch(0.32_0.1_155)]" : "bg-[oklch(0.96_0.06_85)] text-[oklch(0.38_0.09_70)]")}>{status}</span>;
}

function PnlTable({ data, mode, pick, onPick }: { data: { months: string[]; lines: MgmtLine[] }; mode: MgmtMode; pick: Pick | null; onPick: (p: Pick) => void }) {
  const money = useMemo(() => data.lines.filter((l) => l.kind !== "pct").sort((a, b) => rank(a.key) - rank(b.key)), [data.lines]);
  const pcts = useMemo(() => data.lines.filter((l) => l.kind === "pct").sort((a, b) => rank(a.key.replace(/^pct_/, "")) - rank(b.key.replace(/^pct_/, ""))), [data.lines]);
  const asOf = useMgmtRun().data?.as_of_date;
  const colSpan = data.months.length + 2;
  const rowsOf = (lines: MgmtLine[]) =>
    lines.map((l) => {
      const sub = l.kind === "subtotal";
      return (
        <tr key={l.key} data-testid={`row-${l.key}`} data-kind={l.kind} className={cn("border-b", sub && "bg-[oklch(0.975_0.008_265)] font-semibold")}>
          <th scope="row" className={cn("sticky left-0 z-10 whitespace-nowrap border-r px-3 py-1.5 text-left", sub ? "bg-[oklch(0.975_0.008_265)] font-semibold" : "bg-card font-normal")}>
            <button type="button" data-testid={`line-${l.key}`} onClick={() => onPick({ key: l.key, month: null })} title="Show the adjustments behind this line" className="press text-left hover:underline">
              {l.label}
            </button>
            {l.key === "corporate_ebitda" && mode !== "adjustment" && <BasisTag basis={mode === "book" ? "mgmt_book" : "mgmt_total"} />}
          </th>
          {data.months.map((m) => (
            <Cell key={m} line={l} month={m} t={l.values[m]} mode={mode} picked={pick?.key === l.key && pick.month === m} onPick={onPick} />
          ))}
          <Cell line={l} month={null} t={l.total} mode={mode} picked={pick?.key === l.key && pick.month === null} onPick={onPick} />
        </tr>
      );
    });
  return (
    <div className="max-h-[70vh] overflow-auto">
      <table className="w-full min-w-[720px] border-separate border-spacing-0 text-[12.5px]" data-testid="mgmt-table" data-mode={mode}>
        <thead>
          <tr className="text-[10.5px] uppercase tracking-wider text-muted-foreground">
            <th className="sticky left-0 top-0 z-30 border-b border-r bg-card px-3 py-2 text-left font-semibold">INR Cr</th>
            {data.months.map((m) => <th key={m} data-testid={`col-${m}`} className="sticky top-0 z-20 whitespace-nowrap border-b bg-card px-3 py-2 text-right font-semibold">{monthShort(m)}{isPartialMonth(m, asOf) && <span className="block text-[10px] font-medium normal-case text-[oklch(0.5_0.12_70)]" title={`Data stops at ${asOf}: this month is not complete`}>partial</span>}</th>)}
            <th className="sticky top-0 z-20 whitespace-nowrap border-b border-l bg-card px-3 py-2 text-right font-semibold">{data.months.length > 1 ? "Total" : "Period"}</th>
          </tr>
        </thead>
        <tbody>
          {rowsOf(money)}
          {pcts.length > 0 && (
            <>
              <tr data-testid="pct-block-head">
                <th colSpan={colSpan} className="sticky left-0 border-b bg-secondary px-3 py-1.5 text-left text-[10.5px] font-semibold uppercase tracking-wider text-secondary-foreground">As % of total income</th>
              </tr>
              {rowsOf(pcts)}
            </>
          )}
        </tbody>
      </table>
    </div>
  );
}

function BelowEbitda({ data, mode, onPick }: { data: { months: string[]; lines: MgmtLine[] }; mode: MgmtMode; onPick: (p: Pick) => void }) {
  const lines = data.lines.filter((l) => isBelow(l.key) && l.kind !== "pct").sort((a, b) => BELOW_KEYS.indexOf(a.key) - BELOW_KEYS.indexOf(b.key));
  if (lines.length === 0) return null;
  return (
    <div className="px-3 pb-3">
      <Panel testId="mgmt-below" eyebrow="Below EBITDA · information only" title="Interest income and finance cost (INR Cr)" right={<span className="text-[11.5px] text-muted-foreground">Not part of Corporate EBITDA</span>}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-separate border-spacing-0 text-[12.5px]" data-testid="mgmt-below-table">
            <tbody>
              {lines.map((l) => (
                <tr key={l.key} data-testid={`row-${l.key}`} data-kind="below" className="border-b">
                  <th scope="row" className="sticky left-0 z-10 whitespace-nowrap border-r bg-card px-3 py-1.5 text-left font-normal">{l.label}</th>
                  {data.months.map((m) => <Cell key={m} line={l} month={m} t={l.values[m]} mode={mode} picked={false} onPick={onPick} />)}
                  <Cell line={l} month={null} t={l.total} mode={mode} picked={false} onPick={onPick} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function Strip({ lines }: { lines: MgmtLine[] }) {
  const get = (k: string) => lines.find((l) => l.key === k)?.total;
  const p = (k: string) => lines.find((l) => l.key === `pct_${k}`)?.total.total;
  const items = [
    { id: "income", label: "Total income", k: "total_income", pct: null as number | null | undefined },
    { id: "store", label: "Store EBITDA", k: "store_ebitda", pct: p("store_ebitda") },
    { id: "corp", label: "Corporate EBITDA", k: "corporate_ebitda", pct: p("corporate_ebitda") },
    { id: "post", label: "EBITDA post one-time", k: "ebitda_post_one_time", pct: p("ebitda_post_one_time") },
  ];
  return (
    <section aria-label="Headline figures" data-testid="mgmt-strip" className="grid grid-cols-4 divide-x border-b bg-card @max-[700px]:grid-cols-2">
      {items.map((i) => {
        const t = get(i.k);
        return (
          <div key={i.id} data-testid={`strip-${i.id}`} className="px-4 py-3">
            <div className="eyebrow">{i.label}{i.id === "corp" && <BasisTag basis="mgmt_total" />}</div>
            <div data-testid={`strip-${i.id}-value`} data-exact={t?.total ?? ""} className={cn("num-mono text-[20px] font-semibold leading-tight", toneOf(t?.total))}>{t ? cr2(t.total) : DASH}</div>
            <div className="num text-[11.5px] text-muted-foreground" title={t?.total === null || t?.total === undefined ? dashReason("value") : undefined}>
              {i.pct !== undefined && i.pct !== null ? `${pct1(i.pct)} of income` : i.k === "total_income" ? "INR Cr, selected months" : "INR Cr"}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function PnlBody({ months, runWarnings }: { months: string[]; runWarnings: string[] }) {
  const asOf = useMgmtRun().data?.as_of_date;
  // the default window is year to date through the last COMPLETE month; a partial month can still be picked and is labelled
  const [from, setFrom] = useState<string>(fyYtdRange(months, asOf)[0]);
  const [to, setTo] = useState<string>(fyYtdRange(months, asOf)[1]);
  const [mode, setMode] = useState<MgmtMode>("total");
  const [includeProposed, setIncludeProposed] = useState(true);
  const [pick, setPick] = useState<Pick | null>(null);
  const entity = useMgmtEntity();
  const pnl = useMgmtPnl({ from_month: from || undefined, to_month: to || undefined, include_proposed: includeProposed, entity });
  const hasReclass = (pnl.data?.lines ?? []).some((l) => Math.abs(l.total?.reclass ?? 0) >= 0.00005 || Object.values(l.values).some((c) => Math.abs(c?.reclass ?? 0) >= 0.00005));
  return (
    <>
      <div data-testid="mgmt-controls" className="flex flex-wrap items-center gap-3 border-b bg-card px-5 py-2 text-[12px]">
        <MonthRange months={months} from={from} to={to} asOf={asOf} onChange={(f, t) => { setFrom(f); setTo(t); }} />
        <div className="mx-1 h-5 w-px bg-border" />
        <div role="group" aria-label="Figure layer" data-testid="mgmt-mode" className="flex overflow-hidden rounded border">
          {MODES.map((m) => (
            <button key={m.id} type="button" data-testid={`mode-${m.id}`} aria-pressed={mode === m.id} title={m.hint} onClick={() => setMode(m.id)} className={cn("press px-2.5 py-1 font-medium", mode === m.id ? "bg-foreground text-background" : "hover:bg-muted")}>
              {m.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5" title="Proposed adjustments are not yet signed off by Finance">
          <input type="checkbox" data-testid="mgmt-include-proposed" checked={includeProposed} onChange={(e) => setIncludeProposed(e.target.checked)} />
          Include proposed adjustments
        </label>
        <span className="flex items-center gap-1 text-[11.5px] text-muted-foreground"><span className={cn("inline-block h-3 w-3 rounded-sm border", ADJ_BG)} /> carries an adjustment</span>
        <div className="flex-1" />
        {pnl.data && (
          <button
            type="button"
            data-testid="mgmt-export"
            className="press inline-flex items-center gap-1 rounded border px-2 py-1 font-medium hover:bg-muted"
            onClick={() => {
              const d = pnl.data!;
              downloadCsv(`mgmt-pnl-${d.run_id}-${mode}.csv`, [["Line (INR Cr)", ...d.months.map(monthShort), "Total"], ...d.lines.map((l) => [l.label, ...d.months.map((m) => l.values[m]?.[mode] ?? ""), l.total[mode] ?? ""])]);
            }}
          >
            <Download className="h-3.5 w-3.5" /> Download CSV
          </button>
        )}
      </div>
      <LiveBoundary query={pnl} skeleton={<Skeleton className="m-4 h-[420px]" />}>
        {(d) => {
          const extra = d.warnings.filter((w) => !runWarnings.includes(w));
          const main = { months: d.months, lines: d.lines.filter((l) => !isBelow(l.key)) };
          const togglePick = (p: Pick) => setPick((cur) => (cur && cur.key === p.key && cur.month === p.month ? null : p));
          return (
            <>
              <WarningsBanner warnings={extra} />
              <Strip lines={main.lines} />
              <div className="p-3">
                <Panel
                  testId="mgmt-pnl-panel"
                  eyebrow={mode === "total" ? (hasReclass ? "Total = book + reclass + adjustment" : "Total = book + adjustment") : mode === "book" ? "Book layer only" : mode === "reclass" ? "Reclass layer only (nets to zero)" : "Adjustment layer only"}
                  title="Management P&L, INR Cr"
                  right={<span className="num text-[11.5px] text-muted-foreground">{d.store_count !== null ? `${d.store_count.toLocaleString("en-IN")} stores · ` : ""}{monthShort(d.months[0] ?? from)} to {monthShort(d.months[d.months.length - 1] ?? to)}</span>}
                >
                  <PnlTable data={main} mode={mode} pick={pick} onPick={togglePick} />
                </Panel>
              </div>
              <BelowEbitda data={d} mode={mode} onPick={togglePick} />
              {pick && <div className="px-3 pb-3"><AdjustmentsPanel pick={pick} lines={d.lines} onClose={() => setPick(null)} /></div>}
              <div className="px-5 pb-6 text-[11.5px] text-muted-foreground">
                Costs are negative. Store EBITDA is before DC and HO cost; Corporate EBITDA is after both and before one-time items. Click a line name or a figure to see the adjustments behind it.
              </div>
            </>
          );
        }}
      </LiveBoundary>
    </>
  );
}

/** The frame already shows the run's warnings; the P&L response repeats them, so only the new ones are added. */
export function MgmtPnlPage() {
  return <MgmtFrame active="pnl">{(months, runWarnings) => <PnlBody months={months} runWarnings={runWarnings} />}</MgmtFrame>;
}
