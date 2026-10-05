import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronUp, Info, Lock, Search, X } from "lucide-react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cn } from "@/lib/utils";
import {
  DASH,
  aggregateStores,
  billsAbvBridge,
  coverageFor,
  fmtDay,
  fmtGrowth,
  fmtInr,
  fmtNum,
  fmtRange,
  inCohort,
  mappingRule,
  planPeriods,
  reconciles,
  storeDaily,
  totalsFor,
  trendFor,
  weekday,
  type CohortFilter,
  type CompareMode,
  type DayTable,
  type PeriodPlan,
  type StoreAgg,
  type TrendPoint,
} from "@/lib/salesCompare";
import { SAMPLE_AS_OF, SAMPLE_STORES, buildSample } from "@/mocks/salesSample";

/**
 * Operations · Sales Comparison: design prototype on SAMPLE data.
 * Real measures that are not yet certified are shown as unavailable, with the reason. Nothing here is read from CityKart systems.
 * Store cohorts here follow an ILLUSTRATIVE rule; production eligibility is still to be decided.
 */

const MODES: { id: CompareMode; label: string; hint: string }[] = [
  { id: "same_dates", label: "Same dates", hint: "Each day against the same calendar date last year" },
  { id: "same_weekdays", label: "Same weekdays", hint: "Each day against the day 364 days earlier (same weekday)" },
  { id: "custom", label: "Custom period", hint: "Any two periods; unequal lengths are flagged" },
];
const COHORTS: { id: CohortFilter; label: string }[] = [
  { id: "comparable", label: "Comparable stores" },
  { id: "all", label: "All stores" },
  { id: "new", label: "New stores" },
];
type ViewState = "normal" | "loading" | "empty";
const VIEW_STATES: { id: ViewState; label: string }[] = [
  { id: "normal", label: "Normal" },
  { id: "loading", label: "Loading" },
  { id: "empty", label: "Empty" },
];

type Readiness = "conditional" | "unavailable";
const READINESS: { metric: string; status: Readiness; note: string }[] = [
  { metric: "Sales (incl. GST)", status: "conditional", note: "Dashboard view and POS cube agree within 0.012% in 17 of 19 months checked; April 2026 differs by 5.15% and is unexplained. Not certified." },
  { metric: "Sales ex-GST", status: "conditional", note: "Equals taxable value within ₹100 a month on checked months." },
  { metric: "Units", status: "conditional", note: "Totals agree; not independently reconciled." },
  { metric: "ASP", status: "conditional", note: "Sales ÷ Units, recomputed at every level." },
  { metric: "Store contribution", status: "conditional", note: "Store-day key is sound by definition; the comparable-store rule is still to be agreed." },
  { metric: "Same dates / same weekdays / custom", status: "conditional", note: "Computed from history with the reference dates shown. How far back each source reaches is being certified; unreached dates show unavailable." },
  { metric: "Bills, ABV, Bills → ABV bridge", status: "unavailable", note: "No certified bill identity or counting rule yet; return bills are counted as bills in the source." },
  { metric: "Department contribution", status: "unavailable", note: "No department history source verified." },
  { metric: "Festival-stage comparison", status: "unavailable", note: "Source date mappings disagree; the convention is a business decision." },
  { metric: "Footfall and conversion", status: "unavailable", note: "Only current-month, 120-store counters exist." },
  { metric: "Target achievement", status: "unavailable", note: "Not yet examined." },
];

const chip = "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold";
const AMBER = "bg-[oklch(0.985_0.03_90)] text-[oklch(0.45_0.09_75)]";

function SampleBanner({ testId = "sample-banner" }: { testId?: string }) {
  return (
    <div className="flex min-h-6 items-center bg-[oklch(0.96_0.06_85)] px-4 py-0.5 text-[11px] font-medium text-[oklch(0.38_0.09_70)]" data-testid={testId}>
      <span className="flex items-center gap-1.5"><Info className="h-3 w-3 shrink-0" /> SAMPLE DATA — invented stores and numbers to review the design. Nothing here comes from CityKart systems.</span>
    </div>
  );
}

function Unavailable({ id, title, reason }: { id: string; title: string; reason: string }) {
  return (
    <div data-testid={`unavailable-${id}`} className="flex items-start gap-2 rounded-lg border border-dashed bg-muted/40 p-3">
      <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-foreground">{title}</div>
        <div className="text-[12px] text-muted-foreground">Unavailable: {reason}</div>
      </div>
    </div>
  );
}

function Kpi({ id, label, value, reference, delta, growth, notes, provisional }: { id: string; label: string; value: string; reference: string; delta: number | null; growth: number | null; notes?: string[]; provisional?: boolean }) {
  const tone = delta == null || delta === 0 ? "tone-neutral" : delta > 0 ? "tone-good" : "tone-bad";
  return (
    <div data-testid={`kpi-${id}`} className="min-w-0 rounded-lg border bg-card p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="eyebrow">{label}</span>
        {provisional && <span className={cn(chip, AMBER)}>Provisional</span>}
      </div>
      <div className="num mt-1 truncate text-[22px] font-semibold tracking-tight text-foreground" data-testid={`kpi-${id}-value`}>{value}</div>
      <div className="mt-0.5 flex items-center gap-1.5 text-[12px]">
        <span className={cn("num font-semibold", tone)} data-testid={`kpi-${id}-delta`}>
          {delta == null ? DASH : delta > 0 ? <ArrowUp className="mr-0.5 inline h-3 w-3" /> : delta < 0 ? <ArrowDown className="mr-0.5 inline h-3 w-3" /> : null}
          {id === "units" ? fmtNum(delta, { signed: true }) : fmtInr(delta, { signed: true })}
        </span>
        <span className={cn("num font-semibold", tone)} data-testid={`kpi-${id}-growth`}>{fmtGrowth(growth)}</span>
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">Reference {reference}</div>
      {notes?.map((n) => (<div key={n} className="mt-0.5 text-[11px] text-muted-foreground" data-testid={`kpi-${id}-note`}>{n}</div>))}
    </div>
  );
}

function KpiUnavailable({ id, label, reason }: { id: string; label: string; reason: string }) {
  return (
    <div data-testid={`kpi-${id}`} className="min-w-0 rounded-lg border border-dashed bg-muted/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="eyebrow">{label}</span>
        <span className={cn(chip, "bg-secondary text-secondary-foreground")}><Lock className="h-3 w-3" /> Unavailable</span>
      </div>
      <div className="num mt-1 text-[22px] font-semibold tracking-tight text-muted-foreground/60" data-testid={`kpi-${id}-value`}>{DASH}</div>
      <div className="mt-0.5 text-[11px] text-muted-foreground" data-testid={`kpi-${id}-reason`}>{reason}</div>
    </div>
  );
}

function TrendTooltip({ active, payload }: { active?: boolean; payload?: { payload: TrendPoint }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border bg-card p-2 text-[12px] shadow-md">
      <div className="num">Current {p.curDate ? `${fmtDay(p.curDate)} (${weekday(p.curDate)})` : DASH}: <b>{fmtInr(p.cur)}</b></div>
      <div className="num">Reference {p.refDate ? `${fmtDay(p.refDate)} (${weekday(p.refDate)})` : DASH}: <b>{fmtInr(p.ref)}</b></div>
    </div>
  );
}

const axisInr = (v: number) => (v >= 1e7 ? `₹${(v / 1e7).toFixed(1)}Cr` : v >= 1e5 ? `₹${(v / 1e5).toFixed(0)}L` : `₹${Math.round(v).toLocaleString("en-IN")}`);

/** A worked example with invented figures, kept apart from the screen's real-evidence status. */
function BridgeExample() {
  const b = billsAbvBridge(1000, 1000, 900, 1050);
  return (
    <section data-testid="bridge-example" aria-label="Sample worked example: Bills to ABV" className="rounded-lg border-2 border-dashed border-[oklch(0.8_0.08_295)] bg-[oklch(0.985_0.012_295)] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[14px] font-semibold">Worked example: Bills → ABV bridge</h2>
        <span className={cn(chip, "bg-[oklch(0.94_0.04_295)] text-[oklch(0.35_0.14_295)]")}>Invented figures · design example only</span>
      </div>
      <p className="mt-1 text-[12px] text-muted-foreground" data-testid="bridge-example-note">
        This shows how the explanation would read once a certified bill count exists. It does not use the sample stores above and is not production evidence. The real bridge stays unavailable.
      </p>
      <div className="mt-2 grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        <table className="w-full text-[12px]">
          <thead><tr className="text-left text-muted-foreground"><th className="py-0.5 font-medium"></th><th className="py-0.5 text-right font-medium">Reference</th><th className="py-0.5 text-right font-medium">Current</th></tr></thead>
          <tbody className="num">
            <tr><td>Bills</td><td className="text-right">1,000</td><td className="text-right">900</td></tr>
            <tr><td>ABV (sales ÷ bills)</td><td className="text-right">₹1,000</td><td className="text-right">₹1,050</td></tr>
            <tr className="border-t font-semibold"><td>Sales</td><td className="text-right" data-testid="ex-sales-ref">{fmtInr(b.salesRef)}</td><td className="text-right" data-testid="ex-sales-cur">{fmtInr(b.salesCur)}</td></tr>
          </tbody>
        </table>
        <div className="text-[12px]">
          <div className="eyebrow">Order shown: bills first, then ABV</div>
          <ol className="mt-1 space-y-1">
            <li>1. <b>Bills effect</b> = (900 − 1,000) × ₹1,000 = <span className="num font-semibold tone-bad" data-testid="ex-bills-effect">{fmtInr(b.billsEffect, { signed: true })}</span></li>
            <li>2. <b>ABV effect</b> = (₹1,050 − ₹1,000) × 900 = <span className="num font-semibold tone-good" data-testid="ex-abv-effect">{fmtInr(b.abvEffect, { signed: true })}</span></li>
            <li className="border-t pt-1">Total = <span className="num font-semibold" data-testid="ex-total">{fmtInr(b.billsEffect + b.abvEffect, { signed: true })}</span> = sales difference <span className="num font-semibold" data-testid="ex-delta">{fmtInr(b.delta, { signed: true })}</span> {b.exact ? "✓ reconciles" : "✗ does not reconcile"}</li>
          </ol>
        </div>
      </div>
    </section>
  );
}

function StoreDetail({ agg, rows, plan, onClose }: { agg: StoreAgg; rows: DayTable; plan: PeriodPlan; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  const days = storeDaily(rows, agg.store.code, plan);
  return (
    <>
      <button aria-label="Close store detail" onClick={onClose} className="fixed inset-0 z-30 cursor-default bg-black/20" />
      <aside role="dialog" aria-label={`${agg.store.name} detail`} data-testid="store-detail" className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[480px] flex-col overflow-y-auto border-l bg-card shadow-elevated">
        <SampleBanner testId="detail-sample-banner" />
        <div className="flex items-start justify-between gap-2 border-b px-4 py-3">
          <div className="min-w-0">
            <div className="eyebrow">Store detail · {agg.store.region}</div>
            <h2 className="truncate text-[17px] font-semibold tracking-tight">{agg.store.name}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <span className={cn(chip, agg.status === "comparable" ? "bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]" : agg.status === "new" ? "bg-[oklch(0.95_0.025_265)] text-primary" : AMBER)}>{agg.status === "comparable" ? "Comparable" : agg.status === "new" ? "New" : "Data gap"}</span>
              <span className="text-[11px] text-muted-foreground" data-testid="detail-reason">Illustrative rule: {agg.reason}</span>
            </div>
          </div>
          <button data-testid="close-detail" onClick={onClose} className="press rounded border p-1 hover:bg-muted" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="grid grid-cols-3 gap-2 border-b px-4 py-3 text-[12px]">
          <div><div className="eyebrow">Current</div><div className="num text-[15px] font-semibold" data-testid="detail-cur">{fmtInr(agg.cur)}</div></div>
          <div><div className="eyebrow">Reference</div><div className="num text-[15px] font-semibold" data-testid="detail-ref">{fmtInr(agg.ref)}</div></div>
          <div><div className="eyebrow">Difference</div><div className={cn("num text-[15px] font-semibold", agg.delta < 0 ? "tone-bad" : agg.delta > 0 ? "tone-good" : "tone-neutral")}>{fmtInr(agg.delta, { signed: true })}</div></div>
          <div className="col-span-3 text-[11px] text-muted-foreground" data-testid="detail-coverage">Days with data: current {agg.curDays} of {plan.curDates.length}, reference {agg.refDays} of {plan.refDates.length}. A dash is no data, not zero.</div>
        </div>
        <table className="w-full border-collapse text-[12px]">
          <thead className="bg-[oklch(0.3_0.1_265)] text-white">
            <tr>
              <th className="px-3 py-1.5 text-left text-[11px] font-semibold uppercase">Current day</th>
              <th className="px-3 py-1.5 text-right text-[11px] font-semibold uppercase">Sales</th>
              <th className="px-3 py-1.5 text-left text-[11px] font-semibold uppercase">Reference day</th>
              <th className="px-3 py-1.5 text-right text-[11px] font-semibold uppercase">Sales</th>
            </tr>
          </thead>
          <tbody>
            {days.map((d, i) => (
              <tr key={d.index} data-testid={`detail-day-${d.index}`} className={cn("border-t", i % 2 ? "bg-muted/40" : "")}>
                <td className="num px-3 py-1">{d.curDate ? `${fmtDay(d.curDate)} ${weekday(d.curDate)}` : DASH}</td>
                <td className={cn("num px-3 py-1 text-right", !d.cur && "text-muted-foreground")} data-testid={`detail-cur-${d.index}`}>{d.cur ? fmtInr(d.cur.sales) : DASH}</td>
                <td className="num px-3 py-1">{d.refDate ? `${fmtDay(d.refDate)} ${weekday(d.refDate)}` : DASH}</td>
                <td className={cn("num px-3 py-1 text-right", !d.ref && "text-muted-foreground")} data-testid={`detail-ref-${d.index}`}>{d.ref ? fmtInr(d.ref.sales) : DASH}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </aside>
    </>
  );
}

function Skeleton() {
  return (
    <div data-testid="loading" role="status" aria-label="Loading sample data" className="space-y-4 p-4">
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))" }}>
        {Array.from({ length: 5 }, (_, i) => (<div key={i} className="h-[104px] animate-pulse rounded-lg border bg-muted/60" />))}
      </div>
      <div className="h-[240px] animate-pulse rounded-lg border bg-muted/60" />
      <div className="h-[320px] animate-pulse rounded-lg border bg-muted/60" />
    </div>
  );
}

type SortKey = "name" | "cur" | "ref" | "delta" | "growth";

export function SalesComparison() {
  const rows = useMemo(() => buildSample(), []);
  const [mode, setMode] = useState<CompareMode>("same_weekdays");
  const [cohort, setCohort] = useState<CohortFilter>("comparable");
  const [viewState, setViewState] = useState<ViewState>("normal");
  const [start, setStart] = useState("2026-10-01");
  const [end, setEnd] = useState(SAMPLE_AS_OF);
  const [refStart, setRefStart] = useState("2025-09-20");
  const [refEnd, setRefEnd] = useState("2025-10-03");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "delta", dir: 1 });

  const plan = useMemo(() => planPeriods(mode, start, end, { start: refStart, end: refEnd }), [mode, start, end, refStart, refEnd]);
  const all = useMemo(() => (plan.valid ? aggregateStores(SAMPLE_STORES, rows, plan) : []), [plan, rows]);
  const included = useMemo(() => all.filter((a) => inCohort(a, cohort)), [all, cohort]);
  const totals = useMemo(() => totalsFor(included), [included]);
  const coverage = useMemo(() => coverageFor(included, plan), [included, plan]);
  const ok = useMemo(() => reconciles(included, totals), [included, totals]);
  const trend = useMemo(() => (plan.valid ? trendFor(included, rows, plan) : []), [included, rows, plan]);
  const excluded = useMemo(() => all.filter((a) => !inCohort(a, cohort)), [all, cohort]);
  const beyondAsOf = plan.curDates.some((d) => d > SAMPLE_AS_OF);
  const selectedAgg = selected ? all.find((a) => a.store.code === selected) ?? null : null;
  const noReference = plan.valid && included.length > 0 && coverage.refPresent === 0;

  const view = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = included.filter((a) => !q || a.store.name.toLowerCase().includes(q) || a.store.code.toLowerCase().includes(q) || a.store.region.toLowerCase().includes(q));
    const val = (a: StoreAgg) => (sort.key === "name" ? a.store.name : sort.key === "cur" ? a.cur ?? -Infinity : sort.key === "ref" ? a.ref ?? -Infinity : sort.key === "delta" ? a.delta : a.growth ?? -Infinity);
    return [...list].sort((a, b) => {
      const x = val(a);
      const y = val(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [included, query, sort]);

  const decliners = [...included].filter((a) => a.delta < 0).sort((a, b) => a.delta - b.delta).slice(0, 3);
  const gainers = [...included].filter((a) => a.delta > 0).sort((a, b) => b.delta - a.delta).slice(0, 3);
  const gaps = all.filter((a) => a.status === "gap");
  const curDays = plan.curDates.length;
  const refDays = plan.refDates.length;
  const showPerStoreDay = mode === "custom";

  const th = (label: string, key: SortKey, right = true) => (
    <th scope="col" className={cn("px-3 py-2 text-[11px] font-semibold uppercase tracking-wide", right ? "text-right" : "text-left")}>
      <button data-testid={`sort-${key}`} onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((s.dir * -1) as 1 | -1) : 1 }))} className="press inline-flex items-center gap-1 text-white/90 hover:text-white">
        {label}
        {sort.key === key ? sort.dir === 1 ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" /> : null}
      </button>
    </th>
  );

  return (
    <div data-testid="sales-comparison" className="@container">
      <SampleBanner />

      <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-5 py-3">
        <div className="min-w-0">
          <div className="eyebrow">Operations</div>
          <h1 className="truncate text-[20px] font-semibold tracking-tight text-foreground">Sales Comparison</h1>
          <div className="text-[12px] text-muted-foreground">How sales are performing against a reference period, where the difference comes from, and what to look at first.</div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] font-medium">
          <span data-testid="asof" className={cn(chip, "bg-secondary text-secondary-foreground")}><span className="eyebrow !text-[10px]">As of</span> {fmtDay(SAMPLE_AS_OF)}</span>
          <span data-testid="data-state" className={cn(chip, AMBER)}><span className="h-1.5 w-1.5 rounded-full bg-current" /> Sample data · not live</span>
          <span className="text-muted-foreground">Source: invented sample</span>
          <label className="flex items-center gap-1.5 text-muted-foreground">
            <span>Simulate state</span>
            <select data-testid="sample-state" aria-label="Simulate sample state" value={viewState} onChange={(e) => setViewState(e.target.value as ViewState)} className="h-6 cursor-pointer rounded border bg-card px-1 text-[11px] font-semibold text-foreground">
              {VIEW_STATES.map((s) => (<option key={s.id} value={s.id}>{s.label}</option>))}
            </select>
          </label>
        </div>
      </div>

      {/* controls */}
      <div className="space-y-2 border-b bg-background px-5 py-3" data-testid="controls">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <div role="group" aria-label="Comparison basis" className="flex items-center gap-1">
            <span className="eyebrow mr-1">Compare</span>
            {MODES.map((m) => (
              <button key={m.id} data-testid={`mode-${m.id}`} aria-pressed={mode === m.id} title={m.hint} onClick={() => setMode(m.id)} className={cn("press rounded border px-2.5 py-1 text-[12px] font-semibold", mode === m.id ? "border-primary/40 bg-[oklch(0.95_0.025_265)] text-primary" : "bg-card text-muted-foreground hover:bg-muted")}>
                {m.label}
              </button>
            ))}
          </div>
          <div role="group" aria-label="Store cohort" className="flex items-center gap-1">
            <span className="eyebrow mr-1">Stores</span>
            {COHORTS.map((c) => (
              <button key={c.id} data-testid={`cohort-${c.id}`} aria-pressed={cohort === c.id} onClick={() => setCohort(c.id)} className={cn("press rounded border px-2.5 py-1 text-[12px] font-semibold", cohort === c.id ? "border-primary/40 bg-[oklch(0.95_0.025_265)] text-primary" : "bg-card text-muted-foreground hover:bg-muted")}>
                {c.label}
              </button>
            ))}
          </div>
        </div>
        <div className="text-[11px] text-muted-foreground" data-testid="cohort-caption">
          <b>Illustrative cohort rule (sample only):</b> Comparable = opened before the reference period and has data on every day of both periods. New = opened after it started. The production rule is not yet decided.
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px]">
          <label className="flex items-center gap-1.5"><span className="eyebrow">Current from</span><input data-testid="cur-start" type="date" value={start} max={SAMPLE_AS_OF} onChange={(e) => setStart(e.target.value)} className="h-7 rounded border bg-card px-1.5 text-[12px]" /></label>
          <label className="flex items-center gap-1.5"><span className="eyebrow">to</span><input data-testid="cur-end" type="date" value={end} max={SAMPLE_AS_OF} onChange={(e) => setEnd(e.target.value)} className="h-7 rounded border bg-card px-1.5 text-[12px]" /></label>
          {mode === "custom" && (
            <>
              <label className="flex items-center gap-1.5"><span className="eyebrow">Reference from</span><input data-testid="ref-start" type="date" value={refStart} onChange={(e) => setRefStart(e.target.value)} className="h-7 rounded border bg-card px-1.5 text-[12px]" /></label>
              <label className="flex items-center gap-1.5"><span className="eyebrow">to</span><input data-testid="ref-end" type="date" value={refEnd} onChange={(e) => setRefEnd(e.target.value)} className="h-7 rounded border bg-card px-1.5 text-[12px]" /></label>
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]" data-testid="context">
          {plan.valid ? (
            <>
              <span><b>Current</b> <span className="num">{fmtRange(plan.curDates)}</span> · {curDays} day{curDays === 1 ? "" : "s"}</span>
              <span data-testid="ref-dates"><b>Reference</b> <span className="num">{fmtRange(plan.refDates)}</span> · {refDays} day{refDays === 1 ? "" : "s"} · {MODES.find((m) => m.id === mode)?.label.toLowerCase()}</span>
              <span><b>Stores</b> <span className="num">{included.length}</span> in view{excluded.length ? ` · ${excluded.length} outside this cohort` : ""}</span>
            </>
          ) : (
            <span data-testid="plan-problem" className="font-medium tone-bad">{plan.problem}</span>
          )}
        </div>
        {plan.valid && (
          <div className="rounded border bg-card px-2 py-1.5 text-[12px]" data-testid="mapping">
            <div data-testid="mapping-rule"><b>Rule:</b> {mappingRule(mode)}</div>
            <div className="mt-0.5 text-muted-foreground" data-testid="coverage">
              Coverage in this view: current <span className="num font-semibold">{coverage.curPresent.toLocaleString("en-IN")}</span> of <span className="num">{coverage.curExpected.toLocaleString("en-IN")}</span> store-days have data; reference <span className="num font-semibold">{coverage.refPresent.toLocaleString("en-IN")}</span> of <span className="num">{coverage.refExpected.toLocaleString("en-IN")}</span>. Missing store-days are left out, not counted as zero.
            </div>
            <details className="mt-1" data-testid="mapping-details">
              <summary className="cursor-pointer text-[12px] font-semibold text-primary">Show mapped reference dates</summary>
              <table className="mt-1 w-full max-w-[520px] text-[12px]">
                <thead><tr className="text-left text-muted-foreground"><th className="py-0.5 font-medium">Current date</th><th className="py-0.5 font-medium">Reference date</th></tr></thead>
                <tbody className="num">
                  {Array.from({ length: Math.max(curDays, refDays) }, (_, i) => (
                    <tr key={i} data-testid={`map-${i + 1}`}>
                      <td>{plan.curDates[i] ? `${fmtDay(plan.curDates[i])} ${weekday(plan.curDates[i])}` : DASH}</td>
                      <td>{plan.refDates[i] ? `${fmtDay(plan.refDates[i])} ${weekday(plan.refDates[i])}` : DASH}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </div>
        )}
        {plan.notes.map((n) => (
          <div key={n} data-testid="plan-note" className="rounded border border-[oklch(0.85_0.08_85)] bg-[oklch(0.985_0.03_90)] px-2 py-1 text-[12px] text-[oklch(0.42_0.09_70)]">{n}</div>
        ))}
        {beyondAsOf && <div className="text-[12px] font-medium tone-bad">Days after the as-of date are not available and are not treated as zero.</div>}
        {cohort === "all" && plan.valid && <div data-testid="not-like-for-like" className="text-[12px] text-muted-foreground">All stores includes new stores and stores with data gaps, so the growth shown is not like-for-like. Use Comparable stores for growth.</div>}
        {plan.valid && viewState === "normal" && included.length === 0 && (
          <div data-testid="no-eligible" className="rounded border border-[oklch(0.85_0.08_85)] bg-[oklch(0.985_0.03_90)] px-2 py-1 text-[12px] text-[oklch(0.42_0.09_70)]">
            No stores are in this cohort for the selected periods under the illustrative rule, so no totals are shown. Try All stores to see what data exists.
          </div>
        )}
        {noReference && <div data-testid="no-reference" className="rounded border border-[oklch(0.85_0.08_85)] bg-[oklch(0.985_0.03_90)] px-2 py-1 text-[12px] text-[oklch(0.42_0.09_70)]">There is no data in the reference period for these stores, so growth cannot be calculated. It is shown as a dash, not as 0% or infinity.</div>}
      </div>

      {viewState === "loading" && <Skeleton />}
      {viewState === "empty" && (
        <div data-testid="empty" className="m-4 rounded-lg border border-dashed bg-muted/40 p-8 text-center text-[13px] text-muted-foreground">
          No sales data was returned for this selection. Nothing is shown rather than a row of zeros.
        </div>
      )}

      {plan.valid && viewState === "normal" && (
        <div className="space-y-4 p-4">
          {/* KPI strip */}
          <section aria-label="Headline measures" data-testid="kpi-strip" className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
            <Kpi
              id="sales"
              label="Sales (incl. GST)"
              value={fmtInr(totals.cur)}
              reference={fmtInr(totals.ref)}
              delta={totals.delta}
              growth={totals.growth}
              provisional
              notes={
                showPerStoreDay
                  ? [
                      `Per store-day with data: ${fmtInr(totals.curPerStoreDay)} vs ${fmtInr(totals.refPerStoreDay)}.`,
                      `Coverage: current ${coverage.curPresent.toLocaleString("en-IN")} of ${coverage.curExpected.toLocaleString("en-IN")}, reference ${coverage.refPresent.toLocaleString("en-IN")} of ${coverage.refExpected.toLocaleString("en-IN")} store-days.`,
                      "This average moves when coverage changes. It is not comparable-store growth.",
                    ]
                  : undefined
              }
            />
            <Kpi id="units" label="Units" value={fmtNum(totals.curUnits)} reference={fmtNum(totals.refUnits)} delta={totals.curUnits - totals.refUnits} growth={totals.refUnits ? (totals.curUnits - totals.refUnits) / totals.refUnits : null} />
            <Kpi id="asp" label="ASP" value={fmtInr(totals.curAsp)} reference={fmtInr(totals.refAsp)} delta={totals.curAsp != null && totals.refAsp != null ? totals.curAsp - totals.refAsp : null} growth={totals.curAsp != null && totals.refAsp ? (totals.curAsp - totals.refAsp) / totals.refAsp : null} notes={["Sales ÷ Units"]} />
            <KpiUnavailable id="bills" label="Bills" reason="No certified bill count: return bills are counted as bills and the bill identifier is not verified." />
            <KpiUnavailable id="abv" label="ABV" reason="Needs the bill count." />
          </section>

          {/* trend + where the difference comes from */}
          <section className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))" }}>
            <div className="rounded-lg border bg-card p-3 shadow-sm" data-testid="trend-card">
              <div className="mb-1 flex items-baseline justify-between"><h2 className="text-[14px] font-semibold">Daily sales: current vs reference</h2><span className="text-[11px] text-muted-foreground">Sample data</span></div>
              <div className="h-[220px]">
                {trend.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={trend} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="index" tick={{ fontSize: 11 }} label={{ value: "Day of period", position: "insideBottom", offset: -2, fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => axisInr(v as number)} width={56} />
                      <Tooltip content={<TrendTooltip />} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Line type="monotone" dataKey="cur" name="Current" stroke="var(--chart-1)" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
                      <Line type="monotone" dataKey="ref" name="Reference" stroke="var(--chart-5)" strokeWidth={2} strokeDasharray="5 3" dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-[12px] text-muted-foreground">No data for this selection.</div>
                )}
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">A day with no data is a gap in the line, not a zero.</div>
            </div>

            <div className="space-y-3">
              <div className="rounded-lg border bg-card p-3 shadow-sm" data-testid="difference-card">
                <h2 className="text-[14px] font-semibold">Where the difference comes from</h2>
                <div className="num mt-1 text-[18px] font-semibold" data-testid="difference-total">{fmtInr(totals.delta, { signed: true })} <span className="text-[13px] font-medium text-muted-foreground">({fmtGrowth(totals.growth)})</span></div>
                <div className="mt-1 text-[12px] text-muted-foreground" data-testid="reconcile">
                  {ok ? `Store differences add back to the total (${included.length} stores).` : "The store differences do not add back to the total: figures withheld."}
                </div>
                <ul className="mt-2 space-y-1 text-[12px]" data-testid="top-movers">
                  {decliners.map((a) => (<li key={a.store.code} className="flex justify-between gap-2"><span>{a.store.name}</span><span className="num font-semibold tone-bad">{fmtInr(a.delta, { signed: true })}</span></li>))}
                  {gainers.map((a) => (<li key={a.store.code} className="flex justify-between gap-2"><span>{a.store.name}</span><span className="num font-semibold tone-good">{fmtInr(a.delta, { signed: true })}</span></li>))}
                  {!decliners.length && !gainers.length && <li className="text-muted-foreground">No store movement in this view.</li>}
                </ul>
              </div>
              <Unavailable id="bridge" title="Bills → ABV bridge (real data)" reason="shows how much of the difference is fewer or more bills versus a different average bill. Needs a certified bill count. See the separate worked example below." />
            </div>
          </section>

          {/* contribution table */}
          <section className="rounded-lg border bg-card shadow-sm" data-testid="contribution">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
              <h2 className="text-[14px] font-semibold">Store contribution</h2>
              <label className="relative">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
                <input data-testid="store-search" aria-label="Search stores" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search store or region" className="h-7 w-56 rounded border bg-background pl-7 pr-2 text-[12px]" />
              </label>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-[13px]">
                <thead className="bg-[oklch(0.3_0.1_265)] text-white">
                  <tr>
                    {th("Store", "name", false)}
                    <th scope="col" className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide">Region</th>
                    <th scope="col" className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide">Cohort (illustrative)</th>
                    {th("Current", "cur")}
                    {th("Reference", "ref")}
                    {th("Difference", "delta")}
                    {th("Growth", "growth")}
                  </tr>
                </thead>
                <tbody>
                  {view.map((a, i) => (
                    <tr key={a.store.code} data-testid={`row-${a.store.code}`} className={cn("border-t hover:bg-[oklch(0.955_0.03_265)]/60", i % 2 ? "bg-muted/40" : "")}>
                      <td className="px-3 py-1.5 font-medium">
                        <button data-testid={`open-${a.store.code}`} onClick={() => setSelected(a.store.code)} className="press rounded text-left text-primary underline decoration-dotted underline-offset-2 hover:decoration-solid">{a.store.name}</button>
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{a.store.region}</td>
                      <td className="px-3 py-1.5">
                        <span title={`Illustrative rule: ${a.reason}`} className={cn(chip, a.status === "comparable" ? "bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]" : a.status === "new" ? "bg-[oklch(0.95_0.025_265)] text-primary" : AMBER)}>{a.status === "comparable" ? "Comparable" : a.status === "new" ? "New" : "Data gap"}</span>
                      </td>
                      <td className="num px-3 py-1.5 text-right">{fmtInr(a.cur)}</td>
                      <td className="num px-3 py-1.5 text-right">{fmtInr(a.ref)}</td>
                      <td className={cn("num px-3 py-1.5 text-right font-semibold", a.delta < 0 ? "tone-bad" : a.delta > 0 ? "tone-good" : "tone-neutral")}>{fmtInr(a.delta, { signed: true })}</td>
                      <td className={cn("num px-3 py-1.5 text-right", a.growth == null ? "tone-neutral" : a.growth < 0 ? "tone-bad" : "tone-good")}>{fmtGrowth(a.growth)}</td>
                    </tr>
                  ))}
                  {!view.length && (<tr><td colSpan={7} className="px-3 py-6 text-center text-[12px] text-muted-foreground">No stores match.</td></tr>)}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 bg-secondary/60 font-semibold">
                    <td className="px-3 py-1.5" colSpan={3}>Total ({included.length} stores)</td>
                    <td className="num px-3 py-1.5 text-right" data-testid="total-cur">{fmtInr(totals.cur)}</td>
                    <td className="num px-3 py-1.5 text-right" data-testid="total-ref">{fmtInr(totals.ref)}</td>
                    <td className="num px-3 py-1.5 text-right" data-testid="total-delta">{fmtInr(totals.delta, { signed: true })}</td>
                    <td className="num px-3 py-1.5 text-right">{fmtGrowth(totals.growth)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <div className="border-t px-3 py-1.5 text-[11px] text-muted-foreground">A dash means no data for that side. Select a store name for its day-by-day detail. Cohorts follow an illustrative rule; hover a chip for the reason.</div>
          </section>

          {/* exceptions */}
          <section className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
            <div className="rounded-lg border bg-card p-3 shadow-sm" data-testid="exceptions">
              <h2 className="text-[14px] font-semibold">Look at first</h2>
              <ol className="mt-1 space-y-1.5 text-[12px]">
                {decliners.map((a, i) => (<li key={a.store.code}><b>{i + 1}.</b> {a.store.name} is down <span className="num font-semibold tone-bad">{fmtInr(Math.abs(a.delta))}</span> ({fmtGrowth(a.growth)}).</li>))}
                {gaps.map((a) => (<li key={`g-${a.store.code}`} data-testid={`gap-${a.store.code}`}>{a.store.name}: {a.reason}.</li>))}
                {!decliners.length && !gaps.length && <li className="text-muted-foreground">Nothing flagged for this selection.</li>}
              </ol>
            </div>
            <div className="rounded-lg border bg-card p-3 shadow-sm" data-testid="outside-cohort">
              <h2 className="text-[14px] font-semibold">Outside this cohort (illustrative rule)</h2>
              <ul className="mt-1 space-y-1 text-[12px]">
                {excluded.slice(0, 8).map((a) => (<li key={a.store.code}><b>{a.store.name}</b>: {a.reason}.</li>))}
                {!excluded.length && <li className="text-muted-foreground">Every store with data is in this cohort.</li>}
              </ul>
            </div>
          </section>

          <BridgeExample />

          {/* not available */}
          <section aria-label="Not yet available" className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
            <Unavailable id="festival" title="Festival-stage comparison" reason="the source date mappings disagree; the convention is a business decision. Added later." />
            <Unavailable id="department" title="Department contribution" reason="no department history source is verified yet." />
            <Unavailable id="footfall" title="Footfall and conversion" reason="only current-month counters for 120 stores exist." />
            <Unavailable id="target" title="Target achievement" reason="targets have not been examined yet." />
          </section>

          {/* readiness */}
          <section className="rounded-lg border bg-card shadow-sm" data-testid="readiness">
            <div className="border-b px-3 py-2"><h2 className="text-[14px] font-semibold">What is real and what is not yet</h2><div className="text-[12px] text-muted-foreground">Status of each measure against the real source, from the Phase 0 data review.</div></div>
            <ul className="divide-y">
              {READINESS.map((r) => (
                <li key={r.metric} className="flex flex-col gap-1 px-3 py-1.5 text-[12px] sm:flex-row sm:items-start sm:gap-3">
                  <span className={cn(chip, "mt-0.5 w-[92px] shrink-0 justify-center", r.status === "conditional" ? AMBER : "bg-secondary text-secondary-foreground")}>{r.status === "conditional" ? "Conditional" : "Unavailable"}</span>
                  <span className="shrink-0 font-semibold sm:w-[230px]">{r.metric}</span>
                  <span className="min-w-0 text-muted-foreground">{r.note}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}

      {selectedAgg && <StoreDetail agg={selectedAgg} rows={rows} plan={plan} onClose={() => setSelected(null)} />}
    </div>
  );
}
