import { useState } from "react";
import { Navigate, useRouterState } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useStoreWorkspace } from "@/api/hooks";
import { useCfo } from "@/context/CfoContext";
import { fmtCr, fmtPct } from "@/lib/format";
import { movementIdOf, movementNode, storeIdOf } from "@/lib/profitNodes";
import { cn } from "@/lib/utils";
import { QUADRANT_META, type BenchmarkCell, type BenchmarkRow, type StoreWorkspace, type TrajectoryMetric } from "@/types/profitability";
import { Boundary, Skeleton, StaleChip, toneClass } from "../common";
import { Chip, Panel, StripCell, deltaCr } from "../panels";
import { WaterfallChart } from "../WaterfallChart";
import { QUADRANT_COLOR } from "./QuadrantMap";

const NAVY = "oklch(0.3 0.08 255)";
const AXIS = { fontSize: 10.5, fill: "oklch(0.5 0.02 260)" };

function StoreHeader({ ws }: { ws: StoreWorkspace }) {
  return (
    <div className="grid grid-cols-5 divide-x border-b bg-card @max-[1100px]:grid-cols-3 @max-[1100px]:divide-y" data-testid="store-kpis">
      {ws.kpis.map((k) => (
        <StripCell
          key={k.id}
          testId={`kpi-${k.id}`}
          label={k.label}
          value={k.unit === "pct" ? fmtPct(k.value) : fmtCr(k.value)}
          variance={k.unit === "pct" ? `${k.variance < 0 ? "−" : k.variance > 0 ? "+" : ""}${Math.abs(k.variance).toFixed(2)} pp` : deltaCr(k.variance)}
          tone={k.tone}
          sub={k.sub}
        />
      ))}
    </div>
  );
}

function Bridge({ ws, selected, onSelect }: { ws: StoreWorkspace; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <Panel
      testId="store-bridge"
      eyebrow="Store P&L bridge"
      title={ws.bridge.title}
      right={<span className="text-[11px] text-muted-foreground">₹ Lakh · every bar opens its drivers</span>}
    >
      <div className="px-2 pb-2 pt-1">
        <WaterfallChart items={ws.bridge.items} unit="lakh" selectedId={selected} onSelect={(it) => onSelect(it.id)} height={360} ariaLabel={`${ws.store.name} contribution bridge`} />
      </div>
    </Panel>
  );
}

const TRAJ_FMT = (v: number) => (Math.abs(v) < 1 ? `${(v * 100).toFixed(0)} L` : v.toFixed(1));

function Trajectory({ ws }: { ws: StoreWorkspace }) {
  const [metric, setMetric] = useState<TrajectoryMetric["id"]>("contribution");
  const t = ws.trajectory.find((x) => x.id === metric)!;
  const data = t.months.map((m) => ({ month: m.month, budget: m.budget, actual: m.actual, forecast: m.forecast }));
  const lastActual = t.months.filter((m) => m.actual !== null).slice(-1)[0]?.month;
  return (
    <Panel
      testId="store-trajectory"
      eyebrow="Monthly trajectory · FY 2026-27"
      title="Actual vs AOP, with forecast"
      right={
        <div role="tablist" aria-label="Metric" className="flex rounded bg-muted p-0.5">
          {ws.trajectory.map((m) => (
            <button
              key={m.id}
              role="tab"
              data-testid={`traj-${m.id}`}
              aria-selected={metric === m.id}
              onClick={() => setMetric(m.id)}
              className={cn("press whitespace-nowrap rounded px-2.5 py-1 text-[12px] font-semibold", metric === m.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
            >
              {m.id === "gm" ? "GM" : m.label}
            </button>
          ))}
        </div>
      }
    >
      <div className={cn("px-4 pt-3 text-[13px] font-semibold", toneClass(t.gap < 0 ? "bad" : "good"))} data-testid="traj-headline">
        Landing {fmtCr(t.landing)} vs AOP {fmtCr(t.budgetFy)} ({deltaCr(t.gap)})
      </div>
      <div className="h-[250px] px-2 pb-2 pt-1" data-testid="traj-chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 12, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="oklch(0.92 0.01 260)" strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="month" tick={AXIS} tickLine={false} axisLine={{ stroke: "oklch(0.9 0.01 260)" }} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} tickFormatter={TRAJ_FMT} domain={["auto", "auto"]} />
            <Tooltip formatter={(v: number, name: string) => [fmtCr(v), name === "budget" ? ws.comparisonLabel.replace("vs ", "") : name === "actual" ? "Actual" : "Forecast"]} contentStyle={{ fontSize: 12, borderRadius: 6 }} />
            {lastActual && <ReferenceLine x={lastActual} stroke="oklch(0.55 0.02 260)" strokeDasharray="2 3" label={{ value: "Today", position: "top", fontSize: 10.5, fill: "oklch(0.4 0.03 260)" }} />}
            <Line type="monotone" dataKey="budget" stroke="oklch(0.66 0.03 260)" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="actual" stroke={NAVY} strokeWidth={2.6} dot={{ r: 2.5 }} connectNulls isAnimationActive={false} />
            <Line type="monotone" dataKey="forecast" stroke="oklch(0.58 0.15 255)" strokeWidth={2.4} strokeDasharray="6 4" dot={false} connectNulls isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center gap-4 border-t px-4 py-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><i className="h-0.5 w-4 bg-[oklch(0.66_0.03_260)]" /> AOP</span>
        <span className="flex items-center gap-1"><i className="h-0.5 w-4" style={{ background: NAVY }} /> Actual</span>
        <span className="flex items-center gap-1"><i className="h-0.5 w-4 border-t-2 border-dashed border-[oklch(0.58_0.15_255)]" /> Forecast</span>
      </div>
    </Panel>
  );
}

function ExpensePressure({ ws, onSelect, selected }: { ws: StoreWorkspace; onSelect: (id: string) => void; selected: string | null }) {
  const worst = Math.max(...ws.expenses.map((e) => Math.abs(e.overPct)), 1);
  return (
    <Panel testId="expense-pressure" eyebrow="Expense pressure" title="Operating costs ranked by adverse variance" right={<span className="text-[11px] text-muted-foreground">{ws.comparisonLabel}</span>}>
      <ul>
        {ws.expenses.map((e, i) => (
          <li key={e.id}>
            <button
              data-testid={`expense-${e.id}`}
              aria-pressed={selected === e.id}
              onClick={() => onSelect(e.id)}
              className={cn("press grid w-full grid-cols-[22px_minmax(0,1.6fr)_minmax(0,1fr)_64px_84px] items-center gap-x-3 border-b px-4 py-2 text-left hover:bg-[oklch(0.97_0.012_265)]", selected === e.id && "bg-[oklch(0.95_0.025_265)]")}
            >
              <span className="num text-[11px] text-muted-foreground">{i + 1}</span>
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-medium text-foreground">{e.label}</span>
                <span className="num block text-[10.5px] text-muted-foreground">{fmtCr(e.actual)} vs {fmtCr(e.budget)} · {e.pctOfRevenue.toFixed(1)}% of rev.</span>
              </span>
              <span className="relative h-3">
                <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
                <span
                  className={cn("absolute inset-y-0.5 rounded-sm", e.overPct > 0 ? "bg-[oklch(0.58_0.2_25)]" : "bg-[oklch(0.58_0.15_155)]")}
                  style={e.overPct > 0 ? { left: "50%", width: `${(Math.abs(e.overPct) / worst) * 50}%` } : { right: "50%", width: `${(Math.abs(e.overPct) / worst) * 50}%` }}
                />
              </span>
              <span className={cn("num text-right text-[12px] font-semibold", toneClass(e.tone))}>{e.overPct > 0 ? "+" : e.overPct < 0 ? "−" : ""}{Math.abs(e.overPct).toFixed(1)}%</span>
              <span className={cn("num text-right text-[13px] font-semibold", toneClass(e.tone))}>{deltaCr(e.impact)}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="px-4 py-2 text-[11px] text-muted-foreground">Overspend shown in red to the right. The 4-Wall EBITDA impact is in the last column.</div>
    </Panel>
  );
}

function Cell({ c, unit }: { c: BenchmarkCell; unit: string }) {
  return (
    <td className="px-2 py-2 text-right">
      <div className="num text-[12.5px] font-medium">{c.value.toFixed(1)}{unit}</div>
      <div className={cn("num text-[10.5px] font-semibold", toneClass(c.tone))}>{c.delta > 0 ? "+" : c.delta < 0 ? "−" : ""}{Math.abs(c.delta).toFixed(1)} pp</div>
    </td>
  );
}

function Comparison({ ws }: { ws: StoreWorkspace }) {
  const b = ws.benchmarks;
  const cols: [keyof Pick<BenchmarkRow, "company" | "zone" | "region" | "cluster" | "comparable">, string][] = [
    ["company", "Company"],
    ["zone", b.labels.zone],
    ["region", b.labels.region],
    ["cluster", b.labels.cluster],
    ["comparable", `Comparable (${b.comparableCount})`],
  ];
  return (
    <Panel testId="network-comparison" eyebrow="Network comparison" title={`${ws.store.name} vs the network`} right={<span className="text-[11px] text-muted-foreground">Difference is store minus benchmark</span>}>
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b text-[10.5px] uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-2 text-left font-semibold">Metric</th>
            <th className="px-2 py-2 text-right font-semibold text-foreground">{ws.store.name}</th>
            {cols.map(([k, label]) => (
              <th key={k} className="max-w-[110px] truncate px-2 py-2 text-right font-semibold" title={label}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {b.rows.map((r) => (
            <tr key={r.id} data-testid={`bench-${r.id}`} className="border-b">
              <td className="px-4 py-2 font-medium">{r.label}</td>
              <td className="num px-2 py-2 text-right text-[13px] font-semibold">{r.store.toFixed(1)}%</td>
              {cols.map(([k]) => (
                <Cell key={k} c={r[k]} unit="%" />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Why({ ws, onSelect, selected }: { ws: StoreWorkspace; onSelect: (id: string) => void; selected: string | null }) {
  const max = Math.max(...ws.why.drivers.map((d) => Math.abs(d.impact)), 1e-9);
  return (
    <Panel testId="why-gap" eyebrow="Why underperforming" title={ws.why.headline} right={<span className="text-[11px] text-muted-foreground">{ws.comparisonLabel}</span>}>
      <ul>
        {ws.why.drivers.map((d) => (
          <li key={d.id}>
            <button
              data-testid={`why-${d.id}`}
              aria-pressed={selected === d.id}
              onClick={() => onSelect(d.id)}
              className={cn("press grid w-full grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_84px] items-center gap-x-3 border-b px-4 py-2.5 text-left hover:bg-[oklch(0.97_0.012_265)]", selected === d.id && "bg-[oklch(0.95_0.025_265)]")}
            >
              <span className="min-w-0">
                <span className="flex items-baseline gap-2">
                  <span className="truncate text-[13px] font-medium text-foreground">{d.label}</span>
                  <span className="num shrink-0 text-[10.5px] font-semibold text-muted-foreground">{d.share >= 0 ? `${Math.round(d.share * 100)}% of gap` : `offsets ${Math.round(-d.share * 100)}%`}</span>
                </span>
                <span className="block text-[11px] leading-snug text-muted-foreground">{d.note}</span>
              </span>
              <span className="relative h-3">
                <span className={cn("absolute inset-y-0.5 left-0 rounded-sm", d.impact < 0 ? "bg-[oklch(0.58_0.2_25)]" : "bg-[oklch(0.58_0.15_155)]")} style={{ width: `${Math.max(3, (Math.abs(d.impact) / max) * 100)}%` }} />
              </span>
              <span className={cn("num text-right text-[13px] font-semibold", toneClass(d.tone))}>{deltaCr(d.impact)}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="px-4 py-2 text-[11px] text-muted-foreground">Drivers are supplied by the service and add up to the 4-Wall EBITDA gap. Select one to see its accounts.</div>
    </Panel>
  );
}

/** Store workspace: header strip → P&L bridge → why / expense pressure → trajectory / network comparison. */
export function StoreWorkspacePage() {
  const { state, ready, resolving, back, openMovement } = useCfo();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const storeNodeInPath = state.nodes.find((n) => n.dim === "Store");
  const storeId = storeIdOf(storeNodeInPath);
  const q = useStoreWorkspace(storeId);
  const moveNode = state.nodes.find((n) => n.dim === "Movement");
  const selected = state.drawerOpen ? movementIdOf(moveNode) : null;
  const missing = ready && !resolving && pathname === "/profitability/store" && !storeId;
  if (missing) return <Navigate to="/profitability" />;
  const ws = q.data?.data;
  const open = (id: string) => {
    const m = ws?.movements.find((x) => x.id === id);
    if (m) openMovement(movementNode(m));
  };

  return (
    <div data-testid="store-workspace" className="@container">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-5 py-3">
        <div className="min-w-0">
          <button data-testid="store-back" onClick={back} className="press mb-1 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[12px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> Store Profitability
          </button>
          <div className="eyebrow">{ws ? `${ws.store.zone} zone · ${ws.store.region} · ${ws.store.cluster}` : "Store"}</div>
          <h1 className="truncate text-[20px] font-semibold tracking-tight text-foreground" data-testid="store-title">{ws?.store.name ?? storeNodeInPath?.label ?? "Store"}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span data-testid="store-demo-chip" className="rounded bg-[oklch(0.96_0.06_85)] px-2 py-0.5 text-[11px] font-semibold text-[oklch(0.38_0.09_70)]">Demo data - not real</span>
          {ws && <Chip color={QUADRANT_COLOR[ws.store.quadrant]}>{QUADRANT_META[ws.store.quadrant].label}</Chip>}
          {ws && <Chip>{ws.store.format}</Chip>}
          {q.data?.status === "stale" && <StaleChip reason={q.data.reason} />}
        </div>
      </div>
      <Boundary query={q} skeleton={<div className="space-y-4 p-4"><Skeleton className="h-16 w-full" /><Skeleton className="h-[360px] w-full" /></div>} emptyTitle="No data for this store">
        {(w) => (
          <>
            <StoreHeader ws={w} />
            <div className="space-y-4 p-4">
              <Bridge ws={w} selected={selected} onSelect={open} />
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] gap-4 @max-[1150px]:grid-cols-1">
                <Why ws={w} onSelect={open} selected={selected} />
                <ExpensePressure ws={w} onSelect={open} selected={selected} />
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-4 @max-[1150px]:grid-cols-1">
                <Trajectory ws={w} />
                <Comparison ws={w} />
              </div>
            </div>
          </>
        )}
      </Boundary>
    </div>
  );
}
