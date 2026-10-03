import { X } from "lucide-react";
import { useCreditors } from "@/api/hooks";
import { AGE_FILTER_LABELS } from "@/types/creditors";
import { AgeingRiver } from "./AgeingRiver";
import { ExposureStrip } from "./ExposureStrip";
import { LensWorkspace } from "./LensWorkspace";
import { MigrationPanel } from "./MigrationPanel";
import { AgeingBasisNote, useRoomSelection } from "./parts";

/**
 * Stage 2: Creditors / Payables Control Room.
 * Exposure → Age → Movement → Diagnosis → Vendor → Ledger → Voucher. Tables come last, on the vendor page.
 */
export function CreditorsRoom() {
  const q = useCreditors();
  const { age, select } = useRoomSelection();
  return (
    <div data-testid="creditors-room" className="@container">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-5 py-3">
        <div className="min-w-0">
          <div className="eyebrow">Payables</div>
          <h1 className="truncate text-[20px] font-semibold tracking-tight text-foreground">Creditors Control Room</h1>
          <div className="text-[12px] text-muted-foreground">How much we owe, how old it is, what is moving into risk, and which vendors need attention.</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {age !== "all" && (
            <button data-testid="clear-age-filter" onClick={() => select(age)} className="press inline-flex items-center gap-1 rounded bg-[oklch(0.95_0.025_265)] px-2 py-1 text-[12px] font-semibold text-primary hover:bg-[oklch(0.92_0.04_265)]">
              Filter: {AGE_FILTER_LABELS[age]} <X className="h-3 w-3" />
            </button>
          )}
          {q.data?.data && <AgeingBasisNote basis={q.data.data.ageingBasis} />}
        </div>
      </div>
      <ExposureStrip />
      <div className="space-y-4 p-4">
        <AgeingRiver />
        <MigrationPanel />
        <LensWorkspace />
      </div>
    </div>
  );
}
