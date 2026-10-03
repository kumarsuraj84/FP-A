import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { useCreditors, useMigration } from "@/api/hooks";
import { flowLabel, flowNode } from "@/lib/creditorNodes";
import { fmtCr } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AgeingMigration, AgeingMovement, BucketId } from "@/types/creditors";
import { Boundary, SectionTitle, Skeleton, StaleChip } from "../common";
import { AgeingBasisNote, BUCKET_ORDER, bucketColor, useRoomSelection } from "./parts";

type Mode = "risk" | "aged" | "cleared" | "new" | `tile:${string}`;

const MODES: { id: Mode; label: string }[] = [
  { id: "risk", label: "At risk" },
  { id: "aged", label: "All ageing" },
  { id: "cleared", label: "Cleared" },
  { id: "new", label: "New & adjusted" },
];

const TYPE_STYLE: Record<AgeingMovement["movementType"], { label: string; cls: string }> = {
  aged: { label: "Aged", cls: "bg-[oklch(0.96_0.05_60)] text-[oklch(0.45_0.14_50)]" },
  settled: { label: "Settled", cls: "bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]" },
  new: { label: "New", cls: "bg-[oklch(0.95_0.03_255)] text-[oklch(0.35_0.1_255)]" },
  adjusted: { label: "Adjusted", cls: "bg-muted text-muted-foreground" },
};

/** A flow is coloured by the age it lands in; settlements and adjustments by the bucket they leave. */
function barBucket(f: AgeingMovement): BucketId {
  if (f.fromBucket === "new") return "b0_30";
  return f.toBucket === "settled" || f.toBucket === "adjusted" ? f.fromBucket : f.toBucket;
}

const idx = (id: BucketId | "new" | "settled" | "adjusted") => (BUCKET_ORDER as string[]).indexOf(id);

function pick(m: AgeingMigration, mode: Mode): AgeingMovement[] {
  if (mode.startsWith("tile:")) {
    const key = mode.slice(5) as keyof AgeingMigration["summary"];
    const ids = m.summary[key]?.flowIds ?? [];
    return m.flows.filter((f) => ids.includes(f.id));
  }
  switch (mode) {
    case "aged":
      return m.flows.filter((f) => f.movementType === "aged");
    case "cleared":
      return m.flows.filter((f) => f.movementType === "settled");
    case "new":
      return m.flows.filter((f) => f.movementType === "new" || f.movementType === "adjusted");
    default:
      // service flags crossings into the >90 day zone; older settlements are the other side of the same risk
      return m.flows.filter((f) => (f.movementType === "aged" && idx(f.toBucket) >= 3) || (f.movementType === "settled" && idx(f.fromBucket) >= 3));
  }
}

/** Screen C: ageing migration. Answers: what moved into risk? */
export function MigrationPanel() {
  const q = useMigration();
  const ov = useCreditors();
  const { state, age, selectFilter } = useRoomSelection();
  const [mode, setMode] = useState<Mode>("risk");
  const cohort = age === "all" ? null : (ov.data?.data?.cohorts.find((c) => c.id === age)?.buckets ?? null);
  const selectedFlow = state.nodes[0]?.dim === "Migration" ? state.nodes[0].id.slice("Migration:".length) : null;

  return (
    <section aria-label="Ageing migration" data-testid="migration" className="rounded-md border bg-card shadow-elegant">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b px-4 py-3">
        <SectionTitle eyebrow={`Movement · ${q.data?.data?.windowLabel ?? "selected period"}`} title="What moved into risk?" />
        <div className="flex items-center gap-2">
          {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
          {q.data?.data && <AgeingBasisNote basis={q.data.data.ageingBasis} />}
        </div>
      </div>
      <Boundary query={q} skeleton={<Skeleton className="m-4 h-[320px]" />} emptyTitle="No ageing movement for this selection">
        {(m) => {
          const s = m.summary;
          const tiles: { key: keyof AgeingMigration["summary"]; tone: string }[] = [
            { key: "enteringRisk", tone: "tone-bad" },
            { key: "gettingOlder", tone: "tone-warn" },
            { key: "cleared", tone: "tone-good" },
            { key: "newlyCreated", tone: "tone-neutral" },
          ];
          const flows = pick(m, mode);
          const max = Math.max(...flows.map((f) => Math.abs(f.movedExposure)), 1e-9);
          return (
            <div>
              <div className="grid grid-cols-4 divide-x border-b @max-[900px]:grid-cols-2 @max-[900px]:divide-y" data-testid="migration-summary">
                {tiles.map(({ key, tone }) => {
                  const it = s[key];
                  const active = mode === `tile:${key}`;
                  return (
                    <button
                      key={key}
                      data-testid={`mig-tile-${key}`}
                      aria-pressed={active}
                      onClick={() => setMode(active ? "risk" : (`tile:${key}` as Mode))}
                      className={cn("press flex flex-col items-start gap-0.5 px-4 py-3 text-left hover:bg-[oklch(0.975_0.01_265)]", active && "bg-[oklch(0.95_0.025_265)]")}
                    >
                      <span className="eyebrow">{it.label}</span>
                      <span className={cn("num-mono text-[20px] font-semibold", tone)}>{fmtCr(it.amount)}</span>
                      <span className="text-[11px] text-muted-foreground">{it.vendorCount} vendors · {it.flowIds.length} flow{it.flowIds.length === 1 ? "" : "s"}</span>
                    </button>
                  );
                })}
              </div>
              <div className="num border-b bg-[oklch(0.985_0.006_265)] px-4 py-1.5 text-[11.5px] text-muted-foreground" data-testid="migration-reconciliation">
                Opening {fmtCr(m.opening)} + new {fmtCr(s.newlyCreated.amount)} − settled {fmtCr(s.cleared.amount)}
                {Math.abs(s.adjusted.amount) >= 0.005 ? ` ${s.adjusted.amount < 0 ? "−" : "+"} adjusted ${fmtCr(Math.abs(s.adjusted.amount))}` : " (no net adjustments)"} = closing{" "}
                <span className="font-semibold text-foreground">{fmtCr(m.closing)}</span>
              </div>
              <div className="flex items-center gap-1 px-4 pt-3" role="tablist" aria-label="Flow view">
                {MODES.map((c) => (
                  <button
                    key={c.id}
                    role="tab"
                    aria-selected={mode === c.id}
                    data-testid={`mig-mode-${c.id}`}
                    onClick={() => setMode(c.id)}
                    className={cn("press rounded px-2.5 py-1 text-[12px] font-semibold", mode === c.id ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground")}
                  >
                    {c.label}
                  </button>
                ))}
                {mode.startsWith("tile:") && <span className="ml-2 text-[11.5px] text-muted-foreground">Showing: {s[mode.slice(5) as keyof AgeingMigration["summary"]].label}</span>}
              </div>
              <ul className="mt-2" data-testid="mig-flows">
                {flows.length === 0 && <li className="px-4 py-6 text-center text-[12.5px] text-muted-foreground">No flows in this view.</li>}
                {flows.map((f) => {
                  const ts = TYPE_STYLE[f.movementType];
                  const touches = cohort ? [f.fromBucket, f.toBucket].some((b) => (cohort as string[]).includes(b)) : true;
                  const sel = selectedFlow === f.id;
                  return (
                    <li key={f.id}>
                      <button
                        data-testid={`flow-${f.id}`}
                        aria-pressed={sel}
                        onClick={() => selectFilter(sel ? null : flowNode(f))}
                        className={cn("press group grid w-full grid-cols-[84px_190px_1fr_96px_92px_92px_16px] items-center gap-x-3 border-t px-4 py-2 text-left hover:bg-[oklch(0.97_0.012_265)] @max-[1000px]:grid-cols-[70px_150px_1fr_84px_16px]", sel && "bg-[oklch(0.95_0.025_265)]", !touches && "opacity-40")}
                      >
                        <span className={cn("w-fit rounded-sm px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wide", ts.cls)}>{ts.label}</span>
                        <span className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
                          {f.fromBucket !== "new" && <i className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: bucketColor(f.fromBucket) }} />}
                          <span className="truncate">{flowLabel(f)}</span>
                          {f.intoRisk && <span className="rounded-sm bg-[oklch(0.95_0.04_25)] px-1 text-[9.5px] font-bold uppercase text-[oklch(0.45_0.2_25)]">into risk</span>}
                        </span>
                        <span className="h-2 overflow-hidden rounded-full bg-muted">
                          <span className="block h-full rounded-full" style={{ width: `${Math.max(2, (Math.abs(f.movedExposure) / max) * 100)}%`, background: f.fromBucket === "new" ? "oklch(0.5 0.1 255)" : bucketColor(barBucket(f)) }} />
                        </span>
                        <span className="num text-right text-[13px] font-semibold">{fmtCr(f.movedExposure, { signed: f.movementType === "adjusted" })}</span>
                        <span className="num text-right text-[11.5px] text-muted-foreground @max-[1000px]:hidden">{f.vendorCount} vendors</span>
                        <span className="num text-right text-[11.5px] text-muted-foreground @max-[1000px]:hidden">{f.documentCount} docs</span>
                        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground group-hover:text-foreground" />
                      </button>
                    </li>
                  );
                })}
              </ul>
              <div className="border-t px-4 py-2 text-[10.5px] text-muted-foreground">Click a flow to see the vendors and documents behind it.</div>
            </div>
          );
        }}
      </Boundary>
    </section>
  );
}
