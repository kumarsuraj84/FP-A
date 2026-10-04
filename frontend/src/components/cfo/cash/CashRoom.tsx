import { Area, CartesianGrid, ComposedChart, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowRight, TrendingDown } from "lucide-react";
import { useCashRoom } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { cashKeyOf, cashNode, isCashKey } from "@/lib/cashNodes";
import { DASH, fmtCr } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { BridgeItem, Horizon } from "@/types/cfo";
import type { CashObligation, CashRoom as CashRoomData, WcDriver } from "@/types/cash";
import { Boundary, Metric, Skeleton, StaleChip, toneClass } from "../common";
import { Chip, Panel, StripCell, WorkspaceHeader, deltaCr } from "../panels";
import { WaterfallChart } from "../WaterfallChart";

const HORIZONS: { id: Horizon; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "7d", label: "7 Days" },
  { id: "15d", label: "15 Days" },
  { id: "30d", label: "30 Days" },
];
const AXIS = { fontSize: 10.5, fill: "oklch(0.5 0.02 260)" };

function Strip({ room, horizon, onHorizon }: { room: CashRoomData; horizon: Horizon; onHorizon: (h: Horizon) => void }) {
  return (
    <div className="grid grid-cols-5 divide-x border-b bg-card @max-[1100px]:grid-cols-3 @max-[1100px]:divide-y" data-testid="cash-strip">
      {room.steps.map((s) => (
        <StripCell
          key={s.horizon}
          testId={`step-${s.horizon}`}
          label={s.horizon === "today" ? "Cash today" : `Cash in ${s.label}`}
          value={fmtCr(s.closing)}
          variance={s.headroom < 0 ? `${fmtCr(-s.headroom)} below minimum` : `${fmtCr(s.headroom)} above minimum`}
          tone={s.headroom < 0 ? "bad" : s.headroom < 8 ? "warn" : "good"}
          sub={s.dayLabel}
          pressed={horizon === s.horizon}
          onClick={() => onHorizon(s.horizon)}
        />
      ))}
      <StripCell testId="cash-minimum" label="Operating minimum" value={fmtCr(room.operatingMinimum)} sub="policy floor" />
    </div>
  );
}

function DecisionStrip({ room, onOpen }: { room: CashRoomData; onOpen: (key: string, label: string, amount: number | null) => void }) {
  const d = room.decision;
  const bridgeItem = (key: string) => room.bridge.items.find((i) => i.id === key);
  const driver = (key: string) => room.drivers.find((x) => x.id === key);
  const openKey = (key: string) => {
    const b = bridgeItem(key);
    const w = driver(key);
    if (b) onOpen(key, b.label, b.value);
    else if (w) onOpen(key, w.label, w.cashImpact);
  };
  return (
    <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_auto] divide-x rounded-md border bg-card shadow-elegant @max-[1100px]:grid-cols-2 @max-[1100px]:divide-y" data-testid="cash-decision">
      <div className="px-4 py-2.5" data-testid="decision-horizon">
        <div className="eyebrow">{d.horizonLabel}</div>
        <div className={cn("num-mono text-[14px] font-semibold", toneClass(d.tone))}>{d.horizonLine}</div>
      </div>
      <button data-testid="decision-absorption" disabled={!d.absorption} onClick={() => d.absorption && openKey(d.absorption.key)} className="press px-4 py-2.5 text-left hover:bg-[oklch(0.97_0.012_265)] disabled:cursor-default">
        <div className="eyebrow">Largest cash absorption</div>
        <div className="text-[14px] font-semibold">{d.absorption ? <>{d.absorption.label} <span className="num-mono tone-bad">{deltaCr(d.absorption.amount)}</span></> : "None in the period"}</div>
      </button>
      <button data-testid="decision-obligation" disabled={!d.obligation} onClick={() => d.obligation && openKey(d.obligation.key)} className="press px-4 py-2.5 text-left hover:bg-[oklch(0.97_0.012_265)] disabled:cursor-default">
        <div className="eyebrow">Largest upcoming obligation</div>
        <div className="text-[14px] font-semibold">{d.obligation ? <>{d.obligation.label} <span className="num-mono tone-bad">{fmtCr(-d.obligation.amount)}</span> <span className="font-normal text-muted-foreground">· {d.obligation.dayLabel}</span></> : "None in this horizon"}</div>
      </button>
      {d.action ? (
        <button data-testid="decision-action" onClick={() => openKey(d.action!.key)} className="press flex items-center gap-1.5 bg-primary px-4 py-2.5 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90">
          {d.action.text} <ArrowRight className="h-3.5 w-3.5" />
        </button>
      ) : (
        <div className="flex items-center px-4 text-[12px] text-muted-foreground">No action needed</div>
      )}
    </div>
  );
}

function Trajectory({ room, onOpen }: { room: CashRoomData; onOpen: () => void }) {
  let todayIdx = 0;
  room.series.forEach((p, i) => {
    if (p.actual) todayIdx = i;
  });
  const data = room.series.map((p, i) => ({ label: p.label, actual: p.actual ? p.cash : null, projected: !p.actual || i === todayIdx ? p.cash : null }));
  const all = room.series.map((p) => p.cash).concat(room.operatingMinimum);
  const lo = Math.floor(Math.min(...all) - 4);
  const hi = Math.ceil(Math.max(...all) + 4);
  const selected = room.steps.find((s) => s.horizon === room.horizon);
  return (
    <Panel
      testId="cash-trajectory"
      eyebrow="Cash trajectory"
      title="Today → 7 → 15 → 30 days"
      right={<span className={cn("max-w-[420px] truncate text-[12px] font-semibold", toneClass(room.tone))} data-testid="cash-headline">{room.headline}</span>}
    >
      <div className="h-[330px] w-full cursor-pointer px-2 pb-2 pt-3" onClick={onOpen} title="Click to investigate projected cash" data-testid="cash-chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 18, right: 76, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="cashRoomFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="oklch(0.42 0.14 255)" stopOpacity={0.22} />
                <stop offset="100%" stopColor="oklch(0.42 0.14 255)" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="oklch(0.92 0.01 260)" strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={{ stroke: "oklch(0.9 0.01 260)" }} interval="preserveStartEnd" minTickGap={24} />
            <YAxis domain={[lo, hi]} ticks={Array.from({ length: 5 }, (_, i) => Math.round(lo + ((hi - lo) * i) / 4))} tick={AXIS} tickLine={false} axisLine={false} width={40} />
            <Tooltip formatter={(v: number, name: string) => [fmtCr(v), name === "actual" ? "Actual cash" : "Projected cash"]} contentStyle={{ fontSize: 12, borderRadius: 6 }} />
            <ReferenceLine y={room.operatingMinimum} stroke="oklch(0.58 0.2 25)" strokeDasharray="5 4" label={{ value: `Operating minimum ₹${room.operatingMinimum} Cr`, position: "insideBottomRight", fontSize: 10.5, fill: "oklch(0.5 0.2 25)" }} />
            <ReferenceLine x={room.series[todayIdx]?.label} stroke="oklch(0.55 0.02 260)" strokeDasharray="2 3" label={{ value: "Today", position: "top", fontSize: 10.5, fill: "oklch(0.4 0.03 260)" }} />
            {selected && selected.horizon !== "today" && <ReferenceLine x={selected.dayLabel} stroke="oklch(0.3 0.08 255)" strokeDasharray="4 3" />}
            <Area type="monotone" dataKey="actual" stroke="oklch(0.3 0.08 255)" strokeWidth={2.4} fill="url(#cashRoomFill)" dot={false} connectNulls isAnimationActive={false} />
            <Line type="monotone" dataKey="projected" stroke={room.tone === "bad" ? "oklch(0.58 0.2 25)" : "oklch(0.5 0.15 255)"} strokeWidth={2.4} strokeDasharray="6 4" dot={false} connectNulls isAnimationActive={false} />
            {room.steps
              .filter((s) => s.horizon !== "today")
              .map((s) => (
                <ReferenceDot key={s.horizon} x={s.dayLabel} y={s.closing} r={5} fill={s.headroom < 0 ? "oklch(0.58 0.2 25)" : "oklch(0.3 0.08 255)"} stroke="white" strokeWidth={2} label={{ value: `${s.label} · ${s.closing.toFixed(1)}`, position: "top", fontSize: 10.5, fill: "oklch(0.3 0.05 265)" }} />
              ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}

function HorizonBridge({ room, selected, onOpen }: { room: CashRoomData; selected: string | null; onOpen: (it: BridgeItem) => void }) {
  return (
    <Panel
      testId="cash-bridge"
      eyebrow="What moves cash"
      title={room.bridge.title}
      right={<span className="text-[11px] text-muted-foreground">₹ Cr</span>}
    >
      <div className="px-2 pb-1 pt-1">
        <WaterfallChart items={room.bridge.items} selectedId={selected} onSelect={onOpen} height={300} ariaLabel="Cash bridge for the selected horizon" />
      </div>
      <div className="flex items-center gap-2 border-t px-4 py-2 text-[12px]" data-testid="cash-capex">
        <span className="eyebrow">Capex &amp; other commitments</span>
        <Metric m={room.capex} fmt={(n) => fmtCr(n)} className="num-mono text-[13px] font-semibold" />
        {room.capex.value === null && <span className="text-muted-foreground">{room.capex.reason}</span>}
      </div>
    </Panel>
  );
}

const KIND_LABEL: Record<CashObligation["kind"], string> = { vendor: "Vendor", payroll: "Payroll", statutory: "Statutory", occupancy: "Rent & other" };
const KIND_KEY: Record<CashObligation["kind"], string> = { vendor: "obl_vendor", payroll: "obl_payroll", statutory: "obl_statutory", occupancy: "obl_other" };

function Obligations({ room, onOpen }: { room: CashRoomData; onOpen: (o: CashObligation) => void }) {
  return (
    <Panel testId="cash-obligations" eyebrow="Approaching" title="Obligations in the next 30 days" right={<span className="text-[11px] text-muted-foreground">Inside the selected horizon are highlighted</span>}>
      <ul>
        {room.obligations.map((o) => (
          <li key={o.id}>
            <button
              data-testid={`obligation-${o.id.replace(/\s+/g, "-")}`}
              disabled={!o.inHorizon}
              onClick={() => onOpen(o)}
              className={cn("press grid w-full grid-cols-[64px_minmax(0,1fr)_auto_84px] items-center gap-3 border-b px-4 py-2.5 text-left", o.inHorizon ? "hover:bg-[oklch(0.97_0.012_265)]" : "cursor-default opacity-55")}
            >
              <span className="num text-[12px] font-semibold text-foreground">{o.dayLabel}</span>
              <span className="min-w-0 truncate text-[13px] font-medium text-foreground">{o.label}</span>
              <Chip>{KIND_LABEL[o.kind]}</Chip>
              <span className="num-mono text-right text-[13px] font-semibold tone-bad">{fmtCr(-o.amount)}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-auto flex items-center justify-between border-t bg-[oklch(0.975_0.008_265)] px-4 py-2.5 text-[12px]" data-testid="obligation-totals">
        <span className="text-muted-foreground">Inside the selected horizon <b className="num-mono ml-1 text-foreground">{fmtCr(room.obligationTotals.inHorizon)}</b></span>
        <span className="text-muted-foreground">Next 30 days <b className="num-mono ml-1 text-foreground">{fmtCr(room.obligationTotals.all)}</b></span>
      </div>
    </Panel>
  );
}

function Spark({ values }: { values: number[] }) {
  const max = Math.max(...values.map((v) => Math.abs(v)), 1e-9);
  return (
    <span className="flex h-6 items-center gap-[2px]" aria-hidden>
      {values.map((v, i) => (
        <i key={i} className={cn("w-1.5 rounded-sm", v < 0 ? "bg-[oklch(0.58_0.2_25)]" : "bg-[oklch(0.58_0.15_155)]")} style={{ height: `${Math.max(12, (Math.abs(v) / max) * 100)}%` }} />
      ))}
    </span>
  );
}

function measureText(d: WcDriver): string {
  const m = d.measure;
  const sign = m.change > 0 ? "+" : m.change < 0 ? "−" : "";
  return m.unit === "days" ? `${m.value.toFixed(0)} days (${sign}${Math.abs(m.change).toFixed(1)})` : `${fmtCr(m.value)} (${sign}${Math.abs(m.change).toFixed(1)} Cr)`;
}

function Drivers({ room, selected, onOpen, onCreditors }: { room: CashRoomData; selected: string | null; onOpen: (d: WcDriver) => void; onCreditors: () => void }) {
  const max = Math.max(...room.drivers.map((r) => Math.abs(r.cashImpact)), 1);
  const bad = room.drivers.filter((d) => d.deteriorating);
  return (
    <Panel
      testId="cash-drivers"
      eyebrow="Working capital drivers"
      title="Cash absorbed and released"
      right={<span className={cn("num-mono text-[15px] font-semibold", room.netCashImpact < 0 ? "tone-bad" : "tone-good")} data-testid="wc-net-impact">{deltaCr(room.netCashImpact)}</span>}
    >
      <div className={cn("flex items-center gap-2 px-4 pt-3 text-[13px] font-semibold", room.netCashImpact < 0 ? "tone-bad" : "tone-good")} data-testid="wc-headline">
        {room.wcHeadline}
      </div>
      {bad.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-4 pb-1 pt-1.5 text-[12px] text-muted-foreground" data-testid="wc-deteriorating">
          <TrendingDown className="h-3.5 w-3.5 text-[oklch(0.55_0.2_25)]" /> Deteriorating:
          {bad.map((d) => (
            <Chip key={d.id}>{d.label}</Chip>
          ))}
        </div>
      )}
      <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_96px_minmax(0,1.1fr)_56px] gap-x-3 border-b px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        <span>Driver</span>
        <span>Absorbed ← → Released</span>
        <span className="text-right">Cash impact</span>
        <span>Measure</span>
        <span>6 mo</span>
      </div>
      <ul>
        {room.drivers.map((d) => {
          const pct = (Math.abs(d.cashImpact) / max) * 50;
          return (
            <li key={d.id} className="flex items-stretch border-b">
              <button
                data-testid={`driver-${d.id}`}
                aria-pressed={selected === d.id}
                onClick={() => onOpen(d)}
                className={cn("press grid min-w-0 flex-1 grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_96px_minmax(0,1.1fr)_56px] items-center gap-x-3 px-4 py-2.5 text-left hover:bg-[oklch(0.97_0.012_265)]", selected === d.id && "bg-[oklch(0.95_0.025_265)]")}
              >
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-medium text-foreground">{d.label}</span>
                  <span className="block truncate text-[10.5px] text-muted-foreground">{d.direction === "absorbed" ? "Absorbed" : "Released"} · {d.note}</span>
                </span>
                <span className="relative h-3.5">
                  <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
                  <span className={cn("absolute inset-y-0.5 rounded-sm", d.cashImpact < 0 ? "bg-[oklch(0.58_0.2_25)]" : "bg-[oklch(0.58_0.15_155)]")} style={d.cashImpact < 0 ? { right: "50%", width: `${pct}%` } : { left: "50%", width: `${pct}%` }} />
                </span>
                <span className={cn("num text-right text-[13px] font-semibold", toneClass(d.tone))}>{deltaCr(d.cashImpact)}</span>
                <span className="min-w-0">
                  <span className="block truncate text-[10.5px] text-muted-foreground">{d.measure.label}</span>
                  <span className={cn("num block truncate text-[12px] font-medium", d.deteriorating ? "tone-bad" : "text-foreground")}>{measureText(d)}</span>
                </span>
                <Spark values={d.monthly} />
              </button>
              {d.id === "creditors" && (
                <button data-testid="driver-open-creditors" onClick={onCreditors} title="Open Creditors Control" className="press flex items-center gap-1 border-l px-3 text-[11.5px] font-semibold text-primary hover:bg-[oklch(0.97_0.012_265)]">
                  Creditors <ArrowRight className="h-3 w-3" />
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

/**
 * Cash & Working Capital Control.
 * Cash trajectory → what moves cash → obligations → working-capital drivers → investigate → GL → voucher.
 */
export function CashRoom() {
  const { state, dispatch, openCashDriver, enterCreditors } = useCfo();
  const q = useCashRoom(state.horizon);
  const first = state.nodes[0];
  const selected = state.drawerOpen ? cashKeyOf(first) : null;
  const open = (key: string, label: string, amount: number | null) => {
    if (isCashKey(key)) openCashDriver(cashNode(key, label, amount));
  };
  return (
    <div data-testid="cash-room" className="@container">
      <WorkspaceHeader
        eyebrow="Liquidity"
        title="Cash & Working Capital Control"
        subtitle="What cash we have, what it will look like, what is consuming it, what is releasing it, and what is approaching."
        right={
          <>
            {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
            <div role="tablist" aria-label="Horizon" className="flex rounded bg-muted p-0.5">
              {HORIZONS.map((h) => (
                <button
                  key={h.id}
                  role="tab"
                  data-testid={`horizon-${h.id}`}
                  aria-selected={state.horizon === h.id}
                  onClick={() => dispatch({ type: "setHorizon", value: h.id })}
                  className={cn("press whitespace-nowrap rounded px-2.5 py-1 text-[12px] font-semibold", state.horizon === h.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
                >
                  {h.label}
                </button>
              ))}
            </div>
          </>
        }
      />
      <Boundary query={q} skeleton={<div className="space-y-4 p-4"><Skeleton className="h-16 w-full" /><Skeleton className="h-[330px] w-full" /></div>} emptyTitle="No cash projection for this selection">
        {(room) => (
          <>
            <Strip room={room} horizon={state.horizon} onHorizon={(h) => dispatch({ type: "setHorizon", value: h })} />
            <div className="space-y-4 p-4">
              <DecisionStrip room={room} onOpen={open} />
              <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] gap-4 @max-[1500px]:grid-cols-1">
                <Trajectory room={room} onOpen={() => open("projected", "Forecast Closing Cash", room.forecastClosing)} />
                <HorizonBridge room={room} selected={selected} onOpen={(it) => open(it.id, it.label, it.value)} />
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] gap-4 @max-[1250px]:grid-cols-1">
                <Obligations
                  room={room}
                  onOpen={(o) => {
                    const item = room.bridge.items.find((i) => i.id === KIND_KEY[o.kind]);
                    if (item) open(item.id, item.label, item.value);
                  }}
                />
                <Drivers room={room} selected={selected} onOpen={(d) => open(d.id, d.label, d.cashImpact)} onCreditors={() => enterCreditors()} />
              </div>
              <div className="text-[11px] text-muted-foreground">{DASH} marks figures with no source yet. Capex and other commitments are not estimated.</div>
            </div>
          </>
        )}
      </Boundary>
    </div>
  );
}
