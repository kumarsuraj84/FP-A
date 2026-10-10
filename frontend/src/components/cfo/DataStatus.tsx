import { useState } from "react";
import { ChevronDown, RefreshCw, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useFreshness } from "@/api/hooks";
import { isLiveCfo } from "@/api";
import { fmtDate, stampText } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { SourceStamp } from "@/types/cfo";

/** One compact data-status indicator for every page, and ONE drawer that holds everything the old banners, badges and as-of pills said: the source runs and dates, what is not
 *  available yet, and the basis notes. Different sources really do have different as-of dates; the platform says so here once instead of repeating it on every screen. */

export const NOT_YET_AVAILABLE: { label: string; reason: string }[] = [
  { label: "AOP and forecast", reason: "No FY26-27 plan or forecast exists in the sources, so no variance to plan or projection is shown and none is estimated." },
  { label: "Bank reconciliation", reason: "No bank statement or reconciliation is available from the current sources. Store till cash is shown; the bank ledger book is separate and provisional." },
  { label: "Receivables", reason: "A source exists (Sundry Debtors); its contract, extract and verification are not built yet." },
  { label: "Inventory", reason: "No credible current stock valuation source was found; only the year-end closing stock is in the books." },
  { label: "Vendor advances", reason: "No source has been identified." },
];

export interface StatusInput {
  /** page level, when the page has its own verified run */
  page?: { asOf: string | null; stateLabel: string; state: string; updated: string | null; status: "ok" | "error" | "pending" } | null;
  refreshKeys?: string[][];
}

type Tone = "ok" | "mixed" | "bad";

function summarise(sources: SourceStamp[] | undefined, page: StatusInput["page"]): { tone: Tone; text: string } {
  if (page) {
    if (page.status === "error") return { tone: "bad", text: "Data unavailable" };
    if (page.status === "pending") return { tone: "mixed", text: "Checking…" };
    const d = page.asOf ? fmtDate(page.asOf) : "date not given";
    if (page.state === "management") return { tone: "ok", text: `Management view · ${d}` };
    return page.state === "live" ? { tone: "ok", text: `Live · ${d}` } : { tone: "mixed", text: `${page.stateLabel} · ${d}` };
  }
  if (!sources) return { tone: "mixed", text: "Checking sources…" };
  if (sources.some((s) => !s.ok)) return { tone: "bad", text: "A source is unavailable" };
  const dates = new Set(sources.map((s) => s.asOf));
  return dates.size <= 1 ? { tone: "ok", text: `Current · ${sources[0]?.asOf ? fmtDate(sources[0].asOf) : "date not given"}` } : { tone: "mixed", text: "Mixed freshness" };
}

const DOT: Record<Tone, string> = { ok: "bg-[oklch(0.62_0.16_155)]", mixed: "bg-[oklch(0.72_0.15_75)]", bad: "bg-[oklch(0.58_0.2_25)]" };
const CHIP: Record<Tone, string> = { ok: "bg-[oklch(0.96_0.03_155)] text-[oklch(0.38_0.1_155)]", mixed: "bg-[oklch(0.96_0.05_85)] text-[oklch(0.42_0.1_75)]", bad: "bg-[oklch(0.95_0.04_25)] text-[oklch(0.45_0.15_25)]" };

export function DataStatus({ page, refreshKeys }: StatusInput) {
  const [open, setOpen] = useState(false);
  const fresh = useFreshness();
  const qc = useQueryClient();
  const sources = fresh.data?.sources;
  const { tone, text } = summarise(isLiveCfo ? sources : undefined, page ?? null);
  const shown = isLiveCfo || page;
  if (!shown && !fresh.data) return null;
  const label = !isLiveCfo && !page ? (fresh.data?.label ?? "Checking freshness…") : text;
  return (
    <div className="relative flex items-center gap-1.5" data-testid="data-status">
      <button
        type="button"
        data-testid="real-state"
        data-state={page?.state ?? (tone === "ok" ? "live" : tone)}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen(!open)}
        title="Data status: sources, dates and what is not available yet"
        className={cn("press inline-flex items-center gap-1.5 rounded px-2 py-1 text-[11px] font-semibold", CHIP[tone])}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", DOT[tone])} />
        <span data-testid="real-asof" data-asof={page?.asOf ?? ""}>{page?.asOf ? fmtDate(page.asOf) : ""}</span>
        <span data-testid="data-status-text">{label}</span>
        <ChevronDown className="h-3 w-3 opacity-70" />
      </button>
      <button
        type="button"
        data-testid="real-refresh"
        onClick={() => (refreshKeys ?? [["pulse"], ["bridge"], ["fresh"]]).forEach((queryKey) => qc.invalidateQueries({ queryKey }))}
        className="press inline-flex items-center gap-1 rounded border bg-card px-2 py-1 text-[11px] font-semibold hover:bg-muted"
        title="Reload this page's data"
      >
        <RefreshCw className="h-3 w-3" /> Refresh
      </button>
      {page && <div data-testid="real-updated" className="sr-only">{page.updated ? `Source updated ${page.updated}` : "Source timestamp not provided"}</div>}
      {open && (
        <div role="dialog" aria-label="Data status" data-testid="data-status-drawer" className="absolute right-0 top-9 z-40 w-[440px] rounded-md border bg-card p-4 text-[12px] shadow-lg">
          <div className="mb-2 flex items-start justify-between">
            <div>
              <div className="eyebrow">Data status</div>
              <div className="text-[14px] font-semibold">{text}</div>
            </div>
            <button type="button" aria-label="Close data status" onClick={() => setOpen(false)} className="rounded p-1 hover:bg-muted"><X className="h-3.5 w-3.5" /></button>
          </div>
          <p data-testid="data-notes" className="mb-3 text-muted-foreground">
            Each figure carries its own run and as-of date: the P&amp;L, Management P&amp;L, Creditors and Cash are separate runs, so this is real, per-source data and not one synchronised CFO position.
            {page && <> This page: {page.stateLabel}, as of {page.asOf ? fmtDate(page.asOf) : "date not given"}{page.updated ? `, source updated ${page.updated}` : ", source timestamp not provided"}.</>}
          </p>
          <div className="eyebrow mb-1">Sources</div>
          <ul className="mb-3 space-y-1" data-testid="data-sources">
            {(sources ?? []).map((s) => (
              <li key={s.id} data-testid={`freshness-${s.id}`} data-ok={s.ok} className="flex items-start gap-1.5">
                <span className={cn("mt-1 h-1.5 w-1.5 shrink-0 rounded-full", s.ok ? DOT.ok : DOT.bad)} />
                <span>{s.label} {s.ok && s.asOf ? fmtDate(s.asOf) : "not read"}<span className="block text-[11px] text-muted-foreground">{stampText(s)}</span></span>
              </li>
            ))}
            {!sources && <li className="text-muted-foreground">Checking sources…</li>}
          </ul>
          <div className="eyebrow mb-1">Not yet available ({NOT_YET_AVAILABLE.length})</div>
          <ul data-testid="not-yet-available" className="space-y-1">
            {NOT_YET_AVAILABLE.map((n) => (
              <li key={n.label}><span className="font-semibold">{n.label}</span><span className="block text-[11px] text-muted-foreground">{n.reason}</span></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
