import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useLiquidity, useWorkingCapital } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { fmtCr } from "@/lib/format";
import { originFromLiquidity, originFromWcRow } from "@/lib/origins";
import { cn } from "@/lib/utils";
import type { Horizon, LiquiditySummary } from "@/types/cfo";
import { Boundary, Metric, SectionTitle, Skeleton, StaleChip, toneClass } from "./common";

const HORIZONS: { id: Horizon; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "7d", label: "7 Days" },
  { id: "15d", label: "15 Days" },
  { id: "30d", label: "30 Days" },
];

function Stat({ label, children, onClick, testId, tone }: { label: string; children: React.ReactNode; onClick?: () => void; testId: string; tone?: string }) {
  const inner = (
    <>
      <span className="eyebrow">{label}</span>
      <span className={cn("num-mono whitespace-nowrap text-[17px] font-semibold leading-tight @max-[1000px]:text-[14px]", tone ?? "text-foreground")}>{children}</span>
    </>
  );
  return onClick ? (
    <button data-testid={testId} onClick={onClick} className="press flex flex-col items-start gap-0.5 rounded px-3 py-2 text-left hover:bg-[oklch(0.97_0.012_265)]">
      {inner}
    </button>
  ) : (
    <div data-testid={testId} className="flex flex-col items-start gap-0.5 px-3 py-2">
      {inner}
    </div>
  );
}

function Chart({ s, onClick }: { s: LiquiditySummary; onClick: () => void }) {
  let todayIdx = 0;
  s.series.forEach((p, i) => {
    if (p.actual) todayIdx = i;
  });
  const data = s.series.map((p, i) => ({ label: p.label, actual: p.actual ? p.cash : null, projected: !p.actual || i === todayIdx ? p.cash : null }));
  const all = s.series.map((p) => p.cash).concat(s.operatingMinimum);
  const lo = Math.floor(Math.min(...all) - 4);
  const hi = Math.ceil(Math.max(...all) + 4);
  return (
    <div className="h-[236px] w-full cursor-pointer" onClick={onClick} data-testid="liquidity-chart" title="Click to investigate projected cash">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 12, right: 16, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="cashFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="oklch(0.42 0.14 255)" stopOpacity={0.22} />
              <stop offset="100%" stopColor="oklch(0.42 0.14 255)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="oklch(0.92 0.01 260)" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10.5, fill: "oklch(0.5 0.02 260)" }} tickLine={false} axisLine={{ stroke: "oklch(0.9 0.01 260)" }} interval="preserveStartEnd" minTickGap={24} />
          <YAxis domain={[lo, hi]} ticks={Array.from({ length: 5 }, (_, i) => Math.round(lo + ((hi - lo) * i) / 4))} tick={{ fontSize: 10.5, fill: "oklch(0.5 0.02 260)" }} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v}`} />
          <Tooltip formatter={(v: number, name: string) => [fmtCr(v), name === "actual" ? "Actual cash" : "Projected cash"]} contentStyle={{ fontSize: 12, borderRadius: 6 }} />
          <ReferenceLine y={s.operatingMinimum} stroke="oklch(0.58 0.2 25)" strokeDasharray="5 4" label={{ value: `Operating minimum ₹${s.operatingMinimum} Cr`, position: "insideBottomRight", fontSize: 10.5, fill: "oklch(0.5 0.2 25)" }} />
          <ReferenceLine x={s.series[todayIdx]?.label} stroke="oklch(0.55 0.02 260)" strokeDasharray="2 3" label={{ value: "Today", position: "top", fontSize: 10.5, fill: "oklch(0.4 0.03 260)" }} />
          <Area type="monotone" dataKey="actual" stroke="oklch(0.3 0.08 255)" strokeWidth={2.4} fill="url(#cashFill)" dot={false} connectNulls isAnimationActive={false} />
          <Line type="monotone" dataKey="projected" stroke={s.tone === "bad" ? "oklch(0.58 0.2 25)" : "oklch(0.5 0.15 255)"} strokeWidth={2.4} strokeDasharray="6 4" dot={false} connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LiquidityTrajectory() {
  const { state, dispatch, openOrigin } = useCfo();
  const q = useLiquidity(state.horizon);
  return (
    <section aria-label="Liquidity trajectory" data-testid="liquidity" className="@container flex min-w-0 flex-col rounded-md border bg-card shadow-elegant">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <SectionTitle eyebrow="Cash" title="Liquidity trajectory" />
        <div className="flex items-center gap-2">
          {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
          <div role="tablist" aria-label="Horizon" className="flex rounded bg-muted p-0.5">
            {HORIZONS.map((h) => (
              <button
                key={h.id}
                role="tab"
                data-testid={`horizon-${h.id}`}
                aria-selected={state.horizon === h.id}
                onClick={() => dispatch({ type: "setHorizon", value: h.id })}
                className={cn("press whitespace-nowrap rounded px-2.5 py-1 text-[12px] font-semibold", state.horizon === h.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
              >
                {h.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <Boundary query={q} skeleton={<Skeleton className="m-4 h-[320px]" />} emptyTitle="No liquidity projection for this selection">
        {(s) => (
          <>
            <div className="grid grid-cols-5 divide-x border-b px-1 max-[1900px]:[&_.eyebrow]:text-[9.5px]" data-testid="liquidity-stats">
              <Stat testId="liq-current" label="Current cash" onClick={() => openOrigin(originFromLiquidity("current", s))}>
                <Metric m={s.currentCash} fmt={(n) => fmtCr(n)} />
              </Stat>
              <Stat testId="liq-projected" label="Projected" tone={toneClass(s.tone)} onClick={() => openOrigin(originFromLiquidity("projected", s))}>
                <Metric m={s.projectedCash} fmt={(n) => fmtCr(n)} />
              </Stat>
              <Stat testId="liq-min" label="Operating minimum">
                {fmtCr(s.operatingMinimum)}
              </Stat>
              <Stat testId="liq-inflows" label="Expected inflows" tone="tone-good" onClick={() => openOrigin(originFromLiquidity("inflows", s))}>
                <Metric m={s.expectedInflows} fmt={(n) => fmtCr(n, { signed: true })} />
              </Stat>
              <Stat testId="liq-obligations" label="Upcoming obligations" tone="tone-bad" onClick={() => openOrigin(originFromLiquidity("obligations", s))}>
                <Metric m={s.upcomingObligations} fmt={(n) => fmtCr(-n)} />
              </Stat>
            </div>
            <div className={cn("flex items-center gap-2 px-4 pt-3 text-[13px] font-semibold", toneClass(s.tone))} data-testid="liquidity-headline">
              {s.headline}
            </div>
            <div className="px-2 pb-2 pt-1">
              <Chart s={s} onClick={() => openOrigin(originFromLiquidity("projected", s))} />
            </div>
          </>
        )}
      </Boundary>
    </section>
  );
}

export function WorkingCapitalPanel() {
  const q = useWorkingCapital();
  const { state, openOrigin } = useCfo();
  return (
    <section aria-label="Cash absorbed and released" data-testid="wc-panel" className="flex min-w-0 flex-col rounded-md border bg-card shadow-elegant">
      <div className="border-b px-4 py-3">
        <SectionTitle eyebrow="Working capital" title="Cash absorbed / released" right={q.data?.status === "stale" ? <StaleChip reason={q.data.reason} /> : undefined} />
      </div>
      <Boundary query={q} skeleton={<Skeleton className="m-4 h-[300px]" />} emptyTitle="No working-capital movement for this selection">
        {(w) => {
          const max = Math.max(...w.rows.map((r) => Math.abs(r.cashImpact)), 1);
          return (
            <div className="flex flex-1 flex-col">
              <div className={cn("px-4 pt-3 text-[13px] font-semibold", w.netCashImpact < 0 ? "tone-bad" : "tone-good")} data-testid="wc-headline">
                {w.headline}
              </div>
              <ul className="mt-1 flex-1">
                {w.rows.map((r) => {
                  const pct = (Math.abs(r.cashImpact) / max) * 50;
                  const sel = state.origin?.scope === "wc" && state.origin.id === r.id;
                  return (
                    <li key={r.id}>
                      <button
                        data-testid={`wc-row-${r.id}`}
                        aria-pressed={sel}
                        onClick={() => openOrigin(originFromWcRow(r))}
                        className={cn("press grid w-full grid-cols-[132px_1fr_88px] items-center gap-3 border-b px-4 py-2.5 text-left hover:bg-[oklch(0.97_0.012_265)]", sel && "bg-[oklch(0.95_0.025_265)]")}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-[13px] font-medium text-foreground">{r.label}</span>
                          <span className="block truncate text-[10.5px] text-muted-foreground">{r.direction === "absorbed" ? "Absorbed" : "Released"} · {r.note}</span>
                        </span>
                        <span className="relative h-3.5">
                          <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
                          <span
                            className={cn("absolute inset-y-0.5 rounded-sm", r.cashImpact < 0 ? "bg-[oklch(0.58_0.2_25)]" : "bg-[oklch(0.58_0.15_155)]")}
                            style={r.cashImpact < 0 ? { right: "50%", width: `${pct}%` } : { left: "50%", width: `${pct}%` }}
                          />
                        </span>
                        <span className={cn("num text-right text-[13px] font-semibold", toneClass(r.tone))}>{fmtCr(r.cashImpact, { signed: true })}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <div className="flex items-center justify-between bg-[oklch(0.975_0.008_265)] px-4 py-3" data-testid="wc-net">
                <span className="eyebrow">Net working-capital cash impact</span>
                <span className={cn("num-mono text-[20px] font-semibold", w.netCashImpact < 0 ? "tone-bad" : "tone-good")}>{fmtCr(w.netCashImpact, { signed: true })}</span>
              </div>
            </div>
          );
        }}
      </Boundary>
    </section>
  );
}
