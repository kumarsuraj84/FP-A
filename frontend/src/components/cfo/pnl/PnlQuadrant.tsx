import { useState } from "react";
import { useElementSize } from "@/hooks/useElementSize";
import { fmtCr, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PnlStoreRow } from "@/types/pnlLive";

/**
 * Growth x contribution margin. x = sales growth against the same complete months last year, y = contribution % of net sales, bubble = net sales.
 * The reference lines are the VIEW'S OWN growth and contribution margin (the whole company, or the filtered stores), so a quadrant means "better or worse than the network":
 *   strong        growing faster than the network AND earning more than the network
 *   scale         growing faster but earning less (growth is being bought with margin)
 *   mature        earning more but growing slower
 *   turnaround    growing slower AND earning less
 * Stores with no comparable last-year months, or below the sales floor, are not plotted: their number is stated.
 */
export type QuadId = "strong" | "scale" | "mature" | "turnaround";
export const QUADS: { id: QuadId; label: string; hint: string; colour: string }[] = [
  { id: "strong", label: "Strong", hint: "growing faster and earning more than the network", colour: "oklch(0.58 0.15 155)" },
  { id: "scale", label: "Scale, thin margin", hint: "growing faster but earning less than the network", colour: "oklch(0.72 0.15 75)" },
  { id: "mature", label: "Mature earners", hint: "earning more but growing slower than the network", colour: "oklch(0.55 0.1 255)" },
  { id: "turnaround", label: "Turnaround", hint: "growing slower and earning less than the network", colour: "oklch(0.58 0.2 25)" },
];
export const quadOf = (growth: number, margin: number, refG: number, refM: number): QuadId => (growth >= refG ? (margin >= refM ? "strong" : "scale") : margin >= refM ? "mature" : "turnaround");

export interface Plotted {
  s: PnlStoreRow;
  g: number;
  m: number;
  rev: number;
  quad: QuadId;
}

/**
 * The reference lines: the like-for-like growth and the contribution margin of the very stores that are plotted (so a dot is compared with its peers, not with a network average
 * that includes stores too new to have a last year). Growth is last year's sales weighted: sum(LY x (1 + g)) / sum(LY) - 1, the same complete months for every store.
 */
export function reference(stores: PnlStoreRow[]): { growth: number; margin: number } {
  let ly = 0, cur = 0, rev = 0, con = 0;
  for (const s of stores) {
    if (s.growth_pct === null || s.contribution_pct === null || s.last_year_revenue === null) continue;
    const l = Number(s.last_year_revenue);
    ly += l;
    cur += l * (1 + Number(s.growth_pct) / 100);
    rev += Number(s.revenue);
    con += Number(s.contribution);
  }
  return { growth: ly ? (cur / ly - 1) * 100 : 0, margin: rev ? (con / rev) * 100 : 0 };
}

export function plot(stores: PnlStoreRow[], refG: number, refM: number): { plotted: Plotted[]; unplotted: number } {
  const out: Plotted[] = [];
  for (const s of stores) {
    if (s.growth_pct === null || s.contribution_pct === null) continue;
    const g = Number(s.growth_pct);
    const m = Number(s.contribution_pct);
    out.push({ s, g, m, rev: Number(s.revenue) / 1e7, quad: quadOf(g, m, refG, refM) });
  }
  return { plotted: out, unplotted: stores.length - out.length };
}

const INK = "oklch(0.45 0.02 260)";
const GRID = "oklch(0.92 0.005 260)";
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function GrowthMarginQuadrant({ stores, refGrowth, refMargin, onPick, picked, height = 380 }: { stores: PnlStoreRow[]; refGrowth: number; refMargin: number; onPick: (site: string) => void; picked: string | null; height?: number }) {
  const [ref, size] = useElementSize<HTMLDivElement>(640);
  const [only, setOnly] = useState<QuadId | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const { plotted, unplotted } = plot(stores, refGrowth, refMargin);
  const counts = Object.fromEntries(QUADS.map((q) => [q.id, plotted.filter((p) => p.quad === q.id).length])) as Record<QuadId, number>;
  const W = Math.max(360, size.width);
  const M = { l: 46, r: 16, t: 14, b: 40 };
  const iw = W - M.l - M.r;
  const ih = height - M.t - M.b;
  const gs = plotted.map((p) => p.g).sort((a, b) => a - b);
  const ms = plotted.map((p) => p.m).sort((a, b) => a - b);
  const q = (a: number[], f: number) => (a.length ? a[Math.min(a.length - 1, Math.floor(f * a.length))] : 0);
  // robust axes: the 3rd to 97th percentile, always containing the reference lines; dots outside are drawn on the edge and marked
  const gLo = Math.min(q(gs, 0.03), refGrowth, 0) - 5;
  const gHi = Math.max(q(gs, 0.97), refGrowth) + 5;
  const mLo = Math.min(q(ms, 0.03), refMargin, 0) - 2;
  const mHi = Math.max(q(ms, 0.97), refMargin) + 2;
  const x = (v: number) => M.l + ((clamp(v, gLo, gHi) - gLo) / (gHi - gLo || 1)) * iw;
  const y = (v: number) => M.t + ih - ((clamp(v, mLo, mHi) - mLo) / (mHi - mLo || 1)) * ih;
  const maxRev = Math.max(1, ...plotted.map((p) => p.rev));
  const r = (rev: number) => 3 + Math.sqrt(rev / maxRev) * 9;
  return (
    <div ref={ref} className="w-full" data-testid="pnl-quadrant">
      <div className="flex flex-wrap gap-2 px-4 py-2" data-testid="quadrant-chips">
        {QUADS.map((qd) => (
          <button key={qd.id} data-testid={`quad-${qd.id}`} data-count={counts[qd.id]} aria-pressed={only === qd.id} title={qd.hint} onClick={() => setOnly((p) => (p === qd.id ? null : qd.id))}
            className={cn("press inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[12px] font-medium", only === qd.id ? "bg-foreground text-background" : "bg-card hover:bg-muted")}>
            <i className="h-2.5 w-2.5 rounded-full" style={{ background: qd.colour }} />
            {qd.label} <span className="num-mono font-semibold">{counts[qd.id]}</span>
          </button>
        ))}
      </div>
      <svg role="img" aria-label="Stores by sales growth and contribution margin" width={W} height={height} className="block">
        <rect x={x(refGrowth)} y={M.t} width={M.l + iw - x(refGrowth)} height={y(refMargin) - M.t} fill="oklch(0.96 0.04 155)" opacity={0.6} />
        <rect x={M.l} y={y(refMargin)} width={x(refGrowth) - M.l} height={M.t + ih - y(refMargin)} fill="oklch(0.96 0.04 25)" opacity={0.55} />
        <line x1={x(refGrowth)} x2={x(refGrowth)} y1={M.t} y2={M.t + ih} stroke={INK} strokeDasharray="4 3" data-testid="ref-growth" data-value={refGrowth.toFixed(4)} />
        <line x1={M.l} x2={M.l + iw} y1={y(refMargin)} y2={y(refMargin)} stroke={INK} strokeDasharray="4 3" data-testid="ref-margin" data-value={refMargin.toFixed(4)} />
        {[gLo, 0, gHi].map((v) => <text key={`gx${v}`} x={x(v)} y={height - 22} textAnchor="middle" fontSize={10.5} fill={INK}>{`${v.toFixed(0)}%`}</text>)}
        {[mLo, 0, mHi].map((v) => (
          <g key={`my${v}`}><line x1={M.l} x2={M.l + iw} y1={y(v)} y2={y(v)} stroke={GRID} /><text x={M.l - 6} y={y(v) + 4} textAnchor="end" fontSize={10.5} fill={INK}>{`${v.toFixed(0)}%`}</text></g>
        ))}
        <text x={M.l + iw / 2} y={height - 6} textAnchor="middle" fontSize={11} fill={INK}>Sales growth vs last year (complete months)</text>
        <text transform={`translate(11 ${M.t + ih / 2}) rotate(-90)`} textAnchor="middle" fontSize={11} fill={INK}>Contribution % of sales</text>
        <text x={M.l + iw - 4} y={M.t + 12} textAnchor="end" fontSize={11} fontWeight={600} fill={QUADS[0].colour}>Strong</text>
        <text x={M.l + iw - 4} y={M.t + ih - 6} textAnchor="end" fontSize={11} fontWeight={600} fill={QUADS[1].colour}>Scale, thin margin</text>
        <text x={M.l + 4} y={M.t + 12} fontSize={11} fontWeight={600} fill={QUADS[2].colour}>Mature earners</text>
        <text x={M.l + 4} y={M.t + ih - 6} fontSize={11} fontWeight={600} fill={QUADS[3].colour}>Turnaround</text>
        {plotted.map((p) => {
          const dim = (only && only !== p.quad) || (hover && hover !== p.s.site_code);
          const edge = p.g < gLo || p.g > gHi || p.m < mLo || p.m > mHi;
          return (
            <circle key={p.s.site_code} data-testid={`dot-${p.s.site_code}`} data-quad={p.quad} data-edge={edge ? "1" : "0"} cx={x(p.g)} cy={y(p.m)} r={r(p.rev)} fill={QUADS.find((qd) => qd.id === p.quad)!.colour}
              fillOpacity={dim ? 0.12 : 0.62} stroke={picked === p.s.site_code ? "black" : "white"} strokeWidth={picked === p.s.site_code ? 2 : 0.8} className="cursor-pointer" onClick={() => onPick(p.s.site_code)}
              onMouseEnter={() => setHover(p.s.site_code)} onMouseLeave={() => setHover(null)}>
              <title>{`${p.s.store_name ?? `Site ${p.s.site_code}`}: growth ${fmtPct(p.g, { signed: true })}, contribution ${fmtPct(p.m)}, net sales ${fmtCr(p.rev)}${edge ? " (plotted on the edge: off the scale)" : ""}`}</title>
            </circle>
          );
        })}
      </svg>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-2 text-[11.5px] text-muted-foreground" data-testid="quadrant-note">
        <span>
          Reference lines are the like-for-like growth ({fmtPct(refGrowth, { signed: true })}) and the contribution margin ({fmtPct(refMargin)}) of the plotted stores themselves. Bubble size is net sales. {unplotted > 0 && <span data-testid="quadrant-unplotted">{unplotted} stores are not plotted: no comparable last-year months, or below the sales floor.</span>}
        </span>
      </div>
    </div>
  );
}
