/**
 * Cash & Working Capital Control contracts. ₹ Crore. A figure that has no source is a MetricValue with
 * value null and a reason, never zero.
 */
import type { Bridge, Family, Horizon, LiquidityPoint, MetricValue, Tone } from "./cfo";

export interface CashStep {
  horizon: Horizon;
  label: string;
  /** date the step lands on, matching the chart axis */
  dayLabel: string;
  closing: number;
  headroom: number;
  breach: boolean;
}

export interface CashObligation {
  id: string;
  /** e.g. "12 Oct" */
  dayLabel: string;
  daysAway: number;
  label: string;
  amount: number;
  kind: "vendor" | "payroll" | "statutory" | "occupancy";
  /** inside the selected horizon */
  inHorizon: boolean;
}

export interface WcDriver {
  id: string;
  label: string;
  /** cash impact for the selected period, ₹ Cr: negative = absorbed */
  cashImpact: number;
  direction: "absorbed" | "released";
  tone: Tone;
  note: string;
  family: Family;
  /** the operating measure behind the money, e.g. inventory days */
  measure: { label: string; value: number; unit: "days" | "cr"; change: number };
  /** monthly cash impact, oldest first; sums to cashImpact */
  monthly: number[];
  /** getting worse: absorbing more cash, or the measure moving the wrong way */
  deteriorating: boolean;
}

export interface CashRoom {
  horizon: Horizon;
  openingCash: number;
  forecastClosing: number;
  operatingMinimum: number;
  breachDay: string | null;
  headline: string;
  tone: Tone;
  steps: CashStep[];
  /** opening → inflows → obligations → forecast closing, for the selected horizon */
  bridge: Bridge;
  capex: MetricValue;
  series: LiquidityPoint[];
  obligations: CashObligation[];
  obligationTotals: { all: number; inHorizon: number };
  drivers: WcDriver[];
  /** net cash absorbed (−) or released (+) by working capital in the period */
  netCashImpact: number;
  wcHeadline: string;
}
