import { useEffect, useState } from "react";
import { ArrowLeft, BookOpenText, ChevronRight, ExternalLink, Store, Truck, UserSquare2, X } from "lucide-react";
import { useDrill } from "@/api/hooks";
import { isLiveCfo } from "@/api";
import { useCfo } from "@/context/CfoContext";
import { storeNodeByName } from "@/lib/profitNodes";
import { drawerNodes } from "@/context/cfoState";
import { fmtCr, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DrillLink, DrillNode, DrillRow, DrillView } from "@/types/cfo";
import { Boundary, SourceLines, Skeleton, StaleChip, toneClass } from "./common";

const TONE_FILL: Record<string, string> = {
  good: "bg-[oklch(0.62_0.16_155)]",
  bad: "bg-[oklch(0.58_0.2_25)]",
  warn: "bg-[oklch(0.75_0.15_75)]",
  neutral: "bg-[oklch(0.7_0.02_260)]",
};

function RowButton({ row, onOpen, showVar = true }: { row: DrillRow; onOpen: (n: DrillNode) => void; showVar?: boolean }) {
  return (
    <li>
      <button
        data-testid={`drill-row-${row.node.id}`}
        onClick={() => onOpen(row.node)}
        className={cn("press group grid w-full items-center gap-x-3 border-b px-4 py-2 text-left hover:bg-[oklch(0.97_0.012_265)]", showVar ? "grid-cols-[1fr_auto_auto_16px]" : "grid-cols-[1fr_auto_16px]")}
      >
        <span className="min-w-0">
          <span className="block truncate text-[13px] font-medium text-foreground">{row.node.label}</span>
          <span className="mt-1 flex items-center gap-2">
            <span className="h-1 w-24 overflow-hidden rounded-full bg-muted">
              <span className={cn("block h-full rounded-full", TONE_FILL[row.tone])} style={{ width: `${Math.min(100, Math.round(row.share * 100))}%` }} />
            </span>
            <span className="num text-[10.5px] text-muted-foreground">{row.unavailable ? row.unavailable : `${Math.round(row.share * 100)}%`}{row.sublabel ? ` · ${row.sublabel}` : ""}</span>
          </span>
        </span>
        {row.unavailable ? (
          <span className="num text-[13px] font-semibold text-muted-foreground" title={row.unavailable}>
            {"—"}
          </span>
        ) : (
          <span className="num text-[13px] font-semibold text-foreground">{fmtCr(row.amount)}</span>
        )}
        {showVar && <span className={cn("num w-[76px] text-right text-[12px] font-semibold", toneClass(row.tone))}>{fmtCr(row.delta, { signed: true })}</span>}
        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground group-hover:text-foreground" />
      </button>
    </li>
  );
}

function Body({ view, onOpen, onLedger, onProfile, onStore, onLink, showProfile, stale }: { view: DrillView; onOpen: (n: DrillNode) => void; onLedger: () => void; onProfile: () => void; onStore?: () => void; onLink: (l: DrillLink) => void; showProfile: boolean; stale: boolean }) {
  const [tab, setTab] = useState(0);
  const split = view.splits[Math.min(tab, view.splits.length - 1)];
  // for movement items the row amount IS the variance; don't repeat the same figure twice
  const showVar = !split || split.rows.some((r) => Math.abs(r.delta - r.amount) > 1e-6);
  const driversShowVar = view.supportingDrivers.some((r) => Math.abs(r.delta - r.amount) > 1e-6);
  const ProfileIcon = view.entityKind === "store" ? Store : view.entityKind === "vendor" ? Truck : UserSquare2;
  return (
    <div className="flex-1 overflow-y-auto" data-testid="drawer-body">
      <div className="border-b px-4 py-3">
        <div className="flex items-baseline gap-3">
          <span data-testid="drawer-amount" className={cn("num-mono text-[28px] font-semibold leading-none", view.amount !== null && view.amount < 0 ? "tone-bad" : "text-foreground")}>
            {fmtCr(view.amount)}
          </span>
          {stale && <StaleChip />}
        </div>
        {view.variance !== null && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
            <span className="eyebrow">Variance</span>
            <span data-testid="drawer-variance" className={cn("num font-semibold", toneClass(view.tone))}>
              {fmtCr(view.variance, { signed: true })}
            </span>
            <span className={cn("num rounded bg-muted px-1.5 py-0.5 text-[11px] font-semibold", toneClass(view.tone))}>{fmtPct(view.variancePct, { signed: true, digits: Math.abs(view.variancePct ?? 0) < 1 ? 2 : 1 })}</span>
            <span className="text-muted-foreground">{view.comparisonLabel}</span>
          </div>
        )}
        <p className="mt-2.5 text-[12.5px] leading-relaxed text-foreground/80" data-testid="drawer-explanation">
          {view.explanation}
        </p>
        <SourceLines stamps={view.sources} className="mt-2 px-0 pb-0" />
      </div>

      <div className="border-b px-4 py-3">
        <div className="eyebrow mb-1.5">Concentration</div>
        <div className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full">
          {view.concentration.topShares.length > 0 ? (
            view.concentration.topShares.map((s, i) => (
              <span key={i} className="h-full" style={{ width: `${Math.max(2, s * 100)}%`, background: `oklch(${0.32 + i * 0.1} 0.1 ${255 - i * 8})` }} />
            ))
          ) : (
            <span className="h-full w-full bg-muted" />
          )}
        </div>
        <div className="mt-1.5 text-[12px] font-medium text-foreground" data-testid="drawer-concentration">
          {view.concentration.headline}
        </div>
      </div>

      {!view.terminal && split && (
        <div>
          <div className="flex items-center gap-1 border-b px-4 pt-2.5" role="tablist" aria-label="Split by">
            {view.splits.map((s, i) => (
              <button
                key={s.dim}
                role="tab"
                aria-selected={tab === i}
                data-testid={`split-tab-${s.dim}`}
                onClick={() => setTab(i)}
                className={cn("press -mb-px border-b-2 px-2.5 py-1.5 text-[12px] font-semibold", tab === i ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}
              >
                By {s.dim}
              </button>
            ))}
          </div>
          <div className={cn("grid gap-x-3 px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground", showVar ? "grid-cols-[1fr_auto_auto_16px]" : "grid-cols-[1fr_auto_16px]")}>
            <span>{split.dim}</span>
            <span>Amount</span>
            {showVar && <span className="w-[76px] text-right">Variance</span>}
            <span />
          </div>
          <ul data-testid="drill-rows" className="border-t">
            {split.rows.map((r) => (
              <RowButton key={r.node.id} row={r} onOpen={onOpen} showVar={showVar} />
            ))}
            {split.other && (
              <li data-testid="drill-other" className="flex items-center justify-between border-b bg-muted/40 px-4 py-2 text-[12px] text-muted-foreground">
                <span>
                  + {split.other.count} other {split.dim.toLowerCase()}{split.other.count === 1 ? "" : "s"}
                </span>
                <span className="num font-semibold">{fmtCr(split.other.amount)}</span>
              </li>
            )}
          </ul>
        </div>
      )}

      {view.supportingDrivers.length > 0 && (
        <div className="mt-3">
          <div className="eyebrow px-4 pb-1">Supporting drivers</div>
          <ul className="border-t" data-testid="supporting-drivers">
            {view.supportingDrivers.map((r) => (
              <RowButton key={r.node.id} row={r} onOpen={onOpen} showVar={driversShowVar} />
            ))}
          </ul>
        </div>
      )}

      {!view.terminal && view.sources && view.facts.length > 0 && (
        <dl data-testid="drawer-facts" className="grid grid-cols-2 gap-x-4 gap-y-2 border-t px-4 py-3 text-[12.5px]">
          {view.facts.map((f) => (
            <div key={f.label} className="min-w-0">
              <dt className="text-[11px] text-muted-foreground">{f.label}</dt>
              <dd className="break-words font-medium text-foreground">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {view.links && view.links.length > 0 && (
        <div data-testid="drawer-links" className="flex flex-col gap-2 border-t px-4 py-3">
          {view.links.map((l) => (
            <button key={l.label} data-testid="open-live-page" onClick={() => onLink(l)} className="press flex items-center justify-between rounded bg-primary px-3 py-2 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90">
              <span className="flex items-center gap-2"><ExternalLink className="h-4 w-4" /> {l.label}</span>
              <ChevronRight className="h-4 w-4" />
            </button>
          ))}
        </div>
      )}

      {view.terminal && (
        <div className="px-4 py-3" data-testid="drawer-terminal">
          <div className="eyebrow mb-2">Entity</div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12.5px]">
            {view.facts.map((f) => (
              <div key={f.label}>
                <dt className="text-[11px] text-muted-foreground">{f.label}</dt>
                <dd className="font-medium text-foreground">{f.value}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-4 flex flex-col gap-2">
            {!view.links && (
            <button data-testid="open-ledger" onClick={onLedger} className="press flex items-center justify-between rounded bg-primary px-3 py-2 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90">
              <span className="flex items-center gap-2"><BookOpenText className="h-4 w-4" /> Open ledger</span>
              <ChevronRight className="h-4 w-4" />
            </button>
            )}
            {onStore && (
              <button data-testid="open-store-workspace" onClick={onStore} className="press flex items-center justify-between rounded border bg-card px-3 py-2 text-[13px] font-semibold text-foreground hover:bg-muted">
                <span className="flex items-center gap-2"><Store className="h-4 w-4" /> Open store profitability</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            )}
            {showProfile && !view.links && (
              <button data-testid="open-profile" onClick={onProfile} className="press flex items-center justify-between rounded border bg-card px-3 py-2 text-[13px] font-semibold text-foreground hover:bg-muted">
                <span className="flex items-center gap-2"><ProfileIcon className="h-4 w-4" /> Open {view.entityKind === "store" ? "store" : view.entityKind === "vendor" ? "vendor" : "account"} profile</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function InvestigationDrawer() {
  const { state, closeDrawer, pushNode, back, enterStore, enterCreditors, enterRoom } = useCfo();
  const origin = state.origin;
  const open = state.drawerOpen && origin !== null;
  const q = useDrill(open ? origin : null, state.nodes);
  const filters = drawerNodes(state.nodes);
  const last = filters[filters.length - 1];

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeDrawer();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, closeDrawer]);

  if (!open || !origin) return null;
  const openLink = (l: DrillLink) => (l.room === "creditors" ? enterCreditors({ age: l.age }) : enterRoom(l.room));
  const goDeep = (level: "ledger" | "profile") =>
    pushNode({ level, dim: level === "ledger" ? "Ledger" : "Profile", id: level, label: level === "ledger" ? "GL" : q.data?.data?.entityKind === "vendor" ? "Vendor profile" : q.data?.data?.entityKind === "store" ? "Store profile" : "Profile", amount: last?.amount ?? origin.amount, variance: last?.variance ?? origin.variance });

  return (
    <aside
      data-testid="investigation-drawer"
      role="complementary"
      aria-label="Investigation drawer"
      className="fixed bottom-0 right-0 top-[104px] z-30 flex w-[var(--drawer-w)] flex-col border-l bg-card shadow-elevated"
    >
      <div className="flex items-start gap-2 border-b bg-[oklch(0.985_0.006_265)] px-4 py-3">
        <button data-testid="drawer-back" onClick={back} aria-label="Back one level" className="press mt-0.5 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1">
          <div className="eyebrow" data-testid="drawer-level">
            {q.data?.data?.levelLabel ?? "Investigation"}
          </div>
          <h3 className="truncate text-[17px] font-semibold tracking-tight text-foreground" data-testid="drawer-title">
            {last?.label ?? origin.label}
          </h3>
        </div>
        <button data-testid="drawer-close" onClick={closeDrawer} aria-label="Close drawer" className="press rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      <Boundary query={q} skeleton={<div className="space-y-3 p-4"><Skeleton className="h-9 w-40" /><Skeleton className="h-16 w-full" /><Skeleton className="h-40 w-full" /></div>} emptyTitle="No breakdown for this selection">
        {(view, stale) => (
          <Body
            key={`${origin.id}-${filters.map((n) => n.id).join(">")}`}
            view={view}
            stale={stale}
            onOpen={pushNode}
            onLedger={() => goDeep("ledger")}
            onProfile={() => goDeep("profile")}
            // a store reached from the Command Center hands over to its profitability workspace; a GL account in Profitability has no separate profile
            onLink={openLink}
            onStore={!isLiveCfo && view.entityKind === "store" && origin.scope !== "profitability" && last?.dim === "Store" ? () => enterStore(storeNodeByName(last.label)) : undefined}
            showProfile={!(view.entityKind === "account" && origin.scope === "profitability")}
          />
        )}
      </Boundary>
    </aside>
  );
}
