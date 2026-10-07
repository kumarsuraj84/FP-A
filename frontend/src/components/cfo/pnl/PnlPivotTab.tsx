import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, Download } from "lucide-react";
import { usePnlComparison, usePnlExpenses, usePnlPivot, usePnlPivotLedgers } from "@/api/pnlLiveHooks";
import { DASH } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PnlQuery } from "@/types/pnlLive";
import type { PivotColumn, PivotRow } from "@/types/pnlReview";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { bps, cr2, monthShort, pct, psf, tone } from "./pnlFormat";

type Mode = "stores" | "company";
type Unit = "cr" | "share";

function ModeToggle({ mode, setMode }: { mode: Mode; setMode: (m: Mode) => void }) {
  return (
    <div role="group" aria-label="Scope" className="flex overflow-hidden rounded border text-[12px]">
      {(["stores", "company"] as Mode[]).map((m) => (
        <button key={m} data-testid={`mode-${m}`} aria-pressed={mode === m} onClick={() => setMode(m)} className={cn("press px-2.5 py-1 font-medium", mode === m ? "bg-foreground text-background" : "hover:bg-muted")}>
          {m === "stores" ? "Stores" : "Company (incl. head office)"}
        </button>
      ))}
    </div>
  );
}

function colHead(c: PivotColumn) {
  return (
    <th key={c.id} data-testid={`pv-col-${c.id}`} className={cn("whitespace-nowrap px-2.5 py-2 text-right font-semibold", c.kind !== "month" && "bg-[oklch(0.97_0.008_265)]")}>
      {c.kind === "month" ? monthShort(c.id) : c.label}
      {c.partial && <span className="block text-[9.5px] font-normal normal-case tracking-normal text-muted-foreground">partial</span>}
    </th>
  );
}

/** CSV of exactly what is on screen (rupees, exact), for the Excel-style review. */
function toCsv(cols: PivotColumn[], rows: PivotRow[]): string {
  const head = ["Line", ...cols.map((c) => c.label), "LY YTD (day aligned)", "Variance", "Variance %"];
  const lines = rows.map((r) => [r.label, ...cols.map((c) => r.cells[c.id] ?? ""), r.ly_ytd ?? "", r.variance ?? "", r.variance_pct ?? ""]);
  return [head, ...lines].map((l) => l.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(",")).join("\n");
}

function LedgerRows({ q, mode, group, cols }: { q: PnlQuery; mode: Mode; group: string; cols: PivotColumn[] }) {
  const l = usePnlPivotLedgers(q, mode, group);
  if (l.isPending) return <tr><td colSpan={cols.length + 4} className="px-4 py-2 text-muted-foreground">Loading ledgers…</td></tr>;
  if (!l.data) return <tr><td colSpan={cols.length + 4} className="px-4 py-2 tone-bad">Could not load the ledgers.</td></tr>;
  return (
    <>
      {l.data.ledgers.map((x) => (
        <tr key={x.glcode} data-testid={`pv-ledger-${x.glcode}`} className="border-b bg-[oklch(0.985_0.006_265)] text-[12px]">
          <td className="sticky left-0 bg-[oklch(0.985_0.006_265)] px-4 py-1 pl-12">{x.ledger_name}<span className="ml-2 text-[10.5px] text-muted-foreground">ledger {x.glcode}</span></td>
          {cols.map((c) => <td key={c.id} className={cn("num-mono px-2.5 py-1 text-right", tone(x.cells[c.id]))}>{x.cells[c.id] === undefined ? "" : cr2(x.cells[c.id])}</td>)}
          <td className="num-mono px-2.5 py-1 text-right text-muted-foreground">{cr2(x.ly_ytd)}</td>
          <td colSpan={2} />
        </tr>
      ))}
    </>
  );
}

export function PnlPivotTab({ q }: { q: PnlQuery }) {
  const [mode, setMode] = useState<Mode>("stores");
  const [unit, setUnit] = useState<Unit>("cr");
  const [open, setOpen] = useState<string | null>(null);
  const p = usePnlPivot(q, mode);
  return (
    <div className="flex flex-col gap-3 p-3" data-testid="tab-pivot-body">
      <Panel
        testId="pivot-panel"
        eyebrow="Real · verified"
        title="P&L pivot: line × month, quarter, YTD, last year"
        right={
          <div className="flex flex-wrap items-center gap-2">
            <ModeToggle mode={mode} setMode={setMode} />
            <div role="group" aria-label="Unit" className="flex overflow-hidden rounded border text-[12px]">
              {([["cr", "₹ Cr"], ["share", "% of sales"]] as [Unit, string][]).map(([u, label]) => (
                <button key={u} data-testid={`unit-${u}`} aria-pressed={unit === u} onClick={() => setUnit(u)} className={cn("press px-2.5 py-1 font-medium", unit === u ? "bg-foreground text-background" : "hover:bg-muted")}>{label}</button>
              ))}
            </div>
            {p.data && (
              <button data-testid="pivot-export" className="press inline-flex items-center gap-1 rounded border px-2 py-1 text-[12px] font-medium hover:bg-muted"
                onClick={() => {
                  const url = URL.createObjectURL(new Blob([toCsv(p.data!.columns, p.data!.rows)], { type: "text/csv" }));
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `pnl-pivot-${p.data!.run_id}-${mode}.csv`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}>
                <Download className="h-3.5 w-3.5" /> CSV
              </button>
            )}
          </div>
        }
      >
        <LiveBoundary query={p} skeleton={<Skeleton className="m-4 h-[420px]" />}>
          {(d) => {
            const revenue = d.rows.find((r) => r.id === "revenue")!;
            const share = (r: PivotRow, id: string) => {
              const v = r.cells[id];
              const base = Number(revenue.cells[id]);
              return v === null || v === undefined || !base ? DASH : pct(String((Number(v) / base) * 100), false, 1);
            };
            return (
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px]" data-testid="pivot-table" data-mode={d.mode}>
                  <thead>
                    <tr className="border-b text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      <th className="sticky left-0 z-10 min-w-[260px] bg-card px-4 py-2 text-left font-semibold">{unit === "cr" ? "₹ Cr" : "% of net sales"}</th>
                      {d.columns.map(colHead)}
                      <th className="whitespace-nowrap bg-[oklch(0.97_0.008_265)] px-2.5 py-2 text-right font-semibold">LY YTD<span className="block text-[9.5px] font-normal normal-case tracking-normal">day aligned</span></th>
                      <th className="whitespace-nowrap px-2.5 py-2 text-right font-semibold">Var ₹ Cr</th>
                      <th className="whitespace-nowrap px-2.5 py-2 text-right font-semibold">Var %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.rows.map((r) => {
                      const sub = r.kind === "subtotal";
                      const expandable = r.kind === "group" && r.group;
                      const isOpen = open === r.group;
                      return (
                        <Fragment key={r.id}>
                          <tr data-testid={`pv-row-${r.id}`} data-exact={r.cells.ytd ?? ""} onClick={() => expandable && setOpen(isOpen ? null : r.group)}
                            className={cn("border-b", sub && "bg-[oklch(0.975_0.008_265)] font-semibold", r.kind === "memo" && "text-muted-foreground", expandable && "cursor-pointer hover:bg-muted/50")}>
                            <td className={cn("sticky left-0 px-4 py-1.5", sub ? "bg-[oklch(0.975_0.008_265)]" : "bg-card", r.level === 1 && "pl-8")}>
                              <span className="inline-flex items-center gap-1">{expandable ? (isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />) : null}{r.label}</span>
                            </td>
                            {d.columns.map((c) => (
                              <td key={c.id} data-testid={`pv-${r.id}-${c.id}`} data-exact={r.cells[c.id] ?? ""} className={cn("num-mono px-2.5 py-1.5 text-right", tone(r.cells[c.id]), c.kind !== "month" && "bg-[oklch(0.985_0.005_265)]")}>
                                {unit === "cr" ? cr2(r.cells[c.id]) : share(r, c.id)}
                              </td>
                            ))}
                            <td className={cn("num-mono bg-[oklch(0.985_0.005_265)] px-2.5 py-1.5 text-right", tone(r.ly_ytd))}>{d.ly_ytd_available ? (unit === "cr" ? cr2(r.ly_ytd) : DASH) : DASH}</td>
                            <td className={cn("num-mono px-2.5 py-1.5 text-right", tone(r.variance))}>{cr2(r.variance)}</td>
                            <td className={cn("num-mono px-2.5 py-1.5 text-right", tone(r.variance_pct))}>{pct(r.variance_pct, true)}</td>
                          </tr>
                          {expandable && isOpen && <LedgerRows q={q} mode={mode} group={r.group as string} cols={d.columns} />}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
                <div className="border-t px-4 py-2 text-[11.5px] text-muted-foreground" data-testid="pivot-note">
                  {d.mode === "company" ? "Company view: every site, head office and depots included." : `${d.stores} stores.`} {d.ly_ytd_note} Costs are negative. {d.unmapped_note} Budget: not available.
                  Click an expense group for its ledgers.
                </div>
              </div>
            );
          }}
        </LiveBoundary>
      </Panel>
      <ExpenseLinesPanel q={q} />
    </div>
  );
}

function Spark({ values }: { values: (number | null)[] }) {
  const v = values.filter((x): x is number => x !== null);
  if (v.length < 2) return <span className="text-muted-foreground">{DASH}</span>;
  const lo = Math.min(...v), hi = Math.max(...v), W = 76, H = 20;
  const pts = values.map((x, i) => (x === null ? null : `${(i / (values.length - 1)) * W},${H - ((x - lo) / (hi - lo || 1)) * (H - 4) - 2}`)).filter(Boolean).join(" ");
  return <svg width={W} height={H} aria-hidden><polyline points={pts} fill="none" stroke="oklch(0.45 0.12 255)" strokeWidth={1.6} /></svg>;
}

/** Every expense: ₹, % of sales, last year's %, change in basis points, ₹ per sq ft per month (this year and last), trend. */
export function ExpenseLinesPanel({ q }: { q: PnlQuery }) {
  const e = usePnlExpenses(q);
  return (
    <Panel testId="expense-panel" eyebrow="Real · verified" title="Expense lines: ₹, % of sales, bps vs last year, PSF">
      <LiveBoundary query={e} skeleton={<Skeleton className="m-4 h-[260px]" />}>
        {(d) => (
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]" data-testid="expense-table">
              <thead>
                <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-2 font-semibold">Expense</th>
                  <th className="px-3 py-2 text-right font-semibold">₹ Cr</th>
                  <th className="px-3 py-2 text-right font-semibold">% of sales</th>
                  <th className="px-3 py-2 text-right font-semibold">LY %</th>
                  <th className="px-3 py-2 text-right font-semibold">Δ bps</th>
                  <th className="px-3 py-2 text-right font-semibold">₹ PSF / month</th>
                  <th className="px-3 py-2 text-right font-semibold">LY ₹ PSF</th>
                  <th className="px-3 py-2 font-semibold">Trend (% of sales)</th>
                </tr>
              </thead>
              <tbody>
                {d.lines.map((l) => (
                  <tr key={l.group} data-testid={`exp-${l.group}`} data-exact={l.cost} className="border-b last:border-0">
                    <td className="px-4 py-1.5">{l.label}</td>
                    <td className="num-mono px-3 py-1.5 text-right">{cr2(l.cost)}</td>
                    <td className="num-mono px-3 py-1.5 text-right">{pct(l.pct_of_sales, false, 2)}</td>
                    <td className="num-mono px-3 py-1.5 text-right text-muted-foreground">{pct(l.ly_pct_of_sales, false, 2)}</td>
                    <td className={cn("num-mono px-3 py-1.5 text-right", l.bps !== null && Number(l.bps) > 0 ? "tone-bad" : "")}>{bps(l.bps)}</td>
                    <td className="num-mono px-3 py-1.5 text-right">{psf(l.psf)}</td>
                    <td className="num-mono px-3 py-1.5 text-right text-muted-foreground">{psf(l.ly_psf)}</td>
                    <td className="px-3 py-1.5"><Spark values={l.trend.map((t) => (t.pct_of_sales === null ? null : Number(t.pct_of_sales)))} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="border-t px-4 py-2 text-[11.5px] text-muted-foreground" data-testid="expense-note">
              Complete months {d.months.length ? `${monthShort(d.months[0])} to ${monthShort(d.months[d.months.length - 1])}` : ""}. {d.psf_note} PSF covers {d.stores_with_area} of {d.stores} stores (the rest have no area).
              A positive Δ bps means the cost takes more of each rupee of sales than last year.
            </div>
          </div>
        )}
      </LiveBoundary>
    </Panel>
  );
}

/** MTD / QTD / YTD, this year against last year, day aligned. */
export function PnlComparisonTab({ q }: { q: PnlQuery }) {
  const [mode, setMode] = useState<Mode>("stores");
  const c = usePnlComparison(q, mode);
  const metrics: { id: string; label: string; money?: "revenue" | "cogs" | "gross_margin" | "opex" | "contribution"; ratio?: "gross_margin_pct" | "opex_pct" | "contribution_pct" }[] = [
    { id: "revenue", label: "Net sales (ex-GST)", money: "revenue" },
    { id: "cogs", label: "COGS", money: "cogs" },
    { id: "gross_margin", label: "Gross margin ₹", money: "gross_margin" },
    { id: "gm_pct", label: "Gross margin %", ratio: "gross_margin_pct" },
    { id: "opex", label: "Store opex ₹", money: "opex" },
    { id: "opex_pct", label: "Store opex % of sales", ratio: "opex_pct" },
    { id: "contribution", label: "Contribution ₹", money: "contribution" },
    { id: "contribution_pct", label: "Contribution %", ratio: "contribution_pct" },
  ];
  const growthOf = (w: { ty: Record<string, string | null>; ly: Record<string, string | null> | null; growth: Record<string, string | null> | null }, m: (typeof metrics)[number]) => {
    if (!w.ly || !w.growth) return DASH;
    if (m.ratio) {
      const key = m.ratio === "gross_margin_pct" ? "gm_bps" : m.ratio === "opex_pct" ? "opex_bps" : "contribution_bps";
      return bps(w.growth[key]);
    }
    const base = Number(w.ly[m.money!]);
    return base ? pct(String(((Number(w.ty[m.money!]) - base) / Math.abs(base)) * 100), true) : DASH;
  };
  return (
    <div className="flex flex-col gap-3 p-3" data-testid="tab-comparison-body">
      <Panel testId="comparison-panel" eyebrow="Real · verified" title="MTD / QTD / YTD: this year against last year, day aligned" right={<ModeToggle mode={mode} setMode={setMode} />}>
        <LiveBoundary query={c} skeleton={<Skeleton className="m-4 h-[300px]" />}>
          {(d) => (
            <div className="overflow-x-auto">
              <table className="w-full text-[12.5px]" data-testid="comparison-table">
                <thead>
                  <tr className="border-b text-[10.5px] uppercase tracking-wider text-muted-foreground">
                    <th rowSpan={2} className="px-4 py-2 text-left font-semibold">Metric</th>
                    {d.windows.map((w) => (
                      <th key={w.id} colSpan={3} data-testid={`cmp-head-${w.id}`} className="border-l px-3 py-1.5 text-center font-semibold">
                        {w.label}
                        <span className="block text-[9.5px] font-normal normal-case tracking-normal">{monthShort(w.from_month)}{w.from_month !== w.to_month ? ` to ${monthShort(w.to_month)}` : ""}{w.day_aligned ? ` · days 1 to ${d.aligned_days}` : ""}</span>
                      </th>
                    ))}
                  </tr>
                  <tr className="border-b text-[10.5px] uppercase tracking-wider text-muted-foreground">
                    {d.windows.flatMap((w) => ["TY", "LY", "Growth"].map((h) => <th key={`${w.id}-${h}`} className={cn("px-3 py-1.5 text-right font-semibold", h === "TY" && "border-l")}>{h}</th>))}
                  </tr>
                </thead>
                <tbody>
                  {metrics.map((m) => (
                    <tr key={m.id} data-testid={`cmp-${m.id}`} className={cn("border-b last:border-0", m.ratio && "bg-[oklch(0.985_0.005_265)]")}>
                      <td className="px-4 py-1.5 font-medium">{m.label}</td>
                      {d.windows.map((w) => {
                        const ty = m.ratio ? w.ty[m.ratio] : w.ty[m.money!];
                        const ly = w.ly ? (m.ratio ? w.ly[m.ratio] : w.ly[m.money!]) : null;
                        const fmt = (v: string | null) => (m.ratio ? pct(v, false, 2) : cr2(v));
                        return (
                          <Fragment key={w.id}>
                            <td data-testid={`cmp-${m.id}-${w.id}-ty`} data-exact={ty ?? ""} className={cn("num-mono border-l px-3 py-1.5 text-right", !m.ratio && tone(ty))}>{fmt(ty)}</td>
                            <td data-testid={`cmp-${m.id}-${w.id}-ly`} data-exact={ly ?? ""} className="num-mono px-3 py-1.5 text-right text-muted-foreground">{w.ly ? fmt(ly) : DASH}</td>
                            <td className="num-mono px-3 py-1.5 text-right font-semibold">{growthOf(w as never, m)}</td>
                          </Fragment>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="border-t px-4 py-2 text-[11.5px] text-muted-foreground" data-testid="comparison-note">
                {d.note} {d.partial_month ? `The books and the COGS table are read to day ${d.aligned_days} of the as-of month, and last year to the same day.` : "The as-of month is complete."} Amounts compare in %, ratios in basis points.
                {d.windows.some((w) => !w.ly) && " Last year is not available for a window that reaches back before the loaded history."} Budget: not available.
              </div>
            </div>
          )}
        </LiveBoundary>
      </Panel>
    </div>
  );
}
