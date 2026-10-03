import { AttentionQueue, RiskLandscape } from "./RiskAndActions";
import { LiquidityTrajectory, WorkingCapitalPanel } from "./CashStory";
import { FinancialPulse } from "./FinancialPulse";
import { ForecastTrajectory } from "./ForecastTrajectory";
import { HeroBridge } from "./HeroBridge";

/**
 * Stage 1: CFO Command Center.
 * Summary (pulse) → Movement (hero bridge) → Driver/Entity (drawer) → Ledger → Voucher (full pages).
 */
export function CommandCenter() {
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
