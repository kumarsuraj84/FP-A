import { useMemo, useState } from "react";
import { useElementSize } from "@/hooks/useElementSize";
import type { BridgeItem } from "@/types/cfo";

interface Props {
  items: BridgeItem[];
  selectedId: string | null;
  onSelect: (item: BridgeItem) => void;
  height?: number;
  ariaLabel: string;
}

const M = { l: 54, r: 14, t: 34, b: 50 };
const NAVY = "oklch(0.3 0.08 255)";
const COLOR = { good: "oklch(0.58 0.15 155)", bad: "oklch(0.58 0.2 25)", warn: "oklch(0.72 0.15 75)", neutral: "oklch(0.62 0.02 260)" };

function wrap(label: string, max = 13): string[] {
  const words = label.split(" ");
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > max && cur) {
      lines.push(cur);
      cur = w;
    } else cur = (cur + " " + w).trim();
  }
  if (cur) lines.push(cur);
  return lines.slice(0, 3);
}

export function WaterfallChart({ items, selectedId, onSelect, height = 340, ariaLabel }: Props) {
  const [ref, size] = useElementSize<HTMLDivElement>(900);
  const [hover, setHover] = useState<string | null>(null);
  const W = Math.max(320, size.width);
  const H = height;

  const geo = useMemo(() => {
    let run = 0;
    const spans = items.map((it) => {
      if (it.kind === "total") {
        run = it.value;
        return { it, lo: it.value, hi: it.value, from: null as number | null };
      }
      const a = run;
      run += it.value;
      return { it, lo: Math.min(a, run), hi: Math.max(a, run), from: a };
    });
    const lo = Math.min(...spans.map((s) => s.lo));
    const hi = Math.max(...spans.map((s) => s.hi));
    const pad = (hi - lo || 1) * 0.28;
    const domMin = lo - pad;
    const domMax = hi + pad * 0.5;
    return { spans, domMin, domMax };
  }, [items]);

  const plotW = W - M.l - M.r;
  const plotH = H - M.t - M.b;
  const y = (v: number) => M.t + (1 - (v - geo.domMin) / (geo.domMax - geo.domMin)) * plotH;
  const band = plotW / items.length;
  const barW = Math.min(76, band * 0.58);
  const ticks = Array.from({ length: 5 }, (_, i) => geo.domMin + ((geo.domMax - geo.domMin) * i) / 4);
  const startTotal = items.find((i) => i.kind === "total")?.value ?? 1;

  const hovered = geo.spans.find((s) => s.it.id === hover);
  const hoverIdx = hovered ? items.findIndex((i) => i.id === hovered.it.id) : -1;
  const tipX = hoverIdx >= 0 ? Math.min(Math.max(M.l + band * hoverIdx + band / 2, 110), W - 110) : 0;
  const tipY = hovered ? y(hovered.hi) : 0;

  const colorOf = (it: BridgeItem) => (it.kind === "total" ? NAVY : COLOR[it.tone]);

  return (
    <div ref={ref} className="relative w-full" style={{ height: H }} data-testid="waterfall">
      <svg width={W} height={H} role="group" aria-label={ariaLabel} className="block select-none">
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke="oklch(0.92 0.01 260)" strokeDasharray={i === 0 ? undefined : "2 4"} />
            <text x={M.l - 8} y={y(t) + 3.5} textAnchor="end" fontSize={10.5} fill="oklch(0.55 0.02 260)" className="num">
              {t.toFixed(t > 20 ? 0 : 1)}
            </text>
          </g>
        ))}
        {geo.spans.map((s, i) => {
          const cx = M.l + band * i + band / 2;
          const x = cx - barW / 2;
          const isTotal = s.it.kind === "total";
          const top = isTotal ? y(s.it.value) : y(s.hi);
          const bottom = isTotal ? y(geo.domMin) : y(s.lo);
          const h = Math.max(isTotal ? 2 : 3, bottom - top);
          const selected = selectedId === s.it.id;
          const dim = selectedId !== null && !selected;
          const isHover = hover === s.it.id;
          const neg = !isTotal && s.it.value < 0;
          const label = isTotal ? s.it.value.toFixed(2) : `${s.it.value < 0 ? "−" : "+"}${Math.abs(s.it.value).toFixed(2)}`;
          const next = geo.spans[i + 1];
          const endLevel = isTotal ? s.it.value : (s.from ?? 0) + s.it.value;
          return (
            <g
              key={s.it.id}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={`${s.it.label} ${s.it.value.toFixed(2)} crore. Click to investigate.`}
              data-testid={`bar-${s.it.id}`}
              onClick={() => onSelect(s.it)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(s.it);
                }
              }}
              onMouseEnter={() => setHover(s.it.id)}
              onMouseLeave={() => setHover((h0) => (h0 === s.it.id ? null : h0))}
              onFocus={() => setHover(s.it.id)}
              onBlur={() => setHover((h0) => (h0 === s.it.id ? null : h0))}
              className="cursor-pointer outline-none"
              opacity={dim ? 0.42 : 1}
              style={{ transition: "opacity .15s" }}
            >
              <rect x={cx - band / 2} y={M.t - 18} width={band} height={plotH + 18} fill={isHover ? "oklch(0.96 0.015 260)" : "transparent"} rx={3} />
              <rect
                x={x}
                y={top}
                width={barW}
                height={h}
                rx={2}
                fill={colorOf(s.it)}
                stroke={selected ? "oklch(0.2 0.05 265)" : "none"}
                strokeWidth={selected ? 2 : 0}
              />
              <text
                x={cx}
                y={neg ? top + h + 14 : top - 7}
                textAnchor="middle"
                fontSize={12}
                fontWeight={isTotal || selected ? 700 : 600}
                fill={isTotal ? "oklch(0.2 0.05 265)" : s.it.value < 0 ? "oklch(0.5 0.2 25)" : "oklch(0.42 0.14 155)"}
                className="num"
              >
                {label}
              </text>
              {wrap(s.it.label).map((ln, li) => (
                <text
                  key={li}
                  x={cx}
                  y={H - M.b + 18 + li * 13}
                  textAnchor="middle"
                  fontSize={11.5}
                  fontWeight={selected ? 700 : 500}
                  fill={selected ? "oklch(0.2 0.05 265)" : "oklch(0.4 0.03 265)"}
                >
                  {ln}
                </text>
              ))}
              {next && <line x1={x + barW} x2={M.l + band * (i + 1) + band / 2 - Math.min(76, band * 0.58) / 2} y1={y(endLevel)} y2={y(endLevel)} stroke="oklch(0.7 0.02 260)" strokeDasharray="3 3" pointerEvents="none" />}
            </g>
          );
        })}
      </svg>
      {hovered && (
        <div
          role="tooltip"
          data-testid="waterfall-tooltip"
          className="pointer-events-none absolute z-10 w-[210px] -translate-x-1/2 -translate-y-full rounded-md border bg-popover px-3 py-2 text-xs shadow-elevated"
          style={{ left: tipX, top: Math.max(tipY - 30, 52) }}
        >
          <div className="font-semibold text-foreground">{hovered.it.label}</div>
          <div className="num mt-0.5 text-[15px] font-bold" style={{ color: hovered.it.kind === "total" ? NAVY : hovered.it.value < 0 ? "oklch(0.5 0.2 25)" : "oklch(0.42 0.14 155)" }}>
            {`${hovered.it.value < 0 ? "−" : hovered.it.kind === "delta" ? "+" : ""}₹${Math.abs(hovered.it.value).toFixed(2)} Cr`}
          </div>
          {hovered.it.kind === "delta" && <div className="text-muted-foreground">{((hovered.it.value / startTotal) * 100).toFixed(1)}% of opening level</div>}
          <div className="mt-1 text-[11px] font-medium text-primary">Click to investigate →</div>
        </div>
      )}
    </div>
  );
}
