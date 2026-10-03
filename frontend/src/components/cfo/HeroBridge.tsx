import { useBridge } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { fmtCr } from "@/lib/format";
import { HERO_TABS, originFromBridgeItem } from "@/lib/origins";
import { cn } from "@/lib/utils";
import type { Bridge, HeroTab } from "@/types/cfo";
import { Boundary, Skeleton, StaleChip } from "./common";
import { WaterfallChart } from "./WaterfallChart";

export function Readout({ bridge }: { bridge: Bridge }) {
  const totals = bridge.items.filter((i) => i.kind === "total");
  const deltas = bridge.items.filter((i) => i.kind === "delta");
  const net = totals.length >= 2 ? totals[totals.length - 1].value - totals[0].value : 0;
  const worst = [...deltas].filter((d) => d.tone === "bad").sort((a, b) => Math.abs(b.value) - Math.abs(a.value))[0];
  const best = [...deltas].filter((d) => d.tone === "good").sort((a, b) => Math.abs(b.value) - Math.abs(a.value))[0];
  return (
    <aside className="hidden w-[232px] shrink-0 flex-col justify-between gap-4 border-l bg-[oklch(0.985_0.006_265)] px-4 py-4 2xl:flex" data-testid="hero-readout">
      <div>
        <div className="eyebrow">Net movement</div>
        <div className={cn("num-mono mt-0.5 text-[26px] font-semibold leading-tight", net < 0 ? "tone-bad" : "tone-good")}>{fmtCr(net, { signed: true })}</div>
        <div className="text-[11px] text-muted-foreground">
          {totals[0]?.label} → {totals[totals.length - 1]?.label}
        </div>
      </div>
      <div className="space-y-3">
        {worst && (
          <div>
            <div className="eyebrow">Largest adverse</div>
            <div className="text-[13px] font-semibold text-foreground">{worst.label}</div>
            <div className="num tone-bad text-[13px] font-semibold">{fmtCr(worst.value, { signed: true })}</div>
          </div>
        )}
        {best && (
          <div>
            <div className="eyebrow">Largest favourable</div>
            <div className="text-[13px] font-semibold text-foreground">{best.label}</div>
            <div className="num tone-good text-[13px] font-semibold">{fmtCr(best.value, { signed: true })}</div>
          </div>
        )}
      </div>
      <p className="text-[11px] leading-snug text-muted-foreground">Select any bar to open the investigation drawer: movement → driver → entity → ledger → voucher.</p>
    </aside>
  );
}

export function HeroBridge() {
  const { state, dispatch, openOrigin } = useCfo();
  const tab = state.heroTab;
  const q = useBridge(tab);
  const scope = `hero:${tab}`;
  const selected = state.origin?.scope === scope ? state.origin.id : null;

  return (
    <section aria-label="What changed" data-testid="hero" className="overflow-hidden rounded-md border bg-card shadow-elegant">
      <div className="flex flex-wrap items-center justify-between gap-3 bg-[oklch(0.22_0.06_255)] px-5 py-3 text-white">
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-white/60">What changed?</div>
          <h2 className="truncate text-[17px] font-semibold tracking-tight" data-testid="hero-title">
            {q.data?.data?.title ?? "Financial bridge"}
          </h2>
          <div className="text-[11.5px] text-white/60">{q.data?.data?.subtitle ?? " "}</div>
        </div>
        <div className="flex items-center gap-3">
          {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
          <div role="tablist" aria-label="Bridge" className="flex rounded bg-white/10 p-0.5">
            {HERO_TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                data-testid={`hero-tab-${t.id}`}
                aria-selected={tab === t.id}
                onClick={() => dispatch({ type: "setHeroTab", value: t.id as HeroTab })}
                className={cn("press rounded px-3 py-1 text-[12.5px] font-semibold", tab === t.id ? "bg-white text-[oklch(0.22_0.06_255)]" : "text-white/75 hover:bg-white/10")}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="flex">
        <div className="min-w-0 flex-1 px-2 pb-2 pt-3">
          <Boundary query={q} skeleton={<Skeleton className="m-3 h-[330px]" />} emptyTitle="No bridge available for this selection">
            {(bridge) => (
              <>
                <WaterfallChart
                  items={bridge.items}
                  selectedId={selected}
                  ariaLabel={bridge.title}
                  height={352}
                  onSelect={(item) => openOrigin(originFromBridgeItem(bridge, item, scope))}
                />
                <div className="px-3 pb-1 text-[10.5px] text-muted-foreground">{bridge.unitNote}</div>
              </>
            )}
          </Boundary>
        </div>
        {q.data?.data && <Readout bridge={q.data.data} />}
      </div>
    </section>
  );
}
