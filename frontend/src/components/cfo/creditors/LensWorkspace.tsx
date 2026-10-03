import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { useAbnormal, useConcentration } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { abnormalNode, vendorNode } from "@/lib/creditorNodes";
import { DASH, fmtCr, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AGE_FILTER_LABELS, LENSES, type AbnormalCategory, type BucketId, type Lens, type VendorConcentration, type VendorExposureRow } from "@/types/creditors";
import { Boundary, Skeleton, StaleChip } from "../common";
import { BUCKET_ORDER, bucketColor, useRoomSelection } from "./parts";

const NAVY = "oklch(0.32 0.08 255)";

function useOpenVendor() {
  const { pushNode } = useCfo();
  return (r: { vendorId: string; name: string; outstanding: number }) => pushNode(vendorNode(r.vendorId, r.name, r.outstanding));
}

function VendorName({ r, onOpen }: { r: VendorExposureRow; onOpen: (r: VendorExposureRow) => void }) {
  return (
    <button data-testid={`vendor-${r.vendorId}`} onClick={() => onOpen(r)} className="press group flex min-w-0 items-center gap-2 text-left">
      <span className="num w-5 shrink-0 text-right text-[11px] text-muted-foreground">{r.rank}</span>
      <span className="truncate text-[13px] font-medium text-foreground group-hover:underline">{r.name}</span>
      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" />
    </button>
  );
}

function Indicators({ c }: { c: VendorConcentration }) {
  const i = c.indicators;
  const cell = (label: string, value: string, sub?: string, testId?: string) => (
    <div className="px-4 py-2.5" data-testid={testId}>
      <div className="eyebrow">{label}</div>
      <div className="num-mono text-[17px] font-semibold">{value}</div>
      {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
  return (
    <div className="grid grid-cols-5 divide-x border-b @max-[900px]:grid-cols-3 @max-[900px]:divide-y" data-testid="concentration-indicators">
      {cell("Top 1 share", fmtPct(i.top1Share * 100), undefined, "ind-top1")}
      {cell("Top 5 share", fmtPct(i.top5Share * 100), undefined, "ind-top5")}
      {cell("Top 10 share", fmtPct(i.top10Share * 100), undefined, "ind-top10")}
      {cell("Largest single vendor", fmtCr(i.largest.outstanding), i.largest.name, "ind-largest")}
      {cell("Vendors with a balance", String(i.vendorCount), "stated factually", "ind-count")}
    </div>
  );
}

/* ───────────── CONCENTRATION: ranked bars (Screen E) ───────────── */
function ConcentrationView() {
  const { age } = useRoomSelection();
  const q = useConcentration(age);
  const open = useOpenVendor();
  const [all, setAll] = useState(false);
  return (
    <Boundary query={q} skeleton={<Skeleton className="m-4 h-[360px]" />} emptyTitle="No vendors in this selection">
      {(c) => {
        const rows = all ? c.vendors : c.vendors.slice(0, 10);
        const max = Math.max(...c.vendors.map((v) => v.cohortExposure), 1e-9);
        const whole = age === "all";
        return (
          <div>
            <Indicators c={c} />
            <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,3fr)_92px_80px_80px_70px_72px_84px] items-center gap-x-3 px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground @max-[1100px]:grid-cols-[minmax(0,1.6fr)_minmax(0,2fr)_92px_70px]">
              <span>Vendor</span>
              <span>{whole ? "Outstanding · by age" : `Exposure in ${c.filterLabel}`}</span>
              <span className="text-right">{whole ? "Outstanding" : "In selection"}</span>
              <span className="text-right @max-[1100px]:hidden">&gt;90</span>
              <span className="text-right @max-[1100px]:hidden">&gt;180</span>
              <span className="text-right @max-[1100px]:hidden">% of book</span>
              <span className="text-right @max-[1100px]:hidden">Oldest</span>
              <span className="text-right @max-[1100px]:text-right">MTD move</span>
            </div>
            <ul data-testid="concentration-list">
              {rows.map((r) => {
                const w = (r.cohortExposure / max) * 100;
                const base = whole ? Math.max(0, r.outstanding - r.over90) : r.cohortExposure;
                const mid = whole ? Math.max(0, r.over90 - r.over180) : 0;
                const old = whole ? r.over180 : 0;
                const denom = whole ? r.outstanding : r.cohortExposure;
                return (
                  <li key={r.vendorId} className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,3fr)_92px_80px_80px_70px_72px_84px] items-center gap-x-3 border-t px-4 py-1.5 hover:bg-[oklch(0.97_0.012_265)] @max-[1100px]:grid-cols-[minmax(0,1.6fr)_minmax(0,2fr)_92px_70px]">
                    <VendorName r={r} onOpen={open} />
                    <span className="flex h-3 overflow-hidden rounded-sm bg-muted/60" aria-hidden>
                      <span className="flex h-full" style={{ width: `${w}%` }}>
                        <i style={{ width: `${(base / (denom || 1)) * 100}%`, background: NAVY }} />
                        <i style={{ width: `${(mid / (denom || 1)) * 100}%`, background: bucketColor("b91_180") }} />
                        <i style={{ width: `${(old / (denom || 1)) * 100}%`, background: bucketColor("b365p") }} />
                      </span>
                    </span>
                    <span className="num text-right text-[13px] font-semibold">{fmtCr(whole ? r.outstanding : r.cohortExposure)}</span>
                    <span className="num text-right text-[12px] text-muted-foreground @max-[1100px]:hidden">{r.over90 > 0.0049 ? fmtCr(r.over90) : ""}</span>
                    <span className="num text-right text-[12px] text-muted-foreground @max-[1100px]:hidden">{r.over180 > 0.0049 ? fmtCr(r.over180) : ""}</span>
                    <span className="num text-right text-[12px] text-muted-foreground @max-[1100px]:hidden">{fmtPct(r.shareOfBook * 100)}</span>
                    <span className="num text-right text-[12px] text-muted-foreground @max-[1100px]:hidden" title={r.oldestItemDays.reason}>
                      {r.oldestItemDays.value === null ? DASH : `${r.oldestItemDays.value}d`}
                    </span>
                    <span className={cn("num text-right text-[12px] font-semibold", r.mtdMovement > 0 ? "tone-warn" : "tone-good")}>{fmtCr(r.mtdMovement, { signed: true })}</span>
                  </li>
                );
              })}
              {c.others.count > 0 && (
                <li className="flex items-center justify-between border-t bg-muted/40 px-4 py-2 text-[12px] text-muted-foreground" data-testid="concentration-others">
                  <span>+ {c.others.count} other vendor{c.others.count === 1 ? "" : "s"}</span>
                  <span className="num font-semibold">{fmtCr(whole ? c.others.outstanding : c.others.cohortExposure)}</span>
                </li>
              )}
            </ul>
            <div className="flex items-center justify-between border-t px-4 py-2 text-[11px] text-muted-foreground">
              <span className="flex items-center gap-3">
                <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm" style={{ background: NAVY }} /> up to 90 days</span>
                <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm" style={{ background: bucketColor("b91_180") }} /> 91–180</span>
                <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm" style={{ background: bucketColor("b365p") }} /> &gt;180</span>
              </span>
              {c.vendors.length > 10 && (
                <button data-testid="concentration-toggle" onClick={() => setAll((x) => !x)} className="press rounded px-2 py-0.5 font-semibold text-primary hover:bg-muted">
                  {all ? "Show top 10" : `Show all ${c.vendors.length} listed vendors`}
                </button>
              )}
            </div>
          </div>
        );
      }}
    </Boundary>
  );
}

/* ───────────── AGE: where old balances sit ───────────── */
function AgeView() {
  const { age } = useRoomSelection();
  const q = useConcentration(age);
  const open = useOpenVendor();
  return (
    <Boundary query={q} skeleton={<Skeleton className="m-4 h-[320px]" />} emptyTitle="No vendors in this selection">
      {(c) => {
        const rows = c.vendors.slice(0, 9);
        const max = Math.max(...rows.map((r) => r.outstanding), 1e-9);
        return (
          <div className="px-4 py-3" data-testid="age-lens">
            <div className="mb-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
              {BUCKET_ORDER.map((b) => (
                <span key={b} className="flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: bucketColor(b) }} />{AGE_FILTER_LABELS[b]}</span>
              ))}
              <span className="ml-auto">Top {rows.length} vendors by {age === "all" ? "outstanding" : `exposure in ${c.filterLabel}`}</span>
            </div>
            <ul className="space-y-1.5">
              {rows.map((r) => (
                <li key={r.vendorId} className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,3.2fr)_90px] items-center gap-3">
                  <VendorName r={r} onOpen={open} />
                  <span className="flex h-4 overflow-hidden rounded-sm bg-muted/50" aria-hidden>
                    <span className="flex h-full" style={{ width: `${(r.outstanding / max) * 100}%` }}>
                      {BUCKET_ORDER.map((b: BucketId) => (
                        <i key={b} title={`${AGE_FILTER_LABELS[b]}: ${fmtCr(r.byBucket[b])}`} style={{ width: `${(r.byBucket[b] / (r.outstanding || 1)) * 100}%`, background: bucketColor(b), opacity: age === "all" || r.cohortExposure > 0 ? 1 : 0.4 }} />
                      ))}
                    </span>
                  </span>
                  <span className="num text-right text-[13px] font-semibold">{fmtCr(r.outstanding)}</span>
                </li>
              ))}
            </ul>
            {c.vendors.length > rows.length && <div className="mt-2 text-[11px] text-muted-foreground">+ {c.vendors.length - rows.length} more listed vendors and {c.others.count} others. Switch to Concentration for the full ranking.</div>}
          </div>
        );
      }}
    </Boundary>
  );
}

/* ───────────── MOVEMENT: what is increasing / clearing ───────────── */
function MovementView() {
  const { age } = useRoomSelection();
  const q = useConcentration(age);
  const open = useOpenVendor();
  return (
    <Boundary query={q} skeleton={<Skeleton className="m-4 h-[320px]" />} emptyTitle="No vendors in this selection">
      {(c) => {
        const up = [...c.vendors].filter((v) => v.mtdMovement > 0).sort((a, b) => b.mtdMovement - a.mtdMovement).slice(0, 6);
        const down = [...c.vendors].filter((v) => v.mtdMovement < 0).sort((a, b) => a.mtdMovement - b.mtdMovement).slice(0, 4);
        const max = Math.max(...[...up, ...down].map((v) => Math.abs(v.mtdMovement)), 1e-9);
        const Row = ({ r }: { r: VendorExposureRow }) => (
          <li className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,2.6fr)_90px] items-center gap-3">
            <VendorName r={r} onOpen={open} />
            <span className="relative h-3.5" aria-hidden>
              <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
              <span
                className="absolute inset-y-0.5 rounded-sm"
                style={r.mtdMovement < 0 ? { right: "50%", width: `${(Math.abs(r.mtdMovement) / max) * 50}%`, background: "oklch(0.62 0.12 185)" } : { left: "50%", width: `${(r.mtdMovement / max) * 50}%`, background: "oklch(0.68 0.15 60)" }}
              />
            </span>
            <span className={cn("num text-right text-[13px] font-semibold", r.mtdMovement < 0 ? "tone-good" : "tone-warn")}>{fmtCr(r.mtdMovement, { signed: true })}</span>
          </li>
        );
        return (
          <div className="px-4 py-3" data-testid="movement-lens">
            <div className="mb-1 text-[11px] text-muted-foreground">Change in balance vs period opening{age === "all" ? "" : `, vendors with exposure in ${c.filterLabel}`}. Increasing balances are shown factually, not as a judgement.</div>
            <div className="eyebrow mt-2 mb-1">Increasing</div>
            <ul className="space-y-1.5" data-testid="movement-up">{up.map((r) => <Row key={r.vendorId} r={r} />)}</ul>
            <div className="eyebrow mt-3 mb-1">Decreasing / being cleared</div>
            <ul className="space-y-1.5" data-testid="movement-down">{down.length ? down.map((r) => <Row key={r.vendorId} r={r} />) : <li className="text-[12px] text-muted-foreground">No listed vendor decreased in this selection.</li>}</ul>
          </div>
        );
      }}
    </Boundary>
  );
}

/* ───────────── ABNORMAL: diagnostic categories only (Screen G) ───────────── */
function AbnormalView() {
  const q = useAbnormal();
  const { selectFilter, state } = useRoomSelection();
  const selected = state.nodes[0]?.dim === "Abnormal" ? state.nodes[0].id.slice("Abnormal:".length) : null;
  return (
    <Boundary query={q} skeleton={<Skeleton className="m-4 h-[360px]" />} emptyTitle="No abnormal-balance diagnostics for this selection">
      {(a) => (
        <div data-testid="abnormal-lens">
          <div className="border-b bg-[oklch(0.985_0.03_90)] px-4 py-2 text-[11.5px] text-[oklch(0.4_0.08_75)]" data-testid="abnormal-note">{a.note}</div>
          <div className="px-4 pb-1 pt-2 text-[11px] text-muted-foreground">These diagnostics are not filtered by age: they look across the whole creditor ledger.</div>
          <ul>
            {a.categories.map((c: AbnormalCategory) => {
              const sel = selected === c.id;
              return (
                <li key={c.id}>
                  <button
                    data-testid={`abnormal-${c.id}`}
                    aria-pressed={sel}
                    onClick={() => selectFilter(sel ? null : abnormalNode(c))}
                    className={cn("press group grid w-full grid-cols-[minmax(0,2.6fr)_80px_80px_120px_16px] items-center gap-x-3 border-t px-4 py-2 text-left hover:bg-[oklch(0.97_0.012_265)] @max-[900px]:grid-cols-[minmax(0,2fr)_80px_110px_16px]", sel && "bg-[oklch(0.95_0.025_265)]")}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-semibold text-foreground">{c.label}</span>
                      <span className="block truncate text-[11px] text-muted-foreground" title={c.caveat ?? c.description}>{c.description}</span>
                    </span>
                    <span className="num text-right text-[12px] text-muted-foreground" title="vendors">{c.vendorCount.value === null ? DASH : `${c.vendorCount.value} vendor${c.vendorCount.value === 1 ? "" : "s"}`}</span>
                    <span className="num text-right text-[12px] text-muted-foreground @max-[900px]:hidden" title="documents">{c.documentCount.value === null ? DASH : `${c.documentCount.value} docs`}</span>
                    <span className="num text-right text-[14px] font-semibold" title={c.amount.reason}>
                      {c.amount.value === null ? (
                        <span className="text-muted-foreground">
                          {DASH}
                          <span className="block text-[10.5px] font-normal">{c.amount.reason}</span>
                        </span>
                      ) : (
                        fmtCr(c.amount.value)
                      )}
                    </span>
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground group-hover:text-foreground" />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Boundary>
  );
}

/** Screen D: four diagnostic lenses. The selected lens is URL state (`lens=`). */
export function LensWorkspace() {
  const { state, dispatch } = useCfo();
  const { age } = useRoomSelection();
  const lens = state.lens;
  const q = useConcentration(age);
  return (
    <section aria-label="Diagnostic lenses" data-testid="lens-workspace" className="rounded-md border bg-card shadow-elegant">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b px-4 pt-3">
        <div>
          <div className="eyebrow">Diagnosis</div>
          <h2 className="text-[15px] font-semibold tracking-tight">{LENSES.find((l) => l.id === lens)?.hint}</h2>
        </div>
        <div className="flex items-center gap-2 pb-2">
          {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
          {age !== "all" && <span className="rounded bg-[oklch(0.95_0.025_265)] px-2 py-0.5 text-[11.5px] font-semibold text-primary" data-testid="lens-filter-chip">Filtered: {AGE_FILTER_LABELS[age]}</span>}
        </div>
      </div>
      <div role="tablist" aria-label="Lens" className="flex gap-1 border-b px-4 pt-2">
        {LENSES.map((l) => (
          <button
            key={l.id}
            role="tab"
            data-testid={`lens-${l.id}`}
            aria-selected={lens === l.id}
            onClick={() => dispatch({ type: "setLens", value: l.id as Lens })}
            className={cn("press -mb-px border-b-2 px-3 py-1.5 text-[12.5px] font-semibold", lens === l.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}
          >
            {l.label}
          </button>
        ))}
      </div>
      {lens === "age" && <AgeView />}
      {lens === "concentration" && <ConcentrationView />}
      {lens === "movement" && <MovementView />}
      {lens === "abnormal" && <AbnormalView />}
    </section>
  );
}
