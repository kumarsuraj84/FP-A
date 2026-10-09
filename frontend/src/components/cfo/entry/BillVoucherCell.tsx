import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { useBillLink } from "@/api/entryLiveHooks";
import { entryHref, type TrailItem } from "@/lib/entryLinks";
import { AppLink, LINK_REASON, LinkChip } from "./parts";

/**
 * One creditor open bill → its voucher. The link status comes from the Entry API (STRONG, or NOT_LINKED with the reason); it is asked for
 * only when the user asks, so a 500-bill list does not fire 500 requests. A bill that is not linked has no voucher to open, and says why.
 */
export function BillVoucherCell({ itemRef, documentCode, trail }: { itemRef: string; documentCode?: string; trail: TrailItem[] }) {
  const [asked, setAsked] = useState(false);
  if (!asked) {
    return (
      <button data-testid={`bill-voucher-${itemRef}`} onClick={() => setAsked(true)} className="press inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11.5px] font-semibold text-primary hover:bg-muted" title={documentCode ? `Document code ${documentCode}` : "Check whether a voucher is linked to this bill"}>
        <ExternalLink className="h-3 w-3" /> Voucher
      </button>
    );
  }
  return <Result itemRef={itemRef} trail={trail} />;
}

/** Mounted only after the click, so a list of bills fires no request until one is asked for. */
function Result({ itemRef, trail }: { itemRef: string; trail: TrailItem[] }) {
  const q = useBillLink(itemRef);
  if (q.isPending) return <span data-testid={`bill-voucher-${itemRef}`} className="text-[11.5px] text-muted-foreground">Checking…</span>;
  if (q.isError || !q.data) return <span data-testid={`bill-voucher-${itemRef}`} className="text-[11.5px] tone-bad" title={(q.error as Error | null)?.message}>Could not check</span>;
  const k = q.data.link;
  return (
    <span data-testid={`bill-voucher-${itemRef}`} className="inline-flex flex-wrap items-center gap-1.5">
      <LinkChip status={k.link_status} reason={k.not_linked_reason} />
      {k.entry_ref ? (
        <AppLink href={entryHref(k.entry_ref, trail, itemRef)} testId={`bill-open-${itemRef}`} className="num-mono text-[11.5px] font-semibold text-primary underline-offset-2 hover:underline">
          {k.entry_ref}
        </AppLink>
      ) : (
        <span className="max-w-[26ch] text-[11px] leading-tight text-muted-foreground" data-testid={`bill-reason-${itemRef}`}>
          {k.not_linked_reason ? (LINK_REASON[k.not_linked_reason] ?? k.not_linked_reason) : "No voucher"}
        </span>
      )}
    </span>
  );
}
