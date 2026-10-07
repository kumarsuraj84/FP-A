import { useMemo, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { usePnlExpenseExceptions, usePnlHeatmap, usePnlPeers, usePnlQuality, usePnlRevenueExceptions } from "@/api/pnlLiveHooks";
import { DASH } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PnlQuery } from "@/types/pnlLive";
import type { ExpenseException, HeatRow, RevenueException, Severity } from "@/types/pnlReview";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { bps, cr2, FLAG_LABEL, heat, lakh, METRIC_LABEL, monthShort, pct, psf, SEVERITY_STYLE, tone } from "./pnlFormat";

// ───────────── the store EBITDA heat map ─────────────

const HEAT_SORT_LABEL: Record<string, string> = {
  worst_contribution_pct: "Worst contribution %",
  largest_decline_bps: "Largest contribution decline (bps)",
  highest_opex_pct: "Highest opex %",
  worst_opex_deterioration: "Biggest opex deterioration (bps)",
  largest_loss: "Largest ₹ loss (lowest contribution)",
  biggest_opportunity: "Biggest opportunity vs peers",
  best_contribution_pct: "Best contribution %",
  name: "Store name",
};
const FLOORS = [0, 1, 2, 5];

interface HeatCol { key: keyof HeatRow; label: string; fmt: (r: HeatRow) => string; shade?: string; align?: "left" | "right" }
const HEAT_COLS: HeatCol[] = [
  { key: "revenue", label: "Net sales ₹ Cr", fmt: (r) => cr2(r.revenue) },
  { key: "growth_pct", label: "Growth %", fmt: (r) => pct(r.growth_pct, true), shade: "growth_pct" },
  { key: "gross_margin_pct", label: "GM %", fmt: (r) => pct(r.gross_margin_pct), shade: "gross_margin_pct" },
  { key: "opex_pct", label: "Opex %", fmt: (r) => pct(r.opex_pct), shade: "opex_pct" },
  { key: "contribution_pct", label: "Contrib. %", fmt: (r) => pct(r.contribution_pct), shade: "contribution_pct" },
  { key: "contribution", label: "Contrib. ₹ Cr", fmt: (r) => cr2(r.contribution), shade: "contribution" },
  { key: "sales_psf", label: "Sales PSF", fmt: (r) => psf(r.sales_psf), shade: "sales_psf" },
  { key: "payroll_psf", label: "Payroll PSF", fmt: (r) => psf(r.payroll_psf), shade: "payroll_psf" },
  { key: "rent_psf", label: "Rent PSF", fmt: (r) => psf(r.rent_psf), shade: "rent_psf" },
  { key: "power_psf", label: "Power PSF", fmt: (r) => psf(r.power_psf), shade: "power_psf" },
  { key: "ly_contribution_pct", label: "LY contrib. %", fmt: (r) => pct(r.ly_contribution_pct) },
  { key: "contribution_bps", label: "Δ contrib. bps", fmt: (r) => bps(r.contribution_bps), shade: "contribution_bps" },
  { key: "opportunity", label: "Opportunity ₹ Cr", fmt: (r) => (r.opportunity === null ? DASH : cr2(r.opportunity)) },
];

export function HeatMapTab({ q, onPick, picked }: { q: PnlQuery; onPick: (site: string) => void; picked: string | null }) {
  const [sort, setSort] = useState("worst_contribution_pct");
  const [floor, setFloor] = useState(1);
  const h = usePnlHeatmap(q, sort, floor || undefined);
  return (
    <div className="flex flex-col gap-3 p-3" data-testid="tab-heatmap-body">
      <Panel
        testId="heatmap-panel"
        eyebrow="Real · verified"
        title="Store contribution heat map"
        right={
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1 text-[11.5px]"><span className="eyebrow">Sort</span>
              <select aria-label="Heat map sort" data-testid="heat-sort" value={sort} onChange={(e) => setSort(e.target.value)} className="h-7 rounded border bg-card px-1.5 text-[12px] font-medium">
                {Object.entries(HEAT_SORT_LABEL).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-1 text-[11.5px]"><span className="eyebrow">Min net sales</span>
              <select aria-label="Minimum net sales" data-testid="heat-floor" value={floor} onChange={(e) => setFloor(Number(e.target.value))} className="h-7 rounded border bg-card px-1.5 text-[12px]">
                {FLOORS.map((f) => <option key={f} value={f}>{f === 0 ? "none" : `₹${f} Cr`}</option>)}
              </select>
            </label>
          </div>
        }
      >
        <LiveBoundary query={h} skeleton={<Skeleton className="m-4 h-[420px]" />}>
          {(d) => (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]" data-testid="heat-table" data-sort={d.sort}>
                <thead>
                  <tr className="border-b text-[10.5px] uppercase tracking-wider text-muted-foreground">
                    <th className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-semibold">#</th>
                    <th className="sticky left-8 z-10 min-w-[170px] bg-card px-3 py-2 text-left font-semibold">Store</th>
                    <th className="px-3 py-2 text-left font-semibold">Region</th>
                    {HEAT_COLS.map((c) => <th key={c.key} className="whitespace-nowrap px-2.5 py-2 text-right font-semibold">{c.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {d.stores.map((r) => (
                    <tr key={r.site_code} data-testid={`heat-row-${r.site_code}`} data-exact={r.contribution} onClick={() => onPick(r.site_code)} className={cn("cursor-pointer border-b last:border-0 hover:brightness-95", picked === r.site_code && "outline outline-2 -outline-offset-2 outline-[oklch(0.45_0.12_255)]")}>
                      <td className="sticky left-0 bg-card px-3 py-1 text-muted-foreground">{r.rank}</td>
                      <td className="sticky left-8 bg-card px-3 py-1"><span className="font-medium">{r.store_name ?? `Site ${r.site_code}`}</span><span className="ml-1 text-[10.5px] text-muted-foreground">#{r.site_code}</span>{r.vintage === "NEW STORE" && <span className="ml-1 rounded bg-secondary px-1 text-[10px] font-semibold">new</span>}</td>
                      <td className="px-3 py-1 text-muted-foreground">{[r.region, r.cluster].filter((x) => x && x !== "-").join(" · ") || DASH}</td>
                      {HEAT_COLS.map((c) => {
                        const s = c.shade ? d.scales[c.shade] : undefined;
                        const v = r[c.key] as string | null;
                        return <td key={c.key} data-testid={`heat-${r.site_code}-${c.key}`} data-exact={v ?? ""} style={{ background: c.shade ? heat(v, s?.p10, s?.p90, s?.higher_is_better ?? true) : undefined }} className="num-mono px-2.5 py-1 text-right">{c.fmt(r)}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="border-t px-4 py-2 text-[11.5px] text-muted-foreground" data-testid="heat-note">
                {d.returned} of {d.stores_total} stores · complete months {d.months.length ? `${monthShort(d.months[0])} to ${monthShort(d.months[d.months.length - 1])}` : ""} · {d.note} Opportunity is what the store would earn at its peers' median contribution margin (a pointer, not a forecast).
                A store with no area has no PSF; none is estimated.
              </div>
            </div>
          )}
        </LiveBoundary>
      </Panel>
    </div>
  );
}

// ───────────── peer comparison ─────────────

const POSITION_STYLE: Record<string, string> = { "top quartile": "bg-[oklch(0.9_0.08_155)] text-[oklch(0.3_0.1_155)]", middle: "bg-secondary text-secondary-foreground", "bottom quartile": "bg-[oklch(0.92_0.07_25)] text-[oklch(0.4_0.15_25)]" };
const DIM_LABEL: Record<string, string> = { default: "Region + vintage (default)", state: "Same state", region: "Same region", cluster: "Same cluster", vintage: "Same / new store", size_band: "Size band", network: "Whole network" };

export function PeersTab({ q, site, setSite }: { q: PnlQuery; site: string | null; setSite: (s: string | null) => void }) {
  const list = usePnlHeatmap(q, "name");
  const [dim, setDim] = useState("default");
  const stores = list.data?.stores ?? [];
  const chosen = site ?? stores[0]?.site_code ?? null;
  const peers = usePnlPeers(chosen, q);
  return (
    <div className="flex flex-col gap-3 p-3" data-testid="tab-peers-body">
      <Panel
        testId="peers-panel"
        eyebrow="Real · verified"
        title="Peer comparison: is the store weak, or is its market?"
        right={
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1 text-[11.5px]"><span className="eyebrow">Store</span>
              <select aria-label="Store" data-testid="peer-store" value={chosen ?? ""} onChange={(e) => setSite(e.target.value || null)} className="h-7 max-w-[220px] rounded border bg-card px-1.5 text-[12px] font-medium">
                {stores.map((s) => <option key={s.site_code} value={s.site_code}>{`${s.store_name ?? `Site ${s.site_code}`} #${s.site_code}`}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-1 text-[11.5px]"><span className="eyebrow">Peers</span>
              <select aria-label="Peer group" data-testid="peer-dim" value={dim} onChange={(e) => setDim(e.target.value)} className="h-7 rounded border bg-card px-1.5 text-[12px]">
                {Object.entries(DIM_LABEL).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
              </select>
            </label>
          </div>
        }
      >
        <LiveBoundary query={peers} skeleton={<Skeleton className="m-4 h-[300px]" />}>
          {(d) => {
            const g = d.groups.find((x) => x.dimension === dim) ?? d.groups[0];
            return (
              <div className="overflow-x-auto">
                <div className="border-b px-4 py-2 text-[12px]" data-testid="peer-basis">
                  Compared with <span className="font-semibold">{g.peers} peers</span> ({g.basis}{g.basis !== g.requested ? `, widened from ${g.requested} because too few stores qualified` : ""}). Peers need ₹1 Cr of net sales in the period.
                  {" "}Store: {[d.keys.region, d.keys.state, d.keys.cluster, d.keys.vintage, d.keys.size_band].filter((x) => x && x !== "-").join(" · ")}
                </div>
                <table className="w-full text-[12.5px]" data-testid="peer-table">
                  <thead>
                    <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      <th className="px-4 py-2 font-semibold">Measure</th>
                      <th className="px-3 py-2 text-right font-semibold">Store</th>
                      <th className="px-3 py-2 text-right font-semibold">Peer median</th>
                      <th className="px-3 py-2 text-right font-semibold">Top quartile</th>
                      <th className="px-3 py-2 text-right font-semibold">Bottom quartile</th>
                      <th className="px-3 py-2 text-right font-semibold">vs median</th>
                      <th className="px-3 py-2 font-semibold">Position</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.metrics.map((m) => {
                      const meta = METRIC_LABEL[m.metric];
                      const f = (v: string | null) => (meta.kind === "pct" ? pct(v, m.metric === "growth_pct", 1) : psf(v));
                      return (
                        <tr key={m.metric} data-testid={`peer-${m.metric}`} data-exact={m.store ?? ""} className="border-b last:border-0">
                          <td className="px-4 py-1.5 font-medium">{meta.label}</td>
                          <td className="num-mono px-3 py-1.5 text-right font-semibold">{f(m.store)}</td>
                          <td className="num-mono px-3 py-1.5 text-right">{f(m.peer_median)}</td>
                          <td className="num-mono px-3 py-1.5 text-right text-muted-foreground">{f(m.top_quartile)}</td>
                          <td className="num-mono px-3 py-1.5 text-right text-muted-foreground">{f(m.bottom_quartile)}</td>
                          <td className={cn("num-mono px-3 py-1.5 text-right", m.vs_median !== null && (Number(m.vs_median) < 0) === meta.higher ? "tone-bad" : "")}>{m.vs_median === null ? DASH : (meta.kind === "pct" ? `${Number(m.vs_median) > 0 ? "+" : "−"}${Math.abs(Number(m.vs_median)).toFixed(1)} pts` : `${Number(m.vs_median) > 0 ? "+" : "−"}₹${Math.abs(Number(m.vs_median)).toFixed(1)}`)}</td>
                          <td className="px-3 py-1.5">{m.position ? <span className={cn("rounded px-1.5 py-0.5 text-[11px] font-semibold", POSITION_STYLE[m.position])}>{m.position}</span> : <span className="text-muted-foreground">{DASH}</span>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <div className="border-t px-4 py-2 text-[11.5px] text-muted-foreground">For costs (opex %, payroll, rent and power per sq ft) the top quartile is the LOW end. {d.rules.peers}.</div>
              </div>
            );
          }}
        </LiveBoundary>
      </Panel>
    </div>
  );
}

// ───────────── exceptions ─────────────

function SeverityChips({ counts, active, setActive }: { counts: Partial<Record<Severity, number>>; active: Severity | null; setActive: (s: Severity | null) => void }) {
  return (
    <div className="flex flex-wrap gap-2 px-4 py-2" data-testid="severity-chips">
      {(["Critical", "High", "Medium"] as Severity[]).map((s) => (
        <button key={s} data-testid={`sev-${s}`} data-count={counts[s] ?? 0} aria-pressed={active === s} onClick={() => setActive(active === s ? null : s)}
          className={cn("press inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[12px] font-medium", active === s ? "ring-2 ring-foreground" : "bg-card hover:bg-muted")}>
          <span className={cn("rounded px-1.5 text-[10.5px] font-bold", SEVERITY_STYLE[s])}>{s}</span>
          <span className="num-mono font-semibold">{counts[s] ?? 0}</span>
        </button>
      ))}
    </div>
  );
}

function Rules({ rules }: { rules: Record<string, string> }) {
  return (
    <details className="border-t px-4 py-2 text-[11.5px] text-muted-foreground" data-testid="exception-rules">
      <summary className="cursor-pointer font-semibold text-foreground">How exceptions are flagged</summary>
      <p className="mt-1">These are review heuristics, not accounting: they point to what a reviewer should open and never change a number.</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">{Object.entries(rules).map(([k, v]) => <li key={k}><span className="font-medium text-foreground">{FLAG_LABEL[k.toUpperCase()] ?? k.replace(/_/g, " ")}:</span> {v}</li>)}</ul>
    </details>
  );
}

function FlagChips({ flags }: { flags: string[] }) {
  return <div className="flex flex-wrap gap-1">{flags.map((f) => <span key={f} className="rounded bg-secondary px-1.5 py-0.5 text-[10.5px] font-semibold">{FLAG_LABEL[f] ?? f}</span>)}</div>;
}

export function ExpenseExceptionsTab({ q, onOpen, picked }: { q: PnlQuery; onOpen: (site: string, group: string) => void; picked: string | null }) {
  const x = usePnlExpenseExceptions(q);
  const [sev, setSev] = useState<Severity | null>(null);
  const [group, setGroup] = useState("");
  return (
    <div className="flex flex-col gap-3 p-3" data-testid="tab-expense-exceptions-body">
      <Panel testId="expense-exceptions-panel" eyebrow="Real · verified" title="Expense exceptions: sudden moves, share of sales, peers, PSF, trend breaks">
        <LiveBoundary query={x} skeleton={<Skeleton className="m-4 h-[300px]" />}>
          {(d) => {
            const groups = [...new Set(d.exceptions.map((e) => e.group))].sort();
            const rows = d.exceptions.filter((e) => (!sev || e.severity === sev) && (!group || e.group === group));
            return (
              <div className="overflow-x-auto">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b">
                  <SeverityChips counts={d.by_severity} active={sev} setActive={setSev} />
                  <label className="flex items-center gap-1 px-4 text-[11.5px]"><span className="eyebrow">Expense</span>
                    <select aria-label="Expense group" data-testid="exc-group" value={group} onChange={(e) => setGroup(e.target.value)} className="h-7 rounded border bg-card px-1.5 text-[12px]">
                      <option value="">All</option>
                      {groups.map((g) => <option key={g} value={g}>{g.replace(/^\d+-/, "")}</option>)}
                    </select>
                  </label>
                </div>
                <div className="border-b px-4 py-1.5 text-[11.5px] text-muted-foreground" data-testid="exc-month">
                  Reviewing {d.month ? monthShort(d.month) : DASH} against the 3 months before it.{d.provisional_month && <span className="ml-1 font-semibold text-[oklch(0.5_0.12_60)]">This month has unposted entries: confirm before acting.</span>}
                </div>
                <table className="w-full text-[12.5px]" data-testid="expense-exceptions-table">
                  <thead>
                    <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      <th className="px-4 py-2 font-semibold">Severity</th><th className="px-3 py-2 font-semibold">Store</th><th className="px-3 py-2 font-semibold">Expense</th>
                      <th className="px-3 py-2 text-right font-semibold">Current</th><th className="px-3 py-2 text-right font-semibold">Expected</th><th className="px-3 py-2 text-right font-semibold">Variance</th>
                      <th className="px-3 py-2 text-right font-semibold">% sales</th><th className="px-3 py-2 text-right font-semibold">PSF</th><th className="px-3 py-2 text-right font-semibold">Peer %</th><th className="px-3 py-2 font-semibold">Why flagged</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((e: ExpenseException) => (
                      <tr key={`${e.site_code}-${e.group}`} data-testid={`exc-${e.site_code}-${e.group}`} data-severity={e.severity} onClick={() => onOpen(e.site_code, e.group)} className={cn("cursor-pointer border-b align-top last:border-0 hover:bg-muted/50", picked === e.site_code && "bg-[oklch(0.95_0.025_265)]")}>
                        <td className="px-4 py-1.5"><span className={cn("rounded px-1.5 py-0.5 text-[10.5px] font-bold", SEVERITY_STYLE[e.severity])}>{e.severity}</span></td>
                        <td className="px-3 py-1.5"><span className="font-medium">{e.store_name ?? `Site ${e.site_code}`}</span><span className="ml-1 text-[10.5px] text-muted-foreground">#{e.site_code}</span></td>
                        <td className="px-3 py-1.5">{e.label}</td>
                        <td className="num-mono px-3 py-1.5 text-right">{lakh(e.current)}</td>
                        <td className="num-mono px-3 py-1.5 text-right text-muted-foreground">{lakh(e.expected)}</td>
                        <td className={cn("num-mono px-3 py-1.5 text-right", Number(e.variance) > 0 && "tone-bad")}>{pct(e.variance_pct, true, 0)}</td>
                        <td className="num-mono px-3 py-1.5 text-right">{pct(e.pct_of_sales, false, 2)}</td>
                        <td className="num-mono px-3 py-1.5 text-right">{psf(e.psf)}</td>
                        <td className="num-mono px-3 py-1.5 text-right text-muted-foreground">{pct(e.peer_pct_of_sales, false, 2)}</td>
                        <td className="max-w-[420px] px-3 py-1.5"><FlagChips flags={e.flags} /><div className="mt-1 text-[11.5px] text-muted-foreground">{e.why}</div></td>
                      </tr>
                    ))}
                    {rows.length === 0 && <tr><td colSpan={10} className="px-4 py-6 text-center text-muted-foreground" data-testid="exc-empty">No expense exception{sev ? ` at ${sev} severity` : ""}.</td></tr>}
                  </tbody>
                </table>
                <div className="border-t px-4 py-2 text-[11.5px] text-muted-foreground">{rows.length} of {d.total} flagged. Click a row: store → expense group → ledger → month. The voucher level arrives with the common entry layer.</div>
                <Rules rules={d.rules} />
              </div>
            );
          }}
        </LiveBoundary>
      </Panel>
    </div>
  );
}

export function RevenueExceptionsTab({ q, onOpen, picked }: { q: PnlQuery; onOpen: (site: string) => void; picked: string | null }) {
  const x = usePnlRevenueExceptions(q);
  const [sev, setSev] = useState<Severity | null>(null);
  return (
    <div className="flex flex-col gap-3 p-3" data-testid="tab-revenue-exceptions-body">
      <Panel testId="revenue-exceptions-panel" eyebrow="Real · verified" title="Revenue exceptions: sales collapse, productivity, growth that costs margin or profit">
        <LiveBoundary query={x} skeleton={<Skeleton className="m-4 h-[300px]" />}>
          {(d) => {
            const rows = d.exceptions.filter((e) => !sev || e.severity === sev);
            return (
              <div className="overflow-x-auto">
                <div className="border-b"><SeverityChips counts={d.by_severity} active={sev} setActive={setSev} /></div>
                <div className="border-b px-4 py-1.5 text-[11.5px] text-muted-foreground" data-testid="exc-month">Reviewing {d.month ? monthShort(d.month) : DASH}.{d.provisional_month && <span className="ml-1 font-semibold text-[oklch(0.5_0.12_60)]">This month has unposted sales: confirm before acting.</span>}</div>
                <table className="w-full text-[12.5px]" data-testid="revenue-exceptions-table">
                  <thead>
                    <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      <th className="px-4 py-2 font-semibold">Severity</th><th className="px-3 py-2 font-semibold">Store</th><th className="px-3 py-2 text-right font-semibold">Net sales</th><th className="px-3 py-2 text-right font-semibold">3M avg</th>
                      <th className="px-3 py-2 text-right font-semibold">Growth</th><th className="px-3 py-2 text-right font-semibold">GM %</th><th className="px-3 py-2 text-right font-semibold">Sales PSF</th><th className="px-3 py-2 font-semibold">Why flagged</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((e: RevenueException) => (
                      <tr key={e.site_code} data-testid={`rexc-${e.site_code}`} data-severity={e.severity} onClick={() => onOpen(e.site_code)} className={cn("cursor-pointer border-b align-top last:border-0 hover:bg-muted/50", picked === e.site_code && "bg-[oklch(0.95_0.025_265)]")}>
                        <td className="px-4 py-1.5"><span className={cn("rounded px-1.5 py-0.5 text-[10.5px] font-bold", SEVERITY_STYLE[e.severity])}>{e.severity}</span></td>
                        <td className="px-3 py-1.5"><span className="font-medium">{e.store_name ?? `Site ${e.site_code}`}</span><span className="ml-1 text-[10.5px] text-muted-foreground">#{e.site_code}</span></td>
                        <td className="num-mono px-3 py-1.5 text-right">{lakh(e.revenue)}</td>
                        <td className="num-mono px-3 py-1.5 text-right text-muted-foreground">{lakh(e.baseline_revenue)}</td>
                        <td className={cn("num-mono px-3 py-1.5 text-right", tone(e.growth_pct))}>{pct(e.growth_pct, true, 0)}</td>
                        <td className="num-mono px-3 py-1.5 text-right">{pct(e.gross_margin_pct)}</td>
                        <td className="num-mono px-3 py-1.5 text-right">{psf(e.sales_psf)}</td>
                        <td className="max-w-[460px] px-3 py-1.5"><FlagChips flags={e.flags} /><div className="mt-1 text-[11.5px] text-muted-foreground">{e.why}</div></td>
                      </tr>
                    ))}
                    {rows.length === 0 && <tr><td colSpan={8} className="px-4 py-6 text-center text-muted-foreground" data-testid="exc-empty">No revenue exception{sev ? ` at ${sev} severity` : ""}.</td></tr>}
                  </tbody>
                </table>
                <div className="border-t px-4 py-2 text-[11.5px] text-muted-foreground">{rows.length} of {d.total} flagged. Click a row to open the store.</div>
                <Rules rules={d.rules} />
              </div>
            );
          }}
        </LiveBoundary>
      </Panel>
    </div>
  );
}

// ───────────── unmapped / data quality ─────────────

export function QualityTab({ q, reconciliation }: { q: PnlQuery; reconciliation: ReactNode }) {
  const d = usePnlQuality(q);
  const cogs = useMemo(() => d.data?.cogs_pct_by_month ?? [], [d.data]);
  return (
    <div className="flex flex-col gap-3 p-3" data-testid="tab-quality-body">
      <Panel testId="quality-panel" eyebrow="Real · verified" title="Data quality: what is missing or doubtful in the inputs">
        <LiveBoundary query={d} skeleton={<Skeleton className="m-4 h-[220px]" />}>
          {(x) => (
            <div className="grid grid-cols-3 divide-x @max-[1000px]:grid-cols-1 @max-[1000px]:divide-x-0 @max-[1000px]:divide-y">
              <div className="p-4 text-[12.5px]" data-testid="quality-area">
                <div className="eyebrow">Store area</div>
                <div className="mt-1 text-[22px] font-semibold num-mono">{x.stores_without_area.count} <span className="text-[13px] font-normal text-muted-foreground">of {x.stores} stores have no area</span></div>
                <p className="mt-1 text-muted-foreground">{x.stores_without_area.effect}</p>
                <ul className="mt-2 space-y-0.5">{x.stores_without_area.sites.slice(0, 8).map((s) => <li key={s.site_code}>{s.store_name ?? `Site ${s.site_code}`} <span className="text-[10.5px] text-muted-foreground">#{s.site_code}</span></li>)}</ul>
                <p className="mt-2 text-[11.5px] text-muted-foreground">{x.area_units_note}</p>
              </div>
              <div className="p-4 text-[12.5px]" data-testid="quality-dates">
                <div className="eyebrow">Opening and closing dates</div>
                <div className="mt-1"><span className="num-mono text-[18px] font-semibold">{x.stores_with_placeholder_opening_date.count}</span> stores carry a placeholder opening date</div>
                <p className="text-muted-foreground">{x.stores_with_placeholder_opening_date.effect}</p>
                <div className="mt-2"><span className="num-mono text-[18px] font-semibold">{x.closed_stores_without_a_closing_date.count}</span> closed stores have no closing date</div>
                <p className="text-muted-foreground">{x.closed_stores_without_a_closing_date.effect}</p>
                <div className="eyebrow mt-3">Effective-area reasons</div>
                <ul className="mt-1 space-y-0.5 text-[11.5px]">{x.effective_area_reasons.slice(0, 7).map((r) => <li key={r.reason}><span className="num-mono">{r.n.toLocaleString("en-IN")}</span> {r.reason.replace(/\+/g, " + ").replace(/_/g, " ").toLowerCase()}</li>)}</ul>
              </div>
              <div className="p-4 text-[12.5px]" data-testid="quality-cogs">
                <div className="eyebrow">COGS as % of net sales, by month</div>
                <ul className="mt-1 space-y-0.5">
                  {cogs.map((m) => (
                    <li key={m.month} className="flex items-center gap-2" data-outlier={m.outlier ? "1" : "0"}>
                      <span className="w-14 text-muted-foreground">{monthShort(m.month)}</span>
                      <span className="h-2 flex-1 rounded bg-secondary"><span className={cn("block h-2 rounded", m.outlier ? "bg-[oklch(0.58_0.2_25)]" : "bg-[oklch(0.45_0.08_255)]")} style={{ width: `${Math.min(100, Number(m.cogs_pct_of_sales ?? 0))}%` }} /></span>
                      <span className={cn("num-mono w-12 text-right", m.outlier && "font-semibold tone-bad")}>{pct(m.cogs_pct_of_sales)}</span>
                      {m.outlier && <AlertTriangle className="h-3.5 w-3.5 text-[oklch(0.58_0.2_25)]" aria-label="outlier" />}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11.5px] text-muted-foreground">Typical {pct(x.cogs_typical_pct)}. A month 6 points or more above it is marked; the cause is not known (cost adjustments, stock corrections or timing).</p>
              </div>
            </div>
          )}
        </LiveBoundary>
      </Panel>
      {reconciliation}
    </div>
  );
}
