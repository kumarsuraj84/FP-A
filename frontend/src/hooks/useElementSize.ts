import { useEffect, useRef, useState } from "react";

/** Measures an element's content box so SVG charts can lay out at true pixel size. */
export function useElementSize<T extends HTMLElement>(initialWidth = 800) {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: initialWidth, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize({ width: Math.max(0, Math.round(el.clientWidth)), height: Math.round(el.clientHeight) });
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}
