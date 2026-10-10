import { AttentionQueue, RiskLandscape } from "./RiskAndActions";
import { LiquidityTrajectory, WorkingCapitalPanel } from "./CashStory";
import { FinancialPulse } from "./FinancialPulse";
import { ForecastTrajectory } from "./ForecastTrajectory";
import { HeroBridge } from "./HeroBridge";
import { isLiveCfo } from "@/api";
import { NOT_YET_AVAILABLE } from "./DataStatus";

/**
 * Stage 1: CFO Command Center.
 * Summary (pulse) → Movement (hero bridge) → Driver/Entity (drawer) → Ledger → Voucher (full pages).
 */
export function CommandCenter() {
  if (isLiveCfo) {
    // Real data: only what has a source. Everything without one is a single line, and its reasons live in the data-status drawer.
    return (
      <div data-testid="command-center" className="@container">
        <FinancialPulse />
        <div className="space-y-4 p-4">
          <HeroBridge />
          <AttentionQueue />
          <p data-testid="not-yet-available-chip" className="text-[11.5px] text-muted-foreground">
            <span className="font-semibold text-foreground">Data not yet available ({NOT_YET_AVAILABLE.length}):</span> {NOT_YET_AVAILABLE.map((n) => n.label).join(" · ")}. Open the data status at the top right for the reasons.
          </p>
        </div>
      </div>
    );
  }
  return (
    <div data-testid="command-center" className="@container">
      <FinancialPulse />
      <div className="space-y-4 p-4">
        <HeroBridge />
        <div className="grid grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] gap-4 @max-[1150px]:grid-cols-1">
          <LiquidityTrajectory />
          <WorkingCapitalPanel />
        </div>
        <RiskLandscape />
        <AttentionQueue />
        <ForecastTrajectory />
      </div>
    </div>
  );
}
