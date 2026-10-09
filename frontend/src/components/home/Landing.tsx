import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { Banknote, BarChart3, Boxes, ChevronRight, FileSpreadsheet, Handshake, LayoutDashboard, Lock, Store, Truck, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { isLiveCfo } from "@/api";
import { useCashRun } from "@/api/cashLiveHooks";
import { useLiveRun } from "@/api/creditorsLiveHooks";
import { useMgmtRun } from "@/api/mgmtLiveHooks";
import { usePnlRun } from "@/api/pnlLiveHooks";
import { useRelatedSummary } from "@/api/relatedLiveHooks";

/**
 * The front door: Finance, Operations and Merchandising reports kept apart.
 * The status chip on every tile says what stands behind it, so a user never has to guess whether a page is real, demo, sample or not started.
 */
type Tone = "real" | "mgmt" | "live" | "demo" | "sample" | "planned";
/** Chips of the data-backed tiles are derived from the run each page reads (see chipFor); the others are about the tile itself. */
type Source = "pnl" | "mgmt" | "cash" | "cred" | "related";

const TONE: Record<Tone, { label: string; cls: string }> = {
  real: { label: "Real data · verified candidate · not live", cls: "bg-[oklch(0.94_0.06_155)] text-[oklch(0.32_0.1_155)]" },
  mgmt: { label: "Real data · management view · books + adjustments", cls: "bg-[oklch(0.94_0.06_155)] text-[oklch(0.32_0.1_155)]" },
  live: { label: "Real data · per-source as-of", cls: "bg-[oklch(0.94_0.06_155)] text-[oklch(0.32_0.1_155)]" },
  demo: { label: "Demo data", cls: "bg-[oklch(0.96_0.06_85)] text-[oklch(0.38_0.09_70)]" },
  sample: { label: "Sample-data prototype", cls: "bg-[oklch(0.95_0.025_265)] text-[oklch(0.3_0.12_265)]" },
  planned: { label: "Not started", cls: "bg-secondary text-secondary-foreground" },
};

const NEUTRAL = "bg-secondary text-secondary-foreground";
const REAL = "bg-[oklch(0.94_0.06_155)] text-[oklch(0.32_0.1_155)]";
const WARN = "bg-[oklch(0.96_0.06_85)] text-[oklch(0.38_0.09_70)]";

export interface Chip { label: string; cls: string }
/** The chip of a tile that reads a real API: what the run header says, or "Not available" when the run cannot be read. Never a literal. */
export function chipFor(source: Source, run: { isError: boolean; data?: object | null }): Chip {
  if (run.isError) return { label: "Not available", cls: WARN };
  if (!run.data) return { label: "Checking…", cls: NEUTRAL };
  const st = (run.data as { data_state?: string }).data_state;
  if (source === "mgmt") return { label: "Real data · management view · books + adjustments", cls: REAL };
  if (!st) return { label: "Real data", cls: REAL };
  if (st === "live") return { label: "Real data · live", cls: REAL };
  if (st === "verified_candidate") return { label: "Real data · verified candidate · not live", cls: REAL };
  return { label: `Real data · ${st.replace(/_/g, " ")}`, cls: WARN };
}

function useChips(): Record<Source, Chip> {
  const pnl = usePnlRun();
  const mgmt = useMgmtRun();
  const cash = useCashRun();
  const cred = useLiveRun();
  const related = useRelatedSummary();
  return { pnl: chipFor("pnl", pnl), mgmt: chipFor("mgmt", mgmt), cash: chipFor("cash", cash), cred: chipFor("cred", cred), related: chipFor("related", related) };
}

type To = "/" | "/profitability" | "/mgmt" | "/cash" | "/creditors" | "/related-party" | "/operations/sales";
interface Tile {
  id: string;
  title: string;
  blurb: string;
  tone: Tone;
  /** when set, the chip is read from this source's run instead of `tone` */
  source?: Source;
  to?: To;
  icon: ReactNode;
}

const AREAS: { id: string; eyebrow: string; title: string; blurb: string; tiles: Tile[] }[] = [
  {
    id: "finance",
    eyebrow: "FP&A",
    title: "Finance",
    blurb: "The CFO's view: profit, cash and what the company owes.",
    tiles: [
      { id: "command", title: "CFO Command Center", blurb: "Financial pulse, what changed, risk and forecast.", tone: isLiveCfo ? "live" : "demo", to: "/", icon: <LayoutDashboard className="h-4 w-4" /> },
      { id: "profitability", title: "Store Profitability", blurb: "Store-level profit, from revenue from operations to Corporate EBITDA.", tone: "real", source: "pnl", to: "/profitability", icon: <Store className="h-4 w-4" /> },
      { id: "mgmt", title: "Management P&L", blurb: "The finance MIS view: store EBITDA, DC and HO cost, corporate EBITDA, reconciled to the MIS.", tone: "mgmt", source: "mgmt", to: "/mgmt", icon: <FileSpreadsheet className="h-4 w-4" /> },
      { id: "cash", title: "Liquidity & Working Capital", blurb: "Store till cash, creditors and the bank review card.", tone: "real", source: "cash", to: "/cash", icon: <Banknote className="h-4 w-4" /> },
      { id: "creditors", title: "Creditors Control", blurb: "How much we owe, how old it is and which vendors carry it.", tone: "real", source: "cred", to: "/creditors", icon: <Truck className="h-4 w-4" /> },
      { id: "related", title: "Related Party Transactions", blurb: "Intercompany balances and loans, kept out of Creditors and Cash; eliminated on consolidation.", tone: "real", source: "related", to: "/related-party", icon: <Handshake className="h-4 w-4" /> },
    ],
  },
  {
    id: "operations",
    eyebrow: "Retail operations",
    title: "Operations",
    blurb: "How the stores are trading: sales first, other operating reports to follow.",
    tiles: [
      { id: "sales", title: "Sales Comparison", blurb: "This period against a reference period, by store, with the reference dates shown.", tone: "sample", to: "/operations/sales", icon: <TrendingUp className="h-4 w-4" /> },
      { id: "more-ops", title: "More Operations reports", blurb: "To be agreed after Sales Comparison.", tone: "planned", icon: <BarChart3 className="h-4 w-4" /> },
    ],
  },
  {
    id: "merchandising",
    eyebrow: "Buying and stock",
    title: "Merchandising",
    blurb: "Range, stock and allocation reports.",
    tiles: [{ id: "merch", title: "Merchandising reports", blurb: "Not started. Scope to be agreed.", tone: "planned", icon: <Boxes className="h-4 w-4" /> }],
  },
];

function TileCard({ t, chip }: { t: Tile; chip: Chip }) {
  const body = (
    <>
      <div className="flex items-start gap-2.5">
        <span className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded", t.to ? "bg-[oklch(0.95_0.025_265)] text-primary" : "bg-muted text-muted-foreground")}>{t.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
            {t.title}
            {t.to ? <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" /> : <Lock className="h-3 w-3 text-muted-foreground/70" />}
          </div>
          <div className="mt-0.5 text-[12px] text-muted-foreground">{t.blurb}</div>
        </div>
      </div>
      <span data-testid={`tone-${t.id}`} className={cn("mt-2 inline-flex w-fit items-center rounded px-2 py-0.5 text-[11px] font-semibold", chip.cls)}>{chip.label}</span>
    </>
  );
  const cls = "flex h-full flex-col justify-between rounded-lg border bg-card p-3 shadow-sm";
  return t.to ? (
    <Link to={t.to} data-testid={`tile-${t.id}`} className={cn(cls, "press hover:border-primary/40 hover:bg-[oklch(0.985_0.01_265)]")}>
      {body}
    </Link>
  ) : (
    <div data-testid={`tile-${t.id}`} aria-disabled="true" className={cn(cls, "cursor-not-allowed opacity-80")}>
      {body}
    </div>
  );
}

export function Landing() {
  const chips = useChips();
  return (
    <div data-testid="landing" className="@container">
      <div className="border-b bg-card px-5 py-4">
        <div className="eyebrow">CityKart</div>
        <h1 className="text-[22px] font-semibold tracking-tight text-foreground">Analytics Home</h1>
        <div className="text-[12px] text-muted-foreground">Finance, Operations and Merchandising reports, kept separate. Each tile says what stands behind it.</div>
      </div>
      <div className="space-y-6 p-4">
        {AREAS.map((a) => (
          <section key={a.id} data-testid={`area-${a.id}`} aria-labelledby={`area-title-${a.id}`}>
            <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
              <div>
                <div className="eyebrow">{a.eyebrow}</div>
                <h2 id={`area-title-${a.id}`} className="text-[17px] font-semibold tracking-tight text-foreground">{a.title}</h2>
              </div>
              <div className="text-[12px] text-muted-foreground">{a.blurb}</div>
            </div>
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
              {a.tiles.map((t) => (
                <TileCard key={t.id} t={t} chip={t.source ? chips[t.source] : TONE[t.tone]} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
