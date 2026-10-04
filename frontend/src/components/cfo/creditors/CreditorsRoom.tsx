import { X } from "lucide-react";
import { useLiveRun } from "@/api/creditorsLiveHooks";
import { AGE_FILTER_LABELS } from "@/types/creditors";
import { AgeingRiver } from "./AgeingRiver";
import { DueStatusPanel } from "./DueStatusPanel";
import { ExposureStrip } from "./ExposureStrip";
import { LedgerPanel } from "./LedgerPanel";
import { LensWorkspace } from "./LensWorkspace";
import { DataStateBadge, useRoomSelection } from "./parts";

/**
 * Creditors / Payables Control Room on REAL data (the verified FP&A mart, through the read-only Creditors API).
 * Exposure → Document Age → Due Status → Ledgers → Diagnosis → Vendor. The API states the data state; this page only displays it.
 */
export function CreditorsRoom() {
  const run = useLiveRun();
  const { age, select } = useRoomSelection();
  return (
    <div data-testid="creditors-room" className="@container">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-5 py-3">
        <div className="min-w-0">
          <div className="eyebrow">Payables</div>
          <h1 className="truncate text-[20px] font-semibold tracking-tight text-foreground">Creditors Control Room</h1>
          <div className="text-[12px] text-muted-foreground">How much we owe, how old the documents are, what the source says is due, and which vendors carry it.</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {age !== "all" && (
            <button data-testid="clear-age-filter" onClick={() => select(age)} className="press inline-flex items-center gap-1 rounded bg-[oklch(0.95_0.025_265)] px-2 py-1 text-[12px] font-semibold text-primary hover:bg-[oklch(0.92_0.04_265)]">
              Filter: {AGE_FILTER_LABELS[age]} <X className="h-3 w-3" />
            </button>
          )}
          {run.data && <DataStateBadge state={run.data.data_state} run={run.data.extraction_run_id} asOf={run.data.as_of_date} />}
        </div>
      </div>
      <ExposureStrip />
      <div className="space-y-4 p-4">
        <AgeingRiver />
        <DueStatusPanel />
        <LedgerPanel />
        <LensWorkspace />
      </div>
    </div>
  );
}
