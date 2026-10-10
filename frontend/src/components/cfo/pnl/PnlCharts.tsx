import { useState } from "react";
import { useElementSize } from "@/hooks/useElementSize";
import { fmtCr } from "@/lib/format";
import { T } from "@/lib/nomenclature";
import type { PnlMoney, PnlTrendRow } from "@/types/pnlLive";

const cr = (m: string | null | undefined) => (m === null || m === undefined ? null : Number(m) / 1e7);
const NAVY = "oklch(0.3 0.08 255)";
const GOOD = "oklch(0.58 0.15 155)";
const BAD = "oklch(0.58 0.2 25)";
const INK = "oklch(0.45 0.02 260)";
const GRID = "oklch(0.92 0.005 260)";
const monthLabel = (m: string) => new Date(`${m.slice(0, 7)}-01T00:00:00Z`).toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });
export { monthLabel };

interface Step {
  id: string;
  label: string;
  value: number;
  kind: "total" | "delta";
}

/** The MIS chain on the books basis: Revenue from operations -> Material Cost -> other items -> Material Margin -> Store Expenses -> Store EBITDA -> DC cost -> HO cost -> Corporate EBITDA.
 *  Other operating income is part of Material Margin. Every bar is an exact figure from the API (shown in Cr). A store has no DC or HO bars (they are company level). */
export function PnlWaterfall({ t, height = 300, store = false }: { t: PnlMoney; height?: number; store?: boolean }) {
  const [ref, size] = useElementSize<HTMLDivElement>(560);
  const [hover, setHover] = useState<string | null>(null);
  const rev = cr(t.revenue) ?? 0;
  const ooi = cr(t.other_operating_income) ?? 0;
  const steps: Step[] = [
    { id: "revenue", label: T.revenue, value: rev, kind: "total" },
    { id: "cogs", label: T.materialCost, value: -(cr(t.cogs) ?? 0), kind: "delta" },
    { id: "cogs_books", label: "Other material cost items", value: cr(t.cogs_books) ?? 0, kind: "delta" },
    ...(ooi !== 0 ? [{ id: "ooi", label: T.otherOperatingIncome, value: ooi, kind: "delta" as const }] : []),
    { id: "gross_margin", label: store ? T.grossMargin : T.materialMargin, value: cr(t.gross_margin) ?? 0, kind: "total" },
    { id: "opex", label: T.storeExpenses, value: cr(t.opex) ?? 0, kind: "delta" },
    { id: "contribution", label: store ? T.fourWall : T.storeEbitda, value: cr(t.contribution) ?? 0, kind: "total" },
    ...(!store && t.corporate_ebitda !== undefined
      ? [
          { id: "dc_cost", label: T.dcCost, value: cr(t.dc_cost) ?? 0, kind: "delta" as const },
          { id: "ho_cost", label: T.hoCost, value: cr(t.ho_cost) ?? 0, kind: "delta" as const },
          { id: "corporate_ebitda", label: T.corporateEbitda, value: cr(t.corporate_ebitda) ?? 0, kind: "total" as const },
        ]
      : []),
  ];
  const W = Math.max(320, size.width);
  const M = { l: 14, r: 14, t: 30, b: 46 };
  const iw = W - M.l - M.r;
  const ih = height - M.t - M.b;
  const bw = Math.min(64, (iw / steps.length) * 0.62);
  let run = 0;
  const bars = steps.map((s, i) => {
    const start = s.kind === "total" ? 0 : run;
    const end = s.kind === "total" ? s.value : run + s.value;
    run = end;
    return { ...s, i, lo: Math.min(start, end), hi: Math.max(start, end) };
  });
  const max = Math.max(1, ...bars.map((b) => b.hi));
  const min = Math.min(0, ...bars.map((b) => b.lo));
  const y = (v: number) => M.t + ih - ((v - min) / (max - min || 1)) * ih;
  const x = (i: number) => M.l + (iw / steps.length) * (i + 0.5);
  return (
    <div ref={ref} className="w-full" data-testid="pnl-waterfall">
      <svg role="img" aria-label="P&L bridge from revenue from operations to Corporate EBITDA" width={W} height={height} className="block">
        <line x1={M.l} x2={W - M.r} y1={y(0)} y2={y(0)} stroke={GRID} />
        {iw / steps.length < 84 && <text x={M.l} y={12} fontSize={10.5} fill={INK}>₹ Cr</text>}
        {bars.map((b) => {
          const colour = b.kind === "total" ? NAVY : b.value < 0 ? BAD : GOOD;
          return (
            <g key={b.id} onMouseEnter={() => setHover(b.id)} onMouseLeave={() => setHover(null)} data-testid={`wf-${b.id}`} data-exact={String(b.value)}>
              <rect x={x(b.i) - bw / 2} y={y(b.hi)} width={bw} height={Math.max(2, y(b.lo) - y(b.hi))} rx={2} fill={colour} opacity={hover && hover !== b.id ? 0.55 : 1} />
              <text x={x(b.i)} y={y(b.hi) - 8} textAnchor="middle" fontSize={11.5} fontWeight={600} fill={INK} className="num-mono">
                {fmtCr(b.value, { plain: iw / steps.length < 84 })}
              </text>
              {b.id === "gross_margin" && rev !== 0 && (
                <text x={x(b.i)} y={y(b.hi) - 22} textAnchor="middle" fontSize={10.5} fill={INK}>{`${((b.value / rev) * 100).toFixed(1)}% of sales`}</text>
              )}
              {(b.id === "contribution" || b.id === "corporate_ebitda") && rev !== 0 && (
                <text x={x(b.i)} y={y(b.hi) - 22} textAnchor="middle" fontSize={10.5} fill={INK}>{`${((b.value / rev) * 100).toFixed(1)}% of sales`}</text>
              )}
              <text x={x(b.i)} y={height - 24} textAnchor="middle" fontSize={11} fill={INK}>
                {b.label.length > 14 ? b.label.split(" ").slice(0, 2).join(" ") : b.label}
              </text>
              {b.label.length > 14 && (
                <text x={x(b.i)} y={height - 11} textAnchor="middle" fontSize={11} fill={INK}>
                  {b.label.split(" ").slice(2).join(" ")}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Monthly revenue from operations (bars), Store EBITDA margin % (line), LY revenue (tick). The current month is partial (hatched); provisional months are marked. */
export function PnlTrendChart({ months, height = 300 }: { months: PnlTrendRow[]; height?: number }) {
  const [ref, size] = useElementSize<HTMLDivElement>(560);
  const [hover, setHover] = useState<number | null>(null);
  const W = Math.max(320, size.width);
  const M = { l: 44, r: 40, t: 26, b: 40 };
  const iw = W - M.l - M.r;
  const ih = height - M.t - M.b;
  const revs = months.map((m) => cr(m.revenue) ?? 0);
  const lys = months.map((m) => cr(m.last_year?.revenue) ?? 0);
  const pcts = months.map((m) => (m.contribution_pct === null ? null : Number(m.contribution_pct)));
  const top = Math.max(1, ...revs, ...lys) * 1.12;
  const pMax = Math.max(10, ...pcts.map((p) => p ?? 0)) * 1.15;
  const pMin = Math.min(0, ...pcts.map((p) => p ?? 0)) * 1.15;
  const step = iw / Math.max(1, months.length);
  const bw = Math.min(46, step * 0.58);
  const xm = (i: number) => M.l + step * (i + 0.5);
  const yr = (v: number) => M.t + ih - (v / top) * ih;
  const yp = (v: number) => M.t + ih - ((v - pMin) / (pMax - pMin || 1)) * ih;
  const open = (i: number) => months[i].partial || months[i].provisional;          // costs not fully booked yet: the margin is shown hollow and is not joined to the line
  const line = pcts.map((p, i) => (p === null || open(i) ? null : `${xm(i)},${yp(p)}`)).filter(Boolean).join(" ");
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  return (
    <div ref={ref} className="w-full" data-testid="pnl-trend">
      <svg role="img" aria-label="Monthly revenue from operations and Store EBITDA margin" width={W} height={height} className="block">
        <defs>
          <pattern id="partial" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="3" height="6" fill={NAVY} opacity={0.55} />
          </pattern>
        </defs>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={yr(v)} y2={yr(v)} stroke={GRID} />
            <text x={M.l - 6} y={yr(v) + 4} textAnchor="end" fontSize={10.5} fill={INK}>{v.toFixed(0)}</text>
          </g>
        ))}
        {months.map((m, i) => (
          <g key={m.month} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} data-testid={`tr-${m.month}`} data-exact={m.revenue} data-partial={m.partial ? "1" : "0"}>
            <rect x={xm(i) - bw / 2} y={yr(revs[i])} width={bw} height={Math.max(1, yr(0) - yr(revs[i]))} rx={2} fill={m.partial ? "url(#partial)" : NAVY} opacity={hover !== null && hover !== i ? 0.6 : 1} />
            {m.last_year && <line x1={xm(i) - bw / 2 - 2} x2={xm(i) + bw / 2 + 2} y1={yr(lys[i])} y2={yr(lys[i])} stroke="oklch(0.72 0.15 75)" strokeWidth={2.5} />}
            <text x={xm(i)} y={height - 22} textAnchor="middle" fontSize={11} fill={INK}>{monthLabel(m.month)}</text>
            {m.provisional && <text x={xm(i)} y={height - 9} textAnchor="middle" fontSize={9.5} fill="oklch(0.55 0.15 60)">provisional</text>}
            {m.partial && !m.provisional && <text x={xm(i)} y={height - 9} textAnchor="middle" fontSize={9.5} fill={INK}>partial</text>}
            <title>{`${monthLabel(m.month)}: revenue ${fmtCr(revs[i])}${m.last_year ? `, LY ${fmtCr(lys[i])}` : ""}${m.contribution_pct ? `, Store EBITDA ${Number(m.contribution_pct).toFixed(1)}%` : ""}${m.partial ? " (partial month)" : ""}`}</title>
          </g>
        ))}
        {line && <polyline points={line} fill="none" stroke={GOOD} strokeWidth={2} />}
        {pcts.map((p, i) => (p === null ? null : open(i)
          ? <circle key={months[i].month} data-testid={`mg-${months[i].month}`} data-open="1" cx={xm(i)} cy={yp(p)} r={3.6} fill="white" stroke={GOOD} strokeWidth={1.8}><title>Costs for this month are not fully booked: the margin is not comparable</title></circle>
          : <circle key={months[i].month} data-testid={`mg-${months[i].month}`} cx={xm(i)} cy={yp(p)} r={3.2} fill={p < 0 ? BAD : GOOD} />))}
        {[pMin, 0, pMax].map((v) => (
          <text key={v} x={W - M.r + 6} y={yp(v) + 4} fontSize={10.5} fill={GOOD}>{`${v.toFixed(0)}%`}</text>
        ))}
      </svg>
      <div className="flex flex-wrap items-center gap-4 px-4 pb-2 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: NAVY }} /> Revenue from operations (₹ Cr)</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-[3px] w-3.5" style={{ background: "oklch(0.72 0.15 75)" }} /> Same month LY</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-[3px] w-3.5" style={{ background: GOOD }} /> Store EBITDA % of revenue (hollow = costs not fully booked)</span>
      </div>
    </div>
  );
}
