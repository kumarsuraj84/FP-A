import { useState } from "react";
import { useExpTrend } from "@/api/expensesLiveHooks";
import { useElementSize } from "@/hooks/useElementSize";
import type { ExpMode, ExpQuery, ExpTrend as Trend } from "@/types/expensesLive";
import { Skeleton } from "../common";
import { LiveBoundary } from "../creditors/parts";
import { Panel } from "../panels";
import { cr2, monthShort } from "../mgmt/mgmtFormat";
import { isPartialMonth } from "../mgmt/mgmtMonths";

/** Colours per head: fixed order so a head keeps its colour across the two pages. */
const COLOURS = ["oklch(0.52 0.15 265)", "oklch(0.62 0.14 200)", "oklch(0.66 0.15 155)", "oklch(0.74 0.15 85)", "oklch(0.62 0.18 40)", "oklch(0.55 0.17 330)", "oklch(0.6 0.03 260)"];
const INK = "oklch(0.45 0.02 260)";
const GRID = "oklch(0.92 0.005 260)";
const LY = "oklch(0.25 0.02 260)";

export function addMonths(m: string, n: number): string {
  const t = Number(m.slice(0, 4)) * 12 + Number(m.slice(5, 7)) - 1 + n;
  return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`;
}

function Chart({ d, mode, height = 260 }: { d: Trend; mode: ExpMode; height?: number }) {
  const [ref, size] = useElementSize<HTMLDivElement>(720);
  const [hover, setHover] = useState<string | null>(null);
  const months = d.months;
  const partial = (m: string) => isPartialMonth(m, d.as_of_date);
  const W = Math.max(360, size.width);
  const M = { l: 44, r: 12, t: 14, b: 30 };
  const iw = W - M.l - M.r;
  const ih = height - M.t - M.b;
  const val = (key: string, m: string) => d.series.find((s) => s.key === key)?.values[m]?.[mode] ?? 0;
  const stacks = months.map((m) => {
    let pos = 0;
    let neg = 0;
    return d.series.map((s, i) => {
      const v = val(s.key, m);
      const from = v >= 0 ? pos : neg;
      if (v >= 0) pos += v;
      else neg += v;
      return { key: s.key, i, v, lo: Math.min(from, from + v), hi: Math.max(from, from + v) };
    });
  });
  const lyVals = months.map((m) => d.ly_total[m]);
  const max = Math.max(0.01, ...stacks.map((st) => Math.max(0, ...st.map((b) => b.hi))), ...lyVals.map((v) => v ?? 0));
  const min = Math.min(0, ...stacks.map((st) => Math.min(0, ...st.map((b) => b.lo))));
  const y = (v: number) => M.t + ih - ((v - min) / (max - min || 1)) * ih;
  const step = iw / Math.max(1, months.length);
  const bw = Math.min(46, step * 0.64);
  const x = (i: number) => M.l + step * (i + 0.5);
  const ticks = [0, 0.5, 1].map((f) => min + (max - min) * f);
  const ly = months.map((m, i) => (d.ly_total[m] === null || d.ly_total[m] === undefined ? null : { x: x(i), y: y(d.ly_total[m] as number), m, v: d.ly_total[m] as number }));
  const lyPts = ly.filter((p): p is NonNullable<typeof p> => p !== null);
  return (
    <div ref={ref} className="w-full" data-testid="exp-trend-chart">
      <svg role="img" aria-label={`${d.scope_label} by month and head, INR Cr`} width={W} height={height} className="block">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke={GRID} />
            <text x={M.l - 6} y={y(t) + 4} textAnchor="end" fontSize={10.5} fill={INK} className="num-mono">{t.toFixed(1)}</text>
          </g>
        ))}
        <defs>
          <pattern id="exp-partial-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="white" fillOpacity="0.55" />
            <line x1="0" y1="0" x2="0" y2="6" stroke={INK} strokeWidth="2" />
          </pattern>
        </defs>
        {months.map((m, i) => (
          <g key={m} data-testid={`trend-${m}`} data-partial={partial(m)} data-exact={String(d.total[m]?.[mode] ?? "")}>
            {stacks[i].map((b) => (
              <rect key={b.key} x={x(i) - bw / 2} y={y(b.hi)} width={bw} height={Math.max(0, y(b.lo) - y(b.hi))} fill={COLOURS[b.i % COLOURS.length]} opacity={hover && hover !== b.key ? 0.4 : 1} onMouseEnter={() => setHover(b.key)} onMouseLeave={() => setHover(null)}>
                <title>{`${monthShort(m)} · ${d.series[b.i].label}: ${cr2(b.v)} Cr`}</title>
              </rect>
            ))}
            {partial(m) && <rect data-testid={`trend-partial-${m}`} x={x(i) - bw / 2} y={y(Math.max(0, ...stacks[i].map((b) => b.hi)))} width={bw} height={Math.max(0, y(Math.min(0, ...stacks[i].map((b) => b.lo))) - y(Math.max(0, ...stacks[i].map((b) => b.hi))))} fill="url(#exp-partial-hatch)" stroke={INK} strokeDasharray="3 2" />}
            <text x={x(i)} y={height - 12} textAnchor="middle" fontSize={10.5} fill={INK}>{monthShort(m)}</text>
            {partial(m) && <text x={x(i)} y={height - 2} textAnchor="middle" fontSize={9} fill={INK}>partial</text>}
          </g>
        ))}
        {lyPts.length > 0 && (
          <g data-testid="trend-ly">
            <polyline fill="none" stroke={LY} strokeWidth={1.5} strokeDasharray="4 3" points={lyPts.map((p) => `${p.x},${p.y}`).join(" ")} />
            {lyPts.map((p) => (
              <circle key={p.m} cx={p.x} cy={p.y} r={3} fill={LY}><title>{`Same month last year (${monthShort(addMonths(p.m, -12))}): ${cr2(p.v)} Cr`}</title></circle>
            ))}
          </g>
        )}
      </svg>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 pb-3 text-[11.5px]" data-testid="trend-legend">
        {d.series.map((s, i) => (
          <span key={s.key} className="inline-flex items-center gap-1.5" onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)}>
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: COLOURS[i % COLOURS.length] }} />{s.label}
          </span>
        ))}
        {lyPts.length > 0 && <span className="inline-flex items-center gap-1.5 text-muted-foreground"><span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: LY }} />Same month last year (total)</span>}
      </div>
    </div>
  );
}

/** Monthly expense by head, up to 12 months ending at the selected month, with last year's total as a dashed line where gold has it. */
export function ExpTrendPanel({ q, mode, firstMonth }: { q: ExpQuery; mode: ExpMode; firstMonth: string }) {
  const to = q.to_month ?? "";
  const from = to ? addMonths(to, -11) : undefined;
  const t = useExpTrend({ ...q, from_month: from && from < firstMonth ? firstMonth : from, to_month: q.to_month });
  return (
    <Panel testId="exp-trend" eyebrow="Trend" title={`${q.scope === "store" ? "Store expenses" : "DC cost"} by month and head (INR Cr, ${mode})`}>
      <LiveBoundary query={t} skeleton={<Skeleton className="m-4 h-[260px]" />}>
        {(d) => (
          <>
            <Chart d={d} mode={mode} />
            <div className="border-t px-4 py-1.5 text-[11.5px] text-muted-foreground" data-testid="trend-note">{d.note}{d.months.some((m) => isPartialMonth(m, d.as_of_date)) && " Hatched bars are partial months (data stops before month end): do not compare them with whole months."}</div>
          </>
        )}
      </LiveBoundary>
    </Panel>
  );
}
