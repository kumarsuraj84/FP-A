import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";

// The default Command Center data source is REAL (live APIs). The existing suites exercise the demo service, so they opt in explicitly;
// the live adapter has its own tests that build it directly.
vi.stubEnv("VITE_CFO_DATA", "mock");
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  try {
    sessionStorage.clear();
  } catch {
    /* ignore */
  }
});

// jsdom has no ResizeObserver (Recharts' ResponsiveContainer needs one)
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
