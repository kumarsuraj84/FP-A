import { fmtCr } from "@/lib/format";
import { AppLink } from "../entry/parts";

/** One line on the Creditors and Cash pages: intercompany payables are kept out of these figures and live on their own page. Hidden when the API reports none. */
export function RelatedExcludedNote({ excluded, testId = "related-excluded-note", className }: { excluded: { payable_cr: string } | null | undefined; testId?: string; className?: string }) {
  if (!excluded) return null;
  return (
    <div data-testid={testId} className={className ?? "border-t bg-[oklch(0.985_0.006_265)] px-4 py-1.5 text-[11.5px] text-muted-foreground"}>
      Related-party balances of <span data-exact={excluded.payable_cr} className="num font-semibold text-foreground">{fmtCr(Number(excluded.payable_cr))}</span> payable are excluded (intercompany) - see{" "}
      <AppLink href="/related-party" testId={`${testId}-link`} className="font-semibold text-primary underline-offset-2 hover:underline">Related Party Transactions</AppLink>.
    </div>
  );
}
