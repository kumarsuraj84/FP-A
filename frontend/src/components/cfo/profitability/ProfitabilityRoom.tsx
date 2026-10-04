import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronRight, X } from "lucide-react";
import { useProfitPortfolio } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { fmtCr, fmtPct } from "@/lib/format";
import { quadrantNode, quadrantOf, storeNode } from "@/lib/profitNodes";
import { cn } from "@/lib/utils";
import { QUADRANT_META, QUADRANT_ORDER, type QuadrantId, type StoreDot } from "@/types/profitability";
import { Boundary, Skeleton, StaleChip, toneClass } from "../common";
import { Chip, Panel, StripCell, WorkspaceHeader, deltaCr } from "../panels";
import { QUADRANT_COLOR, QuadrantMap } from "./QuadrantMap";

type SortKey = "gap" | "revenue" | "growth" | "margin";

const SORTS: { id: SortKey; label: string }[] = [
  { id: "gap", label: "vs comparison" },
  { id: "revenue", label: "Revenue" },
  { id: "growth", label: "Growth" },
  { id: "margin", label: "Contribution %" },
];

/**
 * Stage 3: Profitability portfolio.
 * Hero quadrant (growth × contribution margin) → quadrant filter → store workspace → movement → GL → voucher.
 */
export function ProfitabilityRoom() {
  const q = useProfitPortfolio();
  const { state, selectFilter, enterStore } = useCfo();
  const active = quadrantOf(state.nodes[0]);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "gap", dir: 1 });
  const p = q.data?.data;

  const toggle = (id: QuadrantId) => selectFilter(active === id ? null : quadrantNode(id));
  const open = (s: StoreDot) => enterStore(storeNode(s));

  const rows = useMemo(() => {
    if (!p) return [];
    const list = p.stores.filter((s) => active === null || s.quadrant === active);
    const val = (s: StoreDot) => (sort.key === "gap" ? s.contributionVsComparison : sort.key === "revenue" ? s.revenue : sort.key === "growth" ? s.revenueGrowthPct : s.contributionMarginPct);
    return [...list].sort((a, b) => (val(a) - val(b)) * sort.dir);
  }, [p, active, sort]);

  return (
    <div data-testid="profitability-room" className="@container">
      <WorkspaceHeader
        eyebrow="Performance"
        title="Store Profitability"
        subtitle="Which stores earn their place in the network, and which need fixing. Growth against contribution margin; dot size is revenue."
        right={
          <>
            {active && (
              <button data-testid="clear-quadrant-filter" onClick={() => toggle(active)} className="press inline-flex items-center gap-1 rounded bg-[oklch(0.95_0.025_265)] px-2 py-1 text-[12px] font-semibold text-primary hover:bg-[oklch(0.92_0.04_265)]">
                Filter: {QUADRANT_META[active].label} <X className="h-3 w-3" />
              </button>
            )}
            {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
            {p && <span className="text-[11px] text-muted-foreground">{p.basisNote}</span>}
          </>
        }
      />
      <Boundary query={q} skeleton={<div className="space-y-4 p-4"><Skeleton className="h-16 w-full" /><Skeleton className="h-[430px] w-full" /></div>} emptyTitle="No stores for this selection">
        {(portfolio) => (
          <>
            <div className="grid grid-cols-6 divide-x border-b bg-card @max-[1100px]:grid-cols-3 @max-[1100px]:divide-y" data-testid="portfolio-strip">
              <StripCell testId="pf-stores" label="Stores" value={portfolio.stores.length} sub="trading in the period" />
              <StripCell testId="pf-revenue" label="Revenue" value={fmtCr(portfolio.company.revenue)} sub={`${fmtPct(portfolio.company.revenueGrowthPct, { signed: true })} year on year`} />
              <StripCell testId="pf-gm" label="Gross margin" value={fmtPct(portfolio.company.gmPct)} sub="of revenue" />
              <StripCell testId="pf-contribution" label="Store contribution" value={fmtCr(portfolio.company.contribution)} variance={deltaCr(portfolio.company.contributionVsComparison)} tone={portfolio.company.contributionVsComparison < 0 ? "bad" : "good"} sub={portfolio.comparisonLabel} />
              <StripCell testId="pf-cm" label="Contribution margin" value={fmtPct(portfolio.company.contributionMarginPct)} sub="network line on the map" />
              <StripCell testId="pf-attention" label="Need attention" value={portfolio.quadrants.filter((x) => x.id === "fix" || x.id === "turnaround").reduce((a, x) => a + x.count, 0)} sub="Fix Economics + Turnaround" />
            </div>

            <div className="space-y-4 p-4">
              <Panel
                testId="portfolio-map"
                eyebrow="Portfolio"
                title="Revenue growth vs contribution margin"
              >
                <div className="border-b px-4 py-2 text-[13px] font-semibold text-foreground" data-testid="portfolio-headline">
                  {portfolio.headline}
                </div>
                <div className="grid grid-cols-4 divide-x border-b @max-[1000px]:grid-cols-2 @max-[1000px]:divide-y" role="group" aria-label="Quadrants">
                  {QUADRANT_ORDER.map((id) => {
                    const sm = portfolio.quadrants.find((x) => x.id === id)!;
                    return (
                      <button
                        key={id}
                        data-testid={`quadrant-${id}`}
                        aria-pressed={active === id}
                        onClick={() => toggle(id)}
                        className={cn("press px-4 py-2.5 text-left hover:bg-[oklch(0.97_0.012_265)]", active === id && "bg-[oklch(0.95_0.025_265)]")}
                      >
                        <div className="flex items-center gap-1.5 text-[12.5px] font-semibold text-foreground">
                          <i className="h-2.5 w-2.5 rounded-full" style={{ background: QUADRANT_COLOR[id] }} />
                          {QUADRANT_META[id].label}
                          <span className="num ml-auto rounded bg-muted px-1.5 text-[11px]">{sm.count}</span>
                        </div>
                        <div className="num mt-0.5 text-[12px] text-muted-foreground">{fmtCr(sm.contribution)} contribution · {fmtCr(sm.revenue)} revenue</div>
                        <div className="truncate text-[11px] text-muted-foreground">{QUADRANT_META[id].action}</div>
                      </button>
                    );
                  })}
                </div>
                <div className="px-2 pb-2 pt-2">
                  <QuadrantMap stores={portfolio.stores} quadrants={portfolio.quadrants} split={portfolio.split} active={active} onSelectQuadrant={toggle} onSelectStore={open} />
                </div>
              </Panel>

              <Panel
                testId="store-table-panel"
                eyebrow={active ? QUADRANT_META[active].label : "All stores"}
                title={`${rows.length} store${rows.length === 1 ? "" : "s"}`}
                right={<span className="text-[11px] text-muted-foreground">Select a store to open its workspace</span>}
              >
                <table className="w-full text-[12.5px]" data-testid="store-table">
                  <thead>
                    <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      <th className="px-4 py-2 font-semibold">Store</th>
                      <th className="px-2 py-2 font-semibold">Region</th>
                      {SORTS.map((c) => (
                        <th key={c.id} className="px-2 py-2 text-right font-semibold">
                          <button data-testid={`sort-${c.id}`} onClick={() => setSort((s) => ({ key: c.id, dir: s.key === c.id ? (s.dir === 1 ? -1 : 1) : c.id === "gap" ? 1 : -1 }))} className="press inline-flex items-center gap-0.5 uppercase tracking-wider hover:text-foreground">
                            {c.label}
                            {sort.key === c.id && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                          </button>
                        </th>
                      ))}
                      <th className="px-2 py-2 font-semibold">Quadrant</th>
                      <th className="w-6" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((s) => (
                      <tr key={s.id} data-testid={`store-row-${s.id}`} tabIndex={0} onClick={() => open(s)} onKeyDown={(e) => e.key === "Enter" && open(s)} className="press border-b hover:bg-[oklch(0.97_0.012_265)]">
                        <td className="px-4 py-2 font-medium text-foreground">{s.name}</td>
                        <td className="px-2 py-2 text-muted-foreground">{s.region}</td>
                        <td className={cn("num px-2 py-2 text-right font-semibold", toneClass(s.contributionVsComparison < 0 ? "bad" : "good"))}>{deltaCr(s.contributionVsComparison)}</td>
                        <td className="num px-2 py-2 text-right">{fmtCr(s.revenue)}</td>
                        <td className="num px-2 py-2 text-right">{fmtPct(s.revenueGrowthPct, { signed: true })}</td>
                        <td className="num px-2 py-2 text-right">{fmtPct(s.contributionMarginPct)}</td>
                        <td className="px-2 py-2">
                          <Chip color={QUADRANT_COLOR[s.quadrant]}>{QUADRANT_META[s.quadrant].label}</Chip>
                        </td>
                        <td className="pr-3 text-muted-foreground">
                          <ChevronRight className="h-3.5 w-3.5" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            </div>
          </>
        )}
      </Boundary>
    </div>
  );
}
