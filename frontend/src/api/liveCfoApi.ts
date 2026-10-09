import type {
  Bridge,
  BridgeItem,
  CfoAction,
  CfoApi,
  DrillLink,
  DrillNode,
  DrillOrigin,
  DrillRow,
  DrillView,
  Envelope,
  EntityProfile,
  Family,
  ForecastTrajectory,
  FreshnessInfo,
  HeroTab,
  Horizon,
  LedgerView,
  LiquiditySummary,
  MetricValue,
  PulseMetric,
  QueryCtx,
  RiskPillar,
  LiveSeverity,
  SourceId,
  SourceStamp,
  Tone,
  VoucherEvidence,
  WorkingCapitalLine,
  WorkingCapitalSummary,
} from "@/types/cfo";
import type { PnlStoreRow, PnlSummary } from "@/types/pnlLive";
import type { CashSummary, TillStore } from "@/types/cashLive";
import type { LedgerRow, LiveSummary } from "@/types/creditorsLive";
import { DASH, fmtCr, fmtDate, stampText } from "@/lib/format";
import { liveCash } from "./cashLive";
import { liveCreditors } from "./creditorsLive";
import { livePnl } from "./pnlLive";
import { ApiError, mockApi } from "./mockApi";

/**
 * The LIVE implementation of CfoApi for the Command Center.
 *
 * It is composed ONLY from the three real, read-only APIs (P&L actuals, Creditors, Cash). Nothing here is estimated:
 *  - every figure carries the SourceStamp (run id + the run's OWN as-of date) of the source it was read from;
 *  - the three runs are separate and may carry different as-of dates, so no figure is ever presented as part of one
 *    synchronized CFO position;
 *  - what no source can supply (bank-reconciled cash, receivables, inventory, vendor advances, forecast, budget) is an explicit
 *    "unavailable" with the source's own reason, never zero and never an invented number;
 *  - risks and actions are derived only from real facts, and each cites the evidence it rests on.
 *
 * Room-level methods that only feed the demo workspaces (Stage 2-4 room data, ledger / voucher / profile of those rooms) are
 * delegated unchanged to the demo service, so the three live pages behave exactly as before.
 */

export interface LiveClients {
  pnl: Pick<typeof livePnl, "current" | "summary" | "stores" | "reconciliation">;
  cash: Pick<typeof liveCash, "current" | "summary" | "stores">;
  creditors: Pick<typeof liveCreditors, "current" | "summary" | "ledgers">;
}

export interface LiveOptions {
  clients?: LiveClients;
  /** serves the room-level methods that belong to the demo workspaces; defaults to the demo service */
  rooms?: CfoApi;
  /** how long a read is reused across sections (the sections all load at once); 0 = never */
  ttlMs?: number;
}

const CR = 1e7;
const rupToCr = (s: string | number | null | undefined): number | null => (s === null || s === undefined || s === "" ? null : Number(s) / CR);
const n = (s: string | number | null | undefined): number => (s === null || s === undefined || s === "" ? 0 : Number(s));
const r2 = (x: number) => Math.round(x * 100) / 100;
const pct1 = (x: number) => `${x.toFixed(1)}%`;
const na = (reason: string): MetricValue => ({ value: null, reason });
const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthLabel = (m: string) => `${MONTHS[Number(m.slice(5, 7)) - 1] ?? m.slice(5, 7)} ${m.slice(0, 4)}`;
const monthsText = (a: string, b: string) => (a === b ? monthLabel(a) : `${monthLabel(a)} to ${monthLabel(b)}`);

const STATE_TEXT: Record<string, string> = { verified_candidate: "Verified candidate · not live", live: "Live", superseded: "Superseded", withdrawn: "Withdrawn" };
const SOURCE_LABEL: Record<SourceId, string> = { pnl: "P&L", creditors: "Creditors", cash: "Cash" };

/** The period control only reaches the P&L (flows). Creditors and Cash are point-in-time balances. */
const PERIOD_MONTHS: Record<QueryCtx["period"], [string | undefined, string | undefined]> = {
  sep26: ["2026-09", "2026-09"],
  q2fy27: ["2026-07", "2026-09"],
  ytdfy27: [undefined, undefined],
};

export const NO_BUDGET = "Budget is not available for FY26-27 (the FY25-26 plan ended in March 2026). Nothing is estimated.";
export const NO_FORECAST = "No forecast source exists. A projection is not shown, and none is estimated.";
export const NO_RECON = "No bank statement or reconciliation is available from the current sources.";
export const NO_CASH_MOVEMENT = "No opening-cash or cash-flow source exists. Store till cash is a balance, not a movement, and no bank statement or reconciliation is available.";

/* ───────────── per-source reads (each degrades alone) ───────────── */

type Read<T> = { ok: true; stamp: SourceStamp; data: T } | { ok: false; stamp: SourceStamp; error: string };

const stamp = (id: SourceId, runId: string, asOf: string, state: string, label?: string): SourceStamp => ({
  id,
  label: SOURCE_LABEL[id],
  runId,
  asOf,
  state,
  stateLabel: STATE_TEXT[state] ?? label ?? state,
  ok: true,
});
const failed = (id: SourceId, error: string): SourceStamp => ({ id, label: SOURCE_LABEL[id], runId: null, asOf: null, state: "error", stateLabel: "Not available", ok: false, reason: error });

const oldest = (stamps: SourceStamp[]): string => {
  const d = stamps.map((s) => s.asOf).filter((x): x is string => !!x).sort();
  return d[0] ?? new Date().toISOString().slice(0, 10);
};

export function createLiveCfoApi(opts: LiveOptions = {}): CfoApi {
  const c: LiveClients = opts.clients ?? { pnl: livePnl, cash: liveCash, creditors: liveCreditors };
  const rooms = opts.rooms ?? mockApi;
  const ttl = opts.ttlMs ?? 30_000;

  /* The sections of the page all load together: share one read per source for a short moment. Failures are never kept. */
  const cache = new Map<string, { at: number; p: Promise<unknown> }>();
  function memo<T>(key: string, fn: () => Promise<T>, keep: (v: T) => boolean = () => true): Promise<T> {
    const hit = cache.get(key);
    if (hit && Date.now() - hit.at < ttl) return hit.p as Promise<T>;
    const p = fn();
    cache.set(key, { at: Date.now(), p });
    p.then(
      (v) => {
        if (!keep(v)) cache.delete(key);
      },
      () => cache.delete(key),
    );
    return p;
  }

  const readPnl = (period: QueryCtx["period"]) =>
    memo<Read<PnlSummary>>(
      `pnl:${period}`,
      async () => {
        try {
          const h = await c.pnl.current();
          const [from, to] = PERIOD_MONTHS[period];
          const s = await c.pnl.summary(h.run_id, { basis: "all", from_month: from, to_month: to });
          return { ok: true, stamp: stamp("pnl", s.run_id, s.as_of_date, s.data_state, s.data_state_label), data: s };
        } catch (e) {
          return { ok: false, stamp: failed("pnl", msg(e)), error: msg(e) };
        }
      },
      (r) => r.ok,
    );

  const readCash = () =>
    memo<Read<CashSummary>>(
      "cash",
      async () => {
        try {
          const h = await c.cash.current();
          const s = await c.cash.summary(h.run_id);
          return { ok: true, stamp: stamp("cash", s.run_id, s.as_of_date, s.data_state, s.data_state_label), data: s };
        } catch (e) {
          return { ok: false, stamp: failed("cash", msg(e)), error: msg(e) };
        }
      },
      (r) => r.ok,
    );

  const readCred = () =>
    memo<Read<LiveSummary>>(
      "cred",
      async () => {
        try {
          const h = await c.creditors.current();
          const s = await c.creditors.summary(h.extraction_run_id);
          return { ok: true, stamp: stamp("creditors", s.extraction_run_id, s.as_of_date, s.data_state, s.data_state_label), data: s };
        } catch (e) {
          return { ok: false, stamp: failed("creditors", msg(e)), error: msg(e) };
        }
      },
      (r) => r.ok,
    );

  const all = async (ctx: QueryCtx) => {
    const [pnl, cash, cred] = await Promise.all([readPnl(ctx.period), readCash(), readCred()]);
    return { pnl, cash, cred, stamps: [pnl.stamp, cred.stamp, cash.stamp] };
  };

  const ok = <T,>(data: T, asOf: string, reason?: string): Envelope<T> => ({ status: "ok", data, asOf, reason });
  const unavailable = <T,>(reason: string, asOf = new Date().toISOString().slice(0, 10)): Envelope<T> => ({ status: "unavailable", reason, asOf });
  const allDown = (reads: Read<unknown>[]) => new ApiError(`The real sources could not be read: ${reads.map((r) => `${r.stamp.label} (${r.ok ? "ok" : (r as { error: string }).error})`).join("; ")}`, 502);

  /* ───────────── comparison (last year only: there is no live budget or forecast) ───────────── */

  function lastYear(ctx: QueryCtx, s: PnlSummary) {
    const cmp = s.comparison;
    if (ctx.comparison === "budget") return { ly: null, label: "Budget not available", reason: s.budget_note || NO_BUDGET };
    if (ctx.comparison === "forecast") return { ly: null, label: "Forecast not available", reason: NO_FORECAST };
    if (!cmp?.last_year) return { ly: null, label: "No last-year data", reason: "No comparable last-year months exist for this selection." };
    return { ly: cmp, label: `vs last year · ${monthsText(cmp.period.from_month, cmp.period.to_month)}, complete months`, reason: undefined };
  }

  const toneOf = (v: number | null, goodWhenUp = true): Tone => (v === null || Math.abs(v) < 0.005 ? "neutral" : v > 0 === goodWhenUp ? "good" : "bad");

  /* ───────────── pulse ───────────── */

  async function getPulse(ctx: QueryCtx): Promise<Envelope<PulseMetric[]>> {
    const { pnl, cash, cred, stamps } = await all(ctx);
    if (!pnl.ok && !cash.ok && !cred.ok) throw allDown([pnl, cash, cred]);
    const out: PulseMetric[] = [];

    /* Cash */
    if (cash.ok) {
      const t = cash.data.till;
      out.push({
        id: "cash", label: "Store till cash", value: { value: rupToCr(t.store_till_cash) }, unit: "cr",
        comparisonLabel: "No prior snapshot", movement: na("No prior till snapshot is served, so no movement is shown."), movementUnit: "cr",
        status: `${t.stores_with_cash} of ${t.stores} stores hold cash · excludes bank`,
        tone: t.stores_negative > 0 ? "warn" : "neutral", family: "cash", heroTab: "cash",
        origin: { source: "pulse", scope: "pulse", id: "cash", label: "Store till cash", family: "cash", amount: rupToCr(t.store_till_cash), variance: null },
        source: cash.stamp,
      });
    } else out.push(missing("cash", "Store till cash", "cash", "cash", cash.stamp));

    /* P&L: net sales, gross margin, contribution */
    if (pnl.ok) {
      const s = pnl.data;
      const t = s.totals;
      const { ly, label, reason } = lastYear(ctx, s);
      const why = reason ?? "";
      const span = `${monthsText(s.scope.from_month, s.scope.to_month)}${s.scope.partial_last_month ? " (last month partial)" : ""}`;
      const revMove = ly?.current && ly.last_year ? rupToCr(String(n(ly.current.revenue) - n(ly.last_year.revenue))) : null;
      const profMove = ly?.current && ly.last_year ? rupToCr(String(n(ly.current.contribution) - n(ly.last_year.contribution))) : null;
      const gmMove = ly?.current && ly.last_year && ly.current.gross_margin_pct && ly.last_year.gross_margin_pct ? Math.round((n(ly.current.gross_margin_pct) - n(ly.last_year.gross_margin_pct)) * 100) : null;
      const rev = rupToCr(t.revenue);
      out.push({
        id: "revenue", label: "Net sales", value: { value: rev }, unit: "cr", comparisonLabel: label,
        movement: revMove === null ? na(why) : { value: revMove }, movementUnit: "cr",
        status: span, tone: toneOf(revMove), family: "volume", heroTab: "profit",
        origin: { source: "pulse", scope: "pulse", id: "revenue", label: "Net sales", family: "volume", amount: rev, variance: revMove },
        source: pnl.stamp,
      });
      const gmPct = t.gross_margin_pct === null ? null : n(t.gross_margin_pct);
      out.push({
        id: "gm", label: "Gross margin", value: gmPct === null ? na("Gross margin % is not available for this selection.") : { value: gmPct }, unit: "pct", comparisonLabel: label,
        movement: gmMove === null ? na(why || "No last-year margin to compare with.") : { value: gmMove }, movementUnit: "bps",
        status: `${fmtCr(rupToCr(t.gross_margin))} gross margin`, tone: gmMove === null ? "neutral" : gmMove < -100 ? "bad" : gmMove < 0 ? "warn" : "good", family: "margin", heroTab: "profit",
        origin: { source: "pulse", scope: "pulse", id: "gm", label: "Gross margin", family: "margin", amount: rupToCr(t.gross_margin), variance: null },
        source: pnl.stamp,
      });
      const cont = rupToCr(t.contribution);
      out.push({
        id: "profit", label: "Store contribution", value: { value: cont }, unit: "cr", comparisonLabel: label,
        movement: profMove === null ? na(why) : { value: profMove }, movementUnit: "cr",
        status: `${t.contribution_pct === null ? DASH : pct1(n(t.contribution_pct))} of net sales · before head office`, tone: toneOf(profMove), family: "margin", heroTab: "profit",
        origin: { source: "pulse", scope: "pulse", id: "profit", label: "Store contribution", family: "margin", amount: cont, variance: profMove },
        source: pnl.stamp,
      });
    } else {
      out.push(missing("revenue", "Net sales", "volume", "profit", pnl.stamp), missing("gm", "Gross margin", "margin", "profit", pnl.stamp, "pct", "bps"), missing("profit", "Store contribution", "margin", "profit", pnl.stamp));
    }

    /* Creditors */
    if (cred.ok) {
      const s = cred.data;
      const credit = n(s.credit_outstanding);
      const share = credit ? (n(s.past_due_credit) * 100) / credit : 0;
      out.push({
        id: "creditors", label: "Creditors", value: { value: rupToCr(s.credit_outstanding) }, unit: "cr", comparisonLabel: "No prior snapshot",
        movement: na("No prior-period creditors snapshot is served, so no movement is shown."), movementUnit: "cr",
        status: `Past due ${fmtCr(rupToCr(s.past_due_credit))} · ${pct1(share)} of credit`, tone: share >= 60 ? "bad" : share >= 30 ? "warn" : "neutral", family: "payables", heroTab: "workingCapital",
        origin: { source: "pulse", scope: "pulse", id: "creditors", label: "Creditors", family: "payables", amount: rupToCr(s.credit_outstanding), variance: null },
        target: { age: "all" }, source: cred.stamp,
      });
    } else out.push(missing("creditors", "Creditors", "payables", "workingCapital", cred.stamp));

    /* No source: honest placeholders */
    const advances = cash.ok ? cash.data.unavailable.find((u) => u.id === "vendor_advances")?.reason : undefined;
    out.push({
      id: "advances", label: "Vendor advances", value: na(advances ?? "No source has been identified for vendor advances."), unit: "cr", comparisonLabel: "",
      movement: na("Not available"), movementUnit: "cr", status: advances ?? "No source has been identified", tone: "neutral", family: "advances", heroTab: "workingCapital",
      origin: { source: "pulse", scope: "pulse", id: "advances", label: "Vendor advances", family: "advances", amount: null, variance: null },
    });
    out.push({
      id: "unreconciled", label: "Unreconciled", value: na(NO_RECON), unit: "cr", comparisonLabel: "",
      movement: na("Not available"), movementUnit: "cr", status: NO_RECON, tone: "neutral", family: "recon", heroTab: "profit",
      origin: { source: "pulse", scope: "pulse", id: "unreconciled", label: "Unreconciled", family: "recon", amount: null, variance: null },
    });

    // keep the page's fixed order
    const order = ["cash", "revenue", "gm", "profit", "creditors", "advances", "unreconciled"];
    out.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    return ok(out, oldest(stamps));
  }

  function missing(id: PulseMetric["id"], label: string, family: Family, heroTab: HeroTab, source: SourceStamp, unit: "cr" | "pct" = "cr", mu: "cr" | "bps" = "cr"): PulseMetric {
    const reason = `${source.label} source could not be read: ${source.reason ?? "unavailable"}`;
    return {
      id, label, value: na(reason), unit, comparisonLabel: "", movement: na(reason), movementUnit: mu, status: reason, tone: "neutral", family, heroTab,
      origin: { source: "pulse", scope: "pulse", id, label, family, amount: null, variance: null }, source,
    };
  }

  /* ───────────── bridges ───────────── */

  async function getBridge(ctx: QueryCtx, tab: HeroTab): Promise<Envelope<Bridge>> {
    if (tab === "cash") {
      const cash = await readCash();
      return unavailable(NO_CASH_MOVEMENT, cash.stamp.asOf ?? undefined);
    }
    if (tab === "workingCapital") {
      const cred = await readCred();
      if (!cred.ok) throw new ApiError(`The Creditors source could not be read: ${cred.error}`, 502);
      const s = cred.data;
      const credit = n(s.credit_outstanding);
      const past = n(s.past_due_credit);
      const noDue = n(s.due_unavailable_credit);
      const notYet = credit - past - noDue;
      const debit = n(s.creditor_debit_balance);
      const items: BridgeItem[] = [
        { id: "not_yet_due", label: "Not yet due", kind: "delta", value: r2(notYet / CR), tone: "neutral", family: "payables" },
        { id: "past_due", label: "Past due", kind: "delta", value: r2(past / CR), tone: "bad", family: "payables" },
        { id: "due_unavailable", label: "Due date missing", kind: "delta", value: r2(noDue / CR), tone: "warn", family: "payables" },
        { id: "credit_outstanding", label: "Credit outstanding", kind: "total", value: r2(credit / CR), tone: "neutral", family: "payables" },
        { id: "debit_balances", label: "Vendor debit balances", kind: "delta", value: -r2(debit / CR), tone: "good", family: "payables" },
        { id: "net_payable", label: "Net payable", kind: "total", value: r2((credit - debit) / CR), tone: "neutral", family: "payables" },
      ];
      return ok(
        {
          id: "workingCapital",
          title: "What do we owe vendors, and how much is overdue?",
          subtitle: `Creditors only · ${stampText(cred.stamp)} · inventory, receivables and vendor advances are not available`,
          unitNote: "₹ Cr · a position, not a movement: no prior-period creditors snapshot is served. Inventory, receivables and vendor advances have no source and are not shown.",
          items,
          readout: { label: "Net payable", value: fmtCr(r2((credit - debit) / CR)), note: "credit outstanding less vendor debit balances" },
          sources: [cred.stamp],
        },
        cred.stamp.asOf ?? oldest([cred.stamp]),
      );
    }
    const pnl = await readPnl(ctx.period);
    if (!pnl.ok) throw new ApiError(`The P&L source could not be read: ${pnl.error}`, 502);
    const s = pnl.data;
    const t = s.totals;
    const items: BridgeItem[] = [
      { id: "net_sales", label: "Net sales", kind: "total", value: r2(rupToCr(t.revenue) ?? 0), tone: "neutral", family: "volume" },
      { id: "cogs", label: "COGS", kind: "delta", value: -r2(rupToCr(t.cogs) ?? 0), tone: "bad", family: "margin" },
      { id: "cogs_books", label: "Other COGS (books)", kind: "delta", value: r2(rupToCr(t.cogs_books) ?? 0), tone: toneOf(n(t.cogs_books)), family: "margin" },
      { id: "gross_margin", label: "Gross margin", kind: "total", value: r2(rupToCr(t.gross_margin) ?? 0), tone: "neutral", family: "margin" },
      { id: "store_opex", label: "Store opex", kind: "delta", value: r2(rupToCr(t.opex) ?? 0), tone: "bad", family: "cost" },
      { id: "contribution", label: "Contribution", kind: "total", value: r2(rupToCr(t.contribution) ?? 0), tone: "neutral", family: "margin" },
    ];
    return ok(
      {
        id: "profit",
        title: "How does net sales become store contribution?",
        subtitle: `${monthsText(s.scope.from_month, s.scope.to_month)}${s.scope.partial_last_month ? " (last month partial)" : ""} · ${stampText(pnl.stamp)}`,
        unitNote: `₹ Cr · real P&L, ${s.scope.basis_label.toLowerCase()}. A composition, not a variance bridge: ${s.flags.contribution_definition} Budget: not available.`,
        items,
        readout: { label: "Contribution margin", value: t.contribution_pct === null ? DASH : pct1(n(t.contribution_pct)), note: "of net sales, before other income, finance cost and head office" },
        sources: [pnl.stamp],
      },
      pnl.stamp.asOf ?? oldest([pnl.stamp]),
    );
  }

  /* ───────────── liquidity / working capital ───────────── */

  async function getLiquidity(ctx: QueryCtx, _horizon: Horizon): Promise<Envelope<LiquiditySummary>> {
    const cash = await readCash();
    if (!cash.ok) throw new ApiError(`The Cash source could not be read: ${cash.error}`, 502);
    const t = cash.data.till;
    const till = rupToCr(t.store_till_cash);
    const fc = cash.data.unavailable.find((u) => u.id === "cash_forecast")?.reason ?? NO_FORECAST;
    void ctx;
    return ok(
      {
        currentCash: { value: till, reason: "Store till cash only: it excludes bank balances and is not the company's cash." },
        projectedCash: na(fc),
        operatingMinimum: null,
        expectedInflows: na("No inflow forecast or receivables source exists."),
        upcomingObligations: na("No dated obligations schedule is served for this horizon. See Creditors for what is owed and past due."),
        breachDay: null,
        series: [],
        headline: `Store till cash is ${fmtCr(till)} across ${t.stores} stores (as of ${fmtDate(cash.data.till_balance_date)}). Company cash is not shown: ${NO_RECON}`,
        tone: "neutral",
        sources: [cash.stamp],
      },
      cash.stamp.asOf ?? oldest([cash.stamp]),
    );
  }

  async function getWorkingCapital(_ctx: QueryCtx): Promise<Envelope<WorkingCapitalSummary>> {
    const [cred, cash] = await Promise.all([readCred(), readCash()]);
    if (!cred.ok && !cash.ok) throw allDown([cred, cash]);
    const why = (id: string, fallback: string) => (cash.ok ? cash.data.unavailable.find((u) => u.id === id)?.reason : undefined) ?? fallback;
    const rows: WorkingCapitalLine[] = [];
    if (cred.ok) {
      rows.push({
        id: "creditors", label: "Creditors", cashImpact: null, balance: { value: rupToCr(cred.data.credit_outstanding) }, direction: "absorbed", tone: "neutral",
        note: `owed to vendors; ${fmtCr(rupToCr(cred.data.past_due_credit))} past due. Movement needs a prior-period snapshot`, family: "payables",
      });
    } else rows.push({ id: "creditors", label: "Creditors", cashImpact: null, balance: na(`Creditors source could not be read: ${cred.error}`), direction: "absorbed", tone: "neutral", note: "source could not be read", family: "payables" });
    const gap = (id: string, label: string, family: Family, reason: string) =>
      rows.push({ id, label, cashImpact: null, balance: na(reason), direction: "absorbed", tone: "neutral", note: reason, family });
    gap("inventory", "Inventory", "volume", why("inventory", "No credible current stock valuation source was found."));
    gap("receivables", "Receivables", "cash", why("receivables", "No receivables source is connected yet."));
    gap("vendor_advances", "Vendor advances", "advances", why("vendor_advances", "No source has been identified."));
    return ok(
      {
        rows,
        netCashImpact: null,
        headline: "Only the creditors balance has a real source. Cash absorbed or released is not shown: it needs a prior-period snapshot, and inventory, receivables and vendor advances have no source.",
        sources: [cred.stamp, cash.stamp],
      },
      oldest([cred.stamp, cash.stamp]),
    );
  }

  /* ───────────── risks and actions: derived only from real facts ───────────── */

  const sevOfPastDue = (share: number): LiveSeverity => (share >= 60 ? "high" : share >= 30 ? "medium" : "low");
  const sevOfGm = (bps: number): LiveSeverity => (bps <= -100 ? "high" : bps < 0 ? "medium" : "low");

  async function getRisks(ctx: QueryCtx): Promise<Envelope<RiskPillar[]>> {
    const { pnl, cash, cred, stamps } = await all(ctx);
    if (!pnl.ok && !cash.ok && !cred.ok) throw allDown([pnl, cash, cred]);
    const o = (id: string, label: string, family: Family, amount: number | null): DrillOrigin => ({ source: "risk", scope: "risk", id, label, family, amount, variance: null });
    const pillars: RiskPillar[] = [];

    /* liquidity */
    if (cash.ok) {
      const t = cash.data.till;
      pillars.push({
        id: "liquidity", label: "Liquidity", exposure: { value: rupToCr(t.store_till_cash), reason: "Store till cash only; excludes bank balances" }, movement: na("No prior till snapshot"),
        severity: t.stores_negative > 0 ? "medium" : "unrated", exposureLabel: "Store till cash, excl. bank", diagnosticLabel: "Stores with negative till", diagnosticValue: `${t.stores_negative} of ${t.stores}`,
        family: "cash", origin: o("liquidity", "Liquidity", "cash", rupToCr(t.store_till_cash)), source: cash.stamp,
      });
    } else pillars.push(missingRisk("liquidity", "Liquidity", "cash", cash.stamp));

    /* gross margin */
    if (pnl.ok) {
      const s = pnl.data;
      const { ly } = lastYear({ ...ctx, comparison: "ly" }, s);
      const cur = ly?.current?.gross_margin_pct;
      const prev = ly?.last_year?.gross_margin_pct;
      const bps = cur && prev ? Math.round((n(cur) - n(prev)) * 100) : null;
      pillars.push({
        id: "gm", label: "Gross margin", exposure: na("No budget or margin-at-risk estimate exists, so no financial impact is stated."),
        movement: bps === null ? na("No comparable last-year margin") : { value: bps, reason: "vs last year, complete months" }, severity: bps === null ? "unrated" : sevOfGm(bps),
        diagnosticLabel: "Gross margin", diagnosticValue: s.totals.gross_margin_pct === null ? DASH : pct1(n(s.totals.gross_margin_pct)),
        family: "margin", origin: o("gm", "Gross margin", "margin", rupToCr(s.totals.gross_margin)), source: pnl.stamp,
      });
    } else pillars.push(missingRisk("gm", "Gross margin", "margin", pnl.stamp));

    /* payables */
    if (cred.ok) {
      const s = cred.data;
      const credit = n(s.credit_outstanding);
      const share = credit ? (n(s.past_due_credit) * 100) / credit : 0;
      pillars.push({
        id: "payables", label: "Payables", exposure: { value: rupToCr(s.over_180_credit) }, movement: na("No prior-period creditors snapshot"),
        severity: credit ? sevOfPastDue(share) : "unrated", diagnosticLabel: "Past due", diagnosticValue: `${fmtCr(rupToCr(s.past_due_credit))} · ${pct1(share)}`,
        family: "payables", origin: o("payables", "Payables", "payables", rupToCr(s.over_180_credit)), target: { age: "gt180" }, source: cred.stamp,
      });
    } else pillars.push(missingRisk("payables", "Payables", "payables", cred.stamp));

    /* advances: no source */
    const adv = cash.ok ? cash.data.unavailable.find((u) => u.id === "vendor_advances")?.reason : undefined;
    pillars.push({
      id: "advances", label: "Vendor advances", exposure: na(adv ?? "No source has been identified for vendor advances."), movement: na("Not available"), severity: "unrated",
      diagnosticLabel: "Source", diagnosticValue: "None identified", family: "advances", origin: o("advances", "Vendor advances", "advances", null),
    });

    /* recon: unmapped P&L ledgers */
    if (pnl.ok) {
      const u = pnl.data.excluded_unmapped;
      pillars.push({
        id: "recon", label: "Reconciliation", exposure: na("The unmapped ledgers are mainly purchases and stock transfers that reach the P&L through COGS, so no single exposure amount is stated."),
        movement: na("Not available"), severity: u.ledgers > 0 ? "medium" : "low", diagnosticLabel: "P&L ledgers needing mapping", diagnosticValue: `${u.ledgers} of ${u.run_ledgers}`,
        family: "recon", origin: o("recon", "Reconciliation", "recon", null), source: pnl.stamp,
      });
    } else pillars.push(missingRisk("recon", "Reconciliation", "recon", pnl.stamp));
    return ok(pillars, oldest(stamps));
  }

  function missingRisk(id: RiskPillar["id"], label: string, family: Family, source: SourceStamp): RiskPillar {
    const reason = `${source.label} source could not be read: ${source.reason ?? "unavailable"}`;
    return {
      id, label, exposure: na(reason), movement: na(reason), severity: "unrated", diagnosticLabel: "Source", diagnosticValue: "Not read", family,
      origin: { source: "risk", scope: "risk", id, label, family, amount: null, variance: null }, source,
    };
  }

  async function getActions(ctx: QueryCtx): Promise<Envelope<CfoAction[]>> {
    const { pnl, cash, cred, stamps } = await all(ctx);
    if (!pnl.ok && !cash.ok && !cred.ok) throw allDown([pnl, cash, cred]);
    const out: CfoAction[] = [];
    const ev = (s: SourceStamp, field: string) => `${s.label} · ${s.runId} · as of ${s.asOf ? fmtDate(s.asOf) : DASH} · ${field}`;
    const origin = (id: string, label: string, family: Family, amount: number | null): DrillOrigin => ({ source: "action", scope: "action", id, label, family, amount, variance: null });

    if (cred.ok) {
      const s = cred.data;
      const credit = n(s.credit_outstanding);
      const share = credit ? (n(s.past_due_credit) * 100) / credit : 0;
      const cc = s.credit_concentration;
      if (n(s.past_due_credit) > 0) {
        out.push({
          id: "past_due", problem: `${fmtCr(rupToCr(s.past_due_credit))} of vendor credit is past due`, amount: { value: rupToCr(s.past_due_credit) },
          driver: `${s.past_due_items.toLocaleString("en-IN")} past-due items · ${pct1(share)} of ${fmtCr(rupToCr(s.credit_outstanding))} credit outstanding`,
          concentration: `Top 10 vendors hold ${pct1(n(cc.top_10) * 100)} of all credit; the largest holds ${pct1(n(cc.top_1) * 100)}`,
          age: `Over 90 days ${fmtCr(rupToCr(s.over_90_credit))} · over 180 days ${fmtCr(rupToCr(s.over_180_credit))}`,
          cta: "Open Creditors", severity: sevOfPastDue(share), family: "payables", origin: origin("past_due", "Past-due creditors", "payables", rupToCr(s.past_due_credit)),
          target: { age: "past_due" }, evidence: ev(cred.stamp, "past_due_credit, past_due_items, credit_concentration"),
        });
      }
      if (n(s.due_unavailable_credit) > 0) {
        out.push({
          id: "due_missing", problem: `${fmtCr(rupToCr(s.due_unavailable_credit))} of vendor credit has no usable due date`, amount: { value: rupToCr(s.due_unavailable_credit) },
          driver: `${s.due_unavailable_items.toLocaleString("en-IN")} items cannot be classed as due or not due, so they are not in the past-due figure`,
          concentration: `${pct1(credit ? (n(s.due_unavailable_credit) * 100) / credit : 0)} of credit outstanding`, age: "Age by document date is available in the Creditors ageing view",
          cta: "Review in Creditors", severity: "medium", family: "payables", origin: origin("due_missing", "Due date missing", "payables", rupToCr(s.due_unavailable_credit)),
          target: { age: "due_unavailable" }, evidence: ev(cred.stamp, "due_unavailable_credit, due_unavailable_items"),
        });
      }
    }

    if (pnl.ok) {
      const u = pnl.data.excluded_unmapped;
      if (u.ledgers > 0) {
        out.push({
          id: "unmapped_ledgers", problem: `${u.ledgers} P&L ledgers need Finance mapping`, amount: na("No amount is stated: the unmapped ledgers are mainly purchases and stock transfers that reach the P&L through COGS."),
          driver: `${u.ledgers} of ${u.run_ledgers} ledgers in the run are outside every P&L total until Finance assigns a group; none is assigned automatically`,
          concentration: "Largest ledgers are listed in the drill", age: `Run ${pnl.stamp.runId}`, cta: "Review ledgers", severity: "medium", family: "recon",
          origin: origin("unmapped_ledgers", "Unmapped P&L ledgers", "recon", null), evidence: ev(pnl.stamp, "excluded_unmapped"),
        });
      }
      const { ly } = lastYear({ ...ctx, comparison: "ly" }, pnl.data);
      const cur = ly?.current?.gross_margin_pct;
      const prev = ly?.last_year?.gross_margin_pct;
      const bps = cur && prev ? Math.round((n(cur) - n(prev)) * 100) : null;
      if (bps !== null && bps < 0 && ly?.current) {
        out.push({
          id: "gm_decline", problem: `Gross margin is ${Math.abs(bps)} bps below last year`, amount: { value: rupToCr(pnl.data.totals.gross_margin) },
          driver: `${pct1(n(cur))} against ${pct1(n(prev))} over ${monthsText(ly.period.from_month, ly.period.to_month)} (complete months); amount shown is gross margin to date`,
          concentration: "Store-level margins are on the Profitability page", age: `Run ${pnl.stamp.runId}`, cta: "Open drill", severity: sevOfGm(bps), family: "margin",
          origin: origin("gm_decline", "Gross margin vs last year", "margin", rupToCr(pnl.data.totals.gross_margin)), evidence: ev(pnl.stamp, "comparison.current / last_year gross_margin_pct"),
        });
      }
    }

    if (cash.ok && cash.data.till.stores_negative > 0) {
      let neg = 0;
      let cnt = cash.data.till.stores_negative;
      try {
        const page = await c.cash.stores(cash.stamp.runId as string, { sort: "cumulative_balance", order: "asc", limit: 100 });
        const negs = page.stores.filter((x) => n(x.cumulative_balance) < 0);
        neg = negs.reduce((a, x) => a + n(x.cumulative_balance), 0);
        cnt = Math.max(cnt, negs.length);
      } catch {
        /* amount stays unknown below */
      }
      out.push({
        id: "negative_till", problem: `${cnt} store${cnt === 1 ? "" : "s"} carry a negative till balance`, amount: neg < 0 ? { value: rupToCr(neg) } : na("The negative balances could not be summed."),
        driver: "A till cannot hold less than nothing: these balances need a posting check", concentration: `${cnt} of ${cash.data.till.stores} stores`,
        age: `Till balances as of ${fmtDate(cash.data.till_balance_date)}`, cta: "Open drill", severity: "medium", family: "cash",
        origin: origin("negative_till", "Negative till balances", "cash", neg < 0 ? rupToCr(neg) : null), evidence: ev(cash.stamp, "till.stores_negative"),
      });
    }

    const rank: Record<LiveSeverity, number> = { critical: 0, high: 1, medium: 2, low: 3, unrated: 4 };
    out.sort((a, b) => rank[a.severity] - rank[b.severity]);
    if (!out.length) return { status: "empty", reason: "No action is derived from the real facts read.", asOf: oldest(stamps) };
    return ok(out, oldest(stamps));
  }

  async function getForecast(_ctx: QueryCtx): Promise<Envelope<ForecastTrajectory>> {
    return unavailable(`${NO_FORECAST} ${NO_BUDGET}`);
  }

  async function getFreshness(ctx: QueryCtx): Promise<FreshnessInfo> {
    const { stamps } = await all(ctx);
    const asOfs = stamps.filter((s) => s.ok && s.asOf).map((s) => `${s.label} ${fmtDate(s.asOf as string)}`);
    const down = stamps.filter((s) => !s.ok).map((s) => s.label);
    return {
      asOf: oldest(stamps),
      stale: down.length > 0,
      label: `Real data, per source: ${asOfs.join(" · ") || "no source read"}${down.length ? ` · not read: ${down.join(", ")}` : ""}`,
      sources: stamps,
    };
  }

  /* ───────────── drill: real splits from the live sources ───────────── */

  type Key = "sales" | "gm" | "contribution" | "cogs" | "opex" | "unmapped" | "till" | "creditors" | "negtill";
  const KEY_OF: Record<string, Key> = {
    "pulse:revenue": "sales", "hero:profit:net_sales": "sales",
    "pulse:gm": "gm", "hero:profit:gross_margin": "gm", "risk:gm": "gm", "action:gm_decline": "gm",
    "pulse:profit": "contribution", "hero:profit:contribution": "contribution",
    "hero:profit:cogs": "cogs", "hero:profit:cogs_books": "cogs",
    "hero:profit:store_opex": "opex",
    "risk:recon": "unmapped", "action:unmapped_ledgers": "unmapped",
    "pulse:cash": "till", "liquidity:current": "till", "risk:liquidity": "till", "action:negative_till": "negtill",
    "pulse:creditors": "creditors", "risk:payables": "creditors", "action:past_due": "creditors", "action:due_missing": "creditors", "wc:creditors": "creditors",
  };
  const keyOf = (o: DrillOrigin): Key | null => {
    const scope = o.scope ?? o.source;
    const direct = KEY_OF[`${scope}:${o.id}`];
    if (direct) return direct;
    if (scope === "hero:workingCapital") return "creditors";
    return null;
  };

  const credLinks = (age?: DrillLink["age"]): DrillLink[] => [{ label: age && age !== "all" ? "Open Creditors with this filter" : "Open Creditors", room: "creditors", age }];
  const PROFIT_LINK: DrillLink[] = [{ label: "Open Profitability (store P&L, ledgers)", room: "profitability" }];
  const CASH_LINK: DrillLink[] = [{ label: "Open Liquidity & Working Capital", room: "cashroom" }];

  const node = (dim: string, id: string, label: string, amount: number | null, level: DrillNode["level"] = "entity"): DrillNode => ({ level, dim, id: `${dim}:${id}`, label, amount, variance: null });
  const row = (dim: string, id: string, label: string, amount: number, total: number, extra: Partial<DrillRow> = {}): DrillRow => ({
    node: node(dim, id, label, amount), amount, share: total ? Math.min(1, Math.abs(amount) / Math.abs(total)) : 0, delta: amount, tone: "neutral", ...extra,
  });
  /** keeps the visible rows reconciling to the parent: the rest is stated as "other" */
  function topRows(rows: DrillRow[], total: number, max = 10) {
    const sorted = [...rows].sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));
    const shown = sorted.slice(0, max);
    const rest = sorted.slice(max);
    const restAmt = r2(total - shown.reduce((a, r) => a + r.amount, 0));
    return { rows: shown, other: rest.length ? { count: rest.length, amount: restAmt, delta: restAmt } : undefined };
  }
  const blank = (v: Partial<DrillView> & Pick<DrillView, "title" | "levelLabel" | "amount" | "explanation">): DrillView => ({
    variance: null, variancePct: null, comparisonLabel: "", tone: "neutral", concentration: { headline: "", topShares: [] }, splits: [], supportingDrivers: [], terminal: false, entityKind: "other", facts: [], ...v,
  });

  async function getDrillView(ctx: QueryCtx, origin: DrillOrigin, nodes: DrillNode[]): Promise<Envelope<DrillView>> {
    // the three live pages own their drawers; they keep their existing behaviour
    if (origin.scope === "creditors" || origin.scope === "profitability" || origin.scope === "cashroom") return rooms.getDrillView(ctx, origin, nodes);
    const key = keyOf(origin);
    if (!key) {
      const why =
        origin.family === "advances" ? "No source has been identified for vendor advances."
        : origin.id === "unreconciled" ? "No bank statement or reconciliation is available from the current sources."
        : origin.scope === "liquidity" ? `${NO_FORECAST} ${NO_CASH_MOVEMENT}`
        : origin.scope === "wc" ? "This working-capital line has no real source yet."
        : origin.scope === "forecast" ? NO_FORECAST
        : "No real source backs this drill.";
      return unavailable(why);
    }
    const last = nodes[nodes.length - 1];
    switch (key) {
      case "sales":
      case "gm":
      case "contribution":
      case "cogs":
      case "opex":
        return pnlDrill(ctx, key, origin, last);
      case "unmapped":
        return unmappedDrill(ctx, origin, last);
      case "till":
      case "negtill":
        return tillDrill(key, origin, last);
      case "creditors":
        return credDrill(origin, last);
    }
  }

  async function pnlDrill(ctx: QueryCtx, key: Key, origin: DrillOrigin, last?: DrillNode): Promise<Envelope<DrillView>> {
    const pnl = await readPnl(ctx.period);
    if (!pnl.ok) throw new ApiError(`The P&L source could not be read: ${pnl.error}`, 502);
    const s = pnl.data;
    const t = s.totals;
    const sales = rupToCr(t.revenue) ?? 0;
    const sources = [pnl.stamp];
    const span = monthsText(s.scope.from_month, s.scope.to_month);
    const base = { sources, links: PROFIT_LINK, comparisonLabel: "" };
    const asOf = pnl.stamp.asOf ?? oldest([pnl.stamp]);

    if (last) {
      // second level: one expense group, one store, or one component
      if (last.dim === "Expense group") {
        const line = s.lines.find((l) => l.section === "STORE_OPEX" && l.group_label === last.id.slice("Expense group:".length));
        if (!line) return unavailable("That expense group is no longer in the run.", asOf);
        const amt = Math.abs(rupToCr(line.amount) ?? 0);
        return ok(blank({ ...base, title: line.group_label, levelLabel: "Expense group", amount: -amt, explanation: `${span}. This group is ${pct1((amt * 100) / sales)} of net sales. Ledger-level detail is on the Profitability page.`, terminal: true, entityKind: "account", facts: [{ label: "Amount", value: fmtCr(-amt) }, { label: "Ledgers", value: String(line.ledgers) }, { label: "Share of net sales", value: pct1((amt * 100) / sales) }, { label: "Run", value: stampText(pnl.stamp) }] }), asOf);
      }
      if (last.dim === "Top store") {
        const page = await memo(`pnl:stores:${pnl.stamp.runId}:${ctx.period}`, () => c.pnl.stores(pnl.stamp.runId as string, { basis: "all", from_month: PERIOD_MONTHS[ctx.period][0], to_month: PERIOD_MONTHS[ctx.period][1] }, { sort: "revenue", order: "desc", limit: 10 }));
        const st = page.stores.find((x) => `Top store:${x.site_code}` === last.id);
        if (!st) return unavailable("That store is no longer in the top list.", asOf);
        return ok(blank({ ...base, title: st.store_name ?? `Site ${st.site_code}`, levelLabel: "Store", amount: rupToCr(st.revenue), explanation: `${span}. Net sales ex-GST for this store; open Profitability for the full store P&L.`, terminal: true, entityKind: "store", facts: storeFacts(st) }), asOf);
      }
      if (last.dim === "Component") {
        return ok(blank({ ...base, title: last.label, levelLabel: "Component", amount: last.amount, explanation: `${span}. ${last.label} as read from the P&L run; the bridge on the page shows how it feeds contribution.`, terminal: true, facts: [{ label: "Amount", value: fmtCr(last.amount) }, { label: "Run", value: stampText(pnl.stamp) }] }), asOf);
      }
      return unavailable("No further real breakdown exists for this selection.", asOf);
    }

    const comp = (id: string, label: string, amount: number) => row("Component", id, label, amount, sales);
    if (key === "sales") {
      const page = await memo(`pnl:stores:${pnl.stamp.runId}:${ctx.period}`, () => c.pnl.stores(pnl.stamp.runId as string, { basis: "all", from_month: PERIOD_MONTHS[ctx.period][0], to_month: PERIOD_MONTHS[ctx.period][1] }, { sort: "revenue", order: "desc", limit: 10 }));
      const rows = page.stores.map((st) => row("Top store", String(st.site_code), st.store_name ?? `Site ${st.site_code}`, rupToCr(st.revenue) ?? 0, sales, { sublabel: st.state ?? undefined }));
      const split = topRows(rows, sales, 10);
      const more = page.stores_total - rows.length;
      if (more > 0) {
        const amt = r2(sales - rows.reduce((a, r) => a + r.amount, 0));
        split.other = { count: more, amount: amt, delta: amt };
      }
      const topShare = rows.slice(0, 5).reduce((a, r) => a + r.amount, 0) / (sales || 1);
      return ok(blank({ ...base, title: "Net sales", levelLabel: "Real data · P&L", amount: sales, explanation: `${span}${s.scope.partial_last_month ? " (last month partial)" : ""}. Net sales ex-GST across ${s.stores_in_scope} stores, ${s.scope.basis_label.toLowerCase()}. Stores are ranked by net sales; the rest is stated as other.`, concentration: { headline: `Top 5 stores hold ${pct1(topShare * 100)} of net sales`, topShares: rows.slice(0, 5).map((r) => r.share) }, splits: [{ dim: "Top store", rows: split.rows, other: split.other }], facts: [{ label: "Stores in scope", value: String(s.stores_in_scope) }, { label: "Basis", value: s.scope.basis_label }, { label: "Run", value: stampText(pnl.stamp) }] }), asOf);
    }
    if (key === "cogs") {
      const rows = [comp("cogs", "COGS (COGS table)", rupToCr(t.cogs) ?? 0), comp("cogs_books", "Other COGS items (books)", rupToCr(t.cogs_books) ?? 0)];
      return ok(blank({ ...base, title: "Cost of goods sold", levelLabel: "Real data · P&L", amount: rupToCr(t.cogs), explanation: `${span}. COGS comes from the COGS table, which runs to ${fmtDate(s.flags.cogs_through)} while the books run to ${fmtDate(s.flags.books_through)}. ${s.flags.cogs_has_no_posting_status}`, splits: [{ dim: "Component", rows }], facts: [{ label: "COGS lags books", value: s.flags.cogs_lags_books ? "Yes" : "No" }, { label: "Run", value: stampText(pnl.stamp) }] }), asOf);
    }
    if (key === "opex") {
      const lines = s.lines.filter((l) => l.section === "STORE_OPEX");
      const total = Math.abs(rupToCr(t.opex) ?? 0);
      const rows = lines.map((l) => row("Expense group", l.group_label, l.group_label, Math.abs(rupToCr(l.amount) ?? 0), total, { sublabel: `${l.ledgers} ledger${l.ledgers === 1 ? "" : "s"}` }));
      const split = topRows(rows, total, 10);
      return ok(blank({ ...base, title: "Store operating expenses", levelLabel: "Real data · P&L", amount: rupToCr(t.opex), explanation: `${span}. Store operating expenses by group, ${t.opex_pct === null ? DASH : pct1(n(t.opex_pct))} of net sales. Group sizes are shown as positive costs.`, concentration: { headline: `Largest group: ${split.rows[0]?.node.label ?? DASH} at ${pct1((split.rows[0]?.share ?? 0) * 100)} of store opex`, topShares: split.rows.slice(0, 5).map((r) => r.share) }, splits: [{ dim: "Expense group", rows: split.rows, other: split.other }], facts: [{ label: "Groups", value: String(lines.length) }, { label: "Run", value: stampText(pnl.stamp) }] }), asOf);
    }
    if (key === "gm") {
      const rows = [comp("net_sales", "Net sales", sales), comp("cogs", "COGS", -(rupToCr(t.cogs) ?? 0)), comp("cogs_books", "Other COGS items (books)", rupToCr(t.cogs_books) ?? 0)];
      const { ly, label } = lastYear({ ...ctx, comparison: "ly" }, s);
      return ok(blank({ ...base, title: "Gross margin", levelLabel: "Real data · P&L", amount: rupToCr(t.gross_margin), explanation: `${span}. Gross margin is ${t.gross_margin_pct === null ? DASH : pct1(n(t.gross_margin_pct))} of net sales.${ly?.last_year ? ` Over complete months it was ${pct1(n(ly.current.gross_margin_pct))} against ${pct1(n(ly.last_year.gross_margin_pct))} last year.` : " No last-year comparison is available."} Budget is not available.`, splits: [{ dim: "Component", rows }], facts: [{ label: "Comparison", value: label }, { label: "Run", value: stampText(pnl.stamp) }] }), asOf);
    }
    // contribution
    const rows = [comp("gross_margin", "Gross margin", rupToCr(t.gross_margin) ?? 0), comp("store_opex", "Store operating expenses", rupToCr(t.opex) ?? 0)];
    return ok(blank({ ...base, title: "Store contribution", levelLabel: "Real data · P&L", amount: rupToCr(t.contribution), explanation: `${span}. ${s.flags.contribution_definition} Other income ${fmtCr(rupToCr(t.other_income))} and finance cost ${fmtCr(rupToCr(t.finance_cost))} sit below it.`, splits: [{ dim: "Component", rows }], facts: [{ label: "Contribution margin", value: t.contribution_pct === null ? DASH : pct1(n(t.contribution_pct)) }, { label: "After other income and finance cost", value: fmtCr(rupToCr(s.below_contribution.after_below_the_line)) }, { label: "Run", value: stampText(pnl.stamp) }] }), asOf);
  }

  const storeFacts = (st: PnlStoreRow) => [
    { label: "Net sales", value: fmtCr(rupToCr(st.revenue)) },
    { label: "Contribution", value: fmtCr(rupToCr(st.contribution)) },
    { label: "Region", value: st.region ?? DASH },
    { label: "State", value: st.state ?? DASH },
  ];

  async function unmappedDrill(ctx: QueryCtx, origin: DrillOrigin, last?: DrillNode): Promise<Envelope<DrillView>> {
    void origin;
    const pnl = await readPnl(ctx.period);
    if (!pnl.ok) throw new ApiError(`The P&L source could not be read: ${pnl.error}`, 502);
    const rec = await memo(`pnl:recon:${pnl.stamp.runId}:${ctx.period}`, () => c.pnl.reconciliation(pnl.stamp.runId as string, { basis: "all", from_month: PERIOD_MONTHS[ctx.period][0], to_month: PERIOD_MONTHS[ctx.period][1] }));
    const u = rec.excluded_unmapped;
    const asOf = pnl.stamp.asOf ?? oldest([pnl.stamp]);
    const gross = rupToCr(u.gross_abs) ?? 0;
    const base = { sources: [pnl.stamp], links: PROFIT_LINK, comparisonLabel: "" };
    if (last) {
      const l = u.ledgers.find((x) => `Ledger:${x.glcode}` === last.id);
      if (!l) return unavailable("That ledger is no longer in the run.", asOf);
      return ok(blank({ ...base, title: l.ledger_name, levelLabel: "Unmapped ledger", amount: rupToCr(l.net), explanation: "This ledger is outside every P&L total until Finance assigns it to a group. None is assigned automatically.", terminal: true, entityKind: "account", facts: [{ label: "Ledger code", value: l.glcode }, { label: "Net", value: fmtCr(rupToCr(l.net)) }, { label: "Debit", value: fmtCr(rupToCr(l.debit)) }, { label: "Credit", value: fmtCr(rupToCr(l.credit)) }, { label: "Sites", value: String(l.sites) }] }), asOf);
    }
    const rows = u.ledgers.map((l) => row("Ledger", l.glcode, l.ledger_name, Math.abs(rupToCr(l.net) ?? 0), gross, { sublabel: `${n(l.net) < 0 ? "net debit" : "net credit"} · ${l.sites} sites` }));
    const split = topRows(rows, gross, 10);
    return ok(blank({ ...base, title: "Unmapped P&L ledgers", levelLabel: "Real data · P&L", amount: null, explanation: `${u.count} of ${u.run_ledgers} ledgers in the run need Finance classification. ${u.explanation} Sizes below are absolute net movement per ledger; no single exposure is stated because purchases and stock transfers reach the P&L through COGS.`, splits: [{ dim: "Ledger", rows: split.rows, other: split.other }], facts: [{ label: "Ledgers needing mapping", value: String(u.count) }, { label: "Ledgers in run", value: String(u.run_ledgers) }, { label: "Run", value: stampText(pnl.stamp) }] }), asOf);
  }

  async function tillDrill(key: Key, origin: DrillOrigin, last?: DrillNode): Promise<Envelope<DrillView>> {
    const cash = await readCash();
    if (!cash.ok) throw new ApiError(`The Cash source could not be read: ${cash.error}`, 502);
    const t = cash.data.till;
    const runId = cash.stamp.runId as string;
    const asOf = cash.stamp.asOf ?? oldest([cash.stamp]);
    const total = rupToCr(t.store_till_cash) ?? 0;
    const base = { sources: [cash.stamp], links: CASH_LINK, comparisonLabel: "" };
    const stores = await memo(`cash:stores:${runId}:${key === "negtill" ? "asc" : "desc"}`, () => c.cash.stores(runId, { sort: "cumulative_balance", order: key === "negtill" ? "asc" : "desc", limit: key === "negtill" ? 100 : 10 }));
    const mk = (st: TillStore) => row("Top store", String(st.site_code), st.store_name ?? `Site ${st.site_code}`, rupToCr(st.cumulative_balance) ?? 0, total, { tone: n(st.cumulative_balance) < 0 ? "bad" : "neutral" });
    if (last) {
      const st = stores.stores.find((x) => `Top store:${x.site_code}` === last.id);
      if (!st) return unavailable("That store is not in the list read.", asOf);
      return ok(blank({ ...base, title: st.store_name ?? `Site ${st.site_code}`, levelLabel: "Store till", amount: rupToCr(st.cumulative_balance), explanation: "Cumulative store till balance. Bank balances are not included.", terminal: true, entityKind: "store", facts: [{ label: "Till balance", value: fmtCr(rupToCr(st.cumulative_balance)) }, { label: "FYTD debit", value: fmtCr(rupToCr(st.fytd_debit)) }, { label: "FYTD credit", value: fmtCr(rupToCr(st.fytd_credit)) }, { label: "Last activity", value: st.last_activity_date ? fmtDate(st.last_activity_date) : DASH }] }), asOf);
    }
    const rows = (key === "negtill" ? stores.stores.filter((x) => n(x.cumulative_balance) < 0) : stores.stores).map(mk);
    const split: { rows: DrillRow[]; other?: { count: number; amount: number; delta: number } } = key === "negtill" ? { rows } : topRows(rows, total, 10);
    if (key !== "negtill" && t.stores > rows.length) {
      const amt = r2(total - rows.reduce((a, r) => a + r.amount, 0));
      split.other = { count: t.stores - rows.length, amount: amt, delta: amt };
    }
    const bank = NO_RECON;
    return ok(blank({ ...base, title: key === "negtill" ? "Negative till balances" : "Store till cash", levelLabel: "Real data · Cash", amount: key === "negtill" ? origin.amount : total, explanation: `Cash held in store tills across ${t.stores} stores (${t.stores_with_cash} hold cash, ${t.stores_negative} negative). It is not the company's cash: ${bank}`, splits: rows.length ? [{ dim: "Top store", rows: split.rows, other: split.other }] : [], facts: [{ label: "Stores", value: String(t.stores) }, { label: "Last till activity", value: t.last_activity_date ? fmtDate(t.last_activity_date) : DASH }, { label: "Largest store", value: t.largest_store ? `${t.largest_store.store_name ?? t.largest_store.site_code} · ${fmtCr(rupToCr(t.largest_store.cumulative_balance))}` : DASH }, { label: "Run", value: stampText(cash.stamp) }] }), asOf);
  }

  async function credDrill(origin: DrillOrigin, last?: DrillNode): Promise<Envelope<DrillView>> {
    const cred = await readCred();
    if (!cred.ok) throw new ApiError(`The Creditors source could not be read: ${cred.error}`, 502);
    const s = cred.data;
    const asOf = cred.stamp.asOf ?? oldest([cred.stamp]);
    const credit = rupToCr(s.credit_outstanding) ?? 0;
    const base = { sources: [cred.stamp], comparisonLabel: "" };
    const status = [
      { id: "past_due", label: "Past due", amount: rupToCr(s.past_due_credit) ?? 0, tone: "bad" as Tone, items: s.past_due_items },
      { id: "due_unavailable", label: "Due date missing", amount: rupToCr(s.due_unavailable_credit) ?? 0, tone: "warn" as Tone, items: s.due_unavailable_items },
    ];
    const notYet = r2(credit - status[0].amount - status[1].amount);
    if (last) {
      if (last.dim === "Due status") {
        const id = last.id.slice("Due status:".length);
        const amount = id === "not_yet_due" ? notYet : status.find((x) => x.id === id)?.amount ?? 0;
        return ok(blank({ ...base, links: credLinks(id as DrillLink["age"]), title: last.label, levelLabel: "Due status", amount, explanation: `Vendor credit in this due status, ${pct1(credit ? (amount * 100) / credit : 0)} of ${fmtCr(credit)} credit outstanding. Vendors and items are on the Creditors page.`, terminal: true, facts: [{ label: "Amount", value: fmtCr(amount) }, { label: "Share of credit", value: pct1(credit ? (amount * 100) / credit : 0) }, { label: "Run", value: stampText(cred.stamp) }] }), asOf);
      }
      if (last.dim === "Ledger") {
        const lg = (await memo(`cred:ledgers:${cred.stamp.runId}`, () => c.creditors.ledgers(cred.stamp.runId as string))).find((x) => `Ledger:${x.ledger_code}` === last.id);
        if (!lg) return unavailable("That ledger is not in the run.", asOf);
        return ok(blank({ ...base, links: credLinks("all"), title: lg.ledger_name, levelLabel: "Creditor ledger", amount: rupToCr(lg.credit_outstanding), explanation: "Credit outstanding in this creditor ledger.", terminal: true, entityKind: "account", facts: [{ label: "Credit outstanding", value: fmtCr(rupToCr(lg.credit_outstanding)) }, { label: "Past due", value: fmtCr(rupToCr(lg.past_due_credit)) }, { label: "Due date missing", value: fmtCr(rupToCr(lg.due_unavailable_credit)) }, { label: "Credit vendors", value: String(lg.credit_vendors) }] }), asOf);
      }
      return unavailable("No further real breakdown exists for this selection.", asOf);
    }
    const focus = origin.id === "past_due" ? "past_due" : origin.id === "due_missing" || origin.id === "due_unavailable" ? "due_unavailable" : origin.id === "not_yet_due" ? "not_yet_due" : "all";
    const dueRows = [row("Due status", "not_yet_due", "Not yet due", notYet, credit), ...status.map((x) => row("Due status", x.id, x.label, x.amount, credit, { tone: x.tone, sublabel: `${x.items.toLocaleString("en-IN")} items` }))];
    const ledgers: LedgerRow[] = await memo(`cred:ledgers:${cred.stamp.runId}`, () => c.creditors.ledgers(cred.stamp.runId as string));
    const ledgerRows = ledgers.map((l) => row("Ledger", l.ledger_code, l.ledger_name, rupToCr(l.credit_outstanding) ?? 0, credit, { sublabel: `${l.credit_vendors} vendors` }));
    const cc = s.credit_concentration;
    return ok(blank({ ...base, links: credLinks(focus as DrillLink["age"]), title: origin.label === "Creditors" ? "Creditors" : origin.label, levelLabel: "Real data · Creditors", amount: origin.amount ?? credit, explanation: `Vendor credit outstanding is ${fmtCr(credit)} across ${s.credit_vendors.toLocaleString("en-IN")} vendors; ${fmtCr(rupToCr(s.past_due_credit))} is past due and ${fmtCr(rupToCr(s.due_unavailable_credit))} has no usable due date. A snapshot: no prior-period creditors data is served.`, concentration: { headline: `Top 10 vendors hold ${pct1(n(cc.top_10) * 100)} of credit; the largest holds ${pct1(n(cc.top_1) * 100)}`, topShares: [n(cc.top_1), n(cc.top_5) - n(cc.top_1), n(cc.top_10) - n(cc.top_5)] }, splits: [{ dim: "Due status", rows: dueRows }, { dim: "Ledger", rows: ledgerRows }], facts: [{ label: "Credit items", value: s.credit_items.toLocaleString("en-IN") }, { label: "Vendor debit balances", value: fmtCr(rupToCr(s.creditor_debit_balance)) }, { label: "Run", value: stampText(cred.stamp) }] }), asOf);
  }

  /* deep pages: the Command Center has no real ledger / voucher / profile source */
  const NO_DEEP = "Ledger, voucher and profile detail are not connected to a real source from the Command Center. Use the Profitability, Liquidity or Creditors pages, which read the verified sources.";
  const roomScope = (o: DrillOrigin) => o.scope === "creditors" || o.scope === "profitability" || o.scope === "cashroom";

  return {
    getFreshness,
    getPulse,
    getBridge,
    getLiquidity,
    getWorkingCapital,
    getRisks,
    getActions,
    getForecast,
    getDrillView,
    getLedger: (ctx, origin, nodes): Promise<Envelope<LedgerView>> => (roomScope(origin) ? rooms.getLedger(ctx, origin, nodes) : Promise.resolve(unavailable(NO_DEEP))),
    // a voucher is only reachable from a room's ledger, never from a Command Center drill
    getVoucher: (ctx, voucherId, amount): Promise<Envelope<VoucherEvidence>> => rooms.getVoucher(ctx, voucherId, amount),
    getEntityProfile: (ctx, origin, nodes): Promise<Envelope<EntityProfile>> => (roomScope(origin) ? rooms.getEntityProfile(ctx, origin, nodes) : Promise.resolve(unavailable(NO_DEEP))),
    // room-level data of the demo workspaces: unchanged
    getCreditors: rooms.getCreditors,
    getAgeingMigration: rooms.getAgeingMigration,
    getVendorConcentration: rooms.getVendorConcentration,
    getAbnormalBalances: rooms.getAbnormalBalances,
    getVendorProfile: rooms.getVendorProfile,
    getProfitPortfolio: rooms.getProfitPortfolio,
    getStoreWorkspace: rooms.getStoreWorkspace,
    getCashRoom: rooms.getCashRoom,
  };
}
