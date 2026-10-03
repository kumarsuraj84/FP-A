import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { useCreditors } from "@/api/hooks";
import { useElementSize } from "@/hooks/useElementSize";
import { fmtCr, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AgeingBucket, AgeCohort, BucketId } from "@/types/creditors";
import { Boundary, Skeleton, StaleChip } from "../common";
import { AgeingBasisNote, bucketColor, useRoomSelection } from "./parts";

const H = 170;

interface Block {
  b: AgeingBucket;
  x: number;
  w: number;
  h: number;
}

/** Widths are proportional to exposure (with a floor so the smallest bucket stays clickable). */
function layout(buckets: AgeingBucket[], W: number): Block[] {
  const min = 0.055 * W;
  const total = buckets.reduce((a, b) => a + b.exposure, 0) || 1;
  let widths = buckets.map((b) => (b.exposure / total) * W);
  const small = widths.filter((w) => w < min).length;
  const free = W - small * min;
  const bigTotal = buckets.reduce((a, b, i) => a + (widths[i] < min ? 0 : b.exposure), 0) || 1;
  widths = buckets.map((b, i) => (widths[i] < min ? min : (b.exposure / bigTotal) * free));
  const maxExp = Math.max(...buckets.map((b) => b.exposure), 1);
  let x = 0;
  return buckets.map((b, i) => {
    const blk = { b, x, w: widths[i], h: 40 + 100 * Math.pow(b.exposure / maxExp, 0.45) };
    x += widths[i];
    return blk;
  });
}

function River({ buckets, selected, onPick, hover, setHover }: { buckets: AgeingBucket[]; selected: BucketId[] | null; onPick: (id: BucketId) => void; hover: BucketId | null; setHover: (b: BucketId | null) => void }) {
  const [ref, size] = useElementSize<HTMLDivElement>(1000);
  const W = Math.max(360, size.width);
  const blocks = layout(buckets, W);
  const yc = H / 2;
  return (
    <div ref={ref} className="w-full" data-testid="ageing-river">
      <svg width={W} height={H} role="group" aria-label="Ageing river: creditor exposure by age" className="block select-none">
        {blocks.map((blk, i) => {
          const prev = blocks[i - 1];
          const next = blocks[i + 1];
          const hl = prev ? (prev.h + blk.h) / 2 : blk.h * 0.75;
          const hr = next ? (blk.h + next.h) / 2 : blk.h * 0.75;
          const peak = blk.h - (hl + hr) / 4;
          const xl = blk.x;
          const xr = blk.x + blk.w;
          const xc = blk.x + blk.w / 2;
          const d = `M ${xl} ${yc - hl / 2} Q ${xc} ${yc - peak} ${xr} ${yc - hr / 2} L ${xr} ${yc + hr / 2} Q ${xc} ${yc + peak} ${xl} ${yc + hl / 2} Z`;
          const isSel = selected === null || selected.includes(blk.b.id);
          const isHover = hover === blk.b.id;
          return (
            <g
              key={blk.b.id}
              role="button"
              tabIndex={0}
              aria-pressed={selected !== null && selected.includes(blk.b.id)}
              aria-label={`${blk.b.label}: ${fmtCr(blk.b.exposure)}, ${fmtPct(blk.b.share * 100)} of creditors, ${blk.b.vendorCount} vendors. Click to filter.`}
              data-testid={`river-${blk.b.id}`}
              className="cursor-pointer outline-none"
              onClick={() => onPick(blk.b.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onPick(blk.b.id);
                }
              }}
              onMouseEnter={() => setHover(blk.b.id)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(blk.b.id)}
              onBlur={() => setHover(null)}
              opacity={isSel ? 1 : 0.28}
              style={{ transition: "opacity .15s" }}
            >
              <path d={d} fill={bucketColor(blk.b.id)} stroke="white" strokeWidth={isHover ? 3 : 1.5} />
              {blk.w > 96 && (
                <>
                  <text x={xc} y={yc - 4} textAnchor="middle" fontSize={15} fontWeight={700} fill="white" className="num" style={{ paintOrder: "stroke", stroke: "oklch(0 0 0 / 0.18)", strokeWidth: 3 }}>
                    {fmtCr(blk.b.exposure)}
                  </text>
                  <text x={xc} y={yc + 14} textAnchor="middle" fontSize={11.5} fontWeight={600} fill="white" style={{ paintOrder: "stroke", stroke: "oklch(0 0 0 / 0.18)", strokeWidth: 3 }}>
                    {fmtPct(blk.b.share * 100)}
                  </text>
                </>
              )}
              <rect x={xl} y={0} width={blk.w} height={H} fill="transparent" />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function cohortOf(cohorts: AgeCohort[], id: string): AgeCohort | undefined {
  return cohorts.find((c) => c.id === id);
}

/** Screen B: the ageing river, the dominant visual of the page. */
export function AgeingRiver() {
  const q = useCreditors();
  const { age, select } = useRoomSelection();
  const [hover, setHover] = useState<BucketId | null>(null);
  return (
    <section aria-label="Ageing river" data-testid="river-section" className="overflow-hidden rounded-md border bg-card shadow-elegant">
      <div className="flex flex-wrap items-center justify-between gap-3 bg-[oklch(0.22_0.06_255)] px-5 py-3 text-white">
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-white/60">How old is what we owe?</div>
          <h2 className="truncate text-[17px] font-semibold tracking-tight">Ageing river · {q.data?.data ? `${fmtCr(q.data.data.totalCreditors.value)} across ${q.data.data.vendorsTotal} vendors` : "creditor exposure by age"}</h2>
          <div className="text-[11.5px] text-white/60">{q.data?.data ? `${q.data.data.scope} · segment width is proportional to exposure` : " "}</div>
        </div>
        <div className="flex items-center gap-3">
          {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
          {q.data?.data && <AgeingBasisNote basis={q.data.data.ageingBasis} />}
        </div>
      </div>
      <Boundary query={q} skeleton={<Skeleton className="m-4 h-[260px]" />} emptyTitle="No creditor ageing for this selection">
        {(o) => {
          const sel = age === "all" ? null : (cohortOf(o.cohorts, age)?.buckets ?? null);
          return (
            <div className="px-4 pb-4 pt-4">
              <River buckets={o.buckets} selected={sel} hover={hover} setHover={setHover} onPick={(id) => select(id)} />
              <div className="mt-3 grid grid-cols-6 divide-x rounded border @max-[900px]:grid-cols-3 @max-[900px]:divide-y" data-testid="river-detail">
                {o.buckets.map((b) => {
                  const active = sel?.includes(b.id) ?? false;
                  const Arrow = b.movement === 0 ? Minus : b.movement > 0 ? ArrowUpRight : ArrowDownRight;
                  const older = BUCKET_RISK.has(b.id) && b.movement > 0;
                  return (
                    <button
                      key={b.id}
                      data-testid={`bucket-${b.id}`}
                      aria-pressed={active}
                      onClick={() => select(b.id)}
                      onMouseEnter={() => setHover(b.id)}
                      onMouseLeave={() => setHover(null)}
                      className={cn("press flex min-w-0 flex-col items-start gap-0.5 px-3 py-2.5 text-left hover:bg-[oklch(0.975_0.01_265)]", active && "bg-[oklch(0.95_0.025_265)]", sel && !active && "opacity-50")}
                    >
                      <span className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground">
                        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: bucketColor(b.id) }} />
                        {b.label}
                      </span>
                      <span className="num-mono text-[16px] font-semibold">{fmtCr(b.exposure)}</span>
                      <span className="num text-[11px] text-muted-foreground">
                        {fmtPct(b.share * 100)} · {b.vendorCount} vendors
                      </span>
                      <span className={cn("num flex items-center gap-1 text-[11.5px] font-semibold", older ? "tone-bad" : "tone-neutral")}>
                        <Arrow className="h-3 w-3" />
                        {fmtCr(b.movement, { signed: true })}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="mt-2 text-[10.5px] text-muted-foreground">Click a segment or a column to filter every section below. Movement is against the period opening.</div>
            </div>
          );
        }}
      </Boundary>
    </section>
  );
}

const BUCKET_RISK = new Set<BucketId>(["b91_180", "b181_365", "b365p"]);
