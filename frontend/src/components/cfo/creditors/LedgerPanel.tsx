import { useLiveLedgers } from "@/api/creditorsLiveHooks";
import { fmtRupees, toCr } from "@/api/creditorsLive";
import { fmtCr } from "@/lib/format";
import type { LedgerRow } from "@/types/creditorsLive";
import { cn } from "@/lib/utils";
import type { AgeFilter } from "@/types/creditors";
import { Skeleton } from "../common";
import { LiveBoundary, useRoomSelection } from "./parts";

/** The four creditor ledgers in scope. Credit and debit are separate columns; there is no blended total per ledger. */
export function LedgerPanel() {
  const q = useLiveLedgers();
  const { age, select } = useRoomSelection();
  return (
    <section aria-label="Creditor ledgers" data-testid="ledger-panel" className="rounded-md border bg-card shadow-elegant">
      <div className="border-b px-4 py-3">
        <div className="eyebrow">Scope · four creditor ledgers</div>
        <h2 className="text-[15px] font-semibold tracking-tight">Where the balances sit</h2>
      </div>
      <LiveBoundary query={q} skeleton={<Skeleton className="m-4 h-[140px]" />}>
        {(rows: LedgerRow[]) => (
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="border-b text-left text-[10.5px] uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-2 font-semibold">Ledger</th>
                  <th className="px-2 py-2 text-right font-semibold">Credit outstanding</th>
                  <th className="px-2 py-2 text-right font-semibold">Debit balance</th>
                  <th className="px-2 py-2 text-right font-semibold">Past due</th>
                  <th className="px-2 py-2 text-right font-semibold">Due date unavailable</th>
                  <th className="px-2 py-2 text-right font-semibold">Vendors</th>
                  <th className="px-4 py-2 text-right font-semibold">Items (Cr / Dr)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const f = `ledger_${r.ledger_code}` as AgeFilter;
                  return (
                  <tr key={r.ledger_code} data-testid={`ledger-${r.ledger_code}`} aria-selected={age === f} tabIndex={0} onClick={() => select(f)} onKeyDown={(e) => e.key === "Enter" && select(f)} title="Click to show only this ledger's vendors below" className={cn("press cursor-pointer border-b last:border-b-0 hover:bg-[oklch(0.97_0.012_265)]", age === f && "bg-[oklch(0.95_0.025_265)]")}>
                    <td className="px-4 py-2"><span className="font-medium text-foreground">{r.ledger_name}</span> <span className="text-muted-foreground">· {r.ledger_code}</span></td>
                    <td data-exact={r.credit_outstanding} className="num px-2 py-2 text-right font-semibold" title={fmtRupees(r.credit_outstanding)}>{fmtCr(toCr(r.credit_outstanding))}</td>
                    <td data-exact={r.debit_balance} className="num px-2 py-2 text-right text-muted-foreground" title={fmtRupees(r.debit_balance)}>{fmtCr(toCr(r.debit_balance))}</td>
                    <td className="num px-2 py-2 text-right">{fmtCr(toCr(r.past_due_credit))}</td>
                    <td className="num px-2 py-2 text-right">{fmtCr(toCr(r.due_unavailable_credit))}</td>
                    <td className="num px-2 py-2 text-right">{r.vendors.toLocaleString("en-IN")}</td>
                    <td className="num px-4 py-2 text-right text-muted-foreground">{r.credit_items.toLocaleString("en-IN")} / {r.debit_items.toLocaleString("en-IN")}</td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="border-t px-4 py-2 text-[10.5px] text-muted-foreground">A vendor can sit in more than one ledger, so ledger vendor counts add up to more than the distinct vendor total. Click a ledger to narrow the vendor sections to it.</div>
          </div>
        )}
      </LiveBoundary>
    </section>
  );
}
