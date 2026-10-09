import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FOOT_TOLERANCE, WaterfallChart, footCheck, waterfallGeometry } from "./WaterfallChart";
import type { BridgeItem } from "@/types/cfo";

const item = (id: string, kind: "total" | "delta", value: number): BridgeItem => ({ id, label: id, kind, value, tone: value < 0 ? "bad" : "good", family: "margin" }) as BridgeItem;

const POSITIVE = [item("revenue", "total", 611.95), item("cost", "delta", -400.67), item("margin", "total", 211.28), item("exp", "delta", -118.4), item("ebitda", "total", 92.88)];
const NEGATIVE = [item("revenue", "total", 100), item("cost", "delta", -90), item("margin", "total", 10), item("exp", "delta", -22.8), item("ebitda", "total", -12.8)];
const MIXED = [item("open", "total", 50), item("up", "delta", 20), item("down", "delta", -90), item("close", "total", -20)];

function bars() {
  // every bar is a rect inside <g data-testid="bar-<id>">; the first rect is the hover band, the second the bar itself
  return (id: string) => {
    const rects = screen.getByTestId(`bar-${id}`).querySelectorAll("rect");
    const r = rects[1];
    return { y: Number(r.getAttribute("y")), h: Number(r.getAttribute("height")), fill: r.getAttribute("fill"), negative: r.getAttribute("data-negative-total") };
  };
}
const zeroY = () => Number(screen.getByTestId("waterfall-zero-line").getAttribute("y1"));
const mount = (items: BridgeItem[]) => render(<WaterfallChart items={items} selectedId={null} onSelect={() => undefined} ariaLabel="t" />);

describe("waterfall geometry (C-01)", () => {
  it("measures totals from a true zero baseline and never truncates", () => {
    const g = waterfallGeometry(POSITIVE);
    expect(g.domMin).toBe(0);
    expect(g.truncated).toBe(false);
    for (const s of g.spans.filter((x) => x.it.kind === "total")) {
      expect(s.lo).toBe(0);
      expect(s.hi).toBe(s.it.value);
    }
  });

  it("includes zero and the negative extent for a loss", () => {
    const g = waterfallGeometry(NEGATIVE);
    expect(g.domMin).toBeLessThan(-12.8);
    const close = g.spans.find((s) => s.it.id === "ebitda")!;
    expect([close.lo, close.hi]).toEqual([-12.8, 0]);
  });
});

describe("waterfall rendering (C-01, C-02)", () => {
  it("draws total bar heights in proportion to their values from the zero line", () => {
    mount(POSITIVE);
    const b = bars();
    const rev = b("revenue");
    const ebitda = b("ebitda");
    const margin = b("margin");
    expect(rev.y + rev.h).toBeCloseTo(zeroY(), 3);
    expect(rev.h / ebitda.h).toBeCloseTo(611.95 / 92.88, 1);
    expect(rev.h / margin.h).toBeCloseTo(611.95 / 211.28, 1);
    expect(screen.queryByTestId("axis-truncated")).toBeNull();
    expect(screen.queryByTestId("foot-warning")).toBeNull();
  });

  it("draws a negative closing total DOWNWARD from zero in the bad colour", () => {
    mount(NEGATIVE);
    const loss = bars()("ebitda");
    expect(loss.y).toBeCloseTo(zeroY(), 3); // starts at the zero line and hangs below it
    expect(loss.h).toBeGreaterThan(0);
    expect(loss.negative).toBe("true");
    expect(loss.fill).toMatch(/0\.58 0\.2 25/);
    expect(bars()("revenue").fill).not.toMatch(/0\.58 0\.2 25/);
    expect(bars()("revenue").negative).toBeNull();
  });

  it("handles a mixed series: the positive opening total above zero, the negative closing total below", () => {
    mount(MIXED);
    const open = bars()("open");
    const close = bars()("close");
    expect(open.y + open.h).toBeCloseTo(zeroY(), 3);
    expect(close.y).toBeCloseTo(zeroY(), 3);
    expect(open.h / close.h).toBeCloseTo(50 / 20, 1);
  });
});

describe("foot-check (C-03)", () => {
  it("passes when the steps add to the closing totals within 0.01", () => {
    expect(footCheck(POSITIVE)).toEqual([]);
    expect(footCheck(NEGATIVE)).toEqual([]);
    expect(footCheck(MIXED)).toEqual([]);
    // the rounding drift the adapters produce (57.87 vs running sum 57.88) is inside the tolerance
    expect(footCheck([item("a", "total", 10), item("b", "delta", 47.88), item("c", "total", 57.87)])).toEqual([]);
    expect(FOOT_TOLERANCE).toBe(0.01);
  });

  it("reports a total the steps do not add up to", () => {
    const bad = [item("a", "total", 100), item("b", "delta", -30), item("c", "total", 75)];
    const f = footCheck(bad);
    expect(f).toHaveLength(1);
    expect(f[0]).toMatchObject({ id: "c", expected: 70, actual: 75 });
  });

  it("shows a visible 'does not foot' marker only when it does not foot", () => {
    const { unmount } = mount([item("a", "total", 100), item("b", "delta", -30), item("c", "total", 75)]);
    expect(screen.getByTestId("foot-warning")).toHaveTextContent(/does not foot/i);
    unmount();
    mount(POSITIVE);
    expect(screen.queryByTestId("foot-warning")).toBeNull();
  });
});
