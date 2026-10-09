import { cn } from "@/lib/utils";

/**
 * One small tag that says on which basis a figure is computed. 'Corporate EBITDA' has three values on three pages because they are three bases:
 * the gold books (Profitability), the management book layer, and the management total (book plus adjustments). Label only: no number depends on it.
 */
export type Basis = "books" | "mgmt_book" | "mgmt_total";

export const BASIS_LABEL: Record<Basis, string> = {
  books: "Books",
  mgmt_book: "Management: book layer",
  mgmt_total: "Management total",
};

export function BasisTag({ basis, className, onDark = false }: { basis: Basis; className?: string; onDark?: boolean }) {
  return (
    <span
      data-testid="basis-tag"
      data-basis={basis}
      title={basis === "books" ? "Gold books, before management adjustments" : basis === "mgmt_book" ? "Management P&L, book layer only (before adjustments)" : "Management P&L: book plus management adjustments"}
      className={cn("ml-1.5 inline-flex items-center rounded-sm border px-1 py-px align-middle text-[9.5px] font-semibold normal-case leading-none tracking-normal", onDark ? "border-white/30 text-white/80" : "border-border bg-muted text-muted-foreground", className)}
    >
      {BASIS_LABEL[basis]}
    </span>
  );
}
