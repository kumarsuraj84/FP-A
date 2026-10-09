import { useMemo, useState } from "react";
import { useElementSize } from "@/hooks/useElementSize";
import { fmtCr, fmtPct } from "@/lib/format";
import { QUADRANT_META, type QuadrantId, type QuadrantSummary, type StoreDot } from "@/types/profitability";

export const QUADRANT_COLOR: Record<QuadrantId, string> = {
  grow: "oklch(0.58 0.15 155)",
  fix: "oklch(0.72 0.15 75)",
  defend: "oklch(0.5 0.14 255)",
  turnaround: "oklch(0.58 0.2 25)",
};
const TINT: Record<QuadrantId, string> = {
  grow: "oklch(0.97 0.03 155)",
  fix: "oklch(0.975 0.035 85)",
  defend: "oklch(0.965 0.025 255)",
  turnaround: "oklch(0.97 0.03 25)",
};

interface Props {
  stores: StoreDot[];
  quadrants: QuadrantSummary[];
  split: { growthPct: number; marginPct: number };
  active: QuadrantId | null;
  onSelectQuadrant: (q: QuadrantId) => void;
  onSelectStore: (s: StoreDot) => void;
  height?: number;
}

const M = { l: 58, r: 20, t: 14, b: 48 };

function niceDomain(vals: number[], pad: number): [number, number] {
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  return [Math.floor(lo - pad), Math.ceil(hi + pad)];
}

/** Hero quadrant: X = Y-o-Y revenue growth, Y = 4-Wall EBITDA margin, dot = store, size = revenue. */
export function QuadrantMap({ stores, quadrants, split, active, onSelectQuadrant, onSelectStore, height = 430 }: Props) {
  const [ref, size] = useElementSize<HTMLDivElement>(900);
  const [hover, setHover] = useState<string | null>(null);
  const W = Math.max(380, size.width);
  const H = height;
  const plotW = W - M.l - M.r;
  const plotH = H - M.t - M.b;

  const geo = useMemo(() => {
    const [x0, x1] = niceDomain([...stores.map((s) => s.revenueGrowthPct), split.growthPct], 3);
    const [y0, y1] = niceDomain([...stores.map((s) => s.contributionMarginPct), split.marginPct], 1.5);
    const maxRev = Math.max(...stores.map((s) => s.revenue), 1);
    return { x0, x1, y0, y1, maxRev };
  }, [stores, split]);

  const x = (v: number) => M.l + ((v - geo.x0) / (geo.x1 - geo.x0)) * plotW;
  const y = (v: number) => M.t + (1 - (v - geo.y0) / (geo.y1 - geo.y0)) * plotH;
  const rad = (rev: number) => 5 + 15 * Math.sqrt(rev / geo.maxRev);
  const xs = x(split.growthPct);
  const ys = y(split.marginPct);
  const ticks = (a: number, b: number, n = 5) => Array.from({ length: n }, (_, i) => a + ((b - a) * i) / (n - 1));

  const areas: { id: QuadrantId; x: number; y: number; w: number; h: number; anchor: "start" | "end"; top: boolean }[] = [
    { id: "defend", x: M.l, y: M.t, w: xs - M.l, h: ys - M.t, anchor: "start", top: true },
    { id: "grow", x: xs, y: M.t, w: W - M.r - xs, h: ys - M.t, anchor: "end", top: true },
    { id: "turnaround", x: M.l, y: ys, w: xs - M.l, h: H - M.b - ys, anchor: "start", top: false },
    { id: "fix", x: xs, y: ys, w: W - M.r - xs, h: H - M.b - ys, anchor: "end", top: false },
  ];
  const summary = (id: QuadrantId) => quadrants.find((q) => q.id === id);
  const hovered = stores.find((s) => s.id === hover);

  return (
    <div ref={ref} className="relative w-full" style={{ height: H }} data-testid="quadrant-map">
      <svg width={W} height={H} role="group" aria-label="Profitability portfolio: Y-o-Y revenue growth against 4-Wall EBITDA margin, one dot per store, dot size is revenue" className="block select-none">
        {areas.map((a) => (
          <g key={a.id}>
            <rect
              data-testid={`quad-area-${a.id}`}
              x={a.x}
              y={a.y}
              width={Math.max(0, a.w)}
              height={Math.max(0, a.h)}
              fill={TINT[a.id]}
              opacity={active && active !== a.id ? 0.45 : 1}
              stroke={active === a.id ? QUADRANT_COLOR[a.id] : "none"}
              strokeWidth={active === a.id ? 2 : 0}
              className="cursor-pointer"
              onClick={() => onSelectQuadrant(a.id)}
            />
            <text
              x={a.anchor === "start" ? a.x + 12 : a.x + a.w - 12}
              y={a.top ? a.y + 20 : a.y + a.h - 24}
              textAnchor={a.anchor}
              fontSize={12.5}
              fontWeight={700}
              fill={QUADRANT_COLOR[a.id]}
              pointerEvents="none"
            >
              {QUADRANT_META[a.id].label}
            </text>
            <text x={a.anchor === "start" ? a.x + 12 : a.x + a.w - 12} y={a.top ? a.y + 35 : a.y + a.h - 9} textAnchor={a.anchor} fontSize={11} fill="oklch(0.45 0.03 265)" pointerEvents="none">
              {summary(a.id)?.count ?? 0} stores · {fmtCr(summary(a.id)?.revenue ?? 0)} revenue
            </text>
          </g>
        ))}

        {ticks(geo.x0, geo.x1).map((t, i) => (
          <text key={`x${i}`} x={x(t)} y={H - M.b + 16} textAnchor="middle" fontSize={10.5} fill="oklch(0.55 0.02 260)" className="num">
            {t.toFixed(0)}%
          </text>
        ))}
        {ticks(geo.y0, geo.y1).map((t, i) => (
          <text key={`y${i}`} x={M.l - 8} y={y(t) + 3.5} textAnchor="end" fontSize={10.5} fill="oklch(0.55 0.02 260)" className="num">
            {t.toFixed(1)}%
          </text>
        ))}
        <text x={M.l + plotW / 2} y={H - 8} textAnchor="middle" fontSize={11.5} fontWeight={600} fill="oklch(0.4 0.03 265)">
          Revenue growth, year on year →
        </text>
        <text transform={`translate(14 ${M.t + plotH / 2}) rotate(-90)`} textAnchor="middle" fontSize={11.5} fontWeight={600} fill="oklch(0.4 0.03 265)">
          4-Wall EBITDA margin →
        </text>

        <line x1={xs} x2={xs} y1={M.t} y2={H - M.b} stroke="oklch(0.55 0.04 265)" strokeDasharray="4 4" pointerEvents="none" />
        <line x1={M.l} x2={W - M.r} y1={ys} y2={ys} stroke="oklch(0.55 0.04 265)" strokeDasharray="4 4" pointerEvents="none" />
        <text x={xs + 4} y={H - M.b - 4} fontSize={10} fill="oklch(0.45 0.04 265)" pointerEvents="none">
          network {fmtPct(split.growthPct)}
        </text>
        <text x={W - M.r - 4} y={ys - 4} textAnchor="end" fontSize={10} fill="oklch(0.45 0.04 265)" pointerEvents="none">
          network {fmtPct(split.marginPct)}
        </text>

        {[...stores]
          .sort((a, b) => b.revenue - a.revenue)
          .map((s) => {
            const dim = (active !== null && s.quadrant !== active) || (hover !== null && hover !== s.id);
            const isHover = hover === s.id;
            const r = rad(s.revenue);
            return (
              <g
                key={s.id}
                role="button"
                tabIndex={0}
                data-testid={`dot-${s.id}`}
                aria-label={`${s.name}: revenue ${fmtCr(s.revenue)}, growth ${fmtPct(s.revenueGrowthPct)}, 4-Wall EBITDA margin ${fmtPct(s.contributionMarginPct)}. Open store workspace.`}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectStore(s);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelectStore(s);
                  }
                }}
                onMouseEnter={() => setHover(s.id)}
                onMouseLeave={() => setHover((h) => (h === s.id ? null : h))}
                onFocus={() => setHover(s.id)}
                onBlur={() => setHover((h) => (h === s.id ? null : h))}
                className="cursor-pointer outline-none"
                opacity={dim ? (hover !== null ? 0.38 : 0.22) : 1}
                style={{ transition: "opacity .15s" }}
              >
                <circle cx={x(s.revenueGrowthPct)} cy={y(s.contributionMarginPct)} r={r} fill={QUADRANT_COLOR[s.quadrant]} fillOpacity={isHover ? 0.95 : 0.72} stroke={isHover ? "oklch(0.2 0.05 265)" : "white"} strokeWidth={isHover ? 2 : 1.5} />
                {(active === s.quadrant || isHover) && (
                  <text x={x(s.revenueGrowthPct)} y={y(s.contributionMarginPct) - r - 5} textAnchor="middle" fontSize={11} fontWeight={600} fill="oklch(0.25 0.05 265)" pointerEvents="none" paintOrder="stroke" stroke="white" strokeWidth={3}>
                    {s.name}
                  </text>
                )}
              </g>
            );
          })}
      </svg>
      {hovered && (
        <div
          role="tooltip"
          data-testid="quadrant-tooltip"
          className="pointer-events-none absolute z-10 w-[230px] rounded-md border bg-popover px-3 py-2 text-xs shadow-elevated"
          style={{ left: Math.min(Math.max(x(hovered.revenueGrowthPct) + 14, 8), W - 232), top: Math.max(y(hovered.contributionMarginPct) - 84, 6) }}
        >
          <div className="font-semibold text-foreground">{hovered.name}</div>
          <div className="text-muted-foreground">{hovered.region} · {hovered.cluster}</div>
          <div className="num mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
            <span className="text-muted-foreground">Revenue</span>
            <span className="text-right font-semibold">{fmtCr(hovered.revenue)}</span>
            <span className="text-muted-foreground">Growth</span>
            <span className="text-right font-semibold">{fmtPct(hovered.revenueGrowthPct, { signed: true })}</span>
            <span className="text-muted-foreground">4-Wall EBITDA</span>
            <span className="text-right font-semibold">{fmtPct(hovered.contributionMarginPct)}</span>
            <span className="text-muted-foreground">Gap vs AOP</span>
            <span className={`text-right font-semibold ${hovered.contributionVsComparison < 0 ? "tone-bad" : "tone-good"}`}>{fmtCr(hovered.contributionVsComparison, { signed: true })}</span>
          </div>
          <div className="mt-1 text-[11px] font-medium text-primary">Click to open store →</div>
        </div>
      )}
    </div>
  );
}
