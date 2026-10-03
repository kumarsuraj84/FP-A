import { CartesianGrid, ComposedChart, Legend, Line, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useForecast } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { fmtCr } from "@/lib/format";
import { originFromBridgeItem } from "@/lib/origins";
import type { ForecastTrajectory as Forecast } from "@/types/cfo";
import { Boundary, Metric, SectionTitle, Skeleton, StaleChip } from "./common";
import { WaterfallChart } from "./WaterfallChart";

function FyChart({ f }: { f: Forecast }) {
  const last = f.months[f.months.length - 1];
  return (
    <div className="h-[250px] w-full" data-testid="forecast-chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={f.months} margin={{ top: 22, right: 96, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="oklch(0.92 0.01 260)" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="month" tick={{ fontSize: 11, fill: "oklch(0.45 0.02 260)" }} tickLine={false} axisLine={{ stroke: "oklch(0.9 0.01 260)" }} />
          <YAxis tick={{ fontSize: 10.5, fill: "oklch(0.5 0.02 260)" }} tickLine={false} axisLine={false} width={42} tickFormatter={(v) => `${v}`} />
          <Tooltip formatter={(v: number, n: string) => [fmtCr(v), n]} contentStyle={{ fontSize: 12, borderRadius: 6 }} />
          <Legend verticalAlign="top" align="right" iconType="plainline" wrapperStyle={{ fontSize: 11.5, top: -4 }} />
          <Line name="Budget" type="monotone" dataKey="budget" stroke="oklch(0.65 0.02 260)" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line name="Actual" type="monotone" dataKey="actual" stroke="oklch(0.28 0.08 255)" strokeWidth={3} dot={{ r: 2.5 }} connectNulls={false} isAnimationActive={false} />
          <Line name="Latest forecast" type="monotone" dataKey="forecast" stroke="oklch(0.55 0.12 190)" strokeWidth={2.6} strokeDasharray="6 4" dot={false} connectNulls={false} isAnimationActive={false} />
          {f.budgetFy.value !== null && (
            <ReferenceDot x={last.month} y={last.budget} r={4} fill="oklch(0.65 0.02 260)" stroke="white" strokeWidth={2} label={{ value: `Budget ${fmtCr(f.budgetFy.value)}`, position: "top", fontSize: 11, fill: "oklch(0.45 0.02 260)" }} />
          )}
          {f.landing.value !== null && (
            <ReferenceDot x={last.month} y={last.forecast ?? f.landing.value} r={5} fill="oklch(0.55 0.12 190)" stroke="white" strokeWidth={2} label={{ value: fmtCr(f.landing.value), position: "right", fontSize: 11.5, fontWeight: 700, fill: "oklch(0.3 0.08 255)" }} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ForecastTrajectory() {
  const q = useForecast();
  const { state, openOrigin } = useCfo();
  return (
    <section aria-label="Forecast trajectory" data-testid="forecast" className="rounded-md border bg-card shadow-elegant">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b px-4 py-3">
        <SectionTitle eyebrow="FY 2026-27 · Apr → Mar" title="Forecast trajectory — where are we landing?" />
        <div className="flex items-center gap-4">
          {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
          {q.data?.data && (
            <div className="flex items-center gap-5 text-right">
              <div>
                <div className="eyebrow">Budget FY</div>
                <div className="num-mono text-[15px] font-semibold"><Metric m={q.data.data.budgetFy} fmt={(n) => fmtCr(n)} /></div>
              </div>
              <div>
                <div className="eyebrow">Latest forecast</div>
                <div className="num-mono text-[15px] font-semibold"><Metric m={q.data.data.landing} fmt={(n) => fmtCr(n)} /></div>
              </div>
              <div>
                <div className="eyebrow">Gap</div>
                <div className={`num-mono text-[15px] font-semibold ${(q.data.data.gap.value ?? 0) < 0 ? "tone-bad" : "tone-good"}`}><Metric m={q.data.data.gap} fmt={(n) => fmtCr(n, { signed: true })} /></div>
              </div>
            </div>
          )}
        </div>
      </div>
      <Boundary query={q} skeleton={<Skeleton className="m-4 h-[480px]" />} emptyTitle="No forecast for this selection">
        {(f) => (
          <div className="px-2 pb-3 pt-2">
            <div className="px-3 pb-1 text-[12.5px] font-semibold text-foreground" data-testid="forecast-headline">{f.headline}</div>
            <FyChart f={f} />
            <div className="mx-3 mt-1 border-t pt-3">
              <div className="px-0.5 pb-1 text-[12.5px] font-semibold text-foreground">Forecast bridge · {f.bridge.title}</div>
              <WaterfallChart
                items={f.bridge.items}
                height={280}
                ariaLabel={f.bridge.title}
                selectedId={state.origin?.scope === "forecast" ? state.origin.id : null}
                onSelect={(item) => openOrigin(originFromBridgeItem(f.bridge, item, "forecast"))}
              />
              <div className="pb-1 text-[10.5px] text-muted-foreground">{f.bridge.unitNote}</div>
            </div>
          </div>
        )}
      </Boundary>
    </section>
  );
}
