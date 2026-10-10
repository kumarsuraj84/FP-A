import { useState } from "react";
import { useLiveDocumentAge, useLiveSummary } from "@/api/creditorsLiveHooks";
import { API_TO_BUCKET, fmtRupees, num, toCr } from "@/api/creditorsLive";
import { useElementSize } from "@/hooks/useElementSize";
import { fmtCr, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AgeFilter, BucketId } from "@/types/creditors";
import type { AgeBucketRow } from "@/types/creditorsLive";
import { Skeleton } from "../common";
import { LiveBoundary, bucketColor, useRoomSelection } from "./parts";

const H = 170;
const COHORT: Partial<Record<AgeFilter, BucketId[]>> = { gt90: ["b91_180", "b181_365", "b365p"], gt180: ["b181_365", "b365p"] };
const BUCKET_IDS = Object.values(API_TO_BUCKET) as string[];

interface RiverBucket {
  id: BucketId;
  label: string;
  credit: number;
  creditExact: string;
  share: number;
  creditItems: number;
  debit: number;
  debitItems: number;
}
interface Block {
  b: RiverBucket;
  x: number;
  w: number;
  h: number;
}

/** Widths are proportional to credit outstanding (with a floor so the smallest bucket stays clickable). */
function layout(buckets: RiverBucket[], W: number): Block[] {
  const min = 0.055 * W;
  const total = buckets.reduce((a, b) => a + b.credit, 0) || 1;
  let widths = buckets.map((b) => (b.credit / total) * W);
  const small = widths.filter((w) => w < min).length;
  const free = W - small * min;
  const bigTotal = buckets.reduce((a, b, i) => a + (widths[i] < min ? 0 : b.credit), 0) || 1;
  widths = buckets.map((b, i) => (widths[i] < min ? min : (b.credit / bigTotal) * free));
  const maxExp = Math.max(...buckets.map((b) => b.credit), 1);
  let x = 0;
  return buckets.map((b, i) => {
    const blk = { b, x, w: widths[i], h: 40 + 100 * Math.pow(b.credit / maxExp, 0.45) };
    x += widths[i];
    return blk;
  });
}

function River({ buckets, selected, onPick, hover, setHover }: { buckets: RiverBucket[]; selected: BucketId[] | null; onPick: (id: BucketId) => void; hover: BucketId | null; setHover: (b: BucketId | null) => void }) {
  const [ref, size] = useElementSize<HTMLDivElement>(1000);
  const W = Math.max(360, size.width);
  const blocks = layout(buckets, W);
  const yc = H / 2;
  return (
    <div ref={ref} className="w-full" data-testid="ageing-river">
      <svg width={W} height={H} role="group" aria-label="Document age: credit outstanding by age of document" className="block select-none">
        {blocks.map((blk, i) => {
          // a distribution, not a flow: one straight stacked bar, segment width proportional to credit
          const bh = H * 0.7;
          const xl = blk.x;
          const xr = blk.x + blk.w;
          const xc = blk.x + blk.w / 2;
          const d = `M ${xl} ${yc - bh / 2} L ${xr} ${yc - bh / 2} L ${xr} ${yc + bh / 2} L ${xl} ${yc + bh / 2} Z`;
          const isSel = selected === null || selected.includes(blk.b.id);
          const isHover = hover === blk.b.id;
          return (
            <g
              key={blk.b.id}
              role="button"
              tabIndex={0}
              aria-pressed={selected !== null && selected.includes(blk.b.id)}
              aria-label={`${blk.b.label}: credit ${fmtCr(blk.b.credit)}, ${fmtPct(blk.b.share * 100)} of credit outstanding, ${blk.b.creditItems} items. Click to filter.`}
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
                    {fmtCr(blk.b.credit)}
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

/** Which Document Age buckets a room filter covers. A Due Status filter does not narrow them: the two are separate dimensions. */
function cohortBuckets(age: AgeFilter): BucketId[] | null {
  if (age === "all") return null;
  const c = COHORT[age];
  if (c) return c;
  return BUCKET_IDS.includes(age) ? [age as BucketId] : null;
}

/** Document Age: how old the credit documents are (document date vs the as-of date). Due Status is a separate panel. */
export function AgeingRiver() {
  const q = useLiveDocumentAge();
  const sum = useLiveSummary();
  const { age, select } = useRoomSelection();
  const [hover, setHover] = useState<BucketId | null>(null);
  return (
    <section aria-label="Document age" data-testid="river-section" className="overflow-hidden rounded-md border bg-card shadow-elegant">
      <div className="flex flex-wrap items-center justify-between gap-3 bg-[oklch(0.22_0.06_255)] px-5 py-3 text-white">
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-white/60">How old are the documents we owe on?</div>
          <h2 className="truncate text-[17px] font-semibold tracking-tight">Document Age · {sum.data ? `${fmtCr(toCr(sum.data.credit_outstanding))} credit outstanding across ${sum.data.credit_vendors.toLocaleString("en-IN")} vendors` : "credit outstanding by document age"}</h2>
          <div className="text-[11.5px] text-white/60">Age = as-of date − document date · segment width is proportional to credit outstanding</div>
        </div>
      </div>
      <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[260px]" />}>
        {(rows: AgeBucketRow[]) => {
          const credit = rows.reduce((a, r) => a + num(r.credit_outstanding), 0);
          const buckets: RiverBucket[] = rows
            .filter((r) => r.bucket in API_TO_BUCKET)
            .map((r) => ({
              id: API_TO_BUCKET[r.bucket],
              label: `${r.label} days`,
              credit: toCr(r.credit_outstanding) ?? 0,
              creditExact: r.credit_outstanding,
              share: credit ? num(r.credit_outstanding) / credit : 0,
              creditItems: r.credit_items,
              debit: toCr(r.debit_balance) ?? 0,
              debitItems: r.debit_items,
            }));
          const un = rows.find((r) => r.bucket === "UNCLASSIFIED");
          const sel = cohortBuckets(age);
          return (
            <div className="px-4 pb-4 pt-4">
              <River buckets={buckets} selected={sel} hover={hover} setHover={setHover} onPick={(id) => select(id)} />
              <div className="mt-3 grid grid-cols-6 divide-x rounded border @max-[900px]:grid-cols-3 @max-[900px]:divide-y" data-testid="river-detail">
                {buckets.map((b) => {
                  const active = sel?.includes(b.id) ?? false;
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
                      <span data-exact={b.creditExact} className="num-mono text-[16px] font-semibold">{fmtCr(b.credit)}</span>
                      <span className="num text-[11px] text-muted-foreground">
                        {fmtPct(b.share * 100)} · {b.creditItems.toLocaleString("en-IN")} items
                      </span>
                      <span className="num text-[11px] text-muted-foreground">{b.debitItems > 0 ? `Dr ${fmtCr(b.debit)} · ${b.debitItems.toLocaleString("en-IN")} items` : "no debit items"}</span>
                    </button>
                  );
                })}
              </div>
              {un && (un.credit_items > 0 || un.debit_items > 0) && (
                <div data-testid="age-unclassified" className="num mt-2 rounded border border-dashed bg-[oklch(0.985_0.03_90)] px-3 py-1.5 text-[11.5px] text-[oklch(0.4_0.08_75)]">
                  Unclassified (no usable document date): credit {fmtRupees(un.credit_outstanding)} in {un.credit_items} item{un.credit_items === 1 ? "" : "s"}, debit {fmtRupees(un.debit_balance)} in {un.debit_items} item{un.debit_items === 1 ? "" : "s"}
                  {un.reasons?.length ? ` · ${un.reasons.filter((r) => r.credit_items + r.debit_items > 0).map((r) => r.reason.replaceAll("_", " ").toLowerCase()).join(", ")}` : ""}. Held outside the buckets, not guessed.
                </div>
              )}
              <div className="mt-2 text-[10.5px] text-muted-foreground">Click a segment or a column to filter the vendor sections below. Credit and debit are shown separately in every bucket; debit is never netted into credit.</div>
            </div>
          );
        }}
      </LiveBoundary>
    </section>
  );
}
