import type { ReactNode } from "react";
import { useRouter, useRouterState } from "@tanstack/react-router";
import { AlertTriangle, CheckCircle2, ChevronRight, Link2, Link2Off } from "lucide-react";
import { useEntryRun } from "@/api/entryLiveHooks";
import { crumbHref, hereWithoutTrail, pushTrail, type TrailItem } from "@/lib/entryLinks";
import { cn } from "@/lib/utils";
import type { LinkStatus } from "@/types/entryLive";
import { DataStateBadge } from "../creditors/parts";

/** A same-app link that keeps the SPA (and its in-memory data) but still has a real href, so it opens in a new tab and can be copied. */
export function AppLink({ href, children, className, testId, title }: { href: string; children: ReactNode; className?: string; testId?: string; title?: string }) {
  const router = useRouter();
  return (
    <a
      href={href}
      data-testid={testId}
      title={title}
      className={className}
      onClick={(e) => {
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        router.history.push(href);
      }}
    >
      {children}
    </a>
  );
}

/** The page's own URL without its trail, and the trail extended by this page, for the links that leave it. */
export function useHere(trail: TrailItem[], label: string) {
  const href = useRouterState({ select: (s) => s.location.href });
  const here = hereWithoutTrail(href);
  return { here, next: pushTrail(trail, label, here) };
}

/** Breadcrumb: where the user came from (each step is a real link with its own way back), then this page. */
export function Crumbs({ trail, current }: { trail: TrailItem[]; current: string }) {
  return (
    <nav aria-label="Where you came from" data-testid="entry-crumbs" className="flex flex-wrap items-center gap-1 border-b bg-background px-5 py-1.5 text-[12px]">
      <span className="text-muted-foreground">CityKart</span>
      {trail.map((t, i) => (
        <span key={`${t.h}-${i}`} className="flex items-center gap-1">
          <ChevronRight className="h-3 w-3 text-muted-foreground/60" />
          <AppLink href={crumbHref(trail, i)} testId={`entry-crumb-${i}`} className="press max-w-[34ch] truncate rounded px-1 py-0.5 text-muted-foreground hover:bg-muted hover:text-foreground">
            {t.l}
          </AppLink>
        </span>
      ))}
      <ChevronRight className="h-3 w-3 text-muted-foreground/60" />
      <span aria-current="page" className="font-semibold text-foreground">{current}</span>
    </nav>
  );
}

/** The run the drill reads (own as-of, own state), in the same badge the other real pages use. */
export function EntryRunBadge() {
  const run = useEntryRun();
  if (!run.data) return null;
  return <DataStateBadge state={run.data.data_state} run={run.data.entry_run_id} asOf={run.data.register_report_date} />;
}

const STATUS_STYLE: Record<string, string> = {
  Posted: "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]",
  Unposted: "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] text-[oklch(0.45_0.09_75)]",
  Mixed: "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] text-[oklch(0.45_0.09_75)]",
};

export function StatusChip({ status, className }: { status: string; className?: string }) {
  return (
    <span data-testid="release-status" data-status={status} className={cn("inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[11px] font-semibold", STATUS_STYLE[status] ?? "border-border bg-muted text-muted-foreground", className)}>
      {status}
    </span>
  );
}

/** Dr = Cr or not, in words. The unbalanced case carries the honest reason: gold holds only the cost-tag legs of a voucher. */
export function BalanceBadge({ balanced, difference }: { balanced: boolean; difference: string }) {
  return balanced ? (
    <span data-testid="balance-badge" data-balanced="true" className="inline-flex items-center gap-1 rounded-sm border border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)] px-1.5 py-0.5 text-[11px] font-semibold text-[oklch(0.4_0.12_155)]">
      <CheckCircle2 className="h-3 w-3" /> Debits = credits
    </span>
  ) : (
    <span data-testid="balance-badge" data-balanced="false" className="inline-flex items-center gap-1 rounded-sm border border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] px-1.5 py-0.5 text-[11px] font-semibold text-[oklch(0.45_0.09_75)]" title={`Debits minus credits: ${difference}`}>
      <AlertTriangle className="h-3 w-3" /> Not balanced in the extract
    </span>
  );
}

const LINK_STYLE: Record<string, string> = {
  EXACT: "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]",
  STRONG: "border-[oklch(0.75_0.1_155)] bg-[oklch(0.96_0.04_155)] text-[oklch(0.4_0.12_155)]",
  AMBIGUOUS: "border-[oklch(0.8_0.08_85)] bg-[oklch(0.985_0.03_90)] text-[oklch(0.45_0.09_75)]",
  NOT_LINKED: "border-border bg-muted text-muted-foreground",
};
const LINK_TEXT: Record<string, string> = { EXACT: "Exact", STRONG: "Strong", AMBIGUOUS: "Ambiguous", NOT_LINKED: "Not linked" };

export const LINK_REASON: Record<string, string> = {
  REGISTER_COVERAGE_UNAVAILABLE: "The voucher register does not reach back to this bill's date",
  NO_MATCH: "No voucher in the register carries this bill's document code",
};

export function LinkChip({ status, reason, className }: { status: LinkStatus; reason?: string | null; className?: string }) {
  const Icon = status === "NOT_LINKED" ? Link2Off : Link2;
  return (
    <span data-testid="link-status" data-status={status} title={reason ? (LINK_REASON[reason] ?? reason) : undefined} className={cn("inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] font-semibold", LINK_STYLE[status] ?? LINK_STYLE.NOT_LINKED, className)}>
      <Icon className="h-3 w-3" /> {LINK_TEXT[status] ?? status}
    </span>
  );
}

/** The gold source holds the cost-tag legs of a voucher only. Said once, in one place, so every unbalanced figure is read the same way. */
export const GAP_NOTE =
  "The gold extract holds only the cost-tag lines of a voucher: the creditor, bank and cash-control legs are not in it. About 9% of recent vouchers therefore do not add up to zero here. That is a gap in the source extract, not a posting error.";
